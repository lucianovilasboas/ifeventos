from django import forms
from eventos.models import Participante
from django.contrib.auth.forms import UserChangeForm



class ParticipanteUpdateForm(UserChangeForm):  # Herdando de UserChangeForm para edição de User
    class Meta:
        model = Participante
        fields = ['first_name', 'last_name', 'username', 'email', 'cpf', 'telefone', 'endereco']


    def __init__(self, *args, **kwargs):
        super(ParticipanteUpdateForm, self).__init__(*args, **kwargs)
        # Oculta campos que não devem ser editáveis no formulário
        self.fields['password'].widget = forms.HiddenInput()
        # Aplica o padrão visual do Bootstrap aos campos visíveis
        for name, field in self.fields.items():
            if not isinstance(field.widget, forms.HiddenInput):
                css = field.widget.attrs.get('class', '')
                field.widget.attrs['class'] = (css + ' form-control').strip()