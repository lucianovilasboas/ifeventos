"""Testes da API da trilha de auditoria (/api/v1/auditoria/)."""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from eventos.models import Evento, RegistroAuditoria

U = get_user_model()
SENHA = "SenhaForte123!"
LISTA = "/api/v1/auditoria/"
RESUMO = "/api/v1/auditoria/resumo/"


def _evento(organizador, **kwargs):
    dados = dict(
        title="Evento Aud API", description="d", local="Sala",
        data_inicio=date(2026, 10, 10), data_fim=date(2026, 10, 12),
    )
    dados.update(kwargs)
    return Evento.objects.create(organizador=organizador, **dados)


class AuditoriaApiTests(TestCase):
    def setUp(self):
        self.org = U.objects.create_user(
            email="org@audapi.test", password=SENHA, is_organizador=True
        )
        self.outro_org = U.objects.create_user(
            email="outro@audapi.test", password=SENHA, is_organizador=True
        )
        self.participante = U.objects.create_user(
            email="part@audapi.test", password=SENHA
        )
        self.evento = _evento(self.org, title="Meu evento")  # gera linha "criar"
        self.evento_outro = _evento(self.outro_org, title="Evento alheio")
        self.client = APIClient()

    def test_participante_recebe_403(self):
        self.client.force_authenticate(user=self.participante)
        self.assertEqual(self.client.get(LISTA).status_code, 403)

    def test_organizador_lista(self):
        self.client.force_authenticate(user=self.org)
        resposta = self.client.get(LISTA)
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("results", resposta.json())

    def test_filtro_por_entidade(self):
        self.client.force_authenticate(user=self.org)
        resposta = self.client.get(LISTA, {"entidade": "Evento"})
        self.assertEqual(resposta.status_code, 200)
        linha = next(
            r for r in resposta.json()["results"]
            if str(r["objeto_id"]) == str(self.evento.id)
        )
        self.assertEqual(linha["acao"], "criar")

    def test_escopo_nao_mostra_evento_alheio(self):
        self.client.force_authenticate(user=self.org)
        resposta = self.client.get(LISTA, {"entidade": "Evento"})
        ids = {str(r["objeto_id"]) for r in resposta.json()["results"]}
        self.assertIn(str(self.evento.id), ids)
        self.assertNotIn(str(self.evento_outro.id), ids)

    def test_email_mascarado(self):
        RegistroAuditoria.objects.create(
            acao="criar", entidade="Evento", objeto_id="x",
            usuario=self.org, usuario_email=self.org.email,
        )
        self.client.force_authenticate(user=self.org)
        resposta = self.client.get(LISTA)
        emails = {r["usuario_email"] for r in resposta.json()["results"] if r["usuario_email"]}
        self.assertTrue(emails)
        for email in emails:
            self.assertIn("***", email)

    def test_resumo_agrega(self):
        self.client.force_authenticate(user=self.org)
        resposta = self.client.get(RESUMO)
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()
        self.assertGreaterEqual(dados["total"], 1)
        self.assertTrue(dados["por_acao"])
        self.assertTrue(dados["por_dia"])

    def test_filtro_desde(self):
        self.client.force_authenticate(user=self.org)
        resposta = self.client.get(LISTA, {"desde": "2000-01-01"})
        self.assertEqual(resposta.status_code, 200)
        resposta = self.client.get(LISTA, {"desde": "2999-01-01"})
        self.assertEqual(resposta.json()["count"], 0)
