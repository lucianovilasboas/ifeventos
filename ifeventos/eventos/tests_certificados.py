"""Testes dos certificados: elegibilidade, render e telas de configuração."""

from datetime import date, datetime
from datetime import timezone as tz

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from eventos import certificados
from eventos.models import (
    Atividade,
    ConfiguracaoCertificado,
    Evento,
    Inscricao,
    Presenca,
)

U = get_user_model()
SENHA = "SenhaForte123!"


def _evento(organizador, **kwargs):
    dados = dict(
        title="Evento Cert", description="d", local="Auditório",
        data_inicio=date(2026, 10, 10), data_fim=date(2026, 10, 12),
    )
    dados.update(kwargs)
    return Evento.objects.create(organizador=organizador, **dados)


def _atividade(evento, **kwargs):
    dados = dict(
        titulo="Atividade", descricao="d", local="Sala",
        data_hora_inicio=datetime(2026, 10, 10, 10, 0, tzinfo=tz.utc),
        data_hora_fim=datetime(2026, 10, 10, 11, 0, tzinfo=tz.utc),
        n_vagas=10, emite_certificado=True,
    )
    dados.update(kwargs)
    return Atividade.objects.create(evento=evento, **dados)


class ElegibilidadeTests(TestCase):
    def setUp(self):
        self.dono = U.objects.create_user(email="dono@cert.test", password=SENHA, is_organizador=True)
        self.evento = _evento(self.dono)
        self.pessoa = U.objects.create_user(email="p@cert.test", password=SENHA)

    def test_atividade_sem_emite_certificado_nao_elegivel(self):
        a = _atividade(self.evento, emite_certificado=False)
        Presenca.objects.create(atividade=a, participante=self.pessoa)
        self.assertFalse(certificados.participantes_da_atividade(a).exists())

    def test_presenca_torna_elegivel(self):
        a = _atividade(self.evento)
        Presenca.objects.create(atividade=a, participante=self.pessoa)
        self.assertIn(self.pessoa, certificados.participantes_da_atividade(a))

    def test_inscricao_confirmada_torna_elegivel(self):
        a = _atividade(self.evento)
        Inscricao.objects.create(atividade=a, participante=self.pessoa, confirmada=True)
        self.assertIn(self.pessoa, certificados.participantes_da_atividade(a))

    def test_evento_por_percentual(self):
        a1 = _atividade(self.evento, titulo="A1")
        a2 = _atividade(self.evento, titulo="A2")
        a3 = _atividade(self.evento, titulo="A3")
        a4 = _atividade(self.evento, titulo="A4")
        # 3 de 4 = 75% -> elegível; outro com 2 de 4 = 50% -> não.
        for a in (a1, a2, a3):
            Presenca.objects.create(atividade=a, participante=self.pessoa)
        outro = U.objects.create_user(email="q@cert.test", password=SENHA)
        for a in (a1, a2):
            Presenca.objects.create(atividade=a, participante=outro)
        elegiveis = set(certificados.participantes_do_evento(self.evento))
        self.assertIn(self.pessoa, elegiveis)
        self.assertNotIn(outro, elegiveis)

    def test_limiar_configuravel(self):
        self.evento.percentual_certificado = 50
        self.evento.save(update_fields=["percentual_certificado"])
        a1 = _atividade(self.evento, titulo="A1")
        _atividade(self.evento, titulo="A2")
        Presenca.objects.create(atividade=a1, participante=self.pessoa)
        self.assertIn(self.pessoa, certificados.participantes_do_evento(self.evento))


class RenderTests(TestCase):
    def setUp(self):
        self.dono = U.objects.create_user(email="dono2@cert.test", password=SENHA, is_organizador=True)
        self.evento = _evento(self.dono)

    def test_render_pdf_gera_pdf_valido(self):
        config = ConfiguracaoCertificado.objects.create(
            evento=self.evento, titulo="CERTIFICADO",
            corpo="Certificamos que {{nome}} participou de {{atividade}} ({{carga_horaria}}).",
        )
        contexto = certificados.contexto_certificado(self.dono, evento=self.evento, config=config)
        dados = certificados.render_pdf(contexto, config)
        self.assertTrue(dados.startswith(b"%PDF"))

    def test_substituir_variaveis(self):
        texto = certificados.substituir_variaveis("Oi {{nome}}!", {"nome": "Ana"})
        self.assertEqual(texto, "Oi Ana!")


class ConfigViewTests(TestCase):
    def setUp(self):
        self.dono = U.objects.create_user(email="dono3@cert.test", password=SENHA, is_organizador=True)
        self.evento = _evento(self.dono)
        self.participante = U.objects.create_user(email="x@cert.test", password=SENHA)

    def test_participante_recebe_403(self):
        self.client.force_login(self.participante)
        r = self.client.get(reverse("organizador:certificado_config", args=[self.evento.id]))
        self.assertEqual(r.status_code, 403)

    def test_dono_abre_e_salva(self):
        self.client.force_login(self.dono)
        url = reverse("organizador:certificado_config", args=[self.evento.id])
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        r = self.client.post(url, {
            "titulo": "CERTIFICADO DE PARTICIPAÇÃO",
            "corpo": "Certificamos que {{nome}}.",
            "modo_layout": "fundo",
            "enviar_email": "on",
            "assinaturas-TOTAL_FORMS": "2",
            "assinaturas-INITIAL_FORMS": "0",
            "assinaturas-MIN_NUM_FORMS": "0",
            "assinaturas-MAX_NUM_FORMS": "2",
            "assinaturas-0-nome": "Diretor Geral",
            "assinaturas-0-cargo": "Diretor",
            "assinaturas-1-nome": "",
            "assinaturas-1-cargo": "",
        })
        self.assertEqual(r.status_code, 302)
        config = ConfiguracaoCertificado.objects.get(evento=self.evento)
        self.assertEqual(config.assinaturas.count(), 1)

    def test_preview_retorna_pdf(self):
        self.client.force_login(self.dono)
        r = self.client.get(reverse("organizador:certificado_preview", args=[self.evento.id]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertTrue(r.content.startswith(b"%PDF"))
