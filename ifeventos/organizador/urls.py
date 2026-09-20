from django.contrib import admin
from django.urls import path
from django.views.generic import RedirectView

from organizador.views import adicionar_palestrante, adicionar_tipo_atividade
from organizador.views import adicionar_espaco_ajax
from .views import ModeloCrachaEventoView, dashboard, criar_evento, editar_evento, excluir_evento
from .views import atividades_evento, criar_atividade, editar_atividade, excluir_atividade
from .views import criar_editar_atividade
from .views import profile
from .views import importar_metadados, modelo_metadados_csv
from .views import importar_programacao
from .views import copiloto_evento_plano, aplicar_plano_evento, remover_plano_evento
from .views import equipe_apoio_adicionar, equipe_apoio_remover
from .views import briefing_operacional, briefing_leitura, gerar_divulgacao
from relatorios.views import RelatorioInscricoesView
from relatorios.views import ListaPresencaView
from relatorios.views import OcupacaoSalasView
from relatorios.views import RelatoriosGraficosView
from relatorios.views import narrativa_evento
from relatorios.views import (
    RelatorioParticipantesView,
    relatorio_participante_detalhe,
    graficos_curadoria,
    graficos_insights,
    grafico_por_descricao,
    RelatorioTurmasView,
    RelatorioOficinasView,
)
from organizador.views import publicar_atividade
from organizador.views import (
    adicionar_espaco,
    adicionar_vaga,
    aprovar_proposta,
    gerar_grade_lote,
    chamada_painel,
    chamada_proposicoes,
    editar_espaco,
    editar_vaga,
    excluir_espaco,
    excluir_vaga,
    propostas_pendentes,
    rejeitar_proposta,
    cadastrar_palestrante_sugerido,
    cadastrar_tipo_sugerido,
    salvar_chamada,
    triagem_propostas,
)

from eventos.services import ia_mensagem_view, gerar_conteudo_ajax, sugerir_categoria_ajax
from .views import EmitirCertificadosAtividadeView
from .views import EmitirCertificadosEventoView
from .views import EmitirCertificadoInscricaoView
from .views import CheckinAtividadeView, CrachasEventoView, QrAtividadeView


app_name = 'organizador'


urlpatterns = [
    # path('register/', register, name='register'),
    # path('login/', login_view, name='login'),

    path('dashboard/', dashboard, name='dashboard'), 

    path('criar_evento/', criar_evento, name='criar_evento'),
    path('editar_evento/<int:evento_id>/', editar_evento, name='editar_evento'),
    path('excluir_evento/<int:evento_id>/', excluir_evento, name='excluir_evento'),    


    path('atividades_evento/<int:evento_id>/', atividades_evento, name='atividades_evento'), 

    path('evento/<int:evento_id>/importar-programacao/', importar_programacao, name='importar_programacao'),
    path('copiloto/<int:evento_id>/', copiloto_evento_plano, name='copiloto_evento'),
    path('evento/<int:evento_id>/aplicar-plano/', aplicar_plano_evento, name='aplicar_plano_evento'),
    path('evento/<int:evento_id>/remover-plano/', remover_plano_evento, name='remover_plano_evento'),
    path('evento/<int:evento_id>/operacao/', briefing_operacional, name='briefing_operacional'),
    path('evento/<int:evento_id>/operacao/leitura/', briefing_leitura, name='briefing_leitura'),
    path('evento/<int:evento_id>/divulgacao/', gerar_divulgacao, name='gerar_divulgacao'),

    path('criar_atividade/', criar_atividade, name='criar_atividade'), # criar atividade via modal

    path('atividades_evento/<int:evento_id>/atividade/nova/', criar_editar_atividade, name='criar_editar_atividade_criar'),
    path('atividades_evento/<int:evento_id>/atividade/<int:atividade_id>/editar/', criar_editar_atividade, name='criar_editar_atividade_editar'),


    path('editar_atividade/<int:atividade_id>/', editar_atividade, name='editar_atividade'),
    path('atividade/<int:atividade_id>/publicar/', publicar_atividade, name='publicar_atividade'),
    path('excluir_atividade/<int:atividade_id>/', excluir_atividade, name='excluir_atividade'),


    path('adicionar_palestrante/', adicionar_palestrante, name='adicionar_palestrante'),
    path('adicionar_tipo_atividade/', adicionar_tipo_atividade, name='adicionar_tipo_atividade'), 
    path('adicionar_espaco/', adicionar_espaco_ajax, name='adicionar_espaco_ajax'),


    #-- Profile --
    path('profile/', profile, name='profile'), 

    # -- Chamada de proposições de atividades --
    path("chamada/<int:evento_id>/", chamada_proposicoes, name="chamada_proposicoes"),
    path("chamada/<int:evento_id>/salvar/", salvar_chamada, name="salvar_chamada"),
    path("chamada/<int:evento_id>/espaco/novo/", adicionar_espaco, name="adicionar_espaco"),
    path("chamada/<int:evento_id>/espaco/<int:espaco_id>/editar/", editar_espaco, name="editar_espaco"),
    path("chamada/<int:evento_id>/espaco/<int:espaco_id>/excluir/", excluir_espaco, name="excluir_espaco"),
    path("chamada/<int:evento_id>/vaga/nova/", adicionar_vaga, name="adicionar_vaga"),
    path("chamada/<int:evento_id>/vagas/gerar/", gerar_grade_lote, name="gerar_grade_lote"),
    path("chamada/<int:evento_id>/vaga/<int:vaga_id>/editar/", editar_vaga, name="editar_vaga"),
    path("chamada/vaga/<int:vaga_id>/excluir/", excluir_vaga, name="excluir_vaga"),
    path("chamada/<int:evento_id>/painel/", chamada_painel, name="chamada_painel"),
    path("propostas/<int:evento_id>/", propostas_pendentes, name="propostas_pendentes"),
    path("propostas/<int:evento_id>/triagem/", triagem_propostas, name="triagem_propostas"),
    path("proposta/<int:atividade_id>/aprovar/", aprovar_proposta, name="aprovar_proposta"),
    path("proposta/<int:atividade_id>/rejeitar/", rejeitar_proposta, name="rejeitar_proposta"),
    path("palestrante-sugerido/<int:sugestao_id>/cadastrar/", cadastrar_palestrante_sugerido, name="cadastrar_palestrante_sugerido"),
    path("proposta/<int:atividade_id>/tipo-sugerido/cadastrar/", cadastrar_tipo_sugerido, name="cadastrar_tipo_sugerido"),

    #-- Metadados do participante (por escola) --
    path('importar_metadados/', importar_metadados, name='importar_metadados'),
    path('metadados/modelo.csv', modelo_metadados_csv, name='modelo_metadados_csv'),


    # -- Relatórios -- 
    path("relatorio_inscricoes/<int:evento_id>/", RelatorioInscricoesView.as_view(), name="relatorio_inscricoes"),
    path("ocupacao_salas/<int:evento_id>/", OcupacaoSalasView.as_view(), name="ocupacao_salas"),
    path("relatorios_graficos/<int:evento_id>/", RelatoriosGraficosView.as_view(), name="relatorios_graficos"),
    path("relatorios_graficos/<int:evento_id>/narrado/", narrativa_evento, name="narrativa_evento"),
    path("relatorio_participantes/<int:evento_id>/", RelatorioParticipantesView.as_view(), name="relatorio_participantes"),
    path("relatorio_turmas/<int:evento_id>/", RelatorioTurmasView.as_view(), name="relatorio_turmas"),
    path("relatorio_oficinas/<int:evento_id>/", RelatorioOficinasView.as_view(), name="relatorio_oficinas"),
    path("relatorio_participantes/<int:evento_id>/<int:participante_id>/", relatorio_participante_detalhe, name="relatorio_participante_detalhe"),
    path("relatorio_participantes/<int:evento_id>/curadoria/", graficos_curadoria, name="graficos_curadoria"),
    path("relatorio_participantes/<int:evento_id>/grafico/", grafico_por_descricao, name="grafico_por_descricao"),
    path("relatorio_participantes/<int:evento_id>/insights/", graficos_insights, name="graficos_insights"),
    # Redirecionamento das URLs antigas (rename "aluno" -> "participante").
    # 301 permanente + query string preservada, para links/bookmarks antigos
    # não caírem em 404. As sub-rotas curadoria/grafico/insights são POST do
    # próprio JS (a página sempre carrega com a URL nova) e ficam de fora.
    path("relatorio_alunos/<int:evento_id>/",
         RedirectView.as_view(pattern_name="organizador:relatorio_participantes",
                              permanent=True, query_string=True),
         name="relatorio_alunos_redirect"),
    path("relatorio_alunos/<int:evento_id>/<int:participante_id>/",
         RedirectView.as_view(pattern_name="organizador:relatorio_participante_detalhe",
                              permanent=True, query_string=True),
         name="relatorio_aluno_detalhe_redirect"),
    path("relatorio_lista_presenca/atividade/<int:atividade_id>/", ListaPresencaView.as_view(), name="relatorio_lista_presenca"),


    # -- Certificados --
    path("emitir-certificados/atividade/<int:atividade_id>/", EmitirCertificadosAtividadeView.as_view(), name="emitir_certificados_atividade"),

    path("emitir-certificado/inscricao/<int:inscricao_id>/", EmitirCertificadoInscricaoView.as_view(), name="emitir_certificado_inscricao"),

    path("emitir-certificados/evento/<int:evento_id>/", EmitirCertificadosEventoView.as_view(), name="emitir_certificados_evento"),

    # -- Crachás --
    path("crachas/evento/<int:evento_id>/", CrachasEventoView.as_view(), name="crachas_evento"),

    # -- Presença: QR da atividade (exibir na tela) e check-in pela câmera --
    path("atividade/<int:atividade_id>/qrcode/", QrAtividadeView.as_view(), name="qrcode_atividade"),
    path("atividade/<int:atividade_id>/checkin/", CheckinAtividadeView.as_view(), name="checkin_atividade"),
    path("evento/<int:evento_id>/modelo-cracha/", ModeloCrachaEventoView.as_view(), name="modelo_cracha_evento"),

    # -- Equipe de apoio do evento --
    path("evento/<int:evento_id>/equipe/adicionar/", equipe_apoio_adicionar, name="equipe_apoio_adicionar"),
    path("evento/<int:evento_id>/equipe/remover/", equipe_apoio_remover, name="equipe_apoio_remover"),

    # -- Rotas para a IA --
    path('ia_mensagem/', ia_mensagem_view, name='ia_mensagem'),
    path('gerar_descricao/', gerar_conteudo_ajax, name='gerar_descricao'),   
    path('sugerir_categoria/', sugerir_categoria_ajax, name='sugerir_categoria'),
]