"""Equipe de apoio: a flag global `is_equipe` acompanha o vínculo por evento.

A flag é global (menu/painel de apoio), mas a equipe é por evento. Ao remover
alguém de um evento, a flag só é zerada se a pessoa não estiver na equipe de
nenhum outro.
"""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from eventos.models import Evento

U = get_user_model()
SENHA = "SenhaForte123!"


class EquipeFlagTests(TestCase):
    def setUp(self):
        self.org = U.objects.create_user(
            email="org_eq@example.com", password=SENHA, cpf="12345678909",
            is_organizador=True,
        )
        self.pessoa = U.objects.create_user(
            email="apoio_eq@example.com", password=SENHA, cpf="11144477735"
        )
        self.evento = Evento.objects.create(
            title="E1", description="d", local="l",
            data_inicio=date(2026, 10, 1), data_fim=date(2026, 10, 2),
            organizador=self.org,
        )
        self.evento2 = Evento.objects.create(
            title="E2", description="d", local="l",
            data_inicio=date(2026, 10, 1), data_fim=date(2026, 10, 2),
            organizador=self.org,
        )

    def test_adicionar_e_remover_pela_tela_sincroniza_a_flag(self):
        self.client.force_login(self.org)

        self.client.post(
            reverse("organizador:equipe_apoio_adicionar", args=[self.evento.id]),
            {"email": self.pessoa.email},
        )
        self.pessoa.refresh_from_db()
        self.assertTrue(self.pessoa.is_equipe)
        self.assertTrue(self.evento.equipe.filter(pk=self.pessoa.pk).exists())

        self.client.post(
            reverse("organizador:equipe_apoio_remover", args=[self.evento.id]),
            {"pessoa_id": self.pessoa.pk},
        )
        self.pessoa.refresh_from_db()
        self.assertFalse(self.pessoa.is_equipe)

    def test_remover_de_um_evento_mantem_a_flag_se_ainda_na_equipe_de_outro(self):
        self.evento.equipe.add(self.pessoa)
        self.evento2.equipe.add(self.pessoa)
        self.pessoa.refresh_from_db()
        self.assertTrue(self.pessoa.is_equipe)

        self.evento.equipe.remove(self.pessoa)  # sinal m2m_changed
        self.pessoa.refresh_from_db()
        self.assertTrue(self.pessoa.is_equipe, "ainda é equipe do evento 2")

        self.evento2.equipe.remove(self.pessoa)
        self.pessoa.refresh_from_db()
        self.assertFalse(self.pessoa.is_equipe)

    def test_add_direto_no_m2m_liga_a_flag(self):
        self.evento.equipe.add(self.pessoa)  # sem passar pela view
        self.pessoa.refresh_from_db()
        self.assertTrue(self.pessoa.is_equipe)

    def test_clear_zera_a_flag(self):
        self.evento.equipe.add(self.pessoa)
        self.pessoa.refresh_from_db()
        self.assertTrue(self.pessoa.is_equipe)

        self.evento.equipe.clear()
        self.pessoa.refresh_from_db()
        self.assertFalse(self.pessoa.is_equipe)
