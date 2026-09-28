from django.contrib import admin
from django.utils import timezone

from eventos.admin import miniatura

from .models import FotoPost, PostEvento


class FotoPostInline(admin.TabularInline):
    model = FotoPost
    extra = 0
    fields = ("imagem", "legenda", "ordem", "preview")
    readonly_fields = ("preview",)

    def preview(self, obj):
        return miniatura(obj.imagem, 80, 60) if obj else "—"

    preview.short_description = "Prévia"


@admin.register(PostEvento)
class PostEventoAdmin(admin.ModelAdmin):
    list_display = (
        "titulo", "evento", "autor_nome", "situacao", "fixado",
        "publicado_em", "criado_em",
    )
    list_filter = ("situacao", "fixado", "evento")
    search_fields = ("titulo", "resumo", "corpo", "autor_nome")
    date_hierarchy = "criado_em"
    inlines = [FotoPostInline]
    readonly_fields = ("capa_preview", "autor_nome", "publicado_em", "criado_em", "atualizado_em")
    actions = ("aprovar", "ocultar")

    def capa_preview(self, obj):
        return miniatura(obj.capa, 120, 90)

    capa_preview.short_description = "Capa"

    @admin.action(description="Publicar posts selecionados")
    def aprovar(self, request, queryset):
        for post in queryset:
            campos = {
                "situacao": PostEvento.SIT_PUBLICADO,
                "atualizado_em": timezone.now(),
            }
            if not post.publicado_em:
                campos["publicado_em"] = timezone.now()
            PostEvento.objects.filter(pk=post.pk).update(**campos)

    @admin.action(description="Ocultar posts selecionados")
    def ocultar(self, request, queryset):
        queryset.update(
            situacao=PostEvento.SIT_OCULTO, atualizado_em=timezone.now()
        )
