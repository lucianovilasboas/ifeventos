from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.views.generic import ListView
from django.shortcuts import get_object_or_404
from eventos.metadados import campos as campos_metadados, colunas_selecionadas
from eventos.models import Inscricao, Atividade


# Campos ordenáveis do relatório: chave do cabeçalho -> campos do ORM.
ORDENACAO = {
    "participante": ("participante__first_name", "participante__last_name"),
    "atividade": ("atividade__titulo",),
    "evento": ("atividade__evento__title",),
    "confirmada": ("confirmada",),
    "certificado": ("certificado_emitido",),
}


class _ColunasMetadadosMixin:
    """Contexto das colunas extras (metadados configuráveis) dos relatórios.

    `colunas_disponiveis` traz, por campo, um link que liga/desliga a coluna
    preservando os demais parâmetros da query (`q`, `ordenar`, `dir`…).
    """

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
            "campos_selecionados_str": ",".join(chaves),
            "export_urls": self._urls_exportacao(),
        }


class RelatorioInscricoesView(_ColunasMetadadosMixin, LoginRequiredMixin, ListView):
    model = Inscricao
    template_name = "relatorios/inscricoes.html"
    context_object_name = "inscricoes"
    paginate_by = 20  # Paginação: Exibe 20 inscrições por página

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
        colunas = []
        for chave, rotulo in (
            ("participante", "Participante"),
            ("atividade", "Atividade"),
            ("evento", "Evento"),
            ("confirmada", "Confirmada"),
            ("certificado", "Certificado"),
        ):
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
        cabecalhos = ["Participante", "Atividade", "Evento",
                      "Confirmada", "Certificado Emitido"] + [c["rotulo"] for c in colunas]
        linhas = []
        for inscricao in self.get_queryset():
            dados = self._dados_metadados(inscricao.participante)
            nome = f"{inscricao.participante.first_name} {inscricao.participante.last_name}".strip()
            linhas.append(
                [nome, inscricao.atividade.titulo, inscricao.atividade.evento.title,
                 "Sim" if inscricao.confirmada else "Não",
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
