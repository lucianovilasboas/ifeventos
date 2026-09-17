"""Apaga uma chave de metadado já gravada (ex.: campo que saiu do schema).

Uso:
    python manage.py limpar_metadado siape            # só mostra o que mudaria
    python manage.py limpar_metadado siape --aplicar  # grava

Varre os três lugares onde o valor pode ficar: `ParticipanteMetadados.dados`,
`PessoaRoster.dados` e o snapshot `PessoaRoster.dados_usuario["metadados"]`.
Serve para quando um campo é removido de `settings.METADADOS_PARTICIPANTE` e o
valor antigo continuaria inerte no JSON (e visível na API, que devolve o dict).
"""

from django.core.management.base import BaseCommand, CommandError

from eventos.models import ParticipanteMetadados, PessoaRoster


def _sem_chave(dados, chave):
    """Cópia do dict sem a chave, ou `None` se ela não está lá."""
    if not isinstance(dados, dict) or chave not in dados:
        return None
    novo = dict(dados)
    del novo[chave]
    return novo


class Command(BaseCommand):
    help = "Remove uma chave de metadado dos participantes e do roster."

    def add_arguments(self, parser):
        parser.add_argument("chave", help="Chave do metadado (ex.: siape)")
        parser.add_argument(
            "--aplicar",
            action="store_true",
            help="Grava a remoção (sem isto, só mostra o que seria afetado).",
        )

    def handle(self, *args, **options):
        chave = (options["chave"] or "").strip()
        if not chave:
            raise CommandError("Informe a chave do metadado.")
        aplicar = options["aplicar"]

        participantes = self._limpar_participantes(chave, aplicar)
        linhas, snapshots = self._limpar_roster(chave, aplicar)

        verbo = "removida" if aplicar else "seria removida (use --aplicar)"
        self.stdout.write(
            self.style.SUCCESS(
                f"Chave '{chave}' {verbo}: {participantes} participante(s), "
                f"{linhas} linha(s) do roster, {snapshots} snapshot(s)."
            )
        )

    def _limpar_participantes(self, chave, aplicar):
        total = 0
        for obj in ParticipanteMetadados.objects.all().iterator():
            novo = _sem_chave(obj.dados, chave)
            if novo is None:
                continue
            total += 1
            if aplicar:
                obj.dados = novo
                obj.save(update_fields=["dados"])
        return total

    def _limpar_roster(self, chave, aplicar):
        linhas = snapshots = 0
        for obj in PessoaRoster.objects.all().iterator():
            campos = []

            novo_dados = _sem_chave(obj.dados, chave)
            if novo_dados is not None:
                linhas += 1
                if aplicar:
                    obj.dados = novo_dados
                    campos.append("dados")

            usuario = obj.dados_usuario if isinstance(obj.dados_usuario, dict) else {}
            novo_meta = _sem_chave(usuario.get("metadados"), chave)
            if novo_meta is not None:
                snapshots += 1
                if aplicar:
                    obj.dados_usuario = {**usuario, "metadados": novo_meta}
                    campos.append("dados_usuario")

            if aplicar and campos:
                obj.save(update_fields=campos)
        return linhas, snapshots
