"""Backend de e-mail que envia FORA da requisição.

O backend SMTP padrão segura a requisição durante o handshake TLS — no Gmail,
1 a 3 segundos por mensagem. Como todo e-mail do sistema é acessório (avisos da
chamada, confirmação de cadastro, reset de senha), o envio não deve ditar o
tempo de resposta de nenhuma ação.

Este backend herda do SMTP e desvia o `send_messages` para um pool de threads
limitado: a requisição retorna na hora e a mensagem sai em segundo plano. Falha
de SMTP vai só para o log — o mesmo contrato *best-effort* de `eventos/emails.py`.

O runner de testes do Django força `EMAIL_BACKEND=locmem`, então este backend
nunca roda nos testes: `mail.outbox` continua funcionando normalmente.
"""

import logging
from concurrent.futures import ThreadPoolExecutor

from django.core.mail.backends.smtp import EmailBackend
from django.db import connections

logger = logging.getLogger(__name__)

# Limitado de propósito: um pico de cadastros não pode abrir uma thread por
# mensagem. Quatro envios simultâneos por worker cobrem com folga o volume.
MAX_WORKERS = 4

# Um pool por processo. O gunicorn (sem `--preload`) importa o módulo em cada
# worker, então cada um tem o seu.
_pool = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="email")


def _enviar(kwargs, mensagens):
    """Envia as mensagens num backend SMTP próprio desta thread.

    Um backend novo por tarefa evita compartilhar a conexão SMTP entre threads
    (que não é thread-safe). O `connections.close_all` devolve a conexão de
    banco da thread ao pool — ela fica viva no executor e não pode segurar uma
    conexão antiga.
    """
    try:
        backend = EmailBackend(**kwargs)
        backend.send_messages(mensagens)
        backend.close()
    except Exception:
        logger.exception("Falha no envio assíncrono de e-mail")
    finally:
        connections.close_all()


class AsyncEmailBackend(EmailBackend):
    """SMTP que devolve o controle na hora e envia em segundo plano."""

    def __init__(self, **kwargs):
        # Guarda a configuração para montar o backend da thread de envio;
        # `super()` valida os argumentos como no SMTP normal.
        self._kwargs = kwargs
        super().__init__(**kwargs)

    def send_messages(self, email_messages):
        mensagens = list(email_messages)
        if not mensagens:
            return 0
        _pool.submit(_enviar, self._kwargs, mensagens)
        return len(mensagens)
