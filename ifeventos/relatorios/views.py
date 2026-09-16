from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.views.generic import ListView, View
from django.shortcuts import render
from django.shortcuts import get_object_or_404
from eventos.metadados import campos as campos_metadados, colunas_selecionadas
from eventos.models import Inscricao, Atividade


# Campos ordenáveis do relatório: chave do cabeçalho -> campos do ORM.
ORDENACAO = {
    "participante": ("participante__first_name", "participante__last_name"),
    "atividade": ("atividade__titulo",),
    "local": ("atividade__local",),
    "evento": ("atividade__evento__title",),
    "confirmada": ("confirmada",),
    "certificado": ("certificado_emitido",),
}


class _ColunasMetadadosMixin:
    """Contexto das colunas extras (metadados configuráveis) dos relatórios.

    `colunas_disponiveis` traz, por campo, um link que liga/desliga a coluna
    preservando os demais parâmetros da query (`q`, `ordenar`, `dir`…). O mesmo
    vale para `colunas_opcionais`: colunas fixas que a view deixa ocultar
    (`?ocultar=evento`), como o Evento num relatório de um evento só.
    """

    def colunas_opcionais(self):
        """Colunas fixas ocultáveis desta view: (chave, rótulo). Vazio por padrão."""
        return ()

    def _ocultas(self):
        """Chaves de `colunas_opcionais()` escondidas na URL (validadas)."""
        permitidas = {chave for chave, _ in self.colunas_opcionais()}
        return {chave for chave in self.request.GET.getlist("ocultar") if chave in permitidas}

    def _selecionadas(self):
        """Colunas de metadados escolhidas na URL (na ordem da configuração)."""
        return colunas_selecionadas(self.request.GET)

    @staticmethod
    def _dados_metadados(participante):
        obj = getattr(participante, "metadados", None)
        return dict(obj.dados) if obj else {}

    def _urls_exportacao(self):
        """Links de exportação preservando a query atual (filtros + colunas)."""
        urls = []
        for formato, rotulo in (("csv", "CSV"), ("xlsx", "Excel"), ("pdf", "PDF")):
            params = self.request.GET.copy()
            params["export"] = formato
            urls.append({"rotulo": rotulo, "url": "?" + params.urlencode()})
        return urls

    def _urls_colunas_opcionais(self):
        """Links que ligam/desligam as colunas fixas ocultáveis."""
        ocultas = self._ocultas()
        urls = []
        for chave, rotulo in self.colunas_opcionais():
            novas = [k for k in ocultas if k != chave]
            if chave not in ocultas:
                novas.append(chave)
            params = self.request.GET.copy()
            params.pop("page", None)
            if novas:
                params.setlist("ocultar", novas)
            else:
                params.pop("ocultar", None)
            urls.append({
                "chave": chave,
                "rotulo": rotulo,
                "ativo": chave not in ocultas,
                "url": "?" + params.urlencode(),
            })
        return urls

    def metadados_colunas(self):
        selecionadas = self._selecionadas()
        chaves = [c["chave"] for c in selecionadas]
        ordem = [c["chave"] for c in campos_metadados()]

        disponiveis = []
        for campo in campos_metadados():
            novas = list(chaves)
            if campo["chave"] in novas:
                novas.remove(campo["chave"])
            else:
                novas.append(campo["chave"])
            novas = [k for k in ordem if k in set(novas)]

            params = self.request.GET.copy()
            params.pop("page", None)
            params.setlist("campos", novas)
            disponiveis.append({
                "chave": campo["chave"],
                "rotulo": campo["rotulo"],
                "ativo": campo["chave"] in chaves,
                "url": "?" + params.urlencode(),
            })

        return {
            "campos_metadados": campos_metadados(),
            "colunas_metadados": selecionadas,
            "colunas_disponiveis": disponiveis,
            "colunas_opcionais": self._urls_colunas_opcionais(),
            "campos_selecionados_str": ",".join(chaves),
            "export_urls": self._urls_exportacao(),
        }


class RelatorioInscricoesView(_ColunasMetadadosMixin, LoginRequiredMixin, ListView):
    model = Inscricao
    template_name = "relatorios/inscricoes.html"
    context_object_name = "inscricoes"
    paginate_by = 20  # Paginação: Exibe 20 inscrições por página

    def colunas_opcionais(self):
        """O Evento é o mesmo para todas as linhas, então dá para ocultá-lo."""
        return (("evento", "Evento"),)

    # -- template --------------------------------------------------------------

    def get_template_names(self):
        """A busca (AJAX) troca só o trecho de resultados, não a página inteira."""
        if self.request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return ["relatorios/_resultado_inscricoes.html"]
        return [self.template_name]

    # -- filtros (query string) ------------------------------------------------

    def _evento_id(self):
        """Evento do relatório — vem sempre da URL (/relatorio_inscricoes/<id>/)."""
        return self.kwargs.get("evento_id")

    def _busca(self):
        """Texto livre digitado na busca (`?q=`)."""
        return (self.request.GET.get("q") or "").strip()

    def _aplicar_busca(self, queryset, termo):
        """Busca livre no servidor: cada palavra precisa casar em algum campo.

        Campos: nome/sobrenome, e-mail, título da atividade e os metadados
        configurados (ex.: matrícula, curso, turma). No servidor porque a lista
        pagina (20/página) — filtrar no cliente mentiria.
        """
        if not termo:
            return queryset
        chaves = [c["chave"] for c in campos_metadados()]
        for palavra in termo.split():
            condicao = (
                Q(participante__first_name__icontains=palavra)
                | Q(participante__last_name__icontains=palavra)
                | Q(participante__email__icontains=palavra)
                | Q(atividade__titulo__icontains=palavra)
            )
            for chave in chaves:
                condicao |= Q(
                    **{f"participante__metadados__dados__{chave}__icontains": palavra}
                )
            queryset = queryset.filter(condicao)
        return queryset

    def get_queryset(self):
        """Inscrições do evento, já com a busca (`?q=`) e a ordem (`?ordenar=`)."""
        queryset = Inscricao.objects.select_related(
            "participante", "participante__metadados", "atividade", "atividade__evento"
        )

        evento_id = self._evento_id()
        if evento_id:
            queryset = queryset.filter(atividade__evento_id=evento_id)

        queryset = self._aplicar_busca(queryset, self._busca())

        campos = ORDENACAO.get(self.request.GET.get("ordenar"))
        if campos:
            prefixo = "-" if self.request.GET.get("dir") == "desc" else ""
            queryset = queryset.order_by(*[prefixo + campo for campo in campos], "id")
        else:
            queryset = queryset.order_by("id")

        return queryset

    def _colunas(self):
        """Cabeçalhos ordenáveis: rótulo, link que alterna a direção e aria-sort."""
        atual = self.request.GET.get("ordenar")
        direcao_atual = self.request.GET.get("dir")
        ocultas = self._ocultas()
        colunas = []
        for chave, rotulo in (
            ("participante", "Participante"),
            ("atividade", "Atividade"),
            ("local", "Local"),
            ("evento", "Evento"),
            ("confirmada", "Confirmada"),
            ("certificado", "Certificado"),
        ):
            if chave in ocultas:
                continue
            if chave == atual:
                proxima = "desc" if direcao_atual != "desc" else "asc"
                aria = "descending" if direcao_atual == "desc" else "ascending"
            else:
                proxima = "asc"
                aria = "none"
            params = self.request.GET.copy()
            params["ordenar"] = chave
            params["dir"] = proxima
            params.pop("page", None)
            colunas.append({
                "rotulo": rotulo,
                "url": "?" + params.urlencode(),
                "aria": aria,
                "ativa": chave == atual,
            })
        return colunas

    def get(self, request, *args, **kwargs):
        # Exportação reaproveita os filtros/ordem/colunas da própria URL.
        formato = request.GET.get("export")
        if formato in ("csv", "xlsx", "pdf"):
            return self._exportar(formato)
        return super().get(request, *args, **kwargs)

    def _exportar(self, formato):
        from eventos.exportacao import exportar

        colunas = self._selecionadas()
        # A exportação espelha as colunas da tela (o Evento pode estar oculto).
        sem_evento = "evento" in self._ocultas()
        cabecalhos = ["Participante", "Atividade", "Local"]
        if not sem_evento:
            cabecalhos.append("Evento")
        cabecalhos += ["Confirmada", "Certificado Emitido"] + [c["rotulo"] for c in colunas]
        linhas = []
        for inscricao in self.get_queryset():
            dados = self._dados_metadados(inscricao.participante)
            nome = f"{inscricao.participante.first_name} {inscricao.participante.last_name}".strip()
            linha = [nome, inscricao.atividade.titulo, inscricao.atividade.local]
            if not sem_evento:
                linha.append(inscricao.atividade.evento.title)
            linhas.append(
                linha
                + ["Sim" if inscricao.confirmada else "Não",
                   "Sim" if inscricao.certificado_emitido else "Não"]
                + [dados.get(c["chave"], "") for c in colunas]
            )
        return exportar(
            formato, f"inscricoes_{self._evento_id() or 'todas'}",
            cabecalhos, linhas, titulo="Relatório de Inscrições",
        )

    def get_context_data(self, **kwargs):
        """Totais (já filtrados), busca atual e cabeçalhos."""
        context = super().get_context_data(**kwargs)
        queryset = self.get_queryset()

        context["total_inscricoes"] = queryset.count()
        context["total_confirmadas"] = queryset.filter(confirmada=True).count()
        context["q"] = self._busca()

        context["colunas"] = self._colunas()
        context.update(self.metadados_colunas())

        # Colunas fixas ocultáveis (ex.: Evento). O colspan da linha de vazio é
        # o total de colunas fixas visíveis (6) + Ações (1) + metadados.
        ocultas = self._ocultas()
        context["ocultas"] = ocultas
        context["colspan_vazio"] = 7 - len(ocultas)

        # Querystring dos filtros (sem `page`) para os links de paginação.
        params = self.request.GET.copy()
        params.pop("page", None)
        context["querystring"] = params.urlencode()

        # "Limpar busca" tira só o `q` (colunas e ordem continuam).
        limpar = self.request.GET.copy()
        limpar.pop("q", None)
        limpar.pop("page", None)
        context["limpar_url"] = "?" + limpar.urlencode() if limpar else "?"
        return context


class ListaPresencaView(_ColunasMetadadosMixin, LoginRequiredMixin, ListView):
    model = Inscricao
    template_name = "relatorios/lista_presenca.html"
    context_object_name = "inscricoes"

    def get_queryset(self):
        """
        Retorna todas as inscrições confirmadas para a atividade especificada.
        """
        atividade_id = self.kwargs.get("atividade_id")
        queryset = Inscricao.objects.select_related(
            "participante", "participante__metadados", "atividade"
        ).filter(atividade_id=atividade_id)
        return queryset

    def get(self, request, *args, **kwargs):
        formato = request.GET.get("export")
        if formato in ("csv", "xlsx", "pdf"):
            return self._exportar(formato)
        return super().get(request, *args, **kwargs)

    def _exportar(self, formato):
        from eventos.exportacao import exportar

        atividade = get_object_or_404(Atividade, id=self.kwargs.get("atividade_id"))
        colunas = self._selecionadas()
        cabecalhos = (
            ["#", "Participante", "Email"]
            + [c["rotulo"] for c in colunas]
            + ["Presença Confirmada", "Certificado Emitido"]
        )
        linhas = []
        for indice, inscricao in enumerate(self.get_queryset(), start=1):
            dados = self._dados_metadados(inscricao.participante)
            nome = f"{inscricao.participante.first_name} {inscricao.participante.last_name}".strip()
            linhas.append(
                [indice, nome, inscricao.participante.email]
                + [dados.get(c["chave"], "") for c in colunas]
                + ["Sim" if inscricao.confirmada else "Não",
                   "Sim" if inscricao.certificado_emitido else "Não"]
            )
        return exportar(
            formato, f"lista_presenca_{atividade.id}",
            cabecalhos, linhas, titulo=f"Lista de Presença — {atividade.titulo}",
        )

    def get_context_data(self, **kwargs):
        """
        Adiciona detalhes da atividade ao contexto do template.
        """
        context = super().get_context_data(**kwargs)
        atividade_id = self.kwargs.get("atividade_id")
        context["atividade"] = get_object_or_404(Atividade, id=atividade_id)
        context["total_inscricoes"] = self.get_queryset().count()
        context["total_confirmadas"] = self.get_queryset().filter(confirmada=True).count()
        context.update(self.metadados_colunas())
        return context


class OcupacaoSalasView(LoginRequiredMixin, View):
    """Ocupação por sala do evento + distribuição por dia/hora (organizador).

    Ajuda a dimensionar espaços: quantas atividades, vagas oferecidas,
    inscritos e a taxa de ocupação de cada local — considerando os vários
    lugares de uma atividade (o campo `local` é uma lista) e os apelidos de
    local configurados em `AGENDA_ALIASES_LOCAL`.
    """

    template_name = "relatorios/ocupacao_salas.html"

    def _evento(self):
        from eventos.models import Evento

        return get_object_or_404(Evento, id=self.kwargs["evento_id"])

    def _atividades(self, evento):
        return evento.atividades.select_related("tipo").order_by(
            "data_hora_inicio", "id"
        )

    def _por_local(self, atividades):
        from eventos import agenda

        contagem = {}
        for atividade in atividades:
            for lugar in agenda.locais_de(atividade) or [agenda.SEM_LOCAL]:
                dados = contagem.setdefault(
                    lugar, {"local": lugar, "atividades": 0, "vagas": 0, "inscritos": 0}
                )
                dados["atividades"] += 1
                dados["vagas"] += atividade.n_vagas or 0
                dados["inscritos"] += atividade.n_inscricoes or 0
        linhas = []
        for lugar in sorted(contagem, key=lambda t: t.lower()):
            dados = contagem[lugar]
            dados["ocupacao"] = (
                round(100 * dados["inscritos"] / dados["vagas"]) if dados["vagas"] else 0
            )
            linhas.append(dados)
        return linhas

    def _por_dia_hora(self, atividades):
        """Matriz dia × hora com o nº de atividades que começam no horário."""
        from django.utils.timezone import localtime

        dias = []
        horas = set()
        mapa = {}
        for atividade in atividades:
            inicio = localtime(atividade.data_hora_inicio)
            dia = inicio.date()
            if dia not in dias:
                dias.append(dia)
            horas.add(inicio.hour)
            mapa[(dia, inicio.hour)] = mapa.get((dia, inicio.hour), 0) + 1
        horas = sorted(horas)
        linhas = []
        for hora in horas:
            linhas.append({
                "rotulo": f"{hora:02d}:00",
                "celulas": [mapa.get((dia, hora), 0) for dia in dias],
            })
        return {"dias": dias, "horas": horas, "linhas": linhas}

    def get(self, request, *args, **kwargs):
        evento = self._evento()
        atividades = list(self._atividades(evento))
        por_local = self._por_local(atividades)
        formato = request.GET.get("export")

        if formato in ("csv", "xlsx", "pdf"):
            from eventos.exportacao import exportar

            cabecalhos = ["Local", "Atividades", "Vagas", "Inscritos", "Ocupação (%)"]
            linhas = [
                [l["local"], l["atividades"], l["vagas"], l["inscritos"], l["ocupacao"]]
                for l in por_local
            ]
            return exportar(
                formato, f"ocupacao_salas_{evento.id}", cabecalhos, linhas,
                titulo=f"Ocupação por sala — {evento.title}",
            )

        return render(request, self.template_name, {
            "evento": evento,
            "linhas": por_local,
            "por_dia_hora": self._por_dia_hora(atividades),
            "totais": {
                "atividades": len(atividades),
                "vagas": sum(a.n_vagas or 0 for a in atividades),
                "inscritos": sum(a.n_inscricoes or 0 for a in atividades),
            },
        })
