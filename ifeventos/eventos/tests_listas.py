"""Testes das listas de atividades ordenadas por data."""

from datetime import date, datetime, timezone as tz

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Atividade, Evento, TipoAtividade

U = get_user_model()
SENHA = "SenhaForte123!"


class ProgramacaoOrdemTests(TestCase):
    """A programação pública sai na ordem em que as atividades vão acontecer."""

    def setUp(self):
        self.org = U.objects.create_user(
            email="org_prog@example.com", password=SENHA, cpf="12345678909"
        )
        self.tipo = TipoAtividade.objects.create(nome="Palestra")
        self.evento = Evento.objects.create(
            title="Evento", description="d", local="l",
            data_inicio=date(2026, 10, 10), data_fim=date(2026, 10, 12),
            categoria="formacao", organizador=self.org,
        )
        for titulo, dia in (("Terceiro", 12), ("Primeiro", 10), ("Segundo", 11)):
            Atividade.objects.create(
                evento=self.evento, titulo=titulo, descricao="d", tipo=self.tipo,
                data_hora_inicio=datetime(2026, 10, dia, 10, 0, tzinfo=tz.utc),
                data_hora_fim=datetime(2026, 10, dia, 11, 0, tzinfo=tz.utc),
                n_vagas=10,
            )

    def test_programacao_em_ordem_de_data(self):
        resposta = self.client.get(
            reverse("eventos:programacao", kwargs={"evento_id": self.evento.id})
        )
        self.assertEqual(resposta.status_code, 200)
        titulos = [a.titulo for a in resposta.context["atividades"]]
        self.assertEqual(titulos, ["Primeiro", "Segundo", "Terceiro"])


class TabelaAtividadesColunaDataTests(TestCase):
    """A tabela do organizador tem a data em coluna própria e ordenável."""

    def setUp(self):
        self.org = U.objects.create_user(
            email="org_tab@example.com", password=SENHA, cpf="12345678909",
            is_organizador=True,
        )
        self.tipo = TipoAtividade.objects.create(nome="Palestra")
        self.evento = Evento.objects.create(
            title="Evento", description="d", local="l",
            data_inicio=date(2026, 10, 10), data_fim=date(2026, 10, 12),
            categoria="formacao", organizador=self.org,
        )
        Atividade.objects.create(
            evento=self.evento, titulo="Abertura", descricao="d", tipo=self.tipo,
            data_hora_inicio=datetime(2026, 10, 10, 10, 0, tzinfo=tz.utc),
            data_hora_fim=datetime(2026, 10, 10, 11, 0, tzinfo=tz.utc),
            n_vagas=10,
        )
        self.client.force_login(self.org)

    def test_coluna_data_presente_e_com_valor_iso(self):
        resposta = self.client.get(
            reverse("organizador:atividades_evento", kwargs={"evento_id": self.evento.id})
        )
        self.assertEqual(resposta.status_code, 200)
        html = resposta.content.decode()
        self.assertIn(">Data</th>", html)
        self.assertIn('data-ordenar-inicial="5:desc"', html)
        # ISO localizado (ex.: 2026-10-10T07:00:00-03:00) — ordena como texto.
        self.assertIn('data-valor="2026-10-10T', html)


class LandingTotalAtividadesTests(TestCase):
    """O card e o modal da landing mostram o total de atividades do evento."""

    def setUp(self):
        self.org = U.objects.create_user(
            email="org_land@example.com", password=SENHA, cpf="12345678909"
        )
        self.tipo = TipoAtividade.objects.create(nome="Palestra")
        self.evento = Evento.objects.create(
            title="Evento Land", description="d", local="l",
            data_inicio=date(2030, 1, 1), data_fim=date(2030, 1, 2),
            categoria="formacao", organizador=self.org,
        )
        for titulo in ("Abertura", "Encerramento"):
            Atividade.objects.create(
                evento=self.evento, titulo=titulo, descricao="d", tipo=self.tipo,
                data_hora_inicio=datetime(2030, 1, 1, 10, 0, tzinfo=tz.utc),
                data_hora_fim=datetime(2030, 1, 1, 11, 0, tzinfo=tz.utc),
                n_vagas=10,
            )

    def test_card_e_modal_tem_o_total(self):
        resposta = self.client.get(reverse("eventos:eventos"))
        self.assertEqual(resposta.status_code, 200)
        html = resposta.content.decode()
        self.assertIn("2 atividades", html)   # card
        self.assertIn("nAtiv: 2", html)       # dados do modal (JS)
