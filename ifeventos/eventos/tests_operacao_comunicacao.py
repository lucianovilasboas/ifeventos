"""Testes do briefing operacional e da comunicação assistida."""

import json
from datetime import timedelta
from unittest import mock
from unittest.mock import AsyncMock

from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from asgiref.sync import async_to_sync

from eventos import comunicacao, operacao
from eventos.models import Atividade, Evento, Inscricao, TipoAtividade

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
        self.org = U.objects.create_user(
            email="org_op@example.com", password=SENHA, cpf="12345678909",
            is_organizador=True,
        )
        self.pessoa = U.objects.create_user(
            email="pessoa_op@example.com", password=SENHA, cpf="11144477735",
        )
        self.tipo = TipoAtividade.objects.create(nome="Oficina")
        hoje = timezone.localdate()
        self.evento = Evento.objects.create(
            title="Evento Operação", description="Descrição do evento.",
            local="Auditório", data_inicio=hoje, data_fim=hoje + timedelta(days=1),
            categoria="formacao", organizador=self.org,
        )
        self.agora = timezone.now()
        # Uma em curso, uma a seguir.
        self.em_curso = Atividade.objects.create(
            evento=self.evento, titulo="Em curso", descricao="d", tipo=self.tipo,
            n_vagas=10, data_hora_inicio=self.agora - timedelta(hours=1),
            data_hora_fim=self.agora + timedelta(hours=1),
        )
        self.futura = Atividade.objects.create(
            evento=self.evento, titulo="A seguir", descricao="d", tipo=self.tipo,
            n_vagas=10, data_hora_inicio=self.agora + timedelta(hours=1),
            data_hora_fim=self.agora + timedelta(hours=2),
        )
        Inscricao.objects.create(participante=self.pessoa, atividade=self.em_curso)


class OperacaoTests(_FixturesMixin, TestCase):
    def test_em_curso_e_a_seguir(self):
        em_curso = operacao.em_curso(self.evento, self.agora)
        a_seguir = operacao.a_seguir(self.evento, self.agora)

        self.assertEqual([f["atividade"].titulo for f in em_curso], ["Em curso"])
        self.assertEqual([f["atividade"].titulo for f in a_seguir], ["A seguir"])

    def test_alerta_sem_checkin(self):
        avisos = operacao.alertas(self.evento, self.agora)
        self.assertTrue(any("não tem check-in" in a for a in avisos))

    def test_resumo_tem_chaves(self):
        dados = operacao.resumo(self.evento, self.agora)
        for chave in ("total_atividades", "em_curso", "a_seguir", "alertas"):
            self.assertIn(chave, dados)


class OperacaoAsyncTests(_FixturesMixin, TransactionTestCase):
    def test_leitura_fallback_sem_ia(self):
        with mock.patch("eventos.services.get_openai_client", side_effect=RuntimeError("x")):
            resultado = async_to_sync(operacao.leitura_do_dia)(self.evento, self.agora)
        self.assertEqual(resultado["origem"], "heuristica")
        self.assertTrue(resultado["leitura"])

    def test_view_operacao_exige_organizador(self):
        self.client.force_login(self.pessoa)
        resposta = self.client.get(
            reverse("organizador:briefing_operacional", args=[self.evento.id])
        )
        self.assertEqual(resposta.status_code, 403)

    def test_view_operacao_renderiza(self):
        self.client.force_login(self.org)
        resposta = self.client.get(
            reverse("organizador:briefing_operacional", args=[self.evento.id])
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Operação do evento")


class ComunicacaoTests(_FixturesMixin, TransactionTestCase):
    def test_rascunho_basico(self):
        post = comunicacao.rascunho_basico(self.evento, "post")
        email = comunicacao.rascunho_basico(self.evento, "email")
        self.assertIn(self.evento.title, post["corpo"])
        self.assertEqual(post["assunto"], "")
        self.assertIn("Convite", email["assunto"])

    def test_gerar_rascunho_fallback(self):
        with mock.patch("eventos.services.get_openai_client", side_effect=RuntimeError("x")):
            resultado = async_to_sync(comunicacao.gerar_rascunho)(self.evento, "post")
        self.assertEqual(resultado["origem"], "heuristica")
        self.assertIn(self.evento.title, resultado["corpo"])

    def test_gerar_rascunho_ia(self):
        conteudo = json.dumps({"assunto": "", "corpo": "Participe do evento!"})
        with mock.patch("eventos.services.get_openai_client", return_value=_FakeOpenAI(conteudo)):
            resultado = async_to_sync(comunicacao.gerar_rascunho)(self.evento, "post")
        self.assertEqual(resultado["origem"], "ia")
        self.assertEqual(resultado["corpo"], "Participe do evento!")

    def test_view_divulgacao_exige_organizador(self):
        self.client.force_login(self.pessoa)
        resposta = self.client.post(
            reverse("organizador:gerar_divulgacao", args=[self.evento.id]),
            data=json.dumps({"canal": "post"}), content_type="application/json",
        )
        self.assertEqual(resposta.status_code, 403)

    def test_view_divulgacao_ok(self):
        self.client.force_login(self.org)
        with mock.patch("eventos.services.get_openai_client", side_effect=RuntimeError("x")):
            resposta = self.client.post(
                reverse("organizador:gerar_divulgacao", args=[self.evento.id]),
                data=json.dumps({"canal": "post", "objetivo": "divulgar"}),
                content_type="application/json",
            )
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("corpo", resposta.json())
