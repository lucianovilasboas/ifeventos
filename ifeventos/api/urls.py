from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)
from rest_framework.routers import DefaultRouter

from .auth import ObtainTokenView, RegistroView
from .viewsets import (
    AtividadeViewSet,
    CrachasEventoPDFView,
    EventoViewSet,
    MeusCertificadosViewSet,
    MeusCrachasViewSet,
    MinhasInscricoesViewSet,
    PalestranteViewSet,
    PresencaViewSet,
    QrAtividadePngView,
    QrCrachaPngView,
    TipoAtividadeViewSet,
    VerificacaoView,
)

router = DefaultRouter()
router.register("eventos", EventoViewSet, basename="evento")
router.register("atividades", AtividadeViewSet, basename="atividade")
router.register("tipos-atividade", TipoAtividadeViewSet, basename="tipo-atividade")
router.register("palestrantes", PalestranteViewSet, basename="palestrante")
router.register("minhas-inscricoes", MinhasInscricoesViewSet, basename="minha-inscricao")
router.register("meus-certificados", MeusCertificadosViewSet, basename="meu-certificado")
router.register("meus-crachas", MeusCrachasViewSet, basename="meu-cracha")
router.register("presencas", PresencaViewSet, basename="presenca")

urlpatterns = [
    path("auth/token/", ObtainTokenView.as_view(), name="token"),
    path("auth/registro/", RegistroView.as_view(), name="registro"),
    # Verificação pública: quem confere pode estar deslogado (portaria, app scanner)
    path("verificar/<str:token>/", VerificacaoView.as_view(), name="verificacao"),
    # PDF em lote dos crachás do evento
    path("eventos/<int:evento_id>/crachas.pdf", CrachasEventoPDFView.as_view(), name="crachas-evento-pdf"),
    # Imagens dos QR: rota literal (ver comentário em viewsets.py sobre o porquê)
    path("atividades/<int:atividade_id>/qrcode.png", QrAtividadePngView.as_view(), name="atividade-qrcode-png"),
    path("meus-crachas/<int:evento_id>/qr.png", QrCrachaPngView.as_view(), name="cracha-qr-png"),
    path("", include(router.urls)),
    # Docs OpenAPI / Swagger
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    path("redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]