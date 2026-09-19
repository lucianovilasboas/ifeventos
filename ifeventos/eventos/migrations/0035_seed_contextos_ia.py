"""Semeia os contextos de IA a partir do registro em `eventos/ia_config.py`.

Idempotente. Novos contextos que o código ganhar depois entram pelo comando
`sincronizar_contextos_ia` (o deploy roda as migrations, não o comando).
"""

from django.db import migrations


def semear(apps, schema_editor):
    from eventos.ia_config import CONTEXTOS

    ContextoIA = apps.get_model("eventos", "ContextoIA")
    for item in CONTEXTOS:
        ContextoIA.objects.update_or_create(
            chave=item["chave"],
            defaults={
                "rotulo": item["rotulo"],
                "grupo": item["grupo"],
                "tipo_padrao": item["tipo_padrao"],
                "ordem": item["ordem"],
            },
        )


def reverter(apps, schema_editor):
    ContextoIA = apps.get_model("eventos", "ContextoIA")
    ContextoIA.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [("eventos", "0034_contextoia")]

    operations = [migrations.RunPython(semear, reverter)]
