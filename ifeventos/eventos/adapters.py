from allauth.account.adapter import DefaultAccountAdapter
from django.shortcuts import redirect

class CustomAccountAdapter(DefaultAccountAdapter):
    def add_message(self, request, level, message_template, message_context=None, extra_tags=''):
        # Impede que o django-allauth exiba mensagens automáticas
        pass

    def get_email_verification_redirect_url(self, request):
        return "/accounts/email-confirmation/"  # Redireciona para um template customizado
