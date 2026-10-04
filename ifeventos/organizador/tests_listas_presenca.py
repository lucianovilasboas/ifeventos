"""Testes das listas de presença em PDF (folha de assinatura).

Cobre autorização, o PDF de uma atividade, o PDF de todas as publicadas
(uma página por atividade) e a presença dos botões nas telas do organizador.
"""

from datetime import date, timedelta
from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfReader

from eventos.models import Atividade, Evento, Inscricao, ParticipanteMetadados

U = get_user_model()
SENHA = "SenhaLista123!"


def _ler_pdf(conteudo):
    """Devolve (texto, nº de páginas) do PDF em bytes."""
    leitor = PdfReader(BytesIO(conteudo))
    texto = "\n".join((pagina.extract_text() or "") for pagina in leitor.pages)
    return texto, len(leitor.pages)


class ListasPresencaPDFTests(TestCase):
    def setUp(self):
        self.org = U.objects.create_user(
            email="org@lp.test", password=SENHA, is_organizador=True
        )
        self.outro_org = U.objects.create_user(
            email="outro@lp.test", password=SENHA, is_organizador=True
        )
        self.ana = U.objects.create_user(
            email="ana@lp.test", password=SENHA,
            first_name="Ana", last_name="Silva",
        )
        hoje = date.today()
        self.evento = Evento.objects.create(
            title="Evento Listas", description="d", local="Auditório",
            data_inicio=hoje, data_fim=hoje, organizador=self.org,
        )
        agora = timezone.now()
        self.pub1 = Atividade.objects.create(
            evento=self.evento, titulo="Oficina Alfa", descricao="d",
            data_hora_inicio=agora, data_hora_fim=agora + timedelta(hours=1),
            n_vagas=10, publicada=True,
        )
        self.pub2 = Atividade.objects.create(
            evento=self.evento, titulo="Oficina Beta", descricao="d",
            data_hora_inicio=agora + timedelta(hours=2),
            data_hora_fim=agora + timedelta(hours=3), n_vagas=10, publicada=True,
        )
        self.rascunho = Atividade.objects.create(
            evento=self.evento, titulo="Rascunho Secreto", descricao="d",
            data_hora_inicio=agora, data_hora_fim=agora + timedelta(hours=1),
            n_vagas=10, publicada=False,
        )
        Inscricao.objects.create(participante=self.ana, atividade=self.pub1)

    def _url_atividade(self, atividade):
        return reverse("organizador:lista_presenca_pdf", args=[atividade.id])

    def _url_evento(self):
        return reverse("organizador:listas_presenca_evento_pdf", args=[self.evento.id])

    # ---------------- PDF de uma atividade ----------------
    def test_pdf_da_atividade_tem_nome_e_assinatura(self):
        self.client.force_login(self.org)
        resp = self.client.get(self._url_atividade(self.pub1))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertIn("inline", resp["Content-Disposition"])

        texto, _ = _ler_pdf(resp.content)
        self.assertIn("Oficina Alfa", texto)
        self.assertIn("Ana Silva", texto)
        self.assertIn("Assinatura", texto)

    def test_pdf_da_atividade_nao_expoe_email(self):
        self.client.force_login(self.org)
        resp = self.client.get(self._url_atividade(self.pub1))
        texto, _ = _ler_pdf(resp.content)
        self.assertNotIn("ana@lp.test", texto)

    def test_pdf_da_atividade_mostra_vinculo_no_nome(self):
        ParticipanteMetadados.objects.create(
            participante=self.ana,
            dados={"vinculo": "Aluno", "matricula": "1", "curso": "Informática",
                   "turma": "Turma 1", "ano": "Primeiro ano"},
        )
        self.client.force_login(self.org)
        texto, _ = _ler_pdf(self.client.get(self._url_atividade(self.pub1)).content)
        self.assertIn("Ana Silva (Aluno/Informática-Turma 1-Primeiro ano)", texto)

    def test_pdf_agrupado_tem_cabecalhos_de_vinculo_e_turma(self):
        ParticipanteMetadados.objects.create(
            participante=self.ana,
            dados={"vinculo": "Aluno", "matricula": "1", "curso": "Informática",
                   "turma": "Turma 1", "ano": "Primeiro ano"},
        )
        self.client.force_login(self.org)
        resp = self.client.get(self._url_atividade(self.pub1) + "?agrupar=1")
        texto, _ = _ler_pdf(resp.content)
        self.assertIn("Aluno", texto)
        self.assertIn("Informática", texto)
        self.assertIn("Turma 1", texto)

    def _com_metadados(self):
        ParticipanteMetadados.objects.create(
            participante=self.ana,
            dados={"vinculo": "Aluno", "matricula": "1", "curso": "Informática",
                   "turma": "Turma 1", "ano": "Primeiro ano"},
        )

    def test_pdf_modo_simples_mostra_so_o_nome(self):
        self._com_metadados()
        self.client.force_login(self.org)
        resp = self.client.get(self._url_atividade(self.pub1) + "?modo=simples")
        texto, _ = _ler_pdf(resp.content)
        self.assertIn("Ana Silva", texto)
        self.assertNotIn("Aluno", texto)

    def test_pdf_modo_agrupada_linha_sem_vinculo(self):
        self._com_metadados()
        self.client.force_login(self.org)
        resp = self.client.get(self._url_atividade(self.pub1) + "?modo=agrupada")
        texto, _ = _ler_pdf(resp.content)
        self.assertIn("Aluno", texto)          # cabeçalho do grupo
        self.assertIn("Informática", texto)    # cabeçalho do 2º nível
        self.assertNotIn("Ana Silva (Aluno", texto)  # linha sai com o nome simples

    def test_botoes_da_lista_oferecem_os_tres_modos(self):
        self.client.force_login(self.org)
        resp = self.client.get(
            reverse("organizador:atividades_evento", args=[self.evento.id])
        )
        self.assertContains(resp, "?modo=simples")
        self.assertContains(resp, "?modo=agrupada")
        self.assertContains(resp, "?modo=vinculo")

    def test_cartao_do_dashboard_oferece_os_modos(self):
        self.client.force_login(self.org)
        resp = self.client.get(reverse("organizador:dashboard"))
        self.assertContains(resp, "?modo=agrupada")

    def test_sem_permissao_recebe_403(self):
        self.client.force_login(self.outro_org)
        resp = self.client.get(self._url_atividade(self.pub1))
        self.assertEqual(resp.status_code, 403)

    # ---------------- PDF do evento (todas) ----------------
    def test_pdf_do_evento_uma_pagina_por_atividade_publicada(self):
        self.client.force_login(self.org)
        resp = self.client.get(self._url_evento())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")

        texto, paginas = _ler_pdf(resp.content)
        self.assertEqual(paginas, 2)  # duas publicadas
        self.assertIn("Oficina Alfa", texto)
        self.assertIn("Oficina Beta", texto)
        self.assertNotIn("Rascunho Secreto", texto)

    def test_pdf_do_evento_sem_publicadas_avisa_e_volta(self):
        vazio = Evento.objects.create(
            title="Evento Vazio", description="d", local="Sala",
            data_inicio=date.today(), data_fim=date.today(), organizador=self.org,
        )
        self.client.force_login(self.org)
        resp = self.client.get(
            reverse("organizador:listas_presenca_evento_pdf", args=[vazio.id])
        )
        self.assertEqual(resp.status_code, 302)

    def test_pdf_do_evento_sem_permissao_recebe_403(self):
        self.client.force_login(self.outro_org)
        resp = self.client.get(self._url_evento())
        self.assertEqual(resp.status_code, 403)

    # ---------------- botões nas telas ----------------
    def test_botao_no_cartao_do_dashboard(self):
        self.client.force_login(self.org)
        resp = self.client.get(reverse("organizador:dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self._url_evento())

    def test_botoes_na_tela_de_atividades(self):
        self.client.force_login(self.org)
        resp = self.client.get(
            reverse("organizador:atividades_evento", args=[self.evento.id])
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self._url_evento())
        self.assertContains(resp, self._url_atividade(self.pub1))
