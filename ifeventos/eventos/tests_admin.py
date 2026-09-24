"""Testes dos ModelAdmin: toda busca configurada precisa funcionar.

Um campo de busca que é um FK direto (ex.: `search_fields = ("participante",)`)
estoura `FieldError` no Django — o "Search" do admin daria 500. Este teste
percorre todos os admins registrados e roda a busca, pegando esse caso.
"""

from django.contrib import admin
from django.test import RequestFactory, TestCase


class AdminSearchTests(TestCase):
    def test_toda_busca_registrada_funciona(self):
        request = RequestFactory().get("/admin/")
        for model, model_admin in admin.site._registry.items():
            with self.subTest(model=model.__name__):
                campos = model_admin.get_search_fields(request)
                if not campos:
                    continue
                queryset = model_admin.get_queryset(request)
                resultado, _dup = model_admin.get_search_results(
                    request, queryset, "teste"
                )
                list(resultado)  # avalia: lookup inválido estoura aqui

    def test_evento_e_participante_tem_busca(self):
        from eventos.models import Evento, Participante

        self.assertTrue(admin.site._registry[Evento].get_search_fields(None))
        self.assertTrue(admin.site._registry[Participante].get_search_fields(None))
