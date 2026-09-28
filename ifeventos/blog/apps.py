from django.apps import AppConfig


class BlogConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "blog"
    verbose_name = "Blog do evento"

    def ready(self):
        # Conecta os sinais que apagam os arquivos de imagem junto do post/foto
        # (inclusive na exclusão do evento, que não chama delete() dos filhos).
        from . import signals  # noqa: F401
