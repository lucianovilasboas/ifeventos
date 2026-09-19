"""Testes da configuração de modelos de LLM por contexto (admin)."""

from django.conf import settings
from django.contrib import admin
from django.core.cache import cache
from django.test import TestCase, override_settings

from eventos import ia_config
from eventos.models import ContextoIA

CACHE_LOCMEM = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}


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

    def test_admin_registrado(self):
        self.assertIn(ContextoIA, admin.site._registry)
