"""Testes do relatório de inscrições: escopo, busca livre e ordenação."""

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

        def atividade(evento, titulo, dia, local=""):
            return Atividade.objects.create(
                evento=evento, titulo=titulo, descricao="d", tipo=self.tipo,
                local=local,
                data_hora_inicio=datetime(2026, 10, dia, 10, 0, tzinfo=tz.utc),
                data_hora_fim=datetime(2026, 10, dia, 11, 0, tzinfo=tz.utc),
                n_vagas=10,
            )

        self.evento_a = evento("Evento A", 1)
        self.evento_b = evento("Evento B", 5)
        self.atv_a1 = atividade(self.evento_a, "Abertura", 1, local="Auditório")
        self.atv_a2 = atividade(self.evento_a, "Encerramento", 2, local="Sala 2")
        self.atv_b1 = atividade(self.evento_b, "Workshop", 5, local="Laboratório")

        self.p1 = U.objects.create_user(
            email="ana@example.com", password=SENHA, cpf="11144477735",
            first_name="Ana", last_name="Souza",
        )
        self.p2 = U.objects.create_user(
            email="bruno@example.com", password=SENHA, cpf="12345678909",
            first_name="Bruno", last_name="Lima",
        )
        ParticipanteMetadados.objects.create(
            participante=self.p2,
            dados={"vinculo": "Aluno", "matricula": "2026001", "curso": "TPG"},
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

    def _buscar(self, termo):
        return self.client.get(self._url(), {"q": termo})

    def test_escopo_pelo_evento_da_url(self):
        resposta = self.client.get(self._url())
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.context["total_inscricoes"], 2)

    def test_busca_por_nome(self):
        resposta = self._buscar("Ana")
        self.assertEqual(resposta.context["total_inscricoes"], 1)
        self.assertEqual(resposta.context["inscricoes"][0].participante_id, self.p1.id)

    def test_busca_por_email(self):
        resposta = self._buscar("bruno@")
        self.assertEqual(resposta.context["total_inscricoes"], 1)
        self.assertEqual(resposta.context["inscricoes"][0].participante_id, self.p2.id)

    def test_busca_por_atividade(self):
        resposta = self._buscar("Abertura")
        self.assertEqual(resposta.context["total_inscricoes"], 1)
        self.assertEqual(resposta.context["inscricoes"][0].atividade_id, self.atv_a1.id)

    def test_busca_por_metadado(self):
        resposta = self._buscar("2026001")
        self.assertEqual(resposta.context["total_inscricoes"], 1)
        self.assertEqual(resposta.context["inscricoes"][0].participante_id, self.p2.id)

    def test_busca_com_multiplos_termos_e_and(self):
        # "Ana Souza" casa na mesma linha; "Bruno Abertura" exigiria uma única
        # inscrição com os dois termos (Bruno só está em "Encerramento").
        self.assertEqual(self._buscar("Ana Souza").context["total_inscricoes"], 1)
        self.assertEqual(self._buscar("Bruno Abertura").context["total_inscricoes"], 0)

    def test_sem_busca_traz_tudo(self):
        self.assertEqual(self._buscar("").context["total_inscricoes"], 2)
        self.assertEqual(self.client.get(self._url()).context["total_inscricoes"], 2)

    def test_ajax_devolve_apenas_o_trecho(self):
        resposta = self.client.get(
            self._url(), {"q": "Ana"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertTemplateUsed(resposta, "relatorios/_resultado_inscricoes.html")
        self.assertEqual(resposta.context["total_inscricoes"], 1)
        html = resposta.content.decode()
        # Sem o formulário (o input fica vivo na página) nem a página inteira.
        self.assertNotIn("<form", html)
        self.assertNotIn("<html", html)
        self.assertIn("Total de Inscrições", html)

    def test_pagina_inteira_traz_formulario_e_alvo_do_ajax(self):
        html = self.client.get(self._url()).content.decode()
        self.assertIn("data-busca-ajax", html)
        self.assertIn('id="resultado-inscricoes"', html)
        self.assertNotIn("<datalist", html)

    def test_tabela_e_card_mostram_o_local(self):
        html = self.client.get(self._url()).content.decode()
        self.assertIn(">Local</a>", html)      # cabeçalho ordenável da tabela
        self.assertIn("Auditório", html)       # célula (tabela) / linha (card)
        self.assertIn("Sala 2", html)

    def test_card_mobile_mostra_os_metadados(self):
        # O card repete as colunas de metadados da tabela (matrícula do Bruno).
        html = self.client.get(self._url()).content.decode()
        self.assertIn("Matrícula: 2026001", html)

    def test_evento_pode_ser_ocultado(self):
        # Todas as linhas são do mesmo evento, então a coluna Evento é opcional.
        visivel = self.client.get(self._url())
        self.assertEqual(
            [c["rotulo"] for c in visivel.context["colunas"]],
            ["Participante", "Atividade", "Local", "Evento", "Confirmada", "Certificado"],
        )
        self.assertIn("ocultar=evento", visivel.content.decode())  # botão p/ esconder
        self.assertIn("Evento A", visivel.content.decode())

        oculto = self.client.get(self._url(), {"ocultar": "evento"})
        self.assertEqual(
            [c["rotulo"] for c in oculto.context["colunas"]],
            ["Participante", "Atividade", "Local", "Confirmada", "Certificado"],
        )
        self.assertEqual(oculto.context["ocultas"], {"evento"})
        self.assertEqual(oculto.context["colspan_vazio"], 6)
        html = oculto.content.decode()
        self.assertNotIn("Evento A", html)          # nem na tabela nem no card
        self.assertIn(">Local</a>", html)          # as demais colunas continuam

    def test_exportacao_respeita_o_evento_oculto(self):
        cabecalho = self.client.get(
            self._url(), {"ocultar": "evento", "export": "csv"}
        ).content.decode("utf-8-sig").splitlines()[0]
        self.assertIn("Local", cabecalho)
        self.assertNotIn("Evento", cabecalho)

    def test_ordenacao_por_local(self):
        resposta = self.client.get(self._url(), {"ordenar": "local", "dir": "asc"})
        locais = [i.atividade.local for i in resposta.context["inscricoes"]]
        self.assertEqual(locais, ["Auditório", "Sala 2"])

    def test_ordenacao_server_side_por_atividade(self):
        crescente = self.client.get(self._url(), {"ordenar": "atividade", "dir": "asc"})
        titulos = [i.atividade.titulo for i in crescente.context["inscricoes"]]
        self.assertEqual(titulos, ["Abertura", "Encerramento"])

        decrescente = self.client.get(self._url(), {"ordenar": "atividade", "dir": "desc"})
        titulos = [i.atividade.titulo for i in decrescente.context["inscricoes"]]
        self.assertEqual(titulos, ["Encerramento", "Abertura"])

    def test_links_de_coluna_e_exportacao_preservam_a_busca(self):
        resposta = self._buscar("Ana")
        urls_colunas = [c["url"] for c in resposta.context["colunas_disponiveis"]]
        self.assertTrue(urls_colunas)
        self.assertTrue(all("q=Ana" in url for url in urls_colunas))
        urls_export = [e["url"] for e in resposta.context["export_urls"]]
        self.assertTrue(all("q=Ana" in url for url in urls_export))

    def test_limpar_busca_preserva_colunas_e_ordem(self):
        resposta = self.client.get(
            self._url(),
            {"q": "Ana", "campos": "matricula", "ordenar": "atividade", "dir": "asc"},
        )
        limpar = resposta.context["limpar_url"]
        self.assertNotIn("q=", limpar)
        self.assertIn("campos=matricula", limpar)
        self.assertIn("ordenar=atividade", limpar)
        self.assertIn("dir=asc", limpar)


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
            local="Auditório",
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
        self.assertIn("Local", texto)
        self.assertIn("Auditório", texto)

    def test_export_respeita_a_busca(self):
        com = self._inscricoes(export="csv", q="2026001").content.decode("utf-8-sig")
        self.assertIn("Aluna", com)
        sem = self._inscricoes(export="csv", q="nao-existe-xyz").content.decode("utf-8-sig")
        self.assertNotIn("Aluna Teste", sem)

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
