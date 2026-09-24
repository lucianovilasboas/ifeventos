"""Handler de logging que grava erros (ERROR+) na trilha de auditoria.

Complementa o log de console: além do traceback em stderr, deixa uma linha em
`RegistroAuditoria` (acao="erro"), visível no admin e consultável pela API/agente.
"""

import asyncio
import logging
import threading

_estado = threading.local()


def _em_contexto_async():
    """Há um event loop rodando nesta thread?

    O ORM do Django é síncrono: gravar a partir de um contexto async levanta
    SynchronousOnlyOperation. Nesses casos o erro continua no console, mas não
    vira linha de auditoria.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


class AuditoriaErroHandler(logging.Handler):
    """Grava registros ERROR+ como linhas de auditoria.

    - Só ERROR+ (WARNING/INFO passam).
    - Nunca levanta: qualquer falha é engolida (um erro no log não pode virar
      outro erro).
    - Guarda de reentrância: se a própria gravação gerar log, não recursa.
    """

    def emit(self, record):
        if record.levelno < logging.ERROR:
            return
        if getattr(_estado, "ativo", False):
            return
        if _em_contexto_async():
            return
        _estado.ativo = True
        try:
            self._gravar(record)
        except Exception:
            pass
        finally:
            _estado.ativo = False

    def _gravar(self, record):
        from . import auditoria
        from .models import RegistroAuditoria

        request = getattr(record, "request", None) or auditoria.request_atual()
        usuario = None
        if request is not None:
            usuario = getattr(request, "user", None)
            if usuario is not None and not getattr(usuario, "is_authenticated", False):
                usuario = None
        if usuario is None:
            usuario = auditoria.usuario_atual()

        traceback = ""
        if record.exc_info:
            traceback = logging.Formatter().formatException(record.exc_info)

        auditoria.registrar(
            acao=RegistroAuditoria.ACAO_ERRO,
            entidade="Sistema",
            resumo=record.getMessage() or record.levelname,
            detalhes={
                "logger": record.name,
                "nivel": record.levelname,
                "traceback": traceback[:4000],
            },
            usuario=usuario,
            request=request,
            status=getattr(record, "status_code", None),
        )
