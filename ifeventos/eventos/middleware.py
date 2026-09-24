"""Middleware de contexto da auditoria.

Guarda o request atual num thread-local, para que o helper `registrar()` e os
`signals` saibam o usuário/IP/path sem precisar repassá-los em cada chamada.
"""

from . import auditoria


class AuditoriaContextoMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        auditoria.set_contexto(request)
        try:
            response = self.get_response(request)
        finally:
            auditoria.limpar_contexto()
        return response
