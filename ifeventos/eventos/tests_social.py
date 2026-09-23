"""Testes do enriquecimento do perfil pelo login social (Google).

A rede é SEMPRE mockada (`requests.get`) — nenhum teste baixa nada de verdade
nem envia e-mail. O `MEDIA_ROOT` vai para um diretório temporário.
"""

import shutil
import tempfile
from io import BytesIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from allauth.socialaccount.signals import social_account_added

from eventos import social

U = get_user_model()
SENHA = "SenhaForte123!"


def _imagem_png(lado=400, cor=(200, 30, 30)):
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (lado, lado), cor).save(buffer, format="PNG")
    return buffer.getvalue()


class _Raw:
    """Imita o `response.raw` do requests (aceita o kwarg decode_content)."""

    def __init__(self, dados):
        self._buffer = BytesIO(dados)

    def read(self, n=-1, decode_content=False):
        return self._buffer.read(n)


class _Resposta:
    def __init__(self, dados=None, status=200, tipo="image/png"):
        self.status_code = status
        self.headers = {"Content-Type": tipo}
        self.raw = _Raw(dados or b"")


def _sociallogin(picture="https://lh3.googleusercontent.com/a/abc=s96-c", **extra):
    dados = {"given_name": "João", "family_name": "Braz", "picture": picture}
    dados.update(extra)
    conta = mock.Mock()
    conta.provider = "google"
    conta.extra_data = dados
    login = mock.Mock()
    login.account = conta
    return login


class EnriquecerTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls._media = tempfile.mkdtemp(prefix="media_social_")
        cls.enterClassContext(override_settings(MEDIA_ROOT=cls._media))
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(cls._media, ignore_errors=True)

    def test_baixa_e_salva_avatar_e_preenche_nome(self):
        user = U.objects.create_user(email="a@example.com", password=SENHA)
        with mock.patch.object(social.requests, "get", return_value=_Resposta(_imagem_png())):
            self.assertTrue(social.enriquecer_do_google(user, _sociallogin()))
        user.refresh_from_db()
        self.assertTrue(user.foto)
        self.assertEqual(user.first_name, "João")
        self.assertEqual(user.last_name, "Braz")

    def test_falha_no_download_guarda_url(self):
        user = U.objects.create_user(email="b@example.com", password=SENHA)
        with mock.patch.object(social.requests, "get", return_value=_Resposta(status=500)):
            social.enriquecer_do_google(user, _sociallogin())
        user.refresh_from_db()
        self.assertFalse(user.foto)
        self.assertIn("=s256-c", user.foto_social_url)

    def test_tipo_invalido_guarda_url(self):
        user = U.objects.create_user(email="c@example.com", password=SENHA)
        with mock.patch.object(
            social.requests, "get",
            return_value=_Resposta(b"nao e imagem", tipo="text/html"),
        ):
            social.enriquecer_do_google(user, _sociallogin())
        user.refresh_from_db()
        self.assertFalse(user.foto)
        self.assertTrue(user.foto_social_url)

    def test_nao_sobrescreve_foto_existente(self):
        user = U.objects.create_user(email="d@example.com", password=SENHA)
        user.foto = SimpleUploadedFile("f.png", _imagem_png(), content_type="image/png")
        user.save()
        caminho = user.foto.name
        with mock.patch.object(social.requests, "get", return_value=_Resposta(_imagem_png())):
            social.enriquecer_do_google(user, _sociallogin())
        user.refresh_from_db()
        self.assertEqual(user.foto.name, caminho)

    def test_nao_sobrescreve_nome_existente(self):
        user = U.objects.create_user(
            email="e@example.com", password=SENHA,
            first_name="Pedro", last_name="Santos",
        )
        with mock.patch.object(social.requests, "get", return_value=_Resposta(_imagem_png())):
            social.enriquecer_do_google(user, _sociallogin())
        user.refresh_from_db()
        self.assertEqual(user.first_name, "Pedro")
        self.assertEqual(user.last_name, "Santos")

    def test_sem_picture_nao_quebra(self):
        user = U.objects.create_user(email="f@example.com", password=SENHA)
        with mock.patch.object(social.requests, "get") as get:
            social.enriquecer_do_google(user, _sociallogin(picture=None))
        get.assert_not_called()  # sem picture, não toca a rede
        user.refresh_from_db()
        self.assertFalse(user.foto)
        self.assertEqual(user.foto_social_url, "")
        self.assertEqual(user.first_name, "João")  # o nome ainda é preenchido


class SignalSocialTests(TestCase):
    def test_social_account_added_dispara_enriquecimento(self):
        user = U.objects.create_user(email="g@example.com", password=SENHA)
        login = _sociallogin()
        login.user = user
        with mock.patch.object(social, "enriquecer_do_google") as chamada:
            social_account_added.send(sender=None, request=None, sociallogin=login)
        chamada.assert_called_once()
