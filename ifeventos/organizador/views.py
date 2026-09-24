from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from eventos.models import Atividade, Inscricao, Participante
from eventos import agenda
from django.contrib import messages
from django.utils.timezone import localtime
from django.utils.crypto import get_random_string
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
import json
from .forms import ParticipanteUpdateForm
from .decorators import organizador_required
from eventos.forms import EventoForm, PalestranteForm, TipoAtividadeForm
from eventos.forms import ChamadaProposicoesForm, EspacoForm, GradeVagasForm, VagaForm
from eventos.forms import (
    AssinanteForm,
    AssinaturaCertificadoFormSet,
    ConfiguracaoCertificadoForm,
)
from eventos.models import Assinante, ConfiguracaoCertificado
from eventos import certificados
from eventos.models import Evento
from eventos.forms import AtividadeForm
from eventos.models import Atividade
from eventos.models import ChamadaProposicoes, Espaco, TipoAtividade, Vaga
from eventos import propostas
from eventos.propostas import PropostaBloqueada
from eventos import triagem
from eventos import importacao_assistida
from eventos import copiloto_evento
from eventos import operacao
from eventos import comunicacao
from django.db.models import Count, Exists, OuterRef, Q
from asgiref.sync import sync_to_async, async_to_sync

from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from eventos.crachas import (
    atividade_aceita_presenca_agora,
    gerar_pdf_crachas_evento,
    modelo_de_cracha,
    pessoas_do_evento,
    pode_exibir_qr_atividade,
    pode_checkin_apoio,
    pode_gerenciar_evento,
)
from eventos.models import Inscricao

from eventos.imagens import imagem_cortada


# -- Dashboard do Organizador --
@login_required(login_url='/accounts/login/')
@organizador_required
def dashboard(request):
    organizador = get_object_or_404(Participante, id=request.user.id)  

    if organizador.is_superuser:
        eventos = Evento.objects.all() # Todos os eventos de todos os organizadores
    else:
        # Dono OU co-organizador: quem gerencia o evento o vê no painel.
        eventos = Evento.objects.filter(
            Q(organizador=organizador) | Q(organizadores=organizador)
        ).distinct()

    # Chamada de proposições: o cartão do evento mostra o atalho e quantas
    # propostas esperam decisão (sem uma query por cartão).
    eventos = eventos.annotate(
        n_pendentes=Count(
            "atividades", filter=Q(atividades__situacao=Atividade.SITUACAO_PENDENTE)
        ),
        tem_chamada=Exists(ChamadaProposicoes.objects.filter(evento=OuterRef("pk"))),
    )
    # Equipe de apoio por evento, para o modal do dashboard (1 query).
    eventos = eventos.prefetch_related("equipe")
    equipe_por_evento = {
        e.id: [
            {"id": p.id, "nome": p.get_full_name() or p.email}
            for p in e.equipe.all()
        ]
        for e in eventos
    }

    # if organizador.is_participante: # rever essa condição 
    #     inscricoes = Inscricao.objects.filter(participante=organizador) # Inscrições do organizador
    #     atividades = Atividade.objects.exclude(inscritos__participante=organizador)  # Atividades não inscritas
    # else:
    #     inscricoes = []
    #     atividades = []
        
    form = ParticipanteUpdateForm(instance=organizador) # Formulário para atualizar o perfil

    # print(">>> organizador.foto:", organizador.foto )

    if request.method == "POST":
        form = ParticipanteUpdateForm(data=request.POST,
                                    #    files=request.FILES,
                                       instance=organizador)
        if form.is_valid():
            organizador = form.save(commit=False)  # ⚠ Salvamos manualmente depois para capturar a imagem

            # A foto recortada (modal de perfil) tem prioridade sobre o arquivo
            # original enviado pelo input.
            recorte = imagem_cortada(request, f'perfil_{organizador.id}')
            if recorte:
                organizador.foto = recorte
            elif 'foto' in request.FILES:
                organizador.foto = request.FILES['foto']  # Atribuímos a imagem manualmente

            organizador.save()  # Agora salvamos no banco
            form.save_metadados(organizador)  # Campos extra do perfil (config)
            # form.save()

            return redirect("organizador:dashboard")
        # POST inválido: o modal precisa mostrar os erros. Sem isto o `perfil_form`
        # (context processor) vinha novo (sem os erros) e o usuário via o modal
        # "resetado", sem saber que nada foi salvo.
        messages.error(
            request,
            "Não foi possível salvar o perfil: "
            + "; ".join(
                m for mensagens in form.errors.values() for m in mensagens
            ),
        )

    contexto = {
        'eventos': eventos,
        'equipe_por_evento': equipe_por_evento,
        'form': form,
        'is_participante': organizador.is_participante,
        'organizador': organizador,
        'form_evt': EventoForm(),
    }
    if request.method == "POST" and not form.is_valid():
        contexto['perfil_form'] = form      # formulário ligado, com os erros
        contexto['perfil_abrir'] = True     # abre o modal para o usuário ver
    return render(request, 'organizador/dashboard.html', contexto)

# -- Profile --

@login_required(login_url='/accounts/login/')
def profile(request):
    usuario = get_object_or_404(Participante, id=request.user.id)  
    form = ParticipanteUpdateForm(instance=usuario) # Formulário para atualizar o perfil
    if request.method == "POST":
        form = ParticipanteUpdateForm(data=request.POST,
                                    #    files=request.FILES,
                                       instance=usuario)
        
        if form.is_valid():
            usuario = form.save(commit=False)  # ⚠ Salvamos manualmente depois para capturar a imagem

            # A foto recortada (modal de perfil) tem prioridade sobre o arquivo
            # original enviado pelo input.
            recorte = imagem_cortada(request, f'perfil_{usuario.id}')
            if recorte:
                usuario.foto = recorte
            elif 'foto' in request.FILES:
                usuario.foto = request.FILES['foto']  # Atribuímos a imagem manualmente

            usuario.save()  # Agora salvamos no banco
            form.save_metadados(usuario)  # Campos extra do perfil (config)
            messages.success(request, "Perfil atualizado com sucesso!")
            return redirect("organizador:profile")
        
    return render(request, 'organizador/form_profile.html', {'form': form })


@login_required(login_url='/accounts/login/')
def importar_metadados(request):
    """Importa metadados do participante por CSV (organizador/superuser).

    O arquivo atualiza quem já existe (chave = e-mail); campo que não se aplica
    ao vínculo é ignorado com aviso. Ver `eventos/importacao.py`.
    """
    from eventos import importacao

    if not (request.user.is_superuser or getattr(request.user, "is_organizador", False)):
        messages.warning(request, "Apenas organizadores podem importar metadados.")
        return redirect("organizador:dashboard")

    relatorio = None
    if request.method == "POST":
        arquivo = request.FILES.get("arquivo")
        if not arquivo:
            messages.warning(request, "Selecione um arquivo CSV.")
        else:
            relatorio = importacao.importar(arquivo)

    return render(request, "organizador/importar_metadados.html", {
        "cabecalhos": importacao.cabecalhos(),
        "relatorio": relatorio,
    })


@login_required(login_url='/accounts/login/')
@organizador_required
def modelo_metadados_csv(request):
    """Baixa o CSV-modelo (só o cabeçalho) com as colunas configuradas."""
    import csv

    from django.http import HttpResponse

    from eventos import importacao

    if not (request.user.is_superuser or getattr(request.user, "is_organizador", False)):
        raise PermissionDenied(
            "Apenas organizadores podem baixar o modelo de metadados."
        )

    resposta = HttpResponse(content_type="text/csv; charset=utf-8")
    resposta["Content-Disposition"] = 'attachment; filename="modelo_metadados.csv"'
    resposta.write("\ufeff")  # BOM: Excel abre os acentos corretamente
    escritor = csv.writer(resposta)
    escritor.writerow(importacao.cabecalhos())
    return resposta
    



# -- Eventos --

@login_required(login_url='/accounts/login/')
def criar_evento(request):
    """Cria um novo evento associado ao organizador autenticado via modal"""

    if not (request.user.is_superuser or getattr(request.user, "is_organizador", False)):
        return JsonResponse({"success": False, "errors": "Apenas organizadores podem criar eventos."}, status=403)

    organizador = get_object_or_404(Participante, id=request.user.id) 

    if request.method == "POST":
        form = EventoForm(request.POST, request.FILES) # request.FILES é necessário para arquivos
        if form.is_valid():
            evento = form.save(commit=False)
            evento.organizador = organizador
            # Capa recortada no modal de criação (16:9) tem prioridade.
            recorte = imagem_cortada(request, 'evento')
            if recorte:
                evento.imagem = recorte
            evento.save()
            messages.success(request, "Evento criado com sucesso!")
            # Vai direto para a edição: é onde ficam o copiloto e a divulgação.
            return JsonResponse({
                "success": True,
                "message": "Evento criado com sucesso!",
                "redirect": reverse("organizador:editar_evento", args=[evento.id]),
            })
        else:
            messages.warning(request, "Erro ao criar evento.")
            return JsonResponse({"success": False, "errors": form.errors}, status=400)
    
    # A criação de evento é feita pelo modal do dashboard (POST por AJAX, que
    # devolve JSON). Esta rota não tem página própria: antes ela renderizava o
    # template de edição sem o objeto `evento`, e a página morria com
    # NoReverseMatch (erro 500) ao tentar montar a URL de edição. Redireciona
    # para o painel, que é onde o modal de criação vive.
    return redirect('organizador:dashboard')



@login_required(login_url='/accounts/login/')
def editar_evento(request, evento_id):
    """Permite editar um evento"""
    
    _, evento = get_user_and_evento(request, evento_id)

    if request.method == "POST":
        form = EventoForm(data=request.POST, files=request.FILES,  instance=evento)
        if form.is_valid():
            evento = form.save(commit=False)

            # A capa recortada tem prioridade sobre o arquivo original enviado
            # pelo input.
            recorte = imagem_cortada(request, 'evento')
            if recorte:
                evento.imagem = recorte
            elif 'imagem' in request.FILES:
                evento.imagem = request.FILES['imagem']  # Atribuímos a imagem manualmente

            evento.save()
            
            messages.success(request, "Evento atualizado com sucesso!")
            return redirect('organizador:dashboard')
    else:
        form = EventoForm(instance=evento)

    return render(request, 'organizador/form_evento.html', {
        'form': form, 'evento': evento,
        # Títulos das atividades publicadas: a IA pode mencioná-los na descrição.
        'programacao_titulos': list(
            evento.atividades.filter(publicada=True)
            .order_by('data_hora_inicio')
            .values_list('titulo', flat=True)[:8]
        ),
        # Co-organizadores: o painel da tela de edição.
        'organizadores': evento.organizadores.order_by('first_name', 'email'),
        'pode_gerenciar_coorganizadores': (
            request.user.is_superuser
            or evento.organizador_id == request.user.id
        ),
    })



def get_user_and_evento(request, evento_id):
    organizador = get_object_or_404(Participante, id=request.user.id)
    if organizador.is_superuser:
        evento = get_object_or_404(Evento, id=evento_id)
    else:
        # Dono OU co-organizador: ambos gerenciam o evento (só excluir é do dono).
        evento = get_object_or_404(
            Evento.objects.filter(
                Q(organizador=organizador) | Q(organizadores=organizador)
            ).distinct(),
            id=evento_id,
        )
    return organizador, evento


def _evento_do_dono(request, evento_id):
    """O evento apenas para o DONO (ou superuser) — usado onde co-organizador não decide."""
    organizador = get_object_or_404(Participante, id=request.user.id)
    if organizador.is_superuser:
        return get_object_or_404(Evento, id=evento_id)
    return get_object_or_404(Evento, id=evento_id, organizador=organizador)


def _exige_organizador(request):
    """Recusa (403) quem não tem a flag de organizador nem é superuser."""
    if not (request.user.is_superuser or getattr(request.user, "is_organizador", False)):
        raise PermissionDenied("Apenas organizadores podem fazer isto.")



@login_required(login_url='/accounts/login/')
def excluir_evento(request, evento_id):
    """Exclui um evento"""
    organizador = get_object_or_404(Participante, id=request.user.id)

    if organizador.is_superuser:
        evento = get_object_or_404(Evento, id=evento_id)
    else:
        evento = get_object_or_404(Evento, id=evento_id, organizador=organizador)


    evento.delete()
    messages.success(request, "Evento excluído com sucesso!")
    return redirect('organizador:dashboard')





# -- Atividades --
@login_required(login_url='/accounts/login/')
def atividades_evento(request, evento_id):
    """Lista as atividades de um evento (lista ou grade) + conflitos da grade."""
    evento = _evento_gerenciavel(request, evento_id)
    # Ordem padrão: quem tem mais inscritos primeiro. O desempate por horário e
    # id mantém a lista ESTÁVEL (sem "pular" a cada recarregamento) quando duas
    # atividades têm a mesma quantidade de inscritos.
    atividades = list(
        evento.atividades.all().order_by("-n_inscricoes", "data_hora_inicio", "id")
    )
    # Rascunhos primeiro, num bloco separado: é o que precisa de gerenciamento.
    rascunhos = [a for a in atividades if not a.publicada]
    publicadas = [a for a in atividades if a.publicada]
    # A grade trabalha em ordem cronológica e precisa do tipo/palestrantes.
    para_grade = (
        evento.atividades.select_related("tipo")
        .prefetch_related("palestrantes")
        .order_by("data_hora_inicio", "id")
    )

    form = AtividadeForm(initial={'evento': evento})

    vista_atividades = request.GET.get("vista", "lista")
    if vista_atividades not in ("lista", "grade"):
        vista_atividades = "lista"

    return render(request, 'organizador/atividades_evento.html', {
        'form_ativ' : form, 'evento': evento, 'atividades': atividades,
        'rascunhos': rascunhos, 'publicadas': publicadas,
        'grade': agenda.montar_grade(para_grade),
        'choques': agenda.choques(para_grade),
        'vista_atividades': vista_atividades,
        'vistas_atividades': [
            {"valor": "lista", "rotulo": "Lista", "icone": "fa-solid fa-list"},
            {"valor": "grade", "rotulo": "Grade", "icone": "fa-solid fa-table-cells"},
        ],
        'modelos_cracha': Evento.MODELO_CRACHA_CHOICES,
    }) 


# -- Equipe de apoio do evento -------------------------------------------
@login_required(login_url='/accounts/login/')
@require_POST
def equipe_apoio_adicionar(request, evento_id):
    """Adiciona uma pessoa à equipe de apoio do evento, pelo e-mail.

    Conta já existente (participante/palestrante) é REAPROVEITADA: ela só
    ganha a flag `is_equipe` e o vínculo. E-mail novo cria uma conta mínima
    (senha temporária devolvida UMA vez, para o organizador repassar).
    """
    _, evento = get_user_and_evento(request, evento_id)
    email = (request.POST.get("email") or "").strip().lower()
    if not email:
        return JsonResponse({"success": False, "erro": "Informe o e-mail."}, status=400)

    try:
        pessoa = Participante.objects.get(email__iexact=email)
    except Participante.DoesNotExist:
        from allauth.account.models import EmailAddress

        senha_temporaria = get_random_string(8)
        pessoa = Participante.objects.create_user(
            email=email,
            password=senha_temporaria,
            is_participante=False,
            is_equipe=True,
        )
        # O organizador criou a conta e avaliza a pessoa: o e-mail nasce
        # verificado (senão, com ACCOUNT_EMAIL_VERIFICATION='mandatory', ela
        # não conseguiria entrar antes de confirmar o e-mail).
        EmailAddress.objects.create(
            user=pessoa, email=pessoa.email, verified=True, primary=True
        )
        reusada = False
    else:
        senha_temporaria = None
        reusada = True
        if not pessoa.is_equipe:
            pessoa.is_equipe = True
            pessoa.save(update_fields=["is_equipe"])

    evento.equipe.add(pessoa)
    return JsonResponse({
        "success": True,
        "pessoa_id": pessoa.id,
        "nome": pessoa.get_full_name() or pessoa.email,
        "reusada": reusada,
        "senha_temporaria": senha_temporaria,
    })


@login_required(login_url='/accounts/login/')
@require_POST
def equipe_apoio_remover(request, evento_id):
    """Tira a pessoa da equipe de apoio do evento (não apaga a conta)."""
    _, evento = get_user_and_evento(request, evento_id)
    pessoa_id = request.POST.get("pessoa_id") or ""
    if pessoa_id.isdigit():
        evento.equipe.remove(int(pessoa_id))
    return JsonResponse({"success": True}) 


# -- Co-organizadores do evento (só o dono/superuser gerencia o time) --------
@login_required(login_url='/accounts/login/')
@require_POST
def coorganizador_adicionar(request, evento_id):
    """Adiciona um co-organizador ao evento, pelo e-mail.

    Conta existente é reaproveitada (e ganha is_organizador=True se não tiver).
    E-mail novo cria uma conta mínima de organizador (senha temporária devolvida
    UMA vez, e-mail já verificado). Só o dono/superuser pode.
    """
    evento = _evento_do_dono(request, evento_id)
    email = (request.POST.get("email") or "").strip().lower()
    if not email:
        return JsonResponse({"success": False, "erro": "Informe o e-mail."}, status=400)

    try:
        pessoa = Participante.objects.get(email__iexact=email)
    except Participante.DoesNotExist:
        from allauth.account.models import EmailAddress

        senha_temporaria = get_random_string(8)
        pessoa = Participante.objects.create_user(
            email=email,
            password=senha_temporaria,
            is_participante=False,
            is_organizador=True,
        )
        EmailAddress.objects.create(
            user=pessoa, email=pessoa.email, verified=True, primary=True
        )
        reusada = False
    else:
        senha_temporaria = None
        reusada = True
        if not pessoa.is_organizador:
            pessoa.is_organizador = True
            pessoa.save(update_fields=["is_organizador"])

    evento.organizadores.add(pessoa)
    return JsonResponse({
        "success": True,
        "pessoa_id": pessoa.id,
        "nome": pessoa.get_full_name() or pessoa.email,
        "reusada": reusada,
        "senha_temporaria": senha_temporaria,
    })


@login_required(login_url='/accounts/login/')
@require_POST
def coorganizador_remover(request, evento_id):
    """Tira a pessoa dos co-organizadores (não apaga a conta). Só o dono."""
    evento = _evento_do_dono(request, evento_id)
    pessoa_id = request.POST.get("pessoa_id") or ""
    if pessoa_id.isdigit():
        evento.organizadores.remove(int(pessoa_id))
    return JsonResponse({"success": True}) 


# -- cria Atividade usando o modal --
@login_required(login_url='/accounts/login/')
def criar_atividade(request):
    """Cria uma nova atividade associada a um evento"""
    # print("request.POST.get('evento'): ",request.POST.get('evento'))
   
    evento_id = request.POST.get('evento') # Recupera o id do evento via POST
    evento = _evento_gerenciavel(request, evento_id)
    if request.method == "POST":
        # request.FILES é indispensável: sem ele o navegador envia a imagem e o
        # Django simplesmente ignora o arquivo, gravando a atividade sem foto.
        form = AtividadeForm(request.POST, request.FILES)
        if form.is_valid():
            atividade = form.save(commit=False)
            atividade.evento = evento # Garante que o evento está correto
            atividade.save()
            form.save_m2m()  # Salva os campos ManyToMany corretamente
            messages.success(request, "Atividade criada com sucesso!")
            return redirect('organizador:atividades_evento', evento_id=evento_id)
    else:
        form = AtividadeForm()
    

    return render(request, 'organizador/form_atividade.html', {
        'form_ativ': form, 'evento': evento,
        'nomes_conhecidos': propostas.nomes_conhecidos(),
        'form_local': EspacoForm(prefix="local"),
    })



@login_required(login_url='/accounts/login/')
def criar_editar_atividade(request, evento_id, atividade_id=None):
    """Cria ou edita uma atividade associada a um evento"""
    
    evento = _evento_gerenciavel(request, evento_id)

    if atividade_id:  # Se houver um ID, estamos editando
        atividade = get_object_or_404(Atividade, id=atividade_id, evento=evento)
    else:  # Se não houver um ID, estamos criando uma nova atividade
        atividade = None
        form = AtividadeForm(files=request.FILES)  # request.FILES é necessário para arquivos


    if request.method == "POST":
        form = AtividadeForm(data=request.POST, files=request.FILES, instance=atividade)
        if form.is_valid():
            atividade = form.save(commit=False)

            # A imagem recortada tem prioridade sobre o arquivo original.
            recorte = imagem_cortada(request, 'atividade')
            if recorte:
                atividade.imagem = recorte
            elif 'imagem' in request.FILES:
                atividade.imagem = request.FILES['imagem']  # Atribuímos a imagem manualmente

            atividade.evento = evento  # Garante que o evento está correto
            atividade.save()
            form.save_m2m()  # Salva os campos ManyToMany corretamente

            
            messages.success(request, "Atividade salva com sucesso!")
            return redirect('organizador:atividades_evento', evento_id=evento_id)
    else:
        form = AtividadeForm(instance=atividade)  # Preenche o form se for edição

    # O campo `evento` saiu do formulário: o vínculo é garantido pelo
    # `atividade.evento = evento` acima, e a tela mostra o evento como
    # contexto no topo (antes o select podia ser trocado sem efeito).

    return render(request, 'organizador/form_atividade.html', {
        'form_ativ': form,
        'evento': evento,
        'atividade': atividade,  # Para o template saber se é criação ou edição
        'nomes_conhecidos': propostas.nomes_conhecidos(),
        'form_local': EspacoForm(prefix="local"),
    })



@login_required(login_url='/accounts/login/')
def editar_atividade(request, atividade_id):
    """Permite editar uma atividade"""
    atividade = get_object_or_404(Atividade, id=atividade_id)
    _evento_gerenciavel(request, atividade.evento_id)
    evento = atividade.evento

    if request.method == "POST":
        # Mesmo caso do criar_atividade: sem request.FILES a imagem enviada é
        # descartada e a atividade continua com a imagem antiga (ou sem nenhuma).
        form = AtividadeForm(request.POST, request.FILES, instance=atividade)
        if form.is_valid():
            form.save()
            messages.success(request, "Atividade atualizada com sucesso!")
            return redirect('organizador:atividades_evento', evento_id=evento.id)
    else:
        form = AtividadeForm(instance=atividade)

    return render(request, 'organizador/form_atividade.html', {
        'form_ativ': form, 'atividade': atividade, 'evento': evento,
        'nomes_conhecidos': propostas.nomes_conhecidos(),
        'form_local': EspacoForm(prefix="local"),
    })


@login_required(login_url='/accounts/login/')
def excluir_atividade(request, atividade_id):
    """Exclui uma atividade"""
    atividade = get_object_or_404(Atividade, id=atividade_id)
    _evento_gerenciavel(request, atividade.evento_id)
    evento = atividade.evento
    atividade.delete()
    messages.success(request, "Atividade excluída com sucesso!")
    return redirect('organizador:atividades_evento', evento_id=evento.id)






# -- Palestrantes e Tipos de Atividade --
@login_required(login_url='/accounts/login/')
def adicionar_palestrante(request):
    if not (request.user.is_superuser or getattr(request.user, "is_organizador", False)):
        return JsonResponse({"success": False, "errors": "Apenas organizadores."}, status=403)
    # print("request.POST: ", request.POST)
    # print("request.FILES: ", request.FILES)
    if request.method == "POST":
        form = PalestranteForm(request.POST, request.FILES) # request.FILES é necessário para arquivos
        if form.is_valid():
            palestrante = form.save(commit=False)  # ⚠ Salvamos manualmente depois para capturar a imagem

            # Foto recortada no modal tem prioridade sobre o arquivo original.
            recorte = imagem_cortada(request, 'palestrante')
            if recorte:
                palestrante.foto = recorte
            elif 'foto' in request.FILES:
                palestrante.foto = request.FILES['foto']  # Atribuímos a imagem manualmente

            palestrante.is_palestrante = True  # Garantimos que é palestrante    

            palestrante.save()  # Agora salvamos no banco
            return JsonResponse({"success": True, "id": palestrante.id, "nome": palestrante.first_name + " " + palestrante.last_name})
        return JsonResponse({"success": False, "errors": form.errors})
    return JsonResponse({"success": False, "message": "Método inválido"})



@login_required(login_url='/accounts/login/')
def adicionar_tipo_atividade(request):
    if not (request.user.is_superuser or getattr(request.user, "is_organizador", False)):
        return JsonResponse({"success": False, "errors": "Apenas organizadores."}, status=403)
    if request.method == "POST":
        form = TipoAtividadeForm(request.POST)
        if form.is_valid():
            tipo = form.save()
            return JsonResponse({"success": True, "id": tipo.id, "nome": tipo.nome})
        return JsonResponse({"success": False, "errors": form.errors})
    return JsonResponse({"success": False, "message": "Método inválido"})


@login_required(login_url='/accounts/login/')
def adicionar_espaco_ajax(request):
    """Cadastra um espaço no catálogo da escola via modal do formulário de atividade."""
    if not (request.user.is_superuser or getattr(request.user, "is_organizador", False)):
        return JsonResponse({"success": False, "errors": "Apenas organizadores."}, status=403)
    if request.method == "POST":
        form = EspacoForm(request.POST, prefix="local")
        if form.is_valid():
            espaco = form.save()
            return JsonResponse({"success": True, "id": espaco.id, "nome": espaco.nome})
        return JsonResponse({"success": False, "errors": form.errors})
    return JsonResponse({"success": False, "message": "Método inválido"})





# -- Certificados --


class EmitirCertificadoInscricaoView(LoginRequiredMixin, View):
    """
    View para que o organizador emita um certificado para uma inscrição confirmada.
    """
    def post(self, request, inscricao_id):
        inscricao = get_object_or_404(Inscricao, id=inscricao_id)
        if not pode_gerenciar_evento(request.user, inscricao.atividade.evento):
            raise PermissionDenied("Você não organiza o evento desta inscrição.")

        if inscricao.certificado_emitido:
            return JsonResponse({"message": "Certificado já emitido para esta inscrição!", "certificado": False})

        _certificado, criado = certificados.emitir(
            inscricao.participante, atividade=inscricao.atividade
        )
        if not criado:
            return JsonResponse({"message": "Certificado já emitido para esta inscrição!", "certificado": False})

        inscricao.certificado_emitido = True
        inscricao.save(update_fields=["certificado_emitido"])

        return JsonResponse({"message": "Certificado emitido com sucesso!", "certificado": True})




class EmitirCertificadosAtividadeView(LoginRequiredMixin, View):
    """
    View para que o organizador emita certificados de uma atividade encerrada para participantes confirmados.
    """
    def post(self, request, atividade_id):
        atividade = get_object_or_404(Atividade, id=atividade_id)
        if not pode_gerenciar_evento(request.user, atividade.evento):
            raise PermissionDenied("Você não organiza o evento desta atividade.")
        inscritos = certificados.participantes_da_atividade(atividade)

        certificados_gerados = []
        for pessoa in inscritos:
            _certificado, criado = certificados.emitir(pessoa, atividade=atividade)
            if criado:
                certificados_gerados.append(pessoa.id)

        if certificados_gerados:
            Inscricao.objects.filter(
                atividade=atividade, participante_id__in=certificados_gerados
            ).update(certificado_emitido=True)

        return JsonResponse({"message": "Certificados gerados com sucesso!", "certificados": certificados_gerados})







class ModeloCrachaEventoView(LoginRequiredMixin, View):
    """Define o modelo dos crachás do evento (quem decide é o organizador).

    O participante não escolhe: ele recebe o modelo do evento. Antes cada um
    escolhia o seu, e o mesmo evento saía com crachás de dois desenhos.
    """

    def post(self, request, evento_id):
        evento = get_object_or_404(Evento, id=evento_id)
        if not pode_gerenciar_evento(request.user, evento):
            raise PermissionDenied("Você não organiza este evento.")

        modelo = modelo_de_cracha(request.POST.get("modelo"))
        if evento.modelo_cracha != modelo:
            evento.modelo_cracha = modelo
            evento.save(update_fields=["modelo_cracha", "updated_at"])
            messages.success(
                request,
                "Modelo dos crachás deste evento: "
                + dict(Evento.MODELO_CRACHA_CHOICES).get(modelo, modelo)
                + ". O participante passa a ver e imprimir este.",
            )
        return redirect("organizador:atividades_evento", evento.id)


class EmitirCertificadosEventoView(LoginRequiredMixin, View):
    def post(self, request, evento_id):
        evento = get_object_or_404(Evento, id=evento_id)
        if not pode_gerenciar_evento(request.user, evento):
            raise PermissionDenied("Você não organiza este evento.")

        config = certificados.config_do_evento(evento)
        gerados = []
        for pessoa in certificados.participantes_do_evento(evento, config):
            _certificado, criado = certificados.emitir(pessoa, evento=evento)
            if criado:
                gerados.append(pessoa.id)

        return JsonResponse({"message": "Certificados emitidos para o evento!", "certificados": gerados})


# -- Configuração de certificados e catálogo de assinantes --


class CertificadoConfigView(LoginRequiredMixin, View):
    """Configura o certificado do evento: texto, layout e assinaturas (1–2)."""

    template_name = "organizador/certificado_config.html"

    def _get_evento(self, request, evento_id):
        evento = get_object_or_404(Evento, id=evento_id)
        if not pode_gerenciar_evento(request.user, evento):
            raise PermissionDenied("Você não organiza este evento.")
        return evento

    def _contexto(self, evento, form, formset):
        return {
            "evento": evento,
            "form": form,
            "formset": formset,
            "assinantes": Assinante.objects.filter(ativo=True),
            "config": certificados.config_do_evento(evento),
        }

    def get(self, request, evento_id):
        evento = self._get_evento(request, evento_id)
        config = certificados.config_do_evento(evento)
        if config is None:
            config = ConfiguracaoCertificado.objects.create(evento=evento)
        form = ConfiguracaoCertificadoForm(instance=config)
        formset = AssinaturaCertificadoFormSet(instance=config)
        return render(request, self.template_name, self._contexto(evento, form, formset))

    def post(self, request, evento_id):
        evento = self._get_evento(request, evento_id)
        config = certificados.config_do_evento(evento)
        if config is None:
            config = ConfiguracaoCertificado.objects.create(evento=evento)
        form = ConfiguracaoCertificadoForm(request.POST, request.FILES, instance=config)
        formset = AssinaturaCertificadoFormSet(request.POST, request.FILES, instance=config)
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            # A ordem é a posição na tela (1, 2): o organizador não digita.
            for i, assinatura in enumerate(config.assinaturas.order_by("id"), start=1):
                if assinatura.ordem != i:
                    assinatura.ordem = i
                    assinatura.save(update_fields=["ordem"])
            messages.success(request, "Configuração do certificado salva.")
            return redirect("organizador:certificado_config", evento.id)
        messages.warning(request, "Confira os campos destacados.")
        return render(request, self.template_name, self._contexto(evento, form, formset))


class CertificadoPreviewView(LoginRequiredMixin, View):
    """PDF de amostra do certificado (usa o organizador como exemplo)."""

    def get(self, request, evento_id):
        evento = get_object_or_404(Evento, id=evento_id)
        if not pode_gerenciar_evento(request.user, evento):
            raise PermissionDenied("Você não organiza este evento.")
        config = certificados.config_do_evento(evento)
        atividade = evento.atividades.filter(emite_certificado=True).first()
        arquivo = certificados.gerar_certificado(
            request.user, atividade=atividade, evento=evento, config=config
        )
        resposta = HttpResponse(arquivo.read(), content_type="application/pdf")
        resposta["Content-Disposition"] = 'inline; filename="certificado_amostra.pdf"'
        return resposta


def _pode_gerir_assinantes(user):
    return bool(
        user.is_superuser
        or user.is_staff
        or getattr(user, "is_organizador", False)
    )


class AssinantesView(LoginRequiredMixin, View):
    """Catálogo reutilizável de assinantes (organizador e staff)."""

    template_name = "organizador/assinantes.html"

    def get(self, request):
        if not _pode_gerir_assinantes(request.user):
            raise PermissionDenied("Área restrita a organizadores.")
        return render(request, self.template_name, {
            "assinantes": Assinante.objects.all(),
            "form": AssinanteForm(),
        })

    def post(self, request):
        if not _pode_gerir_assinantes(request.user):
            raise PermissionDenied("Área restrita a organizadores.")
        form = AssinanteForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, "Assinante cadastrado.")
            return redirect("organizador:assinantes")
        return render(request, self.template_name, {
            "assinantes": Assinante.objects.all(),
            "form": form,
        })


class AssinanteRemoverView(LoginRequiredMixin, View):
    def post(self, request, assinante_id):
        if not _pode_gerir_assinantes(request.user):
            raise PermissionDenied("Área restrita a organizadores.")
        Assinante.objects.filter(id=assinante_id).delete()
        messages.success(request, "Assinante removido.")
        return redirect("organizador:assinantes")


# -- Crachás --


class CrachasEventoView(LoginRequiredMixin, View):
    """PDF com os crachás de todas as pessoas com papel no evento.

    Quatro crachás por folha A4 (105 x 148,5 mm cada), no modelo que o
    organizador escolhe na hora de gerar: "etiqueta" (fundo colorido com a foto
    do evento) ou "classico" (tarja verde e faixa do evento). Serve para
    imprimir em lote e entregar no credenciamento, sem montar crachá por crachá.
    """

    def get(self, request, evento_id):
        evento = get_object_or_404(Evento, id=evento_id)

        # Mesma regra usada pela API e pelo check-in (eventos/crachas.py).
        if not pode_gerenciar_evento(request.user, evento):
            raise PermissionDenied("Você não organiza este evento.")

        # Sem ninguém com papel, sairia um PDF sem página: melhor avisar.
        if not pessoas_do_evento(evento):
            messages.warning(
                request,
                "Ainda não há ninguém com crachá neste evento. Quem se inscrever, "
                "palestrar ou organizar aparece aqui.",
            )
            return redirect("organizador:atividades_evento", evento.id)

        # O modelo é decisão do organizador, guardada no evento: o participante
        # recebe exatamente esse e o evento não sai com dois desenhos.
        modelo = modelo_de_cracha(evento.modelo_cracha)
        nome_arquivo, conteudo = gerar_pdf_crachas_evento(evento, modelo)
        resposta = HttpResponse(conteudo.read(), content_type="application/pdf")
        resposta["Content-Disposition"] = f'inline; filename="{nome_arquivo}"'
        return resposta


class QrAtividadeView(LoginRequiredMixin, View):
    """Tela que exibe o QR de presença da atividade, para projetar ou mostrar na porta.

    O código em si é gerado pela API (`/api/v1/atividades/<id>/qrcode/`) e renovado
    pela própria página, de tempos em tempos — é o que faz uma foto compartilhada
    do QR deixar de funcionar depois de alguns minutos.
    """

    template_name = "organizador/atividade_qrcode.html"

    def get(self, request, atividade_id):
        atividade = get_object_or_404(Atividade, id=atividade_id)
        if not pode_exibir_qr_atividade(request.user, atividade):
            raise PermissionDenied("Você não organiza este evento nem palestra nesta atividade.")
        return render(request, self.template_name, {
            "atividade": atividade,
            "evento": atividade.evento,
            # A tela é liberada também para quem PALESTRA na atividade e para a
            # equipe de apoio, mas desfazer presença exige gerenciar o evento ou
            # ser da equipe dele (mesma regra da API). Sem separar as duas, o
            # palestrante veria um ✕ que sempre falha.
            "pode_desfazer": pode_checkin_apoio(request.user, atividade.evento),
        })


class CheckinAtividadeView(LoginRequiredMixin, View):
    """Check-in da atividade pela câmera do navegador (fluxo A1).

    A página liga a câmera, lê o QR do crachá de cada pessoa e registra a
    presença sozinha — a organização aponta e pronto, sem clicar em nome algum.
    O campo de código fica ao lado para quem estiver sem celular ou com o crachá
    amassado, e a lista mostra quem já entrou, com opção de desfazer.
    """

    template_name = "organizador/atividade_checkin.html"

    def get(self, request, atividade_id):
        atividade = get_object_or_404(Atividade, id=atividade_id)
        if not pode_checkin_apoio(request.user, atividade.evento):
            raise PermissionDenied("Você não organiza o evento nem é da equipe de apoio dele.")

        janela_aberta, motivo = atividade_aceita_presenca_agora(atividade)
        voltar_url = reverse("organizador:atividades_evento", args=[atividade.evento_id])
        if (getattr(request.user, "is_equipe", False)
                and not pode_gerenciar_evento(request.user, atividade.evento)):
            voltar_url = reverse("apoio:evento", args=[atividade.evento_id])
        return render(request, self.template_name, {
            "atividade": atividade,
            "evento": atividade.evento,
            "voltar_url": voltar_url,
            "janela_aberta": janela_aberta,
            "janela_motivo": motivo,
        })


@login_required(login_url='/accounts/login/')
@require_POST
def publicar_atividade(request, atividade_id):
    """Alterna rascunho/publicada (organizador do evento/superuser)."""
    atividade = get_object_or_404(Atividade, id=atividade_id)
    _evento_gerenciavel(request, atividade.evento_id)
    atividade.publicada = not atividade.publicada
    atividade.save(update_fields=["publicada"])
    messages.success(
        request,
        "Atividade publicada na programação." if atividade.publicada
        else "Atividade voltou para rascunho.",
    )
    return redirect("organizador:atividades_evento", evento_id=atividade.evento_id)


# -- Chamada de proposições de atividades --
def _evento_gerenciavel(request, evento_id):
    """Busca o evento e recusa (403) quem não o gerencia."""
    evento = get_object_or_404(Evento, id=evento_id)
    if not pode_gerenciar_evento(request.user, evento):
        raise PermissionDenied("Você não gerencia este evento.")
    return evento


def _erros_do_form(form):
    return "; ".join(m for mensagens in form.errors.values() for m in mensagens)


@login_required(login_url='/accounts/login/')
def chamada_proposicoes(request, evento_id):
    """Tela da chamada: janela de proposições, espaços e grade de vagas."""
    evento = _evento_gerenciavel(request, evento_id)
    chamada = propostas.chamada_de(evento)
    # Catálogo da escola (reaproveitado entre eventos): os espaços que ESTE
    # evento já usa aparecem primeiro, para o organizador não se perder.
    espacos_usados = set(
        Vaga.objects.filter(evento=evento).values_list("espaco_id", flat=True)
    )
    espacos = sorted(
        Espaco.objects.all(), key=lambda e: (e.pk not in espacos_usados, e.nome)
    )
    return render(request, 'organizador/chamada_proposicoes.html', {
        'evento': evento,
        'chamada': chamada,
        'form_chamada': ChamadaProposicoesForm(instance=chamada, prefix='chamada'),
        'form_espaco': EspacoForm(prefix='espaco'),
        # O modal de edição usa OUTRO prefixo para não colidir com os ids do
        # formulário de "adicionar" (os dois convivem na mesma página).
        'form_espaco_modal': EspacoForm(prefix='espaco_modal'),
        'form_vaga': VagaForm(evento=evento, prefix='vaga'),
        'form_vaga_modal': VagaForm(evento=evento, prefix='vaga_modal'),
        'form_grade': GradeVagasForm(evento=evento, prefix='grade'),
        # `?abrir=espaco|vaga` reabre o formulário depois de um erro de validação.
        'abrir': (request.GET.get('abrir') or '').strip(),
        'espacos': espacos,
        'espacos_usados': espacos_usados,
        'nomes_conhecidos': propostas.nomes_conhecidos(),
        'vagas': propostas.vagas_do_evento(evento),
        'n_pendentes': propostas.contagem_pendentes([evento]),
        'aberta': propostas.esta_aberta(evento),
        'situacao': propostas.situacao(evento),
    })


@login_required(login_url='/accounts/login/')
@require_POST
def salvar_chamada(request, evento_id):
    """Cria/atualiza a janela de proposições (e liga/desliga o aceite)."""
    evento = _evento_gerenciavel(request, evento_id)
    form = ChamadaProposicoesForm(
        request.POST, instance=propostas.chamada_de(evento), prefix='chamada'
    )
    if form.is_valid():
        chamada = form.save(commit=False)
        chamada.evento = evento
        chamada.save()
        messages.success(
            request,
            "Chamada salva e aberta." if chamada.esta_aberta()
            else "Chamada salva (fora da janela / desligada).",
        )
    else:
        messages.error(request, f"Confira a chamada: {_erros_do_form(form)}")
    return redirect('organizador:chamada_proposicoes', evento_id=evento.id)


@login_required(login_url='/accounts/login/')
@require_POST
def adicionar_espaco(request, evento_id):
    """Cadastra um espaço no catálogo da escola (vale para os próximos eventos)."""
    evento = _evento_gerenciavel(request, evento_id)
    form = EspacoForm(request.POST, prefix='espaco')
    if form.is_valid():
        espaco = form.save()
        messages.success(
            request,
            f"Espaço '{espaco.nome}' disponível no catálogo para todos os eventos.",
        )
        return redirect('organizador:chamada_proposicoes', evento_id=evento.id)

    # Deu erro: volta com o formulário ABERTO (o aviso sozinho não bastaria,
    # o usuário teria de reabrir o collapse para corrigir).
    messages.error(request, f"Confira o espaço: {_erros_do_form(form)}")
    return redirect(
        reverse('organizador:chamada_proposicoes', args=[evento.id])
        + "?abrir=espaco#espacos"
    )


@login_required(login_url='/accounts/login/')
@require_POST
def editar_espaco(request, evento_id, espaco_id):
    """Edita nome/capacidade de um espaço do catálogo.

    Renomear NÃO reescreve o `local` das atividades já criadas (ele é texto,
    copiado no momento da proposta) — vale para as próximas.
    """
    evento = _evento_gerenciavel(request, evento_id)
    espaco = get_object_or_404(Espaco, id=espaco_id)
    form = EspacoForm(request.POST, instance=espaco, prefix='espaco_modal')
    if form.is_valid():
        form.save()
        messages.success(request, f"Espaço '{espaco.nome}' atualizado no catálogo.")
    else:
        messages.error(request, f"Confira o espaço: {_erros_do_form(form)}")
    return redirect('organizador:chamada_proposicoes', evento_id=evento.id)


@login_required(login_url='/accounts/login/')
@require_POST
def excluir_espaco(request, evento_id, espaco_id):
    """Remove um espaço do catálogo — só se nenhum evento o estiver usando."""
    evento = _evento_gerenciavel(request, evento_id)
    espaco = get_object_or_404(Espaco, id=espaco_id)
    if Vaga.objects.filter(espaco=espaco).exists():
        messages.error(
            request,
            f"'{espaco.nome}' está na grade de vagas de um evento: exclua as "
            "vagas (ou as propostas) antes de tirá-lo do catálogo.",
        )
    else:
        nome = espaco.nome
        espaco.delete()
        messages.success(request, f"Espaço '{nome}' removido do catálogo.")
    return redirect('organizador:chamada_proposicoes', evento_id=evento.id)


@login_required(login_url='/accounts/login/')
@require_POST
def adicionar_vaga(request, evento_id):
    """Cria uma vaga (dia + horário + espaço) que os proponentes podem reservar."""
    evento = _evento_gerenciavel(request, evento_id)
    form = VagaForm(request.POST, evento=evento, prefix='vaga')
    if form.is_valid():
        vaga = form.save(commit=False)
        vaga.evento = evento
        vaga.save()
        messages.success(request, f"Vaga criada: {vaga}.")
        return redirect('organizador:chamada_proposicoes', evento_id=evento.id)

    messages.error(request, f"Confira a vaga: {_erros_do_form(form)}")
    return redirect(
        reverse('organizador:chamada_proposicoes', args=[evento.id])
        + "?abrir=vaga#vagas"
    )


@login_required(login_url='/accounts/login/')
@require_POST
def gerar_grade_lote(request, evento_id):
    """Cria vagas em lote (dias × blocos × espaços), sem duplicar o que existe."""
    evento = _evento_gerenciavel(request, evento_id)
    form = GradeVagasForm(request.POST, evento=evento, prefix='grade')
    if not form.is_valid():
        messages.error(request, f"Confira a grade: {_erros_do_form(form)}")
        return redirect(
            reverse('organizador:chamada_proposicoes', args=[evento.id])
            + "?abrir=grade#vagas"
        )

    resultado = propostas.gerar_grade(
        evento,
        dias=form.cleaned_data['dias'],
        blocos=form.cleaned_data['blocos'],
        espacos=form.cleaned_data['espacos'],
        capacidade=form.cleaned_data['capacidade'],
    )
    detalhe = (
        f" — {resultado['existentes']} já existia(m)." if resultado['existentes'] else "."
    )
    messages.success(
        request, f"{resultado['criadas']} vaga(s) criada(s){detalhe}"
    )
    return redirect('organizador:chamada_proposicoes', evento_id=evento.id)


@login_required(login_url='/accounts/login/')
@require_POST
def editar_vaga(request, evento_id, vaga_id):
    """Edita uma vaga da grade (espaço, janela e capacidade).

    Vaga com proposta pendente/aprovada fica com espaço e horário travados — a
    proposta copiou a janela ao ser enviada (a trava é do `VagaForm`).
    """
    evento = _evento_gerenciavel(request, evento_id)
    vaga = get_object_or_404(Vaga, id=vaga_id, evento=evento)
    form = VagaForm(request.POST, instance=vaga, evento=evento, prefix='vaga_modal')
    if form.is_valid():
        form.save()
        messages.success(request, f"Vaga atualizada: {vaga}.")
        return redirect('organizador:chamada_proposicoes', evento_id=evento.id)

    messages.error(request, f"Confira a vaga: {_erros_do_form(form)}")
    return redirect(
        reverse('organizador:chamada_proposicoes', args=[evento.id])
        + "?abrir=vaga#vagas"
    )


@login_required(login_url='/accounts/login/')
@require_POST
def excluir_vaga(request, vaga_id):
    """Remove uma vaga — só se não houver proposta ativa reservando-a."""
    vaga = get_object_or_404(Vaga, id=vaga_id)
    evento = _evento_gerenciavel(request, vaga.evento_id)
    if vaga.propostas_ativas().exists():
        messages.error(
            request,
            "Esta vaga tem proposta pendente ou aprovada: decida ou cancele "
            "antes de excluí-la.",
        )
    else:
        vaga.delete()
        messages.success(request, "Vaga removida.")
    return redirect('organizador:chamada_proposicoes', evento_id=evento.id)


@login_required(login_url='/accounts/login/')
def chamada_painel(request, evento_id):
    """Painel de acompanhamento da chamada (só leitura)."""
    evento = _evento_gerenciavel(request, evento_id)
    return render(request, 'organizador/chamada_painel.html', {
        'evento': evento,
        **propostas.resumo(evento),
    })


@login_required(login_url='/accounts/login/')
def propostas_pendentes(request, evento_id):
    """Propostas aguardando decisão do organizador."""
    evento = _evento_gerenciavel(request, evento_id)
    return render(request, 'organizador/propostas_pendentes.html', {
        'evento': evento,
        'lista': list(propostas.pendentes([evento]).prefetch_related('palestrantes')),
        'tipos': TipoAtividade.objects.all().order_by('nome'),
        'chamada': propostas.chamada_de(evento),
        'aberta': propostas.esta_aberta(evento),
    })


@login_required(login_url='/accounts/login/')
@require_POST
def aprovar_proposta(request, atividade_id):
    """Aprova a proposta (por padrão já publica na programação)."""
    atividade = get_object_or_404(Atividade, id=atividade_id)
    _evento_gerenciavel(request, atividade.evento_id)

    # O form manda um hidden "0" e o checkbox "1": sem marcar, o value lido é 0
    # (aprova mantendo rascunho); marcado, é 1 (aprova e publica).
    publicar = request.POST.get('publicar') == '1'
    tipo = None
    tipo_id = (request.POST.get('tipo') or '').strip()
    if tipo_id.isdigit():
        tipo = TipoAtividade.objects.filter(pk=tipo_id).first()

    try:
        propostas.aprovar(atividade, request.user, publicar=publicar, tipo=tipo)
    except PropostaBloqueada as erro:
        messages.error(request, erro.messages[0])
    else:
        messages.success(
            request,
            "Proposta aprovada e publicada na programação." if publicar
            else "Proposta aprovada, mantida como rascunho.",
        )
    return redirect('organizador:propostas_pendentes', evento_id=atividade.evento_id)


@login_required(login_url='/accounts/login/')
@require_POST
def rejeitar_proposta(request, atividade_id):
    """Rejeita a proposta (com motivo) e libera a vaga."""
    atividade = get_object_or_404(Atividade, id=atividade_id)
    _evento_gerenciavel(request, atividade.evento_id)
    try:
        propostas.rejeitar(atividade, request.user, request.POST.get('motivo'))
    except PropostaBloqueada as erro:
        messages.error(request, erro.messages[0])
    else:
        messages.success(request, "Proposta rejeitada e vaga liberada.")
    return redirect('organizador:propostas_pendentes', evento_id=atividade.evento_id)


@login_required(login_url='/accounts/login/')
@require_POST
def cadastrar_palestrante_sugerido(request, sugestao_id):
    """Cadastra/vincula um palestrante sugerido à atividade e o converte.

    Reusa a regra de `propostas.cadastrar_sugerido`: se o e-mail já existir no
    sistema, vincula ao cadastro existente; senão cria um novo palestrante.
    """
    from eventos.models import PalestranteSugerido

    sugestao = get_object_or_404(PalestranteSugerido, id=sugestao_id)
    atividade = sugestao.atividade
    _evento_gerenciavel(request, atividade.evento_id)
    try:
        propostas.cadastrar_sugerido(
            sugestao,
            nome=request.POST.get('nome'),
            email=request.POST.get('email'),
            telefone=request.POST.get('telefone'),
        )
    except PropostaBloqueada as erro:
        messages.error(request, erro.messages[0])
    else:
        messages.success(request, "Palestrante cadastrado e vinculado à atividade.")
    return redirect(request.META.get('HTTP_REFERER') or
                    'organizador:propostas_pendentes',
                    evento_id=atividade.evento_id)


@login_required(login_url='/accounts/login/')
@require_POST
def cadastrar_tipo_sugerido(request, atividade_id):
    """Cadastra o tipo sugerido pelo proponente e já o seleciona na proposta.

    Idempotente: se o tipo já existir no catálogo, apenas seleciona. A
    aprovação continua sendo decisão explícita no botão "Aprovar".
    """
    atividade = get_object_or_404(Atividade, id=atividade_id)
    _evento_gerenciavel(request, atividade.evento_id)
    nome = (atividade.tipo_sugerido or "").strip()
    if not nome:
        messages.error(request, "Não há tipo sugerido nesta proposta.")
        return redirect('organizador:propostas_pendentes', evento_id=atividade.evento_id)

    tipo = TipoAtividade.objects.filter(nome__iexact=nome).first()
    if tipo is None:
        tipo = TipoAtividade.objects.create(nome=nome)
    atividade.tipo = tipo
    atividade.save(update_fields=["tipo"])
    messages.success(request, "Tipo '%s' cadastrado e selecionado na proposta." % nome)
    return redirect('organizador:propostas_pendentes', evento_id=atividade.evento_id)


# -- Pré-triagem de propostas (copiloto do organizador) --
@login_required(login_url='/accounts/login/')
@require_POST
async def triagem_propostas(request, evento_id):
    """Analisa a fila de propostas e devolve SUGESTÕES (não decide nada).

    Endpoint AJAX chamado pela tela de propostas pendentes. O resultado fica em
    cache; `forcar=1` (GET ou POST) refaz a análise.
    """
    try:
        evento = await sync_to_async(_evento_gerenciavel)(request, evento_id)
    except PermissionDenied:
        return JsonResponse({"erro": "Você não gerencia este evento."}, status=403)

    forcar = (request.GET.get("forcar") or request.POST.get("forcar")) == "1"
    resultado = await triagem.analisar_evento(evento, forcar=forcar)
    return JsonResponse(resultado)


# -- Importação assistida da programação (copiloto do organizador) --
@login_required(login_url='/accounts/login/')
def importar_programacao(request, evento_id):
    """Assistente de importação da programação a partir de uma planilha.

    Etapas: upload → sugestão de mapeamento (IA + sinônimos) → revisão/prévia →
    confirmação. Nada é gravado antes da confirmação; o arquivo lido fica no
    cache entre as etapas (token).
    """
    evento = _evento_gerenciavel(request, evento_id)
    tipos = list(TipoAtividade.objects.order_by("nome"))
    contexto = {
        "evento": evento,
        "campos": importacao_assistida.CAMPOS,
        "tipos": tipos,
    }
    template = "organizador/importar_programacao.html"

    if request.method == "GET":
        return render(request, template, contexto)

    acao = (request.POST.get("acao") or "").strip()
    token = (request.POST.get("token") or "").strip()

    # Etapa 1: upload + sugestão de mapeamento.
    if acao == "preview":
        arquivo = request.FILES.get("arquivo")
        if not arquivo:
            contexto["erro"] = "Selecione um arquivo (.csv, .xls ou .xlsx)."
            return render(request, template, contexto)
        try:
            cabecalhos, linhas = importacao_assistida.ler_upload(arquivo)
        except Exception as erro:  # noqa: BLE001 - arquivo do usuário: devolve amigável
            contexto["erro"] = "Não consegui ler o arquivo (%s)." % erro
            return render(request, template, contexto)
        if not linhas:
            contexto["erro"] = "O arquivo não tem linhas de dados."
            return render(request, template, contexto)

        token = importacao_assistida.novo_token()
        sugestao = async_to_sync(importacao_assistida.sugerir_mapeamento)(
            cabecalhos, linhas, evento
        )
        normalizacoes = sugestao["normalizacoes"]
        importacao_assistida.guardar(token, {
            "cabecalhos": cabecalhos, "linhas": linhas, "normalizacoes": normalizacoes,
        })
        canonicas = importacao_assistida.aplicar_mapeamento(
            linhas, sugestao["mapeamento"], evento, normalizacoes
        )
        contexto.update({
            "token": token,
            "cabecalhos": cabecalhos,
            "mapeamento": sugestao["mapeamento"],
            "campos_mapeamento": importacao_assistida.campos_com_selecao(sugestao["mapeamento"]),
            "origem": sugestao["origem"],
            "aviso_ia": sugestao["aviso"],
            "avisos_ia": sugestao["avisos"],
            "dossie_info": sugestao["dossie"],
            "normalizacoes": normalizacoes,
            "imagens": importacao_assistida.detectar_imagens(linhas, sugestao["mapeamento"]),
            "duplicatas": importacao_assistida.detectar_duplicatas(canonicas, evento),
            "faltantes": importacao_assistida.valores_faltantes(canonicas, evento),
            "total_linhas": len(linhas),
            "previa": importacao_assistida.previsualizar(evento, canonicas),
            "previa_canonicas": canonicas[:10],
        })
        return render(request, template, contexto)

    # Etapas 2 e 3: refazer a prévia ou importar (reusam o arquivo no cache).
    dados = importacao_assistida.recuperar(token)
    if not dados:
        contexto["erro"] = "A sessão de importação expirou. Envie o arquivo de novo."
        return render(request, template, contexto)

    cabecalhos, linhas = dados["cabecalhos"], dados["linhas"]
    normalizacoes = dados.get("normalizacoes") or {"tipo": {}, "local": {}}
    mapeamento = {
        canonico: (request.POST.get("map_%s" % canonico) or "").strip()
        for canonico, _rotulo, _obrig, _ajuda in importacao_assistida.CAMPOS
    }
    mapeamento = {chave: valor for chave, valor in mapeamento.items() if valor}
    erros, avisos = importacao_assistida.validar_mapeamento(mapeamento, cabecalhos)

    contexto.update({
        "token": token,
        "cabecalhos": cabecalhos,
        "mapeamento": mapeamento,
        "campos_mapeamento": importacao_assistida.campos_com_selecao(mapeamento),
        "normalizacoes": normalizacoes,
        "total_linhas": len(linhas),
        "erros_mapeamento": erros,
        "avisos_mapeamento": avisos,
    })
    if erros:
        return render(request, template, contexto)

    canonicas = importacao_assistida.aplicar_mapeamento(
        linhas, mapeamento, evento, normalizacoes
    )
    contexto["imagens"] = importacao_assistida.detectar_imagens(linhas, mapeamento)
    contexto["duplicatas"] = importacao_assistida.detectar_duplicatas(canonicas, evento)
    contexto["faltantes"] = importacao_assistida.valores_faltantes(canonicas, evento)

    if acao == "importar":
        from eventos.importacao_programacao import importar_linhas

        # Cria tipos/espaços marcados pelo organizador antes de importar.
        for nome in request.POST.getlist("criar_tipo"):
            nome = " ".join(nome.split())[:255]
            if nome and not TipoAtividade.objects.filter(nome__iexact=nome).exists():
                TipoAtividade.objects.create(nome=nome)
        for nome in request.POST.getlist("criar_espaco"):
            nome = " ".join(nome.split())[:160]
            if nome and not Espaco.objects.filter(nome__iexact=nome).exists():
                Espaco.objects.create(nome=nome)

        contexto["relatorio"] = importar_linhas(evento, canonicas)
        contexto["concluido"] = True
        return render(request, template, contexto)

    contexto["previa"] = importacao_assistida.previsualizar(evento, canonicas)
    contexto["previa_canonicas"] = canonicas[:10]
    return render(request, template, contexto)


# -- Copiloto de criação de evento (plano de programação) --
@csrf_exempt
@login_required(login_url='/accounts/login/')
async def copiloto_evento_plano(request, evento_id):
    """Recebe um resumo e devolve um plano inicial do evento (JSON)."""
    if request.method != "POST":
        return JsonResponse({"erro": "Método não permitido"}, status=405)
    try:
        dados = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"erro": "Corpo da requisição inválido."}, status=400)

    try:
        evento = await sync_to_async(_evento_gerenciavel)(request, evento_id)
    except PermissionDenied:
        return JsonResponse({"erro": "Você não gerencia este evento."}, status=403)

    plano = await copiloto_evento.gerar_plano(
        (dados.get("titulo") or "").strip(),
        (dados.get("descricao") or "").strip(),
        (dados.get("categoria") or "").strip(),
        evento,
        (dados.get("observacoes") or "").strip(),
    )
    return JsonResponse(plano)


@login_required(login_url='/accounts/login/')
@require_POST
def aplicar_plano_evento(request, evento_id):
    """Cria as atividades do plano como RASCUNHO (reusa a importação)."""
    from eventos.importacao_programacao import importar_linhas

    evento = _evento_gerenciavel(request, evento_id)
    try:
        dados = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"erro": "Corpo da requisição inválido."}, status=400)

    plano = dados.get("plano") if isinstance(dados.get("plano"), dict) else dados
    linhas = copiloto_evento.plano_para_linhas(plano, evento)
    if not linhas:
        return JsonResponse({"erro": "Nenhuma atividade para criar."}, status=400)

    relatorio = importar_linhas(evento, linhas, publicada=False)
    return JsonResponse({"relatorio": relatorio})


@login_required(login_url='/accounts/login/')
@require_POST
def remover_plano_evento(request, evento_id):
    """Remove os rascunhos criados pelo copiloto (somente atividades NÃO publicadas).

    Guarda de segurança: nunca apaga atividade publicada nem de outro evento —
    o organizador informa os ids que o copiloto criou.
    """
    evento = _evento_gerenciavel(request, evento_id)
    try:
        dados = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"erro": "Corpo da requisição inválido."}, status=400)

    ids = [v for v in (dados.get("atividade_ids") or []) if str(v).isdigit()]
    removidas = Atividade.objects.filter(
        pk__in=ids, evento=evento, publicada=False
    ).delete()[0]
    return JsonResponse({"removidas": removidas})


# -- Briefing operacional (execução, no dia) --
@login_required(login_url='/accounts/login/')
def briefing_operacional(request, evento_id):
    """Painel de operação do evento: agora, a seguir e alertas."""
    evento = _evento_gerenciavel(request, evento_id)
    contexto = {"evento": evento, **operacao.resumo(evento)}
    return render(request, "organizador/operacao.html", contexto)


@csrf_exempt
@login_required(login_url='/accounts/login/')
async def briefing_leitura(request, evento_id):
    """Leitura rápida do estado atual do evento (IA)."""
    if request.method != "POST":
        return JsonResponse({"erro": "Método não permitido"}, status=405)
    try:
        evento = await sync_to_async(_evento_gerenciavel)(request, evento_id)
    except PermissionDenied:
        return JsonResponse({"erro": "Você não gerencia este evento."}, status=403)
    return JsonResponse(await operacao.leitura_do_dia(evento))


# -- Comunicação assistida (rascunhos de divulgação) --
@csrf_exempt
@login_required(login_url='/accounts/login/')
async def gerar_divulgacao(request, evento_id):
    """Gera rascunho de post/e-mail para divulgação do evento (IA)."""
    if request.method != "POST":
        return JsonResponse({"erro": "Método não permitido"}, status=405)
    try:
        dados = json.loads(request.body.decode("utf-8"))
    except Exception:
        dados = {}
    try:
        evento = await sync_to_async(_evento_gerenciavel)(request, evento_id)
    except PermissionDenied:
        return JsonResponse({"erro": "Você não gerencia este evento."}, status=403)
    return JsonResponse(await comunicacao.gerar_rascunho(
        evento,
        canal=(dados.get("canal") or "post").strip(),
        objetivo=(dados.get("objetivo") or "").strip(),
    ))
