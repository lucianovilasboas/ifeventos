"""Tags de template para o login social.

Motivo: a tag `provider_login_url` do allauth levanta
`SocialApp.DoesNotExist` quando o provedor (ex.: Google) ainda não foi
cadastrado no banco. Isso derrubava a página de login inteira com erro 500
— inclusive numa instalação nova, antes de configurar o provedor.

A tag abaixo faz a mesma coisa, mas devolve string vazia em vez de estourar.
Assim o botão do provedor simplesmente não aparece enquanto ele não estiver
configurado, e o login por e-mail continua funcionando normalmente.
"""

from django import template
from allauth.socialaccount.templatetags.socialaccount import provider_login_url as _provider_login_url

register = template.Library()


@register.simple_tag(takes_context=True)
def provider_login_url_seguro(context, provider, **kwargs):
    """Devolve a URL de login do provedor, ou "" se ele não estiver configurado.

    Uso no template:
        {% provider_login_url_seguro 'google' as google_url %}
        {% if google_url %}<a href="{{ google_url }}">...</a>{% endif %}
    """
    try:
        return _provider_login_url(context, provider, **kwargs)
    except Exception:
        # Provedor não cadastrado (SocialApp ausente) ou mal configurado:
        # o botão não é exibido, mas a página continua funcionando.
        return ""
