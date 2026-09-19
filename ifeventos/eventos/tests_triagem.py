"""Testes da pré-triagem de propostas (copiloto do organizador).

Cobrem os sinais objetivos (sem IA), a sanitização da resposta do modelo, o
fallback quando a IA está indisponível, a ausência de PII no dossiê e a view.
"""

from datetime import datetime, time, timedelta
from unittest import mock
from unittest.mock import AsyncMock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from asgiref.sync import async_to_sync

from eventos import triagem
from eventos.models import Atividade, ChamadaProposicoes, Espaco, Evento, TipoAtividade, Vaga

U = get_user_model()
SENHA = "SenhaForte123!"

# A triagem em teste não pode depender da tabela de cache do banco.
CACHE_LOCMEM = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}


class _FixturesMixin:
    """Evento futuro com chamada aberta, espaço e vaga (14h–16h)."""

    def setUp(self):
        cache.clear()
        self.org = U.objects.create_user(
            email="org_tri@example.com", password=SENHA, cpf="12345678909",
            is_organizador=True,
        )
        self.pessoa = U.objects.create_user(
            email="pessoa_tri@example.com", password=SENHA, cpf="11144477735",
        )
        self.tipo = TipoAtividade.objects.create(nome="Oficina")

        hoje = timezone.localdate()
        self.evento = Evento.objects.create(
            title="Evento da Triagem", description="d", local="Campus",
            data_inicio=hoje + timedelta(days=10),
            data_fim=hoje + timedelta(days=12),
            categoria="formacao", organizador=self.org,
        )
        agora = timezone.now()
        ChamadaProposicoes.objects.create(
            evento=self.evento, titulo="Chamada", inicio=agora - timedelta(days=1),
            fim=agora + timedelta(days=5), aberta=True,
        )
        self.espaco = Espaco.objects.create(nome="Auditório", capacidade=40)
        dia = self.evento.data_inicio
        self.inicio = timezone.make_aware(datetime.combine(dia, time(14, 0)))
        self.fim = timezone.make_aware(datetime.combine(dia, time(16, 0)))
        self.vaga = Vaga.objects.create(
            evento=self.evento, espaco=self.espaco,
            inicio=self.inicio, fim=self.fim, capacidade=2,
        )

    def _propor(self, usuario=None, **extra):
        from eventos import propostas

        dados = {
            "vaga": self.vaga, "titulo": "Minha proposta",
            "descricao": "Descrição suficientemente longa para não acionar o alerta de texto curto.",
            "tipo": self.tipo,
        }
        dados.update(extra)
        return propostas.propor(usuario or self.pessoa, self.evento, **dados)

    def _tipos_por_chave(self):
        return {
            "oficina": {"id": self.tipo.pk, "nome": self.tipo.nome},
        }


class TriagemDeterministicaTests(_FixturesMixin, TestCase):
    """Camada 1 (sem IA) e sanitização da resposta."""

    def test_dossie_nao_leva_pii(self):
        proposta = self._propor()
        dossie = triagem.montar_dossie(proposta, self.evento, self._tipos_por_chave())

        texto = repr(dossie)
        self.assertNotIn("pessoa_tri@example.com", texto)
        self.assertNotIn("11144477735", texto)

    def test_prompt_nao_leva_pii(self):
        proposta = self._propor()
        dossie = triagem.montar_dossie(proposta, self.evento, self._tipos_por_chave())
        prompt = triagem._prompt([dossie], self.evento, [self.tipo])

        self.assertNotIn("pessoa_tri@example.com", prompt)
        self.assertNotIn("11144477735", prompt)

    def test_alerta_de_conflito_de_espaco(self):
        proposta = self._propor(titulo="Concorrente")
        # A atividade concorrente é criada DEPOIS: no envio, o conflito bloquearia
        # a proposta (a triagem é justamente para enxergar o que já existe).
        Atividade.objects.create(
            evento=self.evento, titulo="Outra atividade", descricao="d",
            local="Auditório", tipo=self.tipo,
            data_hora_inicio=self.inicio, data_hora_fim=self.fim,
        )

        alertas = triagem.alertas_objetivos(proposta, self.evento, self._tipos_por_chave())
        self.assertTrue(any(a.startswith("Choque de espaço") for a in alertas))

    def test_alerta_vagas_acima_da_capacidade(self):
        proposta = self._propor(titulo="Lotada", n_vagas=999)
        alertas = triagem.alertas_objetivos(proposta, self.evento, self._tipos_por_chave())
        self.assertTrue(any("acima da capacidade" in a for a in alertas))

    def test_alerta_descricao_curta(self):
        proposta = self._propor(titulo="Curta", descricao="curta")
        alertas = triagem.alertas_objetivos(proposta, self.evento, self._tipos_por_chave())
        self.assertTrue(any(a.startswith("Descrição muito curta") for a in alertas))

    def test_detecta_duplicatas(self):
        texto = "Oficina de robótica com montagem de protótipos e programação em blocos."
        self._propor(titulo="Oficina de robótica", descricao=texto)
        outro = U.objects.create_user(
            email="outro_tri@example.com", password=SENHA, cpf="39053344705"
        )
        self._propor(usuario=outro, titulo="Oficina de robótica", descricao=texto)

        dossies = triagem.coletar_dossies(self.evento)
        self.assertEqual(len(dossies), 2)
        self.assertTrue(all(d["duplicata_de"] for d in dossies))

    def test_decisao_heuristica_aprova_sem_conflito(self):
        proposta = self._propor(
            titulo="Oficina de robótica",
            descricao="x" * 150,
        )
        dossie = triagem.montar_dossie(proposta, self.evento, self._tipos_por_chave())
        score, decisao, _justificativa = triagem.decisao_heuristica(dossie)

        self.assertGreaterEqual(score, 80)
        self.assertEqual(decisao, "aprovar")

    def test_sanitiza_decisao_invalida_e_score_fora_do_range(self):
        proposta = self._propor()
        dossie = triagem.montar_dossie(proposta, self.evento, self._tipos_por_chave())
        item = triagem.sanitizar_item(
            {"score": 999, "decisao": "explodir", "tipo_sugerido_id": 424242},
            dossie, {self.tipo.pk},
        )

        self.assertEqual(item["score"], 100)
        self.assertIn(item["decisao"], triagem.DECISOES)
        self.assertNotEqual(item["tipo_sugerido_id"], 424242)

    def test_sanitiza_aceita_tipo_do_catalogo(self):
        proposta = self._propor()
        dossie = triagem.montar_dossie(proposta, self.evento, self._tipos_por_chave())
        item = triagem.sanitizar_item(
            {"decisao": "aprovar", "tipo_sugerido_id": self.tipo.pk},
            dossie, {self.tipo.pk},
        )
        self.assertEqual(item["tipo_sugerido_id"], self.tipo.pk)


@override_settings(CACHES=CACHE_LOCMEM)
class TriagemOrquestracaoTests(_FixturesMixin, TransactionTestCase):
    """Orquestração async: fallback, IA e cache."""

    def test_sem_propostas_nao_consulta_ia(self):
        resultado = async_to_sync(triagem.analisar_evento)(self.evento)
        self.assertEqual(resultado["itens"], [])
        self.assertIsNone(resultado["origem"])

    def test_sem_ia_usa_heuristica(self):
        self._propor()
        with mock.patch.object(
            triagem.services, "get_openai_client", side_effect=RuntimeError("sem chave")
        ):
            resultado = async_to_sync(triagem.analisar_evento)(self.evento)

        self.assertEqual(resultado["origem"], "heuristica")
        self.assertEqual(len(resultado["itens"]), 1)
        self.assertIn(resultado["itens"][0]["decisao"], triagem.DECISOES)

    def test_ia_aplica_sugestao(self):
        proposta = self._propor(titulo="Proposta fora do tema")
        retorno = [{
            "proposta_id": proposta.pk,
            "score": 20,
            "decisao": "rejeitar",
            "justificativa": "Fora do tema do evento.",
            "tipo_sugerido_id": None,
            "qualidade_descricao": "fraca",
            "motivo_rejeicao_sugerido": "Fora do tema do evento.",
        }]
        with mock.patch.object(triagem, "_chamar_ia", new=AsyncMock(return_value=retorno)):
            resultado = async_to_sync(triagem.analisar_evento)(self.evento)

        self.assertEqual(resultado["origem"], "ia")
        item = resultado["itens"][0]
        self.assertEqual(item["decisao"], "rejeitar")
        self.assertEqual(item["score"], 20)
        self.assertEqual(item["motivo_rejeicao_sugerido"], "Fora do tema do evento.")

    def test_cache_evita_segunda_chamada(self):
        self._propor()
        retorno = [{"proposta_id": 0, "decisao": "aprovar", "score": 80}]
        with mock.patch.object(
            triagem, "_chamar_ia", new=AsyncMock(return_value=retorno)
        ) as chamada:
            async_to_sync(triagem.analisar_evento)(self.evento)
            async_to_sync(triagem.analisar_evento)(self.evento)

        self.assertEqual(chamada.await_count, 1)

    def test_forcar_ignora_o_cache(self):
        self._propor()
        retorno = [{"proposta_id": 0, "decisao": "aprovar", "score": 80}]
        with mock.patch.object(
            triagem, "_chamar_ia", new=AsyncMock(return_value=retorno)
        ) as chamada:
            async_to_sync(triagem.analisar_evento)(self.evento)
            async_to_sync(triagem.analisar_evento)(self.evento, forcar=True)

        self.assertEqual(chamada.await_count, 2)


@override_settings(CACHES=CACHE_LOCMEM)
class TriagemViewTests(_FixturesMixin, TransactionTestCase):
    """Endpoint AJAX: permissão e formato da resposta."""

    def test_permissao_exige_organizador(self):
        self.client.force_login(self.pessoa)
        resposta = self.client.post(
            reverse("organizador:triagem_propostas", args=[self.evento.id])
        )
        self.assertEqual(resposta.status_code, 403)

    def test_organizador_recebe_sugestoes(self):
        proposta = self._propor()
        self.client.force_login(self.org)
        retorno = [{
            "proposta_id": proposta.pk, "score": 90, "decisao": "aprovar",
            "justificativa": "ok",
        }]
        with mock.patch.object(triagem, "_chamar_ia", new=AsyncMock(return_value=retorno)):
            resposta = self.client.post(
                reverse("organizador:triagem_propostas", args=[self.evento.id])
            )

        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()
        self.assertEqual(dados["origem"], "ia")
        self.assertEqual(dados["itens"][0]["proposta_id"], proposta.pk)
