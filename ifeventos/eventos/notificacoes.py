"""Notificações persistentes do usuário (sino do topo).

São avisos que sobrevivem à requisição — ao contrário das `messages` do Django.
O worker cria a notificação ao concluir uma tarefa longa (hoje, o envio de
comunicados); o sino busca as últimas por AJAX em qualquer página do app.
"""

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .models import Notificacao
from .tempo import local_legivel


def _como_dict(notificacao):
    return {
        "id": notificacao.pk,
        "tipo": notificacao.tipo,
        "titulo": notificacao.titulo,
        "mensagem": notificacao.mensagem,
        "url": notificacao.url,
        "lida": notificacao.lida,
        "criada_em": local_legivel(notificacao.criada_em, "%d/%m %H:%M"),
    }


@login_required(login_url="/accounts/login/")
def listar(request):
    """Últimas notificações do usuário + contagem de não lidas."""
    queryset = Notificacao.objects.filter(usuario=request.user)
    itens = list(queryset.order_by("-criada_em", "-id")[:10])
    return JsonResponse({
        "nao_lidas": queryset.filter(lida=False).count(),
        "itens": [_como_dict(item) for item in itens],
    })


@login_required(login_url="/accounts/login/")
@require_POST
def marcar_lida(request, notificacao_id):
    """Marca uma notificação do próprio usuário como lida."""
    atualizadas = Notificacao.objects.filter(
        pk=notificacao_id, usuario=request.user
    ).update(lida=True)
    if not atualizadas:
        return JsonResponse({"erro": "Notificação não encontrada."}, status=404)
    return JsonResponse({
        "ok": True,
        "nao_lidas": Notificacao.objects.filter(
            usuario=request.user, lida=False
        ).count(),
    })


@login_required(login_url="/accounts/login/")
@require_POST
def marcar_todas(request):
    """Marca todas as notificações do usuário como lidas."""
    Notificacao.objects.filter(usuario=request.user, lida=False).update(lida=True)
    return JsonResponse({"ok": True, "nao_lidas": 0})
