"""Testes do diagnóstico da auditoria (sinais + playbooks + relatório)."""

import json
import types
from datetime import date, timedelta
from unittest import mock

from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from eventos import auditor_diagnostico
from eventos.auditoria_playbooks import playbooks_para
from eventos.models import Evento, RegistroAuditoria

U = get_user_model()
SENHA = "SenhaForte123!"


class _Resposta:
    def __init__(self, conteudo):
        self.choices = [
            types.SimpleNamespace(message=types.SimpleNamespace(content=conteudo))
        ]


def _erro(resumo, logger, evento=None, traceback="", **kwargs):
    return RegistroAuditoria.objects.create(
        acao=RegistroAuditoria.ACAO_ERRO,
        entidade="Sistema",
        resumo=resumo,
        evento=evento,
        detalhes={"logger": logger, "nivel": "ERROR", "traceback": traceback},
        **kwargs,
    )


class NormalizarAssinaturaTests(TestCase):
    def test_troca_ids_e_numeros(self):
        a = auditor_diagnostico.normalizar_assinatura(
            "Atividade 42 falhou (id 7f3a1c9b2d4e)"
        )
        b = auditor_diagnostico.normalizar_assinatura(
            "Atividade 99 falhou (id aa11bb22cc33)"
        )
        self.assertEqual(a, b)
        self.assertIn("<n>", a)


class PlaybooksTests(TestCase):
    def test_casa_websocket_client(self):
        pbs = playbooks_para(
            "websocket-client package not installed, only polling transport is available",
            "engineio.client",
        )
        self.assertEqual(pbs[0]["id"], "engineio-websocket-client")

    def test_casa_por_logger(self):
        pbs = playbooks_para("qualquer coisa", "eventos.services")
        self.assertIn("socket-notify", {pb["id"] for pb in pbs})

    def test_sem_correspondencia(self):
        self.assertEqual(playbooks_para("mensagem qualquer", "eventos.desconhecido"), [])


class ColetarSinaisTests(TestCase):
    def setUp(self):
        self.admin = U.objects.create_user(
            email="adm@diag.test", password=SENHA, is_superuser=True, is_staff=True
        )
        self.org = U.objects.create_user(
            email="org@diag.test", password=SENHA, is_organizador=True
        )
        self.evento = Evento.objects.create(
            title="E", description="d", local="l",
            data_inicio=date(2026, 10, 1), data_fim=date(2026, 10, 2),
            organizador=self.org,
        )
        for i in range(3):
            _erro(f"Atividade {i} falhou", "eventos.crachas", evento=self.evento)
        _erro("Falha alheia 123", "eventos.foo")  # sem evento

    def _janela(self):
        agora = timezone.now()
        return agora - timedelta(days=1), agora

    def test_agrupa_por_assinatura(self):
        desde, ate = self._janela()
        sinais = auditor_diagnostico.coletar_sinais(self.admin, desde, ate)
        self.assertEqual(sinais["erros_total"], 4)
        grupos = {g["assinatura"]: g["ocorrencias"] for g in sinais["erros_grupos"]}
        self.assertEqual(grupos.get("Atividade <n> falhou"), 3)

    def test_escopo_do_organizador(self):
        desde, ate = self._janela()
        sinais = auditor_diagnostico.coletar_sinais(self.org, desde, ate)
        self.assertEqual(sinais["erros_total"], 3)  # não vê o erro sem evento

    def test_playbook_aparece_no_grupo(self):
        _erro(
            "websocket-client package not installed, only polling transport is available",
            "engineio.client",
            evento=self.evento,
        )
        desde, ate = self._janela()
        sinais = auditor_diagnostico.coletar_sinais(self.admin, desde, ate)
        ids = {
            pb["id"]
            for g in sinais["erros_grupos"]
            for pb in g["playbooks"]
        }
        self.assertIn("engineio-websocket-client", ids)

    def test_traceback_mascarado(self):
        _erro(
            "Falha com dado pessoal",
            "eventos.foo",
            evento=self.evento,
            traceback="INSERT ... 'fulano@example.com' ... cpf 123.456.789-09",
        )
        desde, ate = self._janela()
        sinais = auditor_diagnostico.coletar_sinais(self.admin, desde, ate)
        grupo = next(g for g in sinais["erros_grupos"] if "dado pessoal" in g["exemplo"])
        self.assertNotIn("fulano@example.com", grupo["traceback"])
        self.assertNotIn("123.456.789-09", grupo["traceback"])


class RelatorioTests(TestCase):
    def setUp(self):
        self.admin = U.objects.create_user(
            email="adm2@diag.test", password=SENHA, is_superuser=True, is_staff=True
        )
        self.evento = Evento.objects.create(
            title="E", description="d", local="l",
            data_inicio=date(2026, 10, 1), data_fim=date(2026, 10, 2),
        )
        for _ in range(3):
            _erro("Atividade falhou", "eventos.crachas", evento=self.evento)

    def _sinais(self):
        agora = timezone.now()
        return auditor_diagnostico.coletar_sinais(
            self.admin, agora - timedelta(days=1), agora
        )

    def test_json_valido_e_interpretado(self):
        bruto = json.dumps(
            {
                "severidade_geral": "alto",
                "resumo": "Há um erro recorrente.",
                "itens": [
                    {
                        "titulo": "Erro recorrente",
                        "severidade": "alto",
                        "evidencia": "3 ocorrências",
                        "causa_provavel": "causa",
                        "solucao": "fazer X",
                        "onde": "eventos/crachas.py",
                    }
                ],
            }
        )
        rel = auditor_diagnostico.montar_relatorio(bruto, self._sinais())
        self.assertEqual(rel["severidade_geral"], "alto")
        self.assertEqual(rel["itens"][0]["solucao"], "fazer X")

    def test_json_invalido_cai_no_deterministico(self):
        rel = auditor_diagnostico.montar_relatorio("nao e json", self._sinais())
        self.assertTrue(rel["itens"])  # fallback usa os grupos
        self.assertIn(rel["severidade_geral"], auditor_diagnostico.SEVERIDADES)

    def test_severidade_deterministica_com_5xx(self):
        sinais = {"erros_grupos": [], "http_status": [{"status": 500, "total": 2}]}
        self.assertEqual(auditor_diagnostico.severidade_deterministica(sinais), "alto")


class DiagnosticoTests(TestCase):
    def setUp(self):
        self.admin = U.objects.create_user(
            email="adm3@diag.test", password=SENHA, is_superuser=True, is_staff=True
        )

    def test_ia_falha_usa_deterministico(self):
        with mock.patch.object(
            auditor_diagnostico.services,
            "gerar_chat",
            new=mock.AsyncMock(side_effect=RuntimeError("sem chave")),
        ):
            resultado = async_to_sync(auditor_diagnostico.diagnostico)(self.admin)
        self.assertTrue(resultado["ok"])
        self.assertIn(resultado["severidade_geral"], auditor_diagnostico.SEVERIDADES)

    def test_diagnostico_com_mock(self):
        bruto = json.dumps(
            {"severidade_geral": "ok", "resumo": "Tudo certo.", "itens": []}
        )
        with mock.patch.object(
            auditor_diagnostico.services,
            "gerar_chat",
            new=mock.AsyncMock(return_value=_Resposta(bruto)),
        ):
            resultado = async_to_sync(auditor_diagnostico.diagnostico)(self.admin)
        self.assertTrue(resultado["ok"])
        self.assertEqual(resultado["severidade_geral"], "ok")
        self.assertEqual(resultado["resumo"], "Tudo certo.")


class DiagnosticoEndpointTests(TestCase):
    URL = "/organizador/auditoria/diagnostico/"

    def test_superuser_recebe(self):
        admin = U.objects.create_user(
            email="adm4@diag.test", password=SENHA, is_superuser=True, is_staff=True
        )
        self.client.force_login(admin)
        bruto = json.dumps({"severidade_geral": "ok", "resumo": "ok", "itens": []})
        with mock.patch.object(
            auditor_diagnostico.services,
            "gerar_chat",
            new=mock.AsyncMock(return_value=_Resposta(bruto)),
        ):
            resposta = self.client.post(
                self.URL, data=json.dumps({"dias": 7}), content_type="application/json"
            )
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.json()["ok"])

    def test_organizador_bloqueado(self):
        org = U.objects.create_user(
            email="org5@diag.test", password=SENHA, is_organizador=True
        )
        self.client.force_login(org)
        resposta = self.client.post(
            self.URL, data=json.dumps({"dias": 7}), content_type="application/json"
        )
        self.assertEqual(resposta.status_code, 403)
