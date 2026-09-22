"""Decorators de escopo do app organizador.

O `@login_required` do Django só garante que há um usuário logado; as rotas de
gestão precisam, além disso, do papel de organizador. Usar um decorator deixa a
recusa explícita (403) — o contrato de 2.2.2 — em vez de um redirect silencioso.
"""

from functools import wraps

from django.core.exceptions import PermissionDenied


def organizador_required(view):
    """Devolve 403 para quem não é organizador/superuser.

    Deve vir **abaixo** de `@login_required`: o anônimo continua sendo mandado
    ao login (302); o usuário logado sem a flag recebe 403.
    """

    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        user = request.user
        if not (user.is_superuser or getattr(user, "is_organizador", False)):
            raise PermissionDenied("Área restrita a organizadores.")
        return view(request, *args, **kwargs)

    return _wrapped
