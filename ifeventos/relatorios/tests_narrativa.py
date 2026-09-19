"""Testes da narrativa dos relatórios (resumo + ações)."""

import json
from datetime import timedelta
from unittest import mock
from unittest.mock import AsyncMock

from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from asgiref.sync import async_to_sync

from eventos.models import Atividade, Evento, Inscricao, TipoAtividade
from relatorios import narrativa

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
            email="org_nar@example.com", password=SENHA, cpf="12345678909",
            is_organizador=True,
        )
        self.pessoa = U.objects.create_user(
            email="pessoa_nar@example.com", password=SENHA, cpf="11144477735",
        )
        self.tipo = TipoAtividade.objects.create(nome="Oficina")
        hoje = timezone.localdate()
        self.evento = Evento.objects.create(
            title="Evento Narrado", description="d", local="Campus",
            data_inicio=hoje + timedelta(days=10),
            data_fim=hoje + timedelta(days=11),
            categoria="formacao", organizador=self.org,
        )
        self.atividade = Atividade.objects.create(
            evento=self.evento, titulo="Oficina A", descricao="d", tipo=self.tipo,
            n_vagas=10,
            data_hora_inicio=timezone.now() + timedelta(days=10),
            data_hora_fim=timezone.now() + timedelta(days=10, hours=2),
        )
        Inscricao.objects.create(participante=self.pessoa, atividade=self.atividade)


class NarrativaBasicaTests(_FixturesMixin, TestCase):
    def test_resumo_e_acoes_deterministicos(self):
        dados = {
            "indicadores": {
                "Atividades": {"valor": 3}, "Inscrições": {"valor": 10},
                "Ocupação média": {"valor": 50}, "Comparecimento": {"valor": 40},
                "Rascunhos": {"valor": 2}, "Conflitos na grade": {"valor": 1},
            },
            "vagas_ociosas": [{"titulo": "Oficina X", "vagas_livres": 5}],
        }
        resultado = narrativa.narrativa_basica(dados)

        self.assertIn("3 atividade", resultado["resumo"])
        self.assertTrue(resultado["destaques"])
        self.assertTrue(any("rascunho" in a.lower() for a in resultado["acoes"]))
        self.assertEqual(resultado["origem"], "heuristica")

    def test_fatos_traz_indicadores(self):
        dados = narrativa.fatos(self.evento)
        self.assertEqual(dados["evento"]["titulo"], "Evento Narrado")
        self.assertIn("Inscrições", dados["indicadores"])
        self.assertIn("publicacao", dados)


class NarrarTests(_FixturesMixin, TransactionTestCase):
    def test_fallback_sem_ia(self):
        with mock.patch("eventos.services.get_openai_client", side_effect=RuntimeError("x")):
            resultado = async_to_sync(narrativa.narrar)(self.evento)
        self.assertEqual(resultado["origem"], "heuristica")
        self.assertTrue(resultado["resumo"])

    def test_ia_devolve_resumo(self):
        conteudo = json.dumps({
            "resumo": "Evento saudável.",
            "destaques": ["Boa procura"],
            "acoes": ["Divulgar as vagas ociosas"],
        })
        with mock.patch("eventos.services.get_openai_client", return_value=_FakeOpenAI(conteudo)):
            resultado = async_to_sync(narrativa.narrar)(self.evento)
        self.assertEqual(resultado["origem"], "ia")
        self.assertEqual(resultado["resumo"], "Evento saudável.")
        self.assertEqual(resultado["acoes"], ["Divulgar as vagas ociosas"])


class NarrativaViewTests(_FixturesMixin, TransactionTestCase):
    def test_permissao_exige_organizador(self):
        self.client.force_login(self.pessoa)
        resposta = self.client.post(
            reverse("organizador:narrativa_evento", args=[self.evento.id])
        )
        self.assertEqual(resposta.status_code, 403)

    def test_organizador_recebe_narrativa(self):
        self.client.force_login(self.org)
        with mock.patch("eventos.services.get_openai_client", side_effect=RuntimeError("x")):
            resposta = self.client.post(
                reverse("organizador:narrativa_evento", args=[self.evento.id])
            )
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()
        self.assertEqual(dados["origem"], "heuristica")
        self.assertIn("resumo", dados)
