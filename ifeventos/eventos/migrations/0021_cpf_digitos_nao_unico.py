"""CPF: normaliza para 11 dígitos e deixa de ser único.

Motivo (bug de 12/09/2026): o cadastro web não coletava CPF, então o campo era
gravado como "". Como `cpf` era `unique=True`, o PRIMEIRO cadastro ocupava o
valor vazio e TODOS os seguintes estouravam
`UniqueViolation: eventos_participante_cpf_key` -> HTTP 500.

A identidade da conta passa a ser o E-MAIL (que já é `unique=True` e é o
`USERNAME_FIELD`); um mesmo CPF pode estar associado a mais de um e-mail.
"""

import re

from django.db import migrations, models


def normalizar_cpfs(apps, schema_editor):
    """Guarda apenas os dígitos (remove máscara). Idempotente."""
    Participante = apps.get_model("eventos", "Participante")
    for p in Participante.objects.all().only("id", "cpf"):
        atual = p.cpf or ""
        novo = re.sub(r"\D", "", atual)
        if novo != atual:
            p.cpf = novo
            p.save(update_fields=["cpf"])


class Migration(migrations.Migration):

    dependencies = [
        ("eventos", "0020_alter_presenca_origem"),
    ]

    operations = [
        # 1) Normaliza os dados ANTES de reduzir o tamanho do campo.
        migrations.RunPython(normalizar_cpfs, migrations.RunPython.noop),
        # 2) Remove o unique (e o índice único) e ajusta para 11 dígitos.
        migrations.AlterField(
            model_name="participante",
            name="cpf",
            field=models.CharField(blank=False, db_index=True, default="", max_length=11),
        ),
    ]
