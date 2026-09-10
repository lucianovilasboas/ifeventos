from django import forms
from eventos.forms import PalestranteForm, TipoAtividadeForm
from eventos.models import Participante
from django.contrib.auth.forms import UserChangeForm
from django.http import JsonResponse
 


class ParticipanteUpdateForm(UserChangeForm):  # Herdando de UserChangeForm para edição de User
    class Meta:
        model = Participante
        fields = [ 'first_name', 'last_name', 'username', 'email', 'cpf', 'telefone', 'endereco', 'foto']

        widgets = { 
            'foto': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'cpf': forms.TextInput(attrs={'class': 'form-control'}),
            'telefone': forms.TextInput(attrs={'class': 'form-control'}),
            'endereco': forms.Textarea(attrs={'class': 'form-control','style': 'max-height: 100px; overflow-y: auto;'}),
        }




    def __init__(self, *args, **kwargs):
        super(ParticipanteUpdateForm, self).__init__(*args, **kwargs)
        # Oculta campos que não devem ser editáveis no formulário
        self.fields['password'].widget = forms.HiddenInput()     



