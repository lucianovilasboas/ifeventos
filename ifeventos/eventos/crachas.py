"""Crachás de participação — papel por evento, token do QR, código curto e PDF.

Decisão de projeto: o crachá NÃO é um registro no banco. Ele é derivado do que
já existe (evento + pessoa + papel), então não há nada para manter em sincronia
quando alguém ganha ou perde um papel. O que fica gravado é apenas a **presença**
(model `Presenca`), que o check-in cria.

O QR do crachá carrega um **token assinado** (`django.core.signing`), portanto
sem estado: não precisa de tabela de tokens, funciona para quem não tem
inscrição (organizador e palestrante) e pode ser revogado em massa trocando o
sal. Junto dele vai um **código curto** para digitação manual, quando a câmera
não estiver disponível.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import threading
from datetime import timedelta

import qrcode
from django.conf import settings
from django.core import signing
from django.core.files.base import ContentFile
from django.utils import timezone

from .models import Atividade, Certificado, Evento, Inscricao, Participante, Presenca

# Trocar qualquer um dos dois sais invalida TODOS os crachás já emitidos e os
# códigos curtos correspondentes. É a válvula de emergência em caso de
# vazamento — e por isso não devem ser alterados sem aviso.
SAL_TOKEN = "cracha-ifmg-v1"

# Sal separado para o QR da atividade: um token de crachá nunca vale como
# código de atividade, e vice-versa — são permissões diferentes.
SAL_PRESENCA = "presenca-atividade-v1"

# Alfabeto sem I, L, O e U: os quatro caracteres que as pessoas confundem ao
# ditar um código em voz alta na portaria (I/1, O/0, U/V).
ALFABETO_CODIGO = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
TAMANHO_CODIGO = 6

ROTULOS_PAPEL = {
    "organizador": "Organizador",
    "palestrante": "Palestrante",
    "participante": "Participante",
}


class CrachaInvalido(Exception):
    """Token adulterado, expirado ou emitido para outro fim."""


# --------------------------------------------------------------------------
# Papel e listagem
# --------------------------------------------------------------------------

def papel_no_evento(usuario, evento):
    """Papel do usuário NAQUELE evento: organizador, palestrante ou participante.

    Os campos `is_organizador`/`is_palestrante`/`is_participante` do Participante
    são globais, mas o papel do crachá é do evento: quem organiza o evento A
    costuma ser apenas participante no evento B. Por isso derivamos do contexto,
    nesta ordem de precedência (a primeira que casa vence):

        organizador  -> é o organizador cadastrado no evento;
        palestrante  -> está entre os palestrantes de alguma atividade do evento;
        participante -> tem inscrição em alguma atividade do evento.

    Devolve None quando a pessoa não tem papel nenhum no evento — e nesse caso
    não recebe crachá.
    """
    if not evento or not usuario or not getattr(usuario, "is_authenticated", False):
        return None

    if evento.organizador_id == usuario.id:
        return "organizador"

    if evento.atividades.filter(palestrantes=usuario).exists():
        return "palestrante"

    if Inscricao.objects.filter(participante=usuario, atividade__evento=evento).exists():
        return "participante"

    return None


def eventos_com_papel(usuario):
    """Eventos em que o usuário tem algum papel, do mais recente para o mais antigo."""
    if not usuario or not getattr(usuario, "is_authenticated", False):
        return []
    return list(
        (
            # `atividades` é o related_name de Atividade.evento — o padrão
            # (`atividade_set`) não vale aqui.
            Evento.objects.filter(organizador=usuario)
            | Evento.objects.filter(atividades__palestrantes=usuario)
            | Evento.objects.filter(atividades__inscritos__participante=usuario)
        )
        .distinct()
        .order_by("-data_inicio", "-id")
    )


def pessoas_do_evento(evento):
    """Quem tem crachá no evento: [(participante, papel)], com o papel resolvido.

    Inclui organizador, palestrantes das atividades e inscritos. A ordem é
    alfabética pelo nome, que é a ordem prática de uma mesa de credenciamento.
    """
    ids = set()
    if evento.organizador_id:
        ids.add(evento.organizador_id)
    ids.update(
        evento.atividades.values_list("palestrantes__id", flat=True)
    )
    ids.update(
        Inscricao.objects.filter(atividade__evento=evento)
        .values_list("participante_id", flat=True)
    )
    ids.discard(None)

    pessoas = Participante.objects.filter(id__in=ids)

    resultado = []
    for pessoa in sorted(pessoas, key=lambda p: (p.first_name or "", p.last_name or "", p.id)):
        papel = papel_no_evento(pessoa, evento)
        if papel:
            resultado.append((pessoa, papel))
    return resultado


# --------------------------------------------------------------------------
# Token do QR e código curto
# --------------------------------------------------------------------------

def gerar_token(usuario_id, evento_id=None, tipo="cracha", atividade_id=None):
    """Token assinado que vai dentro do QR.

    `tipo` distingue crachá de certificado: os dois usam a mesma rota pública de
    verificação (/c/<token>/), e o tipo decide o que a página mostra.
    """
    dados = {"u": int(usuario_id), "t": tipo}
    if evento_id:
        dados["e"] = int(evento_id)
    if atividade_id:
        dados["a"] = int(atividade_id)
    return signing.dumps(dados, salt=SAL_TOKEN, compress=True)


def ler_token(token, max_age=None):
    """Devolve o conteúdo do token ou levanta `CrachaInvalido`.

    `max_age` fica em segundos e não é aplicado por padrão: um crachá impresso
    precisa continuar válido enquanto o evento acontece.
    """
    try:
        return signing.loads(token, salt=SAL_TOKEN, max_age=max_age)
    except signing.SignatureExpired as erro:
        raise CrachaInvalido("Este crachá expirou.") from erro
    except signing.BadSignature as erro:
        raise CrachaInvalido("Crachá inválido: o código não confere.") from erro


def url_verificacao(token):
    """URL absoluta que vai dentro do QR (usa SITE_URL, que é configurável)."""
    base = (getattr(settings, "SITE_URL", "") or "").rstrip("/")
    caminho = f"/c/{token}/"
    return f"{base}{caminho}" if base else caminho


def codigo_curto(usuario_id, evento_id=None):
    """Código de 6 caracteres para digitação manual, no formato `7K2-9QF`.

    É derivado (não guardado), então quem confere calcula e compara — não existe
    tabela de códigos para vazar ou manter. Sem evento, o código é só do usuário.
    """
    semente = f"{SAL_TOKEN}|{evento_id or 0}|{int(usuario_id)}".encode()
    numero = int.from_bytes(hashlib.sha256(semente).digest()[:6], "big")
    letras = []
    for _ in range(TAMANHO_CODIGO):
        numero, resto = divmod(numero, len(ALFABETO_CODIGO))
        letras.append(ALFABETO_CODIGO[resto])
    cru = "".join(letras)
    return f"{cru[:3]}-{cru[3:]}"


def normalizar_codigo(texto):
    """Deixa o código digitado comparável: sem espaços, sem hífen, em maiúsculas."""
    return "".join(c for c in (texto or "").upper() if c.isalnum())


def buscar_por_codigo(texto, evento=None):
    """Acha (participante, papel, evento) pelo código curto digitado.

    A busca é feita sobre os candidatos reais — as pessoas com papel no evento —
    em vez de existir um índice de códigos. Assim o código nunca "vaza" uma
    listagem de pessoas de outros eventos.
    """
    alvo = normalizar_codigo(texto)
    if len(alvo) != TAMANHO_CODIGO:
        return None

    if evento is not None:
        candidatos = [(p, papel, evento) for p, papel in pessoas_do_evento(evento)]
    else:
        candidatos = []
        for pessoa in Participante.objects.all().only("id", "first_name", "last_name", "email"):
            for ev in eventos_com_papel(pessoa):
                papel = papel_no_evento(pessoa, ev)
                if papel:
                    candidatos.append((pessoa, papel, ev))

    for pessoa, papel, ev in candidatos:
        if normalizar_codigo(codigo_curto(pessoa.id, ev.id)) == alvo:
            return pessoa, papel, ev
    return None


# --------------------------------------------------------------------------
# QR e crachá (estrutura comum à tela e ao PDF)
# --------------------------------------------------------------------------

def imagem_qr(conteudo, caixa=8, borda=1):
    """QR como imagem Pillow (usada no PDF)."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=caixa,
        border=borda,
    )
    qr.add_data(conteudo)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").get_image().convert("RGB")


def qr_como_data_url(conteudo, caixa=8, borda=1):
    """QR embutido como data URL: o `<img>` do crachá na tela não faz outra requisição."""
    buffer = io.BytesIO()
    imagem_qr(conteudo, caixa=caixa, borda=borda).save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def montar_cracha(usuario, evento, papel=None):
    """Todos os dados que a tela e o PDF precisam para desenhar um crachá."""
    papel = papel or papel_no_evento(usuario, evento)
    if not papel:
        return None
    token = gerar_token(usuario.id, evento.id, tipo="cracha")
    url = url_verificacao(token)
    return {
        "usuario": usuario,
        "evento": evento,
        "nome": nome_completo(usuario),
        "periodo": periodo_legivel(evento),
        "papel": papel,
        "papel_rotulo": ROTULOS_PAPEL.get(papel, papel),
        "token": token,
        "url": url,
        "codigo": codigo_curto(usuario.id, evento.id),
        "qr": qr_como_data_url(url),
    }


def crachas_do_usuario(usuario):
    """Crachás do usuário, um por evento em que ele tem papel."""
    crachas = []
    for evento in eventos_com_papel(usuario):
        cracha = montar_cracha(usuario, evento)
        if cracha:
            crachas.append(cracha)
    return crachas


def url_da_logo():
    """URL da logo institucional, quando o arquivo existe.

    A logo vive em `media/` (é a mesma que o certificado usa), não em `static/`.
    Devolver None sem o arquivo faz o crachá seguir válido, apenas sem a marca.
    """
    if (settings.MEDIA_ROOT / "logo_ifmg.png").exists():
        return f"{settings.MEDIA_URL.rstrip('/')}/logo_ifmg.png"
    return None


def nome_completo(usuario):
    """Nome de exibição do crachá, com fallback para o e-mail."""
    nome = f"{usuario.first_name or ''} {usuario.last_name or ''}".strip()
    return nome or usuario.email or usuario.username or f"Usuário {usuario.id}"


def periodo_legivel(evento):
    """Data do evento em texto curto: `10/09/2026` ou `10 a 11/09/2026`."""
    if not evento.data_inicio:
        return ""
    if not evento.data_fim or evento.data_fim == evento.data_inicio:
        return evento.data_inicio.strftime("%d/%m/%Y")
    if (evento.data_inicio.year, evento.data_inicio.month) == (
        evento.data_fim.year,
        evento.data_fim.month,
    ):
        return f"{evento.data_inicio.day:02d} a {evento.data_fim.strftime('%d/%m/%Y')}"
    return f"{evento.data_inicio.strftime('%d/%m/%Y')} a {evento.data_fim.strftime('%d/%m/%Y')}"


# --------------------------------------------------------------------------
# PDF em lote (10x7 cm, um crachá por página)
# --------------------------------------------------------------------------

LARGURA_MM = 100
ALTURA_MM = 70


def imagem_para_faixa(evento, largura_alvo, altura_alvo):
    """Recorta a imagem do evento no formato da faixa (equivalente ao `cover` do CSS).

    `drawImage` do reportlab estica a imagem; sem este recorte, a foto do evento
    sai distorcida na faixa do crachá.
    """
    from PIL import Image

    if not evento.imagem:
        return None
    try:
        imagem = Image.open(evento.imagem.path).convert("RGB")
    except Exception:
        return None

    proporcao_alvo = largura_alvo / float(altura_alvo)
    largura, altura = imagem.size
    if largura / float(altura) > proporcao_alvo:
        nova_largura = int(altura * proporcao_alvo)
        esquerda = (largura - nova_largura) // 2
        imagem = imagem.crop((esquerda, 0, esquerda + nova_largura, altura))
    else:
        nova_altura = int(largura / proporcao_alvo)
        topo = (altura - nova_altura) // 2
        imagem = imagem.crop((0, topo, largura, topo + nova_altura))
    return imagem


def gerar_pdf_crachas_evento(evento):
    """PDF com os crachás de todas as pessoas com papel no evento.

    Uma página de 10x7 cm por pessoa — o tamanho padrão de crachá com cordão.
    Devolve (nome_do_arquivo, ContentFile).
    """
    from reportlab.lib.colors import HexColor, white
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as canvas_pdf

    pessoas = pessoas_do_evento(evento)
    buffer = io.BytesIO()
    largura = LARGURA_MM * mm
    altura = ALTURA_MM * mm
    c = canvas_pdf.Canvas(buffer, pagesize=(largura, altura))

    verde = HexColor("#2f9e41")
    verde_ink = HexColor("#23792f")
    verde_soft = HexColor("#e8f5ea")
    texto = HexColor("#3c3c3c")
    cinza = HexColor("#6b6b6b")
    borda = HexColor("#e5e5e5")
    oliva_escuro = HexColor("#3f4d1e")
    oliva_claro = HexColor("#7d9440")

    faixa_altura = 20 * mm
    topo_altura = 9 * mm
    margem = 6 * mm

    logo_caminho = settings.MEDIA_ROOT / "logo_ifmg.png"

    for pessoa, papel in pessoas:
        # --- tarja superior de identificação ---
        c.setFillColor(verde)
        c.rect(0, altura - topo_altura, largura, topo_altura, fill=True, stroke=False)
        if logo_caminho.exists():
            try:
                c.setFillColor(white)
                c.roundRect(margem / 2, altura - topo_altura + 1.4 * mm,
                            topo_altura / mm * mm * 0.75, topo_altura - 2.8 * mm, 1 * mm,
                            fill=True, stroke=False)
                c.drawImage(
                    ImageReader(str(logo_caminho)),
                    margem / 2 + 1 * mm, altura - topo_altura + 2 * mm,
                    width=12 * mm, height=topo_altura - 4 * mm,
                    preserveAspectRatio=True, anchor="c", mask="auto",
                )
            except Exception:
                pass
        c.setFillColor(white)
        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(margem / 2 + 15 * mm, altura - topo_altura + 3.4 * mm, "IFMG · Campus Ponte Nova")

        # --- faixa com a imagem do evento (ou o gradiente oliva de reserva) ---
        y_faixa = altura - topo_altura - faixa_altura
        imagem_faixa = imagem_para_faixa(evento, largura, faixa_altura)
        if imagem_faixa is not None:
            c.drawImage(
                ImageReader(imagem_faixa), 0, y_faixa,
                width=largura, height=faixa_altura,
                preserveAspectRatio=False, mask="auto",
            )
        else:
            c.saveState()
            caminho = c.beginPath()
            caminho.rect(0, y_faixa, largura, faixa_altura)
            c.clipPath(caminho, stroke=0, fill=0)
            c.linearGradient(0, y_faixa, largura, y_faixa + faixa_altura,
                             [oliva_escuro, oliva_claro])
            c.restoreState()

        # --- título e período do evento ---
        c.setFillColor(texto)
        c.setFont("Helvetica-Bold", 9.5)
        titulo = (evento.title or "").strip()
        if len(titulo) > 58:
            titulo = titulo[:57].rstrip() + "…"
        c.drawString(margem, y_faixa - 6.2 * mm, titulo)
        c.setFont("Helvetica", 7)
        c.setFillColor(cinza)
        subtitulo = " · ".join(p for p in [periodo_legivel(evento), (evento.local or "").strip()] if p)
        if len(subtitulo) > 74:
            subtitulo = subtitulo[:73].rstrip() + "…"
        c.drawString(margem, y_faixa - 10.4 * mm, subtitulo)

        # --- nome em destaque + papel ---
        c.setStrokeColor(borda)
        c.setLineWidth(0.6)
        c.line(margem, y_faixa - 13.4 * mm, largura - margem, y_faixa - 13.4 * mm)

        nome = nome_completo(pessoa)
        corpo_nome = 15 if len(nome) <= 26 else (12.5 if len(nome) <= 34 else 10.5)
        c.setFillColor(texto)
        c.setFont("Helvetica-Bold", corpo_nome)
        c.drawString(margem, y_faixa - 21 * mm, nome)

        rotulo = ROTULOS_PAPEL.get(papel, papel).upper()
        c.setFont("Helvetica-Bold", 8)
        largura_rotulo = c.stringWidth(rotulo, "Helvetica-Bold", 8) + 8 * mm
        c.setFillColor(verde_soft)
        c.roundRect(margem, y_faixa - 29 * mm, largura_rotulo, 6 * mm, 3 * mm,
                    fill=True, stroke=False)
        c.setFillColor(verde_ink)
        c.drawString(margem + 4 * mm, y_faixa - 27.4 * mm, rotulo)

        # --- QR + código curto (canto inferior direito) ---
        lado_qr = 22 * mm
        x_qr = largura - margem - lado_qr
        y_qr = margem - 1 * mm
        qr = imagem_qr(url_verificacao(gerar_token(pessoa.id, evento.id, tipo="cracha")))
        c.drawImage(ImageReader(qr), x_qr, y_qr, width=lado_qr, height=lado_qr, mask="auto")

        c.setFont("Helvetica-Bold", 8.5)
        c.setFillColor(texto)
        codigo = codigo_curto(pessoa.id, evento.id)
        c.drawRightString(largura - margem, y_qr + lado_qr + 1.6 * mm, codigo)
        c.setFont("Helvetica", 5.6)
        c.setFillColor(cinza)
        c.drawRightString(largura - margem, y_qr + lado_qr + 4.6 * mm,
                          "Aponte a câmera para confirmar presença")
        c.drawRightString(largura - margem, margem - 3.4 * mm, "código para digitação manual")

        c.showPage()

    c.save()
    buffer.seek(0)
    apelido = "evento"
    if evento.title:
        apelido = "".join(c if c.isalnum() else "-" for c in evento.title.lower())[:40].strip("-")
    return f"crachas-{apelido}.pdf", ContentFile(buffer.read())


# ---------------------------------------------------------------------------
# QR em bytes, verificação, check-in e permissão
#
# Estas funções são a regra única da funcionalidade: a página pública, a API e
# (na F2) a tela de check-in chamam as mesmas — assim não existe a chance de a
# página dizer "válido" e a API dizer "inválido" para o mesmo crachá.
# ---------------------------------------------------------------------------


def png_qr(conteudo, caixa=10, borda=2):
    """QR como PNG em bytes — para o endpoint que devolve a imagem do QR."""
    buffer = io.BytesIO()
    imagem_qr(conteudo, caixa=caixa, borda=borda).save(buffer, format="PNG")
    return buffer.getvalue()


def pode_gerenciar_evento(usuario, evento):
    """Quem pode operar crachás e check-in de um evento.

    Vale para os quatro casos reais do sistema: staff, superusuário, quem tem a
    flag de organizador e o organizador cadastrado no próprio evento. Sem isso,
    um organizador de outro evento operaria o check-in alheio.
    """
    if not usuario or not getattr(usuario, "is_authenticated", False):
        return False
    if usuario.is_staff or usuario.is_superuser:
        return True
    if getattr(usuario, "is_organizador", False):
        return True
    return bool(evento and evento.organizador_id == usuario.id)


def pode_exibir_qr_atividade(usuario, atividade):
    """Quem pode exibir o QR de presença da atividade.

    É quem organiza o evento **ou** quem palestra naquela atividade — os dois
    estão na sala no momento e podem mostrar o código para a turma.
    """
    if pode_gerenciar_evento(usuario, atividade.evento):
        return True
    if not usuario or not getattr(usuario, "is_authenticated", False):
        return False
    return atividade.palestrantes.filter(id=usuario.id).exists()


def verificar_token(token):
    """Verifica um token de crachá ou de certificado e devolve o resultado.

    Regra única da verificação, usada pela página pública e pela API. Devolve
    sempre um dicionário com `valido`, `erro` e `status`, para as duas pontas
    contarem a mesma história.
    """
    try:
        dados = ler_token(token)
    except CrachaInvalido as erro:
        return {"valido": False, "erro": str(erro), "status": 404}

    pessoa = Participante.objects.filter(id=dados.get("u")).first()
    if pessoa is None:
        return {
            "valido": False,
            "status": 404,
            "erro": "Este código aponta para um usuário que não existe mais.",
        }

    resultado = {
        "tipo": dados.get("t") or "cracha",
        "pessoa": pessoa,
        "nome": nome_completo(pessoa),
    }

    # -- Certificado ---------------------------------------------------------
    if resultado["tipo"] == "certificado":
        # Casa com o que a linha do certificado realmente guarda: na emissão por
        # atividade a linha tem `atividade` (e `evento` vazio); na emissão por
        # evento é o contrário. Exigir os dois daria 404 em certificado bom.
        consulta = Certificado.objects.filter(participante=pessoa)
        if dados.get("a"):
            consulta = consulta.filter(atividade_id=dados["a"])
        elif dados.get("e"):
            consulta = consulta.filter(evento_id=dados["e"])

        certificado = consulta.first()
        if certificado is None:
            return {
                "valido": False,
                "status": 404,
                "erro": "Não há certificado emitido com este código para esta pessoa.",
            }

        evento = certificado.evento or (
            certificado.atividade.evento if certificado.atividade else None
        )
        resultado.update({
            "valido": True,
            "status": 200,
            "certificado": certificado,
            "atividade": certificado.atividade,
            "evento": evento,
            "papel": None,
            "papel_rotulo": "Certificado",
            "periodo": periodo_legivel(evento) if evento else "",
        })
        return resultado

    # -- Crachá: o papel é reconferido agora --------------------------------
    evento = Evento.objects.filter(id=dados.get("e")).first()
    if evento is None:
        return {"valido": False, "status": 404, "erro": "O evento deste crachá não existe mais."}

    papel = papel_no_evento(pessoa, evento)
    if not papel:
        return {
            "valido": False,
            "status": 404,
            "erro": "Esta pessoa não tem mais vínculo com o evento, então o crachá não vale mais.",
        }

    resultado.update({
        "valido": True,
        "status": 200,
        "evento": evento,
        "papel": papel,
        "papel_rotulo": ROTULOS_PAPEL.get(papel, papel),
        "periodo": periodo_legivel(evento),
    })
    return resultado


def pessoa_por_token_ou_codigo(token=None, codigo=None, evento=None):
    """Descobre quem é a pessoa a partir do token do crachá ou do código digitado.

    Devolve (pessoa, papel, evento) — ou (None, None, None) quando não acha.
    O token precisa ser do MESMO evento do contexto: crachá de um evento não
    vale no check-in de outro. É essa checagem que impede usar, no evento B, um
    QR fotografado no evento A.
    """
    if token:
        try:
            dados = ler_token(token)
        except CrachaInvalido:
            return None, None, None

        pessoa = Participante.objects.filter(id=dados.get("u")).first()
        if pessoa is None:
            return None, None, None

        if evento is not None and dados.get("e") and int(dados["e"]) != evento.id:
            return None, None, None

        evento_do_token = evento
        if dados.get("e"):
            evento_do_token = Evento.objects.filter(id=dados["e"]).first()
        if evento_do_token is None:
            return None, None, None

        return pessoa, papel_no_evento(pessoa, evento_do_token), evento_do_token

    if codigo:
        achado = buscar_por_codigo(codigo, evento=evento)
        if achado is None:
            return None, None, None
        return achado

    return None, None, None


def notificar_presenca_confirmada(atividade, presenca_id):
    """Avisa quem está com a tela do QR aberta que alguém confirmou presença.

    O evento leva só o sinal — atividade, evento e id da presença. **Nenhum dado
    pessoal**: o servidor de socket do projeto não tem autenticação nem salas, e
    o que passa por ele chega a qualquer cliente conectado. Os detalhes (nome,
    papel, hora) quem busca é a tela do organizador, autenticada, na API.

    Notificar é acessório: se o socket estiver fora, a presença já foi gravada e
    a tela se atualiza pelo polling de segurança.
    """
    from .services import notify_socketio  # import local: evita ciclo de módulos

    dados = {
        "atividade_id": atividade.id,
        "evento_id": atividade.evento_id,
        "presenca_id": presenca_id,
    }

    try:
        asyncio.run(notify_socketio("presenca_confirmada", dados))
    except RuntimeError:
        # Já existe um laço de eventos em execução (contexto async): o projeto
        # usa este mesmo desvio em eventos/signals.py.
        threading.Thread(
            target=lambda: asyncio.run(notify_socketio("presenca_confirmada", dados)),
            daemon=True,
        ).start()
    except Exception as erro:
        print(f"[SocketIO] presença não notificada: {erro}")


def registrar_presenca(atividade, pessoa, registrada_por=None, origem="qr"):
    """Registra a presença e devolve (presenca, criada, motivo_da_recusa).

    Idempotente: o segundo check-in da mesma pessoa na mesma atividade devolve a
    presença que já existe, sem duplicar (o model tem constraint de unicidade).

    Recusa — devolvendo (None, False, "explicação") — em dois casos:
      - a pessoa não tem papel no evento: dar presença a quem não é do evento
        não faz sentido e seria porta aberta para fraude;
      - está fora da janela da atividade: a janela existe porque o QR da
        atividade é público, e sem ela uma foto compartilhada valeria para sempre.

    A marcação manual (origem="manual"), feita pela organização, ignora a janela
    de propósito: quem organiza pode confirmar depois, ao fechar a lista.
    """
    if origem != "manual":
        permitido, motivo = atividade_aceita_presenca_agora(atividade)
        if not permitido:
            return None, False, motivo

    papel = papel_no_evento(pessoa, atividade.evento)
    if not papel:
        return None, False, "Esta pessoa não tem vínculo com o evento, então não pode ter presença registrada."

    presenca, criada = Presenca.objects.get_or_create(
        atividade=atividade,
        participante=pessoa,
        defaults={
            "papel": papel,
            "registrada_por": registrada_por,
            "origem": origem,
        },
    )

    if criada:
        # Releitura do mesmo crachá não é novidade: só a presença nova avisa.
        notificar_presenca_confirmada(atividade, presenca.id)

    return presenca, criada, ""


# ---------------------------------------------------------------------------
# Presença: janela, QR rotativo da atividade e os dois fluxos de confirmação
#
# FLUXO A (organização confirma): alguém da organização lê o QR do crachá.
#   A1 -> pela página de check-in, com a câmera ligada (um scanner por atividade);
#   A2 -> pela câmera nativa do celular, que abre /c/<token>/: se houver UMA só
#         atividade do evento na janela, a presença é gravada sem nenhum toque.
# FLUXO B (a pessoa confirma): ela lê o QR da ATIVIDADE, exibido pela organização
#   ou pelo palestrante. Quem ela é vem da própria sessão (por isso o login).
# ---------------------------------------------------------------------------


def janela_de_presenca(atividade, agora=None):
    """Devolve (abre_em, fecha_em) da janela de confirmação desta atividade."""
    agora = agora or timezone.now()
    margem_antes = timedelta(minutes=getattr(settings, "PRESENCA_MARGEM_ANTES_MINUTOS", 30))
    margem_depois = timedelta(hours=getattr(settings, "PRESENCA_MARGEM_DEPOIS_HORAS", 2))
    return (
        (atividade.data_hora_inicio - margem_antes) if atividade.data_hora_inicio else None,
        (atividade.data_hora_fim + margem_depois) if atividade.data_hora_fim else None,
    )


def atividade_aceita_presenca_agora(atividade, agora=None):
    """A atividade aceita confirmação de presença neste momento? (permitido, motivo)."""
    agora = agora or timezone.now()
    abre_em, fecha_em = janela_de_presenca(atividade, agora)
    if abre_em and agora < abre_em:
        return False, (
            f"A confirmação desta atividade abre {abre_em.strftime('%d/%m às %H:%M')}."
        )
    if fecha_em and agora > fecha_em:
        return False, (
            f"O prazo para confirmar presença nesta atividade terminou em "
            f"{fecha_em.strftime('%d/%m às %H:%M')}."
        )
    return True, ""


def atividades_na_janela(evento, agora=None):
    """Atividades do evento cuja janela de confirmação inclui este momento."""
    agora = agora or timezone.now()
    return [
        atividade
        for atividade in evento.atividades.all().order_by("data_hora_inicio", "id")
        if atividade_aceita_presenca_agora(atividade, agora)[0]
    ]


def gerar_token_atividade(atividade_id):
    """Código do QR da atividade (o que a organização exibe na tela).

    Assinado e sem estado: não precisa de tabela. A validade curta é conferida
    na leitura (`ler_token_atividade`), e é o que faz o QR rotativo valer.
    """
    return signing.dumps(
        {"a": int(atividade_id), "t": "atividade"}, salt=SAL_PRESENCA, compress=True
    )


def url_presenca_atividade(token):
    """URL pública que o QR da atividade abre (é o que a pessoa escaneia)."""
    base = (getattr(settings, "SITE_URL", "") or "").rstrip("/")
    caminho = f"/p/{token}/"
    return f"{base}{caminho}" if base else caminho


def ler_token_atividade(token, validade=None):
    """Lê o código da atividade recusando o que passou da validade."""
    validade = validade or getattr(settings, "PRESENCA_QR_VALIDADE_SEGUNDOS", 300)
    try:
        return signing.loads(token, salt=SAL_PRESENCA, max_age=validade)
    except signing.SignatureExpired as erro:
        raise CrachaInvalido(
            "Este código da atividade expirou. Escaneie o QR que está na tela."
        ) from erro
    except signing.BadSignature as erro:
        raise CrachaInvalido("Código de atividade inválido.") from erro


def confirmar_por_token_atividade(token, pessoa):
    """FLUXO B — a própria pessoa confirmou, escaneando o QR da atividade.

    Devolve (atividade, presenca, criada, erro). A pessoa vem da sessão: é por
    isso que o fluxo exige login — sem saber quem é, não há presença a registrar.
    """
    try:
        dados = ler_token_atividade(token)
    except CrachaInvalido as erro:
        return None, None, False, str(erro)

    atividade = (
        Atividade.objects.select_related("evento").filter(id=dados.get("a")).first()
    )
    if atividade is None:
        return None, None, False, "A atividade deste código não existe mais."

    presenca, criada, motivo = registrar_presenca(
        atividade, pessoa, registrada_por=pessoa, origem="proprio"
    )
    if presenca is None:
        return atividade, None, False, motivo

    return atividade, presenca, criada, ""


def confirmar_para_organizador(pessoa, evento, atividade=None, registrada_por=None):
    """FLUXO A2 — a organização leu o crachá e a confirmação sai sozinha.

    Sem atividade indicada, confirma automaticamente **somente quando há uma
    única atividade do evento na janela** — é o caso que permite zero toques
    (apontei a câmera, confirmou). Havendo mais de uma, devolve as candidatas
    para a organização escolher, porque adivinhar seria registrar presença na
    atividade errada.

    Devolve um dicionário com candidatas, atividade, presenca, criada e motivo.
    """
    candidatas = atividades_na_janela(evento)

    if atividade is None:
        if not candidatas:
            return {
                "candidatas": [],
                "atividade": None,
                "presenca": None,
                "criada": False,
                "motivo": "Nenhuma atividade deste evento está na janela de confirmação agora.",
            }
        if len(candidatas) > 1:
            return {
                "candidatas": candidatas,
                "atividade": None,
                "presenca": None,
                "criada": False,
                "motivo": "Mais de uma atividade deste evento está na janela. Escolha em qual confirmar.",
            }
        atividade = candidatas[0]

    presenca, criada, motivo = registrar_presenca(
        atividade, pessoa, registrada_por=registrada_por, origem="auto"
    )
    return {
        "candidatas": candidatas,
        "atividade": atividade,
        "presenca": presenca,
        "criada": criada,
        "motivo": motivo,
    }
