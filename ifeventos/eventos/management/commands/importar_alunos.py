"""Importa a planilha de alunos para a pré-carga (`AlunoRoster`).

Uso:
    python manage.py importar_alunos /caminho/IFMG_PN_ALUNOS.xls

A chave é o e-mail pessoal; rodar de novo atualiza (idempotente). Requer `xlrd`.
As linhas de PNEDOCIN (curso sem opção no sistema) e de CPF inválido são
relatadas e ignoradas.
"""

from django.core.management.base import BaseCommand, CommandError

from eventos import roster


class Command(BaseCommand):
    help = "Importa a planilha (.xls) de alunos para o roster de pré-carga de perfil."

    def add_arguments(self, parser):
        parser.add_argument("arquivo", help="Caminho do arquivo .xls")

    def handle(self, *args, **options):
        caminho = options["arquivo"]
        try:
            relatorio = roster.importar_xls(caminho)
        except FileNotFoundError:
            raise CommandError(f"Arquivo não encontrado: {caminho}")
        except ImportError:
            raise CommandError(
                "Dependência 'xlrd' ausente. Instale com: pip install xlrd==2.0.2"
            )

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
