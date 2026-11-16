"""Worker da fila de comunicados por e-mail.

Reivindica e processa `ComunicadoJob` pendentes, um por vez, em lotes — o mesmo
desenho do worker de certificados. Por padrão fica em loop (sobe junto do
uvicorn no `entrypoint.sh`); `--once` processa o que houver e sai.
"""

import time

from django.core.management.base import BaseCommand
from django.db import connection

from eventos import comunicados


class Command(BaseCommand):
    help = "Processa a fila de comunicados por e-mail (worker)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--once", action="store_true", help="Processa o que houver e sai."
        )
        parser.add_argument(
            "--intervalo", type=int, default=3,
            help="Segundos entre checagens no loop.",
        )

    def handle(self, *args, **options):
        # Jobs presos (worker anterior caiu) voltam para a fila.
        comunicados.reciclar_presos()

        if options["once"]:
            while comunicados.processar_proximo_job() is not None:
                connection.close()
            return

        self.stdout.write("Worker de comunicados iniciado.")
        intervalo = max(1, options["intervalo"])
        while True:
            job = comunicados.processar_proximo_job()
            connection.close()  # processo longo: não segura conexão entre jobs
            if job is None:
                time.sleep(intervalo)
