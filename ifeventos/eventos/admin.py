from django.contrib import admin
from django.contrib.auth import get_user_model
from .models import Evento
from .models import Participante
from .models import Atividade
from .models import TipoAtividade
from .models import ChamadaProposicoes
from .models import Espaco
from .models import Vaga
from .models import Inscricao
from .models import Certificado
from .models import PresencaCancelada
from .models import PalestranteSugerido
from .models import PessoaRoster
from .models import ContextoIA
from .models import Assinante
from .models import AssinaturaCertificado
from .models import ConfiguracaoCertificado
from .models import RegistroAuditoria
from django.utils.html import format_html
from django.utils import timezone
from django.http import JsonResponse
from django.urls import path
from django import forms
from django.core.exceptions import ValidationError
from . import metadados
from .validators import validar_cpf


def miniatura(arquivo, largura=40, altura=None):
    """Miniatura CLICÁVEL de uma imagem no admin (ou "—" quando não há).

    Abre a imagem original em outra aba. Usada nas listas e nos detalhes para o
    organizador ver a cara da imagem sem baixar o arquivo.
    """
    if not arquivo:
        return "—"
    try:
        url = arquivo.url
    except ValueError:
        return "—"
    altura = altura or largura
    return format_html(
        '<a href="{0}" target="_blank" rel="noopener">'
        '<img src="{0}" alt="" loading="lazy" '
        'style="width:{1}px;height:{2}px;object-fit:cover;border-radius:6px;'
        'border:1px solid #e5e5e5;vertical-align:middle;"/></a>',
        url, largura, altura,
    )


def link_arquivo(arquivo, rotulo="Abrir"):
    """Link que abre um arquivo (ex.: PDF) em outra aba — "—" quando não há."""
    if not arquivo:
        return "—"
    try:
        url = arquivo.url
    except ValueError:
        return "—"
    return format_html(
        '<a href="{0}" target="_blank" rel="noopener">{1}</a>', url, rotulo
    )



@admin.register(Evento)
class EventoAdmin(admin.ModelAdmin):

    def get_participantes(self, obj):
        # Obtém todos os participantes que estão inscritos em qualquer atividade do evento
        participantes = Participante.objects.filter(inscricoes__atividade__evento=obj).distinct()
        return ", ".join([p.first_name for p in participantes])

    def get_total_participantes(self, obj):
        # Obtém o total de participantes que estão inscritos em qualquer atividade do evento
        return Participante.objects.filter(inscricoes__atividade__evento=obj).distinct().count()

    get_total_participantes.short_description = "Total" 

    get_participantes.short_description = "Participantes"

    @admin.display(description="Imagem")
    def miniatura_imagem(self, obj):
        return miniatura(obj.imagem, 60, 40)

    list_display = ('title', 'miniatura_imagem', 'local','get_total_participantes','get_participantes', 'organizador', 'data_inicio', 'data_fim')
    list_display_links = ('title',)
    readonly_fields = ('miniatura_imagem',)
    date_hierarchy = ('data_inicio')
    ordering = ('data_inicio',)
    search_fields = (
        'title', 'description', 'local',
        'organizador__first_name', 'organizador__last_name', 'organizador__email',
    )
    # list_editable = ('description', 'local', 'data_inicio', 'data_fim')


    def save_model(self, request, obj, form, change):
        """
        Ao criar um novo evento, define automaticamente o organizador autenticado,
        mas permite que o superusuário ou outro organizador altere essa escolha.
        """
        if not change and not obj.organizador:  # Apenas se for um novo evento e não tiver organizador definido
            obj.organizador = request.user  # Associa o organizador autenticado
        
        super().save_model(request, obj, form, change)


 
# @admin.register(Participante)
# class ParticipanteAdmin(admin.ModelAdmin): 
#     ...

class InscricaoInline(admin.TabularInline):  
    model = Inscricao
    extra = 1  # Mostra uma linha extra para adicionar novas inscrições
    fields = ('atividade', 'confirmada')  # Campos visíveis
    autocomplete_fields = ('atividade',)  # Facilita a seleção de atividades
    can_delete = True  # Permite remover inscrições
    show_change_link = True  # Adiciona link para editar a inscrição



@admin.register(Participante)
class ParticipanteAdmin(admin.ModelAdmin):

    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Informações pessoais', {'fields': ('foto', 'first_name', 'last_name', 'email', 'cpf', 'bio', 'telefone', 'endereco')}),
        ('Permissões', {'fields': ('is_active', 'is_equipe', 'is_organizador', 'is_participante', 'is_palestrante')}),
        # Readonly: quando a conta foi criada, último login e última alteração.
        ('Registro', {'fields': ('date_joined', 'last_login', 'atualizado_em')}),
    )

    list_display = (
        'mostrar_foto', 'first_name', 'last_name', 'username', 'cpf',
        'get_atividades_inscritas', 'is_active', 'is_staff', 'is_equipe',
        'is_organizador', 'is_participante', 'is_palestrante', 'criado_em',
    )
    list_display_links = ('first_name',)
    list_filter = ('is_active', 'is_equipe', 'is_organizador', 'is_participante', 'is_palestrante')
    # Mais recentes primeiro: é o que interessa ao conferir cadastros novos.
    ordering = ('-date_joined', '-id')
    date_hierarchy = 'date_joined'
    readonly_fields = ('mostrar_foto', 'date_joined', 'last_login', 'atualizado_em')
    search_fields = ('first_name', 'last_name', 'email', 'cpf', 'username')


    @admin.display(description="Foto")
    def mostrar_foto(self, obj):
        if obj.foto:
            return miniatura(obj.foto, 32, 32)
        return format_html(
            '<img src="/media/usuarios/default.jpeg" width="32" height="32" '
            'style="border-radius:5px;object-fit:cover;"/>'
        )

    @admin.display(description="Criado em", ordering="date_joined")
    def criado_em(self, obj):
        if not obj.date_joined:
            return "—"
        return timezone.localtime(obj.date_joined).strftime("%d/%m/%Y %H:%M")

    def get_atividades_inscritas(self, obj):
        atividades = obj.inscricoes.values_list('atividade__titulo', flat=True)
        return ", ".join(atividades) if atividades else "..."

    get_atividades_inscritas.short_description = "Atividades Inscritas"

    inlines = [InscricaoInline]  # Adiciona inscrições editáveis na página do participante

    # ----------------------------------------------------------------------
    # Ações: alternar os papéis da pessoa (equipe/organizador/participante/
    # palestrante). Usa `update()` no banco em vez de `obj.save()`: atualiza o
    # papel E `atualizado_em` de uma vez, sem disparar o reprocessamento da
    # imagem de perfil que o `save()` do modelo faria a cada clique.
    # ----------------------------------------------------------------------
    def _alternar_papel(self, queryset, campo):
        for pessoa in queryset:
            queryset.model.objects.filter(pk=pessoa.pk).update(
                **{campo: not getattr(pessoa, campo), "atualizado_em": timezone.now()}
            )

    @admin.action(description="Alternar membro da equipe de apoio")
    def alternar_equipe(self, request, queryset):
        self._alternar_papel(queryset, "is_equipe")

    @admin.action(description="Alternar organizador")
    def alternar_organizador(self, request, queryset):
        self._alternar_papel(queryset, "is_organizador")

    @admin.action(description="Alternar participante")
    def alternar_participante(self, request, queryset):
        self._alternar_papel(queryset, "is_participante")

    @admin.action(description="Alternar palestrante")
    def alternar_palestrante(self, request, queryset):
        self._alternar_papel(queryset, "is_palestrante")

    actions = [
        "alternar_equipe",
        "alternar_organizador",
        "alternar_participante",
        "alternar_palestrante",
    ]




@admin.register(Atividade)
class AtividadeAdmin(admin.ModelAdmin):

    def get_palestrantes(self, obj):
        return ", ".join([p.first_name for p in obj.palestrantes.all()])  # Ajuste conforme necessário

    def get_participantes(self, obj):
        return ", ".join([inscricao.participante.first_name for inscricao in obj.inscritos.all()])

    def vagas_disponiveis(self, obj):
        return obj.vagas_disponiveis()

    get_palestrantes.short_description = "Palestrante(s)"  # Nome exibido no Admin    
    get_participantes.short_description = "Participante(s)"    
    vagas_disponiveis.short_description = "# Vagas Disponíveis"

    @admin.display(description="Imagem")
    def miniatura_imagem(self, obj):
        return miniatura(obj.imagem, 60, 40)

    list_display = ('titulo', 'miniatura_imagem', 'evento', 'situacao', 'proponente', 'codigo_confirmacao', 'get_palestrantes','get_participantes','vagas_disponiveis', 'tipo', 'n_vagas','data_hora_inicio','data_hora_inicio',)
    list_display_links = ('titulo',)
    readonly_fields = ('miniatura_imagem',)
    list_filter = ('evento', 'tipo', 'situacao', 'publicada', 'data_hora_inicio')
    search_fields = ('titulo', 'descricao', 'tipo__nome')
    date_hierarchy = 'data_hora_inicio'
    ordering = ('data_hora_inicio',)
    filter_horizontal = ('palestrantes',)
    list_editable = ('tipo', 'n_vagas',)



    # Função para duplicar atividades selecionadas
    def duplicar_atividades(modeladmin, request, queryset):
        for obj in queryset:
            obj.id = None  # Define o ID como None para criar um novo objeto
            obj.save()
    duplicar_atividades.short_description = "Duplicar Atividades Selecionadas"    

    actions = [duplicar_atividades]  # Adicionando ações personalizadas



@admin.register(Espaco)
class EspacoAdmin(admin.ModelAdmin):
    """Catálogo de espaços da escola (compartilhado pelos eventos)."""

    list_display = ('nome', 'capacidade', 'id')
    search_fields = ('nome',)
    ordering = ('nome',)


@admin.register(ChamadaProposicoes)
class ChamadaProposicoesAdmin(admin.ModelAdmin):
    """Período de proposições do evento."""

    list_display = ('evento', 'titulo', 'inicio', 'fim', 'aberta')
    list_filter = ('aberta', 'evento')
    search_fields = ('evento__title', 'titulo')
    ordering = ('-inicio',)


@admin.register(Vaga)
class VagaAdmin(admin.ModelAdmin):
    """Grade de oferta: o que o proponente pode reservar."""

    def get_ocupadas(self, obj):
        return obj.ocupadas

    get_ocupadas.short_description = "Ocupadas"

    list_display = ('espaco', 'evento', 'inicio', 'fim', 'capacidade', 'get_ocupadas')
    list_filter = ('evento', 'espaco')
    search_fields = ('espaco__nome', 'evento__title')
    ordering = ('inicio',)


@admin.register(TipoAtividade)
class TipoAtividadeAdmin(admin.ModelAdmin):
    list_display = ('nome','id')
    search_fields = ('nome',)


@admin.register(Inscricao)
class InscricaoAdmin(admin.ModelAdmin):
    list_display = ('atividade','id', 'participante', 'confirmada','certificado_emitido', 'codigo_confirmacao','created_at', 'updated_at')
    search_fields = (
        'participante__first_name', 'participante__last_name',
        'participante__email', 'participante__cpf', 'atividade__titulo',
    )
    list_editable = ('participante', )
    list_filter = ('atividade', 'atividade__evento',)


    # Função para marcar/desmarcar inscrições como confirmadas 
    def trocar_status_de_confirmada(modeladmin, request, queryset):
        # queryset.update(is_organizador=True)
        for obj in queryset:
            obj.confirmada = not obj.confirmada
            obj.save()        
    trocar_status_de_confirmada.short_description = "Marcar/descmarcar como Conformada"


    # Função para marcar/desmarcar inscrições como certificado emitido
    def trocar_status_de_certificado_emitido(modeladmin, request, queryset):
        # queryset.update(is_organizador=True)
        for obj in queryset:
            obj.certificado_emitido = not obj.certificado_emitido
            obj.save()        
    trocar_status_de_certificado_emitido.short_description = "Marcar/descmarcar Certificado Emitido"


    actions = [trocar_status_de_confirmada, trocar_status_de_certificado_emitido]  # Adicionando ações personalizadas



@admin.register(Certificado)
class CertificadoAdmin(admin.ModelAdmin):
    @admin.display(description="PDF")
    def arquivo_pdf(self, obj):
        return link_arquivo(obj.pdf, "Abrir PDF")

    list_display = ('participante', 'tipo', 'atividade', 'evento', 'carga_horaria', 'data_emissao', 'codigo', 'arquivo_pdf')
    readonly_fields = ('arquivo_pdf',)
    search_fields = (
        'participante__first_name', 'participante__last_name',
        'participante__email', 'participante__cpf',
        'atividade__titulo', 'evento__title',
    )
    list_filter = ('tipo', 'atividade', 'atividade__evento',)


@admin.register(PresencaCancelada)
class PresencaCanceladaAdmin(admin.ModelAdmin):
    """Histórico de presenças desfeitas — SOMENTE LEITURA.

    É registro de auditoria: se pudesse ser editado ou apagado, não serviria
    para dizer quem desfez uma presença e quando.
    """

    list_display = (
        'cancelada_em', 'pessoa_nome', 'atividade_titulo', 'papel', 'motivo', 'cancelada_por',
    )
    list_filter = ('papel', 'origem', 'cancelada_em')
    search_fields = ('pessoa_nome', 'atividade_titulo', 'motivo')
    date_hierarchy = 'cancelada_em'
    readonly_fields = (
        'atividade', 'atividade_titulo', 'participante', 'pessoa_nome',
        'papel', 'origem', 'registrada_em', 'cancelada_em', 'cancelada_por', 'motivo',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class PessoaRosterForm(forms.ModelForm):
    """Valida o JSON `dados` e o CPF na hora de salvar, no próprio admin.

    Sem isto, um valor fora das opções (ex.: "Informatica", sem acento) só
    aparecia como aviso no log, em tempo de login, e o perfil não era
    preenchido. Aqui o erro aparece no formulário, antes de gravar. A validação
    é por vínculo (o mesmo `metadados.validar` do formulário/importação).
    """

    class Meta:
        model = PessoaRoster
        fields = "__all__"

    cpf = forms.CharField(
        max_length=14,  # aceita com máscara; normalizamos no clean_cpf
        required=False,
        label="CPF",
        help_text="Aceita com ou sem máscara; guardamos só os 11 dígitos.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["dados"].help_text = self._ajuda_dados()
        self.fields["dados"].widget.attrs.setdefault("rows", 6)

    @staticmethod
    def _ajuda_dados():
        partes = []
        for campo in metadados.campos():
            if campo["opcoes_por"]:
                valores = "; ".join(
                    f"{pai}: {', '.join(opcoes)}"
                    for pai, opcoes in campo["opcoes_por"].items()
                )
                partes.append(
                    f"{campo['chave']} (conforme {campo['depende_de']}: {valores})"
                )
            elif campo["opcoes"]:
                partes.append(f"{campo['chave']} ({', '.join(campo['opcoes'])})")
            else:
                partes.append(campo["chave"])
        return "JSON com os metadados. Chaves: " + "; ".join(partes) + "."

    def clean_dados(self):
        dados = self.cleaned_data.get("dados")
        if not dados:
            return {}
        if not isinstance(dados, dict):
            raise forms.ValidationError('Informe um objeto JSON ({"chave": "valor"}).')
        erros = metadados.validar(dados)
        if erros:
            rotulos = {c["chave"]: c["rotulo"] for c in metadados.campos()}
            mensagens = [
                f"{rotulos.get(chave, chave)}: {mensagem}"
                for chave, lista in erros.items()
                for mensagem in lista
            ]
            raise forms.ValidationError(mensagens)
        return dados

    def clean_cpf(self):
        cpf = (self.cleaned_data.get("cpf") or "").strip()
        if not cpf:
            return ""
        try:
            return validar_cpf(cpf)
        except ValidationError as exc:
            raise forms.ValidationError(exc.messages)


@admin.register(PessoaRoster)
class PessoaRosterAdmin(admin.ModelAdmin):
    """Pré-carga da planilha — serve TODOS os vínculos.

    A chave é o e-mail; `dados` são os metadados (validados por vínculo) que
    preenchem o perfil na criação da conta. `vinculo` é só um espelho para
    filtro/relatório e é derivado de `dados`.
    """

    form = PessoaRosterForm
    list_display = ('email', 'nome', 'vinculo', 'metadados_resumo', 'cpf',
                    'confere', 'situacao', 'usado_em', 'atualizado_em')
    list_filter = ('vinculo', 'confere')
    search_fields = ('email', 'nome', 'cpf')
    ordering = ('email',)
    readonly_fields = ('vinculo', 'atualizado_em', 'usado_em', 'dados_usuario')

    @admin.display(description='Situação')
    def situacao(self, obj):
        if not obj.usado_em:
            return 'não usado'
        return 'usado e confere' if obj.confere else 'usado e diverge'

    @admin.display(description='Metadados')
    def metadados_resumo(self, obj):
        dados = obj.dados or {}
        partes = [
            f"{campo['rotulo']}: {dados[campo['chave']]}"
            for campo in metadados.campos()
            if dados.get(campo["chave"])
        ]
        return " · ".join(partes)


@admin.register(ContextoIA)
class ContextoIAAdmin(admin.ModelAdmin):
    """Edita QUAL modelo de LLM cada contexto usa (sem deploy).

    Os campos de identificação (chave/rótulo/grupo/ordem/padrão) vêm do código
    e ficam somente-leitura aqui; o comando `sincronizar_contextos_ia` mantém as
    linhas em dia. O que se edita é o modelo, os ajustes e o liga/desliga.
    """

    list_display = ("grupo", "rotulo", "chave", "modelo_efetivo", "modelo",
                    "ativo", "atualizado_em")
    list_editable = ("modelo", "ativo")
    list_filter = ("grupo", "ativo")
    search_fields = ("chave", "rotulo", "modelo")
    ordering = ("grupo", "ordem", "rotulo")
    readonly_fields = ("chave", "rotulo", "grupo", "tipo_padrao", "ordem",
                       "modelo_efetivo", "atualizado_em")

    class Media:
        # Preenche o datalist do campo "Modelo de LLM" com os modelos da OpenAI.
        js = ("js/admin_contextoia.js",)

    @admin.display(description="Modelo efetivo")
    def modelo_efetivo(self, obj):
        from . import ia_config

        return ia_config.modelo_da_linha(obj)

    def get_urls(self):
        urls = super().get_urls()
        extra = [
            path(
                "modelos-openai/",
                self.admin_site.admin_view(self.modelos_openai_view),
                name="eventos_contextoia_modelos",
            ),
        ]
        return extra + urls

    def modelos_openai_view(self, request):
        """Lista (cacheada) dos modelos de chat da OpenAI para o datalist."""
        from . import ia_config

        return JsonResponse({"modelos": ia_config.modelos_openai()})


@admin.register(PalestranteSugerido)
class PalestranteSugeridoAdmin(admin.ModelAdmin):
    list_display = ("nome", "email", "atividade", "participante", "criado_em")
    list_filter = ("atividade__evento",)
    search_fields = ("nome", "email")


@admin.register(Assinante)
class AssinanteAdmin(admin.ModelAdmin):
    @admin.display(description="Assinatura")
    def miniatura_assinatura(self, obj):
        return miniatura(obj.imagem, 120, 40)

    list_display = ("nome", "miniatura_assinatura", "cargo", "ativo", "criado_em")
    list_display_links = ("nome",)
    readonly_fields = ("miniatura_assinatura",)
    list_filter = ("ativo",)
    search_fields = ("nome", "cargo")


class AssinaturaCertificadoInline(admin.TabularInline):
    model = AssinaturaCertificado
    extra = 1
    max_num = 2
    fields = ("ordem", "nome", "cargo", "imagem", "miniatura_assinatura")
    readonly_fields = ("miniatura_assinatura",)

    @admin.display(description="Prévia")
    def miniatura_assinatura(self, obj):
        if obj is None or not obj.pk:
            return "—"
        return miniatura(obj.imagem, 120, 40)


@admin.register(ConfiguracaoCertificado)
class ConfiguracaoCertificadoAdmin(admin.ModelAdmin):
    list_display = ("evento", "escopo", "atividade", "modo_layout", "titulo", "enviar_email")
    list_filter = ("escopo", "modo_layout", "enviar_email")
    search_fields = ("evento__title", "atividade__titulo")
    inlines = [AssinaturaCertificadoInline]



@admin.register(RegistroAuditoria)
class RegistroAuditoriaAdmin(admin.ModelAdmin):
    """Trilha de auditoria — SOMENTE LEITURA.

    É registro histórico: se pudesse ser editado/apagado, não serviria para
    dizer quem fez o quê. A aplicação também nunca altera estas linhas.
    """

    list_display = (
        "criado_em", "usuario_nome", "acao", "entidade", "objeto_repr",
        "origem", "resumo",
    )
    list_filter = ("acao", "entidade", "origem", "criado_em")
    search_fields = (
        "usuario_nome", "usuario_email", "resumo", "objeto_repr", "objeto_id",
    )
    date_hierarchy = "criado_em"
    list_select_related = ("usuario", "evento")
    readonly_fields = (
        "criado_em", "request_id", "usuario", "usuario_nome", "usuario_email",
        "origem", "acao", "entidade", "objeto_id", "objeto_repr", "evento",
        "resumo", "detalhes", "ip", "path", "metodo", "status",
    )
    ordering = ("-criado_em",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
