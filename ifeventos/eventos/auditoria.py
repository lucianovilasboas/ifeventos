"""Serviços da trilha de auditoria.

Três responsabilidades:
  * **Contexto da requisição** (thread-local): guarda o request atual (usuário,
    IP, path) para que `signals` e o helper `registrar()` saibam o autor sem
    precisar passá-lo em cada chamada.
  * **Máscaras**: CPF/e-mail nunca saem crus para a API/agente.
  * **`registrar()`**: grava uma linha em `RegistroAuditoria`. Nunca levanta
    exceção — auditoria é acessória e não pode derrubar a operação.
"""

import logging
import threading
import uuid

logger = logging.getLogger(__name__)

_local = threading.local()


# ---------------------------------------------------------------------------
# Contexto da requisição
# ---------------------------------------------------------------------------
def set_contexto(request):
    """Guarda o request atual (chamado pelo middleware)."""
    _local.request = request
    _local.request_id = uuid.uuid4()


def limpar_contexto():
    _local.request = None
    _local.request_id = None


def request_atual():
    return getattr(_local, "request", None)


def request_id_atual():
    return getattr(_local, "request_id", None)


def usuario_atual():
    """Usuário autenticado da requisição atual (ou None)."""
    request = request_atual()
    usuario = getattr(request, "user", None) if request else None
    if usuario is not None and getattr(usuario, "is_authenticated", False):
        return usuario
    return None


def _ip(request):
    if not request:
        return None
    encaminhado = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if encaminhado:
        return encaminhado.split(",")[0].strip()[:45] or None
    return request.META.get("REMOTE_ADDR") or None


def _origem(request):
    from .models import RegistroAuditoria

    if not request:
        return RegistroAuditoria.ORIGEM_SISTEMA
    path = getattr(request, "path", "") or ""
    if path.startswith("/admin"):
        return RegistroAuditoria.ORIGEM_ADMIN
    if path.startswith("/api"):
        return RegistroAuditoria.ORIGEM_API
    return RegistroAuditoria.ORIGEM_WEB


# ---------------------------------------------------------------------------
# Máscaras
# ---------------------------------------------------------------------------
def mascarar_cpf(valor):
    digitos = "".join(c for c in str(valor or "") if c.isdigit())
    if len(digitos) != 11:
        return "***" if valor else ""
    return f"***.***.{digitos[6:9]}-**"


def mascarar_email(valor):
    valor = str(valor or "").strip()
    if "@" not in valor:
        return "***" if valor else ""
    local, _, dominio = valor.partition("@")
    return f"{local[0]}***@{dominio}" if local else f"***@{dominio}"


_CHAVES_SENSIVEIS = ("cpf", "password", "senha", "token")


def _sanitizar(valor):
    """Mascara valores sensíveis dentro de `detalhes` (recursivo)."""
    if isinstance(valor, dict):
        saida = {}
        for chave, item in valor.items():
            baixa = str(chave).lower()
            if "cpf" in baixa:
                saida[chave] = mascarar_cpf(item)
            elif any(s in baixa for s in _CHAVES_SENSIVEIS):
                saida[chave] = "***"
            elif "email" in baixa or "e-mail" in baixa:
                saida[chave] = mascarar_email(item)
            else:
                saida[chave] = _sanitizar(item)
        return saida
    if isinstance(valor, (list, tuple)):
        return [_sanitizar(item) for item in valor]
    return valor


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------
def rotulo(obj):
    """Representação curta do objeto (sobrevive à exclusão, é só texto)."""
    try:
        return str(obj)[:255]
    except Exception:
        return ""


def _resolver_evento(objeto, evento):
    if evento is not None:
        return evento
    if objeto is None:
        return None
    if objeto.__class__.__name__ == "Evento":
        return objeto
    return getattr(objeto, "evento", None)


def registrar(
    *,
    acao,
    objeto=None,
    entidade="",
    objeto_id="",
    objeto_repr="",
    evento=None,
    resumo="",
    detalhes=None,
    usuario=None,
    request=None,
    origem=None,
    status=None,
):
    """Grava uma linha na trilha. Nunca levanta exceção."""
    from .models import RegistroAuditoria

    try:
        request = request or request_atual()
        if usuario is None:
            usuario = usuario_atual()
        if usuario is not None and not hasattr(usuario, "pk"):
            usuario = None

        if objeto is not None:
            if not entidade:
                entidade = objeto.__class__.__name__
            if not objeto_id and getattr(objeto, "pk", None) is not None:
                objeto_id = str(objeto.pk)
            if not objeto_repr:
                objeto_repr = rotulo(objeto)
        evento = _resolver_evento(objeto, evento)

        RegistroAuditoria.objects.create(
            request_id=request_id_atual(),
            usuario=usuario,
            usuario_nome=(usuario.get_full_name() or "") if usuario else "",
            usuario_email=getattr(usuario, "email", "") if usuario else "",
            origem=origem or _origem(request),
            acao=acao,
            entidade=entidade or "",
            objeto_id=str(objeto_id or ""),
            objeto_repr=(objeto_repr or "")[:255],
            evento=evento,
            resumo=(resumo or "")[:255],
            detalhes=_sanitizar(detalhes) if detalhes else None,
            ip=_ip(request),
            path=(getattr(request, "path", "") or "")[:255] if request else "",
            metodo=(getattr(request, "method", "") or "")[:10] if request else "",
            status=status,
        )
    except Exception:  # pragma: no cover - auditoria nunca quebra o fluxo
        logger.exception("auditoria: falha ao registrar a ação %s", acao)
