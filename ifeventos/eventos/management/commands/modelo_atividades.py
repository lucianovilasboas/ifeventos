"""Gera um arquivo-modelo para importar a programação de um evento.

Uso:
    python manage.py modelo_atividades                 # exemplo_atividades.csv
    python manage.py modelo_atividades --saida /tmp/m.csv
    python manage.py modelo_atividades --xlsx

O exemplo traz **duas linhas fictícias** no mesmo dia, com um horário que se
sobrepõe de propósito (para você ver o alerta de conflito depois de importar).
"""

import csv
import os

from django.core.management.base import BaseCommand

CABECALHO = [
    "titulo", "descricao", "tipo", "local",
    "inicio", "fim", "n_vagas", "emite_certificado", "palestrantes",
]

LINHAS = [
    {
        "titulo": "Abertura oficial",
        "descricao": "Sessão de abertura do evento.",
        "tipo": "Palestra",
        "local": "Auditório",
        "inicio": "05/10/2026 08:00",
        "fim": "05/10/2026 09:00",
        "n_vagas": "300",
        "emite_certificado": "sim",
        "palestrantes": "",
    },
    {
        "titulo": "Oficina de Robótica",
        "descricao": "Oficina prática, vagas limitadas.",
        "tipo": "Oficina",
        "local": "Laboratório de Informática",
        "inicio": "05/10/2026 08:00",
        "fim": "05/10/2026 10:00",
        "n_vagas": "20",
        "emite_certificado": "sim",
        "palestrantes": "palestrante@example.com",
    },
]


class Command(BaseCommand):
    help = "Gera um arquivo-modelo de programação (csv ou xlsx)."

    def add_arguments(self, parser):
        parser.add_argument("--saida", default="exemplo_atividades.csv")
        parser.add_argument("--xlsx", action="store_true")

    def handle(self, *args, **options):
        saida = options["saida"]
        if options["xlsx"]:
            saida = os.path.splitext(saida)[0] + ".xlsx"
            self._xlsx(saida)
        else:
            saida = os.path.splitext(saida)[0] + ".csv"
            self._csv(saida)
        self.stdout.write(self.style.SUCCESS(f"{len(LINHAS)} linha(s) -> {saida}"))

    @staticmethod
    def _csv(caminho):
        with open(caminho, "w", newline="", encoding="utf-8-sig") as arquivo:
            escritor = csv.DictWriter(arquivo, fieldnames=CABECALHO, delimiter=";")
            escritor.writeheader()
            escritor.writerows(LINHAS)

    @staticmethod
    def _xlsx(caminho):
        from openpyxl import Workbook

        livro = Workbook()
        aba = livro.active
        aba.append(CABECALHO)
        for linha in LINHAS:
            aba.append([linha[c] for c in CABECALHO])
        livro.save(caminho)
