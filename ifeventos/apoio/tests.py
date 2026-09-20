"""Testes da equipe de apoio (papel `is_equipe` + `Evento.equipe`)."""

from datetime import datetime, timedelta, timezone as tz

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from allauth.account.models import EmailAddress

from eventos.models import Atividade, Evento, TipoAtividade

U = get_user_model()
SENHA = "SenhaForte123!"


def _novo_usuario(email, **flags):
    base = {"email": email, "password": SENHA, "cpf": ""}
    base.update(flags)
    return U.objects.create_user(**base)


class EquipeApoioBase(TestCase):
    def setUp(self):
        self.org = _novo_usuario("org_equipe@example.com", cpf="12345678909", is_organizador=True)
        self.equipe = _novo_usuario("equipe@example.com", cpf="11144477735", is_equipe=True)
        self.fora = _novo_usuario("fora@example.com", cpf="52998224725", is_equipe=True)
        self.tipo = TipoAtividade.objects.create(nome="Palestra")
        self.evento = Evento.objects.create(
            title="Evento Equipe", description="d", local="Campus",
            data_inicio="2026-10-10", data_fim="2026-10-12",
            organizador=self.org,
        )
        self.evento.equipe.add(self.equipe)
        self.outro = Evento.objects.create(
            title="Outro Evento", description="d", local="l",
            data_inicio="2026-10-10", data_fim="2026-10-12",
            organizador=self.org,
        )
        self.atividade = Atividade.objects.create(
            evento=self.evento, titulo="Palestra A", descricao="d", tipo=self.tipo,
            data_hora_inicio=datetime(2026, 10, 10, 10, 0, tzinfo=tz.utc),
            data_hora_fim=datetime(2026, 10, 10, 11, 0, tzinfo=tz.utc),
            n_vagas=10,
        )


class PermissoesDeCheckinTests(EquipeApoioBase, TestCase):
    def test_equipe_do_evento_abre_checkin(self):
        self.client.force_login(self.equipe)
        resposta = self.client.get(
            reverse("organizador:checkin_atividade", args=[self.atividade.id])
        )
        self.assertEqual(resposta.status_code, 200)

    def test_equipe_de_outro_evento_nao_abre_checkin(self):
        self.client.force_login(self.fora)
        resposta = self.client.get(
            reverse("organizador:checkin_atividade", args=[self.atividade.id])
        )
        self.assertEqual(resposta.status_code, 403)

    def test_equipe_exibe_qr_de_presenca(self):
        self.client.force_login(self.equipe)
        resposta = self.client.get(
            reverse("organizador:qrcode_atividade", args=[self.atividade.id])
        )
        self.assertEqual(resposta.status_code, 200)

    def test_equipe_nao_gerencia_o_evento(self):
        # Rotas de gestão do evento exigem o dono (get_user_and_evento → 404).
        self.client.force_login(self.equipe)
        resposta = self.client.get(
            reverse("organizador:editar_evento", args=[self.evento.id])
        )
        self.assertEqual(resposta.status_code, 404)


class PainelDeApoioTests(EquipeApoioBase, TestCase):
    def test_painel_lista_so_eventos_vinculados(self):
        self.client.force_login(self.equipe)
        html = self.client.get(reverse("apoio:dashboard")).content.decode()
        self.assertIn("Evento Equipe", html)
        self.assertNotIn("Outro Evento", html)

    def test_evento_do_apoio_lista_atividades_publicadas(self):
        self.client.force_login(self.equipe)
        html = self.client.get(reverse("apoio:evento", args=[self.evento.id])).content.decode()
        self.assertIn("Palestra A", html)
        self.assertIn(reverse("organizador:checkin_atividade", args=[self.atividade.id]), html)

    def test_equipe_de_outro_evento_nao_ve_este_evento(self):
        self.client.force_login(self.fora)
        resposta = self.client.get(reverse("apoio:evento", args=[self.evento.id]))
        self.assertEqual(resposta.status_code, 403)


class GestaoDaEquipeTests(EquipeApoioBase, TestCase):
    def _adicionar(self, email):
        return self.client.post(
            reverse("organizador:equipe_apoio_adicionar", args=[self.evento.id]),
            {"email": email},
        )

    def test_adicionar_reaproveita_conta_existente(self):
        self.client.force_login(self.org)
        pessoa = _novo_usuario("nova_pessoa@example.com", cpf="12345678909")
        resposta = self._adicionar(pessoa.email)
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()
        self.assertTrue(dados["reusada"])
        self.assertIsNone(dados["senha_temporaria"])
        pessoa.refresh_from_db()
        self.assertTrue(pessoa.is_equipe)
        self.assertIn(pessoa, self.evento.equipe.all())

    def test_adicionar_cria_conta_minima_para_email_novo(self):
        self.client.force_login(self.org)
        resposta = self._adicionar("ajudante@example.com")
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()
        self.assertFalse(dados["reusada"])
        self.assertTrue(dados["senha_temporaria"])
        pessoa = U.objects.get(email="ajudante@example.com")
        self.assertTrue(pessoa.is_equipe)
        self.assertFalse(pessoa.is_participante)
        self.assertIn(pessoa, self.evento.equipe.all())
        # O e-mail nasce verificado: com ACCOUNT_EMAIL_VERIFICATION='mandatory'
        # a conta precisa estar pronta para entrar sem confirmar e-mail.
        endereco = EmailAddress.objects.get(user=pessoa, email=pessoa.email)
        self.assertTrue(endereco.verified)
        self.assertTrue(endereco.primary)
        # A senha temporária realmente loga.
        self.assertTrue(self.client.login(email="ajudante@example.com",
                                           password=dados["senha_temporaria"]))

    def test_remover_tira_do_evento_mas_nao_apaga_conta(self):
        self.client.force_login(self.org)
        resposta = self.client.post(
            reverse("organizador:equipe_apoio_remover", args=[self.evento.id]),
            {"pessoa_id": self.equipe.id},
        )
        self.assertEqual(resposta.status_code, 200)
        self.equipe.refresh_from_db()
        self.assertTrue(U.objects.filter(id=self.equipe.id).exists())
        self.assertNotIn(self.equipe, self.evento.equipe.all())

    def test_nao_organizador_nao_adiciona_equipe(self):
        self.client.force_login(self.equipe)
        resposta = self._adicionar("x@example.com")
        self.assertEqual(resposta.status_code, 404)  # get_user_and_evento recusa