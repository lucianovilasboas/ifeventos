"""Cadastra (ou atualiza) o provedor de login social a partir do ambiente.

Por que existe: o registro do provedor fica no BANCO, não no código. Numa
instalação nova ele não existe, e a página de login depende dele para exibir
o botão do Google. Este comando deixa a configuração reproduzível a partir
do .env, em vez de depender de alguém clicar no admin.

Uso:
    python manage.py configurar_socialapp google
    python manage.py configurar_socialapp google --remover
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Cadastra ou atualiza o provedor de login social a partir das variáveis de ambiente."

    def add_arguments(self, parser):
        parser.add_argument(
            "provider",
            nargs="?",
            default="google",
            help="Provedor do allauth (padrão: google)",
        )
        parser.add_argument(
            "--remover",
            action="store_true",
            help="Remove o provedor em vez de cadastrar",
        )

    def handle(self, *args, **options):
        from allauth.socialaccount.models import SocialApp

        provider = options["provider"]

        if options["remover"]:
            removidos, _ = SocialApp.objects.filter(provider=provider).delete()
            self.stdout.write(
                self.style.WARNING(f"Provedor '{provider}' removido ({removidos} registro(s)).")
            )
            return

        # Cada provedor lê um par de variáveis diferente. Só o Google está
        # previsto hoje no projeto; estender aqui quando surgir outro.
        if provider == "google":
            client_id = (getattr(settings, "GOOGLE_CLIENT_ID", "") or "").strip()
            secret = (getattr(settings, "GOOGLE_CLIENT_SECRET", "") or "").strip()
            nome = "Google"
        else:
            raise CommandError(
                f"Provedor '{provider}' nao previsto. Ajuste o comando para ler as "
                f"credenciais corretas antes de usar."
            )

        if not client_id or not secret:
            raise CommandError(
                f"Credenciais ausentes para '{provider}'. Defina GOOGLE_CLIENT_ID e "
                f"GOOGLE_CLIENT_SECRET no .env."
            )

        app, criado = SocialApp.objects.update_or_create(
            provider=provider,
            defaults={"name": nome, "client_id": client_id, "secret": secret},
        )

        # Com django.contrib.sites instalado, o provedor precisa estar
        # associado a um site para aparecer. Aqui o projeto não usa o app
        # de sites, então o bloco é defensivo.
        try:
            from django.contrib.sites.models import Site

            site = Site.objects.filter(id=getattr(settings, "SITE_ID", 1)).first()
            if site:
                app.sites.add(site)
        except Exception:
            pass

        acao = "criado" if criado else "atualizado"
        self.stdout.write(self.style.SUCCESS(f"Provedor '{provider}' {acao} com sucesso."))
