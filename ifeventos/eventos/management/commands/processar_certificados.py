"""Worker de emissão assíncrona de certificados.

Reivindica e processa `CertificadoJob` pendentes, um por vez. Por padrão fica em
loop (sobe junto do uvicorn no `entrypoint.sh`); `--once` processa o que houver e
sai.
"""

import time

from django.core.management.base import BaseCommand
from django.db import connection

from eventos import emissao_certificados


class Command(BaseCommand):
    help = "Processa a fila de emissão de certificados (worker)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--once", action="store_true", help="Processa o que houver e sai."
        )
        parser.add_argument(
            "--intervalo", type=int, default=2, help="Segundos entre checagens no loop."
        )

    def handle(self, *args, **options):
        # Jobs presos (worker anterior caiu) voltam para a fila.
        emissao_certificados.reciclar_presos()

        if options["once"]:
            while emissao_certificados.processar_proximo_job() is not None:
                connection.close()
            return

        self.stdout.write("Worker de certificados iniciado.")
        intervalo = max(1, options["intervalo"])
        while True:
            job = emissao_certificados.processar_proximo_job()
            connection.close()  # processo longo: não segura conexão entre jobs
            if job is None:
                time.sleep(intervalo)
