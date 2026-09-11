from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth.decorators import login_required
from eventos.models import Atividade, Inscricao, Participante
from django.contrib import messages
from django.utils.timezone import localtime
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json
from .forms import ParticipanteUpdateForm
from eventos.forms import EventoForm, PalestranteForm, TipoAtividadeForm
from eventos.models import Evento
from eventos.forms import AtividadeForm
from eventos.models import Atividade

from django.views import View
from eventos.models import Inscricao, Certificado
from eventos.utils import gerar_certificado

import base64
from django.core.files.base import ContentFile


# -- Dashboard do Organizador --
@login_required(login_url='/accounts/login/')
def dashboard(request):
    organizador = get_object_or_404(Participante, id=request.user.id)  

    if organizador.is_superuser:
        eventos = Evento.objects.all() # Todos os eventos de todos os organizadores
    else:
        eventos = organizador.eventos.all() # Apenas eventos do organizador logado

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
            if 'foto' in request.FILES:
                organizador.foto = request.FILES['foto']  # Atribuímos a imagem manualmente

            organizador.save()  # Agora salvamos no banco
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
            if 'foto' in request.FILES:
                usuario.foto = request.FILES['foto']  # Atribuímos a imagem manualmente

                cropped_image_data = request.POST.get('cropped_image')
                if cropped_image_data:
                    format, imgstr = cropped_image_data.split(';base64,')
                    ext = format.split('/')[-1]
                    data = ContentFile(base64.b64decode(imgstr), name=f'perfil_{usuario.id}.{ext}')
                    usuario.foto = data  # ajuste conforme o campo do seu model

            
            usuario.save()  # Agora salvamos no banco
            messages.success(request, "Perfil atualizado com sucesso!")
            return redirect("organizador:profile")
        
    return render(request, 'organizador/form_profile.html', {'form': form })
    



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
            if 'imagem' in request.FILES:
                evento.imagem = request.FILES['imagem']  # Atribuímos a imagem manualmente
            
                cropped_image_data = request.POST.get('cropped_image')
                if cropped_image_data:
                    format, imgstr = cropped_image_data.split(';base64,')
                    ext = format.split('/')[-1]
                    data = ContentFile(base64.b64decode(imgstr), name=f'evento_{evento.id}.{ext}')
                    evento.imagem = data  # ajuste conforme o campo do seu model

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
    """Lista as atividades de um evento"""
    evento = get_object_or_404(Evento, id=evento_id)
    atividades = evento.atividades.all()

    form = AtividadeForm(initial={'evento': evento})

    return render(request, 'organizador/atividades_evento.html', {
        'form_ativ' : form, 'evento': evento, 'atividades': atividades
    }) 


# -- cria Atividade usando o modal --
@login_required(login_url='/accounts/login/')
def criar_atividade(request):
    """Cria uma nova atividade associada a um evento"""
    # print("request.POST.get('evento'): ",request.POST.get('evento'))
   
    evento_id = request.POST.get('evento') # Recupera o id do evento via POST
    evento = get_object_or_404(Evento, id=evento_id)
    if request.method == "POST":
        form = AtividadeForm(request.POST)
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
            if 'imagem' in request.FILES:
                atividade.imagem = request.FILES['imagem']  # Atribuímos a imagem manualmente

                cropped_image_data = request.POST.get('cropped_image')
                if cropped_image_data:
                    format, imgstr = cropped_image_data.split(';base64,')
                    ext = format.split('/')[-1]
                    data = ContentFile(base64.b64decode(imgstr), name=f'atividade_{atividade.id}.{ext}')
                    atividade.imagem = data  # ajuste conforme o campo do seu model

            atividade.evento = evento  # Garante que o evento está correto
            atividade.save()
            form.save_m2m()  # Salva os campos ManyToMany corretamente

            
            messages.success(request, "Atividade salva com sucesso!")
            return redirect('organizador:atividades_evento', evento_id=evento_id)
    else:
        form = AtividadeForm(instance=atividade)  # Preenche o form se for edição

    form.fields['evento'].initial = evento  # Define o evento automaticamente
    
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
        form = AtividadeForm(request.POST, instance=atividade)
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
            if 'foto' in request.FILES:
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
