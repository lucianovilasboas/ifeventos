"""Migra as configurações de certificado do modo antigo `fundo` para `texto`.

O layout deixou de ter três opções: agora são duas (Texto livre com imagem de
fundo opcional, e Modelo .docx). Quem estava em `fundo` passa a `texto` — a
imagem de fundo continua salva em `layout_fundo` e segue sendo usada.
"""

from django.db import migrations


def fundo_para_texto(apps, schema_editor):
    ConfiguracaoCertificado = apps.get_model("eventos", "ConfiguracaoCertificado")
    ConfiguracaoCertificado.objects.filter(modo_layout="fundo").update(
        modo_layout="texto"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("eventos", "0043_alter_configuracaocertificado_modo_layout"),
    ]

    operations = [
        migrations.RunPython(fundo_para_texto, migrations.RunPython.noop),
    ]
