"""Enriquecimento do perfil a partir do login social (Google).

O allauth guarda o payload do provedor em `SocialAccount.extra_data` (nome,
`picture`, `email_verified`...). Aproveitamos o que ainda falta no perfil:

- **nome** (`first_name`/`last_name`) quando estiver vazio;
- **avatar**: baixa a `picture` uma única vez e guarda em `Participante.foto`;
  se o download falhar, guarda a URL em `foto_social_url` (fallback).

Nunca levanta exceção — o login não pode quebrar por causa disto.
"""

from __future__ import annotations

import logging
import re
from io import BytesIO

import requests
from django.core.files.base import ContentFile

logger = logging.getLogger(__name__)

TIMEOUT = 5
TAMANHO_MAX = 2 * 1024 * 1024  # 2 MB
LADO_AVATAR = 256


def _url_maior(url: str | None) -> str | None:
    """Pede ao Google uma imagem maior (o padrão vem em 96px)."""
    if not url:
        return url
    return re.sub(r"=s\d+(-c)?$", f"=s{LADO_AVATAR}-c", url)


def _quadrado(conteudo: bytes) -> bytes | None:
    """Recorta no centro e redimensiona para `LADO_AVATAR` (JPEG)."""
    from PIL import Image

    imagem = Image.open(BytesIO(conteudo)).convert("RGB")
    largura, altura = imagem.size
    lado = min(largura, altura)
    esquerda = (largura - lado) // 2
    topo = (altura - lado) // 2
    imagem = imagem.crop((esquerda, topo, esquerda + lado, topo + lado))
    imagem = imagem.resize((LADO_AVATAR, LADO_AVATAR))
    buffer = BytesIO()
    imagem.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


def _baixar_avatar(url: str) -> bytes | None:
    """Bytes de uma imagem quadrada, ou None se não der para baixar/validar."""
    resposta = requests.get(url, timeout=TIMEOUT, stream=True)
    if resposta.status_code != 200:
        return None
    tipo = (resposta.headers.get("Content-Type") or "").lower()
    if not tipo.startswith("image/"):
        return None
    conteudo = resposta.raw.read(TAMANHO_MAX + 1, decode_content=True)
    if not conteudo or len(conteudo) > TAMANHO_MAX:
        return None
    return _quadrado(conteudo)


def _preencher_nome(user, dados: dict) -> bool:
    primeiro = (user.first_name or "").strip()
    sobrenome = (user.last_name or "").strip()
    if primeiro and sobrenome:
        return False
    dado_primeiro = (dados.get("given_name") or "").strip()
    dado_sobrenome = (dados.get("family_name") or "").strip()
    if not dado_primeiro and not dado_sobrenome:
        partes = (dados.get("name") or "").strip().split(" ", 1)
        dado_primeiro = partes[0] if partes else ""
        dado_sobrenome = partes[1] if len(partes) > 1 else ""
    campos = []
    if not primeiro and dado_primeiro:
        user.first_name = dado_primeiro
        campos.append("first_name")
    if not sobrenome and dado_sobrenome:
        user.last_name = dado_sobrenome
        campos.append("last_name")
    if not campos:
        return False
    user.save(update_fields=campos)
    return True


def _aplicar_avatar(user, dados: dict) -> bool:
    if user.foto:
        return False
    url = _url_maior(dados.get("picture"))
    if not url:
        return False
    conteudo = _baixar_avatar(url)
    if conteudo:
        user.foto.save(f"google_{user.pk}.jpg", ContentFile(conteudo), save=True)
        return True
    # Fallback: sem arquivo, guarda a URL para o avatar aparecer de qualquer forma.
    if user.foto_social_url != url:
        user.foto_social_url = url
        user.save(update_fields=["foto_social_url"])
        return True
    return False


def enriquecer_do_google(user, sociallogin) -> bool:
    """Completa nome e avatar a partir do `extra_data` do Google. Não levanta."""
    try:
        if user is None or not getattr(user, "pk", None):
            return False
        conta = getattr(sociallogin, "account", None)
        dados = getattr(conta, "extra_data", None) or {}
        if not dados:
            return False
        mudou = _preencher_nome(user, dados)
        return _aplicar_avatar(user, dados) or mudou
    except Exception:
        logger.exception(
            "social: falha ao enriquecer o perfil de %r",
            getattr(user, "email", None),
        )
        return False
