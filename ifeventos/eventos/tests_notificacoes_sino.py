"""Testes do sino de notificações persistentes (conclusão de tarefas)."""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from eventos.models import Evento, Notificacao

U = get_user_model()
SENHA = "SenhaForte123!"


class NotificacoesSinoTests(TestCase):
    def setUp(self):
        self.pessoa = U.objects.create_user(
            email="notif@example.com", password=SENHA, cpf="12345678909",
            is_organizador=True,
        )
        self.outra = U.objects.create_user(
            email="outra_notif@example.com", password=SENHA, cpf="11144477735",
        )
        self.evento = Evento.objects.create(
            title="Evento", description="d", local="l",
            data_inicio=date(2026, 10, 10), data_fim=date(2026, 10, 11),
            organizador=self.pessoa,
        )
        self.notificacao = Notificacao.objects.create(
            usuario=self.pessoa, evento=self.evento,
            titulo="Comunicado enviado", mensagem="10 e-mails enviados.",
            url="/organizador/evento/%s/comunicacao/" % self.evento.id,
        )
        self.antiga = Notificacao.objects.create(
            usuario=self.pessoa, titulo="Antiga", lida=True,
        )
        Notificacao.objects.create(usuario=self.outra, titulo="De outra pessoa")

    def test_lista_apenas_as_do_usuario(self):
        self.client.force_login(self.pessoa)
        resposta = self.client.get(reverse("notificacoes"))
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()
        self.assertEqual(dados["nao_lidas"], 1)
        ids = {item["id"] for item in dados["itens"]}
        self.assertEqual(ids, {self.notificacao.id, self.antiga.id})

    def test_marcar_lida(self):
        self.client.force_login(self.pessoa)
        resposta = self.client.post(
            reverse("notificacao_lida", args=[self.notificacao.id])
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json()["nao_lidas"], 0)
        self.notificacao.refresh_from_db()
        self.assertTrue(self.notificacao.lida)

    def test_nao_marca_notificacao_de_outro_usuario(self):
        self.client.force_login(self.outra)
        resposta = self.client.post(
            reverse("notificacao_lida", args=[self.notificacao.id])
        )
        self.assertEqual(resposta.status_code, 404)
        self.notificacao.refresh_from_db()
        self.assertFalse(self.notificacao.lida)

    def test_marcar_todas(self):
        self.client.force_login(self.pessoa)
        resposta = self.client.post(reverse("notificacoes_marcar_todas"))
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json()["nao_lidas"], 0)
        self.assertFalse(
            Notificacao.objects.filter(usuario=self.pessoa, lida=False).exists()
        )

    def test_anonimo_redireciona(self):
        resposta = self.client.get(reverse("notificacoes"))
        self.assertEqual(resposta.status_code, 302)

    def test_sino_aparece_no_painel(self):
        self.client.force_login(self.pessoa)
        resposta = self.client.get(reverse("organizador:dashboard"))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "data-notificacoes")
        self.assertContains(resposta, "Notificações")
