from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth.decorators import login_required
from eventos.models import Atividade, Inscricao, Participante
from eventos.inscricoes import InscricaoBloqueada, cancelar_inscricao as cancelar_inscricao_servico
from django.contrib import messages
from django.utils.timezone import localtime
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json
from .forms import ParticipanteUpdateForm

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, TemplateView
from eventos.models import Certificado
from eventos.crachas import crachas_do_usuario, url_da_logo
from eventos.imagens import imagem_cortada


@login_required(login_url='/accounts/login/')
def dashboard(request):

    participante = get_object_or_404(Participante, id=request.user.id)

    inscricoes = Inscricao.objects.filter(participante=participante)
    # Atividades não inscritas, da que acontece antes para a que acontece depois.
    atividades = Atividade.objects.exclude(inscritos__participante=participante).order_by(
        "data_hora_inicio", "id"
    )

    form = ParticipanteUpdateForm(instance=participante)

    if request.method == "POST":
        form = ParticipanteUpdateForm(request.POST, instance=participante)
        if form.is_valid():

            participante = form.save(commit=False)  # ⚠ Salvamos manualmente depois para capturar a imagem

            # A foto recortada (modal de perfil) tem prioridade sobre o arquivo
            # original enviado pelo input.
            recorte = imagem_cortada(request, f'perfil_{participante.id}')
            if recorte:
                participante.foto = recorte
            elif 'foto' in request.FILES:
                participante.foto = request.FILES['foto']  # Atribuímos a imagem manualmente
            participante.save()  # Agora salvamos no banco

            return redirect("participante:dashboard")

    return render(request, 'participante/dashboard.html', {
        'inscricoes': inscricoes,
        'atividades': atividades,
        'message': 'Bora se inscrever em mais atividades?',
        'is_organizador': participante.is_organizador,
        'form': form
        })






@login_required(login_url='/accounts/login/')
def inscrever(request, atividade_id):
    atividade = get_object_or_404(Atividade, id=atividade_id)
    participante = Participante.from_user(request.user)  # Obtém o participante vinculado ao usuário

    # Verifica se o participante já está inscrito na atividade
    if Inscricao.objects.filter(participante=participante, atividade=atividade).exists():
        messages.warning(request, "Você já está inscrito nesta atividade.")
        return redirect('participante:dashboard')

    # Verifica se a atividade ainda possui vagas
    if atividade.n_vagas <= Inscricao.objects.filter(atividade=atividade).count():
        messages.warning(request, "Lamentamos, mas essa atividade não possui mais vagas.")
        return redirect('participante:dashboard')

    # 🔹 Verifica se há conflito de horários com atividades já inscritas
    atividades_inscritas = Atividade.objects.filter(
        inscritos__participante=participante
    )

    for inscrita in atividades_inscritas:
        if (
            localtime(atividade.data_hora_inicio) < localtime(inscrita.data_hora_fim) and
            localtime(atividade.data_hora_fim) > localtime(inscrita.data_hora_inicio)
        ):
            messages.error(request, f"Conflito de horário com '{inscrita.titulo}', que ocorre de {inscrita.data_hora_inicio.strftime('%d/%m/%Y %H:%M')} até {inscrita.data_hora_fim.strftime('%d/%m/%Y %H:%M')}.")
            return redirect('participante:dashboard')

    # Se não houver conflito, realiza a inscrição
    Inscricao.objects.create(participante=participante, atividade=atividade)
    messages.success(request, "Inscrição realizada com sucesso!")
    return redirect('participante:dashboard')






@login_required(login_url='/accounts/login/')
def cancelar_inscricao(request, inscricao_id):
    # get_object_or_404: id inexistente (ou de outra pessoa) devolvia 500.
    inscricao = get_object_or_404(Inscricao, id=inscricao_id, participante=request.user)

    try:
        # Cancela a inscrição E a presença naquela atividade, com auditoria.
        cancelar_inscricao_servico(inscricao, por=request.user)
    except InscricaoBloqueada as bloqueio:
        messages.warning(request, bloqueio.messages[0])
        return redirect('participante:dashboard')

    messages.success(request, "Inscrição cancelada com sucesso!")
    return redirect('participante:dashboard')














# -- Alterações para o AJAX --


@csrf_exempt
@login_required
def gerenciar_inscricoes_ajax(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            atividade_id = data.get("atividade_id")
            inscrito = data.get("inscrito")
            participante = get_object_or_404(Participante, id=request.user.id) 

            atividade = Atividade.objects.get(id=atividade_id)
            
            if inscrito: 
                # Inscrever usuário
                Inscricao.objects.get_or_create(participante=participante, atividade=atividade)
            else:
                # Cancelar inscrição: o serviço também cancela a presença na
                # atividade (com auditoria) e recusa quando já há certificado.
                para_cancelar = Inscricao.objects.filter(
                    participante=participante, atividade=atividade
                ).first()
                if para_cancelar is not None:
                    cancelar_inscricao_servico(para_cancelar, por=request.user)

            # Atualiza o número de inscritos
            inscritos_count = Inscricao.objects.filter(atividade=atividade).count()   
            messages.success(request, "Inscrição atualizada com sucesso!")
            return JsonResponse({"status": "success", "inscritos": inscritos_count, "vagas": atividade.n_vagas - inscritos_count})
        except InscricaoBloqueada as bloqueio:
            messages.warning(request, bloqueio.messages[0])
            return JsonResponse({"status": "error", "message": bloqueio.messages[0]}, status=400)
        except Exception as e:
            messages.warning(request, "Erro ao atualizar inscrição.")
            return JsonResponse({"status": "error", "message": str(e)}, status=400)

    return JsonResponse({"status": "error", "message": "Método não permitido"}, status=405)





# -- Certificados --

class MeusCertificadosView(LoginRequiredMixin, ListView):
    """
    View para que o participante veja e baixe seus certificados.
    """
    model = Certificado
    template_name = "participante/meus_certificados.html"
    context_object_name = "certificados"

    def get_queryset(self):
        return Certificado.objects.filter(participante=self.request.user)



class MeusCrachasView(LoginRequiredMixin, TemplateView):
    """Crachás do usuário: um por evento em que ele tem papel.

    Atende aos três papéis de uma vez — organizador, palestrante e participante
    são a mesma pessoa logada; o que muda, de um crachá para o outro, é o papel
    que ela tem em cada evento (e é isso que o crachá estampa).
    """

    template_name = "participante/meus_crachas.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["crachas"] = crachas_do_usuario(self.request.user)
        contexto["logo_url"] = url_da_logo()
        return contexto
