from django.apps import AppConfig


class EventosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "eventos"

    def ready(self):
        import eventos.signals  # Certifica-se de que os signals são carregados

        # Invalida o cache dos modelos de IA quando o admin salva um contexto.
        from django.db.models.signals import post_save, post_delete

        from . import ia_config
        from .models import ContextoIA

        post_save.connect(ia_config.invalidar_cache, sender=ContextoIA,
                          dispatch_uid="ia_config_save")
        post_delete.connect(ia_config.invalidar_cache, sender=ContextoIA,
                            dispatch_uid="ia_config_delete")