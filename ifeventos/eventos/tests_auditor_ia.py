"""Testes do agente interno de auditoria (consulta estruturada + resumo)."""

import json
import types
from datetime import date
from unittest import mock

from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.test import TestCase

from eventos import auditor_ia
from eventos.models import Evento, RegistroAuditoria

U = get_user_model()
SENHA = "SenhaForte123!"


def _evento(organizador, **kwargs):
    dados = dict(
        title="Evento IA", description="d", local="Sala",
        data_inicio=date(2026, 10, 10), data_fim=date(2026, 10, 12),
    )
    dados.update(kwargs)
    return Evento.objects.create(organizador=organizador, **dados)


class _Resposta:
    def __init__(self, conteudo):
        self.choices = [
            types.SimpleNamespace(message=types.SimpleNamespace(content=conteudo))
        ]


class NormalizarSpecTests(TestCase):
    def test_remove_invalidos_e_limita(self):
        spec = auditor_ia.normalizar_spec(
            {
                "filtros": {
                    "acao": "emitir_certificado",
                    "entidade": "Evento",
                    "origem": "web",
                    "desde": "2026-09-01",
                    "evento": "10",
                    "usuario": None,
                    "drop": "x",
                },
                "agrupar_por": "dia",
                "limite": 999,
            }
        )
        self.assertEqual(spec["filtros"]["acao"], "emitir_certificado")
        self.assertEqual(spec["filtros"]["entidade"], "Evento")
        self.assertEqual(spec["filtros"]["evento"], 10)
        self.assertNotIn("usuario", spec["filtros"])
        self.assertNotIn("drop", spec["filtros"])
        self.assertEqual(spec["agrupar_por"], "dia")
        self.assertEqual(spec["limite"], 100)

    def test_lixo_vira_padrao(self):
        spec = auditor_ia.normalizar_spec(
            {"filtros": {"acao": "DROP TABLE"}, "agrupar_por": "hack", "limite": "x"}
        )
        self.assertNotIn("acao", spec["filtros"])
        self.assertIsNone(spec["agrupar_por"])
        self.assertEqual(spec["limite"], 20)


class ExecutarConsultaTests(TestCase):
    def setUp(self):
        self.org = U.objects.create_user(
            email="org@ia.test", password=SENHA, is_organizador=True
        )
        self.outro = U.objects.create_user(
            email="outro@ia.test", password=SENHA, is_organizador=True
        )
        self.evento = _evento(self.org)
        self.evento_outro = _evento(self.outro)
        RegistroAuditoria.objects.create(
            acao="emitir_certificado", entidade="Certificado",
            evento=self.evento, usuario=self.org, usuario_nome="Org",
        )
        RegistroAuditoria.objects.create(
            acao="criar", entidade="Evento", evento=self.evento_outro, usuario=self.outro,
        )

    def test_filtro_e_escopo(self):
        spec = auditor_ia.normalizar_spec(
            {"filtros": {"acao": "emitir_certificado"}, "limite": 10}
        )
        resultado = auditor_ia.executar_consulta(spec, self.org)
        self.assertEqual(resultado["total"], 1)
        self.assertEqual(resultado["itens"][0]["acao"], "emitir_certificado")

    def test_escopo_nao_vaza_evento_alheio(self):
        spec = auditor_ia.normalizar_spec({"filtros": {"entidade": "Evento"}})
        resultado = auditor_ia.executar_consulta(spec, self.org)
        eventos = {item["evento"] for item in resultado["itens"]}
        self.assertNotIn(self.evento_outro.id, eventos)

    def test_agrupamento(self):
        spec = auditor_ia.normalizar_spec({"agrupar_por": "acao", "limite": 10})
        resultado = auditor_ia.executar_consulta(spec, self.org)
        self.assertEqual(resultado["agrupado_por"], "acao")
        self.assertTrue(resultado["grupos"])


class ResponderTests(TestCase):
    def setUp(self):
        self.org = U.objects.create_user(
            email="org2@ia.test", password=SENHA, is_organizador=True
        )

    def test_pergunta_vazia(self):
        resultado = async_to_sync(auditor_ia.responder)("", self.org)
        self.assertFalse(resultado["ok"])

    def test_responder_com_mock(self):
        spec = json.dumps({"filtros": {"acao": "criar"}, "agrupar_por": "dia"})
        with mock.patch.object(
            auditor_ia.services,
            "gerar_chat",
            new=mock.AsyncMock(side_effect=[_Resposta(spec), _Resposta("Há 1 ação.")]),
        ):
            resultado = async_to_sync(auditor_ia.responder)("Quantas ações?", self.org)
        self.assertTrue(resultado["ok"])
        self.assertEqual(resultado["resposta"], "Há 1 ação.")
        self.assertEqual(resultado["consulta"]["agrupar_por"], "dia")

    def test_falha_da_ia_nao_levanta(self):
        with mock.patch.object(
            auditor_ia.services, "gerar_chat",
            new=mock.AsyncMock(side_effect=RuntimeError("sem chave")),
        ):
            resultado = async_to_sync(auditor_ia.responder)("oi", self.org)
        self.assertFalse(resultado["ok"])
        self.assertIn("erro", resultado)


class PaginaAuditoriaTests(TestCase):
    URL = "/organizador/auditoria/"

    def test_superuser_acessa(self):
        admin = U.objects.create_user(
            email="adm@ia.test", password=SENHA, is_superuser=True, is_staff=True
        )
        self.client.force_login(admin)
        self.assertEqual(self.client.get(self.URL).status_code, 200)

    def test_organizador_bloqueado(self):
        org = U.objects.create_user(
            email="pg@ia.test", password=SENHA, is_organizador=True
        )
        self.client.force_login(org)
        self.assertEqual(self.client.get(self.URL).status_code, 403)

    def test_participante_bloqueado(self):
        part = U.objects.create_user(email="pgp@ia.test", password=SENHA)
        self.client.force_login(part)
        self.assertEqual(self.client.get(self.URL).status_code, 403)

    def test_endpoint_responder(self):
        admin = U.objects.create_user(
            email="resp@ia.test", password=SENHA, is_superuser=True, is_staff=True
        )
        self.client.force_login(admin)
        spec = json.dumps({"filtros": {"acao": "criar"}, "agrupar_por": "acao"})
        with mock.patch.object(
            auditor_ia.services,
            "gerar_chat",
            new=mock.AsyncMock(side_effect=[_Resposta(spec), _Resposta("Ok.")]),
        ):
            resposta = self.client.post(
                "/organizador/auditoria/responder/",
                data=json.dumps({"pergunta": "quantas acoes?"}),
                content_type="application/json",
            )
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.json()["ok"])
