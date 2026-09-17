"""Atualiza o `local` das atividades quando um espaço do catálogo é renomeado.

Uso:
    python manage.py sincronizar_locais --de "Auditório" --para "Auditório Nobre"
    python manage.py sincronizar_locais --de "Auditório" --para "Auditório Nobre" --aplicar
    python manage.py sincronizar_locais --de "Sala" --para "Sala 12" --evento 107 --aplicar

Por que existe: `Atividade.local` é TEXTO — copiado no momento em que a
atividade foi criada (ou proposta), não é uma FK para o espaço. Então renomear
o espaço no catálogo não alcança o que já está gravado, e a agenda passaria a
tratar o lugar antigo e o novo como dois lugares diferentes.

O comando reescreve só o pedaço que casa: o campo aceita vários locais
separados por vírgula, a comparação ignora acento/caixa e um pedaço que hoje
é apelido do nome antigo (`AGENDA_ALIASES_LOCAL`) também é atualizado.
Sem `--aplicar` é só simulação — nada é gravado.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from eventos.models import Atividade, sem_acento


class Command(BaseCommand):
    help = "Reescreve o `local` das atividades quando um espaço é renomeado."

    def add_arguments(self, parser):
        parser.add_argument("--de", required=True, help="Nome atual (antigo) do espaço")
        parser.add_argument("--para", required=True, help="Novo nome do espaço")
        parser.add_argument("--evento", type=int, help="Limita a um evento (id)")
        parser.add_argument(
            "--aplicar",
            action="store_true",
            help="Grava as mudanças (sem isto, só mostra o que seria feito).",
        )

    def handle(self, *args, **options):
        de = " ".join((options["de"] or "").split())
        para = " ".join((options["para"] or "").split())
        if not de or not para:
            raise CommandError("Informe --de e --para.")
        if sem_acento(de) == sem_acento(para):
            raise CommandError("Os nomes são iguais (ignorando acento e caixa).")

        aliases = getattr(settings, "AGENDA_ALIASES_LOCAL", None) or {}
        alvo = sem_acento(de)
        aplicar = options["aplicar"]

        atividades = Atividade.objects.exclude(local="").only("id", "titulo", "local")
        if options.get("evento"):
            atividades = atividades.filter(evento_id=options["evento"])

        alteradas, ocorrencias, amostra = 0, 0, []
        for atividade in atividades.order_by("id"):
            pedacos, vistos, mudou = [], set(), False
            for pedaco in (atividade.local or "").split(","):
                pedaco = pedaco.strip()
                if not pedaco:
                    continue
                if sem_acento(aliases.get(pedaco, pedaco)) == alvo:
                    pedaco = para
                    mudou = True
                    ocorrencias += 1
                chave = sem_acento(pedaco)
                if chave not in vistos:
                    vistos.add(chave)
                    pedacos.append(pedaco)

            if not mudou:
                continue

            alteradas += 1
            if len(amostra) < 5:
                amostra.append(
                    f"  {atividade.titulo}: {atividade.local} -> {', '.join(pedacos)}"
                )
            if aplicar:
                atividade.local = ", ".join(pedacos)
                atividade.save(update_fields=["local"])

        verbo = "atualizada(s)" if aplicar else "seria(m) atualizada(s) — use --aplicar"
        self.stdout.write(
            self.style.SUCCESS(
                f"{alteradas} atividade(s) {verbo}; "
                f"{ocorrencias} ocorrência(s) de '{de}' -> '{para}'."
            )
        )
        for linha in amostra:
            self.stdout.write(linha)
        if not alteradas:
            self.stdout.write("Nada a fazer.")

        apelidos = [
            apelido for apelido, destino in aliases.items()
            if sem_acento(destino) == alvo
        ]
        if apelidos:
            self.stdout.write(
                self.style.WARNING(
                    "Atenção: AGENDA_ALIASES_LOCAL ainda aponta "
                    + ", ".join(f"'{apelido}'" for apelido in apelidos)
                    + f" para '{de}' — atualize o setting para o nome novo."
                )
            )
