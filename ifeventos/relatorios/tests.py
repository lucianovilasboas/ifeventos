"""Testes do relatório de inscrições: escopo, filtros e ordenação (server-side)."""

from datetime import date, datetime, timezone as tz

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from eventos.models import (
    Atividade,
    Evento,
    Inscricao,
    ParticipanteMetadados,
    TipoAtividade,
)

U = get_user_model()
SENHA = "SenhaForte123!"


class RelatorioInscricoesTests(TestCase):
    def setUp(self):
        self.org = U.objects.create_user(
            email="org_rel@example.com", password=SENHA, cpf="12345678909",
            is_organizador=True,
        )
        self.tipo = TipoAtividade.objects.create(nome="Palestra")

        def evento(titulo, dia):
            return Evento.objects.create(
                title=titulo, description="d", local="l",
                data_inicio=date(2026, 10, dia), data_fim=date(2026, 10, dia + 1),
                categoria="formacao", organizador=self.org,
            )

        def atividade(evento, titulo, dia):
            return Atividade.objects.create(
                evento=evento, titulo=titulo, descricao="d", tipo=self.tipo,
                data_hora_inicio=datetime(2026, 10, dia, 10, 0, tzinfo=tz.utc),
                data_hora_fim=datetime(2026, 10, dia, 11, 0, tzinfo=tz.utc),
                n_vagas=10,
            )

        self.evento_a = evento("Evento A", 1)
        self.evento_b = evento("Evento B", 5)
        self.atv_a1 = atividade(self.evento_a, "Abertura", 1)
        self.atv_a2 = atividade(self.evento_a, "Encerramento", 2)
        self.atv_b1 = atividade(self.evento_b, "Workshop", 5)

        self.p1 = U.objects.create_user(
            email="p1@example.com", password=SENHA, cpf="11144477735"
        )
        self.p2 = U.objects.create_user(
            email="p2@example.com", password=SENHA, cpf="12345678909"
        )
        Inscricao.objects.create(participante=self.p1, atividade=self.atv_a1, confirmada=True)
        Inscricao.objects.create(participante=self.p2, atividade=self.atv_a2, confirmada=False)
        Inscricao.objects.create(participante=self.p1, atividade=self.atv_b1, confirmada=True)

        self.client.force_login(self.org)

    def _url(self, evento=None):
        return reverse(
            "organizador:relatorio_inscricoes",
            kwargs={"evento_id": (evento or self.evento_a).id},
        )

    def test_escopo_pelo_evento_da_url(self):
        resposta = self.client.get(self._url())
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.context["total_inscricoes"], 2)

    def test_filtro_por_atividade(self):
        resposta = self.client.get(self._url(), {"atividade": self.atv_a1.id})
        self.assertEqual(resposta.context["total_inscricoes"], 1)
        self.assertEqual(resposta.context["inscricoes"][0].atividade_id, self.atv_a1.id)

    def test_troca_de_evento_por_query(self):
        resposta = self.client.get(self._url(), {"evento": self.evento_b.id})
        self.assertEqual(resposta.context["total_inscricoes"], 1)
        self.assertEqual(resposta.context["evento_selecionado"], self.evento_b.id)

    def test_ordenacao_server_side_por_atividade(self):
        crescente = self.client.get(self._url(), {"ordenar": "atividade", "dir": "asc"})
        titulos = [i.atividade.titulo for i in crescente.context["inscricoes"]]
        self.assertEqual(titulos, ["Abertura", "Encerramento"])

        decrescente = self.client.get(self._url(), {"ordenar": "atividade", "dir": "desc"})
        titulos = [i.atividade.titulo for i in decrescente.context["inscricoes"]]
        self.assertEqual(titulos, ["Encerramento", "Abertura"])

    def test_atividades_do_filtro_sao_do_evento_selecionado(self):
        resposta = self.client.get(self._url())
        ids = {a.id for a in resposta.context["atividades"]}
        self.assertEqual(ids, {self.atv_a1.id, self.atv_a2.id})


class MetadadosNosRelatoriosTests(TestCase):
    """As colunas de metadados configurados aparecem (e podem ser escondidas)."""

    def setUp(self):
        self.org = U.objects.create_user(
            email="org_meta@example.com", password=SENHA, cpf="12345678909",
            is_organizador=True,
        )
        self.tipo = TipoAtividade.objects.create(nome="Palestra")
        self.evento = Evento.objects.create(
            title="Evento Meta", description="d", local="l",
            data_inicio=date(2026, 10, 1), data_fim=date(2026, 10, 2),
            categoria="formacao", organizador=self.org,
        )
        self.atividade = Atividade.objects.create(
            evento=self.evento, titulo="Abertura", descricao="d", tipo=self.tipo,
            data_hora_inicio=datetime(2026, 10, 1, 10, 0, tzinfo=tz.utc),
            data_hora_fim=datetime(2026, 10, 1, 11, 0, tzinfo=tz.utc),
            n_vagas=10,
        )
        self.aluno = U.objects.create_user(
            email="aluno@example.com", password=SENHA, cpf="11144477735",
            first_name="Aluna", last_name="Teste",
        )
        ParticipanteMetadados.objects.create(
            participante=self.aluno,
            dados={"matricula": "2026001", "curso": "Informática", "turma": "B"},
        )
        Inscricao.objects.create(
            participante=self.aluno, atividade=self.atividade, confirmada=True
        )
        self.client.force_login(self.org)

    def _lista_presenca(self, **params):
        return self.client.get(
            reverse(
                "organizador:relatorio_lista_presenca",
                kwargs={"atividade_id": self.atividade.id},
            ),
            params,
        )

    def test_lista_presenca_mostra_colunas_configuradas(self):
        html = self._lista_presenca().content.decode()
        self.assertIn("Matrícula", html)
        self.assertIn("2026001", html)
        self.assertIn("Informática", html)

    def test_lista_presenca_respeita_selecao_de_colunas(self):
        html = self._lista_presenca(campos="matricula").content.decode()
        # "Curso" ainda aparece no seletor de colunas, mas não como coluna.
        self.assertIn("<th>Matrícula</th>", html)
        self.assertNotIn("<th>Curso</th>", html)

    def test_relatorio_inscricoes_mostra_metadados(self):
        resposta = self.client.get(
            reverse("organizador:relatorio_inscricoes", kwargs={"evento_id": self.evento.id})
        )
        html = resposta.content.decode()
        self.assertIn("Matrícula", html)
        self.assertIn("2026001", html)


class ExportacaoRelatoriosTests(TestCase):
    """Exportação CSV/XLSX/PDF respeitando a seleção de colunas."""

    def setUp(self):
        self.org = U.objects.create_user(
            email="org_exp@example.com", password=SENHA, cpf="12345678909",
            is_organizador=True,
        )
        self.tipo = TipoAtividade.objects.create(nome="Palestra")
        self.evento = Evento.objects.create(
            title="Evento Exp", description="d", local="l",
            data_inicio=date(2026, 10, 1), data_fim=date(2026, 10, 2),
            categoria="formacao", organizador=self.org,
        )
        self.atividade = Atividade.objects.create(
            evento=self.evento, titulo="Abertura", descricao="d", tipo=self.tipo,
            data_hora_inicio=datetime(2026, 10, 1, 10, 0, tzinfo=tz.utc),
            data_hora_fim=datetime(2026, 10, 1, 11, 0, tzinfo=tz.utc),
            n_vagas=10,
        )
        self.aluno = U.objects.create_user(
            email="aluno@example.com", password=SENHA, cpf="11144477735",
            first_name="Aluna", last_name="Teste",
        )
        ParticipanteMetadados.objects.create(
            participante=self.aluno,
            dados={"vinculo": "Aluno", "matricula": "2026001", "curso": "Informática"},
        )
        Inscricao.objects.create(
            participante=self.aluno, atividade=self.atividade, confirmada=True
        )
        self.client.force_login(self.org)

    def _inscricoes(self, **params):
        return self.client.get(
            reverse("organizador:relatorio_inscricoes", kwargs={"evento_id": self.evento.id}),
            params,
        )

    def _lista_presenca(self, **params):
        return self.client.get(
            reverse("organizador:relatorio_lista_presenca",
                    kwargs={"atividade_id": self.atividade.id}),
            params,
        )

    def test_csv(self):
        resposta = self._inscricoes(export="csv")
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("text/csv", resposta["Content-Type"])
        texto = resposta.content.decode("utf-8-sig")
        self.assertIn("Matrícula", texto)
        self.assertIn("2026001", texto)

    def test_xlsx(self):
        resposta = self._inscricoes(export="xlsx")
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("spreadsheetml", resposta["Content-Type"])
        self.assertEqual(resposta.content[:2], b"PK")  # assinatura de zip/xlsx

    def test_pdf(self):
        resposta = self._inscricoes(export="pdf")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta["Content-Type"], "application/pdf")
        self.assertEqual(resposta.content[:4], b"%PDF")

    def test_export_respeita_selecao_de_colunas(self):
        resposta = self._inscricoes(export="csv", campos="matricula")
        cabecalho = resposta.content.decode("utf-8-sig").splitlines()[0]
        self.assertIn("Matrícula", cabecalho)
        self.assertNotIn("Curso", cabecalho)

    def test_lista_presenca_csv(self):
        resposta = self._lista_presenca(export="csv")
        self.assertEqual(resposta.status_code, 200)
        texto = resposta.content.decode("utf-8-sig")
        self.assertIn("Matrícula", texto)
        self.assertIn("2026001", texto)
