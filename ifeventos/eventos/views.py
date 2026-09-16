from django.utils import timezone  # ✅ Correto
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Count
from django.http import Http404, JsonResponse
from django.views.decorators.http import require_GET
from django.contrib.auth import logout
from .models import Evento
import qrcode
import io
from django.http import HttpResponse
from .models import Inscricao, Atividade, Presenca
from django.contrib.auth.decorators import login_required
from PIL import Image, ImageDraw, ImageFont
from datetime import date, timedelta
from .crachas import (
    confirmar_para_organizador,
    confirmar_por_token_atividade,
    pode_gerenciar_evento,
    registrar_presenca,
    verificar_token,
)
from django.conf import settings
from django.contrib import messages
from django.urls import reverse


def eventos_view(request):
    hoje = timezone.localdate()
    # Eventos atuais/futuros (a agenda mostra apenas os que não encerraram).
    # `n_atividades` vem anotado para o card/modal não fazerem um COUNT por card.
    eventos = (Evento.objects.filter(data_fim__gte=hoje)
               .annotate(n_atividades=Count('atividades'))
               .order_by('data_inicio'))
    # "Próximo na agenda": o evento mais próximo cujo término é hoje ou no futuro
    hoje = timezone.localdate()
    proximo = (Evento.objects.filter(data_fim__gte=hoje)
               .order_by('data_inicio')
               .first())
    # Frase do card "Começa amanhã" / "Em andamento" / data
    proximo_frase = None
    if proximo:
        if proximo.data_inicio == hoje:
            proximo_frase = "Acontece hoje"
        elif proximo.data_inicio == hoje + timedelta(days=1):
            proximo_frase = "Começa amanhã"
        elif proximo.data_inicio <= hoje <= proximo.data_fim:
            proximo_frase = "Em andamento"
        else:
            proximo_frase = f"Começa em {proximo.data_inicio.strftime('%d/%m')}"
    # Chips de filtro: apenas as categorias que realmente têm evento na agenda,
    # na ordem canônica do model. Derivar do banco (em vez de uma lista fixa)
    # faz um tema novo aparecer sozinho — e evita chip que não filtra nada.
    ordem = [valor for valor, _ in Evento.CATEGORIA_CHOICES]
    rotulos = dict(Evento.CATEGORIA_CHOICES)
    usadas = set(eventos.values_list('categoria', flat=True))
    # Categorias da lista-semente primeiro (na ordem canônica) e depois as que
    # os organizadores criaram, em ordem alfabética. O rótulo de uma categoria
    # nova é o próprio texto gravado (com acento, como foi escrito).
    categorias = [(v, rotulos[v]) for v in ordem if v in usadas]
    categorias += [(v, v) for v in sorted(usadas - set(ordem)) if v]

    return render(request, 'eventos/eventos.html', {
        'eventos': eventos,
        'proximo': proximo,
        'proximo_frase': proximo_frase,
        'categorias': categorias,
        # Últimos eventos realizados/encerrados (data_fim no passado),
        # do mais recente para o mais antigo.
        'encerrados': Evento.objects.filter(data_fim__lt=hoje)
                                  .annotate(n_atividades=Count('atividades'))
                                  .order_by('-data_fim'),
    })


def evento_programacao_view(request, evento_id):
    try:
        evento  = get_object_or_404(Evento, id=evento_id)
    except Http404 as e:
        return redirect('eventos:eventos')

    # Ordem cronológica: a atividade que acontece antes aparece primeiro.
    atividades = evento.atividades.order_by("data_hora_inicio", "id")
    return render(request, 'eventos/programacao.html', {
        'evento': evento,
        'atividades': atividades,
    })



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
    """Confirmação pelo QR fixo de UMA inscrição (código permanente da inscrição).

    Mantida porque os QR já emitidos apontam para cá — mas a regra agora é a
    mesma da confirmação nova: quem confirma é quem está logado, a janela da
    atividade vale e a presença fica registrada em `Presenca`, com origem e
    autoria. Antes esta view marcava apenas `Inscricao.confirmada`, então o mesmo
    ato aparecia num lugar e não no outro.
    """
    inscricao = get_object_or_404(Inscricao, codigo_confirmacao=codigo_confirmacao)

    if inscricao.participante_id != request.user.id:
        return render(request, "eventos/presenca_confirmada.html", {
            "success": False,
            "inscricao": inscricao,
            "mensagem": "Esta inscrição é de outra pessoa. Confirme a sua, pela sua conta.",
        })

    presenca, criada, motivo = registrar_presenca(
        inscricao.atividade, request.user, registrada_por=request.user, origem="proprio"
    )
    if presenca is None:
        return render(request, "eventos/presenca_confirmada.html", {
            "success": False, "inscricao": inscricao, "mensagem": motivo,
        })

    return render(request, "eventos/presenca_confirmada.html", {
        "success": True,
        "inscricao": inscricao,
        "mensagem": "Presença confirmada com sucesso!" if criada else "Presença já confirmada!",
    })


# -- Confirmação de Presença por atividade --

@login_required(login_url='/accounts/login/') # Garantir que o usuário esteja logado
def confirmar_presenca_atividade(request, codigo_confirmacao):
    """Confirmação pelo QR fixo da atividade (código permanente da atividade).

    Aceita qualquer pessoa com papel no evento — quem tem inscrição, quem
    palestra e quem organiza —, respeita a janela de confirmação e grava em
    `Presenca`. Antes exigia inscrição, e o palestrante não conseguia confirmar a
    própria presença.
    """
    atividade = get_object_or_404(Atividade, codigo_confirmacao=codigo_confirmacao)
    inscricao = Inscricao.objects.filter(participante=request.user, atividade=atividade).first()

    presenca, criada, motivo = registrar_presenca(
        atividade, request.user, registrada_por=request.user, origem="proprio"
    )
    if presenca is None:
        return render(request, "eventos/presenca_confirmada.html", {
            "success": False, "inscricao": inscricao, "mensagem": motivo,
        })

    return render(request, "eventos/presenca_confirmada.html", {
        "success": True,
        "inscricao": inscricao,
        "mensagem": "Presença confirmada com sucesso!" if criada else "Presença já confirmada!",
    })


# ---------------------------------------------------------------------------
# Verificação pública do QR (crachá e certificado)
# ---------------------------------------------------------------------------


def verificar_cracha(request, token):
    """Página aberta pelo QR do crachá — e também pelo QR do certificado.

    Fica fora do painel de propósito: quem confere costuma estar deslogado, no
    celular, na porta da atividade. Mostra apenas o que a conferência exige
    (nome, papel, evento e período) e nada de dado pessoal — CPF, e-mail e
    telefone não aparecem aqui.
    """
    # A regra da verificação vive em eventos/crachas.py, a mesma que a API usa.
    resultado = verificar_token(token)
    if not resultado["valido"]:
        return render(
            request,
            "cracha/verificacao.html",
            {"valido": False, "erro": resultado.get("erro", "Crachá inválido.")},
            status=resultado.get("status", 404),
        )

    evento = resultado.get("evento")

    # Quem está lendo pode ser a organização (pela sessão) ou apenas alguém
    # conferindo o crachá no celular. Só no primeiro caso há o que confirmar — e
    # a credencial é a sessão de quem lê, nunca o código que foi lido.
    eh_cracha = resultado["tipo"] == "cracha" and evento is not None
    organizacao = bool(
        eh_cracha
        and request.user.is_authenticated
        and pode_gerenciar_evento(request.user, evento)
    )

    confirmacao = None
    presencas_da_pessoa = None

    if request.method == "POST":
        if not organizacao:
            return render(request, "cracha/verificacao.html",
                          {"valido": False, "erro": "Só quem organiza este evento pode fazer isso."},
                          status=403)

        if request.POST.get("desfazer"):
            presenca = (
                Presenca.objects.filter(id=request.POST["desfazer"], participante=resultado["pessoa"])
                .select_related("atividade")
                .first()
            )
            if presenca:
                presenca.cancelar(
                    por=request.user,
                    motivo="Desfazer pelo check-in do crachá",
                )
                messages.success(request, "Presença desfeita.")
            return redirect("verificar_cracha", token=token)

        if request.POST.get("atividade"):
            # Escolha explícita, para quando há mais de uma atividade na janela.
            confirmacao = confirmar_para_organizador(
                resultado["pessoa"],
                evento,
                atividade=get_object_or_404(Atividade, id=request.POST["atividade"], evento=evento),
                registrada_por=request.user,
            )

    if organizacao:
        # FLUXO A2: a presença sai sozinha, sem toque nenhum — é o que permite à
        # pessoa da organização apenas apontar a câmera do celular para o crachá,
        # sem abrir o sistema. Só acontece quando há UMA atividade do evento na
        # janela: havendo mais de uma, o certo é perguntar, nunca adivinhar,
        # porque presença na atividade errada é pior que presença nenhuma.
        if confirmacao is None:
            confirmacao = confirmar_para_organizador(
                resultado["pessoa"], evento, registrada_por=request.user
            )

        # A lista vale nos dois casos: mostra o que já está registrado e deixa
        # desfazer sem sair da tela.
        presencas_da_pessoa = (
            Presenca.objects.filter(participante=resultado["pessoa"], atividade__evento=evento)
            .select_related("atividade")
            .order_by("-registrada_em")
        )

    return render(request, "cracha/verificacao.html", {
        "valido": True,
        "nome": resultado["nome"],
        "papel_rotulo": resultado["papel_rotulo"],
        # Todos os papéis da pessoa no evento (o crachá mostra o mesmo)
        "papeis_rotulos": resultado.get("papeis_rotulos") or [resultado["papel_rotulo"]],
        "evento": evento,
        "atividade": resultado.get("atividade"),
        "periodo": resultado.get("periodo", ""),
        "certificado": resultado.get("certificado"),
        "confirmacao": confirmacao,
        "presencas_da_pessoa": presencas_da_pessoa,
        "tipo": resultado["tipo"],
    })


def confirmar_presenca_pelo_qr(request, token):
    """FLUXO B — a própria pessoa confirma, escaneando o QR ROTATIVO da atividade.

    É o caminho novo: o QR é assinado e vale poucos minutos, então uma foto
    compartilhada deixa de funcionar. Quem confirma é quem está logado — o nome
    que entra na lista é o da conta que escaneou, e não há como confirmar
    presença de outra pessoa por aqui. Sem sessão, manda para o login e volta
    para o mesmo código (`next` preservado).
    """
    if not request.user.is_authenticated:
        return redirect(f"{settings.LOGIN_URL}?next={request.path}")

    atividade, presenca, criada, erro = confirmar_por_token_atividade(token, request.user)
    return render(
        request,
        "cracha/confirmacao.html",
        {
            "atividade": atividade,
            "presenca": presenca,
            "criada": criada,
            "erro": erro,
            "pessoa": request.user,
        },
        status=200 if presenca else 400,
    )


@require_GET
def roster_lookup(request):
    """AJAX do cadastro: busca a linha da planilha de alunos e devolve os dados.

    Público de propósito — quem consulta ainda não tem conta. Busca primeiro
    pelo e-mail; não achando, tenta pelo CPF. A pessoa usa o retorno só para
    pré-preencher o formulário e confirmar/corrigir.
    """
    from .models import PessoaRoster
    from .validators import apenas_digitos, formatar_cpf

    email = (request.GET.get("email") or "").strip().lower()
    cpf = apenas_digitos(request.GET.get("cpf") or "")

    linha = None
    origem = None
    if email:
        linha = PessoaRoster.objects.filter(email=email).first()
        if linha is not None:
            origem = "email"
    if linha is None and len(cpf) == 11:
        linha = PessoaRoster.objects.filter(cpf=cpf).first()
        if linha is not None:
            origem = "cpf"

    if linha is None:
        resposta = JsonResponse({"encontrado": False})
    else:
        from .roster import dividir_nome

        primeiro, sobrenome = dividir_nome(linha.nome)
        resposta = JsonResponse({
            "encontrado": True,
            "origem": origem,
            "nome": linha.nome,
            "first_name": primeiro,
            "last_name": sobrenome,
            "cpf": formatar_cpf(linha.cpf),
            "dados": dict(linha.dados or {}),
        })
    resposta["Cache-Control"] = "no-store"
    return resposta
