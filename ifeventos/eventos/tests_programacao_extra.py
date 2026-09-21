"""Testes da importação da programação, do rascunho e das exportações."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from eventos import importacao_programacao as imp
from eventos.models import Atividade, Evento, TipoAtividade

U = get_user_model()


def linha(**kwargs):
    base = {
        "titulo": "Abertura", "descricao": "Sessão", "tipo": "Palestra",
        "local": "Auditório", "inicio": "05/10/2026 08:00", "fim": "05/10/2026 09:00",
        "n_vagas": "50", "emite_certificado": "sim", "palestrantes": "",
    }
    base.update(kwargs)
    return base


class ImportacaoProgramacaoTests(TestCase):
    def setUp(self):
        self.evento = Evento.objects.create(
            title="Mostra", description="d", local="Campus",
            data_inicio="2026-10-05", data_fim="2026-10-05",
        )
        self.tipo = TipoAtividade.objects.create(nome="Palestra")

    def test_cria_e_atualiza_sem_duplicar(self):
        relatorio = imp.importar_linhas(self.evento, [linha()])
        self.assertEqual(relatorio["criadas"], 1)
        self.assertEqual(relatorio["erros"], 0)

        atividade = Atividade.objects.get()
        self.assertTrue(atividade.emite_certificado)
        self.assertEqual(atividade.n_vagas, 50)
        self.assertEqual(atividade.tipo, self.tipo)

        # Chave = título + início: rodar de novo ATUALIZA.
        relatorio = imp.importar_linhas(self.evento, [linha(**{"n_vagas": "70"})])
        self.assertEqual(relatorio["atualizadas"], 1)
        self.assertEqual(Atividade.objects.count(), 1)
        self.assertEqual(Atividade.objects.get().n_vagas, 70)

    def test_tipo_inexistente_e_erro(self):
        relatorio = imp.importar_linhas(self.evento, [linha(**{"tipo": "Fantasma"})])
        self.assertEqual(relatorio["erros"], 1)
        self.assertEqual(Atividade.objects.count(), 0)

    def test_datas_invalidas_e_fim_antes_do_inicio(self):
        relatorio = imp.importar_linhas(self.evento, [
            linha(**{"inicio": "ontem", "fim": "hoje"}),
            linha(**{"inicio": "05/10/2026 10:00", "fim": "05/10/2026 09:00"}),
        ])
        self.assertEqual(relatorio["erros"], 2)

    def test_palestrante_sem_conta_avisa_e_nao_quebra(self):
        relatorio = imp.importar_linhas(
            self.evento, [linha(**{"palestrantes": "ninguem@example.com"})]
        )
        self.assertEqual(relatorio["criadas"], 1)
        self.assertTrue(relatorio["linhas"][0]["avisos"])

    def test_sem_titulo_e_erro(self):
        relatorio = imp.importar_linhas(self.evento, [linha(**{"titulo": ""})])
        self.assertEqual(relatorio["erros"], 1)


class RascunhoTests(TestCase):
    def setUp(self):
        self.evento = Evento.objects.create(
            title="Mostra", description="d", local="Campus",
            data_inicio="2026-10-05", data_fim="2026-10-05",
        )
        self.tipo = TipoAtividade.objects.create(nome="Oficina")
        self.publicada = Atividade.objects.create(
            evento=self.evento, titulo="Publicada", descricao="d", tipo=self.tipo,
            data_hora_inicio=timezone.now() + timezone.timedelta(days=1),
            data_hora_fim=timezone.now() + timezone.timedelta(days=1, hours=1),
            n_vagas=10, publicada=True,
        )
        self.rascunho = Atividade.objects.create(
            evento=self.evento, titulo="Rascunho interno", descricao="d", tipo=self.tipo,
            data_hora_inicio=timezone.now() + timezone.timedelta(days=2),
            data_hora_fim=timezone.now() + timezone.timedelta(days=2, hours=1),
            n_vagas=10, publicada=False,
        )
        self.org = U.objects.create_user(
            email="org@example.com", password="SenhaForte123!",
            is_organizador=True, is_staff=True,
        )

    def test_programacao_publica_esconde_rascunho(self):
        html = self.client.get(
            reverse("eventos:programacao", args=[self.evento.id])
        ).content.decode()
        self.assertIn("Publicada", html)
        self.assertNotIn("Rascunho interno", html)

    def test_organizador_alterna_rascunho(self):
        self.client.force_login(self.org)
        url = reverse("organizador:publicar_atividade", args=[self.rascunho.id])
        self.client.post(url)
        self.rascunho.refresh_from_db()
        self.assertTrue(self.rascunho.publicada)
        self.client.post(url)
        self.rascunho.refresh_from_db()
        self.assertFalse(self.rascunho.publicada)


class ExportacoesTests(TestCase):
    def setUp(self):
        self.evento = Evento.objects.create(
            title="Mostra", description="d", local="Campus",
            data_inicio="2026-10-05", data_fim="2026-10-05",
        )
        self.tipo = TipoAtividade.objects.create(nome="Oficina")
        self.a = Atividade.objects.create(
            evento=self.evento, titulo="Oficina A", descricao="d", tipo=self.tipo,
            local="Auditório", n_vagas=20, n_inscricoes=5,
            data_hora_inicio=timezone.now() + timezone.timedelta(days=1),
            data_hora_fim=timezone.now() + timezone.timedelta(days=1, hours=1),
        )
        self.org = U.objects.create_user(
            email="org2@example.com", password="SenhaForte123!", is_organizador=True
        )
        # Com o escopo por evento, o organizador precisa ser dono (ou co-organizador).
        self.evento.organizador = self.org
        self.evento.save(update_fields=["organizador"])

    def test_pdf_da_programacao(self):
        resposta = self.client.get(
            reverse("eventos:programacao_pdf", args=[self.evento.id])
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta["Content-Type"], "application/pdf")

    def test_ics_de_uma_atividade(self):
        resposta = self.client.get(
            reverse("eventos:atividade_ics", args=[self.a.id])
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta["Content-Type"].startswith("text/calendar"))
        self.assertIn("BEGIN:VEVENT", resposta.content.decode())

    def test_ocupacao_por_sala(self):
        self.client.force_login(self.org)
        resposta = self.client.get(
            reverse("organizador:ocupacao_salas", args=[self.evento.id])
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Auditório")

        exportado = self.client.get(
            reverse("organizador:ocupacao_salas", args=[self.evento.id]) + "?export=csv"
        )
        self.assertEqual(exportado.status_code, 200)
        self.assertIn("text/csv", exportado["Content-Type"])
