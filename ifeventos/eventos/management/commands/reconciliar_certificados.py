"""Reconcilia `Inscricao.certificado_emitido` com a tabela `Certificado`.

A fonte de verdade de "certificado emitido" é a tabela `Certificado`; a flag
`Inscricao.certificado_emitido` é apenas um cache mantido em sincronia na
emissão. Emissões antigas (ou a antiga ação em lote do admin) deixaram a flag
defasada, o que fazia a tela mostrar "Sem certificado" para quem já tinha.

Sincroniza nos DOIS sentidos: liga onde existe `Certificado` e desliga onde não
existe. Por padrão só lista (dry-run); use `--confirmar` para gravar.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from eventos.models import Certificado, Inscricao


class Command(BaseCommand):
    help = (
        "Sincroniza Inscricao.certificado_emitido com a tabela Certificado "
        "(dry-run por padrão)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirmar",
            action="store_true",
            help="Grava as correções (sem isso, apenas lista).",
        )

    def handle(self, *args, **options):
        # Só certificados de ATIVIDADE têm inscrição correspondente.
        emitidos = set(
            Certificado.objects.filter(atividade__isnull=False).values_list(
                "participante_id", "atividade_id"
            )
        )

        ligar, desligar = [], []
        for inscricao in Inscricao.objects.only(
            "id", "participante_id", "atividade_id", "certificado_emitido"
        ).iterator():
            deve = (inscricao.participante_id, inscricao.atividade_id) in emitidos
            if deve and not inscricao.certificado_emitido:
                ligar.append(inscricao.id)
            elif not deve and inscricao.certificado_emitido:
                desligar.append(inscricao.id)

        self.stdout.write(
            "Inscrições a LIGAR (têm certificado, flag off): %d" % len(ligar)
        )
        self.stdout.write(
            "Inscrições a DESLIGAR (sem certificado, flag on): %d" % len(desligar)
        )

        if not options["confirmar"]:
            self.stdout.write(
                self.style.WARNING("Dry-run: nada gravado. Use --confirmar.")
            )
            return

        with transaction.atomic():
            if ligar:
                Inscricao.objects.filter(id__in=ligar).update(certificado_emitido=True)
            if desligar:
                Inscricao.objects.filter(id__in=desligar).update(certificado_emitido=False)

        self.stdout.write(
            self.style.SUCCESS(
                "Reconciliado: %d ligada(s), %d desligada(s)."
                % (len(ligar), len(desligar))
            )
        )
