"""Regra do evento em foco (eventos/contexto.py) — sem banco, só a ordenação."""

from datetime import date, datetime, timedelta, timezone as tz
from types import SimpleNamespace

from django.test import SimpleTestCase

from eventos import contexto


def _evento(pk, inicio, fim, arquivado_em=None):
    return SimpleNamespace(
        id=pk, data_inicio=inicio, data_fim=fim, arquivado_em=arquivado_em
    )


HOJE = date(2026, 11, 16)
ARQUIVADO_AGORA = datetime(2026, 11, 16, 12, 0, tzinfo=tz.utc)


class ClassificarTests(SimpleTestCase):
    def test_separa_atual_futuro_terminado_e_arquivado(self):
        atual = _evento(1, HOJE, HOJE)
        futuro = _evento(2, HOJE + timedelta(days=1), HOJE + timedelta(days=2))
        terminado = _evento(3, HOJE - timedelta(days=2), HOJE - timedelta(days=1))
        arquivado = _evento(
            4, HOJE - timedelta(days=9), HOJE - timedelta(days=8), ARQUIVADO_AGORA
        )

        grupos = contexto.classificar(
            [futuro, terminado, arquivado, atual], hoje=HOJE
        )

        self.assertEqual([e.id for e in grupos["atuais"]], [1])
        self.assertEqual([e.id for e in grupos["futuros"]], [2])
        self.assertEqual([e.id for e in grupos["a_encerrar"]], [3])
        self.assertEqual([e.id for e in grupos["arquivados"]], [4])

    def test_data_vencida_sem_encerrar_fica_em_a_encerrar(self):
        terminado = _evento(1, HOJE - timedelta(days=3), HOJE - timedelta(days=2))

        grupos = contexto.classificar([terminado], hoje=HOJE)

        self.assertEqual([e.id for e in grupos["a_encerrar"]], [1])
        self.assertEqual(grupos["a_encerrar"][0].situacao_contexto, contexto.TERMINADO)
        self.assertEqual(grupos["arquivados"], [])

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

    def test_a_encerrar_do_mais_recente_ao_mais_antigo(self):
        antigo = _evento(1, HOJE - timedelta(days=90), HOJE - timedelta(days=80))
        recente = _evento(2, HOJE - timedelta(days=10), HOJE - timedelta(days=5))

        grupos = contexto.classificar([antigo, recente], hoje=HOJE)

        self.assertEqual([e.id for e in grupos["a_encerrar"]], [2, 1])

    def test_arquivados_pelo_encerramento_mais_recente(self):
        antigo = _evento(
            1, HOJE - timedelta(days=90), HOJE - timedelta(days=80),
            ARQUIVADO_AGORA - timedelta(days=30),
        )
        recente = _evento(
            2, HOJE - timedelta(days=10), HOJE - timedelta(days=5), ARQUIVADO_AGORA
        )

        grupos = contexto.classificar([antigo, recente], hoje=HOJE)

        self.assertEqual([e.id for e in grupos["arquivados"]], [2, 1])
        self.assertEqual(
            grupos["arquivados"][0].situacao_contexto, contexto.ARQUIVADO
        )


class ResolverPadraoTests(SimpleTestCase):
    def _grupos(self):
        return contexto.classificar(
            [
                _evento(1, HOJE - timedelta(days=1), HOJE + timedelta(days=1)),
                _evento(2, HOJE + timedelta(days=5), HOJE + timedelta(days=6)),
                _evento(3, HOJE - timedelta(days=9), HOJE - timedelta(days=8)),
                _evento(
                    4, HOJE - timedelta(days=20), HOJE - timedelta(days=19),
                    ARQUIVADO_AGORA,
                ),
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

    def test_sem_atual_nem_futuro_usa_o_terminado_mais_recente(self):
        grupos = contexto.classificar(
            [_evento(3, HOJE - timedelta(days=9), HOJE - timedelta(days=8))],
            hoje=HOJE,
        )
        usuario = SimpleNamespace(evento_padrao=None)

        self.assertEqual(contexto.resolver_padrao(usuario, grupos).id, 3)

    def test_arquivado_nunca_e_padrao(self):
        grupos = contexto.classificar(
            [
                _evento(
                    4, HOJE - timedelta(days=20), HOJE - timedelta(days=19),
                    ARQUIVADO_AGORA,
                )
            ],
            hoje=HOJE,
        )
        usuario = SimpleNamespace(evento_padrao=None)

        self.assertIsNone(contexto.resolver_padrao(usuario, grupos))

    def test_escolha_salva_vence_enquanto_nao_encerrou(self):
        grupos = self._grupos()
        usuario = SimpleNamespace(
            evento_padrao=_evento(2, HOJE + timedelta(days=5), HOJE + timedelta(days=6))
        )

        padrao = contexto.resolver_padrao(usuario, grupos)

        self.assertEqual(padrao.id, 2)
        # Devolve o objeto dos grupos (com o selo), não a instância da FK.
        self.assertEqual(padrao.situacao_contexto, contexto.PROXIMO)

    def test_escolha_salva_de_evento_arquivado_e_ignorada(self):
        grupos = self._grupos()
        usuario = SimpleNamespace(
            evento_padrao=_evento(
                4, HOJE - timedelta(days=20), HOJE - timedelta(days=19),
                ARQUIVADO_AGORA,
            )
        )

        self.assertEqual(contexto.resolver_padrao(usuario, grupos).id, 1)

    def test_sem_eventos_devolve_nada(self):
        self.assertIsNone(
            contexto.resolver_padrao(
                SimpleNamespace(evento_padrao=None),
                {"atuais": [], "futuros": [], "a_encerrar": [], "arquivados": []},
            )
        )
