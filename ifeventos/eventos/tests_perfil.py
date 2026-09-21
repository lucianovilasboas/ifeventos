"""Salvamento do perfil: erro visível no modal + redirect quando válido."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

U = get_user_model()
SENHA = "SenhaForte123!"


def _usuario(email, cpf, **flags):
    return U.objects.create_user(email=email, password=SENHA, cpf=cpf, **flags)


class PerfilSaveTests(TestCase):
    def setUp(self):
        self.org = _usuario("org_perfil@example.com", "12345678909", is_organizador=True)
        self.part = _usuario("part_perfil@example.com", "11144477735")

    def _dados(self, user, extra=None):
        dados = {
            "first_name": "Ana", "last_name": "Silva",
            "username": user.username, "email": user.email,
            "cpf": user.cpf or "", "telefone": "", "endereco": "",
        }
        dados.update(extra or {})
        return dados

    def test_post_invalido_abre_modal_com_erro(self):
        # Sem o Vínculo (obrigatório) o formulário é inválido: a view re-renderiza
        # (200) e avisa o template para reabrir o modal com o formulário ligado.
        self.client.force_login(self.org)
        resposta = self.client.post(
            reverse("organizador:dashboard"), self._dados(self.org)
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.context.get("perfil_abrir"))
        self.assertIn("meta_vinculo", resposta.context["perfil_form"].errors)

    def test_post_valido_redireciona_e_salva(self):
        self.client.force_login(self.org)
        resposta = self.client.post(
            reverse("organizador:dashboard"),
            self._dados(self.org, {"meta_vinculo": "Comunidade externa"}),
        )
        self.assertEqual(resposta.status_code, 302)
        self.org.refresh_from_db()
        self.assertEqual(self.org.first_name, "Ana")

    def test_participante_invalido_tambem_abre_modal(self):
        self.client.force_login(self.part)
        resposta = self.client.post(
            reverse("participante:dashboard"), self._dados(self.part)
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.context.get("perfil_abrir"))
        self.assertIn("meta_vinculo", resposta.context["perfil_form"].errors)