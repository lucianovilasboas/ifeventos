"""Contexto de implantação disponível em todos os templates.

Expõe SITE_URL e SOCKET_URL para que os templates não precisem de hostname
fixo. Antes havia "http://ifeventos.duckdns.org:8501" escrito em 3 templates,
o que quebra ao mudar de servidor ou domínio.
"""

from django.conf import settings


def deployment(request):
    return {
        "SITE_URL": settings.SITE_URL,
        "SOCKET_URL": settings.SOCKET_URL,
    }
