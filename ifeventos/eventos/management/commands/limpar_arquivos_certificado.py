"""Remove arquivos órfãos de certificado (modelos .docx e imagens de fundo).

Órfão = arquivo em `media/certificados/...` que não é referenciado por nenhum
registro do catálogo. Por padrão só lista (dry-run); use `--confirmar` para
apagar de verdade. Nunca toca em arquivos em uso.
"""

from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand

from eventos.models import FundoCertificado, TemplateCertificadoDocx

# (pasta, modelo do catálogo) — cada pasta guarda só arquivos do seu catálogo.
ALVOS = [
    ("certificados/templates", TemplateCertificadoDocx),
    ("certificados/fundos", FundoCertificado),
]


class Command(BaseCommand):
    help = "Apaga arquivos órfãos de certificado (dry-run por padrão)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirmar",
            action="store_true",
            help="Apaga os arquivos órfãos (sem isso, apenas lista).",
        )

    def handle(self, *args, **options):
        total = 0
        for pasta, modelo in ALVOS:
            referenciados = {
                obj.arquivo.name.rsplit("/", 1)[-1]
                for obj in modelo.objects.all()
                if obj.arquivo
            }
            try:
                _, arquivos = default_storage.listdir(pasta)
            except FileNotFoundError:
                self.stdout.write("Pasta inexistente: " + pasta)
                continue

            orfaos = sorted(
                nome
                for nome in arquivos
                if not nome.startswith(".") and nome not in referenciados
            )
            if not orfaos:
                self.stdout.write(self.style.SUCCESS("Nenhum órfão em " + pasta + "."))
                continue

            for nome in orfaos:
                self.stdout.write("  órfão: " + pasta + "/" + nome)
            self.stdout.write("Total em %s: %d." % (pasta, len(orfaos)))
            total += len(orfaos)

            if options["confirmar"]:
                for nome in orfaos:
                    default_storage.delete(pasta + "/" + nome)
                self.stdout.write(
                    self.style.SUCCESS(
                        "Apagados %d arquivo(s) em %s." % (len(orfaos), pasta)
                    )
                )

        if not options["confirmar"] and total:
            self.stdout.write(
                self.style.WARNING("Dry-run: nada apagado. Use --confirmar.")
            )
