"""Testes do painel do participante."""

import re
from datetime import date, datetime, timedelta, timezone as tz

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from eventos.models import (
    Atividade,
    Certificado,
    Evento,
    Inscricao,
    ParticipanteMetadados,
    TipoAtividade,
)

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
    """A barra inferior do mobile fica só com destinos e todo item tem rótulo.

    O CSS esconde o rótulo completo no mobile e mostra o curto; sem o curto, o
    item some. O que depende da visão/conta foi para o menu do usuário, então a
    barra não deve carregar Painel/Certificados/Propostas/Crachá/Sair.
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

    def test_participante_barra_so_destinos(self):
        pessoa = U.objects.create_user(
            email="nav_participante@example.com", password=SENHA, cpf="11144477735",
        )
        self.client.force_login(pessoa)

        bloco = self._bottomnav(
            self.client.get(reverse("participante:dashboard")).content.decode()
        )

        self._todo_link_tem_rotulo(bloco)
        self.assertIn("Início", bloco)
        self.assertIn("Agenda", bloco)
        for item_de_conta in ("Painel", "Certificados", "Propostas", "Crachá", "Sair"):
            self.assertNotIn(item_de_conta, bloco)

    def test_anonimo_todo_item_tem_rotulo(self):
        bloco = self._bottomnav(
            self.client.get(reverse("account_login")).content.decode()
        )

        self._todo_link_tem_rotulo(bloco)


class MenuDoUsuarioTests(TestCase):
    """O menu do avatar concentra o que depende da visão/da conta."""

    def _menu(self, html):
        achado = re.search(
            r'<div class="menu-usuario"[^>]*>(.*?)</div>\s*</div>', html, re.S
        )
        assert achado is not None, "menu do usuário não renderizou"
        return achado.group(1)

    def test_anonimo_nao_tem_menu(self):
        html = self.client.get(reverse("account_login")).content.decode()
        self.assertNotIn("menu-usuario", html)

    def _evento(self, **kwargs):
        dados = dict(
            title="Evento Menu", description="d", local="l",
            data_inicio=date(2026, 10, 10), data_fim=date(2026, 10, 12),
        )
        dados.update(kwargs)
        return Evento.objects.create(**dados)

    def _atividade(self, evento, **kwargs):
        dados = dict(
            evento=evento, titulo="Atividade", descricao="d",
            data_hora_inicio=datetime(2026, 10, 10, 10, 0, tzinfo=tz.utc),
            data_hora_fim=datetime(2026, 10, 10, 11, 0, tzinfo=tz.utc),
            n_vagas=10,
        )
        dados.update(kwargs)
        return Atividade.objects.create(**dados)

    def _menu_de(self, pessoa):
        self.client.force_login(pessoa)
        return self._menu(
            self.client.get(reverse("participante:dashboard")).content.decode()
        )

    def test_participante_sem_conteudo_nao_tem_atalhos_vazios(self):
        pessoa = U.objects.create_user(
            email="menu_part@example.com", password=SENHA, cpf="11144477735",
        )
        menu = self._menu_de(pessoa)

        for item in ("Meu painel", "Meu perfil", "Sair"):
            self.assertIn(item, menu)
        for vazio in (
            "Meus certificados", "Minhas propostas", "Minhas palestras", "Meus crachás",
        ):
            self.assertNotIn(vazio, menu)
        self.assertNotIn("Trocar para", menu)

    def test_menu_mostra_certificados_quando_ha(self):
        pessoa = U.objects.create_user(
            email="menu_cert@example.com", password=SENHA, cpf="11144477735",
        )
        Certificado.objects.create(participante=pessoa, evento=self._evento())
        menu = self._menu_de(pessoa)
        self.assertIn("Meus certificados", menu)

    def test_menu_mostra_crachas_quando_inscrito(self):
        pessoa = U.objects.create_user(
            email="menu_cracha@example.com", password=SENHA, cpf="11144477735",
        )
        Inscricao.objects.create(
            participante=pessoa, atividade=self._atividade(self._evento())
        )
        menu = self._menu_de(pessoa)
        self.assertIn("Meus crachás", menu)
        self.assertNotIn("Minhas palestras", menu)

    def test_menu_mostra_palestras_quando_palestrante(self):
        pessoa = U.objects.create_user(
            email="menu_palestra@example.com", password=SENHA, cpf="11144477735",
        )
        atividade = self._atividade(self._evento())
        atividade.palestrantes.add(pessoa)
        menu = self._menu_de(pessoa)
        self.assertIn("Minhas palestras", menu)
        self.assertIn("Meus crachás", menu)

    def test_menu_mostra_propostas_quando_ha(self):
        pessoa = U.objects.create_user(
            email="menu_prop@example.com", password=SENHA, cpf="11144477735",
        )
        self._atividade(
            self._evento(), proponente=pessoa,
            situacao=Atividade.SITUACAO_PENDENTE,
        )
        menu = self._menu_de(pessoa)
        self.assertIn("Minhas propostas", menu)

    def test_duplo_papel_mostra_alternancia_para_o_outro_lado(self):
        pessoa = U.objects.create_user(
            email="menu_duplo@example.com", password=SENHA, cpf="11144477735",
            is_organizador=True, is_participante=True,
        )
        self.client.force_login(pessoa)

        no_participante = self._menu(
            self.client.get(reverse("participante:dashboard")).content.decode()
        )
        self.assertIn("Trocar para Organizador", no_participante)
        self.assertIn("Visão: Participante", no_participante)

        no_organizador = self._menu(
            self.client.get(reverse("organizador:dashboard")).content.decode()
        )
        self.assertIn("Trocar para Participante", no_organizador)
        self.assertIn("Visão: Organizador", no_organizador)


class MinhasPalestrasTests(TestCase):
    """R4: seção do palestrante no participante (só ver + QR, sem PII)."""

    def setUp(self):
        self.org = U.objects.create_user(
            email="org_mp@example.com", password=SENHA, cpf="12345678909",
            is_organizador=True,
        )
        self.palestrante = U.objects.create_user(
            email="pal_mp@example.com", password=SENHA, cpf="11144477735",
            is_participante=True,
        )
        self.estranho = U.objects.create_user(
            email="est_mp@example.com", password=SENHA, cpf="39053344705",
            is_participante=True,
        )
        self.tipo = TipoAtividade.objects.create(nome="Oficina")
        self.evento = Evento.objects.create(
            title="Evento", description="d", local="l",
            data_inicio=date(2026, 10, 10), data_fim=date(2026, 10, 12),
            categoria="formacao", organizador=self.org,
        )
        self.atividade = Atividade.objects.create(
            evento=self.evento, titulo="Palestra R4", descricao="d", tipo=self.tipo,
            data_hora_inicio=datetime(2026, 10, 10, 10, 0, tzinfo=tz.utc),
            data_hora_fim=datetime(2026, 10, 10, 11, 0, tzinfo=tz.utc),
            n_vagas=10, n_inscricoes=3,
        )
        self.atividade.palestrantes.add(self.palestrante)

    def test_palestrante_ve_sua_atividade(self):
        self.client.force_login(self.palestrante)
        resposta = self.client.get(reverse("participante:minhas_palestras"))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Palestra R4")
        self.assertContains(resposta, "QR de presença")

    def test_nao_palestrante_ve_lista_vazia(self):
        self.client.force_login(self.estranho)
        resposta = self.client.get(reverse("participante:minhas_palestras"))
        self.assertEqual(resposta.status_code, 200)
        self.assertNotContains(resposta, "Palestra R4")

    def test_nao_exibe_email_de_inscritos(self):
        self.client.force_login(self.palestrante)
        resposta = self.client.get(reverse("participante:minhas_palestras"))
        self.assertEqual(resposta.status_code, 200)
        # Não há lista de inscritos com PII na tela do palestrante.
        self.assertNotContains(resposta, self.org.email)

    def test_qr_liberado_para_palestrante(self):
        self.client.force_login(self.palestrante)
        resposta = self.client.get(reverse("participante:minha_palestra_qr", args=[self.atividade.id]))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "QR de presença da atividade")

    def test_qr_negado_para_quem_nao_palestra(self):
        self.client.force_login(self.estranho)
        resposta = self.client.get(reverse("participante:minha_palestra_qr", args=[self.atividade.id]))
        self.assertEqual(resposta.status_code, 403)

    def test_api_do_qr_liberada_para_palestrante(self):
        # O endpoint da API usava IsDonoEvento e barrava o palestrante (que tem
        # o QR liberado na tela). A checagem fina fica no corpo da action.
        self.client.force_login(self.palestrante)
        resposta = self.client.get(
            "/api/v1/atividades/%s/qrcode/" % self.atividade.id,
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("png", resposta.json())

    def test_menu_tem_minhas_palestras(self):
        self.client.force_login(self.palestrante)
        html = self.client.get(reverse("participante:dashboard")).content.decode()
        self.assertIn("Minhas palestras", html)
