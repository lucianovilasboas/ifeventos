"""Testes da emissão assíncrona de certificados (fila em banco + worker)."""

import shutil
import tempfile
from datetime import date, datetime, timedelta
from datetime import timezone as tz
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from eventos import certificados
from eventos import emissao_certificados as emissao
from eventos.models import (
    Atividade,
    Certificado,
    CertificadoJob,
    Evento,
    Presenca,
)

U = get_user_model()
SENHA = "SenhaForte123!"


def _evento(organizador, **kwargs):
    dados = dict(
        title="Evento Async", description="d", local="Auditório",
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


class EmissaoAsyncTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls._media = tempfile.mkdtemp(prefix="media_async_")
        cls.enterClassContext(override_settings(MEDIA_ROOT=cls._media))
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(cls._media, ignore_errors=True)

    def setUp(self):
        self.dono = U.objects.create_user(
            email="donoa@cert.test", password=SENHA, is_organizador=True
        )
        self.evento = _evento(self.dono)
        self.atividade = _atividade(self.evento)
        self.pessoas = []
        for i in range(4):
            pessoa = U.objects.create_user(email=f"pa{i}@cert.test", password=SENHA)
            Presenca.objects.create(atividade=self.atividade, participante=pessoa)
            self.pessoas.append(pessoa)

    # -- enfileirar / total -------------------------------------------------

    def test_enfileirar_total_por_escopo(self):
        j1 = emissao.enfileirar_job(
            escopo=CertificadoJob.ESCOPO_ATIVIDADE, evento=self.evento,
            atividade=self.atividade, criado_por=self.dono,
        )
        self.assertEqual(j1.total, 4)

        j2 = emissao.enfileirar_job(
            escopo=CertificadoJob.ESCOPO_TODAS, evento=self.evento, criado_por=self.dono
        )
        self.assertEqual(j2.total, 4)

        # Função palestrante: 2 pessoas marcadas como palestrantes.
        self.atividade.palestrantes.add(self.pessoas[0], self.pessoas[1])
        j3 = emissao.enfileirar_job(
            escopo=CertificadoJob.ESCOPO_FUNCAO, evento=self.evento,
            funcao="palestrante", criado_por=self.dono,
        )
        self.assertEqual(j3.total, 2)

        # Individual: só uma pessoa.
        j4 = emissao.enfileirar_job(
            escopo=CertificadoJob.ESCOPO_FUNCAO, evento=self.evento,
            funcao="palestrante", participante=self.pessoas[0], criado_por=self.dono,
        )
        self.assertEqual(j4.total, 1)

    # -- processamento ------------------------------------------------------

    def test_processar_job_gera_e_atualiza_contadores(self):
        job = emissao.enfileirar_job(
            escopo=CertificadoJob.ESCOPO_ATIVIDADE, evento=self.evento,
            atividade=self.atividade, criado_por=self.dono,
        )
        emissao.processar_job(job)
        job.refresh_from_db()
        self.assertEqual(job.status, CertificadoJob.STATUS_CONCLUIDO)
        self.assertEqual(job.processados, 4)
        self.assertEqual(job.gerados, 4)
        self.assertEqual(job.falhas, [])
        self.assertEqual(Certificado.objects.filter(atividade=self.atividade).count(), 4)

    def test_processar_job_falha_isolada_nao_aborta(self):
        job = emissao.enfileirar_job(
            escopo=CertificadoJob.ESCOPO_ATIVIDADE, evento=self.evento,
            atividade=self.atividade, criado_por=self.dono,
        )
        real = certificados.emitir
        alvo = self.pessoas[0].id

        def fake(pessoa, *, atividade=None, evento=None, funcao=None):
            if pessoa.id == alvo:
                raise certificados.CertificadoLayoutError("falhou de propósito")
            return real(pessoa, atividade=atividade, evento=evento, funcao=funcao)

        with mock.patch.object(certificados, "emitir", side_effect=fake):
            emissao.processar_job(job)

        job.refresh_from_db()
        self.assertEqual(job.status, CertificadoJob.STATUS_CONCLUIDO)
        self.assertEqual(job.gerados, 3)
        self.assertEqual(len(job.falhas), 1)
        self.assertEqual(job.processados, 4)

    def test_iniciar_job_ate_3_processa_inline(self):
        pequena = _atividade(self.evento, titulo="Pequena")
        for pessoa in self.pessoas[:2]:
            Presenca.objects.create(atividade=pequena, participante=pessoa)
        job, pronto = emissao.iniciar_job(
            escopo=CertificadoJob.ESCOPO_ATIVIDADE, evento=self.evento,
            atividade=pequena, criado_por=self.dono,
        )
        self.assertTrue(pronto)
        self.assertEqual(job.status, CertificadoJob.STATUS_CONCLUIDO)
        self.assertEqual(job.gerados, 2)

    def test_iniciar_job_grande_fica_pendente(self):
        job, pronto = emissao.iniciar_job(
            escopo=CertificadoJob.ESCOPO_ATIVIDADE, evento=self.evento,
            atividade=self.atividade, criado_por=self.dono,
        )
        self.assertFalse(pronto)
        self.assertEqual(job.status, CertificadoJob.STATUS_PENDENTE)
        self.assertEqual(Certificado.objects.count(), 0)

    @override_settings(CERTIFICADOS_LIMITE_SINCRONO=0)
    def test_limite_zero_sempre_pela_fila(self):
        pequena = _atividade(self.evento, titulo="Pequena")
        Presenca.objects.create(atividade=pequena, participante=self.pessoas[0])
        job, pronto = emissao.iniciar_job(
            escopo=CertificadoJob.ESCOPO_ATIVIDADE, evento=self.evento,
            atividade=pequena, criado_por=self.dono,
        )
        self.assertFalse(pronto)  # 1 > 0 → fila (mostra a barra)
        self.assertEqual(job.total, 1)
        self.assertEqual(job.status, CertificadoJob.STATUS_PENDENTE)

    @override_settings(CERTIFICADOS_LIMITE_SINCRONO=1)
    def test_limite_configuravel_1(self):
        pequena = _atividade(self.evento, titulo="Pequena")
        Presenca.objects.create(atividade=pequena, participante=self.pessoas[0])
        _j, pronto = emissao.iniciar_job(
            escopo=CertificadoJob.ESCOPO_ATIVIDADE, evento=self.evento,
            atividade=pequena, criado_por=self.dono,
        )
        self.assertTrue(pronto)  # 1 ≤ 1

        media = _atividade(self.evento, titulo="Média")
        Presenca.objects.create(atividade=media, participante=self.pessoas[0])
        Presenca.objects.create(atividade=media, participante=self.pessoas[1])
        j2, pronto2 = emissao.iniciar_job(
            escopo=CertificadoJob.ESCOPO_ATIVIDADE, evento=self.evento,
            atividade=media, criado_por=self.dono,
        )
        self.assertFalse(pronto2)  # 2 > 1
        self.assertEqual(j2.total, 2)

    def test_limite_por_evento_sobrepoe_o_global(self):
        # Global = 3; evento com limite 0 → 1 certificado vai pela fila.
        self.evento.certificado_limite_sincrono = 0
        self.evento.save(update_fields=["certificado_limite_sincrono"])
        pequena = _atividade(self.evento, titulo="Pequena")
        Presenca.objects.create(atividade=pequena, participante=self.pessoas[0])
        job, pronto = emissao.iniciar_job(
            escopo=CertificadoJob.ESCOPO_ATIVIDADE, evento=self.evento,
            atividade=pequena, criado_por=self.dono,
        )
        self.assertFalse(pronto)
        self.assertEqual(job.total, 1)
        self.assertEqual(job.status, CertificadoJob.STATUS_PENDENTE)

    @override_settings(CERTIFICADOS_LIMITE_SINCRONO=0)
    def test_limite_por_evento_alto_gera_inline(self):
        # Global = 0, mas evento com limite 10 → 4 certificados inline.
        self.evento.certificado_limite_sincrono = 10
        self.evento.save(update_fields=["certificado_limite_sincrono"])
        job, pronto = emissao.iniciar_job(
            escopo=CertificadoJob.ESCOPO_ATIVIDADE, evento=self.evento,
            atividade=self.atividade, criado_por=self.dono,
        )
        self.assertTrue(pronto)
        self.assertEqual(job.gerados, 4)

    # -- worker: claim / reciclagem ----------------------------------------

    def test_processar_proximo_job_claim_e_fim_da_fila(self):
        j1 = emissao.enfileirar_job(
            escopo=CertificadoJob.ESCOPO_ATIVIDADE, evento=self.evento,
            atividade=self.atividade, criado_por=self.dono,
        )
        j2 = emissao.enfileirar_job(
            escopo=CertificadoJob.ESCOPO_EVENTO, evento=self.evento, criado_por=self.dono,
        )
        self.assertIsNotNone(emissao.processar_proximo_job())
        self.assertIsNotNone(emissao.processar_proximo_job())
        self.assertIsNone(emissao.processar_proximo_job())
        j1.refresh_from_db()
        j2.refresh_from_db()
        self.assertEqual(j1.status, CertificadoJob.STATUS_CONCLUIDO)
        self.assertEqual(j2.status, CertificadoJob.STATUS_CONCLUIDO)

    def test_reciclar_presos(self):
        job = emissao.enfileirar_job(
            escopo=CertificadoJob.ESCOPO_ATIVIDADE, evento=self.evento,
            atividade=self.atividade, criado_por=self.dono,
        )
        CertificadoJob.objects.filter(pk=job.pk).update(
            status=CertificadoJob.STATUS_PROCESSANDO,
            iniciado_em=timezone.now() - timedelta(minutes=60),
        )
        self.assertEqual(emissao.reciclar_presos(), 1)
        job.refresh_from_db()
        self.assertEqual(job.status, CertificadoJob.STATUS_PENDENTE)

    # -- views --------------------------------------------------------------

    def test_endpoint_enfileira_job(self):
        self.client.force_login(self.dono)
        r = self.client.post(
            reverse("organizador:emitir_certificados_atividade", args=[self.atividade.id])
        )
        self.assertEqual(r.status_code, 200)
        dados = r.json()
        self.assertFalse(dados["pronto"])
        self.assertEqual(dados["total"], 4)
        self.assertTrue(CertificadoJob.objects.filter(id=dados["job_id"]).exists())

    def test_endpoint_lote_pequeno_responde_pronto(self):
        pequena = _atividade(self.evento, titulo="Pequena")
        Presenca.objects.create(atividade=pequena, participante=self.pessoas[0])
        self.client.force_login(self.dono)
        r = self.client.post(
            reverse("organizador:emitir_certificados_atividade", args=[pequena.id])
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["pronto"])
        self.assertTrue(
            Certificado.objects.filter(participante=self.pessoas[0], atividade=pequena).exists()
        )

    def test_status_view(self):
        job = emissao.enfileirar_job(
            escopo=CertificadoJob.ESCOPO_ATIVIDADE, evento=self.evento,
            atividade=self.atividade, criado_por=self.dono,
        )
        self.client.force_login(self.dono)
        r = self.client.get(
            reverse("organizador:certificado_job_status", args=[job.id])
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["total"], 4)

    def test_status_view_permissao_e_404(self):
        job = emissao.enfileirar_job(
            escopo=CertificadoJob.ESCOPO_ATIVIDADE, evento=self.evento,
            atividade=self.atividade, criado_por=self.dono,
        )
        intruso = U.objects.create_user(email="intrusoa@cert.test", password=SENHA)
        self.client.force_login(intruso)
        r = self.client.get(
            reverse("organizador:certificado_job_status", args=[job.id])
        )
        self.assertEqual(r.status_code, 403)
        self.client.force_login(self.dono)
        r2 = self.client.get(
            reverse("organizador:certificado_job_status", args=[999999])
        )
        self.assertEqual(r2.status_code, 404)
