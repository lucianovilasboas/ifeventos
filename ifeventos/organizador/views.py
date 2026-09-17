from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth.decorators import login_required
from eventos.models import Atividade, Inscricao, Participante
from eventos import agenda
from django.contrib import messages
from django.utils.timezone import localtime
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
import json
from .forms import ParticipanteUpdateForm
from eventos.forms import EventoForm, PalestranteForm, TipoAtividadeForm
from eventos.forms import ChamadaProposicoesForm, EspacoForm, VagaForm
from eventos.models import Evento
from eventos.forms import AtividadeForm
from eventos.models import Atividade
from eventos.models import ChamadaProposicoes, Espaco, TipoAtividade, Vaga
from eventos import propostas
from eventos.propostas import PropostaBloqueada
from django.db.models import Count, Exists, OuterRef, Q

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
    pode_gerenciar_evento,
)
from eventos.models import Inscricao, Certificado
from eventos.utils import gerar_certificado

from eventos.imagens import imagem_cortada


# -- Dashboard do Organizador --
@login_required(login_url='/accounts/login/')
def dashboard(request):
    organizador = get_object_or_404(Participante, id=request.user.id)  

    if organizador.is_superuser:
        eventos = Evento.objects.all() # Todos os eventos de todos os organizadores
    else:
        eventos = organizador.eventos.all() # Apenas eventos do organizador logado

    # Chamada de proposições: o cartão do evento mostra o atalho e quantas
    # propostas esperam decisão (sem uma query por cartão).
    eventos = eventos.annotate(
        n_pendentes=Count(
            "atividades", filter=Q(atividades__situacao=Atividade.SITUACAO_PENDENTE)
        ),
        tem_chamada=Exists(ChamadaProposicoes.objects.filter(evento=OuterRef("pk"))),
    )

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
        
    return render(request, 'organizador/dashboard.html', {
        # 'inscricoes': inscricoes,
        # 'atividades': atividades, 
        'eventos': eventos,
        'form': form,
        'is_participante': organizador.is_participante,
        'organizador': organizador,
        'form_evt': EventoForm(),
        })

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
def modelo_metadados_csv(request):
    """Baixa o CSV-modelo (só o cabeçalho) com as colunas configuradas."""
    import csv

    from django.http import HttpResponse

    from eventos import importacao

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
            return JsonResponse({"success": True, "message": "Evento criado com sucesso!"})
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

    return render(request, 'organizador/form_evento.html', {'form': form, 'evento': evento})



def get_user_and_evento(request, evento_id):
    organizador = get_object_or_404(Participante, id=request.user.id)
    if organizador.is_superuser:
        evento = get_object_or_404(Evento, id=evento_id)
    else:
        evento = get_object_or_404(Evento, id=evento_id, organizador=organizador)
    return organizador, evento



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
    evento = get_object_or_404(Evento, id=evento_id)
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


# -- cria Atividade usando o modal --
@login_required(login_url='/accounts/login/')
def criar_atividade(request):
    """Cria uma nova atividade associada a um evento"""
    # print("request.POST.get('evento'): ",request.POST.get('evento'))
   
    evento_id = request.POST.get('evento') # Recupera o id do evento via POST
    evento = get_object_or_404(Evento, id=evento_id)
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
    

    return render(request, 'organizador/form_atividade.html', {'form_ativ': form, 'evento': evento})



@login_required(login_url='/accounts/login/')
def criar_editar_atividade(request, evento_id, atividade_id=None):
    """Cria ou edita uma atividade associada a um evento"""
    
    evento = get_object_or_404(Evento, id=evento_id)

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
        'atividade': atividade  # Para o template saber se é criação ou edição
    })



@login_required(login_url='/accounts/login/')
def editar_atividade(request, atividade_id):
    """Permite editar uma atividade"""
    atividade = get_object_or_404(Atividade, id=atividade_id)
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

    return render(request, 'organizador/form_atividade.html', {'form_ativ': form, 'atividade': atividade, 'evento': evento})


@login_required(login_url='/accounts/login/')
def excluir_atividade(request, atividade_id):
    """Exclui uma atividade"""
    atividade = get_object_or_404(Atividade, id=atividade_id)
    evento = atividade.evento
    atividade.delete()
    messages.success(request, "Atividade excluída com sucesso!")
    return redirect('organizador:atividades_evento', evento_id=evento.id)






# -- Palestrantes e Tipos de Atividade --
@login_required(login_url='/accounts/login/')
def adicionar_palestrante(request):
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
    if request.method == "POST":
        form = TipoAtividadeForm(request.POST)
        if form.is_valid():
            tipo = form.save()
            return JsonResponse({"success": True, "id": tipo.id, "nome": tipo.nome})
        return JsonResponse({"success": False, "errors": form.errors})
    return JsonResponse({"success": False, "message": "Método inválido"})





# -- Certificados --


class EmitirCertificadoInscricaoView(View):
    """
    View para que o organizador emita um certificado para uma inscrição confirmada.
    """
    def post(self, request, inscricao_id):
        inscricao = get_object_or_404(Inscricao, id=inscricao_id)

        if inscricao.certificado_emitido or Certificado.objects.filter(participante=inscricao.participante, atividade=inscricao.atividade).exists():
            return JsonResponse({"message": "Certificado já emitido para esta inscrição!", "certificado": False})

        pdf_file = gerar_certificado(inscricao.participante, atividade=inscricao.atividade, evento=inscricao.atividade.evento)
        Certificado.objects.create(
            participante=inscricao.participante,
            atividade=inscricao.atividade,
            pdf=pdf_file
        )

        inscricao.certificado_emitido = True
        inscricao.save()

        return JsonResponse({"message": "Certificado emitido com sucesso!", "certificado": True})




class EmitirCertificadosAtividadeView(View):
    """
    View para que o organizador emita certificados de uma atividade encerrada para participantes confirmados.
    """
    def post(self, request, atividade_id):
        atividade = get_object_or_404(Atividade, id=atividade_id)
        inscritos = Inscricao.objects.filter(atividade=atividade, confirmada=True, certificado_emitido=False)

        certificados_gerados = []
        for inscrito in inscritos:
            if not Certificado.objects.filter(participante=inscrito.participante, atividade=atividade).exists():
                pdf_file = gerar_certificado(inscrito.participante, atividade=atividade, evento=atividade.evento)
                certificado = Certificado.objects.create(
                    participante=inscrito.participante,
                    atividade=atividade,
                    pdf=pdf_file
                )

                inscrito.certificado_emitido = True
                inscrito.save()

                certificados_gerados.append(inscrito.id)

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


class EmitirCertificadosEventoView(View):
    def post(self, request, evento_id):
        evento = get_object_or_404(Evento, id=evento_id)
        participantes = Participante.objects.all()

        for participante in participantes:
            atividades_participadas = Inscricao.objects.filter(participante=participante, atividade__evento=evento, confirmada=True).count()
            total_atividades = evento.atividades.count()

            if total_atividades > 0 and (atividades_participadas / total_atividades) >= 0.75:
                if not Certificado.objects.filter(participante=participante, evento=evento).exists():
                    pdf_file = gerar_certificado(participante, evento=evento)
                    Certificado.objects.create(
                        participante=participante,
                        evento=evento,
                        pdf=pdf_file
                    )

        return JsonResponse({"message": "Certificados emitidos para o evento!"})


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
            # A tela é liberada também para quem PALESTRA na atividade, mas
            # desfazer presença exige gerenciar o evento (mesma regra da API).
            # Sem separar as duas, o palestrante veria um ✕ que sempre falha.
            "pode_desfazer": pode_gerenciar_evento(request.user, atividade.evento),
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
        if not pode_gerenciar_evento(request.user, atividade.evento):
            raise PermissionDenied("Você não organiza o evento desta atividade.")

        janela_aberta, motivo = atividade_aceita_presenca_agora(atividade)
        return render(request, self.template_name, {
            "atividade": atividade,
            "evento": atividade.evento,
            "janela_aberta": janela_aberta,
            "janela_motivo": motivo,
        })


@login_required(login_url='/accounts/login/')
@require_POST
def publicar_atividade(request, atividade_id):
    """Alterna rascunho/publicada (dono do evento/superuser)."""
    atividade = get_object_or_404(Atividade, id=atividade_id)
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
        'form_vaga': VagaForm(evento=evento, prefix='vaga'),
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
    else:
        messages.error(request, f"Confira a vaga: {_erros_do_form(form)}")
    return redirect('organizador:chamada_proposicoes', evento_id=evento.id)


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
