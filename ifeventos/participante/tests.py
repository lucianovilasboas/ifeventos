"""Testes do painel do participante."""

import json
import re
from datetime import date, datetime, timedelta, timezone as tz

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from eventos.models import (
    Atividade,
    Certificado,
    Evento,
    Inscricao,
    ParticipanteMetadados,
    Presenca,
    TipoAtividade,
)

U = get_user_model()
SENHA = "SenhaForte123!"


class DashboardOrdemAtividadesTests(TestCase):
    """Lista/cartões: da atividade mais recente para a mais antiga."""

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
            data_inicio=date(2030, 10, 10), data_fim=date(2030, 10, 12),
            categoria="formacao", organizador=self.org,
        )
        for titulo, dia in (("Terceiro", 12), ("Primeiro", 10), ("Segundo", 11)):
            Atividade.objects.create(
                evento=self.evento, titulo=titulo, descricao="d", tipo=self.tipo,
                data_hora_inicio=datetime(2030, 10, dia, 10, 0, tzinfo=tz.utc),
                data_hora_fim=datetime(2030, 10, dia, 11, 0, tzinfo=tz.utc),
                n_vagas=10,
            )
        self.client.force_login(self.participante)

    def test_atividades_da_mais_recente_para_a_mais_antiga(self):
        resposta = self.client.get(reverse("participante:dashboard"))
        self.assertEqual(resposta.status_code, 200)
        titulos = [a.titulo for a in resposta.context["atividades"]]
        self.assertEqual(titulos, ["Terceiro", "Segundo", "Primeiro"])

    def test_cronograma_continua_em_ordem_cronologica(self):
        resposta = self.client.get(reverse("participante:dashboard"))

        datas = [
            coluna["data"]
            for semana in resposta.context["grade_disponiveis"]["semanas"]
            for coluna in semana["colunas"]
        ]
        self.assertEqual(datas, sorted(datas))


    def test_dashboard_exibe_status_e_kpis_de_presenca(self):
        inscricao = Inscricao.objects.create(
            participante=self.participante, atividade=self.evento.atividades.first(), confirmada=True
        )
        resposta = self.client.get(reverse("participante:dashboard"))
        self.assertContains(resposta, "Presença confirmada")
        self.assertContains(resposta, "1 atividades inscritas")
        self.assertContains(resposta, "1 presenças confirmadas")
        self.assertContains(resposta, "100,0% de participação")
        self.assertNotContains(resposta, "Certificado do evento: mínimo de 75% de participação.")
        self.assertNotContains(resposta, "x Ainda não elegível")


class AtividadesDisponiveisTests(TestCase):
    """Atividades do evento: ordem, marca de hoje e estado encerrado."""

    def setUp(self):
        self.org = U.objects.create_user(
            email="org_disp@example.com", password=SENHA, cpf="12345678909",
            is_organizador=True,
        )
        self.participante = U.objects.create_user(
            email="disp@example.com", password=SENHA, cpf="11144477735"
        )
        self.tipo = TipoAtividade.objects.create(nome="Oficina")
        hoje = timezone.localdate()
        self.evento = Evento.objects.create(
            title="Evento Disponível", description="d", local="Campus",
            data_inicio=hoje - timedelta(days=1), data_fim=hoje + timedelta(days=2),
            categoria="formacao", organizador=self.org,
        )
        agora = timezone.now()
        self.atividade_hoje = Atividade.objects.create(
            evento=self.evento, titulo="Oficina de Hoje", descricao="desc",
            tipo=self.tipo,
            data_hora_inicio=agora,
            data_hora_fim=agora + timedelta(minutes=30),
            n_vagas=10,
        )
        self.atividade_encerrada = Atividade.objects.create(
            evento=self.evento, titulo="Oficina Encerrada", descricao="desc",
            tipo=self.tipo,
            data_hora_inicio=agora - timedelta(hours=3),
            data_hora_fim=agora - timedelta(hours=2),
            n_vagas=10,
        )
        self.atividade_amanha = Atividade.objects.create(
            evento=self.evento, titulo="Oficina de Amanhã", descricao="desc",
            tipo=self.tipo,
            data_hora_inicio=agora + timedelta(days=1),
            data_hora_fim=agora + timedelta(days=1, hours=1),
            n_vagas=10,
        )
        self.client.force_login(self.participante)

    def test_atividade_encerrada_continua_visivel_e_desabilitada(self):
        resposta = self.client.get(reverse("participante:dashboard"))

        titulos = [a.titulo for a in resposta.context["atividades"]]
        self.assertEqual(
            titulos,
            ["Oficina de Amanhã", "Oficina de Hoje", "Oficina Encerrada"],
            "lista/cartões vão da mais recente para a mais antiga",
        )
        self.assertIn("Oficina Encerrada", titulos)
        self.assertContains(resposta, "Oficina Encerrada")
        self.assertContains(resposta, "Inscrições encerradas")
        self.assertNotContains(
            resposta,
            reverse("participante:inscrever", args=[self.atividade_encerrada.id]),
        )
        encerrada = next(
            a for a in resposta.context["atividades"]
            if a.id == self.atividade_encerrada.id
        )
        self.assertFalse(encerrada.inscricao_aberta)

        # As seções por dia também descem: amanhã → hoje, com a encerrada
        # depois da atividade ainda aberta do mesmo dia.
        secoes = resposta.context["secoes_disponiveis"]
        self.assertEqual(
            [secao["itens"][0].titulo for secao in secoes],
            ["Oficina de Amanhã", "Oficina de Hoje"],
        )
        self.assertEqual(secoes[-1]["itens"][-1].titulo, "Oficina Encerrada")

    def test_atividade_de_hoje_recebe_marca(self):
        resposta = self.client.get(reverse("participante:dashboard"))

        marcas = {a.titulo: a.hoje for a in resposta.context["atividades"]}
        self.assertTrue(marcas["Oficina de Hoje"])
        self.assertFalse(marcas["Oficina de Amanhã"])
        # A encerrada de hoje continua sendo "de hoje", mas não recebe o selo
        # de destaque: só a aberta conta.
        self.assertTrue(marcas["Oficina Encerrada"])
        self.assertEqual(resposta.content.decode().count("badge-hoje"), 1)

    def test_inscricao_recusada_em_atividade_encerrada(self):
        resposta = self.client.get(
            reverse("participante:inscrever", args=[self.atividade_encerrada.id])
        )

        self.assertRedirects(resposta, reverse("participante:dashboard"))
        self.assertFalse(
            Inscricao.objects.filter(
                participante=self.participante,
                atividade=self.atividade_encerrada,
            ).exists()
        )

    def test_ajax_recusa_inscricao_em_atividade_encerrada(self):
        resposta = self.client.post(
            reverse("participante:gerenciar_inscricoes_ajax"),
            data=json.dumps({
                "atividade_id": self.atividade_encerrada.id,
                "inscrito": True,
            }),
            content_type="application/json",
        )

        self.assertEqual(resposta.status_code, 400)
        self.assertIn("encerrad", resposta.json()["message"])

    def test_inscricao_recusada_depois_do_evento(self):
        self.evento.data_fim = timezone.localdate() - timedelta(days=1)
        self.evento.save(update_fields=["data_fim"])

        resposta = self.client.get(
            reverse("participante:inscrever", args=[self.atividade_amanha.id])
        )

        self.assertRedirects(resposta, reverse("participante:dashboard"))
        self.assertFalse(
            Inscricao.objects.filter(
                participante=self.participante,
                atividade=self.atividade_amanha,
            ).exists()
        )

    def test_cancelamento_bloqueado_depois_do_evento(self):
        inscricao = Inscricao.objects.create(
            participante=self.participante, atividade=self.atividade_hoje
        )
        self.evento.data_fim = timezone.localdate() - timedelta(days=1)
        self.evento.save(update_fields=["data_fim"])

        resposta = self.client.get(
            reverse("participante:cancelar_inscricao", args=[inscricao.id])
        )

        self.assertRedirects(resposta, reverse("participante:dashboard"))
        self.assertTrue(Inscricao.objects.filter(pk=inscricao.pk).exists())

    def test_consulta_desabilita_o_cancelamento(self):
        inscricao = Inscricao.objects.create(
            participante=self.participante, atividade=self.atividade_hoje
        )
        self.evento.data_fim = timezone.localdate() - timedelta(days=1)
        self.evento.save(update_fields=["data_fim"])

        resposta = self.client.get(reverse("participante:dashboard"))

        self.assertContains(resposta, "Cancelamento indisponível")
        self.assertNotContains(
            resposta,
            reverse("participante:cancelar_inscricao", args=[inscricao.id]),
        )

    def test_oferta_tem_cronograma_e_modal_de_detalhes(self):
        resposta = self.client.get(reverse("participante:dashboard"))

        valores = [v["valor"] for v in resposta.context["vistas_disponiveis"]]
        self.assertEqual(valores, ["lista", "cartoes", "cronograma"])
        self.assertFalse(resposta.context["grade_disponiveis"]["vazio"])
        self.assertContains(resposta, 'id="atividades-detalhes"')
        self.assertContains(
            resposta, 'data-detalhe-atividade="%s"' % self.atividade_hoje.id
        )


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


class EventoPadraoNoPainelTests(TestCase):
    """O painel abre num evento só: o padrão. Os passados vão para o arquivo."""

    def setUp(self):
        hoje = date.today()
        self.org = U.objects.create_user(
            email="org_evpadrao@example.com", password=SENHA, cpf="12345678909",
            is_organizador=True,
        )
        self.participante = U.objects.create_user(
            email="evpadrao@example.com", password=SENHA, cpf="11144477735"
        )
        self.tipo = TipoAtividade.objects.create(nome="Oficina do painel")

        def evento(titulo, inicio, fim):
            return Evento.objects.create(
                title=titulo, description="d", local="Campus",
                data_inicio=inicio, data_fim=fim,
                categoria="formacao", organizador=self.org,
            )

        self.atual = evento(
            "Evento Atual", hoje - timedelta(days=1), hoje + timedelta(days=1)
        )
        self.simultaneo = evento(
            "Evento Simultâneo", hoje - timedelta(days=1), hoje + timedelta(days=1)
        )
        self.futuro = evento(
            "Evento Futuro", hoje + timedelta(days=10), hoje + timedelta(days=11)
        )
        self.passado = evento(
            "Evento Passado", hoje - timedelta(days=30), hoje - timedelta(days=29)
        )
        # No painel, "passado" = encerrado pelo organizador (não só data vencida).
        Evento.objects.filter(pk=self.passado.pk).update(
            arquivado_em=timezone.now(), arquivado_por=self.org
        )
        self.aberto_vencido = evento(
            "Evento Vencido", hoje - timedelta(days=20), hoje - timedelta(days=19)
        )

        for ev, titulo in (
            (self.atual, "Atividade Atual"),
            (self.simultaneo, "Atividade Simultânea"),
            (self.futuro, "Atividade Futura"),
            (self.passado, "Atividade Passada"),
            (self.aberto_vencido, "Atividade Vencida"),
        ):
            inicio = datetime(
                ev.data_inicio.year, ev.data_inicio.month, ev.data_inicio.day,
                10, 0, tzinfo=tz.utc,
            )
            Atividade.objects.create(
                evento=ev, titulo=titulo, descricao="d", tipo=self.tipo,
                data_hora_inicio=inicio,
                data_hora_fim=inicio + timedelta(hours=1),
                n_vagas=10,
            )
        self.client.force_login(self.participante)

    def _pagina(self, parametros=""):
        return self.client.get(reverse("participante:dashboard") + parametros)

    def test_evento_atual_abre_por_padrao(self):
        resposta = self._pagina()

        # Entre simultâneos, vale o que começou por último.
        self.assertEqual(resposta.context["evento_foco"].id, self.simultaneo.id)
        self.assertContains(resposta, "Evento Simultâneo")
        self.assertContains(resposta, "Atividade Simultânea")
        self.assertNotContains(resposta, "Atividade Atual")
        self.assertNotContains(resposta, "Atividade Futura")

    def test_simultaneos_mostram_o_mais_atual_primeiro(self):
        resposta = self._pagina()

        self.assertEqual(
            [e.id for e in resposta.context["eventos_atuais"]],
            [self.simultaneo.id, self.atual.id],
        )

    def test_passados_ficam_na_lista_propria_e_fora_do_contexto(self):
        resposta = self._pagina()

        self.assertContains(resposta, "Eventos arquivados")
        self.assertContains(resposta, f"?evento={self.passado.id}")
        self.assertNotEqual(resposta.context["evento_foco"].id, self.passado.id)
        self.assertNotContains(resposta, "Atividade Passada")

    def test_fixar_evento_grava_a_preferencia(self):
        resposta = self.client.post(
            reverse("eventos:definir_evento_padrao", args=[self.futuro.id]),
            {"next": reverse("participante:dashboard")},
        )

        self.assertRedirects(resposta, reverse("participante:dashboard"))
        self.participante.refresh_from_db()
        self.assertEqual(self.participante.evento_padrao_id, self.futuro.id)

        resposta = self._pagina()
        self.assertEqual(resposta.context["evento_foco"].id, self.futuro.id)
        self.assertContains(resposta, "Atividade Futura")
        self.assertNotContains(resposta, "Atividade Atual")

    def test_consulta_de_passado_nao_muda_o_padrao(self):
        Inscricao.objects.create(
            participante=self.participante,
            atividade=Atividade.objects.get(titulo="Atividade Passada"),
        )

        resposta = self._pagina(f"?evento={self.passado.id}")

        self.assertTrue(resposta.context["modo_consulta"])
        self.assertEqual(resposta.context["evento_foco"].id, self.passado.id)
        self.assertContains(resposta, "Atividade Passada")
        self.assertNotContains(resposta, "Atividade Simultânea")
        self.participante.refresh_from_db()
        self.assertIsNone(self.participante.evento_padrao_id)

    def test_encerrado_sem_arquivar_fica_no_fluxo(self):
        resposta = self._pagina()

        self.assertIn(self.aberto_vencido, resposta.context["eventos_a_encerrar"])
        self.assertNotIn(self.aberto_vencido, resposta.context["eventos_arquivados"])
        self.assertContains(resposta, "Encerrados")

    def test_fixar_encerrado_aberto_abre_em_consulta(self):
        self.client.post(
            reverse("eventos:definir_evento_padrao", args=[self.aberto_vencido.id])
        )

        resposta = self._pagina()

        self.assertEqual(resposta.context["evento_foco"].id, self.aberto_vencido.id)
        self.assertTrue(resposta.context["modo_consulta"])

    def test_evento_encerrado_nao_vira_padrao(self):
        self.client.post(reverse("eventos:definir_evento_padrao", args=[self.passado.id]))

        self.participante.refresh_from_db()
        self.assertIsNone(self.participante.evento_padrao_id)

    def test_evento_fora_do_universo_nao_pode_ser_fixado(self):
        alheio = Evento.objects.create(
            title="Evento Alheio", description="d", local="l",
            data_inicio=date.today(), data_fim=date.today(),
            organizador=self.org,
        )

        resposta = self.client.post(
            reverse("eventos:definir_evento_padrao", args=[alheio.id])
        )

        self.assertEqual(resposta.status_code, 404)


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
    """R4: seção do palestrante — atividades, inscritos e QR."""

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
        self.equipe = U.objects.create_user(
            email="eq_mp@example.com", password=SENHA, cpf="15350946056",
            is_equipe=True,
        )
        self.tipo = TipoAtividade.objects.create(nome="Oficina")
        self.evento = Evento.objects.create(
            title="Evento", description="d", local="l",
            data_inicio=date(2026, 10, 10), data_fim=date(2026, 10, 12),
            categoria="formacao", organizador=self.org,
        )
        self.evento.equipe.add(self.equipe)
        self.atividade = Atividade.objects.create(
            evento=self.evento, titulo="Palestra R4", descricao="d", tipo=self.tipo,
            # A chamada do palestrante só vale durante a atividade: o padrão
            # dos testes fica "acontecendo agora".
            data_hora_inicio=datetime.now(tz.utc) - timedelta(hours=1),
            data_hora_fim=datetime.now(tz.utc) + timedelta(hours=1),
            n_vagas=10, n_inscricoes=3,
        )
        self.atividade.palestrantes.add(self.palestrante)

    def test_palestrante_ve_sua_atividade(self):
        self.client.force_login(self.palestrante)
        resposta = self.client.get(reverse("participante:minhas_palestras"))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Palestra R4")
        self.assertContains(resposta, "QR de presença")

    def test_card_tem_botao_ver_inscritos(self):
        self.client.force_login(self.palestrante)
        resposta = self.client.get(reverse("participante:minhas_palestras"))
        self.assertContains(resposta, "Ver inscritos")
        self.assertContains(
            resposta,
            reverse("participante:minha_palestra_inscritos", args=[self.atividade.id]),
        )

    def test_palestrante_ve_inscritos_com_vinculo_e_presenca(self):
        self._inscrito(com_presenca=True)
        self.client.force_login(self.palestrante)
        resposta = self.client.get(
            reverse("participante:minha_palestra_inscritos", args=[self.atividade.id])
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Inscrita Teste")
        # Nome com vínculo (curso/turma/ano), mas sem dados de contato.
        self.assertContains(resposta, "Aluno/Informática-Turma 1-Primeiro ano")
        self.assertContains(resposta, "Presente")
        self.assertNotContains(resposta, "inscrito_mp@example.com")

    def test_palestrante_ve_switch_de_presenca_manual(self):
        pessoa = self._inscrito(com_presenca=True)
        self.client.force_login(self.palestrante)
        resposta = self.client.get(
            reverse("participante:minha_palestra_inscritos", args=[self.atividade.id])
        )
        self.assertContains(resposta, "js-presenca")
        self.assertContains(
            resposta,
            reverse("organizador:presenca_manual", args=[self.atividade.id, pessoa.id]),
        )
        self.assertContains(resposta, "fazer a chamada")

    def test_coluna_confirmou_presenca_com_data_e_hora(self):
        from django.utils import timezone as dj_timezone

        pessoa = self._inscrito(com_presenca=True)
        self.client.force_login(self.palestrante)
        resposta = self.client.get(
            reverse("participante:minha_palestra_inscritos", args=[self.atividade.id])
        )
        self.assertContains(resposta, "Confirmou presença")
        presenca = Presenca.objects.get(
            atividade=self.atividade, participante=pessoa
        )
        esperado = dj_timezone.localtime(presenca.registrada_em).strftime("%d/%m/%Y %H:%M")
        self.assertContains(resposta, esperado)

    def test_palestrante_fora_da_janela_ve_motivo_sem_switch(self):
        pessoa = self._inscrito()
        self.atividade.data_hora_inicio = datetime.now(tz.utc) + timedelta(hours=2)
        self.atividade.data_hora_fim = datetime.now(tz.utc) + timedelta(hours=3)
        self.atividade.save()
        self.client.force_login(self.palestrante)
        resposta = self.client.get(
            reverse("participante:minha_palestra_inscritos", args=[self.atividade.id])
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertNotContains(
            resposta,
            reverse("organizador:presenca_manual", args=[self.atividade.id, pessoa.id]),
        )
        self.assertContains(resposta, "abre no início da atividade")

    def test_palestrante_com_certificado_ve_motivo_sem_switch(self):
        pessoa = self._inscrito()
        Certificado.objects.create(
            participante=pessoa, atividade=self.atividade, tipo="atividade"
        )
        self.client.force_login(self.palestrante)
        resposta = self.client.get(
            reverse("participante:minha_palestra_inscritos", args=[self.atividade.id])
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertNotContains(
            resposta,
            reverse("organizador:presenca_manual", args=[self.atividade.id, pessoa.id]),
        )
        self.assertContains(resposta, "certificados desta atividade já foram emitidos")

    def test_equipe_ve_lista_sem_switch(self):
        self.client.force_login(self.equipe)
        resposta = self.client.get(
            reverse("participante:minha_palestra_inscritos", args=[self.atividade.id])
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertNotContains(resposta, "js-presenca")

    def test_estranho_nao_ve_inscritos(self):
        self.client.force_login(self.estranho)
        resposta = self.client.get(
            reverse("participante:minha_palestra_inscritos", args=[self.atividade.id])
        )
        self.assertEqual(resposta.status_code, 403)

    def test_atividade_aberta_lista_as_presencas(self):
        self.atividade.exige_inscricao = False
        self.atividade.save()
        self._inscrito(com_inscricao=False, com_presenca=True)
        self.client.force_login(self.palestrante)
        resposta = self.client.get(
            reverse("participante:minha_palestra_inscritos", args=[self.atividade.id])
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Inscrita Teste")
        self.assertContains(resposta, "presença(s) registrada(s)")

    def _inscrito(self, com_inscricao=True, com_presenca=False):
        """Cria uma pessoa com vínculo (e, se pedido, inscrição/presença)."""
        pessoa = U.objects.create_user(
            email="inscrito_mp@example.com", password=SENHA, cpf="52998224725",
            first_name="Inscrita", last_name="Teste",
        )
        ParticipanteMetadados.objects.create(
            participante=pessoa,
            dados={
                "vinculo": "Aluno", "curso": "Informática",
                "turma": "Turma 1", "ano": "Primeiro ano",
            },
        )
        if com_inscricao:
            Inscricao.objects.create(participante=pessoa, atividade=self.atividade)
        if com_presenca:
            Presenca.objects.create(
                atividade=self.atividade, participante=pessoa, papel="participante",
            )
        return pessoa

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


class AtividadeSemInscricaoTests(TestCase):
    """Atividade aberta (ex.: LUAU): não há inscrição, só comparecimento."""

    def setUp(self):
        self.org = U.objects.create_user(
            email="org_si@example.com", password=SENHA, cpf="12345678909",
            is_organizador=True,
        )
        self.participante = U.objects.create_user(
            email="p_si@example.com", password=SENHA, cpf="11144477735"
        )
        self.tipo = TipoAtividade.objects.create(nome="Festa")
        self.evento = Evento.objects.create(
            title="SNCT", description="d", local="Campus",
            data_inicio=date(2030, 10, 10), data_fim=date(2030, 10, 12),
            organizador=self.org,
        )
        self.atividade = Atividade.objects.create(
            evento=self.evento, titulo="LUAU", descricao="d", tipo=self.tipo,
            data_hora_inicio=datetime(2030, 10, 10, 20, 0, tzinfo=tz.utc),
            data_hora_fim=datetime(2030, 10, 10, 23, 0, tzinfo=tz.utc),
            n_vagas=0, exige_inscricao=False,
        )

    def test_inscrever_recusa_quando_nao_exige(self):
        self.client.force_login(self.participante)
        resposta = self.client.get(
            reverse("participante:inscrever", args=[self.atividade.id])
        )
        self.assertEqual(resposta.status_code, 302)
        self.assertFalse(
            Inscricao.objects.filter(
                participante=self.participante, atividade=self.atividade
            ).exists()
        )

    def test_ajax_recusa_quando_nao_exige(self):
        self.client.force_login(self.participante)
        resposta = self.client.post(
            reverse("participante:gerenciar_inscricoes_ajax"),
            data=json.dumps({"atividade_id": self.atividade.id, "inscrito": True}),
            content_type="application/json",
        )
        self.assertEqual(resposta.status_code, 400)
        self.assertFalse(
            Inscricao.objects.filter(
                participante=self.participante, atividade=self.atividade
            ).exists()
        )

    def test_dashboard_mostra_selo(self):
        self.client.force_login(self.participante)
        resposta = self.client.get(reverse("participante:dashboard"))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Não precisa de inscrição")

    def test_programacao_mostra_selo(self):
        resposta = self.client.get(
            reverse("eventos:programacao", args=[self.evento.id])
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Não precisa de inscrição")


class BuscarParticipanteTests(TestCase):
    """A busca de palestrante devolve também a foto (usada nos chips da proposta)."""

    def test_resultado_inclui_foto(self):
        usuario = U.objects.create_user(
            email="quem_busca@example.com", password=SENHA, cpf="12345678909"
        )
        U.objects.create_user(
            email="ana_busca@example.com", password=SENHA, cpf="11144477735",
            first_name="Ana", last_name="Souza",
        )
        self.client.force_login(usuario)

        resposta = self.client.get(
            reverse("participante:buscar_participante"), {"q": "Ana"}
        )

        self.assertEqual(resposta.status_code, 200)
        resultados = resposta.json()["resultados"]
        self.assertTrue(resultados)
        self.assertIn("foto", resultados[0])


class ConflitoFusoTests(TestCase):
    """A mensagem de conflito de horário usa o fuso LOCAL (regressão do UTC)."""

    def test_mensagem_de_conflito_no_fuso_local(self):
        from django.contrib.messages import get_messages
        from django.utils import timezone as dj_timezone

        from eventos.tempo import local_legivel

        org = U.objects.create_user(
            email="org_fuso@example.com", password=SENHA, cpf="12345678909",
            is_organizador=True,
        )
        participante = U.objects.create_user(
            email="part_fuso@example.com", password=SENHA, cpf="11144477735"
        )
        tipo = TipoAtividade.objects.create(nome="Palestra")
        evento = Evento.objects.create(
            title="E", description="d", local="l",
            data_inicio=date(2030, 10, 1), data_fim=date(2030, 10, 2),
            organizador=org,
        )
        inicio = dj_timezone.make_aware(datetime(2030, 10, 5, 10, 0))
        primeira = Atividade.objects.create(
            evento=evento, titulo="Primeira", descricao="d", tipo=tipo, n_vagas=10,
            data_hora_inicio=inicio, data_hora_fim=inicio + timedelta(hours=1),
        )
        segunda = Atividade.objects.create(
            evento=evento, titulo="Segunda", descricao="d", tipo=tipo, n_vagas=10,
            data_hora_inicio=inicio + timedelta(minutes=30),
            data_hora_fim=inicio + timedelta(hours=2),
        )
        Inscricao.objects.create(participante=participante, atividade=primeira)
        self.client.force_login(participante)

        resposta = self.client.get(
            reverse("participante:inscrever", args=[segunda.id])
        )

        mensagens = [str(m) for m in get_messages(resposta.wsgi_request)]
        esperado = local_legivel(primeira.data_hora_inicio)
        self.assertTrue(
            any(esperado in mensagem for mensagem in mensagens), mensagens
        )
