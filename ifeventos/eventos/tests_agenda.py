"""Testes da grade (cronograma) da programação."""

from datetime import datetime, timedelta, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from eventos import agenda
from eventos.models import Atividade, Evento, TipoAtividade

U = get_user_model()


class AtividadeFake:
    """Objeto mínimo: `montar_grade` só usa horários, tipo, título e local."""

    def __init__(self, ini, fim, tipo_id=None, titulo="Atividade", local="", tipo=None):
        self.data_hora_inicio = ini
        self.data_hora_fim = fim
        self.tipo_id = tipo_id
        self.titulo = titulo
        self.local = local
        self.tipo = tipo


class TipoFake:
    def __init__(self, nome):
        self.nome = nome


def local(ano, mes, dia, hora, minuto=0):
    return timezone.make_aware(
        datetime(ano, mes, dia, hora, minuto), timezone.get_current_timezone()
    )


class MontarGradeTests(TestCase):
    def test_vazio(self):
        grade = agenda.montar_grade([])
        self.assertTrue(grade["vazio"])
        self.assertEqual(grade["semanas"], [])

    def test_um_dia_com_duas_atividades(self):
        grade = agenda.montar_grade([
            AtividadeFake(local(2026, 10, 5, 8), local(2026, 10, 5, 9), 1, "A"),
            AtividadeFake(local(2026, 10, 5, 14), local(2026, 10, 5, 15), 1, "B"),
        ])
        self.assertFalse(grade["vazio"])
        self.assertEqual(len(grade["semanas"]), 1)
        self.assertEqual(len(grade["semanas"][0]["colunas"]), 1)

        coluna = grade["semanas"][0]["colunas"][0]
        self.assertEqual(coluna["rotulo"], "Seg")   # 05/10/2026 é segunda
        self.assertEqual(coluna["curta"], "05/10")

        linhas = grade["semanas"][0]["linhas"]
        # Eixo de hora em hora, contínuo (do menor início ao maior fim).
        self.assertEqual(
            [l["rotulo"] for l in linhas],
            ["08:00", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00"],
        )
        self.assertEqual(linhas[0]["celulas"][0]["atividades"][0].titulo, "A")
        self.assertEqual(linhas[6]["celulas"][0]["atividades"][0].titulo, "B")

    def test_varios_dias_viram_varias_colunas(self):
        grade = agenda.montar_grade([
            AtividadeFake(local(2026, 10, 5, 8), local(2026, 10, 5, 9)),
            AtividadeFake(local(2026, 10, 6, 8), local(2026, 10, 6, 9)),
        ])
        colunas = grade["semanas"][0]["colunas"]
        self.assertEqual([c["curta"] for c in colunas], ["05/10", "06/10"])

    def test_sobreposicao_empilha_na_mesma_celula(self):
        grade = agenda.montar_grade([
            AtividadeFake(local(2026, 10, 5, 11), local(2026, 10, 5, 12, 5)),
            AtividadeFake(local(2026, 10, 5, 11), local(2026, 10, 5, 13)),
        ])
        celula = grade["semanas"][0]["linhas"][0]["celulas"][0]
        self.assertEqual(len(celula["atividades"]), 2)

    def test_fim_em_ponto_nao_ocupa_a_hora_seguinte(self):
        grade = agenda.montar_grade([
            AtividadeFake(local(2026, 10, 5, 8), local(2026, 10, 5, 10)),
        ])
        self.assertEqual(
            [l["rotulo"] for l in grade["semanas"][0]["linhas"]], ["08:00", "09:00"]
        )

    def test_fim_com_minutos_ocupa_a_hora_do_fim(self):
        grade = agenda.montar_grade([
            AtividadeFake(local(2026, 10, 5, 8), local(2026, 10, 5, 10, 30)),
        ])
        self.assertEqual(
            [l["rotulo"] for l in grade["semanas"][0]["linhas"]],
            ["08:00", "09:00", "10:00"],
        )

    def test_mais_de_sete_dias_vira_semanas(self):
        atividades = [
            AtividadeFake(local(2026, 10, d, 8), local(2026, 10, d, 9))
            for d in range(1, 11)  # 10 dias -> 2 semanas
        ]
        grade = agenda.montar_grade(atividades)
        self.assertEqual(len(grade["semanas"]), 2)
        self.assertTrue(all(len(s["colunas"]) <= 7 for s in grade["semanas"]))

    def test_cor_por_tipo_e_estavel(self):
        a1 = AtividadeFake(local(2026, 10, 5, 8), local(2026, 10, 5, 9), 7)
        a2 = AtividadeFake(local(2026, 10, 5, 9), local(2026, 10, 5, 10), 7)
        a3 = AtividadeFake(local(2026, 10, 5, 10), local(2026, 10, 5, 11), 9)
        agenda.montar_grade([a1, a2, a3])
        self.assertEqual(a1.agenda_cor, a2.agenda_cor)
        self.assertNotEqual(a1.agenda_cor, a3.agenda_cor)

    def test_agenda_sem_tipo(self):
        a = AtividadeFake(local(2026, 10, 5, 8), local(2026, 10, 5, 9))
        agenda.montar_grade([a])
        self.assertEqual(a.agenda_cor, "agenda-sem-tipo")


class ProgramacaoViewTests(TestCase):
    def setUp(self):
        self.evento = Evento.objects.create(
            title="Mostra", description="Descrição", local="Campus",
            data_inicio="2026-10-05", data_fim="2026-10-09",
        )
        self.tipo = TipoAtividade.objects.create(nome="Palestra")
        self.url = reverse("eventos:programacao", args=[self.evento.id])

    def _atividade(self, dia, hora):
        return Atividade.objects.create(
            evento=self.evento, titulo=f"Atividade {dia}-{hora}", descricao="d",
            tipo=self.tipo, local="Sala 1",
            data_hora_inicio=local(2026, 10, dia, hora),
            data_hora_fim=local(2026, 10, dia, hora + 1),
            n_vagas=10,
        )

    def test_pagina_traz_toggle_e_lista_por_padrao(self):
        self._atividade(5, 8)
        resposta = self.client.get(self.url)
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'data-vista-btn="lista"')
        self.assertContains(resposta, 'data-vista-btn="grade"')
        self.assertEqual(resposta.context["vista"], "lista")

    def test_vista_grade_ativa_o_painel_da_grade(self):
        self._atividade(5, 8)
        resposta = self.client.get(self.url, {"vista": "grade"})
        self.assertEqual(resposta.context["vista"], "grade")
        html = resposta.content.decode()
        # O painel da lista fica escondido; o da grade não.
        self.assertIn('id="vista-lista" data-vista-painel="lista" hidden', html)
        self.assertIn('id="vista-grade" data-vista-painel="grade"', html)

    def test_grade_mostra_dia_hora_e_chip(self):
        self._atividade(5, 8)
        resposta = self.client.get(self.url, {"vista": "grade"})
        self.assertContains(resposta, "agenda-chip")
        self.assertContains(resposta, "Seg")
        self.assertContains(resposta, "08:00")

    def test_sem_atividades_mostra_aviso(self):
        resposta = self.client.get(self.url, {"vista": "grade"})
        self.assertTrue(resposta.context["grade"]["vazio"])
        self.assertContains(resposta, "Nenhuma atividade disponível")

    def test_vista_invalida_cai_na_lista(self):
        resposta = self.client.get(self.url, {"vista": "qualquer"})
        self.assertEqual(resposta.context["vista"], "lista")


class AgruparTests(TestCase):
    def test_por_dia_e_ordenado_por_horario(self):
        secoes = agenda.agrupar([
            AtividadeFake(local(2026, 10, 5, 10), local(2026, 10, 5, 11), titulo="B"),
            AtividadeFake(local(2026, 10, 5, 8), local(2026, 10, 5, 9), titulo="A"),
            AtividadeFake(local(2026, 10, 6, 8), local(2026, 10, 6, 9), titulo="C"),
        ])
        self.assertEqual([s["rotulo"] for s in secoes], ["Seg 05/10", "Ter 06/10"])
        self.assertEqual([s["total"] for s in secoes], [2, 1])
        self.assertEqual([i.titulo for i in secoes[0]["itens"]], ["A", "B"])

    def test_por_local_com_sem_local(self):
        secoes = agenda.agrupar([
            AtividadeFake(local(2026, 10, 5, 8), local(2026, 10, 5, 9), local="Auditório"),
            AtividadeFake(local(2026, 10, 5, 9), local(2026, 10, 5, 10), local="Sala 1"),
            AtividadeFake(local(2026, 10, 5, 11), local(2026, 10, 5, 12), local=""),
        ], ordem="local")
        self.assertEqual(
            [s["rotulo"] for s in secoes],
            ["Auditório", "Sala 1", agenda.SEM_LOCAL],
        )

    def test_por_local_divide_e_repete_nos_varios_lugares(self):
        secoes = agenda.agrupar([
            AtividadeFake(local(2026, 10, 5, 8), local(2026, 10, 5, 9),
                          local="Auditório, Quadra", titulo="Multi"),
        ], ordem="local")
        self.assertEqual([s["rotulo"] for s in secoes], ["Auditório", "Quadra"])
        self.assertEqual([s["total"] for s in secoes], [1, 1])
        self.assertEqual(secoes[0]["itens"][0].titulo, "Multi")

    def test_por_titulo_sem_cabecalho_e_sem_acento(self):
        secoes = agenda.agrupar([
            AtividadeFake(local(2026, 10, 5, 8), local(2026, 10, 5, 9), titulo="Zebra"),
            AtividadeFake(local(2026, 10, 5, 9), local(2026, 10, 5, 10), titulo="Ábaco"),
        ], ordem="titulo")
        self.assertEqual(len(secoes), 1)
        self.assertIsNone(secoes[0]["rotulo"])
        self.assertEqual([i.titulo for i in secoes[0]["itens"]], ["Ábaco", "Zebra"])

    def test_ordem_invalida_cai_no_dia(self):
        secoes = agenda.agrupar(
            [AtividadeFake(local(2026, 10, 5, 8), local(2026, 10, 5, 9))], ordem="x"
        )
        self.assertEqual(secoes[0]["rotulo"], "Seg 05/10")

    def test_vazio(self):
        self.assertEqual(agenda.agrupar([]), [])


class LocaisETiposTests(TestCase):
    def test_locais_divide_por_virgula_e_conta(self):
        locais = agenda.locais_do_evento([
            AtividadeFake(local(2026, 10, 5, 8), local(2026, 10, 5, 9),
                          local="Sala de aula, Auditório"),
            AtividadeFake(local(2026, 10, 5, 9), local(2026, 10, 5, 10), local="Auditório"),
        ])
        self.assertEqual(
            locais,
            [{"nome": "Auditório", "total": 2}, {"nome": "Sala de aula", "total": 1}],
        )

    def test_tipos_com_cor_e_contagem(self):
        palestra, oficina = TipoFake("Palestra"), TipoFake("Oficina")
        tipos = agenda.tipos_do_evento([
            AtividadeFake(local(2026, 10, 5, 8), local(2026, 10, 5, 9), 1, tipo=palestra),
            AtividadeFake(local(2026, 10, 5, 9), local(2026, 10, 5, 10), 1, tipo=palestra),
            AtividadeFake(local(2026, 10, 5, 10), local(2026, 10, 5, 11), 2, tipo=oficina),
        ])
        por_nome = {t["nome"]: t for t in tipos}
        self.assertEqual(por_nome["Palestra"]["total"], 2)
        self.assertEqual(por_nome["Oficina"]["total"], 1)
        self.assertNotEqual(por_nome["Palestra"]["cor"], por_nome["Oficina"]["cor"])

    def test_anotar_gera_locais_com_pipe(self):
        a = AtividadeFake(local(2026, 10, 5, 8), local(2026, 10, 5, 9), local="Auditório, Quadra")
        agenda.anotar([a])
        self.assertEqual(a.agenda_locais, "Auditório|Quadra")

    def test_anotar_gera_horario_de_inicio(self):
        a = AtividadeFake(local(2026, 10, 5, 8, 30), local(2026, 10, 5, 9))
        agenda.anotar([a])
        self.assertEqual(a.agenda_hora, "08:30")


class ProgramacaoFiltrosViewTests(TestCase):
    def setUp(self):
        self.evento = Evento.objects.create(
            title="Mostra", description="d", local="Campus",
            data_inicio="2026-10-05", data_fim="2026-10-09",
        )
        self.tipo = TipoAtividade.objects.create(nome="Palestra")
        self.url = reverse("eventos:programacao", args=[self.evento.id])

    def _atividade(self, dia, hora, nome_local="Sala 1"):
        Atividade.objects.create(
            evento=self.evento, titulo=f"Ativ {dia}-{hora}", descricao="d",
            tipo=self.tipo, local=nome_local,
            data_hora_inicio=local(2026, 10, dia, hora),
            data_hora_fim=local(2026, 10, dia, hora + 1),
            n_vagas=10,
        )

    def test_lista_agrupada_por_dia(self):
        self._atividade(5, 8)
        self._atividade(6, 8)
        resposta = self.client.get(self.url)
        self.assertContains(resposta, "data-secao")
        self.assertContains(resposta, "Seg 05/10")
        self.assertContains(resposta, "Ter 06/10")

    def test_ordem_local_na_view(self):
        self._atividade(5, 8, nome_local="Auditório")
        resposta = self.client.get(self.url, {"ordem": "local"})
        self.assertEqual(resposta.context["ordem"], "local")
        self.assertContains(resposta, "Auditório")

    def test_ordem_invalida_na_view_cai_no_dia(self):
        self._atividade(5, 8)
        resposta = self.client.get(self.url, {"ordem": "xxx"})
        self.assertEqual(resposta.context["ordem"], "dia")

    def test_filtros_renderizam(self):
        self._atividade(5, 8)
        resposta = self.client.get(self.url)
        self.assertContains(resposta, 'data-filtro-local="Sala 1"')
        self.assertContains(resposta, "data-filtro-tipo=")
        self.assertContains(resposta, "data-filtravel")
        self.assertContains(resposta, "ordem=local")
        self.assertContains(resposta, "agenda-legenda")


class AliasLocalTests(TestCase):
    @override_settings(AGENDA_ALIASES_LOCAL={"Lab 1": "Lab"})
    def test_locais_de_aplica_apelido_e_deduplica(self):
        a = AtividadeFake(local(2026, 10, 5, 8), local(2026, 10, 5, 9), local="Lab 1, Lab")
        self.assertEqual(agenda.locais_de(a), ["Lab"])

    @override_settings(AGENDA_ALIASES_LOCAL={"Lab 1": "Lab"})
    def test_locais_do_evento_une_pelo_apelido(self):
        locais = agenda.locais_do_evento([
            AtividadeFake(local(2026, 10, 5, 8), local(2026, 10, 5, 9), local="Lab 1"),
            AtividadeFake(local(2026, 10, 5, 9), local(2026, 10, 5, 10), local="Lab"),
        ])
        self.assertEqual(locais, [{"nome": "Lab", "total": 2}])

    @override_settings(AGENDA_ALIASES_LOCAL={})
    def test_sem_alias_mantem_os_nomes(self):
        a = AtividadeFake(local(2026, 10, 5, 8), local(2026, 10, 5, 9), local="Lab 1")
        self.assertEqual(agenda.locais_de(a), ["Lab 1"])


class MontarIcsTests(TestCase):
    def setUp(self):
        self.evento = Evento.objects.create(
            title="Mostra; C&T", description="d", local="Campus",
            data_inicio="2026-10-05", data_fim="2026-10-05",
        )
        self.tipo = TipoAtividade.objects.create(nome="Palestra")
        self.atividade = Atividade.objects.create(
            evento=self.evento, titulo="Oficina, prática", descricao="Linha1\nLinha2",
            tipo=self.tipo, local="",
            data_hora_inicio=local(2026, 10, 5, 8),
            data_hora_fim=local(2026, 10, 5, 9), n_vagas=5,
        )

    def test_conteudo_do_ics(self):
        ics = agenda.montar_ics(self.evento, [self.atividade])

        self.assertTrue(ics.startswith("BEGIN:VCALENDAR\r\n"))
        self.assertTrue(ics.endswith("END:VCALENDAR\r\n"))
        self.assertEqual(ics.count("BEGIN:VEVENT"), 1)
        self.assertIn(f"UID:{self.atividade.codigo_confirmacao}@ifeventos", ics)

        esperado_ini = self.atividade.data_hora_inicio.astimezone(
            dt_timezone.utc
        ).strftime("%Y%m%dT%H%M%SZ")
        self.assertIn(f"DTSTART:{esperado_ini}", ics)

        # Escapes da RFC: vírgula no título, quebra de linha na descrição e o
        # sem-ponto-e-vírgula do nome do calendário.
        self.assertIn("SUMMARY:Oficina\\, prática", ics)
        self.assertIn("\\n", ics)
        self.assertIn("X-WR-CALNAME:Mostra\\; C&T", ics)
        # Sem local na atividade, usa o do evento.
        self.assertIn("LOCATION:Campus", ics)

    def test_sem_atividades(self):
        ics = agenda.montar_ics(self.evento, [])
        self.assertEqual(ics.count("BEGIN:VEVENT"), 0)


class AgendaIcsViewTests(TestCase):
    def setUp(self):
        self.evento = Evento.objects.create(
            title="Semana de Tecnologia", description="d", local="Campus",
            data_inicio="2026-10-05", data_fim="2026-10-06",
        )
        self.tipo = TipoAtividade.objects.create(nome="Oficina")
        self.a1 = Atividade.objects.create(
            evento=self.evento, titulo="A", descricao="d", tipo=self.tipo, local="Sala 1",
            data_hora_inicio=local(2026, 10, 5, 8),
            data_hora_fim=local(2026, 10, 5, 9), n_vagas=5,
        )
        self.a2 = Atividade.objects.create(
            evento=self.evento, titulo="B", descricao="d", tipo=self.tipo, local="Sala 2",
            data_hora_inicio=local(2026, 10, 6, 8),
            data_hora_fim=local(2026, 10, 6, 9), n_vagas=5,
        )
        self.url = reverse("eventos:agenda_ics", args=[self.evento.id])

    def test_baixa_a_programacao_inteira(self):
        resposta = self.client.get(self.url)
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta["Content-Type"].startswith("text/calendar"))
        self.assertIn("attachment", resposta["Content-Disposition"])
        self.assertIn("programacao-semana-de-tecnologia.ics", resposta["Content-Disposition"])
        self.assertEqual(resposta.content.decode().count("BEGIN:VEVENT"), 2)

    def test_exporta_apenas_os_favoritos(self):
        resposta = self.client.get(self.url, {"favoritos": str(self.a1.id)})
        texto = resposta.content.decode()
        self.assertEqual(texto.count("BEGIN:VEVENT"), 1)
        self.assertIn(str(self.a1.codigo_confirmacao), texto)
        self.assertNotIn(str(self.a2.codigo_confirmacao), texto)


class ParalelasViewTests(TestCase):
    """Atividades no MESMO horário viram um bloco com leque e "+N"."""

    def setUp(self):
        self.evento = Evento.objects.create(
            title="Mostra", description="d", local="Campus",
            data_inicio="2026-10-05", data_fim="2026-10-05",
        )
        self.tipo = TipoAtividade.objects.create(nome="Oficina")
        self.url = reverse("eventos:programacao", args=[self.evento.id])

    def _juntas(self, quantas, hora=8, minuto=0):
        for i in range(quantas):
            Atividade.objects.create(
                evento=self.evento, titulo=f"Oficina {i}", descricao="d",
                tipo=self.tipo, local=f"Sala {i}",
                data_hora_inicio=local(2026, 10, 5, hora, minuto),
                data_hora_fim=local(2026, 10, 5, hora + 1, minuto),
                n_vagas=10,
            )

    def test_quatro_no_mesmo_horario_tem_leque_e_botao(self):
        self._juntas(4)
        html = self.client.get(self.url, {"vista": "grade"}).content.decode()

        self.assertIn("agenda-paralelas is-paralelo", html)
        self.assertIn("em paralelo", html)
        self.assertIn("08:00 · 4 em paralelo", html)
        self.assertIn("is-extra", html)          # a 4ª vai para o "resto"
        self.assertIn("+1 no mesmo horário", html)

    def test_horarios_diferentes_nao_viram_bloco(self):
        self._juntas(2, hora=8)
        self._juntas(2, hora=8, minuto=30)
        html = self.client.get(self.url, {"vista": "grade"}).content.decode()

        self.assertIn("08:00 · 2 em paralelo", html)
        self.assertIn("08:30 · 2 em paralelo", html)
        self.assertNotIn("4 em paralelo", html)

    def test_uma_so_nao_tem_cabecalho_de_paralelo(self):
        self._juntas(1)
        html = self.client.get(self.url, {"vista": "grade"}).content.decode()
        self.assertIn("agenda-paralelas", html)
        self.assertNotIn("em paralelo", html)


class ChoquesTests(TestCase):
    """Conflitos de grade: mesma sala e/ou palestrante no mesmo horário."""

    def setUp(self):
        self.evento = Evento.objects.create(
            title="E", description="d", local="Campus",
            data_inicio="2026-10-05", data_fim="2026-10-05",
        )
        self.tipo = TipoAtividade.objects.create(nome="Oficina")
        self.pessoa = U.objects.create_user(
            email="palestrante@example.com", password="Senha12345!", first_name="Ana"
        )

    def _cria(self, titulo, h, dur, sala="", palestrantes=()):
        a = Atividade.objects.create(
            evento=self.evento, titulo=titulo, descricao="d", tipo=self.tipo, local=sala,
            data_hora_inicio=local(2026, 10, 5, h),
            data_hora_fim=local(2026, 10, 5, h + dur), n_vagas=10,
        )
        if palestrantes:
            a.palestrantes.set(palestrantes)
        return a

    def test_mesma_sala_no_mesmo_horario(self):
        self._cria("A", 8, 1, sala="Sala 1")
        self._cria("B", 8, 2, sala="Sala 1")
        avisos = agenda.choques(self.evento.atividades.all())
        self.assertEqual(len(avisos), 1)
        self.assertEqual(avisos[0]["tipo"], "sala")
        self.assertEqual(avisos[0]["rotulo"], "Sala 1")

    def test_mesmo_palestrante_no_mesmo_horario(self):
        self._cria("A", 8, 1, sala="Sala 1", palestrantes=[self.pessoa])
        self._cria("B", 8, 1, sala="Sala 2", palestrantes=[self.pessoa])
        avisos = agenda.choques(self.evento.atividades.all())
        self.assertEqual([a["tipo"] for a in avisos], ["palestrante"])

    def test_horarios_diferentes_nao_conflitam(self):
        self._cria("A", 8, 1, sala="Sala 1", palestrantes=[self.pessoa])
        self._cria("B", 9, 1, sala="Sala 1", palestrantes=[self.pessoa])
        self.assertEqual(agenda.choques(self.evento.atividades.all()), [])

    def test_salas_e_palestrantes_diferentes(self):
        self._cria("A", 8, 1, sala="Sala 1")
        self._cria("B", 8, 1, sala="Sala 2")
        self.assertEqual(agenda.choques(self.evento.atividades.all()), [])
