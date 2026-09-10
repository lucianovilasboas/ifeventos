from django import forms
from .models import Evento, Participante, TipoAtividade
from .models import Atividade
from django.core.exceptions import ValidationError
from django.urls import reverse_lazy
from django.utils.safestring import mark_safe


# -- Formulário para criação de evento --

class EventoForm(forms.ModelForm):
    class Meta:
        model = Evento
        fields = ['title', 'description', 'data_inicio', 'data_fim', 'local', 'imagem']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control','style': 'max-height: 100px; overflow-y: auto;'}),
            'data_inicio': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
            'data_fim': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
            'local': forms.TextInput(attrs={'class': 'form-control'}),
            'organizador': forms.Select(attrs={'class': 'form-control'}),
            'imagem': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }


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
    
    tipo = forms.ModelChoiceField(
        queryset=TipoAtividade.objects.all(),
        widget=forms.Select(attrs={'class': 'form-control'}),
        required=True
    )
    
    palestrantes = forms.ModelMultipleChoiceField(
        queryset=Participante.objects.filter(is_palestrante=True),
        widget=forms.SelectMultiple(attrs={'class': 'form-control'}),
        required=True
    )

    class Meta:
        model = Atividade
        fields = ['evento','titulo', 'descricao', 'tipo', 'palestrantes', 'data_hora_inicio', 'data_hora_fim', 'n_vagas', 'n_inscricoes', 'imagem']
        widgets = { 
            'evento': forms.Select(attrs={'class': 'form-control'}),
            'titulo': forms.TextInput(attrs={'class': 'form-control'}),
            'descricao': forms.Textarea(attrs={'class': 'form-control','style': 'max-height: 100px; overflow-y: auto;'}),
            'tipo': forms.Select(attrs={'class': 'form-control'}),
            'palestrantes': forms.SelectMultiple(attrs={'class': 'form-control'}),
            'data_hora_inicio': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'data_hora_fim': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'n_vagas': forms.NumberInput(attrs={'class': 'form-control'}),
            'n_inscricoes': forms.NumberInput(attrs={'class': 'form-control'}),
            'imagem': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Adicionando links de criação para novos palestrantes e tipos de atividades
        add_palestrante_url = reverse_lazy('organizador:adicionar_palestrante')  # Substitua pelo nome correto da URL
        add_tipo_url = reverse_lazy('organizador:adicionar_tipo_atividade')  # Substitua pelo nome correto da URL

        self.fields['tipo'].widget.attrs['data-add-url'] = add_tipo_url
        self.fields['palestrantes'].widget.attrs['data-add-url'] = add_palestrante_url

        # Adicionando os botões HTML diretamente no formulário
        self.fields['tipo'].label = mark_safe(f'Tipo de Atividade <a href="{add_tipo_url}" class="btn btn-primary" data-bs-toggle="modal" data-bs-target="#modalTipoAtividade" style="margin: 2px; padding: 6px;" > <i class="fas fa-plus"></i></a>')
        self.fields['palestrantes'].label = mark_safe(f'Palestrantes <a href="{add_palestrante_url}"  class="btn btn-success" data-bs-toggle="modal" data-bs-target="#modalPalestrante" style="margin: 2px; padding: 6px;"> <i class="fas fa-plus"></i></a>')










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
 

