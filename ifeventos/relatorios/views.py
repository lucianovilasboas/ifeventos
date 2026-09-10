from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView
from django.shortcuts import get_object_or_404
from eventos.models import Inscricao
from eventos.models import Inscricao, Atividade



class RelatorioInscricoesView(LoginRequiredMixin, ListView):
    model = Inscricao
    template_name = "relatorios/inscricoes.html"
    context_object_name = "inscricoes"
    paginate_by = 20  # Paginação: Exibe 20 inscrições por página

    def get_queryset(self):
        """
        Retorna todas as inscrições filtradas pelo evento.
        """
        
        evento_id = self.kwargs.get("evento_id")  # Obtém o evento da URL
        queryset = Inscricao.objects.select_related("participante", "atividade")

        if evento_id:
            queryset = queryset.filter(atividade__evento_id=evento_id)

        return queryset

    def get_context_data(self, **kwargs):
        """
        Adiciona informações extras no contexto do template.
        """
        context = super().get_context_data(**kwargs)
        context["total_inscricoes"] = self.get_queryset().count()
        context["total_confirmadas"] = self.get_queryset().filter(confirmada=True).count()
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
