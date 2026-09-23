"""E-mails transacionais da chamada de proposições.

Fica separado de `services.py` (IA/socket) de propósito: aqui é só o envio —
com as mesmas garantias de lá, nunca levanta exceção e nunca segura a
requisição, porque enviar e-mail é acessório: a proposta/decisão já está
gravada e a tela mostra o mesmo estado.

O envio só acontece com `PROPOSTAS_NOTIFICAR_EMAIL` ligado (padrão DESLIGADO):
assim o deploy não começa a mandar e-mail sem o SMTP estar validado. Os corpos
são texto puro, em `templates/emails/`.
"""

import logging

from django.conf import settings
from django.core.mail import EmailMessage, send_mail
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def notificar_email_ligado():
    """O envio está habilitado neste ambiente?"""
    return bool(getattr(settings, "PROPOSTAS_NOTIFICAR_EMAIL", False))


def site_url(caminho=""):
    """URL absoluta para os links do e-mail (usa `SITE_URL`, configurável)."""
    base = (getattr(settings, "SITE_URL", "") or "").rstrip("/")
    return f"{base}{caminho}" if base else caminho


def enviar(assunto, destinatarios, template, contexto):
    """Renderiza o template de texto e envia. Devolve True/False; nunca levanta."""
    destinos = [email for email in (destinatarios or []) if email]
    if not destinos:
        return False
    try:
        corpo = render_to_string(template, contexto)
        send_mail(
            assunto,
            corpo,
            getattr(settings, "DEFAULT_FROM_EMAIL", None),
            destinos,
            fail_silently=False,
        )
        return True
    except Exception:
        logger.exception("Falha ao enviar o e-mail %r para %s", assunto, destinos)
        return False


def enviar_com_anexo(assunto, destinatarios, corpo, anexos=()):
    """Envia e-mail com anexos `(nome, bytes, mimetype)`. Nunca levanta."""
    destinos = [email for email in (destinatarios or []) if email]
    if not destinos:
        return False
    try:
        mensagem = EmailMessage(
            assunto,
            corpo,
            getattr(settings, "DEFAULT_FROM_EMAIL", None),
            destinos,
        )
        for nome, conteudo, tipo in anexos:
            mensagem.attach(nome, conteudo, tipo)
        mensagem.send(fail_silently=False)
        return True
    except Exception:
        logger.exception(
            "Falha ao enviar o e-mail com anexo %r para %s", assunto, destinos
        )
        return False
