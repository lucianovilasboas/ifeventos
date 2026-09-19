"""Testes do formulário de atividade: local (datalist + criar), palestrantes e prévia."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from eventos.forms import AtividadeForm
from eventos.models import Espaco, Evento

U = get_user_model()
SENHA = "SenhaForte123!"


class AtividadeFormTests(TestCase):
    def test_local_usa_datalist(self):
        form = AtividadeForm()
        self.assertEqual(form.fields["local"].widget.attrs.get("list"), "listaLocais")

    def test_palestrantes_so_quem_tem_a_flag(self):
        palestrante = U.objects.create_user(
            email="pal@example.com", password=SENHA, cpf="11144477735",
            is_palestrante=True,
        )
        participante = U.objects.create_user(
            email="part@example.com", password=SENHA, cpf="39053344705",
            is_palestrante=False,
        )
        queryset = AtividadeForm().fields["palestrantes"].queryset
        self.assertIn(palestrante, queryset)
        self.assertNotIn(participante, queryset)


class AdicionarLocalTests(TestCase):
    def setUp(self):
        self.org = U.objects.create_user(
            email="org_local@example.com", password=SENHA, cpf="12345678909",
            is_organizador=True,
        )
        self.url = reverse("organizador:adicionar_local")

    def test_exige_login(self):
        resposta = self.client.post(self.url, {"local-nome": "Sala 3"})
        self.assertEqual(resposta.status_code, 302)

    def test_cria_espaco_no_catalogo(self):
        self.client.force_login(self.org)
        resposta = self.client.post(
            self.url, {"local-nome": "Sala 3", "local-capacidade": "20"}
        )
        dados = resposta.json()
        self.assertTrue(dados["success"])
        self.assertTrue(Espaco.objects.filter(nome="Sala 3").exists())

    def test_nao_duplica_espaco_parecido(self):
        Espaco.objects.create(nome="Auditório", capacidade=40)
        self.client.force_login(self.org)
        resposta = self.client.post(self.url, {"local-nome": "Auditorio"})
        self.assertFalse(resposta.json()["success"])


class FormAtividadeViewTests(TestCase):
    def setUp(self):
        self.org = U.objects.create_user(
            email="org_form@example.com", password=SENHA, cpf="12345678909",
            is_organizador=True,
        )
        hoje = timezone.localdate()
        self.evento = Evento.objects.create(
            title="Evento", description="d", local="Campus",
            data_inicio=hoje + timedelta(days=1), data_fim=hoje + timedelta(days=2),
            organizador=self.org,
        )

    def test_renderiza_datalist_e_placeholder(self):
        self.client.force_login(self.org)
        Espaco.objects.create(nome="Laboratório 1", capacidade=30)
        resposta = self.client.get(reverse(
            "organizador:criar_editar_atividade_criar", args=[self.evento.id]
        ))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'id="listaLocais"')
        self.assertContains(resposta, "Laboratório 1")
        self.assertContains(resposta, "atividade-sem-imagem.png")
        self.assertContains(resposta, 'id="id_local-nome"')
