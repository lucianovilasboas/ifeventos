"""Exclusão de evento: só na edição, com a palavra "excluir" confirmada."""

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from eventos.models import Evento

U = get_user_model()
SENHA = "SenhaForte123!"


class ExclusaoDeEventoTests(TestCase):
    def setUp(self):
        self.org = U.objects.create_user(
            email="org_exclui@example.com", password=SENHA, cpf="12345678909",
            is_organizador=True,
        )
        self.co = U.objects.create_user(
            email="co_exclui@example.com", password=SENHA, cpf="39053344705",
            is_organizador=True,
        )
        self.superuser = U.objects.create_superuser(
            email="root_exclui@example.com", password=SENHA, cpf="98765432100",
        )
        hoje = date.today()
        self.evento = Evento.objects.create(
            title="Evento Excluível", description="d", local="Campus",
            data_inicio=hoje, data_fim=hoje + timedelta(days=1),
            organizador=self.org,
        )
        self.evento.organizadores.add(self.co)
        self.url = reverse("organizador:excluir_evento", args=[self.evento.id])

    def _existe(self):
        return Evento.objects.filter(id=self.evento.id).exists()

    def test_get_nao_exclui(self):
        self.client.force_login(self.org)

        resposta = self.client.get(self.url)

        self.assertEqual(resposta.status_code, 405)
        self.assertTrue(self._existe())

    def test_sem_palavra_nao_exclui(self):
        self.client.force_login(self.org)

        resposta = self.client.post(self.url, {})

        self.assertRedirects(
            resposta,
            reverse("organizador:editar_evento", args=[self.evento.id]),
        )
        self.assertTrue(self._existe())

    def test_palavra_errada_nao_exclui(self):
        self.client.force_login(self.org)

        resposta = self.client.post(self.url, {"confirmacao": "excluirr"})

        self.assertEqual(resposta.status_code, 302)
        self.assertTrue(self._existe())

    def test_palavra_excluir_exclui_mesmo_em_caixa_alta(self):
        self.client.force_login(self.org)

        resposta = self.client.post(self.url, {"confirmacao": " EXCLUIR "})

        self.assertRedirects(resposta, reverse("organizador:dashboard"))
        self.assertFalse(self._existe())

    def test_coorganizador_nao_exclui(self):
        self.client.force_login(self.co)

        resposta = self.client.post(self.url, {"confirmacao": "excluir"})

        self.assertEqual(resposta.status_code, 404)
        self.assertTrue(self._existe())

    def test_superusuario_exclui(self):
        self.client.force_login(self.superuser)

        resposta = self.client.post(self.url, {"confirmacao": "excluir"})

        self.assertRedirects(resposta, reverse("organizador:dashboard"))
        self.assertFalse(self._existe())
