from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth.decorators import login_required
from django.db.models import Exists, OuterRef
from django.urls import reverse
from eventos.models import Atividade, Evento, Inscricao, Participante, Presenca
from eventos.tempo import local_legivel
from eventos import agenda, propostas
from eventos import contexto as contexto_evento
from eventos.forms import PropostaForm
from eventos.propostas import PropostaBloqueada
from eventos.inscricoes import (
    InscricaoBloqueada,
    cancelar_inscricao as cancelar_inscricao_servico,
    conflito_com_inscricoes,
    exigir_cancelamento_permitido,
    motivo_inscricao_encerrada,
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


def _detalhe_atividade(atividade, confirmada=None, inscricao_aberta=True):
    """Dados do modal "Mais informações" (vai para um `json_script`)."""
    return {
        "titulo": atividade.titulo,
        "tipo": str(atividade.tipo) if atividade.tipo_id else "",
        "evento": atividade.evento.title,
        "inicio": localtime(atividade.data_hora_inicio).strftime("%d/%m/%Y %H:%M"),
        "fim": localtime(atividade.data_hora_fim).strftime("%d/%m/%Y %H:%M"),
        "local": atividade.local or atividade.evento.local or "",
        "descricao": atividade.descricao or "",
        "inscritos": atividade.n_inscricoes,
        "vagas": atividade.n_vagas,
        "exige_inscricao": atividade.exige_inscricao,
        "certificado": atividade.emite_certificado,
        "confirmada": confirmada,
        "inscricao_aberta": inscricao_aberta,
        "imagem": atividade.imagem.url if atividade.imagem else "",
        "palestrantes": [
            p.get_full_name() or p.email for p in atividade.palestrantes.all()
        ],
        "ics": reverse("eventos:atividade_ics", args=[atividade.id]),
    }


@login_required(login_url='/accounts/login/')
def dashboard(request):

    participante = get_object_or_404(Participante, id=request.user.id)

    inscricoes = Inscricao.objects.filter(participante=participante).select_related(
        "atividade", "atividade__evento", "atividade__tipo"
    ).prefetch_related("atividade__palestrantes").annotate(
        # "Emitido" deriva da tabela `Certificado` (fonte de verdade).
        tem_certificado=Exists(
            Certificado.objects.filter(
                participante=OuterRef("participante"),
                atividade=OuterRef("atividade"),
            )
        )
    )
    # Atividades não inscritas (e publicadas), da que acontece antes para a que
    # acontece depois.
    atividades = (
        Atividade.objects.exclude(inscritos__participante=participante)
        .filter(publicada=True)
        .select_related("evento", "tipo")
        .prefetch_related("palestrantes")
        .order_by("data_hora_inicio", "id")
    )

    agora = localtime()
    hoje = agora.date()

    # Contexto de evento: o painel mostra UM evento por vez (o padrão). Os
    # grupos já vêm ordenados — atuais, próximos e o arquivo de passados.
    grupos = contexto_evento.classificar(
        contexto_evento.eventos_do_participante(participante)
    )
    evento_padrao = contexto_evento.resolver_padrao(participante, grupos)

    # "Eventos arquivados" é arquivo: o link abre o evento em modo CONSULTA (só
    # minhas inscrições), sem trocar o padrão. Só vale id de evento arquivado
    # da própria pessoa.
    evento_consulta = None
    evento_id = (request.GET.get("evento") or "").strip()
    if evento_id.isdigit():
        evento_consulta = next(
            (e for e in grupos["arquivados"] if str(e.id) == evento_id), None
        )
    evento_foco = evento_consulta or evento_padrao
    modo_consulta = bool(evento_consulta) or bool(
        evento_foco is not None
        and (evento_foco.terminou or evento_foco.arquivado)
    )
    tem_mais_eventos = (
        len(grupos["atuais"]) + len(grupos["futuros"]) + len(grupos["a_encerrar"])
        > 1
    )
    # O arquivo abre em modo consulta (só minhas inscrições), sem trocar o padrão.
    for arquivado in grupos["arquivados"]:
        arquivado.link_contexto = (
            f"{reverse('participante:dashboard')}?evento={arquivado.id}"
        )

    # Todas as minhas inscrições (sem o filtro de evento): é com elas que a
    # lista de disponíveis detecta conflito de horário.
    minhas_todas = [i.atividade for i in inscricoes]

    if evento_foco is not None:
        inscricoes = inscricoes.filter(atividade__evento=evento_foco)
        atividades = atividades.filter(evento=evento_foco)

    if modo_consulta:
        # Evento encerrado/arquivado: a tela é somente leitura (só as minhas
        # inscrições). O bloqueio de servidor vive em `eventos.inscricoes`.
        atividades = atividades.none()

    # "Acontecendo agora" e "a seguir" (entre as minhas inscrições).
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
    inscricoes = list(inscricoes)
    resumos_participacao = []
    por_evento = {}
    for inscricao in inscricoes:
        inscricao.status_presenca = "confirmada" if inscricao.confirmada else "nao_confirmada"
        inscricao.status_presenca_label = (
            "Presença confirmada" if inscricao.confirmada else "Presença não confirmada"
        )
        evento = inscricao.atividade.evento
        resumo = por_evento.setdefault(evento.id, {
            "evento": evento, "inscritas": 0, "confirmadas": 0,
            "limiar": evento.percentual_certificado,
        })
        resumo["inscritas"] += 1
        resumo["confirmadas"] += int(inscricao.confirmada)

    for resumo in por_evento.values():
        resumo["percentual"] = round(
            100 * resumo["confirmadas"] / resumo["inscritas"], 1
        ) if resumo["inscritas"] else 0
        resumo["elegivel"] = resumo["percentual"] >= resumo["limiar"]
    resumos_participacao = sorted(
        por_evento.values(), key=lambda item: item["evento"].title.casefold()
    )
    for inscricao in inscricoes:
        inicio_local = localtime(inscricao.atividade.data_hora_inicio)
        inscricao.dia = inicio_local.strftime("%d/%m/%Y")
        inscricao.hoje = inicio_local.date() == hoje
        # Depois que o evento encerra/é arquivado, o participante não cancela
        # mais — só o organizador (pelo admin).
        inscricao.cancelavel = not modo_consulta
        inscricao.atividade.inscricao = inscricao

    # Aviso de conflito nas disponíveis — calculado em memória (sem query por
    # atividade), pela mesma regra que recusa a inscrição.
    atividades = list(atividades)
    for atividade in atividades:
        atividade.hoje = (
            localtime(atividade.data_hora_inicio).date() == hoje
        )
        atividade.inscricao_aberta = (
            not atividade.encerrada and not modo_consulta
        )
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

    # Disponíveis agrupadas por dia (mesmo cabeçalho da lista de inscrições),
    # com "hoje" marcado. Na lista e nos cartões a ordem é da mais recente para
    # a mais antiga; o cronograma continua cronológico (a grade ordena por
    # dia/hora por conta própria).
    secoes_disponiveis = agenda.agrupar(atividades)
    for secao in secoes_disponiveis:
        secao["itens"] = list(reversed(secao["itens"]))
    secoes_disponiveis.reverse()
    grade_disponiveis = agenda.montar_grade(atividades)
    atividades.reverse()

    # Detalhes do modal "Mais informações": um mapa por atividade, usado pelos
    # cartões e pelos chips do cronograma (sem repetir dezenas de atributos).
    detalhes_atividades = {}
    for inscricao in inscricoes:
        atividade = inscricao.atividade
        detalhes_atividades[atividade.id] = _detalhe_atividade(
            atividade,
            confirmada=inscricao.confirmada,
            inscricao_aberta=(
                not modo_consulta and not atividade.encerrada
            ),
        )
    for atividade in atividades:
        detalhes_atividades[atividade.id] = _detalhe_atividade(
            atividade,
            inscricao_aberta=atividade.inscricao_aberta,
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
        # POST inválido: o modal precisa mostrar os erros (o `perfil_form` do
        # context processor viria novo, sem os erros, e o usuário veria o modal
        # "resetado" sem saber que nada foi salvo).
        messages.error(
            request,
            "Não foi possível salvar o perfil: "
            + "; ".join(
                m for mensagens in form.errors.values() for m in mensagens
            ),
        )

    contexto = {
        'inscricoes': inscricoes,
        'atividades': atividades,
        'secoes_disponiveis': secoes_disponiveis,
        'resumos_participacao': resumos_participacao,
        'grade_minha_agenda': agenda.montar_grade(minhas),
        'grade_disponiveis': grade_disponiveis,
        'detalhes_atividades': detalhes_atividades,
        'acontecendo': acontecendo,
        'a_seguir': a_seguir,
        # Evento em foco e o arquivo separado (não viram chips de filtro).
        'evento_padrao': evento_padrao,
        'evento_foco': evento_foco,
        'modo_consulta': modo_consulta,
        'evento_consulta': evento_consulta,
        'eventos_atuais': grupos["atuais"],
        'eventos_futuros': grupos["futuros"],
        'eventos_a_encerrar': grupos["a_encerrar"],
        'eventos_arquivados': grupos["arquivados"],
        'tem_mais_eventos': tem_mais_eventos,
        'vistas_inscricoes': [
            {"valor": "lista", "rotulo": "Lista", "icone": "fa-solid fa-list"},
            {"valor": "cartoes", "rotulo": "Cartões", "icone": "fa-solid fa-table-cells-large"},
            {"valor": "cronograma", "rotulo": "Cronograma", "icone": "fa-regular fa-calendar-days"},
        ],
        'vistas_disponiveis': [
            {"valor": "lista", "rotulo": "Lista", "icone": "fa-solid fa-list"},
            {"valor": "cartoes", "rotulo": "Cartões", "icone": "fa-solid fa-table-cells-large"},
            {"valor": "cronograma", "rotulo": "Cronograma", "icone": "fa-regular fa-calendar-days"},
        ],
        'message': 'Bora se inscrever em mais atividades?',
        'is_organizador': participante.is_organizador,
        'form': form
    }
    if request.method == "POST" and not form.is_valid():
        contexto['perfil_form'] = form      # formulário ligado, com os erros
        contexto['perfil_abrir'] = True     # abre o modal para o usuário ver
    return render(request, 'participante/dashboard.html', contexto)






@login_required(login_url='/accounts/login/')
def inscrever(request, atividade_id):
    atividade = get_object_or_404(Atividade, id=atividade_id)
    participante = Participante.from_user(request.user)  # Obtém o participante vinculado ao usuário

    # Atividade ou evento já encerrados: a oferta não aceita mais inscrição.
    motivo = motivo_inscricao_encerrada(atividade)
    if motivo:
        messages.warning(request, motivo)
        return redirect('participante:dashboard')

    # Verifica se o participante já está inscrito na atividade
    if Inscricao.objects.filter(participante=participante, atividade=atividade).exists():
        messages.warning(request, "Você já está inscrito nesta atividade.")
        return redirect('participante:dashboard')

    # Atividade aberta (ex.: LUAU): não há lista de inscritos.
    if not atividade.exige_inscricao:
        messages.info(request, "Esta atividade não precisa de inscrição — é só comparecer.")
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
            f"{local_legivel(conflito.data_hora_inicio)} até "
            f"{local_legivel(conflito.data_hora_fim)}."
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
        # Só o participante cancela enquanto o evento está em andamento; depois
        # do fim (ou do arquivamento), a ação é do organizador.
        exigir_cancelamento_permitido(inscricao, por=request.user)
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

            if inscrito and not atividade.exige_inscricao:
                return JsonResponse(
                    {"status": "error",
                     "message": "Esta atividade não precisa de inscrição."},
                    status=400,
                )

            if inscrito: 
                # Inscrever usuário — recusa quando a atividade/evento fechou.
                motivo = motivo_inscricao_encerrada(atividade)
                if motivo:
                    raise InscricaoBloqueada(motivo)
                Inscricao.objects.get_or_create(participante=participante, atividade=atividade)
            else:
                # Cancelar inscrição: depois do fim do evento só o organizador;
                # o serviço também cancela a presença (com auditoria) e recusa
                # quando já há certificado.
                para_cancelar = Inscricao.objects.filter(
                    participante=participante, atividade=atividade
                ).first()
                if para_cancelar is not None:
                    exigir_cancelamento_permitido(para_cancelar, por=request.user)
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

    Atende aos papéis de uma vez — organizador (dono ou co-organizador),
    palestrante, equipe de apoio e participante são a mesma pessoa logada; o que
    muda, de um crachá para o outro, é o papel que ela tem em cada evento (e é
    isso que o crachá estampa).
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
                    exige_inscricao=form.cleaned_data.get('exige_inscricao', True),
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
                    exige_inscricao=form.cleaned_data.get('exige_inscricao', True),
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
            "foto": pessoa.get_foto_url(),
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


# -- Minhas palestras (área restrita do palestrante, sem dados de contato) --
class MinhasPalestrasView(LoginRequiredMixin, TemplateView):
    """Atividades em que a pessoa é palestrante (lista, QR e inscritos).

    A lista de inscritos fica numa tela à parte (`minha_palestra_inscritos`) e
    mostra nome + vínculo, nunca e-mail/CPF/matrícula.
    """

    template_name = "participante/minhas_palestras.html"

    def get_context_data(self, **kwargs):
        from eventos.crachas import atividades_do_palestrante

        contexto = super().get_context_data(**kwargs)
        contexto["atividades"] = atividades_do_palestrante(self.request.user)
        contexto["logo_url"] = url_da_logo()
        return contexto


@login_required(login_url='/accounts/login/')
def minha_palestra_inscritos(request, atividade_id):
    """Inscritos (e presenças) de uma atividade, para quem palestra nela.

    O palestrante precisa saber quem está na turma e quem já confirmou presença.
    Mostra nome + vínculo (`metadados.nome_com_vinculo`), mas **não** e-mail,
    CPF nem matrícula: contato é dado do participante e não é necessário para
    conduzir a atividade.

    Em atividade aberta (`exige_inscricao=False`) não há inscritos, então a
    lista mostra as presenças registradas — é a informação equivalente.
    """
    from django.http import HttpResponseForbidden

    from eventos.crachas import (
        pode_alterar_presenca_agora,
        pode_marcar_presenca_atividade,
        pode_ver_inscritos_atividade,
    )

    atividade = get_object_or_404(
        Atividade.objects.select_related("evento", "tipo"), id=atividade_id
    )
    if not pode_ver_inscritos_atividade(request.user, atividade):
        return HttpResponseForbidden(
            "Você não organiza este evento nem palestra nesta atividade."
        )

    presencas = list(
        Presenca.objects.filter(atividade=atividade)
        .select_related("participante", "participante__metadados")
        .order_by(
            "participante__first_name",
            "participante__last_name",
            "participante__id",
        )
    )
    presenca_por_pessoa = {presenca.participante_id: presenca for presenca in presencas}

    if atividade.exige_inscricao:
        pessoas = [
            inscricao.participante
            for inscricao in Inscricao.objects.filter(atividade=atividade)
            .select_related("participante", "participante__metadados")
            .order_by(
                "participante__first_name",
                "participante__last_name",
                "participante__id",
            )
        ]
    else:
        pessoas = [presenca.participante for presenca in presencas]

    linhas = [
        {"participante": pessoa, "presenca": presenca_por_pessoa.get(pessoa.id)}
        for pessoa in pessoas
    ]
    total_presentes = sum(1 for linha in linhas if linha["presenca"])
    total_inscritos = len(pessoas) if atividade.exige_inscricao else 0

    # O switch só aparece quando o usuário tem o papel E pode alterar agora:
    # palestrante apenas durante a atividade e antes de emitir certificados;
    # organização sempre. Fora da janela, mostramos o motivo no lugar do switch.
    tem_papel_presenca = pode_marcar_presenca_atividade(request.user, atividade)
    pode_marcar_presenca, motivo_presenca = pode_alterar_presenca_agora(
        request.user, atividade
    )

    return render(request, "participante/minha_palestra_inscritos.html", {
        "atividade": atividade,
        "evento": atividade.evento,
        "linhas": linhas,
        "exige_inscricao": atividade.exige_inscricao,
        "total_inscritos": total_inscritos,
        "total_presentes": total_presentes,
        "total_pendentes": max(total_inscritos - total_presentes, 0),
        "pode_marcar_presenca": pode_marcar_presenca,
        "motivo_presenca_bloqueada": (
            motivo_presenca if tem_papel_presenca and not pode_marcar_presenca else ""
        ),
    })


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
