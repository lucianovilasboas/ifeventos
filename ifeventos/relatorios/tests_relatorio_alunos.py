"""Testes do relatório por aluno (F1/F3), da permissão (F0) e da IA dos gráficos."""

from datetime import timedelta
from unittest import mock
from unittest.mock import AsyncMock

from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from asgiref.sync import async_to_sync

from eventos.models import (
    Atividade, Certificado, Evento, Inscricao, Presenca, TipoAtividade,
)
from relatorios import agente_graficos, agregacoes

U = get_user_model()
SENHA = "SenhaForte123!"


def _resposta_fake(conteudo):
    import json
    resposta = mock.MagicMock()
    resposta.choices = [mock.MagicMock()]
    resposta.choices[0].message.content = json.dumps(conteudo)
    resposta.usage = None
    return resposta


class BaseRelatorioTests(TestCase):
    def setUp(self):
        self.org = U.objects.create_user(
            email="org_rel@example.com", password=SENHA, cpf="12345678909",
            is_organizador=True,
        )
        self.outro = U.objects.create_user(
            email="outro_rel@example.com", password=SENHA, cpf="39053344705",
            is_organizador=True,
        )
        self.participante = U.objects.create_user(
            email="part_rel@example.com", password=SENHA, cpf="11144477735",
        )
        self.tipo = TipoAtividade.objects.create(nome="Oficina")
        hoje = timezone.localdate()
        self.evento = Evento.objects.create(
            title="Evento Relatório", description="d", local="Campus",
            data_inicio=hoje, data_fim=hoje + timedelta(days=1), organizador=self.org,
        )
        self.atividade = Atividade.objects.create(
            evento=self.evento, titulo="Oficina A", descricao="d", tipo=self.tipo,
            n_vagas=10, data_hora_inicio=timezone.now(),
            data_hora_fim=timezone.now() + timedelta(hours=2),
        )
        Inscricao.objects.create(participante=self.participante, atividade=self.atividade)
        Presenca.objects.create(
            atividade=self.atividade, participante=self.participante, papel="participante",
        )
        Certificado.objects.create(
            participante=self.participante, atividade=self.atividade, evento=self.evento,
        )

    def url(self, nome, *args):
        return reverse("organizador:%s" % nome, args=list(args))


class PermissaoRelatoriosTests(BaseRelatorioTests):
    """F0: os relatórios existentes deixam de ser abertos a qualquer login."""

    def test_participante_recebe_403(self):
        self.client.force_login(self.participante)
        resposta = self.client.get(self.url("relatorio_inscricoes", self.evento.id))
        self.assertEqual(resposta.status_code, 403)

    def test_dono_recebe_200(self):
        self.client.force_login(self.org)
        resposta = self.client.get(self.url("relatorio_inscricoes", self.evento.id))
        self.assertEqual(resposta.status_code, 200)

    def test_outro_organizador_recebe_200(self):
        self.client.force_login(self.outro)
        resposta = self.client.get(self.url("relatorio_inscricoes", self.evento.id))
        self.assertEqual(resposta.status_code, 200)

    def test_anonimo_redireciona(self):
        resposta = self.client.get(self.url("relatorio_inscricoes", self.evento.id))
        self.assertEqual(resposta.status_code, 302)

    def test_lista_presenca_protegida(self):
        self.client.force_login(self.participante)
        resposta = self.client.get(
            self.url("relatorio_lista_presenca", self.atividade.id)
        )
        self.assertEqual(resposta.status_code, 403)


class AgregacoesTests(BaseRelatorioTests):
    def test_resumo_por_pessoa(self):
        linhas = agregacoes.resumo_por_pessoa(self.evento)
        linha = next(l for l in linhas if l["pessoa"].id == self.participante.id)
        self.assertEqual(linha["n_inscricoes"], 1)
        self.assertEqual(linha["n_presencas"], 1)
        self.assertEqual(linha["n_certificados"], 1)
        self.assertEqual(linha["carga_horaria"], 2.0)

    def test_grupo_invariante(self):
        linhas = agregacoes.resumo_por_pessoa(self.evento)
        grupos = agregacoes.resumo_por_grupo(linhas)
        self.assertEqual(sum(g["pessoas"] for g in grupos), len(linhas))
        self.assertEqual(
            sum(g["presencas"] for g in grupos),
            sum(l["n_presencas"] for l in linhas),
        )

    def test_filtro_busca(self):
        self.assertEqual(len(agregacoes.resumo_por_pessoa(self.evento, termo="Part")), 1)
        self.assertEqual(len(agregacoes.resumo_por_pessoa(self.evento, termo="zzz")), 0)


class RelatorioAlunosViewTests(BaseRelatorioTests):
    def test_pagina_renderiza(self):
        self.client.force_login(self.org)
        resposta = self.client.get(self.url("relatorio_alunos", self.evento.id))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Relatório por aluno")
        self.assertContains(resposta, self.participante.email)

    def test_detalhe_renderiza(self):
        self.client.force_login(self.org)
        resposta = self.client.get(
            self.url("relatorio_aluno_detalhe", self.evento.id, self.participante.id)
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, self.participante.email)

    def test_export_csv(self):
        self.client.force_login(self.org)
        resposta = self.client.get(
            self.url("relatorio_alunos", self.evento.id) + "?export=csv"
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("text/csv", resposta["Content-Type"])


class AgenteGraficosTests(BaseRelatorioTests, TransactionTestCase):
    def test_curadoria_fallback(self):
        linhas = agregacoes.resumo_por_pessoa(self.evento)
        disponiveis = agregacoes.graficos_alunos(linhas)
        with mock.patch("eventos.services.get_openai_client", side_effect=RuntimeError("x")):
            resultado = async_to_sync(agente_graficos.curar)(
                self.evento, disponiveis, {"pessoas": len(linhas)}
            )
        self.assertEqual(resultado["origem"], "heuristica")
        self.assertTrue(resultado["ids"])

    def test_curadoria_ia_descarta_id_invalido(self):
        disponiveis = [{"id": "alunos_vinculo", "titulo": "Vínculo"}]
        fake = mock.MagicMock()
        fake.chat = mock.MagicMock()
        fake.chat.completions.create = AsyncMock(
            return_value=_resposta_fake({"ids": ["inexistente", "alunos_vinculo"], "legenda": "ok"})
        )
        with mock.patch("eventos.services.get_openai_client", return_value=fake):
            resultado = async_to_sync(agente_graficos.curar)(
                self.evento, disponiveis, {"pessoas": 1}
            )
        self.assertEqual(resultado["ids"], ["alunos_vinculo"])

    def test_endpoint_curadoria_exige_organizador(self):
        self.client.force_login(self.participante)
        resposta = self.client.post(
            self.url("graficos_curadoria", self.evento.id)
        )
        self.assertEqual(resposta.status_code, 403)
