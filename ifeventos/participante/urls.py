from django.contrib import admin
from django.urls import path
from .views import dashboard
from .views import inscrever, cancelar_inscricao, gerenciar_inscricoes_ajax
from .views import (
    cancelar_proposta,
    editar_proposta,
    minhas_propostas,
    propor_atividade,
)
from eventos.services import ia_mensagem_view, sugerir_tipo_ajax
from .views import MeusCertificadosView, MeusCrachasView

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

    # -- Meus Crachás (crachá com QR para confirmar presença) --
    path("meus-crachas/", MeusCrachasView.as_view(), name="meus_crachas"),

    # -- Chamada de proposições (proponente) --
    path("propostas/", minhas_propostas, name="minhas_propostas"),
    path("propostas/<int:evento_id>/nova/", propor_atividade, name="propor_atividade"),
    path("propostas/<int:atividade_id>/editar/", editar_proposta, name="editar_proposta"),
    path("propostas/<int:atividade_id>/cancelar/", cancelar_proposta, name="cancelar_proposta"),
    path("propostas/sugerir-tipo/", sugerir_tipo_ajax, name="sugerir_tipo"),


    # -- Rotas para a IA --
    path('ia_mensagem/', ia_mensagem_view, name='ia_mensagem'),
]




