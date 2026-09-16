"""Importa a programação de um evento a partir de CSV/XLS/XLSX.

Uso:
    python manage.py importar_atividades <evento_id> /caminho/arquivo.csv

Colunas: `titulo, descricao, tipo, local, inicio, fim, n_vagas,
emite_certificado, palestrantes`. A chave de idempotência é título + início
(rodar de novo atualiza). Gere um modelo com `modelo_atividades`.
"""

from django.core.management.base import BaseCommand, CommandError

from eventos import importacao_programacao
from eventos.models import Evento


class Command(BaseCommand):
    help = "Importa as atividades (programação) de um evento."

    def add_arguments(self, parser):
        parser.add_argument("evento_id", type=int, help="ID do evento")
        parser.add_argument("arquivo", help="Caminho do arquivo (.csv, .xls ou .xlsx)")

    def handle(self, *args, **options):
        evento = Evento.objects.filter(id=options["evento_id"]).first()
        if evento is None:
            raise CommandError(f"Evento {options['evento_id']} não encontrado.")

        try:
            relatorio = importacao_programacao.importar_arquivo(evento, options["arquivo"])
        except FileNotFoundError:
            raise CommandError(f"Arquivo não encontrado: {options['arquivo']}")
        except ValueError as exc:
            raise CommandError(str(exc))

        self.stdout.write(
            self.style.SUCCESS(
                f"evento={evento.id} total={relatorio['total']} criadas={relatorio['criadas']} "
                f"atualizadas={relatorio['atualizadas']} erros={relatorio['erros']}"
            )
        )
        for item in relatorio["linhas"]:
            if item["status"] == "erros":
                self.stdout.write(
                    f"  [erro] linha {item['indice']} {item['titulo']}: {item['motivo']}"
                )
            for aviso in item["avisos"]:
                self.stdout.write(
                    f"  [aviso] linha {item['indice']} {item['titulo']}: {aviso}"
                )
