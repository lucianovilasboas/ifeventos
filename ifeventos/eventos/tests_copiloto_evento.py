"""Testes do copiloto de criação de evento (plano de programação)."""

import json
from datetime import datetime, time, timedelta
from unittest import mock
from unittest.mock import AsyncMock

from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from asgiref.sync import async_to_sync

from eventos import copiloto_evento as cop
from eventos.models import Atividade, Evento, TipoAtividade

U = get_user_model()
SENHA = "SenhaForte123!"


class _FakeOpenAI:
    def __init__(self, conteudo):
        resposta = mock.MagicMock()
        resposta.choices = [mock.MagicMock()]
        resposta.choices[0].message.content = conteudo
        resposta.usage = None
        self.chat = mock.MagicMock()
        self.chat.completions.create = AsyncMock(return_value=resposta)


class _FixturesMixin:
    def setUp(self):
        self.org = U.objects.create_user(
            email="org_cop@example.com", password=SENHA, cpf="12345678909",
            is_organizador=True,
        )
        self.pessoa = U.objects.create_user(
            email="pessoa_cop@example.com", password=SENHA, cpf="11144477735",
        )
        self.tipo = TipoAtividade.objects.create(nome="Oficina")
        hoje = timezone.localdate()
        self.evento = Evento.objects.create(
            title="Semana de Tecnologia", description="d", local="Campus",
            data_inicio=hoje + timedelta(days=10),
            data_fim=hoje + timedelta(days=12),
            categoria="tecnologia", organizador=self.org,
        )


class SanitizarPlanoTests(_FixturesMixin, TestCase):
    def test_normaliza_turno(self):
        self.assertEqual(cop.normalizar_turno("Manhã"), "manha")
        self.assertEqual(cop.normalizar_turno("VESPERTINO"), "tarde")
        self.assertEqual(cop.normalizar_turno("noite"), "noite")
        self.assertEqual(cop.normalizar_turno("qualquer"), "")

    def test_limita_atividades_e_blocos(self):
        dados = {
            "descricao": "  uma   descrição  ",
            "categoria": "Tecnologia",
            "blocos": ["08:00-10:00", "x", "10:00-12:00", "12:00", "13:30-15:30",
                       "15:30-17:30", "18:00-20:00", "20:00-22:00"],
            "atividades": [
                {"titulo": "At %d" % i, "tipo": "Oficina", "turno": "manhã"}
                for i in range(12)
            ],
        }
        plano = cop.sanitizar_plano(dados, self.evento, [self.tipo])

        self.assertEqual(plano["descricao"], "uma descrição")
        self.assertEqual(plano["categoria"], "Tecnologia")
        self.assertLessEqual(len(plano["blocos"]), cop.MAX_BLOCOS)
        self.assertLessEqual(len(plano["atividades"]), cop.MAX_ATIVIDADES)
        self.assertEqual(plano["atividades"][0]["turno"], "manha")
        # "Oficina" foi casada com o catálogo.
        self.assertEqual(plano["atividades"][0]["tipo"], "Oficina")

    def test_descarta_sem_titulo(self):
        plano = cop.sanitizar_plano(
            {"atividades": [{"titulo": ""}, {"titulo": "Válida"}]}, self.evento, []
        )
        self.assertEqual([a["titulo"] for a in plano["atividades"]], ["Válida"])


class PlanoParaLinhasTests(_FixturesMixin, TestCase):
    def test_distribui_dia_e_turno(self):
        plano = {"atividades": [
            {"titulo": "A1", "descricao": "d", "tipo": "Oficina", "turno": "manha"},
            {"titulo": "A2", "descricao": "d", "tipo": "Oficina", "turno": "tarde"},
        ]}
        linhas = cop.plano_para_linhas(plano, self.evento)

        dia1 = self.evento.data_inicio.strftime("%d/%m/%Y")
        dia2 = (self.evento.data_inicio + timedelta(days=1)).strftime("%d/%m/%Y")
        self.assertEqual(linhas[0]["inicio"], "%s 08:00" % dia1)
        self.assertEqual(linhas[0]["fim"], "%s 12:00" % dia1)
        self.assertEqual(linhas[1]["inicio"], "%s 13:30" % dia2)
        self.assertEqual(linhas[1]["tipo"], "Oficina")

    def test_tipo_inexistente_vira_vazio(self):
        linhas = cop.plano_para_linhas(
            {"atividades": [{"titulo": "A", "tipo": "Inexistente", "turno": "manha"}]},
            self.evento,
        )
        self.assertEqual(linhas[0]["tipo"], "")


class GerarPlanoTests(_FixturesMixin, TransactionTestCase):
    def test_fallback_sem_ia(self):
        with mock.patch("eventos.services.get_openai_client", side_effect=RuntimeError("x")):
            plano = async_to_sync(cop.gerar_plano)(
                "Semana de Tecnologia", "oficinas", "tecnologia", self.evento
            )
        self.assertEqual(plano["origem"], "heuristica")
        self.assertTrue(plano["blocos"])
        self.assertEqual(plano["atividades"], [])

    def test_ia_devolve_plano_sanitizado(self):
        conteudo = json.dumps({
            "descricao": "Venha participar!",
            "categoria": "Tecnologia",
            "blocos": ["08:00-10:00"],
            "atividades": [{"titulo": "Oficina de Robótica", "descricao": "d",
                            "tipo": "Oficina", "turno": "manhã"}],
        })
        with mock.patch("eventos.services.get_openai_client", return_value=_FakeOpenAI(conteudo)):
            plano = async_to_sync(cop.gerar_plano)(
                "Semana de Tecnologia", "", "", self.evento
            )
        self.assertEqual(plano["origem"], "ia")
        self.assertEqual(plano["categoria"], "Tecnologia")
        self.assertEqual(plano["atividades"][0]["titulo"], "Oficina de Robótica")


class CopilotoViewTests(_FixturesMixin, TransactionTestCase):
    def test_copiloto_exige_organizador(self):
        self.client.force_login(self.pessoa)
        resposta = self.client.post(
            reverse("organizador:copiloto_evento", args=[self.evento.id]),
            data=json.dumps({"titulo": "X"}), content_type="application/json",
        )
        self.assertEqual(resposta.status_code, 403)

    def test_copiloto_devolve_plano(self):
        self.client.force_login(self.org)
        with mock.patch("eventos.services.get_openai_client", side_effect=RuntimeError("x")):
            resposta = self.client.post(
                reverse("organizador:copiloto_evento", args=[self.evento.id]),
                data=json.dumps({"titulo": "Semana de Tecnologia"}),
                content_type="application/json",
            )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json()["origem"], "heuristica")

    def test_edicao_renderiza_botoes_ia_e_remover_rascunho(self):
        self.client.force_login(self.org)
        html = self.client.get(
            reverse("organizador:editar_evento", args=[self.evento.id])
        ).content.decode()
        self.assertIn("btn-ia", html)
        self.assertIn("Remover rascunho", html)
        self.assertIn("divulgacaoGerar", html)

    def test_aplicar_plano_cria_rascunhos(self):
        self.client.force_login(self.org)
        plano = {"atividades": [
            {"titulo": "Oficina de Robótica", "descricao": "d", "tipo": "Oficina", "turno": "manha"},
        ]}
        resposta = self.client.post(
            reverse("organizador:aplicar_plano_evento", args=[self.evento.id]),
            data=json.dumps({"plano": plano}), content_type="application/json",
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json()["relatorio"]["criadas"], 1)
        atividade = Atividade.objects.get(evento=self.evento, titulo="Oficina de Robótica")
        self.assertFalse(atividade.publicada)

    def test_aplicar_plano_relatorio_traz_ids(self):
        self.client.force_login(self.org)
        plano = {"atividades": [
            {"titulo": "Oficina de Robótica", "descricao": "d", "tipo": "Oficina", "turno": "manha"},
        ]}
        resposta = self.client.post(
            reverse("organizador:aplicar_plano_evento", args=[self.evento.id]),
            data=json.dumps({"plano": plano}), content_type="application/json",
        )
        linhas = resposta.json()["relatorio"]["linhas"]
        self.assertEqual(linhas[0]["status"], "criadas")
        self.assertTrue(linhas[0]["id"])

    def test_remover_plano_apaga_so_rascunho_do_evento(self):
        self.client.force_login(self.org)
        inicio = timezone.make_aware(datetime.combine(self.evento.data_inicio, time.min))
        rascunho = Atividade.objects.create(
            evento=self.evento, titulo="Rascunho X", descricao="d", tipo=self.tipo,
            data_hora_inicio=inicio, data_hora_fim=inicio + timedelta(hours=1),
            publicada=False,
        )
        publicada = Atividade.objects.create(
            evento=self.evento, titulo="Publicada Y", descricao="d", tipo=self.tipo,
            data_hora_inicio=inicio + timedelta(hours=2),
            data_hora_fim=inicio + timedelta(hours=3), publicada=True,
        )
        outro = Evento.objects.create(
            title="Outro", description="d", local="l",
            data_inicio=self.evento.data_inicio, data_fim=self.evento.data_fim,
            organizador=self.org,
        )
        de_outro = Atividade.objects.create(
            evento=outro, titulo="Rascunho Outro", descricao="d", tipo=self.tipo,
            data_hora_inicio=inicio, data_hora_fim=inicio + timedelta(hours=1),
            publicada=False,
        )
        resposta = self.client.post(
            reverse("organizador:remover_plano_evento", args=[self.evento.id]),
            data=json.dumps({"atividade_ids": [rascunho.pk, publicada.pk, de_outro.pk]}),
            content_type="application/json",
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json()["removidas"], 1)  # só o rascunho do evento
        self.assertFalse(Atividade.objects.filter(pk=rascunho.pk).exists())
        self.assertTrue(Atividade.objects.filter(pk=publicada.pk).exists())
        self.assertTrue(Atividade.objects.filter(pk=de_outro.pk).exists())
