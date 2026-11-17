"""Painel do organizador: evento em destaque, outros eventos e passados."""

from datetime import date, datetime, timedelta, timezone as tz

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from eventos.models import Atividade, Evento, TipoAtividade

U = get_user_model()
SENHA = "SenhaForte123!"


class PainelEventoPadraoTests(TestCase):
    def setUp(self):
        hoje = date.today()
        self.org = U.objects.create_user(
            email="org_painel@example.com", password=SENHA, cpf="12345678909",
            is_organizador=True,
        )
        self.outro_org = U.objects.create_user(
            email="org_alheio@example.com", password=SENHA, cpf="98765432100",
            is_organizador=True,
        )
        self.tipo = TipoAtividade.objects.create(nome="Painel organizador")

        def evento(titulo, inicio, fim, organizador=None):
            return Evento.objects.create(
                title=titulo, description="d", local="Campus",
                data_inicio=inicio, data_fim=fim,
                organizador=organizador or self.org,
            )

        self.atual = evento(
            "Evento Atual", hoje - timedelta(days=1), hoje + timedelta(days=1)
        )
        self.futuro = evento(
            "Evento Futuro", hoje + timedelta(days=10), hoje + timedelta(days=11)
        )
        self.passado = evento(
            "Evento Passado", hoje - timedelta(days=30), hoje - timedelta(days=29)
        )
        for ev in (self.atual, self.futuro, self.passado):
            inicio = datetime(
                ev.data_inicio.year, ev.data_inicio.month, ev.data_inicio.day,
                10, 0, tzinfo=tz.utc,
            )
            Atividade.objects.create(
                evento=ev, titulo=f"Atividade {ev.title}", descricao="d",
                tipo=self.tipo,
                data_hora_inicio=inicio,
                data_hora_fim=inicio + timedelta(hours=1),
                n_vagas=10,
            )
        self.client.force_login(self.org)

    def _html(self):
        return self.client.get(reverse("organizador:dashboard")).content.decode()

    def test_evento_atual_vem_em_destaque(self):
        html = self._html()

        self.assertIn("Evento padrão", html)
        self.assertLess(html.find(self.atual.title), html.find("Outros eventos"))

    def test_outros_eventos_aparecem_em_linhas(self):
        html = self._html()

        self.assertIn("Outros eventos", html)
        self.assertIn(self.futuro.title, html)
        self.assertIn(
            reverse("eventos:definir_evento_padrao", args=[self.futuro.id]), html
        )

    def test_passados_ficam_no_arquivo_e_nao_em_outros(self):
        html = self._html()

        self.assertIn("Eventos passados", html)
        self.assertIn(
            reverse("organizador:atividades_evento", args=[self.passado.id]), html
        )
        # O evento encerrado fica no arquivo, depois dos eventos que ainda valem.
        self.assertGreater(html.find("Eventos passados"), html.find("Outros eventos"))

    def test_fixar_evento_reorganiza_o_painel(self):
        resposta = self.client.post(
            reverse("eventos:definir_evento_padrao", args=[self.futuro.id]),
            {"next": reverse("organizador:dashboard")},
        )

        self.assertRedirects(resposta, reverse("organizador:dashboard"))
        self.org.refresh_from_db()
        self.assertEqual(self.org.evento_padrao_id, self.futuro.id)

        html = self._html()
        self.assertLess(html.find(self.futuro.title), html.find("Outros eventos"))

    def test_nao_fixa_evento_de_outro_organizador(self):
        alheio = Evento.objects.create(
            title="Evento Alheio", description="d", local="l",
            data_inicio=date.today(), data_fim=date.today(),
            organizador=self.outro_org,
        )

        resposta = self.client.post(
            reverse("eventos:definir_evento_padrao", args=[alheio.id])
        )

        self.assertEqual(resposta.status_code, 404)
