"""Sinais do blog: apagam o arquivo de imagem quando o registro sai do banco.

Usa `post_delete` (e não `delete()` sobrescrito) porque o sinal dispara também
nas exclusões em cascata — por exemplo, quando o evento é apagado, o Django
remove os posts/fotos em bloco e não passa pelo `delete()` de cada objeto.
"""

from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import FotoPost, PostEvento


def _apagar(campo):
    if campo:
        try:
            campo.delete(save=False)
        except (OSError, ValueError):
            pass


@receiver(post_delete, sender=PostEvento, dispatch_uid="blog_limpar_capa")
def _limpar_capa(sender, instance, **kwargs):
    _apagar(instance.capa)


@receiver(post_delete, sender=FotoPost, dispatch_uid="blog_limpar_foto")
def _limpar_foto(sender, instance, **kwargs):
    _apagar(instance.imagem)
