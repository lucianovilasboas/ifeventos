"""Importa o arquivo de pré-carga (planilha) — todos os vínculos num arquivo só.

Uso:
    python manage.py importar_roster /caminho/arquivo.csv    # ou .xls / .xlsx

Colunas: `email`, `nome`, `cpf` + as chaves de `settings.METADADOS_PARTICIPANTE`
(vinculo, matricula, curso, turma, ano, funcao, siape…). A chave é o e-mail;
rodar de novo atualiza (idempotente). Gere um modelo com `modelo_roster`.
"""

from django.core.management.base import BaseCommand, CommandError

from eventos import roster


class Command(BaseCommand):
    help = "Importa o arquivo (csv/xls/xlsx) de pré-carga para PessoaRoster."

    def add_arguments(self, parser):
        parser.add_argument("arquivo", help="Caminho do arquivo (.csv, .xls ou .xlsx)")

    def handle(self, *args, **options):
        caminho = options["arquivo"]
        if caminho.lower().endswith(".xls"):
            try:
                import xlrd  # noqa: F401
            except ImportError:
                raise CommandError(
                    "Para importar .xls é preciso o pacote 'xlrd' (pip install xlrd==2.0.2)."
                )
        try:
            relatorio = roster.importar_arquivo(caminho)
        except FileNotFoundError:
            raise CommandError(f"Arquivo não encontrado: {caminho}")
        except ValueError as exc:
            raise CommandError(str(exc))

        self.stdout.write(
            self.style.SUCCESS(
                "total={total} importados={importados} atualizados={atualizados} "
                "ignorados={ignorados} erros={erros}".format(**relatorio)
            )
        )
        for item in relatorio["linhas"]:
            if item["status"] in ("ignorados", "erros"):
                self.stdout.write(
                    f"  [{item['status']}] linha {item['indice']} "
                    f"{item['email']}: {item['motivo']}"
                )
            for aviso in item["avisos"]:
                self.stdout.write(
                    f"  [aviso] linha {item['indice']} {item['email']}: {aviso}"
                )
