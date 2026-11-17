"""Regra do evento em foco (eventos/contexto.py) — sem banco, só a ordenação."""

from datetime import date, timedelta
from types import SimpleNamespace

from django.test import SimpleTestCase

from eventos import contexto


def _evento(pk, inicio, fim):
    return SimpleNamespace(id=pk, data_inicio=inicio, data_fim=fim)


HOJE = date(2026, 11, 16)


class ClassificarTests(SimpleTestCase):
    def test_separa_atual_futuro_e_passado_pelas_bordas(self):
        atual = _evento(1, HOJE, HOJE)
        futuro = _evento(2, HOJE + timedelta(days=1), HOJE + timedelta(days=2))
        passado = _evento(3, HOJE - timedelta(days=2), HOJE - timedelta(days=1))

        grupos = contexto.classificar([futuro, passado, atual], hoje=HOJE)

        self.assertEqual([e.id for e in grupos["atuais"]], [1])
        self.assertEqual([e.id for e in grupos["futuros"]], [2])
        self.assertEqual([e.id for e in grupos["passados"]], [3])

    def test_simultaneos_mostram_o_que_comecou_por_ultimo(self):
        mais_antigo = _evento(1, HOJE - timedelta(days=3), HOJE + timedelta(days=1))
        mais_novo = _evento(2, HOJE - timedelta(days=1), HOJE + timedelta(days=1))

        grupos = contexto.classificar([mais_antigo, mais_novo], hoje=HOJE)

        self.assertEqual([e.id for e in grupos["atuais"]], [2, 1])
        self.assertEqual(grupos["atuais"][0].situacao_contexto, contexto.ATUAL)

    def test_futuros_do_mais_proximo_ao_mais_distante(self):
        perto = _evento(1, HOJE + timedelta(days=2), HOJE + timedelta(days=3))
        longe = _evento(2, HOJE + timedelta(days=20), HOJE + timedelta(days=21))

        grupos = contexto.classificar([longe, perto], hoje=HOJE)

        self.assertEqual([e.id for e in grupos["futuros"]], [1, 2])
        self.assertEqual(grupos["futuros"][0].situacao_contexto, contexto.PROXIMO)

    def test_passados_do_mais_recente_ao_mais_antigo(self):
        antigo = _evento(1, HOJE - timedelta(days=90), HOJE - timedelta(days=80))
        recente = _evento(2, HOJE - timedelta(days=10), HOJE - timedelta(days=5))

        grupos = contexto.classificar([antigo, recente], hoje=HOJE)

        self.assertEqual([e.id for e in grupos["passados"]], [2, 1])
        self.assertEqual(grupos["passados"][0].situacao_contexto, contexto.ENCERRADO)


class ResolverPadraoTests(SimpleTestCase):
    def _grupos(self):
        return contexto.classificar(
            [
                _evento(1, HOJE - timedelta(days=1), HOJE + timedelta(days=1)),
                _evento(2, HOJE + timedelta(days=5), HOJE + timedelta(days=6)),
                _evento(3, HOJE - timedelta(days=9), HOJE - timedelta(days=8)),
            ],
            hoje=HOJE,
        )

    def test_sem_escolha_usa_o_evento_atual(self):
        usuario = SimpleNamespace(evento_padrao=None)

        padrao = contexto.resolver_padrao(usuario, self._grupos())

        self.assertEqual(padrao.id, 1)

    def test_sem_atual_usa_o_proximo(self):
        grupos = contexto.classificar(
            [
                _evento(2, HOJE + timedelta(days=5), HOJE + timedelta(days=6)),
                _evento(3, HOJE - timedelta(days=9), HOJE - timedelta(days=8)),
            ],
            hoje=HOJE,
        )
        usuario = SimpleNamespace(evento_padrao=None)

        self.assertEqual(contexto.resolver_padrao(usuario, grupos).id, 2)

    def test_sem_atual_nem_futuro_usa_o_passado_mais_recente(self):
        grupos = contexto.classificar(
            [_evento(3, HOJE - timedelta(days=9), HOJE - timedelta(days=8))],
            hoje=HOJE,
        )
        usuario = SimpleNamespace(evento_padrao=None)

        self.assertEqual(contexto.resolver_padrao(usuario, grupos).id, 3)

    def test_escolha_salva_vence_enquanto_nao_terminou(self):
        grupos = self._grupos()
        usuario = SimpleNamespace(
            evento_padrao=_evento(2, HOJE + timedelta(days=5), HOJE + timedelta(days=6))
        )

        padrao = contexto.resolver_padrao(usuario, grupos)

        self.assertEqual(padrao.id, 2)
        # Devolve o objeto dos grupos (com o selo), não a instância da FK.
        self.assertEqual(padrao.situacao_contexto, contexto.PROXIMO)

    def test_escolha_salva_que_terminou_e_ignorada(self):
        grupos = self._grupos()
        usuario = SimpleNamespace(
            evento_padrao=_evento(3, HOJE - timedelta(days=9), HOJE - timedelta(days=8))
        )

        self.assertEqual(contexto.resolver_padrao(usuario, grupos).id, 1)

    def test_sem_eventos_devolve_nada(self):
        self.assertIsNone(
            contexto.resolver_padrao(
                SimpleNamespace(evento_padrao=None),
                {"atuais": [], "futuros": [], "passados": []},
            )
        )
