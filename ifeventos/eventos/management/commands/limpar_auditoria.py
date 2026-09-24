"""Retenção da trilha de auditoria: remove registros mais antigos que N dias."""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from eventos.models import RegistroAuditoria


class Command(BaseCommand):
    help = "Apaga registros de auditoria mais antigos que N dias (dry-run por padrão)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dias", type=int, default=90,
            help="Idade mínima (em dias) para remover. Padrão: 90.",
        )
        parser.add_argument(
            "--confirmar", action="store_true",
            help="Apaga de verdade (sem isso, apenas mostra quantos seriam removidos).",
        )

    def handle(self, *args, **options):
        dias = max(1, options["dias"])
        corte = timezone.now() - timedelta(days=dias)
        qs = RegistroAuditoria.objects.filter(criado_em__lt=corte)
        total = qs.count()

        if not total:
            self.stdout.write(
                self.style.SUCCESS("Nada a remover (corte em %s)." % corte.date())
            )
            return

        self.stdout.write(
            "A remover %d registro(s) anteriores a %s." % (total, corte.date())
        )
        if not options["confirmar"]:
            self.stdout.write(
                self.style.WARNING("Dry-run: nada apagado. Use --confirmar.")
            )
            return

        removidos, _ = qs.delete()
        self.stdout.write(self.style.SUCCESS("Removidos %d registro(s)." % removidos))
