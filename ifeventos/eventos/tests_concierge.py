"""Testes do concierge do participante."""

from datetime import timedelta
from unittest import mock
from unittest.mock import AsyncMock

from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from asgiref.sync import async_to_sync

from eventos import concierge
from eventos.models import Atividade, Evento, TipoAtividade

U = get_user_model()
SENHA = "SenhaForte123!"


class _FakeOpenAI:
    def __init__(self, conteudo):
        resposta = mock.MagicMock()
        resposta.choices = [mock.MagicMock()]
        resposta.choices[0].message.content = conteudo
        resposta.usage = None
        self.chat = mock.MagicMock()
        self.chat.completions.create = AsyncMock(return_value=resposta)


class _FixturesMixin:
    def setUp(self):
        self.pessoa = U.objects.create_user(
            email="pessoa_con@example.com", password=SENHA, cpf="11144477735",
        )
        self.tipo = TipoAtividade.objects.create(nome="Oficina")
        hoje = timezone.localdate()
        self.evento = Evento.objects.create(
            title="Mostra de Tecnologia", description="d", local="Campus",
            data_inicio=hoje, data_fim=hoje + timedelta(days=2),
            categoria="tecnologia", organizador=self.pessoa,
        )
        agora = timezone.now()
        self.publicada = Atividade.objects.create(
            evento=self.evento, titulo="Oficina de Robótica", descricao="d",
            tipo=self.tipo, local="Laboratório 1", n_vagas=20,
            data_hora_inicio=agora + timedelta(hours=2),
            data_hora_fim=agora + timedelta(hours=4), publicada=True,
        )
        Atividade.objects.create(
            evento=self.evento, titulo="Rascunho interno", descricao="d",
            tipo=self.tipo, n_vagas=10,
            data_hora_inicio=agora + timedelta(hours=2),
            data_hora_fim=agora + timedelta(hours=4), publicada=False,
        )


class CatalogoTests(_FixturesMixin, TestCase):
    def test_catalogo_so_publicadas(self):
        itens = concierge.catalogo()
        titulos = [i["titulo"] for i in itens]
        self.assertIn("Oficina de Robótica", titulos)
        self.assertNotIn("Rascunho interno", titulos)

    def test_contexto_texto(self):
        texto = concierge.contexto_texto(concierge.catalogo())
        self.assertIn("Oficina de Robótica", texto)
        self.assertIn("Laboratório 1", texto)

    def test_resposta_basica_vazia(self):
        resultado = concierge.resposta_basica([])
        self.assertIn("Não encontrei", resultado["resposta"])


class SugestoesTests(_FixturesMixin, TestCase):
    def test_curto_devolve_faq(self):
        sugestoes = concierge.sugestoes("")
        self.assertTrue(any("certificado" in s.lower() for s in sugestoes))

    def test_por_titulo_de_atividade(self):
        sugestoes = concierge.sugestoes("robótica")
        self.assertIn("Oficina de Robótica", sugestoes)

    def test_por_evento(self):
        sugestoes = concierge.sugestoes("Mostra")
        self.assertIn("Mostra de Tecnologia", sugestoes)

    def test_sem_duplicatas(self):
        sugestoes = concierge.sugestoes("oficina")
        self.assertEqual(len(sugestoes), len(set(s.lower() for s in sugestoes)))


class ResponderTests(_FixturesMixin, TransactionTestCase):
    def test_mensagem_vazia(self):
        resultado = async_to_sync(concierge.responder)("   ")
        self.assertIn("erro", resultado)

    def test_fallback_sem_ia(self):
        with mock.patch("eventos.services.get_openai_client", side_effect=RuntimeError("x")):
            resultado = async_to_sync(concierge.responder)("o que tem hoje?")
        self.assertEqual(resultado["origem"], "heuristica")
        self.assertIn("Oficina de Robótica", resultado["resposta"])

    def test_ia_responde(self):
        fake = _FakeOpenAI("Tem a Oficina de Robótica às 14h, no Laboratório 1.")
        with mock.patch("eventos.services.get_openai_client", return_value=fake):
            resultado = async_to_sync(concierge.responder)("o que tem de tecnologia?")
        self.assertEqual(resultado["origem"], "ia")
        self.assertIn("Robótica", resultado["resposta"])


class ConciergeViewTests(_FixturesMixin, TransactionTestCase):
    def test_view_exige_login(self):
        resposta = self.client.get(reverse("participante:assistente"))
        self.assertEqual(resposta.status_code, 302)

    def test_view_renderiza(self):
        self.client.force_login(self.pessoa)
        resposta = self.client.get(reverse("participante:assistente"))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Assistente da programação")

    def test_responder_endpoint(self):
        self.client.force_login(self.pessoa)
        with mock.patch("eventos.services.get_openai_client", side_effect=RuntimeError("x")):
            resposta = self.client.post(
                reverse("participante:assistente_responder"),
                data='{"mensagem": "o que tem hoje?"}',
                content_type="application/json",
            )
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("resposta", resposta.json())

    def test_sugestoes_endpoint(self):
        self.client.force_login(self.pessoa)
        resposta = self.client.get(
            reverse("participante:assistente_sugestoes"), {"q": "robótica"}
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("Oficina de Robótica", resposta.json()["sugestoes"])

    def test_sugestoes_exige_login(self):
        resposta = self.client.get(reverse("participante:assistente_sugestoes"))
        self.assertEqual(resposta.status_code, 302)
