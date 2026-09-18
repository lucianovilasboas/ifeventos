"""Testes do painel do participante."""

import re
from datetime import date, datetime, timedelta, timezone as tz

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from eventos.models import Atividade, Evento, ParticipanteMetadados, TipoAtividade

U = get_user_model()
SENHA = "SenhaForte123!"


class DashboardOrdemAtividadesTests(TestCase):
    """As atividades disponíveis saem na ordem em que vão acontecer."""

    def setUp(self):
        self.org = U.objects.create_user(
            email="org_pd@example.com", password=SENHA, cpf="12345678909",
            is_organizador=True,
        )
        self.participante = U.objects.create_user(
            email="pd@example.com", password=SENHA, cpf="11144477735"
        )
        self.tipo = TipoAtividade.objects.create(nome="Palestra")
        self.evento = Evento.objects.create(
            title="Evento", description="d", local="l",
            data_inicio=date(2026, 10, 10), data_fim=date(2026, 10, 12),
            categoria="formacao", organizador=self.org,
        )
        for titulo, dia in (("Terceiro", 12), ("Primeiro", 10), ("Segundo", 11)):
            Atividade.objects.create(
                evento=self.evento, titulo=titulo, descricao="d", tipo=self.tipo,
                data_hora_inicio=datetime(2026, 10, dia, 10, 0, tzinfo=tz.utc),
                data_hora_fim=datetime(2026, 10, dia, 11, 0, tzinfo=tz.utc),
                n_vagas=10,
            )
        self.client.force_login(self.participante)

    def test_atividades_em_ordem_de_data(self):
        resposta = self.client.get(reverse("participante:dashboard"))
        self.assertEqual(resposta.status_code, 200)
        titulos = [a.titulo for a in resposta.context["atividades"]]
        self.assertEqual(titulos, ["Primeiro", "Segundo", "Terceiro"])


class PerfilMetadadosTests(TestCase):
    """O perfil do participante grava os metadados configurados por escola."""

    def setUp(self):
        self.participante = U.objects.create_user(
            email="perfilmeta@example.com", password=SENHA, cpf="12345678909",
            first_name="Aluna", last_name="Teste",
        )
        self.client.force_login(self.participante)

    def test_perfil_salva_metadados(self):
        resposta = self.client.post(
            reverse("participante:dashboard"),
            {
                "first_name": "Aluna", "last_name": "Teste",
                "username": self.participante.username,
                "email": self.participante.email,
                "cpf": "12345678909", "telefone": "", "endereco": "",
                "meta_vinculo": "Aluno",
                "meta_matricula": "2026001", "meta_curso": "Informática",
                "meta_turma": "Turma 2", "meta_ano": "Terceiro ano",
            },
        )
        self.assertEqual(resposta.status_code, 302)
        dados = ParticipanteMetadados.objects.get(
            participante=self.participante
        ).dados
        self.assertEqual(dados["vinculo"], "Aluno")
        self.assertEqual(dados["matricula"], "2026001")
        self.assertEqual(dados["curso"], "Informática")
        self.assertEqual(dados["turma"], "Turma 2")


class FiltroDeEventoChipsTests(TestCase):
    """O filtro por evento do painel é de chips (links), não mais um select."""

    def setUp(self):
        self.pessoa = U.objects.create_user(
            email="chips@example.com", password=SENHA, cpf="11144477735"
        )
        hoje = date.today()
        for titulo in ("Evento Alfa", "Evento Beta"):
            evento = Evento.objects.create(
                title=titulo, description="d", local="Campus",
                data_inicio=hoje + timedelta(days=5),
                data_fim=hoje + timedelta(days=6),
                organizador=self.pessoa,
            )
            Atividade.objects.create(
                evento=evento, titulo=f"Atividade {titulo}", descricao="d",
                tipo=TipoAtividade.objects.create(nome=f"Tipo {titulo}"),
                data_hora_inicio=datetime(2030, 1, 1, 10, 0, tzinfo=tz.utc),
                data_hora_fim=datetime(2030, 1, 1, 11, 0, tzinfo=tz.utc),
                n_vagas=10,
            )
        self.client.force_login(self.pessoa)

    def _html(self, parametros=""):
        return self.client.get(
            reverse("participante:dashboard") + parametros
        ).content.decode()

    def test_mostra_chips_no_lugar_do_select(self):
        html = self._html()

        self.assertIn("chips-evento", html)
        self.assertIn("Evento Alfa", html)
        self.assertIn("Evento Beta", html)
        self.assertNotIn('<select name="evento"', html)

    def test_todos_e_o_chip_ativo_sem_filtro(self):
        html = self._html()

        self.assertIn('href="?"', html)
        self.assertIn("chip-evento is-ativo", html)

    def test_filtro_marca_o_chip_e_corta_as_listas(self):
        evento = Evento.objects.get(title="Evento Alfa")

        html = self._html(f"?evento={evento.id}")

        self.assertIn(f'href="?evento={evento.id}"', html)
        self.assertIn("Atividade Evento Alfa", html)
        self.assertNotIn("Atividade Evento Beta", html)


class RotulosDaBarraInferiorTests(TestCase):
    """A barra inferior do mobile não deixa nenhum item só com o ícone.

    O CSS esconde o rótulo completo no mobile e mostra o curto; sem o curto, o
    item some. Aqui garante-se que todo link tem rótulo e que a alternância de
    visão (organizador ↔ participante) tem tratamento próprio.
    """

    def _bottomnav(self, html):
        achado = re.search(
            r'<nav class="app-bottomnav">(.*?)</nav>', html, re.S
        )
        assert achado is not None, "barra inferior não renderizou"
        return achado.group(1)

    def _todo_link_tem_rotulo(self, bloco):
        links = len(re.findall(r"<a\b", bloco))
        rotulos = len(re.findall(r'class="nav-rotulo-curto"', bloco))
        self.assertGreater(links, 0)
        self.assertEqual(links, rotulos, "algum item ficou sem rótulo")

    def test_participante_todo_item_tem_rotulo(self):
        pessoa = U.objects.create_user(
            email="nav_participante@example.com", password=SENHA, cpf="11144477735",
        )
        self.client.force_login(pessoa)

        bloco = self._bottomnav(
            self.client.get(reverse("participante:dashboard")).content.decode()
        )

        self._todo_link_tem_rotulo(bloco)
        self.assertNotIn("nav-modo", bloco)

    def test_anonimo_todo_item_tem_rotulo(self):
        bloco = self._bottomnav(
            self.client.get(reverse("account_login")).content.decode()
        )

        self._todo_link_tem_rotulo(bloco)
        self.assertNotIn("nav-modo", bloco)

    def test_duplo_papel_tem_pilula_de_alternancia_no_fim(self):
        pessoa = U.objects.create_user(
            email="nav_duplo@example.com", password=SENHA, cpf="11144477735",
            is_organizador=True, is_participante=True,
        )
        self.client.force_login(pessoa)

        bloco = self._bottomnav(
            self.client.get(reverse("participante:dashboard")).content.decode()
        )

        self._todo_link_tem_rotulo(bloco)
        self.assertEqual(bloco.count('class="nav-modo"'), 1)
        self.assertIn('class="nav-divisor"', bloco)
        # A alternância fica no grupo de conta: depois de Crachá e antes de Sair.
        self.assertLess(bloco.index("meus-crachas"), bloco.index("nav-modo"))
        self.assertLess(bloco.index("nav-modo"), bloco.index("logout"))
