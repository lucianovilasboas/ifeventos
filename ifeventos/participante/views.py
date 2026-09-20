from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth.decorators import login_required
from eventos.models import Atividade, Evento, Inscricao, Participante
from eventos import agenda, propostas
from eventos.forms import PropostaForm
from eventos.propostas import PropostaBloqueada
from eventos.inscricoes import (
    InscricaoBloqueada,
    cancelar_inscricao as cancelar_inscricao_servico,
    conflito_com_inscricoes,
)
from django.contrib import messages
from django.utils.timezone import localtime
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
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

    inscricoes = Inscricao.objects.filter(participante=participante).select_related(
        "atividade", "atividade__evento", "atividade__tipo"
    )
    # Atividades não inscritas (e publicadas), da que acontece antes para a que
    # acontece depois.
    atividades = (
        Atividade.objects.exclude(inscritos__participante=participante)
        .filter(publicada=True)
        .select_related("evento", "tipo")
        .order_by("data_hora_inicio", "id")
    )

    # Filtro por evento (afeta as duas listas). A lista de opções é montada
    # ANTES de filtrar, senão o próprio filtro sumiria da tela.
    eventos_filtro = sorted(
        {i.atividade.evento for i in inscricoes} | {a.evento for a in atividades},
        key=lambda e: e.title,
    )
    # Todas as minhas inscrições (sem o filtro de evento): é com elas que a
    # lista de disponíveis detecta conflito de horário.
    minhas_todas = [i.atividade for i in inscricoes]

    evento_id = (request.GET.get("evento") or "").strip()
    if evento_id.isdigit():
        inscricoes = inscricoes.filter(atividade__evento_id=evento_id)
        atividades = atividades.filter(evento_id=evento_id)

    # "Acontecendo agora" e "a seguir" (entre as minhas inscrições).
    agora = localtime()
    minhas = [i.atividade for i in inscricoes]
    acontecendo = [
        a for a in minhas if a.data_hora_inicio <= agora < a.data_hora_fim
    ]
    a_seguir = sorted(
        [a for a in minhas if a.data_hora_inicio > agora],
        key=lambda a: a.data_hora_inicio,
    )[:3]

    # Rótulo do dia em cada inscrição: o template usa `{% regroup %}` para
    # agrupar a lista por dia (a ordem cronológica garante dias consecutivos).
    inscricoes = inscricoes.order_by("atividade__data_hora_inicio", "id")
    for inscricao in inscricoes:
        inscricao.dia = localtime(inscricao.atividade.data_hora_inicio).strftime("%d/%m/%Y")
        inscricao.atividade.inscricao = inscricao

    # Aviso de conflito nas disponíveis — calculado em memória (sem query por
    # atividade), pela mesma regra que recusa a inscrição.
    atividades = list(atividades)
    for atividade in atividades:
        atividade.conflito = next(
            (
                m
                for m in minhas_todas
                if m.pk != atividade.pk
                and atividade.data_hora_inicio < m.data_hora_fim
                and atividade.data_hora_fim > m.data_hora_inicio
            ),
            None,
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
            form.save_metadados(participante)  # Campos extra do perfil (config)

            return redirect("participante:dashboard")

    return render(request, 'participante/dashboard.html', {
        'inscricoes': inscricoes,
        'atividades': atividades,
        'grade_minha_agenda': agenda.montar_grade(minhas),
        'acontecendo': acontecendo,
        'a_seguir': a_seguir,
        'eventos_filtro': eventos_filtro,
        'evento_id': evento_id,
        'vistas_inscricoes': [
            {"valor": "lista", "rotulo": "Lista", "icone": "fa-solid fa-list"},
            {"valor": "cartoes", "rotulo": "Cartões", "icone": "fa-solid fa-table-cells-large"},
            {"valor": "cronograma", "rotulo": "Cronograma", "icone": "fa-regular fa-calendar-days"},
        ],
        'vistas_disponiveis': [
            {"valor": "lista", "rotulo": "Lista", "icone": "fa-solid fa-list"},
            {"valor": "cartoes", "rotulo": "Cartões", "icone": "fa-solid fa-table-cells-large"},
        ],
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

    # Conflito de horário com atividades já inscritas (mesma regra usada para
    # avisar antes, na lista de disponíveis).
    conflito = conflito_com_inscricoes(participante, atividade)
    if conflito is not None:
        messages.error(
            request,
            f"Conflito de horário com '{conflito.titulo}', que ocorre de "
            f"{conflito.data_hora_inicio.strftime('%d/%m/%Y %H:%M')} até "
            f"{conflito.data_hora_fim.strftime('%d/%m/%Y %H:%M')}."
        )
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


# ---------------------------------------------------------------------------
# Chamada de proposições (proponente)
# ---------------------------------------------------------------------------

def _palestrantes_escolhidos(form, participante, request=None):
    """Palestrantes escolhidos pela busca + o próprio proponente.

    Não há mais o select múltiplo (expunha nomes demais): a escolha vem dos
    `palestrantes_extra` (chips da busca, qualquer participante cadastrado) e,
    se o switch "Eu vou ministrar" estiver marcado, do próprio proponente.
    Os ids são reconsultados aqui: o POST pode vir com qualquer coisa.
    """
    escolhidos, ids = [], set()

    if request is not None:
        extras = [
            valor for valor in request.POST.getlist("palestrantes_extra")
            if str(valor).isdigit()
        ]
        if extras:
            for pessoa in Participante.objects.filter(pk__in=extras):
                if pessoa.pk != participante.pk and pessoa.pk not in ids:
                    ids.add(pessoa.pk)
                    escolhidos.append(pessoa)

    if form.cleaned_data.get("eu_sou_palestrante") and participante.pk not in ids:
        escolhidos.append(participante)

    return escolhidos


def _sugestoes_do_post(request):
    """Lista de dicts {nome, email, telefone} dos palestrantes sugeridos no form."""
    nomes = request.POST.getlist("sugestao_nome")
    emails = request.POST.getlist("sugestao_email")
    telefones = request.POST.getlist("sugestao_telefone")
    return [
        {
            "nome": (nomes[i] if i < len(nomes) else "") or "",
            "email": (emails[i] if i < len(emails) else "") or "",
            "telefone": (telefones[i] if i < len(telefones) else "") or "",
        }
        for i in range(len(nomes))
    ]


def _extras_do_post(request):
    """Participantes escolhidos pela busca (chips `palestrantes_extra`), do POST."""
    extras = [
        valor for valor in request.POST.getlist("palestrantes_extra")
        if str(valor).isdigit()
    ]
    if not extras:
        return []
    return list(Participante.objects.filter(pk__in=extras))


@login_required(login_url='/accounts/login/')
def minhas_propostas(request):
    """Minhas propostas de atividade e o atalho para propor."""
    participante = get_object_or_404(Participante, id=request.user.id)
    return render(request, 'participante/minhas_propostas.html', {
        'minhas': propostas.minhas_propostas(participante),
        'chamadas': propostas.chamadas_abertas(),
    })


@login_required(login_url='/accounts/login/')
def propor_atividade(request, evento_id):
    """Formulário de proposta de atividade (só com a chamada aberta)."""
    evento = get_object_or_404(Evento, id=evento_id)
    participante = get_object_or_404(Participante, id=request.user.id)
    aberta = propostas.esta_aberta(evento)

    if request.method == "POST":
        if not aberta:
            messages.error(request, propostas.motivo_fechada(evento))
            return redirect('participante:minhas_propostas')

        form = PropostaForm(request.POST, request.FILES, evento=evento,
                            usuario=participante)
        if form.is_valid():
            # A imagem recortada (Cropper) tem prioridade sobre o arquivo cru.
            recorte = imagem_cortada(request, 'proposta')
            imagem = recorte or form.cleaned_data.get('imagem')
            try:
                propostas.propor(
                    participante, evento,
                    vaga=form.cleaned_data['vaga'],
                    titulo=form.cleaned_data['titulo'],
                    descricao=form.cleaned_data['descricao'],
                    tipo=form.cleaned_data.get('tipo'),
                    tipo_sugerido=form.cleaned_data.get('tipo_sugerido'),
                    palestrantes=_palestrantes_escolhidos(form, participante, request),
                    n_vagas=form.cleaned_data.get('n_vagas') or 0,
                    emite_certificado=form.cleaned_data.get('emite_certificado'),
                    imagem=imagem,
                    recursos_necessarios=form.cleaned_data.get('recursos_necessarios') or "",
                    consentimento_voluntario=form.cleaned_data.get('consentimento_voluntario'),
                    sugestoes_palestrantes=_sugestoes_do_post(request),
                )
            except PropostaBloqueada as erro:
                form.add_error(None, erro)
            else:
                messages.success(
                    request,
                    "Proposta enviada! Ela fica como rascunho até a aprovação "
                    "da organização.",
                )
                return redirect('participante:minhas_propostas')
    else:
        form = PropostaForm(evento=evento, usuario=participante)

    slots = propostas.grade_de_propostas(evento, participante)
    return render(request, 'participante/form_proposta.html', {
        'evento': evento,
        'form': form,
        'chamada': propostas.chamada_de(evento),
        'aberta': aberta,
        'motivo_fechado': propostas.motivo_fechada(evento),
        'restantes': propostas.restantes_para_propor(participante, evento),
        'vistas_vaga': propostas.VISTAS_VAGA,
        'slots': slots,
        'slots_json': propostas.grade_em_json(slots),
        # Preserva o que o usuário já tinha preenchido quando a validação falha
        # (chips de palestrante escolhido e de sugestão não podem sumir).
        'palestrantes_extras': _extras_do_post(request),
        'sugestoes_iniciais': _sugestoes_do_post(request),
        # Recorte da imagem (data URL) para a prévia não sumir no erro.
        'imagem_preview': request.POST.get('cropped_image') or '',
    })


@login_required(login_url='/accounts/login/')
def editar_proposta(request, atividade_id):
    """Edita a própria proposta (só enquanto pendente e com a chamada aberta)."""
    proposta = get_object_or_404(
        Atividade, id=atividade_id, proponente_id=request.user.id
    )
    evento = proposta.evento

    if not proposta.pendente:
        messages.error(
            request,
            "Esta proposta já foi decidida pela organização e não pode mais "
            "ser alterada.",
        )
        return redirect('participante:minhas_propostas')
    if not propostas.esta_aberta(evento):
        messages.error(request, propostas.motivo_fechada(evento))
        return redirect('participante:minhas_propostas')

    if request.method == "POST":
        form = PropostaForm(request.POST, request.FILES, instance=proposta,
                            evento=evento, usuario=request.user,
                            incluir_vaga=proposta.vaga)
        if form.is_valid():
            recorte = imagem_cortada(request, 'proposta')
            imagem = recorte or form.cleaned_data.get('imagem')
            try:
                propostas.atualizar(
                    proposta,
                    vaga=form.cleaned_data['vaga'],
                    titulo=form.cleaned_data['titulo'],
                    descricao=form.cleaned_data['descricao'],
                    tipo=form.cleaned_data.get('tipo'),
                    tipo_sugerido=form.cleaned_data.get('tipo_sugerido'),
                    palestrantes=_palestrantes_escolhidos(form, request.user, request),
                    n_vagas=form.cleaned_data.get('n_vagas') or 0,
                    emite_certificado=form.cleaned_data.get('emite_certificado'),
                    imagem=imagem,
                    recursos_necessarios=form.cleaned_data.get('recursos_necessarios') or "",
                    consentimento_voluntario=form.cleaned_data.get('consentimento_voluntario'),
                    sugestoes_palestrantes=_sugestoes_do_post(request),
                )
            except PropostaBloqueada as erro:
                form.add_error(None, erro)
            else:
                messages.success(request, "Proposta atualizada.")
                return redirect('participante:minhas_propostas')
        # Validação falhou: preserva os chips que o autor já tinha montado.
        palestrantes_extras = _extras_do_post(request)
        sugestoes_iniciais = _sugestoes_do_post(request)
    else:
        form = PropostaForm(instance=proposta, evento=evento,
                            usuario=request.user, incluir_vaga=proposta.vaga)
        # O switch reflete se o proponente já é palestrante da proposta.
        form.fields['eu_sou_palestrante'].initial = (
            proposta.palestrantes.filter(pk=request.user.pk).exists()
        )
        palestrantes_extras = [
            pessoa for pessoa in proposta.palestrantes.all()
            if pessoa.pk != request.user.pk
        ]
        sugestoes_iniciais = [
            {"nome": sug.nome, "email": sug.email, "telefone": sug.telefone}
            for sug in proposta.palestrantes_sugeridos.all()
        ]

    slots = propostas.grade_de_propostas(evento, request.user)
    return render(request, 'participante/form_proposta.html', {
        'evento': evento,
        'form': form,
        'proposta': proposta,
        'vistas_vaga': propostas.VISTAS_VAGA,
        'palestrantes_extras': palestrantes_extras,
        'sugestoes_iniciais': sugestoes_iniciais,
        # Recorte da imagem (data URL) para a prévia não sumir no erro.
        'imagem_preview': request.POST.get('cropped_image') or '',
        'chamada': propostas.chamada_de(evento),
        'aberta': True,
        'motivo_fechado': '',
        'slots': slots,
        'slots_json': propostas.grade_em_json(slots),
    })


@login_required(login_url='/accounts/login/')
@require_POST
def cancelar_proposta(request, atividade_id):
    """Cancela a própria proposta enquanto ela está pendente."""
    proposta = get_object_or_404(
        Atividade, id=atividade_id, proponente_id=request.user.id
    )
    try:
        propostas.cancelar(proposta)
    except PropostaBloqueada as erro:
        messages.error(request, erro.messages[0])
    else:
        messages.success(request, "Proposta cancelada.")
    return redirect('participante:minhas_propostas')


@login_required(login_url='/accounts/login/')
def buscar_participante(request):
    """Busca participantes por nome ou e-mail (para escolher palestrantes).

    A lista de palestrantes do formulário traz só quem já tem a flag; este
    endpoint é o que permite escolher qualquer pessoa cadastrada sem
    transformar o select num paredão de centenas de opções. Exige 3 caracteres
    e devolve no máximo 10 resultados.
    """
    from django.db.models import Q

    termo = (request.GET.get("q") or "").strip()
    if len(termo) < 3:
        return JsonResponse({"resultados": []})

    pessoas = (
        Participante.objects.filter(
            Q(first_name__icontains=termo)
            | Q(last_name__icontains=termo)
            | Q(email__icontains=termo)
        )
        .exclude(pk=request.user.pk)
        .order_by("first_name", "last_name")[:10]
    )
    return JsonResponse({"resultados": [
        {
            "id": pessoa.pk,
            "nome": pessoa.get_full_name() or pessoa.username,
            "email": pessoa.email,
            "palestrante": pessoa.is_palestrante,
        }
        for pessoa in pessoas
    ]})


# -- Concierge do participante (chat sobre a programação) --
@login_required(login_url='/accounts/login/')
def assistente(request):
    """Tela do assistente (chat). A resposta vem do endpoint async abaixo."""
    return render(request, "participante/assistente.html")


@csrf_exempt
@login_required(login_url='/accounts/login/')
async def assistente_responder(request):
    """Responde à pergunta do participante, ancorado na programação real."""
    from eventos import concierge

    if request.method != "POST":
        return JsonResponse({"erro": "Método não permitido"}, status=405)
    try:
        dados = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"erro": "Corpo da requisição inválido."}, status=400)

    resultado = await concierge.responder(
        dados.get("mensagem"), dados.get("historico")
    )
    status = 400 if resultado.get("erro") else 200
    return JsonResponse(resultado, status=status)


@login_required(login_url='/accounts/login/')
def assistente_sugestoes(request):
    """Sugestões para o autocomplete do assistente (atividades, eventos e FAQ)."""
    from eventos import concierge

    return JsonResponse({"sugestoes": concierge.sugestoes(request.GET.get("q", ""))})


# -- Minhas palestras (área restrita do palestrante, sem PII) --
class MinhasPalestrasView(LoginRequiredMixin, TemplateView):
    """Atividades em que a pessoa é palestrante (só ver + QR).

    Sem lista de inscritos com e-mail/CPF: o palestrante vê a atividade e o QR
    de presença para mostrar na sala — nada além disso.
    """

    template_name = "participante/minhas_palestras.html"

    def get_context_data(self, **kwargs):
        from eventos.crachas import atividades_do_palestrante

        contexto = super().get_context_data(**kwargs)
        contexto["atividades"] = atividades_do_palestrante(self.request.user)
        contexto["logo_url"] = url_da_logo()
        return contexto


@login_required(login_url='/accounts/login/')
def minha_palestra_qr(request, atividade_id):
    """QR de presença da atividade, para quem PALESTRA nela (sem painel de nomes).

    Diferente da tela do organizador: aqui não sai a lista de quem confirmou
    (PII) nem o botão de desfazer. Só o código, que se renova sozinho.
    """
    from django.http import HttpResponseForbidden

    from eventos.crachas import pode_exibir_qr_atividade

    atividade = get_object_or_404(Atividade, id=atividade_id)
    if not pode_exibir_qr_atividade(request.user, atividade):
        return HttpResponseForbidden("Você não organiza este evento nem palestra nesta atividade.")
    return render(request, "participante/minha_palestra_qr.html", {
        "atividade": atividade,
        "evento": atividade.evento,
        "logo_url": url_da_logo(),
    })
