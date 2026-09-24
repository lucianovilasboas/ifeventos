"""Testes da configuração de modelos de LLM por contexto (admin)."""

from unittest import mock
from unittest.mock import AsyncMock

import openai
from django.conf import settings
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from asgiref.sync import async_to_sync

from eventos import ia_config, services
from eventos.models import ContextoIA

CACHE_LOCMEM = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
U = get_user_model()


def _bad_request(mensagem):
    return openai.BadRequestError(mensagem, response=mock.MagicMock(), body=None)


def _resposta_fake(conteudo="{}"):
    resposta = mock.MagicMock()
    resposta.choices = [mock.MagicMock()]
    resposta.choices[0].message.content = conteudo
    resposta.usage = None
    return resposta


@override_settings(CACHES=CACHE_LOCMEM)
class IAConfigTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_contextos_semeados(self):
        self.assertTrue(ContextoIA.objects.filter(chave="triagem_propostas").exists())
        self.assertEqual(ContextoIA.objects.count(), len(ia_config.CONTEXTOS))

    def test_fallback_quando_sem_linha(self):
        ContextoIA.objects.filter(chave="mensagem_usuario").delete()
        cfg = ia_config.config("mensagem_usuario")
        self.assertEqual(cfg["origem"], "padrao")
        self.assertEqual(cfg["modelo"], settings.IA_MODELO_TEXTO)

    def test_override_pelo_admin(self):
        linha = ContextoIA.objects.get(chave="triagem_propostas")
        linha.modelo = "gpt-5.6-luna"
        linha.save()

        cfg = ia_config.config("triagem_propostas")
        self.assertEqual(cfg["modelo"], "gpt-5.6-luna")
        self.assertEqual(cfg["origem"], "admin")

    def test_modelo_vazio_usa_padrao(self):
        linha = ContextoIA.objects.get(chave="triagem_propostas")
        linha.modelo = ""
        linha.save()
        self.assertEqual(ia_config.config("triagem_propostas")["origem"], "padrao")

    def test_contexto_inativo(self):
        linha = ContextoIA.objects.get(chave="triagem_propostas")
        linha.ativo = False
        linha.save()
        self.assertFalse(ia_config.config("triagem_propostas")["ativo"])

    def test_cache_invalidado_ao_salvar(self):
        self.assertEqual(ia_config.modelo("concierge"), settings.IA_MODELO_CLASSIFICACAO)

        linha = ContextoIA.objects.get(chave="concierge")
        linha.modelo = "modelo-novo"
        linha.save()

        self.assertEqual(ia_config.modelo("concierge"), "modelo-novo")

    def test_chamada_kwargs_aplica_ajustes_do_admin(self):
        linha = ContextoIA.objects.get(chave="triagem_propostas")
        linha.modelo = "m1"
        linha.temperatura = 0.9
        linha.max_tokens = 123
        linha.save()

        kwargs = ia_config.chamada_kwargs("triagem_propostas")
        self.assertEqual(kwargs, {"model": "m1", "max_tokens": 123, "temperature": 0.9})

    def test_chamada_kwargs_usa_defaults_do_codigo(self):
        kwargs = ia_config.chamada_kwargs("triagem_propostas", max_tokens=2000, temperature=0)
        self.assertEqual(kwargs["max_tokens"], 2000)
        self.assertEqual(kwargs["temperature"], 0)

    def test_contexto_inativo_levanta_excecao(self):
        linha = ContextoIA.objects.get(chave="triagem_propostas")
        linha.ativo = False
        linha.save()
        with self.assertRaises(ia_config.ContextoIAInativo):
            ia_config.chamada_kwargs("triagem_propostas")

    def test_sincronizar_idempotente(self):
        resultado = ia_config.sincronizar()
        self.assertEqual(resultado["criados"], 0)
        self.assertEqual(resultado["total"], len(ia_config.CONTEXTOS))

    def test_sincronizar_recria_contexto_ausente(self):
        # Simula um banco que já passou das migrations: um contexto novo do
        # código ainda não tem linha. O sync (que o entrypoint roda) recria.
        ContextoIA.objects.filter(chave="auditoria").delete()
        resultado = ia_config.sincronizar()
        self.assertGreaterEqual(resultado["criados"], 1)
        self.assertTrue(ContextoIA.objects.filter(chave="auditoria").exists())

    def test_admin_registrado(self):
        self.assertIn(ContextoIA, admin.site._registry)


class ParametrosPorModeloTests(TestCase):
    def test_perfil_modelo(self):
        self.assertEqual(ia_config.perfil_modelo("gpt-4o-mini")["token_param"], "max_tokens")
        self.assertTrue(ia_config.perfil_modelo("gpt-4o")["aceita_temperature"])
        self.assertEqual(
            ia_config.perfil_modelo("gpt-5.6-luna")["token_param"], "max_completion_tokens"
        )
        self.assertFalse(ia_config.perfil_modelo("gpt-5.6-luna")["aceita_temperature"])
        self.assertEqual(ia_config.perfil_modelo("o3-mini")["token_param"], "max_completion_tokens")

    def test_parametros_ajustados(self):
        parametros = {"model": "m", "max_tokens": 10, "temperature": 0}

        trocado = services._parametros_ajustados(
            parametros, "Unsupported parameter: 'max_tokens'. Use 'max_completion_tokens'."
        )
        self.assertIn("max_completion_tokens", trocado)
        self.assertNotIn("max_tokens", trocado)

        sem_temp = services._parametros_ajustados(
            parametros, "Unsupported value: 'temperature' does not support 0."
        )
        self.assertNotIn("temperature", sem_temp)

        # Sem nada a ajustar, devolve o MESMO objeto (o chamador decide não retentar).
        self.assertIs(services._parametros_ajustados(parametros, "outro erro"), parametros)


class GerarChatRetryTests(TestCase):
    @override_settings(CACHES=CACHE_LOCMEM)
    def test_retry_troca_max_tokens(self):
        cache.clear()
        linha = ContextoIA.objects.get(chave="triagem_propostas")
        linha.modelo = "gpt-6-desconhecido"  # perfil não reconhece → usa max_tokens
        linha.save()

        resposta = _resposta_fake()
        erro = _bad_request(
            "Unsupported parameter: 'max_tokens' is not supported with this model. "
            "Use 'max_completion_tokens' instead."
        )
        cliente = mock.MagicMock()
        cliente.chat = mock.MagicMock()
        cliente.chat.completions.create = AsyncMock(side_effect=[erro, resposta])

        with mock.patch.object(services, "get_openai_client", return_value=cliente):
            resultado = async_to_sync(services.gerar_chat)(
                "triagem_propostas",
                messages=[{"role": "user", "content": "x"}],
                max_tokens=100,
                temperature=0,
            )

        self.assertIs(resultado, resposta)
        chamadas = cliente.chat.completions.create.await_args_list
        self.assertEqual(len(chamadas), 2)
        self.assertIn("max_completion_tokens", chamadas[1].kwargs)
        self.assertNotIn("max_tokens", chamadas[1].kwargs)


class ModelosOpenAITests(TestCase):
    @override_settings(CACHES=CACHE_LOCMEM, OPENAI_API_KEY="sk-teste", IA_ATIVA=True)
    def test_lista_filtra_nao_chat_e_cacheia(self):
        cache.clear()
        itens = [
            mock.MagicMock(id="gpt-4o", created=1, owned_by="openai"),
            mock.MagicMock(id="text-embedding-3-small", created=1, owned_by="openai"),
            mock.MagicMock(id="whisper-1", created=1, owned_by="openai"),
        ]
        cliente = mock.MagicMock()
        cliente.models.list.return_value = mock.MagicMock(data=itens)

        with mock.patch("openai.OpenAI", return_value=cliente) as construtor:
            primeira = ia_config.modelos_openai()
            segunda = ia_config.modelos_openai()

        self.assertEqual([m["id"] for m in primeira], ["gpt-4o"])
        self.assertEqual(primeira, segunda)
        self.assertEqual(construtor.call_count, 1)  # a 2ª veio do cache

    @override_settings(CACHES=CACHE_LOCMEM, OPENAI_API_KEY="", IA_ATIVA=True)
    def test_sem_chave_devolve_vazio(self):
        cache.clear()
        self.assertEqual(ia_config.modelos_openai(), [])

    def test_endpoint_admin(self):
        funcionario = U.objects.create_user(
            email="adm@example.com", password="Senha12345", cpf="11144477735",
            is_staff=True,
        )
        self.client.force_login(funcionario)
        with mock.patch.object(ia_config, "modelos_openai", return_value=[{"id": "gpt-4o"}]):
            resposta = self.client.get(reverse("admin:eventos_contextoia_modelos"))

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json()["modelos"], [{"id": "gpt-4o"}])

    def test_endpoint_admin_exige_staff(self):
        comum = U.objects.create_user(
            email="comum@example.com", password="Senha12345", cpf="39053344705",
        )
        self.client.force_login(comum)
        resposta = self.client.get(reverse("admin:eventos_contextoia_modelos"))
        self.assertNotEqual(resposta.status_code, 200)
