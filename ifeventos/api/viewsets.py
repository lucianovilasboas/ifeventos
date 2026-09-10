from rest_framework import filters, viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated

from eventos.models import Atividade, Certificado, Evento, Inscricao, TipoAtividade

from .permissions import IsDonoEvento, IsDonoInscricao, IsDonoOuOrganizador, IsOrganizador
from .serializers import (
    AtividadeSerializer,
    AtividadeWriteSerializer,
    CertificadoSerializer,
    EventoSerializer,
    EventoWriteSerializer,
    InscricaoCreateSerializer,
    InscricaoSerializer,
    TipoAtividadeSerializer,
    TipoAtividadeWriteSerializer,
)


class EventoViewSet(viewsets.ModelViewSet):
    """Catálogo público de eventos (leitura) + CRUD para organizadores."""

    # Leitura: qualquer um. Escrita: só is_organizador (D1).
    queryset = Evento.objects.all().order_by("-data_inicio")
    search_fields = ["title", "description", "local"]
    permission_classes = [AllowAny, IsOrganizador]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return EventoWriteSerializer
        return EventoSerializer

    def perform_create(self, serializer):
        serializer.save(organizador=self.request.user)

    def get_permissions(self):
        # Leitura: qualquer um. Escrita: exigir organizador e (no objeto) dono/superuser.
        if self.action in ("list", "retrieve"):
            return [AllowAny()]
        if self.action == "create":
            return [IsOrganizador()]
        return [IsOrganizador(), IsDonoEvento()]

    def get_object(self):
        obj = super().get_object()
        # Edição/exclusão exige dono do evento ou superuser.
        if self.action in ("update", "partial_update", "destroy"):
            self.check_object_permissions(self.request, obj)
        return obj


class AtividadeViewSet(viewsets.ModelViewSet):
    """Catálogo público de atividades + CRUD para organizadores."""

    queryset = Atividade.objects.select_related("tipo", "evento").prefetch_related("palestrantes").order_by("data_hora_inicio")
    search_fields = ["titulo", "descricao"]
    permission_classes = [AllowAny, IsOrganizador]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return AtividadeWriteSerializer
        return AtividadeSerializer

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [AllowAny()]
        if self.action == "create":
            return [IsOrganizador()]
        return [IsOrganizador(), IsDonoEvento()]

    def get_object(self):
        obj = super().get_object()
        if self.action in ("update", "partial_update", "destroy"):
            self.check_object_permissions(self.request, obj)
        return obj


class TipoAtividadeViewSet(viewsets.ModelViewSet):
    """Tipos de atividade: leitura pública, escrita para organizadores."""

    queryset = TipoAtividade.objects.all().order_by("nome")
    permission_classes = [AllowAny, IsOrganizador]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return TipoAtividadeWriteSerializer
        return TipoAtividadeSerializer

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [AllowAny()]
        return [IsOrganizador()]


class MinhasInscricoesViewSet(viewsets.ModelViewSet):
    """Inscrições do usuário autenticado.

    - GET: lista as próprias (organizador vê todas).
    - POST: self-inscrição em uma atividade ({'atividade': id}), com as
      mesmas regras de negócio do site (vagas, duplicidade, conflito).
    - DELETE: cancela a própria inscrição.
    """

    serializer_class = InscricaoSerializer
    permission_classes = [IsAuthenticated, IsDonoOuOrganizador]

    def get_permissions(self):
        # DELETE (cancelar) é somente a própria inscrição; demais exigem
        # autenticação + permissão de objeto (IsDonoOuOrganizador na leitura).
        if self.action == "destroy":
            return [IsAuthenticated(), IsDonoInscricao()]
        return [IsAuthenticated(), IsDonoOuOrganizador()]

    def get_serializer_class(self):
        if self.action == "create":
            return InscricaoCreateSerializer
        return InscricaoSerializer

    def get_queryset(self):
        qs = Inscricao.objects.select_related("participante", "atividade__evento", "atividade__tipo").prefetch_related("atividade__palestrantes")
        user = self.request.user
        if getattr(user, "is_organizador", False):
            return qs.all()
        return qs.filter(participante=user)

    def perform_create(self, serializer):
        serializer.save(participante=self.request.user)

    def get_object(self):
        obj = super().get_object()
        self.check_object_permissions(self.request, obj)
        return obj


class MeusCertificadosViewSet(viewsets.ReadOnlyModelViewSet):
    """Certificados do usuário autenticado (somente leitura, filtro por usuário)."""

    serializer_class = CertificadoSerializer
    permission_classes = [IsAuthenticated, IsDonoOuOrganizador]

    def get_queryset(self):
        qs = Certificado.objects.select_related("participante", "atividade", "evento")
        user = self.request.user
        if getattr(user, "is_organizador", False):
            return qs.all()
        return qs.filter(participante=user)

    def get_object(self):
        obj = super().get_object()
        self.check_object_permissions(self.request, obj)
        return obj