"""Testes do formulário de atividade: espaço (catálogo + criar), palestrantes e prévia."""

from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from eventos.forms import AtividadeForm
from eventos.models import Espaco, Evento

U = get_user_model()
SENHA = "SenhaForte123!"


class AtividadeFormTests(TestCase):
    def test_espaco_e_select_do_catalogo(self):
        Espaco.objects.create(nome="Auditório", capacidade=40)
        campo = AtividadeForm().fields["local"]

        self.assertEqual(campo.label, "Espaço")
        self.assertIsInstance(campo.widget, forms.Select)
        valores = [valor for valor, _rotulo in campo.choices]
        self.assertIn("", valores)
        self.assertIn("Auditório", valores)
        # O widget precisa das opções (não basta o campo): senão o <select> sai vazio.
        self.assertIn("Auditório", [valor for valor, _rotulo in campo.widget.choices])

    def test_espaco_inclui_valor_legado_do_objeto(self):
        from eventos.models import Atividade

        atividade = Atividade(local="Sala Antiga")
        campo = AtividadeForm(instance=atividade).fields["local"]
        valores = [valor for valor, _rotulo in campo.choices]
        self.assertIn("Sala Antiga", valores)

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

    def test_palestrantes_e_opcional(self):
        self.assertFalse(AtividadeForm().fields["palestrantes"].required)

    def test_atividade_sem_palestrante_e_valida(self):
        from eventos.models import TipoAtividade

        tipo = TipoAtividade.objects.create(nome="Oficina")
        dados = {
            "titulo": "Exposição sem palestrante",
            "descricao": "d",
            "local": "",
            "tipo": tipo.id,
            "palestrantes": [],
            "data_hora_inicio": "2026-10-10T08:00",
            "data_hora_fim": "2026-10-10T09:00",
            "n_vagas": 10,
            "emite_certificado": False,
        }
        formulario = AtividadeForm(data=dados)
        self.assertTrue(formulario.is_valid(), formulario.errors)


class CriarAtividadeSemPalestranteTests(TestCase):
    """Criar atividade pelo formulário sem palestrante salva com 0."""

    def setUp(self):
        from eventos.models import Atividade, TipoAtividade

        self.Atividade = Atividade
        self.org = U.objects.create_user(
            email="org_sempal@example.com", password=SENHA, cpf="12345678909",
            is_organizador=True,
        )
        self.tipo = TipoAtividade.objects.create(nome="Oficina")
        self.evento = Evento.objects.create(
            title="Evento", description="d", local="l",
            data_inicio="2026-10-10", data_fim="2026-10-12",
            organizador=self.org,
        )

    def test_cria_atividade_sem_palestrante(self):
        from django.utils import timezone

        self.client.force_login(self.org)
        inicio = timezone.localtime() + timedelta(days=1)
        resposta = self.client.post(
            reverse("organizador:criar_editar_atividade_criar", args=[self.evento.id]),
            {
                "titulo": "Feira sem palestrante",
                "descricao": "d",
                "local": "",
                "tipo": self.tipo.id,
                "palestrantes": [],
                "data_hora_inicio": inicio.strftime("%Y-%m-%dT%H:%M"),
                "data_hora_fim": (inicio + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
                "n_vagas": 10,
                "emite_certificado": False,
            },
        )
        self.assertEqual(resposta.status_code, 302)
        atividade = self.Atividade.objects.get(titulo="Feira sem palestrante")
        self.assertEqual(atividade.palestrantes.count(), 0)


class AdicionarEspacoTests(TestCase):
    def setUp(self):
        self.org = U.objects.create_user(
            email="org_local@example.com", password=SENHA, cpf="12345678909",
            is_organizador=True,
        )
        self.url = reverse("organizador:adicionar_espaco_ajax")

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

    def test_renderiza_select_de_espaco_e_placeholder(self):
        self.client.force_login(self.org)
        Espaco.objects.create(nome="Laboratório 1", capacidade=30)
        resposta = self.client.get(reverse(
            "organizador:criar_editar_atividade_criar", args=[self.evento.id]
        ))
        self.assertEqual(resposta.status_code, 200)
        self.assertNotContains(resposta, "listaLocais")
        self.assertContains(resposta, 'id="listaEspacos"')
        self.assertContains(resposta, "Laboratório 1")
        self.assertContains(resposta, "Espaço")
        self.assertContains(resposta, "atividade-sem-imagem.png")
        self.assertContains(resposta, 'id="id_local-nome"')
