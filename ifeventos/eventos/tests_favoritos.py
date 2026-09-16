"""Testes dos favoritos ("Minha agenda") no perfil do participante."""

from django.db import IntegrityError, transaction
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from eventos.models import Atividade, Evento, Favorito, TipoAtividade

U = get_user_model()


def local(ano, mes, dia, hora):
    from datetime import datetime

    return timezone.make_aware(
        datetime(ano, mes, dia, hora), timezone.get_current_timezone()
    )


class FavoritoTests(TestCase):
    def setUp(self):
        self.evento = Evento.objects.create(
            title="Mostra", description="d", local="Campus",
            data_inicio="2026-10-05", data_fim="2026-10-05",
        )
        self.tipo = TipoAtividade.objects.create(nome="Oficina")
        self.a1 = Atividade.objects.create(
            evento=self.evento, titulo="Oficina 1", descricao="d", tipo=self.tipo,
            data_hora_inicio=local(2026, 10, 5, 8),
            data_hora_fim=local(2026, 10, 5, 9), n_vagas=10,
        )
        self.a2 = Atividade.objects.create(
            evento=self.evento, titulo="Oficina 2", descricao="d", tipo=self.tipo,
            data_hora_inicio=local(2026, 10, 5, 10),
            data_hora_fim=local(2026, 10, 5, 11), n_vagas=10,
        )
        self.user = U.objects.create_user(
            email="aluno@example.com", password="SenhaForte123!", is_participante=True
        )
        self.toggle_url = reverse("eventos:favorito_toggle", args=[self.a1.id])
        self.mesclar_url = reverse("eventos:favoritos_mesclar")
        self.programacao_url = reverse("eventos:programacao", args=[self.evento.id])

    def test_nao_duplica(self):
        Favorito.objects.create(participante=self.user, atividade=self.a1)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Favorito.objects.create(participante=self.user, atividade=self.a1)

    def test_precisa_estar_logado(self):
        resposta = self.client.post(self.toggle_url)
        self.assertEqual(resposta.status_code, 302)
        self.assertIn("/accounts/login", resposta["Location"])

    def test_toggle_cria_e_remove(self):
        self.client.force_login(self.user)

        criado = self.client.post(self.toggle_url).json()
        self.assertTrue(criado["favorito"])
        self.assertEqual(criado["total"], 1)
        self.assertTrue(Favorito.objects.filter(participante=self.user).exists())

        removido = self.client.post(self.toggle_url).json()
        self.assertFalse(removido["favorito"])
        self.assertEqual(removido["total"], 0)
        self.assertFalse(Favorito.objects.filter(participante=self.user).exists())

    def test_get_nao_permitido(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.toggle_url).status_code, 405)

    def test_mesclar_soma_os_locais_e_ignora_invalidos(self):
        self.client.force_login(self.user)
        Favorito.objects.create(participante=self.user, atividade=self.a1)

        resposta = self.client.post(
            self.mesclar_url, {"ids": f"{self.a1.id},{self.a2.id},999999"}
        ).json()

        self.assertEqual(sorted(resposta["ids"]), sorted([self.a1.id, self.a2.id]))
        self.assertEqual(Favorito.objects.filter(participante=self.user).count(), 2)

    def test_pagina_hidrata_os_favoritos_de_quem_esta_logado(self):
        self.client.force_login(self.user)
        Favorito.objects.create(participante=self.user, atividade=self.a1)

        html = self.client.get(self.programacao_url).content.decode()
        self.assertIn("meus-favoritos", html)
        self.assertIn(str(self.a1.id), html)

    def test_pagina_nao_hidrata_para_anonimo(self):
        self.client.logout()
        html = self.client.get(self.programacao_url).content.decode()
        self.assertNotIn("meus-favoritos", html)
