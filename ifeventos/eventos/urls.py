from django.urls import path
from eventos.views import eventos_view
from eventos.views import logout_view
from eventos.views import evento_programacao_view
from .views import gerar_qr_code, confirmar_presenca
from .views import gerar_qr_code_atividade, confirmar_presenca_atividade
from django.views.generic import TemplateView

app_name = "eventos"  # Define o app_name para o namespace


urlpatterns = [
    path("", eventos_view, name="eventos"),
    path("programacao/<int:evento_id>", evento_programacao_view, name="programacao"),

    # logout para todos os usuários
    path('logout/', logout_view, name='logout'),


    # -- QR Code - Confirmação de Presença por inscrição --
    path("gerar-qr-code/<int:inscricao_id>/", gerar_qr_code, name="gerar_qr_code"),
    path("confirmar-presenca/<uuid:codigo_confirmacao>/", confirmar_presenca, name="confirmar_presenca"),
    # path("scan_qr/", TemplateView.as_view(template_name="eventos/scan_qr.html"), name="scan_qr"),
    path("confirmar-presenca/<uuid:codigo_confirmacao>/", confirmar_presenca, name="confirmar_presenca"),

    # -- QR Code - Confirmação de Presença por atividade --
    path("gerar-qr-code-atividade/<int:atividade_id>/", gerar_qr_code_atividade, name="gerar_qr_code_atividade"),
    path("confirmar-presenca-atividade/<uuid:codigo_confirmacao>/", confirmar_presenca_atividade, name="confirmar_presenca_atividade"),
]