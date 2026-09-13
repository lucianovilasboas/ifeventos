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
from datetime import date, datetime, timedelta
import threading

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

# Ordem em que os papéis aparecem: do mais alto para o mais baixo. A MESMA
# pessoa pode organizar, palestrar e estar inscrita no MESMO evento — e o crachá
# é um só por evento, então ele mostra todos os papéis que ela tem ali, com o
# primeiro em destaque.
PAPEIS_ORDEM = ("organizador", "palestrante", "participante")


def papeis_no_evento(usuario, evento):
    """TODOS os papéis do usuário NAQUELE evento, do mais alto para o mais baixo.

    Os campos `is_organizador`/`is_palestrante`/`is_participante` do Participante
    são globais, mas o papel do crachá é do evento: quem organiza o evento A
    costuma ser apenas participante no evento B. Por isso derivamos do contexto:

        organizador  -> é o organizador cadastrado no evento;
        palestrante  -> está entre os palestrantes de alguma atividade do evento;
        participante -> tem inscrição em alguma atividade do evento.

    Devolve lista vazia quando a pessoa não tem papel nenhum (e aí não recebe
    crachá). Lista, e não um papel só, porque quem organiza e também se inscreveu
    perdia a inscrição no crachá pela precedência.
    """
    if not evento or not usuario or not getattr(usuario, "is_authenticated", False):
        return []

    papeis = []
    if evento.organizador_id == usuario.id:
        papeis.append("organizador")
    if evento.atividades.filter(palestrantes=usuario).exists():
        papeis.append("palestrante")
    if Inscricao.objects.filter(participante=usuario, atividade__evento=evento).exists():
        papeis.append("participante")
    return papeis


def papel_no_evento(usuario, evento):
    """Papel PRINCIPAL do usuário no evento (None se não tem nenhum).

    É o papel usado onde um só resolve: registro de presença e verificação. Para
    desenhar o crachá use `papeis_no_evento`, que devolve todos.
    """
    papeis = papeis_no_evento(usuario, evento)
    return papeis[0] if papeis else None


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
    """Todos os dados que a tela e o PDF precisam para desenhar um crachá.

    `papeis`/`papeis_rotulos` são a lista completa (o crachá é um por evento);
    `papel`/`papel_rotulo` continuam sendo o principal, para quem só quer um.
    """
    papeis = papeis_no_evento(usuario, evento)
    if papel and papel not in papeis:
        # Quem chamou informou um papel (ex.: fluxo de presença): ele vira o
        # principal, sem apagar os outros papéis que a pessoa tem no evento.
        papeis.insert(0, papel)
    if not papeis:
        return None
    principal = papeis[0]
    token = gerar_token(usuario.id, evento.id, tipo="cracha")
    url = url_verificacao(token)
    return {
        "usuario": usuario,
        "evento": evento,
        "nome": nome_completo(usuario),
        "periodo": periodo_legivel(evento),
        "papel": principal,
        "papel_rotulo": ROTULOS_PAPEL.get(principal, principal),
        "papeis": papeis,
        "papeis_rotulos": [ROTULOS_PAPEL.get(p, p) for p in papeis],
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


# A marca do crachá tem arquivo próprio, e não o do certificado (`logo_ifmg.png`):
# assim dá para trocar a cara do crachá sem mexer no certificado. Sem o arquivo
# novo, o crachá cai na logo antiga — nunca fica sem marca.
LOGO_CRACHA = "logo_cracha.png"
LOGO_CRACHA_ANTERIOR = "logo_ifmg.png"


def arquivo_logo_cracha():
    """Caminho da logo do crachá dentro de `media/` (None se não houver nenhuma)."""
    for nome in (LOGO_CRACHA, LOGO_CRACHA_ANTERIOR):
        caminho = settings.MEDIA_ROOT / nome
        if caminho.exists():
            return caminho
    return None


def url_da_logo():
    """URL pública da logo do crachá, quando o arquivo existe.

    As logos vivem em `media/` (não em `static/`), como a do certificado.
    Devolver None sem o arquivo faz o crachá seguir válido, apenas sem a marca.
    """
    caminho = arquivo_logo_cracha()
    if caminho is None:
        return None
    return f"{settings.MEDIA_URL.rstrip('/')}/{caminho.name}"


def nome_completo(usuario):
    """Nome de exibição do crachá, com fallback para o e-mail."""
    nome = f"{usuario.first_name or ''} {usuario.last_name or ''}".strip()
    return nome or usuario.email or usuario.username or f"Usuário {usuario.id}"


def periodo_legivel(evento):
    """Data do evento em texto curto: `10/09/2026` ou `10 a 11/09/2026`."""
    inicio = _como_data(evento.data_inicio)
    fim = _como_data(evento.data_fim)
    if not inicio:
        return ""
    if not fim or fim == inicio:
        return inicio.strftime("%d/%m/%Y")
    if (inicio.year, inicio.month) == (fim.year, fim.month):
        return f"{inicio.day:02d} a {fim.strftime('%d/%m/%Y')}"
    return f"{inicio.strftime('%d/%m/%Y')} a {fim.strftime('%d/%m/%Y')}"


def _como_data(valor):
    """Devolve a data, aceitando também texto ISO.

    O campo é DateField, então o valor vem como `date` quando o objeto sai do
    banco — mas um evento montado na mão (teste, importação, API) pode chegar com
    a data em texto, e aí `.year` estourava com AttributeError ao gerar o crachá.
    """
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if isinstance(valor, str):
        try:
            return datetime.fromisoformat(valor).date()
        except ValueError:
            return None
    return None


# --------------------------------------------------------------------------
# PDF em lote: 4 crachás por folha A4 (2 x 2 de 105 x 148,5 mm)
#
# 105 x 148,5 mm é a MAIOR medida que fecha 2x2 no A4: 210 mm de largura por
# 297 mm de altura, exatos. Com 105 x 150 mm a folha pediria 300 mm e a última
# fileira sairia cortada pela impressora — daí 1,5 mm a menos no comprimento,
# que não se percebe na mão e salva a fileira de baixo.
#
# Dois modelos, escolhidos na hora de gerar: "etiqueta" (fundo colorido com a
# foto do evento, círculo branco da logo e etiqueta branca do nome — o modelo
# do crachá de cordão) e "classico" (tarja verde, faixa do evento e nome no
# corpo, como o crachá que aparece na tela).
# --------------------------------------------------------------------------

LARGURA_CARTAO_MM = 105
ALTURA_CARTAO_MM = 148.5
A4_LARGURA_MM = 210
A4_ALTURA_MM = 297
COLUNAS_POR_FOLHA = 2
LINHAS_POR_FOLHA = 2
CARTOES_POR_FOLHA = COLUNAS_POR_FOLHA * LINHAS_POR_FOLHA

MODELOS_CRACHA = {
    "etiqueta": "Etiqueta (fundo colorido e etiqueta branca do nome)",
    "classico": "Clássico (tarja verde e faixa do evento)",
}
MODELO_PADRAO = "etiqueta"


def modelo_de_cracha(modelo):
    """Aceita apenas modelo conhecido — `?modelo=` inválido não pode virar 500."""
    return modelo if modelo in MODELOS_CRACHA else MODELO_PADRAO


def _paleta():
    """Cores do crachá em um lugar só (tela e papel contam a mesma história)."""
    from reportlab.lib.colors import HexColor

    return {
        "verde": HexColor("#2f9e41"),
        "verde_escuro": HexColor("#1d7a2f"),
        "verde_ink": HexColor("#23792f"),
        "verde_soft": HexColor("#e8f5ea"),
        "azul": HexColor("#1f5fa8"),
        "texto": HexColor("#3c3c3c"),
        "cinza": HexColor("#6b6b6b"),
        "borda": HexColor("#e5e5e5"),
        "branco": HexColor("#ffffff"),
        "veu": HexColor("#0b2e18"),
        "corte": HexColor("#b9b9b9"),
    }


def _quebrar_texto(texto, fonte, tamanho, largura_max, max_linhas=2):
    """Quebra o texto em linhas que caibam na largura.

    `drawString` do reportlab não quebra linha sozinho: nome comprido sairia
    vazando para fora do crachá. Quando sobra texto, a última linha recebe "…"
    — melhor avisar que cortou do que sumir com o fim do nome.
    """
    from reportlab.pdfbase.pdfmetrics import stringWidth

    # Palavra sozinha mais larga que a caixa (nome sem espaço — acontece quando a
    # pessoa não cadastrou nome e o e-mail vira o nome do crachá) é fatiada antes
    # da quebra normal; sem isto a linha vazaria para fora do crachá.
    palavras = []
    for palavra in (texto or "").split():
        while stringWidth(palavra, fonte, tamanho) > largura_max and len(palavra) > 1:
            corte = len(palavra)
            while corte > 1 and stringWidth(palavra[:corte], fonte, tamanho) > largura_max:
                corte -= 1
            palavras.append(palavra[:corte])
            palavra = palavra[corte:]
        palavras.append(palavra)

    linhas, atual, i = [], "", 0
    while i < len(palavras):
        proposta = f"{atual} {palavras[i]}".strip()
        if not atual or stringWidth(proposta, fonte, tamanho) <= largura_max:
            atual = proposta
            i += 1
        else:
            linhas.append(atual)
            atual = ""
            if len(linhas) == max_linhas:
                break
    if atual and len(linhas) < max_linhas:
        linhas.append(atual)
    if not linhas:
        return [""]
    if i < len(palavras):  # sobrou texto além do que cabe
        ultima = linhas[-1]
        while ultima and stringWidth(ultima + "…", fonte, tamanho) > largura_max:
            ultima = ultima[:-1]
        linhas[-1] = ultima + "…"
    return linhas


def _desenhar_linhas(c, linhas, fonte, tamanho, x, y, entrelinha, largura=None,
                     alinhamento="left", cor=None):
    """Desenha as linhas empilhadas a partir de `y` (a primeira é a mais alta)."""
    if cor is not None:
        c.setFillColor(cor)
    c.setFont(fonte, tamanho)
    for indice, linha in enumerate(linhas):
        linha_y = y - indice * entrelinha
        if alinhamento == "center" and largura is not None:
            c.drawCentredString(x + largura / 2.0, linha_y, linha)
        elif alinhamento == "right" and largura is not None:
            c.drawRightString(x + largura, linha_y, linha)
        else:
            c.drawString(x, linha_y, linha)


def _desenhar_logo(c, caminho, x, y, largura, altura):
    """Logo institucional no espaço dado. Sem o arquivo, o crachá segue válido."""
    from reportlab.lib.utils import ImageReader

    if not caminho or not caminho.exists():
        return False
    try:
        c.drawImage(ImageReader(str(caminho)), x, y, width=largura, height=altura,
                    preserveAspectRatio=True, anchor="c", mask="auto")
        return True
    except Exception:
        return False


def _linhas_de_corte(c, largura_folha, altura_folha, largura_cartao, altura_cartao):
    """Guias da guilhotina: só as linhas de dentro (as bordas a tesoura acerta sozinha).

    Crachá de 105 x 148,5 mm encosta na borda da folha, então não há margem para
    marca de corte por fora. As linhas internas somem no corte e evitam o corte
    torto de quem imprime em casa.
    """
    cor = _paleta()
    c.saveState()
    c.setStrokeColor(cor["corte"])
    c.setLineWidth(0.3)
    for coluna in range(1, COLUNAS_POR_FOLHA):
        x = coluna * largura_cartao
        c.line(x, 0, x, altura_folha)
    for linha in range(1, LINHAS_POR_FOLHA):
        y = linha * altura_cartao
        c.line(0, y, largura_folha, y)
    c.restoreState()


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


def _largura_papeis(rotulos, tamanho=9, tamanho_outros=7):
    """Largura que as tarjas de papel vão ocupar, SEM desenhar.

    Existe porque `_desenhar_papeis` mede enquanto desenha: para centralizar o
    conjunto antes do primeiro traço, a largura precisa ser calculável à parte —
    e as duas têm de concordar (mesmos recuos e mesmo respiro), senão o crachá
    impresso sai descentralizado em relação à tela.
    """
    from reportlab.lib.units import mm
    from reportlab.pdfbase.pdfmetrics import stringWidth

    total = 0
    for indice, rotulo in enumerate(rotulos):
        principal = indice == 0
        fonte = tamanho if principal else tamanho_outros
        recuo = 4 * mm if principal else 3 * mm
        total += stringWidth(rotulo, "Helvetica-Bold", fonte) + recuo * 2 + 2 * mm
    return total - 2 * mm


def _desenhar_papeis(c, rotulos, x, y, cor, altura=None, tamanho=9, tamanho_outros=7):
    """Tarjas de papel em linha: a PRINCIPAL cheia e as outras menores ao lado.

    O crachá é um por evento e mostra todos os papéis da pessoa nele — quem
    organiza e também se inscreveu aparece com ORGANIZADOR e PARTICIPANTE, em vez
    de perder a inscrição pela precedência. Devolve a largura total usada.
    """
    from reportlab.lib.units import mm

    altura = altura or 8 * mm
    cursor = x
    for indice, rotulo in enumerate(rotulos):
        principal = indice == 0
        fonte = tamanho if principal else tamanho_outros
        alto = altura if principal else altura * 0.78
        recuo = 4 * mm if principal else 3 * mm
        largura = c.stringWidth(rotulo, "Helvetica-Bold", fonte) + recuo * 2
        if principal:
            c.setFillColor(cor["verde_soft"])
            c.roundRect(cursor, y, largura, alto, alto / 2.0, fill=True, stroke=False)
        else:
            # Secundárias vazadas, como no CSS: a principal é a cheia.
            c.setStrokeColor(cor["verde_ink"])
            c.setLineWidth(0.3 * mm)
            c.roundRect(cursor, y, largura, alto, alto / 2.0, fill=False, stroke=True)
        c.setFillColor(cor["verde_ink"])
        c.setFont("Helvetica-Bold", fonte)
        c.drawString(cursor + recuo, y + alto / 2.0 - fonte * 0.18 * mm, rotulo)
        cursor += largura + 2 * mm
    return cursor - x - 1 * mm


def _cracha_etiqueta(c, pessoa, papeis_rotulos, evento, x, y, largura, altura, logo_caminho):
    """Modelo do crachá de cordão: fundo colorido, círculo da logo, etiqueta do nome.

    A etiqueta branca embaixo é o lugar do nome (é o que se lê de longe e o que
    a caneta preenche no crachá de papel); o QR fica dentro dela, no rodapé.
    """
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader

    cor = _paleta()
    nome = nome_completo(pessoa)
    rotulos = [rotulo.upper() for rotulo in papeis_rotulos]

    # 1) fundo: a foto do evento (com véu, senão o texto branco some) ou o
    #    gradiente institucional, que é o que a foto de referência tem.
    c.saveState()
    recorte = c.beginPath()
    recorte.rect(x, y, largura, altura)
    c.clipPath(recorte, stroke=0, fill=0)
    fundo = imagem_para_faixa(evento, largura, altura)
    if fundo is not None:
        c.drawImage(ImageReader(fundo), x, y, width=largura, height=altura,
                    preserveAspectRatio=False, mask="auto")
        c.setFillColor(cor["veu"])
        c.setFillAlpha(0.55)
        c.rect(x, y, largura, altura, fill=True, stroke=False)
        c.setFillAlpha(1)
    else:
        c.linearGradient(x, y, x, y + altura, [cor["azul"], cor["verde"]])
    c.restoreState()

    # 2) círculo branco com a logo, no alto e centralizado
    #    Caixa QUADRADA (e não larga e baixa) porque dentro de círculo a marca
    #    rendonda/vertical é que manda. 26 mm num círculo de 34 mm: a logo fica
    #    com 76% do diâmetro sem que os cantos encostem na borda do círculo.
    centro_x = x + largura / 2.0
    raio = 17 * mm
    centro_y = y + altura - 30 * mm
    c.setFillColor(cor["branco"])
    c.circle(centro_x, centro_y, raio, fill=True, stroke=False)
    _desenhar_logo(c, logo_caminho, centro_x - 13 * mm, centro_y - 13 * mm, 26 * mm, 26 * mm)

    # 3) instituição e evento, em branco sobre o fundo
    c.setFillColor(cor["branco"])
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(centro_x, centro_y - raio - 6 * mm, "IFMG · Campus Ponte Nova")

    _desenhar_linhas(
        c,
        _quebrar_texto(evento.title, "Helvetica-Bold", 14, largura - 20 * mm, 2),
        "Helvetica-Bold", 14, x + 10 * mm, centro_y - raio - 15 * mm, 6.6 * mm,
        largura=largura - 20 * mm, alinhamento="center", cor=cor["branco"],
    )

    subtitulo = " · ".join(p for p in [periodo_legivel(evento), (evento.local or "").strip()] if p)
    _desenhar_linhas(
        c, _quebrar_texto(subtitulo, "Helvetica", 9, largura - 24 * mm, 1),
        "Helvetica", 9, x + 12 * mm, centro_y - raio - 24 * mm, 4.6 * mm,
        largura=largura - 24 * mm, alinhamento="center", cor=cor["branco"],
    )

    # 4) a etiqueta branca do nome (com o QR dentro, no rodapé dela)
    #
    # Três faixas, de cima para baixo: nome (até duas linhas), tarja do papel e
    # rodapé com QR e código. As posições são fixas para que nome comprido — que
    # ocupa duas linhas — não encoste na tarja nem no QR.
    etiqueta_x = x + 8 * mm
    etiqueta_y = y + 8 * mm
    etiqueta_largura = largura - 16 * mm
    etiqueta_altura = 71 * mm
    c.setFillColor(cor["branco"])
    c.roundRect(etiqueta_x, etiqueta_y, etiqueta_largura, etiqueta_altura, 4 * mm,
                fill=True, stroke=False)

    corpo_nome = 21 if len(nome) <= 24 else (18 if len(nome) <= 34 else 15.5)
    _desenhar_linhas(
        c,
        _quebrar_texto(nome, "Helvetica-Bold", corpo_nome, etiqueta_largura - 8 * mm, 2),
        "Helvetica-Bold", corpo_nome, etiqueta_x + 4 * mm,
        etiqueta_y + etiqueta_altura - 7 * mm, corpo_nome * 0.44 * mm, cor=cor["texto"],
    )

    # Tarja(s) do papel em posição fixa: cae uma ou duas linhas de nome acima
    # delas (a segunda linha do nome termina ~7 mm acima).
    # Tarjas centralizadas, como na tela (o etiqueta é o modelo centralizado).
    largura_chips = _largura_papeis(rotulos, tamanho=9, tamanho_outros=7.5)
    _desenhar_papeis(c, rotulos, etiqueta_x + (etiqueta_largura - largura_chips) / 2.0,
                     etiqueta_y + 48 * mm, cor, altura=7 * mm, tamanho=9, tamanho_outros=7.5)

    # 34 mm centralizado: com ~45 módulos dá ~0,75 mm por módulo, o dobro da
    # folga de leitura que os 28 mm davam. Código e instrução vão centralizados
    # ABAIXO do QR (aprovado em 13/09/2026) — mesma régua do modelo clássico.
    lado_qr = 34 * mm
    qr = imagem_qr(url_verificacao(gerar_token(pessoa.id, evento.id, tipo="cracha")))
    centro_x = etiqueta_x + etiqueta_largura / 2.0
    c.drawImage(ImageReader(qr), centro_x - lado_qr / 2.0, etiqueta_y + 12.5 * mm,
                width=lado_qr, height=lado_qr, mask="auto")

    c.setFillColor(cor["texto"])
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(centro_x, etiqueta_y + 10 * mm, codigo_curto(pessoa.id, evento.id))
    c.setFillColor(cor["cinza"])
    c.setFont("Helvetica", 6.4)
    c.drawCentredString(centro_x, etiqueta_y + 4.5 * mm,
                        "Aponte a câmera para confirmar sua presença ou informe este código")


def _cracha_classico(c, pessoa, papeis_rotulos, evento, x, y, largura, altura, logo_caminho):
    """Modelo da tela: tarja verde no topo, faixa do evento, nome no corpo e QR no pé."""
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader

    cor = _paleta()
    nome = nome_completo(pessoa)
    rotulos = [rotulo.upper() for rotulo in papeis_rotulos]
    margem = 8 * mm

    # --- tarja de identificação institucional ---
    # A caixa da logo é QUADRADA e ocupa a altura da tarja: a marca do crachá é
    # vertical (517x765) e, numa caixa larga e baixa, saía com 4 mm de largura —
    # o texto de dentro dela não se lia.
    altura_topo = 20 * mm
    c.setFillColor(cor["verde"])
    c.rect(x, y + altura - altura_topo, largura, altura_topo, fill=True, stroke=False)

    caixa_logo = 16 * mm
    caixa_x = x + 6 * mm
    caixa_y = y + altura - altura_topo + (altura_topo - caixa_logo) / 2.0
    c.setFillColor(cor["branco"])
    c.roundRect(caixa_x, caixa_y, caixa_logo, caixa_logo, 2 * mm, fill=True, stroke=False)
    if not _desenhar_logo(c, logo_caminho, caixa_x + 1.5 * mm, caixa_y + 1.5 * mm,
                          caixa_logo - 3 * mm, caixa_logo - 3 * mm):
        c.setFillColor(cor["verde_ink"])
        c.setFont("Helvetica-Bold", 9)
        c.drawCentredString(caixa_x + caixa_logo / 2.0, caixa_y + 6.5 * mm, "IFMG")

    c.setFillColor(cor["branco"])
    c.setFont("Helvetica-Bold", 11)
    c.drawString(caixa_x + caixa_logo + 5 * mm, y + altura - altura_topo + 8.5 * mm,
                 "IFMG · Campus Ponte Nova")

    # --- faixa com a foto do evento (ou o gradiente oliva de reserva) ---
    # 24 mm (era 45, depois 34): a foto do evento cede o espaço do QR maior.
    altura_faixa = 24 * mm
    y_faixa = y + altura - altura_topo - altura_faixa
    imagem_faixa = imagem_para_faixa(evento, largura, altura_faixa)
    if imagem_faixa is not None:
        c.drawImage(ImageReader(imagem_faixa), x, y_faixa, width=largura, height=altura_faixa,
                    preserveAspectRatio=False, mask="auto")
    else:
        c.saveState()
        caminho = c.beginPath()
        caminho.rect(x, y_faixa, largura, altura_faixa)
        c.clipPath(caminho, stroke=0, fill=0)
        c.linearGradient(x, y_faixa, x, y_faixa + altura_faixa,
                         [cor["verde_escuro"], cor["verde"]])
        c.restoreState()

    # --- evento e período ---
    _desenhar_linhas(
        c, _quebrar_texto(evento.title, "Helvetica-Bold", 14, largura - 2 * margem, 2),
        "Helvetica-Bold", 14, x + margem, y + 96 * mm, 5.6 * mm, cor=cor["texto"],
    )
    subtitulo = " · ".join(p for p in [periodo_legivel(evento), (evento.local or "").strip()] if p)
    _desenhar_linhas(
        c, _quebrar_texto(subtitulo, "Helvetica", 9, largura - 2 * margem, 1),
        "Helvetica", 9, x + margem, y + 86 * mm, 4.6 * mm, cor=cor["cinza"],
    )
    c.setStrokeColor(cor["borda"])
    c.setLineWidth(0.6)
    c.line(x + margem, y + 80 * mm, x + largura - margem, y + 80 * mm)

    # --- nome em destaque + papel ---
    # Medidas ancoradas no PÉ do crachá (e não no topo da faixa): assim o nome
    # tem duas linhas inteiras garantidas e a tarja do papel fica sempre 2,5 mm
    # abaixo dele. Antes o corpo encolhia e o nome saía cortado na base.
    corpo_nome = 19 if len(nome) <= 24 else (17 if len(nome) <= 34 else 15)
    _desenhar_linhas(
        c, _quebrar_texto(nome, "Helvetica-Bold", corpo_nome, largura - 2 * margem, 2),
        "Helvetica-Bold", corpo_nome, x + margem, y + 72 * mm,
        corpo_nome * 0.5 * mm, cor=cor["texto"],
    )
    _desenhar_papeis(c, rotulos, x + margem, y + 50 * mm, cor, altura=8 * mm)

    # --- rodapé: QR + código curto ---
    # 34 mm centralizado, código e instrução abaixo — mesma régua do etiqueta.
    lado_qr = 34 * mm
    qr = imagem_qr(url_verificacao(gerar_token(pessoa.id, evento.id, tipo="cracha")))
    centro_x = x + largura / 2.0
    c.drawImage(ImageReader(qr), centro_x - lado_qr / 2.0, y + 12.5 * mm,
                width=lado_qr, height=lado_qr, mask="auto")

    c.setFillColor(cor["texto"])
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(centro_x, y + 10 * mm, codigo_curto(pessoa.id, evento.id))
    c.setFillColor(cor["cinza"])
    c.setFont("Helvetica", 6.4)
    c.drawCentredString(centro_x, y + 4.5 * mm,
                        "Aponte a câmera para confirmar sua presença ou informe este código")


def gerar_pdf_crachas_evento(evento, modelo=MODELO_PADRAO):
    """PDF com os crachás de todas as pessoas com papel no evento.

    Quatro por folha A4 (2 x 2 de 105 x 148,5 mm), no modelo escolhido, com as
    linhas de corte para a guilhotina. Devolve (nome_do_arquivo, ContentFile).
    """
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as canvas_pdf

    pessoas = pessoas_do_evento(evento)
    modelo = modelo_de_cracha(modelo)
    desenhar = _cracha_etiqueta if modelo == "etiqueta" else _cracha_classico

    buffer = io.BytesIO()
    largura_folha = A4_LARGURA_MM * mm
    altura_folha = A4_ALTURA_MM * mm
    largura_cartao = LARGURA_CARTAO_MM * mm
    altura_cartao = ALTURA_CARTAO_MM * mm

    c = canvas_pdf.Canvas(buffer, pagesize=(largura_folha, altura_folha))
    logo_caminho = arquivo_logo_cracha()

    for indice, (pessoa, _papel_principal) in enumerate(pessoas):
        posicao = indice % CARTOES_POR_FOLHA
        if posicao == 0:
            if indice > 0:
                c.showPage()
            _linhas_de_corte(c, largura_folha, altura_folha, largura_cartao, altura_cartao)

        coluna = posicao % COLUNAS_POR_FOLHA
        linha = posicao // COLUNAS_POR_FOLHA
        # A linha 0 é a de CIMA: o reportlab conta a partir da base da folha.
        cartao_x = coluna * largura_cartao
        cartao_y = altura_folha - (linha + 1) * altura_cartao
        # Um crachá por evento com TODOS os papéis da pessoa nele.
        rotulos = [ROTULOS_PAPEL.get(p, p) for p in papeis_no_evento(pessoa, evento)]
        desenhar(c, pessoa, rotulos, evento, cartao_x, cartao_y,
                 largura_cartao, altura_cartao, logo_caminho)

    c.save()
    buffer.seek(0)
    apelido = "evento"
    if evento.title:
        apelido = "".join(caractere if caractere.isalnum() else "-"
                          for caractere in evento.title.lower())[:40].strip("-")
    sufixo = "" if modelo == MODELO_PADRAO else f"-{modelo}"
    return f"crachas-{apelido}{sufixo}.pdf", ContentFile(buffer.read())


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
            "papeis_rotulos": ["Certificado"],
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
        # A verificação mostra os MESMOS papéis que o crachá: um crachá por
        # evento, com todos os papéis da pessoa nele.
        "papeis_rotulos": [ROTULOS_PAPEL.get(p, p) for p in papeis_no_evento(pessoa, evento)],
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
