from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.shortcuts import redirect

class CustomAccountAdapter(DefaultAccountAdapter):
    def add_message(self, request, level, message_template, message_context=None, extra_tags=''):
        # Impede que o django-allauth exiba mensagens automáticas
        pass

    def get_email_verification_redirect_url(self, request):
        return "/accounts/email-confirmation/"  # Redireciona para um template customizado


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    """Completa o perfil (nome/avatar) a partir do provedor no cadastro social.

    Roda no auto-cadastro social (conta nova). O caso de conta JÁ existente
    (auto-connect) é coberto pelos signals `social_account_added`/`_updated`.
    """

    def save_user(self, request, sociallogin, form=None):
        user = super().save_user(request, sociallogin, form)
        from . import social

        social.enriquecer_do_google(user, sociallogin)
        return user
