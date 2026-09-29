from django.contrib import admin
from django.utils import timezone

from eventos import auditoria
from eventos.admin import miniatura
from eventos.models import RegistroAuditoria

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
            auditoria.registrar(
                acao=RegistroAuditoria.ACAO_EDITAR,
                objeto=post,
                evento=post.evento,
                usuario=request.user,
                resumo=f"Publicou o post “{post.titulo}” pelo admin",
                detalhes={"moderacao": "aprovar", "origem": "admin"},
                request=request,
            )

    @admin.action(description="Ocultar posts selecionados")
    def ocultar(self, request, queryset):
        for post in queryset:
            PostEvento.objects.filter(pk=post.pk).update(
                situacao=PostEvento.SIT_OCULTO, atualizado_em=timezone.now()
            )
            auditoria.registrar(
                acao=RegistroAuditoria.ACAO_EDITAR,
                objeto=post,
                evento=post.evento,
                usuario=request.user,
                resumo=f"Ocultou o post “{post.titulo}” pelo admin",
                detalhes={"moderacao": "ocultar", "origem": "admin"},
                request=request,
            )
