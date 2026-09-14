from django import forms
from .models import Evento, Participante, TipoAtividade
from .models import sem_acento, categorias_conhecidas
from .models import Atividade
from django.core.exceptions import ValidationError
from django.urls import reverse_lazy
from django.utils.safestring import mark_safe

from allauth.account.forms import SignupForm as AllauthSignupForm

from .validators import validar_cpf


# -- Formulário para criação de evento --

class EventoForm(forms.ModelForm):
    # Categoria (é o "tema" que a landing usa nos filtros por assunto).
    # Campo de TEXTO com lista de sugestões (o `datalist` é montado no
    # template): o organizador escolhe uma categoria existente ou escreve uma
    # nova, que passa a existir no banco e ganha filtro próprio na landing.
    categoria = forms.CharField(
        label="Categoria",
        required=True,
        max_length=60,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "list": "listaCategorias",
            "autocomplete": "off",
            "placeholder": "Escolha uma categoria ou escreva uma nova",
        }),
    )

    class Meta:
        model = Evento
        fields = ['title', 'description', 'data_inicio', 'data_fim', 'local', 'categoria', 'imagem']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control','style': 'max-height: 100px; overflow-y: auto;'}),
            'data_inicio': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
            'data_fim': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
            'local': forms.TextInput(attrs={'class': 'form-control'}),
            'imagem': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Sugestões do datalist: lista-semente + categorias já criadas.
        self.categorias_sugeridas = categorias_conhecidas()
        # Ao editar, o campo mostra o rótulo amigável em vez do valor interno
        # (ex.: "Tecnologia" no lugar de "tecnologia").
        if getattr(self.instance, "pk", None):
            self.initial["categoria"] = self.instance.get_categoria_display()

    def clean_categoria(self):
        """Normaliza a categoria informada.

        Quando o texto corresponde a uma categoria já conhecida, grava o valor
        canônico (comparação sem acento e sem caixa). Sem isso, "Robotica"
        digitado viraria um filtro separado de "Robótica" na landing.
        """
        texto = " ".join((self.cleaned_data.get("categoria") or "").split())
        if not texto:
            raise forms.ValidationError("Informe a categoria do evento.")
        for valor, rotulo in categorias_conhecidas():
            if sem_acento(texto) in (sem_acento(valor), sem_acento(rotulo)):
                return valor
        return texto[:60]


# class EventoForm(forms.ModelForm):
#     class Meta:
#         model = Evento
#         fields = ['title', 'description', 'data_inicio', 'data_fim', 'local', 'imagem']
#         widgets = {
#             'title': forms.TextInput(attrs={'class': 'form-control'}),
#             'description': forms.Textarea(attrs={'class': 'form-control', 'style': 'max-height: 100px; overflow-y: auto;'}),
#             'data_inicio': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
#             'data_fim': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
#             'local': forms.TextInput(attrs={'class': 'form-control'}),
#             'imagem': forms.ClearableFileInput(attrs={'class': 'form-control'}),
#         }

#     def __init__(self, *args, **kwargs):
#         super(EventoForm, self).__init__(*args, **kwargs)
#         self.fields['data_inicio'].widget.attrs.update({'class': 'form-control col-6 d-inline-block', 'style': 'width: 40%; margin-right: 4%;'})
#         self.fields['data_fim'].widget.attrs.update({'class': 'form-control col-6 d-inline-block', 'style': 'width: 40%;'})




# -- Formulário para criação ativiade --

# class AtividadeForm(forms.ModelForm):

#     class Meta:
#         model = Atividade
#         fields = ['evento','titulo', 'descricao', 'tipo', 'palestrantes','data_hora_inicio', 'data_hora_fim', 'n_vagas', 'n_inscricoes']
#         widgets = { 
#             'evento': forms.Select(attrs={'class': 'form-control'}),
#             'titulo': forms.TextInput(attrs={'class': 'form-control'}),
#             'descricao': forms.Textarea(attrs={'class': 'form-control','style': 'max-height: 100px; overflow-y: auto;'}),
#             'tipo': forms.Select(attrs={'class': 'form-control'}),
#             'palestrantes': forms.SelectMultiple(attrs={'class': 'form-control'}),
#             'data_hora_inicio': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
#             'data_hora_fim': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
#             'n_vagas': forms.NumberInput(attrs={'class': 'form-control'}),
#             'n_inscricoes': forms.NumberInput(attrs={'class': 'form-control'}),
#         }




class AtividadeForm(forms.ModelForm):
    """Formulário de criação/edição de atividade.

    Diferenças em relação ao formato antigo, todas deliberadas:
      - `evento` saiu do formulário: o evento vem da URL e a view força o
        vínculo ao salvar, então o campo só ocupava espaço e podia ser
        trocado sem efeito algum;
      - `n_inscricoes` saiu: o save() do model recalcula esse número a partir
        das inscrições, ou seja, o que se digitava era descartado;
      - `emite_certificado` entrou: o campo existe no model e a página pública
        mostra "Emite certificado/Sem certificado", mas não havia onde marcá-lo
        (todas as atividades ficavam sem certificado).
    """

    # `tipo` e `palestrantes` são declarados aqui (não vêm do model), então o
    # Meta.labels não os alcança: o rótulo precisa ser dado no próprio campo.
    tipo = forms.ModelChoiceField(
        queryset=TipoAtividade.objects.all(),
        label='Tipo de atividade',
        widget=forms.Select(attrs={'class': 'form-select'}),
        # Sem empty_label o select abria com "---------", que não diz o que
        # escolher (era o estado inicial de toda atividade nova).
        empty_label='Selecione o tipo…',
        required=True
    )

    # Select múltiplo com altura fixa: mostra vários nomes de uma vez e rola
    # dentro da caixa, em vez de esticar o formulário quando há muitos
    # palestrantes cadastrados.
    palestrantes = forms.ModelMultipleChoiceField(
        queryset=Participante.objects.filter(is_palestrante=True),
        label='Palestrantes',
        widget=forms.SelectMultiple(attrs={'class': 'form-select', 'size': 6}),
        required=True
    )

    class Meta:
        model = Atividade
        fields = [
            'titulo', 'descricao', 'local', 'tipo', 'palestrantes',
            'data_hora_inicio', 'data_hora_fim', 'n_vagas',
            'emite_certificado', 'imagem',
        ]
        labels = {
            'titulo': 'Título',
            'descricao': 'Descrição',
            'local': 'Local',
            'data_hora_inicio': 'Início',
            'data_hora_fim': 'Término',
            'n_vagas': 'Vagas',
            'emite_certificado': 'Emite certificado',
            'imagem': 'Imagem',
        }
        widgets = { 
            'titulo': forms.TextInput(attrs={'class': 'form-control',
                'placeholder': 'Ex.: Oficina de fotografia'}),
            'descricao': forms.Textarea(attrs={'class': 'form-control', 'rows': 3,
                'placeholder': 'O que vai acontecer, para quem e o que a pessoa leva de lá.'}),
            'local': forms.TextInput(attrs={'class': 'form-control',
                'placeholder': 'Ex.: Auditório, Sala 12 (vazio = local do evento)'}),
            'data_hora_inicio': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'data_hora_fim': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'n_vagas': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'emite_certificado': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
            'imagem': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }

    def clean(self):
        """Impede término anterior ao início (nada validava isso antes)."""
        dados = super().clean()
        inicio = dados.get('data_hora_inicio')
        fim = dados.get('data_hora_fim')
        if inicio and fim and fim <= inicio:
            self.add_error('data_hora_fim', 'O término precisa ser depois do início.')
        return dados









class TipoAtividadeForm(forms.ModelForm):
    class Meta:
        model = TipoAtividade
        fields = ['nome']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
        } 



class PalestranteForm(forms.ModelForm):
    class Meta:
        model = Participante
        fields = ['first_name', 'last_name','email', 'cpf', 'telefone', 'endereco']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}), 
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'cpf': forms.TextInput(attrs={'class': 'form-control'}),
            'telefone': forms.TextInput(attrs={'class': 'form-control'}),
            'endereco': forms.Textarea(attrs={'class': 'form-control'}), 
        }


# ---------------------------------------------------------------------------
# Cadastro de participante (tela /accounts/signup/) — allauth
# ---------------------------------------------------------------------------

class SignupFormComCpf(AllauthSignupForm):
    """Cadastro pela web: e-mail + senha + CPF.

    O CPF é OBRIGATÓRIO aqui (mas não no modelo: contas de login social/API
    podem não ter documento). A validação usa os dígitos verificadores e
    devolve erro NO CAMPO — o formulário volta para a tela em vez de estourar
    500 no banco (que era o comportamento antigo, quando o CPF nem era pedido).
    """

    cpf = forms.CharField(
        label="CPF",
        required=True,
        max_length=14,  # aceita com ou sem máscara; normalizamos em seguida
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "000.000.000-00",
                "inputmode": "numeric",
                "autocomplete": "off",
                "maxlength": "14",
            }
        ),
        help_text="Somente números.",
    )

    # Ordem de exibição na tela.
    field_order = ["email", "cpf", "password1", "password2"]

    def clean_cpf(self):
        """Valida os dígitos verificadores e devolve o CPF sem máscara."""
        try:
            return validar_cpf(self.cleaned_data.get("cpf"))
        except ValidationError as exc:
            raise forms.ValidationError(exc.messages)

    def save(self, request):
        """Cria a conta pelo allauth e grava o CPF logo depois."""
        user = super().save(request)
        user.cpf = self.cleaned_data["cpf"]
        user.save(update_fields=["cpf"])
        return user
 

