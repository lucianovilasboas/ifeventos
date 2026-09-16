"""Testes da grade (cronograma) da programação."""

from datetime import datetime, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from eventos import agenda
from eventos.models import Atividade, Evento, TipoAtividade


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
        self.assertEqual(linhas[0]["celulas"][0][0].titulo, "A")
        self.assertEqual(linhas[6]["celulas"][0][0].titulo, "B")

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
        self.assertEqual(len(celula), 2)

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
