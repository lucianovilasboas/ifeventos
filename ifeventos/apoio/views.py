"""Painel da equipe de apoio: check-in das atividades dos eventos vinculados.

Quem é da equipe (`is_equipe` + `Evento.equipe`) vê aqui somente os eventos em
que foi adicionada e as atividades publicadas deles, com acesso ao check-in
(câmera/código manual). Não há poder de organização nenhum nesta área.
"""

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, render

from eventos.models import Evento

LOGIN_URL = "/accounts/login/"


def _evento_do_apoio(request, evento_id):
    if not getattr(request.user, "is_equipe", False):
        raise PermissionDenied("Esta área é só para a equipe de apoio.")
    evento = get_object_or_404(Evento, id=evento_id)
    if not evento.equipe.filter(id=request.user.id).exists():
        raise PermissionDenied("Você não é da equipe deste evento.")
    return evento


@login_required(login_url=LOGIN_URL)
def dashboard(request):
    """Eventos em que a pessoa é da equipe de apoio."""
    eventos = request.user.eventos_equipe.select_related("organizador").order_by(
        "data_inicio", "id"
    )
    return render(request, "apoio/dashboard.html", {"eventos": eventos})


@login_required(login_url=LOGIN_URL)
def evento(request, evento_id):
    """Atividades publicadas do evento, com o botão de check-in."""
    evento = _evento_do_apoio(request, evento_id)
    atividades = (
        evento.atividades.filter(publicada=True)
        .select_related("tipo")
        .prefetch_related("palestrantes")
        .order_by("data_hora_inicio", "id")
    )
    return render(
        request,
        "apoio/evento.html",
        {"evento": evento, "atividades": atividades},
    )