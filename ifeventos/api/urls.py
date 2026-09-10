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
    EventoViewSet,
    MeusCertificadosViewSet,
    MinhasInscricoesViewSet,
    TipoAtividadeViewSet,
)

router = DefaultRouter()
router.register("eventos", EventoViewSet, basename="evento")
router.register("atividades", AtividadeViewSet, basename="atividade")
router.register("tipos-atividade", TipoAtividadeViewSet, basename="tipo-atividade")
router.register("minhas-inscricoes", MinhasInscricoesViewSet, basename="minha-inscricao")
router.register("meus-certificados", MeusCertificadosViewSet, basename="meu-certificado")

urlpatterns = [
    path("auth/token/", ObtainTokenView.as_view(), name="token"),
    path("auth/registro/", RegistroView.as_view(), name="registro"),
    path("", include(router.urls)),
    # Docs OpenAPI / Swagger
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    path("redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]