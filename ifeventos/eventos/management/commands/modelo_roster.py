"""Gera um arquivo-modelo da pré-carga, com uma linha de exemplo por vínculo.

Uso:
    python manage.py modelo_roster                 # grava exemplo_roster.csv
    python manage.py modelo_roster --saida /tmp/m.csv
    python manage.py modelo_roster --xlsx          # gera .xlsx

As colunas saem de `settings.METADADOS_PARTICIPANTE`, então o modelo acompanha
o schema da escola automaticamente. Os dados são FICTÍCIOS (e-mails em
example.com e CPFs de teste) — não são pessoas reais.
"""

import csv
import os

from django.core.management.base import BaseCommand

from eventos import metadados, roster

# CPFs apenas VÁLIDOS para o modelo (não pertencem a ninguém).
CPFS_EXEMPLO = [
    "12345678909",
    "52998224725",
    "11144477735",
    "39053344705",
    "16899535009",
]


def linha_exemplo(vinculo, indice):
    """Uma linha preenchida com valores válidos para o vínculo informado."""
    valores = {"vinculo": vinculo}
    for campo in metadados.campos():
        chave = campo["chave"]
        if chave == "vinculo" or not metadados.visivel(campo, valores):
            continue
        pai = valores.get(campo["depende_de"]) if campo["depende_de"] else None
        opcoes = metadados.opcoes_do_campo(campo, pai)
        if opcoes:
            valores[chave] = opcoes[0]
        elif campo["tipo"] == "numero":
            valores[chave] = "123"
        else:
            valores[chave] = f"«{campo['rotulo']}»"

    local = roster._chave(vinculo).replace(" ", "")
    linha = {
        "email": f"{local}{indice}@example.com",
        "nome": f"Exemplo {vinculo}",
        "cpf": CPFS_EXEMPLO[indice % len(CPFS_EXEMPLO)],
    }
    for campo in metadados.campos():
        linha[campo["chave"]] = valores.get(campo["chave"], "")
    return linha


class Command(BaseCommand):
    help = "Gera um arquivo-modelo para a pré-carga (uma linha por vínculo)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--saida", default="exemplo_roster.csv", help="Caminho de saída."
        )
        parser.add_argument(
            "--xlsx", action="store_true", help="Gera .xlsx em vez de .csv."
        )

    def handle(self, *args, **options):
        vinculo = next(c for c in metadados.campos() if c["chave"] == "vinculo")
        vinculos = list(vinculo["opcoes"])
        cabecalho = roster.cabecalhos()
        linhas = [linha_exemplo(v, i + 1) for i, v in enumerate(vinculos)]

        saida = options["saida"]
        if options["xlsx"]:
            saida = os.path.splitext(saida)[0] + ".xlsx"
            self._xlsx(saida, cabecalho, linhas)
        else:
            saida = os.path.splitext(saida)[0] + ".csv"
            self._csv(saida, cabecalho, linhas)

        self.stdout.write(
            self.style.SUCCESS(
                f"{len(linhas)} linha(s) de exemplo "
                f"({', '.join(vinculos)}) -> {saida}"
            )
        )

    @staticmethod
    def _csv(caminho, cabecalho, linhas):
        # `;` é o separador que o Excel em pt-BR espera por padrão.
        with open(caminho, "w", newline="", encoding="utf-8-sig") as arquivo:
            escritor = csv.DictWriter(arquivo, fieldnames=cabecalho, delimiter=";")
            escritor.writeheader()
            escritor.writerows(linhas)

    @staticmethod
    def _xlsx(caminho, cabecalho, linhas):
        from openpyxl import Workbook

        livro = Workbook()
        aba = livro.active
        aba.append(cabecalho)
        for linha in linhas:
            aba.append([linha[c] for c in cabecalho])
        livro.save(caminho)
