"""Testes das agregações dos relatórios gráficos e da tela do organizador."""

from datetime import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from eventos.models import (
    Atividade, Evento, Inscricao, ParticipanteMetadados, Presenca, TipoAtividade,
)
from relatorios import graficos as agg

U = get_user_model()

CONFIG = [
    {"chave": "vinculo", "rotulo": "Vínculo", "tipo": "escolha", "ordem": 1,
     "opcoes": ["Aluno", "Servidor"]},
    {"chave": "curso", "rotulo": "Curso", "tipo": "escolha", "ordem": 2,
     "opcoes": ["Informática", "TPG"]},
]


def local(ano, mes, dia, hora):
    return timezone.make_aware(
        datetime(ano, mes, dia, hora), timezone.get_current_timezone()
    )


class AgregacoesTests(TestCase):
    def setUp(self):
        self.evento = Evento.objects.create(
            title="Mostra", description="d", local="Campus",
            data_inicio="2026-10-05", data_fim="2026-10-06",
        )
        self.oficina = TipoAtividade.objects.create(nome="Oficina")
        self.palestra = TipoAtividade.objects.create(nome="Palestra")

        self.a1 = Atividade.objects.create(  # 10 vagas, 3 inscritos
            evento=self.evento, titulo="Oficina A", descricao="d", tipo=self.oficina,
            local="Auditório", n_vagas=10, n_inscricoes=3,
            data_hora_inicio=local(2026, 10, 5, 8), data_hora_fim=local(2026, 10, 5, 9),
        )
        self.a2 = Atividade.objects.create(  # 100 vagas, 1 inscrito, rascunho
            evento=self.evento, titulo="Palestra B", descricao="d", tipo=self.palestra,
            local="Sala 1", n_vagas=100, n_inscricoes=1, publicada=False,
            data_hora_inicio=local(2026, 10, 6, 8), data_hora_fim=local(2026, 10, 6, 9),
        )

        self.p1 = U.objects.create_user(email="p1@example.com", password="SenhaForte123!")
        self.p2 = U.objects.create_user(email="p2@example.com", password="SenhaForte123!")
        Inscricao.objects.create(participante=self.p1, atividade=self.a1)
        Inscricao.objects.create(participante=self.p2, atividade=self.a1)
        Presenca.objects.create(atividade=self.a1, participante=self.p1)

    def _por_id(self, lista):
        return {g["id"]: g for g in lista}

    def test_kpis(self):
        valores = {k["rotulo"]: k for k in agg.kpis(self.evento)}
        self.assertEqual(valores["Atividades"]["valor"], 2)
        self.assertEqual(valores["Inscrições"]["valor"], 2)
        self.assertEqual(valores["Vagas oferecidas"]["valor"], 110)
        self.assertEqual(valores["Rascunhos"]["valor"], 1)
        # ocupação = inscritos(2 na A + 1 na B) / vagas(110) -> 3%
        self.assertEqual(valores["Ocupação média"]["valor"], 3)
        # comparecimento = 1 presença / 2 inscrições -> 50%
        self.assertEqual(valores["Comparecimento"]["valor"], 50)

    def test_ocupacao_por_atividade_mais_procurada_primeiro(self):
        g = self._por_id(agg.graficos(self.evento))["ocupacao_atividade"]
        self.assertEqual(g["labels"][0], "Oficina A")
        self.assertEqual(g["series"][0]["data"][0], 2)

    def test_inscricoes_por_tipo(self):
        g = self._por_id(agg.graficos(self.evento))["inscricoes_por_tipo"]
        self.assertEqual(dict(zip(g["labels"], g["series"][0]["data"])), {"Oficina": 2, "Palestra": 1})

    def test_ocupacao_por_sala(self):
        g = self._por_id(agg.graficos(self.evento))["ocupacao_sala"]
        self.assertEqual(set(g["labels"]), {"Auditório", "Sala 1"})

    def test_evolucao_tem_um_ponto_por_dia(self):
        g = self._por_id(agg.graficos(self.evento))["evolucao"]
        self.assertEqual(len(g["labels"]), len(g["series"][0]["data"]))
        self.assertGreaterEqual(sum(g["series"][0]["data"]), 2)

    def test_publicadas_e_rascunhos(self):
        g = self._por_id(agg.graficos(self.evento))["publicacao"]
        self.assertEqual(g["labels"], ["Publicadas", "Rascunhos"])
        self.assertEqual(g["series"][0]["data"], [1, 1])

    def test_heatmap(self):
        mapa = agg.heatmap(self.evento)
        self.assertEqual(len(mapa["dias"]), 2)
        self.assertIn(8, mapa["horas"])
        self.assertEqual(mapa["maximo"], 1)

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_perfil_usa_os_metadados_preenchidos(self):
        ParticipanteMetadados.objects.create(
            participante=self.p1, dados={"vinculo": "Aluno", "curso": "Informática"}
        )
        ParticipanteMetadados.objects.create(
            participante=self.p2, dados={"vinculo": "Aluno", "curso": "TPG"}
        )
        por_id = self._por_id(agg.graficos(self.evento))
        self.assertIn("perfil_vinculo", por_id)
        self.assertEqual(por_id["perfil_vinculo"]["labels"], ["Aluno"])
        self.assertEqual(set(por_id["perfil_curso"]["labels"]), {"Informática", "TPG"})

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_sem_metadados_nao_gera_grafico_de_perfil(self):
        por_id = self._por_id(agg.graficos(self.evento))
        self.assertNotIn("perfil_vinculo", por_id)


class RelatoriosGraficosViewTests(TestCase):
    def setUp(self):
        self.evento = Evento.objects.create(
            title="Mostra", description="d", local="Campus",
            data_inicio="2026-10-05", data_fim="2026-10-05",
        )
        self.tipo = TipoAtividade.objects.create(nome="Oficina")
        Atividade.objects.create(
            evento=self.evento, titulo="A", descricao="d", tipo=self.tipo,
            local="Auditório", n_vagas=10,
            data_hora_inicio=local(2026, 10, 5, 8), data_hora_fim=local(2026, 10, 5, 9),
        )
        self.url = reverse("organizador:relatorios_graficos", args=[self.evento.id])
        self.org = U.objects.create_user(
            email="org@example.com", password="SenhaForte123!", is_organizador=True
        )

    def test_exige_login(self):
        resposta = self.client.get(self.url)
        self.assertEqual(resposta.status_code, 302)

    def test_renderiza_paineis_e_dados(self):
        self.client.force_login(self.org)
        resposta = self.client.get(self.url)
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "dados-graficos")
        self.assertContains(resposta, 'data-grafico="ocupacao_atividade"')
        self.assertContains(resposta, "chart.min.js")
        self.assertContains(resposta, "Ocupação média")


class OcupacaoVoltarTests(TestCase):
    """O "Voltar" da ocupação retorna para quem chamou (via `?next=`)."""

    def setUp(self):
        self.evento = Evento.objects.create(
            title="Mostra", description="d", local="Campus",
            data_inicio="2026-10-05", data_fim="2026-10-05",
        )
        self.org = U.objects.create_user(
            email="org3@example.com", password="SenhaForte123!", is_organizador=True
        )
        self.url = reverse("organizador:ocupacao_salas", args=[self.evento.id])
        self.padrao = reverse("organizador:atividades_evento", args=[self.evento.id])

    def test_sem_next_cai_na_lista_de_atividades(self):
        self.client.force_login(self.org)
        resposta = self.client.get(self.url)
        self.assertEqual(resposta.context["voltar_url"], self.padrao)

    def test_next_local_e_respeitado(self):
        self.client.force_login(self.org)
        destino = reverse("organizador:dashboard")
        resposta = self.client.get(self.url, {"next": destino})
        self.assertEqual(resposta.context["voltar_url"], destino)

    def test_next_externo_e_ignorado(self):
        self.client.force_login(self.org)
        resposta = self.client.get(self.url, {"next": "https://evil.example.com/x"})
        self.assertEqual(resposta.context["voltar_url"], self.padrao)
