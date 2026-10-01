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

    def test_palestrantes_em_ordem_alfabetica(self):
        U.objects.create_user(
            email="zeca@example.com", password=SENHA, cpf="11144477735",
            first_name="Zeca", last_name="Alves", is_palestrante=True,
        )
        U.objects.create_user(
            email="ana@example.com", password=SENHA, cpf="39053344705",
            first_name="Ana", last_name="Souza", is_palestrante=True,
        )

        nomes = [str(p) for p in AtividadeForm().fields["palestrantes"].queryset]

        self.assertEqual(nomes, sorted(nomes, key=lambda n: n.lower()))

    def test_widget_mostra_foto_e_nome(self):
        pessoa = U.objects.create_user(
            email="foto@example.com", password=SENHA, cpf="11144477735",
            first_name="Ana", last_name="Souza", is_palestrante=True,
        )

        html = str(AtividadeForm()["palestrantes"])

        self.assertIn("pal-foto", html)
        self.assertIn("Ana Souza", html)
        self.assertIn(pessoa.get_foto_url(), html)
        self.assertIn('name="palestrantes"', html)  # validação do Django segue igual

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

    def test_exige_inscricao_vem_marcada_por_padrao(self):
        campo = AtividadeForm().fields["exige_inscricao"]
        self.assertTrue(campo.initial)
        self.assertFalse(campo.required)

    def test_atividade_sem_inscricao_e_valida(self):
        from eventos.models import TipoAtividade

        tipo = TipoAtividade.objects.create(nome="Festa")
        dados = {
            "titulo": "LUAU",
            "descricao": "d",
            "local": "",
            "tipo": tipo.id,
            "palestrantes": [],
            "data_hora_inicio": "2026-10-10T20:00",
            "data_hora_fim": "2026-10-10T23:00",
            "n_vagas": 0,
            "emite_certificado": False,
        }
        # Checkbox ausente no POST = desmarcada.
        formulario = AtividadeForm(data=dados)
        self.assertTrue(formulario.is_valid(), formulario.errors)
        self.assertFalse(formulario.cleaned_data["exige_inscricao"])


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

    def test_cria_atividade_sem_inscricao(self):
        self.client.force_login(self.org)
        inicio = timezone.localtime() + timedelta(days=1)
        resposta = self.client.post(
            reverse("organizador:criar_editar_atividade_criar", args=[self.evento.id]),
            {
                "titulo": "LUAU",
                "descricao": "d",
                "local": "",
                "tipo": self.tipo.id,
                "palestrantes": [],
                "data_hora_inicio": inicio.strftime("%Y-%m-%dT%H:%M"),
                "data_hora_fim": (inicio + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M"),
                "n_vagas": 0,
                "emite_certificado": False,
                # sem exige_inscricao => desmarcado => atividade aberta
            },
        )
        self.assertEqual(resposta.status_code, 302)
        atividade = self.Atividade.objects.get(titulo="LUAU")
        self.assertFalse(atividade.exige_inscricao)

    def test_exige_inscricao_ligada_no_post(self):
        self.client.force_login(self.org)
        inicio = timezone.localtime() + timedelta(days=1)
        resposta = self.client.post(
            reverse("organizador:criar_editar_atividade_criar", args=[self.evento.id]),
            {
                "titulo": "Palestra",
                "descricao": "d",
                "local": "",
                "tipo": self.tipo.id,
                "palestrantes": [],
                "data_hora_inicio": inicio.strftime("%Y-%m-%dT%H:%M"),
                "data_hora_fim": (inicio + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
                "n_vagas": 10,
                "exige_inscricao": "on",
                "emite_certificado": False,
            },
        )
        self.assertEqual(resposta.status_code, 302)
        atividade = self.Atividade.objects.get(titulo="Palestra")
        self.assertTrue(atividade.exige_inscricao)


    def test_atividade_salva_tolerancia_propria(self):
        self.client.force_login(self.org)
        inicio = timezone.localtime() + timedelta(days=1)
        resposta = self.client.post(
            reverse("organizador:criar_editar_atividade_criar", args=[self.evento.id]),
            {
                "titulo": "Com tolerância",
                "descricao": "d",
                "local": "",
                "tipo": self.tipo.id,
                "palestrantes": [],
                "data_hora_inicio": inicio.strftime("%Y-%m-%dT%H:%M"),
                "data_hora_fim": (inicio + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
                "n_vagas": 10,
                "emite_certificado": False,
                "margem_presenca_antes_min": 5,
                "margem_presenca_depois_min": 6,
            },
        )
        self.assertEqual(resposta.status_code, 302)
        atividade = self.Atividade.objects.get(titulo="Com tolerância")
        self.assertEqual(atividade.margem_presenca_antes_min, 5)
        self.assertEqual(atividade.margem_presenca_depois_min, 6)


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


class AdicionarPalestranteJsonTests(TestCase):
    """JSON do modal de palestrante: success traz id/nome/foto; inválido, errors."""

    def setUp(self):
        self.org = U.objects.create_user(
            email="org_pal_json@example.com", password=SENHA, cpf="39053344705",
            is_organizador=True,
        )
        self.url = reverse("organizador:adicionar_palestrante")

    def test_sucesso_traz_id_nome_e_foto(self):
        self.client.force_login(self.org)
        resposta = self.client.post(self.url, {
            "first_name": "Ana", "last_name": "Souza",
            "email": "pal_json@example.com", "cpf": "11144477735",
        })
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()
        self.assertTrue(dados["success"])
        self.assertEqual(dados["nome"], "Ana Souza")
        self.assertIn("id", dados)
        self.assertTrue(dados["foto"])

    def test_invalido_traz_errors(self):
        self.client.force_login(self.org)
        resposta = self.client.post(self.url, {"first_name": "Sem email"})
        dados = resposta.json()
        self.assertFalse(dados["success"])
        self.assertIn("email", dados["errors"])

    def test_usa_senha_padrao_do_evento(self):
        evento = Evento.objects.create(
            title="Evento", description="d", local="l",
            data_inicio="2026-10-10", data_fim="2026-10-12", organizador=self.org,
            senha_padrao="@snct2026",
        )
        self.client.force_login(self.org)
        resposta = self.client.post(self.url, {
            "first_name": "Ana", "last_name": "Souza",
            "email": "pal_senha@example.com", "cpf": "11144477735",
            "evento_id": evento.id,
        })
        dados = resposta.json()
        self.assertTrue(dados["success"], dados)
        self.assertEqual(dados["senha"], "@snct2026")
        # A senha padrão realmente loga a pessoa.
        self.assertTrue(self.client.login(
            email="pal_senha@example.com", password="@snct2026"
        ))

    def test_senha_padrao_do_sistema_sem_evento(self):
        from django.conf import settings

        self.client.force_login(self.org)
        resposta = self.client.post(self.url, {
            "first_name": "Bia", "last_name": "Lima",
            "email": "pal_sem_evento@example.com", "cpf": "39053344705",
        })
        self.assertEqual(resposta.json()["senha"], settings.SENHA_PADRAO)


class NormalizarNomeTests(TestCase):
    """Nome completo digitado no campo "Nome" vira nome + sobrenome."""

    def test_nome_completo_no_first_name_e_dividido(self):
        pessoa = U.objects.create_user(
            email="nome@example.com", password=SENHA, cpf="11144477735",
            first_name="Maria da Silva", last_name="",
        )
        pessoa.refresh_from_db()
        self.assertEqual(pessoa.first_name, "Maria")
        self.assertEqual(pessoa.last_name, "da Silva")

    def test_nao_mexe_quando_o_sobrenome_foi_informado(self):
        pessoa = U.objects.create_user(
            email="nome2@example.com", password=SENHA, cpf="39053344705",
            first_name="Maria", last_name="Silva",
        )
        pessoa.refresh_from_db()
        self.assertEqual((pessoa.first_name, pessoa.last_name), ("Maria", "Silva"))

    def test_normaliza_mesmo_com_update_fields(self):
        pessoa = U.objects.create_user(
            email="nome3@example.com", password=SENHA, cpf="11144477735",
        )
        pessoa.first_name = "João Pedro"
        pessoa.last_name = ""
        pessoa.save(update_fields=["first_name", "last_name"])
        pessoa.refresh_from_db()
        self.assertEqual((pessoa.first_name, pessoa.last_name), ("João", "Pedro"))


class EventoFormSenhaPadraoTests(TestCase):
    """A senha padrão do evento passa pelo mesmo mínimo de uma senha de login."""

    def _dados(self, **extra):
        base = {
            "title": "Evento", "description": "d", "local": "l",
            "data_inicio": "2026-10-10", "data_fim": "2026-10-12",
            "categoria": "Tecnologia", "senha_padrao": "@snct2026",
        }
        base.update(extra)
        return base

    def test_senha_padrao_valida(self):
        from eventos.forms import EventoForm

        form = EventoForm(data=self._dados())
        self.assertTrue(form.is_valid(), form.errors)

    def test_senha_curta_e_rejeitada(self):
        from eventos.forms import EventoForm

        form = EventoForm(data=self._dados(senha_padrao="abc1"))
        self.assertFalse(form.is_valid())
        self.assertIn("senha_padrao", form.errors)

    def test_senha_so_numerica_e_rejeitada(self):
        from eventos.forms import EventoForm

        form = EventoForm(data=self._dados(senha_padrao="12345678"))
        self.assertFalse(form.is_valid())
        self.assertIn("senha_padrao", form.errors)


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
