from django.utils import timezone  # ✅ Correto
from django.shortcuts import render
from django.http import Http404
from django.contrib.auth import logout
from django.shortcuts import redirect,  get_object_or_404
from .models import Evento
import qrcode
import io
from django.http import HttpResponse
from .models import Inscricao, Atividade
from django.contrib.auth.decorators import login_required
from PIL import Image, ImageDraw, ImageFont


def eventos_view(request):
    eventos = Evento.objects.all().order_by('data_inicio')
    return render(request, 'eventos/eventos.html', {'eventos': eventos})


def evento_programacao_view(request, evento_id):
    try:
        evento  = get_object_or_404(Evento, id=evento_id)
    except Http404 as e:
        return redirect('eventos:eventos')
    
    return render(request, 'eventos/programacao.html', {'evento': evento})



# -- Logout --
def logout_view(request):
    logout(request)
    return redirect('eventos:eventos')





# -- QR Code - Confirmação de Presença --



# @login_required(login_url='/accounts/login/')
# def gerar_qr_code(request, inscricao_id):
#     inscricao = get_object_or_404(Inscricao, id=inscricao_id)

#     # O QR Code conterá a URL para confirmação
#     url_confirmacao = request.build_absolute_uri(f"/eventos/confirmar-presenca/{inscricao.codigo_confirmacao}/")

#     # Gerar QR Code
#     qr = qrcode.make(url_confirmacao)
#     buffer = io.BytesIO()
#     qr.save(buffer, format="PNG")
#     buffer.seek(0)

#     return HttpResponse(buffer.getvalue(), content_type="image/png")



# -- QR Code - Confirmação de Presença por inscrição -- 

@login_required(login_url='/accounts/login/')
def gerar_qr_code(request, inscricao_id):
    inscricao = get_object_or_404(Inscricao, id=inscricao_id)

    # URL que será embutida no QR Code
    url_confirmacao = request.build_absolute_uri(f"/eventos/confirmar-presenca/{inscricao.codigo_confirmacao}/")

    # Criar QR Code
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,  
        border=4  
    )
    qr.add_data(url_confirmacao)
    qr.make(fit=True)

    # Criar imagem do QR Code e converter para RGB
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    # Criar nova imagem maior para adicionar texto
    largura = qr_img.size[0]
    altura_extra = 100  
    nova_altura = qr_img.size[1] + altura_extra

    imagem_final = Image.new("RGB", (largura, nova_altura), "white")
    draw = ImageDraw.Draw(imagem_final)

    # Definir fonte
    try:
        fonte = ImageFont.truetype("arial.ttf", 40)  
    except IOError:
        fonte = ImageFont.load_default()  

    # Adicionar título do evento acima
    titulo_evento = f"Evento: {inscricao.atividade.evento.title}".upper()
    bbox = draw.textbbox((0, 0), titulo_evento, font=fonte)
    w = bbox[2] - bbox[0]  
    draw.text(((largura - w) / 2, 10), titulo_evento, fill="black", font=fonte)

    # Colocar o QR Code na imagem (agora em RGB)
    imagem_final.paste(qr_img, (0, 50))

    # Adicionar texto abaixo do QR Code
    texto_info = f"Atividade: {inscricao.atividade.titulo}"
    bbox = draw.textbbox((0, 0), texto_info, font=fonte)
    w = bbox[2] - bbox[0]  
    draw.text(((largura - w) / 2, qr_img.size[1] + 60), texto_info, fill="black", font=fonte)

    # Salvar a imagem em memória
    buffer = io.BytesIO()
    imagem_final.save(buffer, format="PNG")
    buffer.seek(0)

    return HttpResponse(buffer.getvalue(), content_type="image/png")





# -- QR Code - Confirmação de Presença por atividade --

@login_required(login_url='/accounts/login/')
def gerar_qr_code_atividade(request, atividade_id):
    atividade = get_object_or_404(Atividade, id=atividade_id)

    # URL que será embutida no QR Code
    url_confirmacao = request.build_absolute_uri(f"/eventos/confirmar-presenca-atividade/{atividade.codigo_confirmacao}/")

    # Criar QR Code
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,  
        border=4  
    )
    qr.add_data(url_confirmacao)
    qr.make(fit=True)

    # Criar imagem do QR Code e converter para RGB
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    # Criar nova imagem maior para adicionar texto
    largura = qr_img.size[0]
    altura_extra = 100  
    nova_altura = qr_img.size[1] + altura_extra

    imagem_final = Image.new("RGB", (largura, nova_altura), "white")
    draw = ImageDraw.Draw(imagem_final)

    # Definir fonte
    try:
        fonte = ImageFont.truetype("arial.ttf", 20)  
    except IOError:
        fonte = ImageFont.load_default()  

    # Adicionar título da atividade acima
    titulo_atividade = f"Atividade: {atividade.titulo}".upper()
    bbox = draw.textbbox((0, 0), titulo_atividade, font=fonte)
    w = bbox[2] - bbox[0]  
    draw.text(((largura - w) / 2, 10), titulo_atividade, fill="black", font=fonte)

    # Colocar o QR Code na imagem
    imagem_final.paste(qr_img, (0, 50))

    # Salvar a imagem em memória
    buffer = io.BytesIO()
    imagem_final.save(buffer, format="PNG")
    buffer.seek(0)

    return HttpResponse(buffer.getvalue(), content_type="image/png")




# -- Confirmação de Presença por inscrição --

@login_required(login_url='/accounts/login/') # Garantir que o usuário esteja logado
def confirmar_presenca(request, codigo_confirmacao):
    inscricao = get_object_or_404(Inscricao, codigo_confirmacao=codigo_confirmacao)

    # Verifica se o usuário logado é o mesmo que fez a inscrição
    if inscricao.participante != request.user:
        # return HttpResponseForbidden("Você não tem permissão para confirmar essa presença. Conecte-se com a conta correta e tente novamente.")
        return render(request, "eventos/presenca_confirmada.html", 
                      {"seccess": False, 
                       "inscricao": inscricao, 
                       "mensagem": "Você não tem permissão para confirmar essa presença. Conecte-se com a conta correta e tente novamente."})
    

    # Verificar se o usuario esta tentando confirmar antes ou depois da atividade
    if inscricao.atividade.data_hora_inicio > timezone.now():  # ✅ Agora funciona!
        return render(request, "eventos/presenca_confirmada.html", {"success": False, "inscricao": inscricao, "mensagem": "A atividade ainda não começou."})
    elif inscricao.atividade.data_hora_fim < timezone.now():  # ✅ Agora funciona!
        return render(request, "eventos/presenca_confirmada.html", {"success": False, "inscricao": inscricao, "mensagem": "A atividade já terminou."})


    if inscricao.confirmada:
        return render(request, "eventos/presenca_confirmada.html", {"success": True, "inscricao": inscricao, "mensagem": "Presença já confirmada!"})

    # Marca a presença como confirmada
    inscricao.confirmada = True
    inscricao.save()

    return render(request, "eventos/presenca_confirmada.html", {"success": True, "inscricao": inscricao, "mensagem": "Presença confirmada com sucesso!"})




# -- Confirmação de Presença por atividade --

@login_required(login_url='/accounts/login/') # Garantir que o usuário esteja logado
def confirmar_presenca_atividade(request, codigo_confirmacao):
    atividade = get_object_or_404(Atividade, codigo_confirmacao=codigo_confirmacao)

    # Verifica se o usuário está inscrito na atividade
    inscricao = Inscricao.objects.filter(participante=request.user, atividade=atividade).first()

    if not inscricao:
        return render(request, "eventos/presenca_confirmada.html", {
            "success": False,
            "inscricao": inscricao, 
            "mensagem": "Você não está inscrito nesta atividade!"
        })
    

    # Verificar se o usuario esta tentando confirmar antes ou depois da atividade
    if inscricao.atividade.data_hora_inicio > timezone.now():  # ✅ Agora funciona!
        return render(request, "eventos/presenca_confirmada.html", {"success": False, "inscricao": inscricao, "mensagem": "A atividade ainda não começou."})
    elif inscricao.atividade.data_hora_fim < timezone.now():  # ✅ Agora funciona!
        return render(request, "eventos/presenca_confirmada.html", {"success": False, "inscricao": inscricao, "mensagem": "A atividade já terminou."})


    # Confirma presença
    inscricao.confirmada = True
    inscricao.save()

    return render(request, "eventos/presenca_confirmada.html", {
        "success": True,
        "inscricao": inscricao, 
        "mensagem": "Presença confirmada com sucesso!"
    })