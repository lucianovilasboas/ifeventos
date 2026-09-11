"""
URL configuration for setup project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path, include, re_path
from django.views.static import serve
from eventos.views import confirmar_presenca_pelo_qr, eventos_view, verificar_cracha
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [

    path("", eventos_view, name="home"), 

    path("admin/", admin.site.urls),
    # -- Eventos --
    path("eventos/", include("eventos.urls", namespace="eventos")), 

        # -- Social Auth --
    path('accounts/', include('allauth.urls')), 
    # path('accounts/', include('allauth.socialaccount.urls')),

    path('accounts/profile', eventos_view, name='profile'),

    # -- Verificação pública do QR de crachá e de certificado --
    # Rota curta de propósito: ela vai dentro do QR impresso e é digitada por
    # quem não consegue escanear. Fica fora de /eventos/ e /organizador/ porque
    # quem confere pode estar deslogado.
    path("c/<str:token>/", verificar_cracha, name="verificar_cracha"),
    # Confirmação da própria pessoa pelo QR da atividade (fluxo B)
    path("p/<str:token>/", confirmar_presenca_pelo_qr, name="confirmar_presenca_pelo_qr"),

    # -- API REST (django-rest-framework) --
    path("api/v1/", include("api.urls")),

    # -- Participante --
    path("participante/", include("participante.urls", namespace="participante")),


    # -- Organizador --
    path("organizador/", include("organizador.urls", namespace="organizador")),

    # # -- Relatórios --
    # path("relatorios/", include("relatorios.urls", namespace="relatorios")),
]



# Permite acessar arquivos de mídia publicamente no ambiente de desenvolvimento
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Mídia também em produção: com DEBUG=False o helper static() devolve [] e as
# capas dos eventos e os certificados quebrariam. O helper acima continua
# valendo em desenvolvimento; este garante /media/ em qualquer modo.
# Para volume maior, trocar por um roteador no Traefik servindo o volume.
if not settings.DEBUG:
    urlpatterns += [
        re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
    ]