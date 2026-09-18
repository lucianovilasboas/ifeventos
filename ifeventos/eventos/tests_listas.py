"""Testes das listas de atividades ordenadas por data."""

import re
from datetime import date, datetime, timezone as tz

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Atividade, Evento, TipoAtividade

U = get_user_model()
SENHA = "SenhaForte123!"


class ProgramacaoOrdemTests(TestCase):
    """A programação pública sai na ordem em que as atividades vão acontecer."""

    def setUp(self):
        self.org = U.objects.create_user(
            email="org_prog@example.com", password=SENHA, cpf="12345678909"
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

    def test_programacao_em_ordem_de_data(self):
        resposta = self.client.get(
            reverse("eventos:programacao", kwargs={"evento_id": self.evento.id})
        )
        self.assertEqual(resposta.status_code, 200)
        titulos = [a.titulo for a in resposta.context["atividades"]]
        self.assertEqual(titulos, ["Primeiro", "Segundo", "Terceiro"])


class TabelaAtividadesColunaDataTests(TestCase):
    """A tabela do organizador tem a data em coluna própria e ordenável."""

    def setUp(self):
        self.org = U.objects.create_user(
            email="org_tab@example.com", password=SENHA, cpf="12345678909",
            is_organizador=True,
        )
        self.tipo = TipoAtividade.objects.create(nome="Palestra")
        self.evento = Evento.objects.create(
            title="Evento", description="d", local="l",
            data_inicio=date(2026, 10, 10), data_fim=date(2026, 10, 12),
            categoria="formacao", organizador=self.org,
        )
        Atividade.objects.create(
            evento=self.evento, titulo="Abertura", descricao="d", tipo=self.tipo,
            local="Auditório",
            data_hora_inicio=datetime(2026, 10, 10, 10, 0, tzinfo=tz.utc),
            data_hora_fim=datetime(2026, 10, 10, 11, 0, tzinfo=tz.utc),
            n_vagas=10,
        )
        self.client.force_login(self.org)

    def test_coluna_data_presente_e_com_valor_iso(self):
        resposta = self.client.get(
            reverse("organizador:atividades_evento", kwargs={"evento_id": self.evento.id})
        )
        self.assertEqual(resposta.status_code, 200)
        html = resposta.content.decode()
        self.assertIn(">Data</th>", html)
        # O índice 6 é "Inscritos": as colunas são #, Atividade, Data, Tipo,
        # Local, Vagas, Inscritos, Ações.
        self.assertIn('data-ordenar-inicial="6:desc"', html)

    def test_coluna_local_na_tabela(self):
        resposta = self.client.get(
            reverse("organizador:atividades_evento", kwargs={"evento_id": self.evento.id})
        )
        html = resposta.content.decode()
        self.assertIn('data-sort="text">Local</th>', html)
        self.assertIn("Auditório", html)
        # ISO localizado (ex.: 2026-10-10T07:00:00-03:00) — ordena como texto.
        self.assertIn('data-valor="2026-10-10T', html)


class BuscaNasAtividadesTests(TestCase):
    """A lista de atividades do evento tem busca (filtro no cliente)."""

    def setUp(self):
        self.org = U.objects.create_user(
            email="org_busca_ativ@example.com", password=SENHA, cpf="12345678909",
            is_organizador=True,
        )
        self.tipo = TipoAtividade.objects.create(nome="Oficina")
        self.evento = Evento.objects.create(
            title="Evento Busca", description="d", local="l",
            data_inicio=date(2026, 10, 10), data_fim=date(2026, 10, 12),
            categoria="formacao", organizador=self.org,
        )
        for titulo, local in (("Abertura", "Auditório"), ("Robótica", "Laboratório")):
            Atividade.objects.create(
                evento=self.evento, titulo=titulo, descricao="d", tipo=self.tipo,
                local=local,
                data_hora_inicio=datetime(2026, 10, 10, 10, 0, tzinfo=tz.utc),
                data_hora_fim=datetime(2026, 10, 10, 11, 0, tzinfo=tz.utc),
                n_vagas=10,
            )
        self.client.force_login(self.org)

    def _html(self):
        resposta = self.client.get(
            reverse("organizador:atividades_evento", kwargs={"evento_id": self.evento.id})
        )
        self.assertEqual(resposta.status_code, 200)
        return resposta.content.decode()

    def test_lista_tem_campo_de_busca(self):
        html = self._html()
        self.assertIn("data-busca-lista", html)
        self.assertIn(
            'data-busca placeholder="Buscar atividade pelo nome, tipo ou local"', html
        )
        self.assertIn("data-busca-vazio", html)

    def test_cada_atividade_entra_na_busca(self):
        # 2 atividades × (card mobile + linha da tabela). O par de atributos
        # evita contar as chamadas setAttribute do script da página.
        self.assertEqual(self._html().count("data-busca-item data-atividade-id"), 4)

    def test_script_da_busca_carregado(self):
        self.assertIn("js/lista_busca.js", self._html())


class BotaoRolagemTests(TestCase):
    """Os dois templates base carregam o botão de rolagem (topo ↔ fim)."""

    def setUp(self):
        self.org = U.objects.create_user(
            email="org_rolagem@example.com", password=SENHA, cpf="12345678909",
            is_organizador=True,
        )
        self.tipo = TipoAtividade.objects.create(nome="Palestra")
        self.evento = Evento.objects.create(
            title="Evento Rolagem", description="d", local="l",
            data_inicio=date(2026, 10, 10), data_fim=date(2026, 10, 11),
            categoria="formacao", organizador=self.org,
        )
        Atividade.objects.create(
            evento=self.evento, titulo="Abertura", descricao="d", tipo=self.tipo,
            data_hora_inicio=datetime(2026, 10, 10, 10, 0, tzinfo=tz.utc),
            data_hora_fim=datetime(2026, 10, 10, 11, 0, tzinfo=tz.utc),
            n_vagas=10,
        )

    def test_pagina_publica_carrega_o_script(self):
        # Programação é pública e usa base.html.
        resposta = self.client.get(
            reverse("eventos:programacao", kwargs={"evento_id": self.evento.id})
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("js/botao_rolagem.js", resposta.content.decode())

    def test_pagina_interna_carrega_o_script(self):
        # Atividades do evento usa dashboard_base.html.
        self.client.force_login(self.org)
        resposta = self.client.get(
            reverse("organizador:atividades_evento", kwargs={"evento_id": self.evento.id})
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("js/botao_rolagem.js", resposta.content.decode())


class LandingTotalAtividadesTests(TestCase):
    """O card e o modal da landing mostram o total de atividades do evento."""

    def setUp(self):
        self.org = U.objects.create_user(
            email="org_land@example.com", password=SENHA, cpf="12345678909"
        )
        self.tipo = TipoAtividade.objects.create(nome="Palestra")
        self.evento = Evento.objects.create(
            title="Evento Land", description="d", local="l",
            data_inicio=date(2030, 1, 1), data_fim=date(2030, 1, 2),
            categoria="formacao", organizador=self.org,
        )
        for titulo in ("Abertura", "Encerramento"):
            Atividade.objects.create(
                evento=self.evento, titulo=titulo, descricao="d", tipo=self.tipo,
                data_hora_inicio=datetime(2030, 1, 1, 10, 0, tzinfo=tz.utc),
                data_hora_fim=datetime(2030, 1, 1, 11, 0, tzinfo=tz.utc),
                n_vagas=10,
            )

    def test_card_e_modal_tem_o_total(self):
        resposta = self.client.get(reverse("eventos:eventos"))
        self.assertEqual(resposta.status_code, 200)
        html = resposta.content.decode()
        self.assertIn("2 atividades", html)   # card
        self.assertIn("nAtiv: 2", html)       # dados do modal (JS)

    def test_card_tem_link_para_a_programacao(self):
        html = self.client.get(reverse("eventos:eventos")).content.decode()
        url = reverse("eventos:programacao", args=[self.evento.id])
        self.assertIn(f'href="{url}"', html)
        self.assertIn("Ver programação", html)


class AcoesNaGradeTests(TestCase):
    """Editar/Excluir nos chips da grade só na tela do organizador."""

    def setUp(self):
        self.org = U.objects.create_user(
            email="org_grade@example.com", password=SENHA, cpf="12345678909",
            is_organizador=True,
        )
        self.participante = U.objects.create_user(
            email="part_grade@example.com", password=SENHA, cpf="11144477735"
        )
        self.tipo = TipoAtividade.objects.create(nome="Palestra")
        self.evento = Evento.objects.create(
            title="Evento Grade", description="d", local="l",
            data_inicio=date(2026, 10, 10), data_fim=date(2026, 10, 11),
            categoria="formacao", organizador=self.org,
        )
        self.atividade = Atividade.objects.create(
            evento=self.evento, titulo="Abertura", descricao="d", tipo=self.tipo,
            data_hora_inicio=datetime(2026, 10, 10, 10, 0, tzinfo=tz.utc),
            data_hora_fim=datetime(2026, 10, 10, 11, 0, tzinfo=tz.utc),
            n_vagas=10,
        )

    def _html(self, url):
        return self.client.get(url).content.decode()

    def test_grade_do_organizador_traz_editar_e_excluir(self):
        self.client.force_login(self.org)

        html = self._html(
            reverse("organizador:atividades_evento", args=[self.evento.id])
        )

        self.assertIn("chip-acoes", html)
        self.assertIn(
            reverse(
                "organizador:criar_editar_atividade_editar",
                args=[self.evento.id, self.atividade.id],
            ),
            html,
        )
        self.assertIn(
            reverse("organizador:excluir_atividade", args=[self.atividade.id]), html
        )

    def test_programacao_publica_nao_traz_os_botoes(self):
        html = self._html(reverse("eventos:programacao", args=[self.evento.id]))

        self.assertNotIn("chip-acoes", html)

    def test_painel_do_participante_nao_traz_os_botoes(self):
        self.client.force_login(self.participante)

        html = self._html(reverse("participante:dashboard"))

        self.assertNotIn("chip-acoes", html)

    def test_cabecalho_nao_tem_mais_ocupacao_por_sala(self):
        self.client.force_login(self.org)

        html = self._html(
            reverse("organizador:atividades_evento", args=[self.evento.id])
        )

        self.assertNotIn("Ocupação por sala", html)
        self.assertNotIn(
            reverse("organizador:ocupacao_salas", args=[self.evento.id]), html
        )


class AvatarNaHomeTests(TestCase):
    """A home mostra o avatar no topo quando o usuário está logado."""

    def _acoes_do_topo(self, html):
        achado = re.search(
            r'<div class="landing-topo-acoes">(.*?)</div>', html, re.S
        )
        assert achado is not None, "grupo do topo não renderizou"
        return achado.group(1)

    def test_anonimo_nao_mostra_avatar(self):
        bloco = self._acoes_do_topo(
            self.client.get(reverse("eventos:eventos")).content.decode()
        )

        self.assertNotIn("landing-avatar", bloco)

    def test_logado_mostra_avatar_no_topo(self):
        pessoa = U.objects.create_user(
            email="avatar_home@example.com", password=SENHA, cpf="11144477735",
        )
        self.client.force_login(pessoa)

        bloco = self._acoes_do_topo(
            self.client.get(reverse("eventos:eventos")).content.decode()
        )

        self.assertIn("landing-avatar", bloco)
