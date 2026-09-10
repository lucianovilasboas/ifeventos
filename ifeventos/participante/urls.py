from django.contrib import admin
from django.urls import path
from .views import dashboard
from .views import inscrever, cancelar_inscricao, gerenciar_inscricoes_ajax
from eventos.services import ia_mensagem_view
from .views import MeusCertificadosView

app_name = 'participante' 


urlpatterns = [
    
    # path('register/', register, name='register'),
    # path('login/', login_view, name='login'),
    path('dashboard/', dashboard, name='dashboard'),

    path('inscrever/<int:atividade_id>/', inscrever, name='inscrever'),
    path('cancelar/<int:inscricao_id>/', cancelar_inscricao, name='cancelar_inscricao'),

    # path("gerenciar_inscricoes/", gerenciar_inscricoes, name="gerenciar_inscricoes"),
    path("gerenciar_inscricoes_ajax/", gerenciar_inscricoes_ajax, name="gerenciar_inscricoes_ajax"),


    # -- Meus Certificados --
    path("meus-certificados/", MeusCertificadosView.as_view(), name="meus_certificados"),


    # -- Rotas para a IA --
    path('ia_mensagem/', ia_mensagem_view, name='ia_mensagem'),
]




