from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView
from django.shortcuts import get_object_or_404
from eventos.models import Evento, Inscricao, Atividade


# Campos ordenáveis do relatório: chave do cabeçalho -> campos do ORM.
ORDENACAO = {
    "participante": ("participante__first_name", "participante__last_name"),
    "atividade": ("atividade__titulo",),
    "evento": ("atividade__evento__title",),
    "confirmada": ("confirmada",),
    "certificado": ("certificado_emitido",),
}


class RelatorioInscricoesView(LoginRequiredMixin, ListView):
    model = Inscricao
    template_name = "relatorios/inscricoes.html"
    context_object_name = "inscricoes"
    paginate_by = 20  # Paginação: Exibe 20 inscrições por página

    # -- filtros (query string) ------------------------------------------------

    def _evento_id(self):
        """Evento selecionado: o da query (?evento=) ou o da URL."""
        return self.request.GET.get("evento") or self.kwargs.get("evento_id")

    def _atividade_id(self):
        return self.request.GET.get("atividade") or None

    def _eventos_do_usuario(self):
        """Eventos que o usuário pode relatar (todos, se superuser)."""
        user = self.request.user
        if user.is_superuser:
            return Evento.objects.all().order_by("data_inicio")
        return Evento.objects.filter(organizador=user).order_by("data_inicio")

    def get_queryset(self):
        """
        Inscrições do evento selecionado, opcionalmente de uma atividade, e na
        ordem pedida pelos cabeçalhos (`?ordenar=&dir=`).
        """
        queryset = Inscricao.objects.select_related(
            "participante", "atividade", "atividade__evento"
        )

        evento_id = self._evento_id()
        if evento_id:
            queryset = queryset.filter(atividade__evento_id=evento_id)

        atividade_id = self._atividade_id()
        if atividade_id:
            queryset = queryset.filter(atividade_id=atividade_id)

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
            ("certificado", "Certificado Emitido"),
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

    def get_context_data(self, **kwargs):
        """
        Adiciona totais (já filtrados), as opções dos filtros e os cabeçalhos.
        """
        context = super().get_context_data(**kwargs)
        evento_id = self._evento_id()
        atividade_id = self._atividade_id()
        queryset = self.get_queryset()

        context["total_inscricoes"] = queryset.count()
        context["total_confirmadas"] = queryset.filter(confirmada=True).count()

        context["eventos"] = self._eventos_do_usuario()
        context["evento_selecionado"] = int(evento_id) if evento_id else None
        if evento_id:
            context["atividades"] = Atividade.objects.filter(
                evento_id=evento_id
            ).order_by("data_hora_inicio", "id")
        else:
            context["atividades"] = Atividade.objects.none()
        context["atividade_selecionada"] = int(atividade_id) if atividade_id else None

        context["colunas"] = self._colunas()

        # Querystring dos filtros (sem `page`) para os links de paginação.
        params = self.request.GET.copy()
        params.pop("page", None)
        context["querystring"] = params.urlencode()
        return context


class ListaPresencaView(LoginRequiredMixin, ListView):
    model = Inscricao
    template_name = "relatorios/lista_presenca.html"
    context_object_name = "inscricoes"

    def get_queryset(self):
        """
        Retorna todas as inscrições confirmadas para a atividade especificada.
        """
        atividade_id = self.kwargs.get("atividade_id")
        queryset = Inscricao.objects.select_related("participante", "atividade").filter(
            atividade_id=atividade_id
        )
        return queryset


    def get_context_data(self, **kwargs):
        """
        Adiciona detalhes da atividade ao contexto do template.
        """
        context = super().get_context_data(**kwargs)
        atividade_id = self.kwargs.get("atividade_id")
        context["atividade"] = get_object_or_404(Atividade, id=atividade_id)
        context["total_inscricoes"] = self.get_queryset().count()
        context["total_confirmadas"] = self.get_queryset().filter(confirmada=True).count()        
        return context
