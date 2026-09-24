"""Testes da trilha de auditoria (models, signals, middleware, máscaras)."""

from datetime import date

from django.contrib import admin
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from eventos import auditoria
from eventos.admin import RegistroAuditoriaAdmin
from eventos.middleware import AuditoriaContextoMiddleware
from eventos.models import Evento, RegistroAuditoria


def _evento(organizador, **kwargs):
    dados = dict(
        title="Evento Aud", description="d", local="Sala",
        data_inicio=date(2026, 10, 10), data_fim=date(2026, 10, 12),
    )
    dados.update(kwargs)
    return Evento.objects.create(organizador=organizador, **dados)


class MascarasTests(TestCase):
    def test_mascarar_cpf(self):
        self.assertEqual(auditoria.mascarar_cpf("12345678901"), "***.***.789-**")
        self.assertEqual(auditoria.mascarar_cpf(""), "")
        self.assertEqual(auditoria.mascarar_cpf("123"), "***")

    def test_mascarar_email(self):
        self.assertEqual(auditoria.mascarar_email("fulano@ifmg.edu.br"), "f***@ifmg.edu.br")
        self.assertEqual(auditoria.mascarar_email("semarroba"), "***")

    def test_detalhes_sanitizados(self):
        auditoria.registrar(
            acao="criar",
            detalhes={"cpf": "12345678901", "email": "a@b.com", "senha": "x"},
        )
        linha = RegistroAuditoria.objects.latest("id")
        self.assertIn("***", linha.detalhes["cpf"])
        self.assertTrue(linha.detalhes["email"].startswith("a***"))
        self.assertEqual(linha.detalhes["senha"], "***")


class RegistrarTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        self.dono = get_user_model().objects.create_user(
            email="dono@aud.test", password="SenhaForte123!", is_organizador=True
        )
        self.evento = _evento(self.dono)

    def test_registrar_deriva_objeto(self):
        auditoria.registrar(
            acao="criar", objeto=self.evento, usuario=self.dono, resumo="teste"
        )
        linha = RegistroAuditoria.objects.latest("id")
        self.assertEqual(linha.entidade, "Evento")
        self.assertEqual(linha.objeto_id, str(self.evento.id))
        self.assertEqual(linha.usuario, self.dono)
        self.assertEqual(linha.evento, self.evento)
        self.assertIn("dono@aud.test", linha.usuario_email)

    def test_registrar_nunca_levanta(self):
        from unittest import mock

        # Se a gravação falhar, `registrar` engole o erro (auditoria é acessória).
        with mock.patch.object(
            RegistroAuditoria.objects, "create", side_effect=RuntimeError("boom")
        ):
            auditoria.registrar(acao="criar")  # não pode levantar


class MiddlewareTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        self.dono = get_user_model().objects.create_user(
            email="dono@mw.test", password="SenhaForte123!"
        )

    def test_seta_e_limpa_contexto(self):
        capturado = {}

        def view(request):
            capturado["usuario"] = auditoria.usuario_atual()
            capturado["rid"] = auditoria.request_id_atual()
            return HttpResponse("ok")

        request = RequestFactory().get("/organizador/")
        request.user = self.dono
        resposta = AuditoriaContextoMiddleware(view)(request)

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(capturado["usuario"], self.dono)
        self.assertIsNotNone(capturado["rid"])
        # Depois da resposta o contexto é limpo.
        self.assertIsNone(auditoria.usuario_atual())

    def test_origem_por_path(self):
        from eventos.models import RegistroAuditoria as R

        self.assertEqual(auditoria._origem(RequestFactory().get("/admin/x")), R.ORIGEM_ADMIN)
        self.assertEqual(auditoria._origem(RequestFactory().get("/api/v1/x")), R.ORIGEM_API)
        self.assertEqual(auditoria._origem(RequestFactory().get("/organizador/x")), R.ORIGEM_WEB)
        self.assertEqual(auditoria._origem(None), R.ORIGEM_SISTEMA)


class SignalsTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        self.dono = get_user_model().objects.create_user(
            email="dono@sig.test", password="SenhaForte123!", is_organizador=True
        )

    def test_criar_evento(self):
        evento = _evento(self.dono, title="Novo")
        linha = RegistroAuditoria.objects.filter(
            entidade="Evento", objeto_id=str(evento.id), acao="criar"
        ).first()
        self.assertIsNotNone(linha)

    def test_editar_evento_guarda_diff(self):
        evento = _evento(self.dono, title="Antes")
        RegistroAuditoria.objects.all().delete()
        evento.title = "Depois"
        evento.save()
        linha = RegistroAuditoria.objects.filter(
            entidade="Evento", objeto_id=str(evento.id), acao="editar"
        ).first()
        self.assertIsNotNone(linha)
        diff = linha.detalhes["alteracoes"]["title"]
        self.assertEqual(diff["antes"], "Antes")
        self.assertEqual(diff["depois"], "Depois")

    def test_editar_sem_mudanca_nao_registra(self):
        evento = _evento(self.dono, title="Igual")
        RegistroAuditoria.objects.all().delete()
        evento.save()  # nada relevante mudou
        self.assertFalse(
            RegistroAuditoria.objects.filter(acao="editar", entidade="Evento").exists()
        )

    def test_excluir_evento(self):
        evento = _evento(self.dono, title="Some")
        RegistroAuditoria.objects.all().delete()
        evento_id = evento.id
        evento.delete()
        self.assertTrue(
            RegistroAuditoria.objects.filter(
                entidade="Evento", objeto_id=str(evento_id), acao="excluir"
            ).exists()
        )

    def test_login_registrado(self):
        self.client.force_login(self.dono)
        self.assertTrue(
            RegistroAuditoria.objects.filter(
                acao="login", usuario=self.dono
            ).exists()
        )


class AdminTests(TestCase):
    def test_admin_somente_leitura(self):
        instancia = RegistroAuditoriaAdmin(RegistroAuditoria, admin.site)
        self.assertFalse(instancia.has_add_permission(None))
        self.assertFalse(instancia.has_change_permission(None))
        self.assertFalse(instancia.has_delete_permission(None))
        self.assertIn(RegistroAuditoria, admin.site._registry)
