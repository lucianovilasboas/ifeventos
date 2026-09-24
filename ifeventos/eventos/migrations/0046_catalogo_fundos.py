import os

import django.db.models.deletion
import eventos.models
from django.conf import settings
from django.db import migrations, models


def importar_fundos(apps, schema_editor):
    """Leva cada `layout_fundo` já configurado para o catálogo e vincula.

    Reaproveita o próprio arquivo (mesmo caminho no storage), sem reenviar.
    Fundos repetidos entre configs compartilham a mesma linha do catálogo.
    """
    Config = apps.get_model("eventos", "ConfiguracaoCertificado")
    Fundo = apps.get_model("eventos", "FundoCertificado")

    cache = {}
    for config in Config.objects.all():
        caminho = getattr(config.layout_fundo, "name", "") if config.layout_fundo else ""
        if not caminho:
            continue
        fundo = cache.get(caminho)
        if fundo is None:
            fundo = Fundo.objects.create(
                nome=os.path.basename(caminho), arquivo=caminho
            )
            cache[caminho] = fundo
        config.layout_fundo_novo = fundo
        config.save(update_fields=["layout_fundo_novo"])


class Migration(migrations.Migration):

    dependencies = [
        ("eventos", "0045_catalogo_templates_docx"),
    ]

    operations = [
        migrations.CreateModel(
            name="FundoCertificado",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("nome", models.CharField(max_length=150)),
                (
                    "arquivo",
                    models.ImageField(upload_to=eventos.models.certificado_fundo_upload),
                ),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                (
                    "criado_por",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Fundo de certificado",
                "verbose_name_plural": "Fundos de certificado",
                "ordering": ["-criado_em", "id"],
            },
        ),
        migrations.AddField(
            model_name="configuracaocertificado",
            name="layout_fundo_novo",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="configuracoes",
                to="eventos.fundocertificado",
            ),
        ),
        migrations.RunPython(importar_fundos, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="configuracaocertificado",
            name="layout_fundo",
        ),
        migrations.RenameField(
            model_name="configuracaocertificado",
            old_name="layout_fundo_novo",
            new_name="layout_fundo",
        ),
    ]
