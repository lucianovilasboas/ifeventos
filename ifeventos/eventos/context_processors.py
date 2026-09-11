"""Contexto disponível em todos os templates.

Três coisas que os templates precisam e que não pertencem a uma view:

  - `deployment`: SITE_URL e SOCKET_URL configuráveis por ambiente (antes havia
    hostname fixo escrito em 3 templates, o que quebra ao trocar de servidor);
  - `assets`: `ASSET_VERSION` para o `?v=` dos CSS/JS. O WhiteNoise serve os
    estáticos com `max-age=31536000, public`; com um `?v=` fixo o navegador
    continua usando o CSS antigo por até um ano depois do deploy — foi o que
    mostrou o formulário de atividade com o layout anterior (cabeçalho de seção
    empilhado, sem a caixa do evento) num celular que já tinha o site em cache;
  - `perfil_form`: formulário do modal "Editar Perfil". O modal vive no
    `dashboard_base.html`, que é usado por todas as telas internas, mas só as
    views de dashboard passavam o formulário no contexto. Nas outras telas o
    modal abria sem campo nenhum (apenas os ícones dos rótulos).
"""

import hashlib
from functools import lru_cache
from pathlib import Path

from django.conf import settings


def deployment(request):
    return {
        "SITE_URL": settings.SITE_URL,
        "SOCKET_URL": settings.SOCKET_URL,
    }


def _calcula_versao_dos_estaticos():
    """Hash do conteúdo de `static/`: muda sempre que um CSS/JS muda."""
    resumo = hashlib.sha1()
    raiz = Path(settings.BASE_DIR) / "static"
    for arquivo in sorted(raiz.rglob("*")):
        if arquivo.is_file():
            resumo.update(arquivo.name.encode("utf-8"))
            resumo.update(arquivo.read_bytes())
    return resumo.hexdigest()[:10]


@lru_cache(maxsize=1)
def _versao_em_cache():
    return _calcula_versao_dos_estaticos()


def assets(request):
    if settings.DEBUG:
        # Em desenvolvimento o processo pode ficar no ar enquanto o CSS muda,
        # então o valor é recalculado a cada request (são 6 arquivos pequenos).
        return {"ASSET_VERSION": _calcula_versao_dos_estaticos()}
    # Em produção o valor vale por processo: o contêiner é recriado a cada
    # deploy, e é exatamente isso que invalida o cache do navegador.
    return {"ASSET_VERSION": _versao_em_cache()}


def perfil_form(request):
    if not getattr(request.user, "is_authenticated", False):
        return {}

    # Import local: `organizador.forms` importa `eventos.forms`, e este módulo é
    # carregado durante o boot do Django.
    from organizador.forms import ParticipanteUpdateForm

    return {"perfil_form": ParticipanteUpdateForm(instance=request.user)}
