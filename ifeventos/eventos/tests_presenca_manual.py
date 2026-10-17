"""Testes da marcação manual de presença (checkbox da Lista de Presença)."""

import json
from datetime import date, datetime
from datetime import timezone as tz

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from eventos.models import (
    Atividade,
    Certificado,
    Evento,
    Inscricao,
    Presenca,
    PresencaCancelada,
    RegistroAuditoria,
)

U = get_user_model()
SENHA = "SenhaForte123!"


def _evento(organizador, **kwargs):
    dados = dict(
        title="Evento Presença", description="d", local="Auditório",
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


class PresencaManualTests(TestCase):
    def setUp(self):
        self.dono = U.objects.create_user(
            email="donopm@cert.test", password=SENHA, is_organizador=True
        )
        self.co = U.objects.create_user(
            email="copm@cert.test", password=SENHA, is_organizador=True
        )
        self.equipe = U.objects.create_user(
            email="eqpm@cert.test", password=SENHA, is_equipe=True
        )
        self.evento = _evento(self.dono)
        self.evento.organizadores.add(self.co)
        self.evento.equipe.add(self.equipe)
        self.atividade = _atividade(self.evento)
        self.pessoa = U.objects.create_user(email="alunopm@cert.test", password=SENHA)
        Inscricao.objects.create(
            participante=self.pessoa, atividade=self.atividade, confirmada=False
        )

    def _url(self):
        return reverse(
            "organizador:presenca_manual",
            args=[self.atividade.id, self.pessoa.id],
        )

    def _post(self, presente=True):
        return self.client.post(
            self._url(), data=json.dumps({"presente": presente}),
            content_type="application/json",
        )

    def test_organizador_marca_presenca_manual(self):
        self.client.force_login(self.dono)
        r = self._post(True)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        presenca = Presenca.objects.get(atividade=self.atividade, participante=self.pessoa)
        self.assertEqual(presenca.origem, "manual")
        self.assertEqual(presenca.registrada_por, self.dono)
        # Marcação manual também confirma a inscrição (via Presenca.save).
        self.assertTrue(
            Inscricao.objects.get(participante=self.pessoa, atividade=self.atividade).confirmada
        )

    def test_marcacao_grava_auditoria(self):
        self.client.force_login(self.dono)
        self._post(True)
        self.assertTrue(
            RegistroAuditoria.objects.filter(
                acao=RegistroAuditoria.ACAO_REGISTRAR_PRESENCA
            ).exists()
        )

    def test_coorganizador_pode_marcar(self):
        self.client.force_login(self.co)
        self.assertEqual(self._post(True).status_code, 200)
        self.assertTrue(
            Presenca.objects.filter(atividade=self.atividade, participante=self.pessoa).exists()
        )

    def test_equipe_e_participante_recebem_403(self):
        self.client.force_login(self.equipe)
        self.assertEqual(self._post(True).status_code, 403)
        self.client.force_login(self.pessoa)
        self.assertEqual(self._post(True).status_code, 403)
        self.assertFalse(
            Presenca.objects.filter(atividade=self.atividade, participante=self.pessoa).exists()
        )

    def test_marcar_e_idempotente(self):
        self.client.force_login(self.dono)
        self._post(True)
        r = self._post(True)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            Presenca.objects.filter(atividade=self.atividade, participante=self.pessoa).count(), 1
        )

    def test_desmarcar_remove_e_guarda_historico(self):
        self.client.force_login(self.dono)
        self._post(True)
        r = self._post(False)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["presente"])
        self.assertFalse(
            Presenca.objects.filter(atividade=self.atividade, participante=self.pessoa).exists()
        )
        self.assertTrue(
            PresencaCancelada.objects.filter(
                atividade=self.atividade, participante=self.pessoa
            ).exists()
        )

    def test_desmarcar_com_certificado_pede_confirmacao(self):
        self.client.force_login(self.dono)
        self._post(True)
        Certificado.objects.create(
            participante=self.pessoa, atividade=self.atividade, tipo="atividade"
        )
        r = self._post(False)
        self.assertEqual(r.status_code, 409)
        d = r.json()
        self.assertTrue(d["certificado"])
        self.assertEqual(len(d["certificados"]), 1)
        # A presença permanece (só remove com confirmação).
        self.assertTrue(
            Presenca.objects.filter(atividade=self.atividade, participante=self.pessoa).exists()
        )

    def test_desmarcar_removendo_certificado(self):
        self.client.force_login(self.dono)
        self._post(True)
        certificado = Certificado.objects.create(
            participante=self.pessoa, atividade=self.atividade, tipo="atividade"
        )
        r = self.client.post(
            self._url(),
            data=json.dumps({"presente": False, "remover_certificado": True}),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.assertFalse(Certificado.objects.filter(id=certificado.id).exists())
        self.assertFalse(
            Presenca.objects.filter(atividade=self.atividade, participante=self.pessoa).exists()
        )
        self.assertTrue(
            RegistroAuditoria.objects.filter(
                acao=RegistroAuditoria.ACAO_REMOVER_CERTIFICADO
            ).exists()
        )

    def test_certificado_de_funcao_nao_bloqueia_desmarque(self):
        self.client.force_login(self.dono)
        self._post(True)
        # Certificado de FUNÇÃO não depende da presença.
        Certificado.objects.create(
            participante=self.pessoa, evento=self.evento, tipo="funcao", funcao="palestrante"
        )
        r = self._post(False)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(
            Presenca.objects.filter(atividade=self.atividade, participante=self.pessoa).exists()
        )
        # O certificado de função continua existindo.
        self.assertTrue(
            Certificado.objects.filter(participante=self.pessoa, funcao="palestrante").exists()
        )

    def test_certificados_que_dependem_so_atividade_e_evento(self):
        from eventos.inscricoes import certificados_que_dependem

        atividade_cert = Certificado.objects.create(
            participante=self.pessoa, atividade=self.atividade, tipo="atividade"
        )
        evento_cert = Certificado.objects.create(
            participante=self.pessoa, evento=self.evento, tipo="evento"
        )
        Certificado.objects.create(
            participante=self.pessoa, evento=self.evento, tipo="funcao", funcao="palestrante"
        )
        ids = set(
            certificados_que_dependem(self.pessoa, self.atividade).values_list("id", flat=True)
        )
        self.assertEqual(ids, {atividade_cert.id, evento_cert.id})

    def test_lista_presenca_expoe_tem_presenca(self):
        self.client.force_login(self.dono)
        self._post(True)
        r = self.client.get(
            reverse("organizador:relatorio_lista_presenca", args=[self.atividade.id])
        )
        self.assertEqual(r.status_code, 200)
        inscricao = r.context["inscricoes"][0]
        self.assertTrue(inscricao.tem_presenca)
