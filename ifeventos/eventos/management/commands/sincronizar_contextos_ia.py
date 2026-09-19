"""Sincroniza a tabela `ContextoIA` com o registro de contextos do código.

Idempotente: cria os contextos novos e atualiza rótulo/grupo/padrão/ordem dos
existentes, **sem** tocar no que o admin escolheu (modelo, temperatura,
max_tokens, ativo). Rodar após deploy que adicione um contexto novo.
"""

from django.core.management.base import BaseCommand

from eventos import ia_config


class Command(BaseCommand):
    help = "Cria/atualiza os contextos de IA (modelos configuráveis no admin)."

    def handle(self, *args, **options):
        resultado = ia_config.sincronizar()
        self.stdout.write(self.style.SUCCESS(
            "Contextos de IA: %(criados)s criado(s), %(atualizados)s atualizado(s) "
            "(total %(total)s)." % resultado
        ))
