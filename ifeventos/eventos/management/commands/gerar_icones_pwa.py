"""Gera os icones do PWA a partir da marca (verde institucional + "NE").

Por que existe: o repositorio nao versiona nenhum logo/icone, e o PWA precisa
de PNGs em tamanhos fixos (192, 512, maskable, apple-touch e favicon). Gerar
por comando deixa a marca reproduzivel: mudar a cor ou o texto aqui regenera
tudo, sem depender de arquivo de design externo.

Uso:
    python manage.py gerar_icones_pwa
    python manage.py gerar_icones_pwa --saida static/img/pwa

Observacao: o desenho vive em `eventos.pwa_icons` (so depende de Pillow). Se a
imagem do conteiner nao tiver uma fonte bold instalada, gere os PNGs no host e
versione-os; o comando continua servindo para reproduzir a marca.
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from eventos.pwa_icons import FonteAusente, gerar


class Command(BaseCommand):
    help = "Gera os icones do PWA (192, 512, maskable, apple-touch e favicon)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--saida",
            default="static/img/pwa",
            help="Pasta de destino, relativa a BASE_DIR (padrao: static/img/pwa).",
        )

    def handle(self, *args, **options):
        destino = Path(settings.BASE_DIR) / options["saida"]
        try:
            gerar(destino)
        except FonteAusente as erro:
            raise CommandError(str(erro))
        self.stdout.write(
            self.style.SUCCESS(
                f"Icones gerados em {destino.relative_to(settings.BASE_DIR)}"
            )
        )
