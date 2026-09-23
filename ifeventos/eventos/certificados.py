"""Certificados: elegibilidade, contexto e renderização (modo fundo).

Este módulo concentra as regras que antes estavam soltas nas views e no
`utils.gerar_certificado`:

- **Elegibilidade**: quem tem direito ao certificado de uma atividade (a
  atividade emite certificado + a pessoa participou) e ao certificado do evento
  (percentual mínimo de presença nas atividades que emitem certificado).
- **Contexto**: as variáveis que o texto do certificado pode usar.
- **Renderização**: gera o PDF no modo "fundo" (imagem de pano de fundo +
  texto/assinaturas/QR desenhados com reportlab). O modo ".docx" entra na fase
  seguinte.

O QR aponta para a verificação pública já existente (`/c/<token>/`).
"""

from __future__ import annotations

import io
import logging

from django.db.models import Count
from django.utils import timezone
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from .models import Certificado, Inscricao, Participante, Presenca

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Elegibilidade
# ---------------------------------------------------------------------------


def _participou(participante_id, atividade_id) -> bool:
    """Participou = tem presença; fallback = inscrição confirmada."""
    return (
        Presenca.objects.filter(
            participante_id=participante_id, atividade_id=atividade_id
        ).exists()
        or Inscricao.objects.filter(
            participante_id=participante_id,
            atividade_id=atividade_id,
            confirmada=True,
        ).exists()
    )


def participantes_da_atividade(atividade):
    """Quem tem direito ao certificado DESTA atividade.

    A atividade precisa emitir certificado; a pessoa precisa ter presença (ou
    inscrição confirmada). Devolve um queryset de Participante.
    """
    if not getattr(atividade, "emite_certificado", False):
        return Participante.objects.none()

    ids = set(
        Presenca.objects.filter(atividade=atividade).values_list(
            "participante_id", flat=True
        )
    ) | set(
        Inscricao.objects.filter(
            atividade=atividade, confirmada=True
        ).values_list("participante_id", flat=True)
    )
    return Participante.objects.filter(id__in=ids)


def participantes_do_evento(evento, config=None):
    """Quem tem direito ao certificado DO EVENTO (percentual de presença).

    O denominador são as atividades que emitem certificado. A pessoa precisa
    comparecer a, no mínimo, `percentual`% delas. Devolve um queryset.
    """
    percentual = (
        config.percentual_efetivo
        if config is not None
        else evento.percentual_certificado
    )
    atividades_ids = list(
        evento.atividades.filter(emite_certificado=True).values_list("id", flat=True)
    )
    total = len(atividades_ids)
    if total == 0:
        return Participante.objects.none()

    pres = Presenca.objects.filter(atividade_id__in=atividades_ids).values_list(
        "participante_id", "atividade_id"
    )
    insc = Inscricao.objects.filter(
        atividade_id__in=atividades_ids, confirmada=True
    ).values_list("participante_id", "atividade_id")

    por_pessoa: dict[int, set[int]] = {}
    for participante_id, atividade_id in list(pres) + list(insc):
        por_pessoa.setdefault(participante_id, set()).add(atividade_id)

    minimo = total * (percentual or 0) / 100.0
    ids = [pid for pid, feitas in por_pessoa.items() if len(feitas) >= minimo]
    return Participante.objects.filter(id__in=ids)


def carga_horaria_efetiva(atividade, evento, config=None):
    """Carga horária a imprimir: atividade → config → evento."""
    if atividade is not None and atividade.carga_horaria:
        return atividade.carga_horaria
    if config is not None and config.carga_horaria_padrao:
        return config.carga_horaria_padrao
    if evento is not None and evento.carga_horaria:
        return evento.carga_horaria
    return None


# ---------------------------------------------------------------------------
# Contexto (variáveis do texto)
# ---------------------------------------------------------------------------


def contexto_certificado(participante, *, atividade=None, evento=None, config=None):
    """Variáveis disponíveis no corpo/template do certificado."""
    if evento is None and atividade is not None:
        evento = atividade.evento
    if config is None and evento is not None:
        config = getattr(evento, "certificado_config", None)

    from .crachas import gerar_token, url_verificacao

    qr_url = url_verificacao(
        gerar_token(
            participante.id,
            evento_id=getattr(evento, "id", None),
            tipo="certificado",
            atividade_id=getattr(atividade, "id", None),
        )
    )
    horas = carga_horaria_efetiva(atividade, evento, config)
    return {
        "nome": participante.get_full_name(),
        "cpf": participante.cpf,
        "atividade": atividade.titulo if atividade is not None else "",
        "evento": evento.title if evento is not None else "",
        "local": (atividade.local if atividade is not None and atividade.local else (evento.local if evento else "")),
        "carga_horaria": f"{horas}h" if horas else "",
        "data": timezone.localtime().strftime("%d/%m/%Y"),
        "qr_url": qr_url,
        "tipo": "atividade" if atividade is not None else "evento",
    }


def substituir_variaveis(texto, contexto) -> str:
    """Troca `{{chave}}` pelo valor do contexto (chaves desconhecidas ficam)."""
    if not texto:
        return ""
    saida = texto
    for chave, valor in contexto.items():
        saida = saida.replace("{{" + chave + "}}", str(valor or ""))
    return saida


# ---------------------------------------------------------------------------
# Renderização (modo fundo)
# ---------------------------------------------------------------------------

_AZUL = HexColor("#1F4E79")
_CINZA = HexColor("#333333")
_LINHA = HexColor("#1F4E79")


def _quebrar(texto, fonte, tamanho, largura_max, c):
    """Quebra o texto em linhas que caibam em `largura_max`."""
    linhas = []
    for paragrafo in (texto or "").splitlines() or [""]:
        palavras = paragrafo.split()
        if not palavras:
            linhas.append("")
            continue
        atual = palavras[0]
        for palavra in palavras[1:]:
            teste = atual + " " + palavra
            if pdfmetrics.stringWidth(teste, fonte, tamanho) <= largura_max:
                atual = teste
            else:
                linhas.append(atual)
                atual = palavra
        linhas.append(atual)
    return linhas


def _desenhar_fundo(c, config, width, height):
    """Pinta o fundo: imagem enviada ou o padrão interno."""
    fundo = getattr(config, "layout_fundo", None)
    if fundo:
        try:
            c.drawImage(ImageReader(fundo.path), 0, 0, width=width, height=height,
                        preserveAspectRatio=False, mask="auto")
            return
        except Exception:
            pass  # fundo inválido: cai no padrão
    # Padrão interno (sóbrio, sem depender de arquivo).
    c.setFillColor(HexColor("#FFFFFF"))
    c.rect(0, 0, width, height, fill=True, stroke=False)
    c.setStrokeColor(_LINHA)
    c.setLineWidth(4)
    c.rect(24, 24, width - 48, height - 48)


def _desenhar_qr(c, contexto, width):
    import qrcode

    qr = qrcode.make(contexto.get("qr_url") or "")
    buffer = io.BytesIO()
    qr.save(buffer, format="PNG")
    buffer.seek(0)
    c.drawImage(ImageReader(buffer), width - 130, 40, width=90, height=90, mask="auto")


def _desenhar_assinaturas(c, assinaturas, width):
    assinaturas = list(assinaturas)
    if not assinaturas:
        return
    n = len(assinaturas)
    faixa = width / (n + 1)
    y_linha = 110
    for i, a in enumerate(assinaturas):
        x = faixa * (i + 1)
        if getattr(a, "imagem", None):
            try:
                c.drawImage(
                    ImageReader(a.imagem.path), x - 80, y_linha + 6,
                    width=160, height=44, mask="auto", preserveAspectRatio=True,
                )
            except Exception:
                pass
        c.setStrokeColor(_CINZA)
        c.setLineWidth(1)
        c.line(x - 110, y_linha, x + 110, y_linha)
        c.setFont("Helvetica-Bold", 11)
        c.setFillColor(_CINZA)
        c.drawCentredString(x, y_linha - 15, a.nome)
        if a.cargo:
            c.setFont("Helvetica", 9)
            c.drawCentredString(x, y_linha - 27, a.cargo)


def render_pdf(contexto, config) -> bytes:
    """Gera o PDF do certificado no modo 'fundo'. Devolve os bytes."""
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=landscape(A4))
    width, height = landscape(A4)

    _desenhar_fundo(c, config, width, height)

    # Título
    c.setFont("Helvetica-Bold", 30)
    c.setFillColor(_AZUL)
    c.drawCentredString(width / 2, height - 95, (config.titulo or "CERTIFICADO").upper())

    # Corpo (com variáveis substituídas), centralizado e quebrado
    corpo = substituir_variaveis(config.corpo or "", contexto)
    if not corpo.strip():
        corpo = (
            "Certificamos que {{nome}} participou de {{atividade}}{{evento}}.\n"
            "Carga horária: {{carga_horaria}}."
        )
        corpo = substituir_variaveis(corpo, contexto)
    linhas = _quebrar(corpo, "Helvetica", 15, width - 200, c)
    y = height - 150
    c.setFillColor(_CINZA)
    c.setFont("Helvetica", 15)
    for linha in linhas[:10]:
        c.drawCentredString(width / 2, y, linha)
        y -= 22

    # Rodapé
    if config.rodape:
        c.setFont("Helvetica-Oblique", 10)
        c.drawCentredString(width / 2, 70, config.rodape)

    _desenhar_assinaturas(c, config.assinaturas.all() if config.pk else [], width)
    _desenhar_qr(c, contexto, width)

    c.showPage()
    c.save()
    return buffer.getvalue()


def gerar_certificado(participante, *, atividade=None, evento=None, config=None):
    """Gera o PDF de um certificado e devolve um ContentFile pronto para salvar."""
    from django.core.files.base import ContentFile

    if evento is None and atividade is not None:
        evento = atividade.evento
    if config is None and evento is not None:
        config = getattr(evento, "certificado_config", None)

    contexto = contexto_certificado(
        participante, atividade=atividade, evento=evento, config=config
    )
    if config is not None:
        dados = render_pdf(contexto, config)
    else:
        dados = _render_padrao(contexto, atividade, evento)

    nome = f"certificado_{participante.id}.pdf"
    return ContentFile(dados, nome)


def _render_padrao(contexto, atividade, evento):
    """Fallback sem configuração: usa a config "virtual" só com o padrão."""
    from .models import ConfiguracaoCertificado

    virtual = ConfiguracaoCertificado(
        titulo="CERTIFICADO DE PARTICIPAÇÃO",
        corpo=(
            "Certificamos que {{nome}} participou "
            + ("da atividade {{atividade}}" if atividade is not None else "do evento {{evento}}")
            + ".\nCarga horária: {{carga_horaria}}."
        ),
    )
    return render_pdf(contexto, virtual)


# ---------------------------------------------------------------------------
# Emissão e entrega
# ---------------------------------------------------------------------------


def _enviar_email(certificado, config, evento):
    """Envia o certificado por e-mail (best-effort) quando configurado."""
    if config is None or not config.enviar_email:
        return
    participante = certificado.participante
    if not participante.email or not certificado.pdf:
        return

    from django.conf import settings
    from django.template.loader import render_to_string

    from . import emails

    try:
        certificado.pdf.open("rb")
        conteudo = certificado.pdf.read()
    except Exception:
        logger.exception("certificados: falha ao ler o PDF de %r", participante.email)
        return
    finally:
        try:
            certificado.pdf.close()
        except Exception:
            pass

    escopo = (
        f"atividade {certificado.atividade.titulo}"
        if certificado.atividade_id
        else f"evento {evento.title if evento else ''}"
    )
    corpo = render_to_string(
        "emails/certificado.txt",
        {
            "nome": participante.get_full_name(),
            "escopo": escopo,
            "site_url": emails.site_url(),
            "site_nome": getattr(settings, "SITE_NAME", "Nossos Eventos"),
        },
    )
    emails.enviar_com_anexo(
        f"Seu certificado — {escopo}",
        [participante.email],
        corpo,
        [("certificado.pdf", conteudo, "application/pdf")],
    )


def emitir(participante, *, atividade=None, evento=None):
    """Gera (uma única vez) o certificado de uma atividade ou do evento.

    Idempotente: se já existir, devolve o existente sem gerar de novo nem
    reenviar e-mail. Devolve `(certificado, criado)`.
    """
    if evento is None and atividade is not None:
        evento = atividade.evento
    config = getattr(evento, "certificado_config", None) if evento is not None else None

    if atividade is not None:
        tipo = Certificado.TIPO_ATIVIDADE
        evento_gravado = None
        existente = Certificado.objects.filter(
            participante=participante, atividade=atividade, evento__isnull=True
        ).first()
    else:
        tipo = Certificado.TIPO_EVENTO
        evento_gravado = evento
        existente = Certificado.objects.filter(
            participante=participante, evento=evento, atividade__isnull=True
        ).first()
    if existente is not None:
        return existente, False

    arquivo = gerar_certificado(
        participante, atividade=atividade, evento=evento, config=config
    )
    certificado = Certificado.objects.create(
        participante=participante,
        atividade=atividade,
        evento=evento_gravado,
        tipo=tipo,
        carga_horaria=carga_horaria_efetiva(atividade, evento, config),
        config=config,
        pdf=arquivo,
    )
    _enviar_email(certificado, config, evento)
    return certificado, True
