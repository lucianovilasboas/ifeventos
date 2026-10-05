from datetime import date, datetime, timezone as tz

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from eventos.models import Atividade, Evento, Inscricao, ParticipanteMetadados, TipoAtividade


class ListaPresencaPreparacaoTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.org = User.objects.create_user(email="org-prep@test.local", password="x", is_organizador=True)
        self.aluno = User.objects.create_user(
            email="aluno-prep@test.local", password="x", first_name="Ana", last_name="Silva"
        )
        self.outro = User.objects.create_user(
            email="outro-prep@test.local", password="x", first_name="Bruno", last_name="Lima"
        )
        ParticipanteMetadados.objects.create(
            participante=self.aluno,
            dados={"vinculo": "Aluno", "curso": "Informática", "turma": "Turma 1", "ano": "Primeiro ano"},
        )
        self.evento = Evento.objects.create(
            title="Evento Preparação", description="d", local="Auditório",
            data_inicio=date(2026, 10, 10), data_fim=date(2026, 10, 11),
            categoria="formacao", organizador=self.org,
        )
        tipo = TipoAtividade.objects.create(nome="Oficina")
        self.atividade = Atividade.objects.create(
            evento=self.evento, titulo="Oficina A", descricao="d", tipo=tipo,
            data_hora_inicio=datetime(2026, 10, 10, 10, tzinfo=tz.utc),
            data_hora_fim=datetime(2026, 10, 10, 11, tzinfo=tz.utc), publicada=True,
        )
        Inscricao.objects.create(participante=self.aluno, atividade=self.atividade, confirmada=True)
        Inscricao.objects.create(participante=self.outro, atividade=self.atividade, confirmada=False)
        self.url = reverse("organizador:listas_presenca_preparar", args=[self.evento.id])

    def test_tela_exige_permissao(self):
        self.client.force_login(self.outro)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_tela_padrao_mostra_confirmados_agrupados(self):
        self.client.force_login(self.org)
        resposta = self.client.get(self.url)
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Ana Silva")
        self.assertNotContains(resposta, "Bruno Lima")
        self.assertContains(resposta, "Informática")
        self.assertContains(resposta, "Turma 1 — Primeiro ano")

    def test_filtro_por_dia_e_lista_de_confirmacao(self):
        self.client.force_login(self.org)
        resposta = self.client.get(self.url, {"dia": "2026-10-10", "tipo": "confirmacao"})
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Confirmação de presença")
        self.assertContains(resposta, "10/10/2026")
        self.assertNotContains(resposta, "Assinatura</th>")

    def test_situacao_sem_confirmacao(self):
        self.client.force_login(self.org)
        resposta = self.client.get(self.url, {"situacao": "sem_confirmacao"})
        self.assertContains(resposta, "Bruno Lima")
        self.assertNotContains(resposta, "Ana Silva")

    def test_pdf_da_nova_tela(self):
        self.client.force_login(self.org)
        resposta = self.client.get(self.url, {"tipo": "confirmacao", "export": "pdf"})
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta["Content-Type"], "application/pdf")
        self.assertTrue(resposta.content.startswith(b"%PDF"))
        from io import BytesIO
        from pypdf import PdfReader
        texto = "\n".join(p.extract_text() or "" for p in PdfReader(BytesIO(resposta.content)).pages)
        self.assertIn("Ana Silva", texto)
