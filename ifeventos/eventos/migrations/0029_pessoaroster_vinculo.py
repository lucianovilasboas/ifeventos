from django.db import migrations, models


def copiar_vinculo(apps, schema_editor):
    """Preenche a nova coluna `vinculo` a partir do `dados` já existente."""
    PessoaRoster = apps.get_model("eventos", "PessoaRoster")
    for linha in PessoaRoster.objects.all().iterator():
        vinculo = str((linha.dados or {}).get("vinculo", "") or "").strip()[:50]
        if vinculo:
            PessoaRoster.objects.filter(pk=linha.pk).update(vinculo=vinculo)


class Migration(migrations.Migration):
    dependencies = [
        ("eventos", "0028_rename_alunoroster_pessoaroster"),
    ]

    operations = [
        migrations.AddField(
            model_name="pessoaroster",
            name="vinculo",
            field=models.CharField(
                blank=True, db_index=True, default="", max_length=50
            ),
        ),
        migrations.RunPython(copiar_vinculo, migrations.RunPython.noop),
    ]
