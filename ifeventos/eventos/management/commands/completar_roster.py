"""Aplica a planilha de pré-carga (`PessoaRoster`) nas contas que já existem.

Uso:
    python manage.py completar_roster              # aplica em todas as pendentes
    python manage.py completar_roster --dry-run    # só relata
    python manage.py completar_roster --email x@y  # uma pessoa

Serve para o caso em que a planilha foi importada DEPOIS de a conta existir (ou
a conta veio de importação em lote, sem `user_signed_up`): o preenchimento
normal roda no primeiro acesso (`user_signed_up`/`user_logged_in`), mas quem já
tinha conta antes da planilha precisa deste passo uma vez. Usa o MESMO
`roster.completar_do_roster` — respeita a prioridade do que a pessoa já informou
e não reaplica linha já usada.
"""

from django.core.management.base import BaseCommand

from eventos import roster
from eventos.models import Participante, PessoaRoster


class Command(BaseCommand):
    help = (
        "Aplica a planilha (PessoaRoster) nas contas existentes ainda não "
        "completadas (usado_em nulo)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--email", default=None, help="Aplica só a este e-mail."
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="Só relata; não altera nada."
        )

    def handle(self, *args, **options):
        dry = options["dry_run"]
        alvo = (options.get("email") or "").strip().lower()

        pendentes = PessoaRoster.objects.filter(usado_em__isnull=True).order_by("email")
        if alvo:
            pendentes = pendentes.filter(email=alvo)

        aplicados = sem_conta = 0
        for linha in pendentes:
            conta = Participante.objects.filter(email__iexact=linha.email).first()
            if conta is None:
                sem_conta += 1
                continue
            if dry:
                self.stdout.write(f"[dry-run] {linha.email}: aplicaria")
                aplicados += 1
                continue
            if roster.completar_do_roster(conta):
                self.stdout.write(self.style.SUCCESS(f"ok {linha.email}"))
                aplicados += 1

        self.stdout.write(
            f"aplicados={aplicados} sem_conta={sem_conta} dry_run={dry}"
        )
