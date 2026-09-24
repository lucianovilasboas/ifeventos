from rest_framework.permissions import SAFE_METHODS, BasePermission

from eventos.models import Evento


class IsOrganizador(BasePermission):
    """Permite apenas usuários marcados como organizador (flag is_organizador).

    Espelha o comportamento de permissão já usado pelo sistema: a separação
    organizador/participante é feita pelas flags booleanas no Participante.
    Leitura fica livre para qualquer usuário autenticado; escrita exige
    ser organizador.
    """

    def has_permission(self, request, view):
        user = request.user
        if not user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        return bool(getattr(user, "is_organizador", False))


class IsOrganizadorEstrito(BasePermission):
    """Exige a flag is_organizador em QUALQUER método, inclusive leitura.

    `IsOrganizador` libera métodos seguros para qualquer autenticado (é a regra
    dos catálogos públicos). Aqui não: estes dados trazem PII (cpf, telefone,
    endereço), então nem a listagem pode ser lida por participante comum.
    """

    def has_permission(self, request, view):
        user = request.user
        if not user.is_authenticated:
            return False
        return bool(getattr(user, "is_organizador", False))


class IsDonoOuOrganizador(BasePermission):
    """Permite edição apenas pelos donos do objeto ou por organizadores.

    Usado em recursos que pertencem a um usuário (inscrições, certificados):
    o próprio usuário pode ler/gerenciar os seus; organizadores podem
    gerenciar os de todos.
    """

    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        # Objetos possuem 'participante' FK (Inscricao, Certificado). Compare por pk.
        participante = getattr(obj, "participante", None)
        if participante is not None and participante.pk == user.pk:
            return True
        return bool(getattr(user, "is_organizador", False))


class IsDonoEvento(BasePermission):
    """Permite escrita apenas ao dono do evento ou a superuser.

    Espelha a lógica de `get_user_and_evento` do site:
    - superuser pode agir em qualquer evento;
    - um organizador comum só pode agir nos eventos que criou
      (Evento.organizador == user).
    """

    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        evento = obj if isinstance(obj, Evento) else getattr(obj, "evento", None)
        if evento is None:
            return False
        return bool(evento.organizador_id == user.pk)


class IsDonoInscricao(BasePermission):
    """Permite excluir/cancelar apenas a PRÓPRIA inscrição.

    A inscrição é self-service: cada usuário gerencia somente as suas.
    Mesmo um organizador não cancela inscrição de outro via API (o site
    também só permite o próprio cancelar).
    """

    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        participante = getattr(obj, "participante", None)
        return bool(participante is not None and participante.pk == user.pk)


class PodeLerPresencas(BasePermission):
    """Leitura de presenças: quem organiza o evento ou é da equipe de apoio.

    O escopo por evento é aplicado no `get_queryset` (a pessoa só enxerga as
    presenças dos eventos em que atua); aqui barra-se o participante comum, que
    não tem papel de operação (`API.md:142`). O `create` (check-in) segue com
    `IsAuthenticated`, porque a equipe de apoio e a própria pessoa (via
    `token_atividade`) também registram presença.
    """

    def has_permission(self, request, view):
        user = request.user
        if not user.is_authenticated:
            return False
        return bool(
            user.is_staff
            or user.is_superuser
            or getattr(user, "is_organizador", False)
            or getattr(user, "is_equipe", False)
        )

class IsSuperuser(BasePermission):
    """Exige superusuário (admin). Usada na trilha de auditoria."""

    def has_permission(self, request, view):
        user = request.user
        return bool(user.is_authenticated and user.is_superuser)
