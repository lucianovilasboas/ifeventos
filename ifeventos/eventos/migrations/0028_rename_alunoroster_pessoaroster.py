from django.db import migrations


class Migration(migrations.Migration):
    """Renomeia `AlunoRoster` -> `PessoaRoster` (a tabela agora serve todos os vínculos).

    RenameModel (e não apagar/criar) para PRESERVAR os registros já importados.
    """

    dependencies = [
        ("eventos", "0027_alunoroster_confere_alunoroster_dados_usuario_and_more"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="AlunoRoster",
            new_name="PessoaRoster",
        ),
        migrations.AlterModelOptions(
            name="pessoaroster",
            options={
                "verbose_name": "Pessoa (planilha)",
                "verbose_name_plural": "Pessoas (planilha)",
            },
        ),
    ]
