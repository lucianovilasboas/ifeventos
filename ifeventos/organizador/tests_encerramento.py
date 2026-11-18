"""Encerramento explícito: checklist, arquivamento e desarquivamento."""

from datetime import date, datetime, timedelta, timezone as tz

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from eventos import encerramento
from eventos.models import (
    Atividade,
    Evento,
    Inscricao,
    RegistroAuditoria,
    TipoAtividade,
)

U = get_user_model()
SENHA = "SenhaForte123!"


class EncerramentoEventoTests(TestCase):
    def setUp(self):
        hoje = date.today()
        self.org = U.objects.create_user(
            email="org_encerra@example.com", password=SENHA, cpf="12345678909",
            is_organizador=True,
        )
        self.outro = U.objects.create_user(
            email="outro_encerra@example.com", password=SENHA, cpf="39053344705",
            is_organizador=True,
        )
        self.part = U.objects.create_user(
            email="part_encerra@example.com", password=SENHA, cpf="11144477735",
        )
        self.tipo = TipoAtividade.objects.create(nome="Oficina encerramento")
        self.evento = Evento.objects.create(
            title="Evento Encerramento", description="d", local="Campus",
            data_inicio=hoje - timedelta(days=3), data_fim=hoje - timedelta(days=2),
            organizador=self.org,
        )
        self.atividade = Atividade.objects.create(
            evento=self.evento, titulo="Oficina A", descricao="d", tipo=self.tipo,
            data_hora_inicio=datetime.combine(
                hoje - timedelta(days=3), datetime.min.time(), tzinfo=tz.utc
            ),
            data_hora_fim=datetime.combine(
                hoje - timedelta(days=2), datetime.min.time(), tzinfo=tz.utc
            ),
            n_vagas=10,
        )
        self.url = reverse("organizador:encerrar_evento", args=[self.evento.id])
        self.dashboard = reverse("organizador:dashboard")
        self.client.force_login(self.org)

    def _encerrar(self, **extra):
        dados = {"confirmado": "on"}
        dados.update(extra)
        return self.client.post(self.url, dados)

    def test_data_vencida_nao_arquiva_sozinha(self):
        self.evento.refresh_from_db()
        self.assertFalse(self.evento.arquivado)
        self.assertTrue(self.evento.aguardando_encerramento)

        resposta = self.client.get(self.dashboard)

        self.assertEqual(resposta.context["evento_padrao"].id, self.evento.id)
        self.assertContains(resposta, "Aguardando arquivamento")

    def test_tela_de_confirmacao_mostra_o_checklist(self):
        resposta = self.client.get(self.url)

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Checklist de arquivamento")
        self.assertContains(resposta, "Atividades publicadas")
        self.assertContains(resposta, "Certificados das atividades")
        self.assertContains(resposta, 'name="confirmado"')

    def test_rascunho_bloqueia_o_encerramento(self):
        Atividade.objects.create(
            evento=self.evento, titulo="Rascunho", descricao="d", tipo=self.tipo,
            data_hora_inicio=datetime.now(tz.utc),
            data_hora_fim=datetime.now(tz.utc) + timedelta(hours=1),
            n_vagas=10, publicada=False,
        )

        resposta = self._encerrar()

        self.assertEqual(resposta.status_code, 400)
        self.evento.refresh_from_db()
        self.assertFalse(self.evento.arquivado)
        self.assertContains(
            resposta, "pendências que impedem o arquivamento", status_code=400
        )

    def test_proposta_pendente_bloqueia_o_encerramento(self):
        Atividade.objects.create(
            evento=self.evento, titulo="Proposta", descricao="d", tipo=self.tipo,
            data_hora_inicio=datetime.now(tz.utc),
            data_hora_fim=datetime.now(tz.utc) + timedelta(hours=1),
            n_vagas=10, situacao=Atividade.SITUACAO_PENDENTE,
        )

        resposta = self._encerrar()

        self.assertEqual(resposta.status_code, 400)
        self.evento.refresh_from_db()
        self.assertFalse(self.evento.arquivado)

    def test_certificado_pendente_apenas_avisa(self):
        self.atividade.emite_certificado = True
        self.atividade.save(update_fields=["emite_certificado"])
        Inscricao.objects.create(
            participante=self.part, atividade=self.atividade, confirmada=True
        )

        item = next(
            i for i in encerramento.checklist(self.evento)
            if i.chave == "certificados_atividade"
        )
        self.assertFalse(item.ok)
        self.assertFalse(item.bloqueante)

        resposta = self._encerrar()

        self.assertRedirects(resposta, self.dashboard)
        self.evento.refresh_from_db()
        self.assertTrue(self.evento.arquivado)

    def test_sem_confirmacao_nao_encerra(self):
        resposta = self.client.post(self.url, {})

        self.assertEqual(resposta.status_code, 400)
        self.evento.refresh_from_db()
        self.assertFalse(self.evento.arquivado)

    def test_encerrar_grava_autor_e_auditoria(self):
        self._encerrar()

        self.evento.refresh_from_db()
        self.assertIsNotNone(self.evento.arquivado_em)
        self.assertEqual(self.evento.arquivado_por_id, self.org.id)

        registro = RegistroAuditoria.objects.filter(
            acao=RegistroAuditoria.ACAO_ENCERRAR_EVENTO,
            objeto_id=str(self.evento.id),
        ).first()
        self.assertIsNotNone(registro)
        self.assertEqual(registro.detalhes["data_fim"], self.evento.data_fim.isoformat())

    def test_encerrado_sai_do_destaque_e_vai_para_o_arquivo(self):
        self._encerrar()

        resposta = self.client.get(self.dashboard)

        self.assertIn(self.evento, resposta.context["eventos_arquivados"])
        self.assertIsNone(resposta.context["evento_padrao"])
        self.assertContains(resposta, "Eventos arquivados")
        self.assertContains(
            resposta,
            reverse("organizador:desarquivar_evento", args=[self.evento.id]),
        )

    def test_desarquivar_devolve_ao_fluxo(self):
        self._encerrar()

        resposta = self.client.post(
            reverse("organizador:desarquivar_evento", args=[self.evento.id])
        )

        self.assertRedirects(resposta, self.dashboard)
        self.evento.refresh_from_db()
        self.assertIsNone(self.evento.arquivado_em)
        self.assertIsNone(self.evento.arquivado_por_id)
        self.assertTrue(
            RegistroAuditoria.objects.filter(
                acao=RegistroAuditoria.ACAO_DESARQUIVAR_EVENTO,
                objeto_id=str(self.evento.id),
            ).exists()
        )

        resposta = self.client.get(self.dashboard)
        self.assertIn(self.evento, resposta.context["eventos_a_encerrar"])
        self.assertNotIn(self.evento, resposta.context["eventos_arquivados"])

    def test_evento_ja_arquivado_nao_reencerra(self):
        self._encerrar()

        resposta = self.client.get(self.url)

        self.assertRedirects(resposta, self.dashboard)

    def test_evento_futuro_pode_encerrar_com_aviso(self):
        futuro = Evento.objects.create(
            title="Evento Futuro", description="d", local="Campus",
            data_inicio=date.today() + timedelta(days=5),
            data_fim=date.today() + timedelta(days=6),
            organizador=self.org,
        )
        url = reverse("organizador:encerrar_evento", args=[futuro.id])

        resposta = self.client.get(url)
        self.assertContains(resposta, "ainda não encerrou")

        resposta = self.client.post(url, {"confirmado": "on"})
        self.assertRedirects(resposta, self.dashboard)
        futuro.refresh_from_db()
        self.assertTrue(futuro.arquivado)

    def test_somente_quem_gerencia_encerra_e_desarquiva(self):
        self.client.force_login(self.outro)

        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(
            self.client.post(self.url, {"confirmado": "on"}).status_code, 403
        )
        self.assertEqual(
            self.client.post(
                reverse("organizador:desarquivar_evento", args=[self.evento.id])
            ).status_code,
            403,
        )

        self.evento.refresh_from_db()
        self.assertFalse(self.evento.arquivado)

    def test_coorganizador_encerra(self):
        self.evento.organizadores.add(self.outro)
        self.client.force_login(self.outro)

        resposta = self._encerrar()

        self.assertRedirects(resposta, self.dashboard)
        self.evento.refresh_from_db()
        self.assertTrue(self.evento.arquivado)


class ChecklistTests(TestCase):
    """O checklist não bloqueia por certificado, mas bloqueia o operacional."""

    def setUp(self):
        hoje = date.today()
        self.org = U.objects.create_user(
            email="org_check@example.com", password=SENHA, cpf="12345678909",
            is_organizador=True,
        )
        self.tipo = TipoAtividade.objects.create(nome="Checklist")
        self.evento = Evento.objects.create(
            title="Evento Checklist", description="d", local="Campus",
            data_inicio=hoje - timedelta(days=2), data_fim=hoje - timedelta(days=1),
            organizador=self.org,
        )

    def test_evento_sem_atividade_avisa_mas_nao_bloqueia(self):
        itens = {i.chave: i for i in encerramento.checklist(self.evento)}

        self.assertFalse(itens["atividades_publicadas"].ok)
        self.assertFalse(itens["atividades_publicadas"].bloqueante)
        self.assertTrue(encerramento.pode_encerrar(self.evento))

    def test_certificados_do_evento_sem_elegiveis_ficam_ok(self):
        itens = {i.chave: i for i in encerramento.checklist(self.evento)}

        self.assertTrue(itens["certificados_evento"].ok)
        self.assertIn("certificados_funcao", itens)

    def test_evento_nao_terminado_nao_lista_certificados(self):
        futuro = Evento.objects.create(
            title="Futuro", description="d", local="Campus",
            data_inicio=date.today() + timedelta(days=2),
            data_fim=date.today() + timedelta(days=3),
            organizador=self.org,
        )

        chaves = {i.chave for i in encerramento.checklist(futuro)}

        self.assertNotIn("certificados_atividade", chaves)
        self.assertNotIn("certificados_evento", chaves)
