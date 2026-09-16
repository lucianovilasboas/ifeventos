from django.contrib import admin
from django.contrib.auth import get_user_model
from .models import Evento
from .models import Participante
from .models import Atividade
from .models import TipoAtividade
from .models import Inscricao
from .models import Certificado
from .models import PresencaCancelada
from .models import PessoaRoster
from django.utils.html import format_html
from django import forms
from django.core.exceptions import ValidationError
from . import metadados
from .validators import validar_cpf



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

    list_display = ('title', 'local','get_total_participantes','get_participantes', 'organizador', 'data_inicio', 'data_fim')
    date_hierarchy = ('data_inicio')
    ordering = ('data_inicio',)
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
        ('Informações pessoais', {'fields': ('foto','first_name', 'last_name', 'email', 'cpf', 'bio', 'telefone', 'endereco')}),
        ('Permissões', {'fields': ('is_active', 'is_organizador', 'is_participante', 'is_palestrante')}),
    )

    list_display = ( 'mostrar_foto', 'first_name','last_name','username', 'cpf', 'get_atividades_inscritas','is_active','is_staff', 'is_organizador', 'is_participante','is_palestrante')
    readonly_fields = ('mostrar_foto',)  # Exibir no detalhe do objeto


    def mostrar_foto(self, obj):
        return format_html('<img src="{}" width="30" style="border-radius: 5px;"/>', obj.foto.url if obj.foto else '/media/usuarios/default.jpeg')
        # return format_html('<img src="{}" width="20" style="border-radius: 5px;"/>', '/media/palestrantes/foto_.jpeg')  # foto padrão

    mostrar_foto.short_description = "Foto"  # Nome da coluna no Admin


    inlines = [InscricaoInline]  # Adiciona inscrições editáveis na página do participante

    def get_atividades_inscritas(self, obj):
        atividades = obj.inscricoes.values_list('atividade__titulo', flat=True)
        return ", ".join(atividades) if atividades else "..."

    get_atividades_inscritas.short_description = "Atividades Inscritas"



    # Função para marcar atividades como concluídas
    def trocar_status_de_organizador(modeladmin, request, queryset):
        # queryset.update(is_organizador=True)
        for obj in queryset:
            obj.is_organizador = not obj.is_organizador
            obj.save()        
    trocar_status_de_organizador.short_description = "Marcar/descmarcar como Organizador"

    actions = [trocar_status_de_organizador]  # Adicionando ações personalizadas




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

    list_display = ('titulo', 'evento', 'codigo_confirmacao', 'get_palestrantes','get_participantes','vagas_disponiveis', 'tipo', 'n_vagas','data_hora_inicio','data_hora_inicio',)
    list_filter = ('evento', 'tipo', 'data_hora_inicio')
    search_fields = ('titulo', 'descricao', 'tipo')
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



@admin.register(TipoAtividade)
class TipoAtividadeAdmin(admin.ModelAdmin):
    list_display = ('nome','id')
    search_fields = ('nome',)


@admin.register(Inscricao)
class InscricaoAdmin(admin.ModelAdmin):
    list_display = ('atividade','id', 'participante', 'confirmada','certificado_emitido', 'codigo_confirmacao','created_at', 'updated_at')
    search_fields = ('participante', )
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
    list_display = ('participante', 'atividade', 'evento', 'data_emissao', 'codigo')
    search_fields = ('participante', )
    list_filter = ('atividade', 'atividade__evento',)


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


