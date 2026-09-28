"""Testes do blog do evento.

Cobre autorização (quem publica/edita/modera), os estados de publicação, a
privacidade das imagens e a validação de upload.
"""

import tempfile
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image

from eventos.models import Atividade, Evento, Inscricao, Presenca

from .models import FotoPost, PostEvento

U = get_user_model()
SENHA = "SenhaBlog123!"


def _arquivo_imagem(nome="foto.png"):
    buffer = BytesIO()
    Image.new("RGB", (20, 20), "green").save(buffer, format="PNG")
    return SimpleUploadedFile(nome, buffer.getvalue(), content_type="image/png")


@override_settings(BLOG_PRIVATE_ROOT=Path(tempfile.mkdtemp(prefix="blog_teste_")))
class BlogTestCase(TestCase):
    def setUp(self):
        self.organizador = U.objects.create_user(
            email="org@blog.test", password=SENHA, is_organizador=True
        )
        self.participante = U.objects.create_user(
            email="part@blog.test", password=SENHA
        )
        self.outro = U.objects.create_user(email="outro@blog.test", password=SENHA)
        self.forasteiro = U.objects.create_user(
            email="fora@blog.test", password=SENHA
        )

        hoje = date.today()
        self.evento = Evento.objects.create(
            title="Evento Blog",
            description="Descrição",
            local="Auditório",
            data_inicio=hoje,
            data_fim=hoje,
            organizador=self.organizador,
        )
        agora = timezone.now()
        self.atividade = Atividade.objects.create(
            evento=self.evento,
            titulo="Atividade",
            descricao="d",
            data_hora_inicio=agora,
            data_hora_fim=agora + timedelta(hours=1),
            n_vagas=10,
        )
        # Participante com inscrição; outro com presença; forasteiro sem vínculo.
        Inscricao.objects.create(
            participante=self.participante, atividade=self.atividade
        )
        Presenca.objects.create(
            participante=self.outro, atividade=self.atividade, papel="participante"
        )

    # ---------------- helpers ----------------
    def _url_indice(self):
        return f"/blog/evento/{self.evento.id}/"

    def _criar_post(self, autor, situacao=PostEvento.SIT_PENDENTE, **extra):
        dados = dict(
            evento=self.evento, autor=autor,
            autor_nome=autor.get_full_name() or autor.username,
            titulo="História", corpo="Era uma vez...", situacao=situacao,
        )
        dados.update(extra)
        return PostEvento.objects.create(**dados)

    def _post_criar(self, dados=None, arquivos=None):
        dados = dados if dados is not None else {}
        arquivos = arquivos if arquivos is not None else {}
        return self.client.post(f"{self._url_indice()}novo/", {**dados, **arquivos})

    def _post_editar(self, post, dados):
        return self.client.post(f"/blog/post/{post.id}/editar/", dados)

    # ---------------- leitura pública ----------------
    def test_indice_publico(self):
        resp = self.client.get(self._url_indice())
        self.assertEqual(resp.status_code, 200)

    def test_post_publicado_visivel_a_anonimo(self):
        post = self._criar_post(
            self.organizador, situacao=PostEvento.SIT_PUBLICADO,
            publicado_em=timezone.now(),
        )
        resp = self.client.get(f"/blog/post/{post.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "História")

    def test_post_pendente_invisivel_a_anonimo(self):
        post = self._criar_post(self.participante)
        resp = self.client.get(f"/blog/post/{post.id}/")
        self.assertEqual(resp.status_code, 404)

    def test_autor_ve_o_proprio_pendente(self):
        post = self._criar_post(self.participante)
        self.client.force_login(self.participante)
        resp = self.client.get(f"/blog/post/{post.id}/")
        self.assertEqual(resp.status_code, 200)

    # ---------------- criação e permissão ----------------
    def test_sem_vinculo_nao_publica(self):
        self.client.force_login(self.forasteiro)
        resp = self._post_criar({"titulo": "T", "corpo": "C"})
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(PostEvento.objects.filter(autor=self.forasteiro).exists())

    def test_inscrito_cria_como_pendente(self):
        self.client.force_login(self.participante)
        resp = self._post_criar({"titulo": "Minha", "corpo": "C", "acao": "enviar"})
        self.assertEqual(resp.status_code, 302)
        post = PostEvento.objects.get(autor=self.participante)
        self.assertEqual(post.situacao, PostEvento.SIT_PENDENTE)

    def test_presenca_permite_publicar(self):
        self.client.force_login(self.outro)
        resp = self._post_criar({"titulo": "De presença", "corpo": "C"})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(PostEvento.objects.filter(autor=self.outro).exists())

    def test_organizador_publica_direto(self):
        self.client.force_login(self.organizador)
        resp = self._post_criar(
            {"titulo": "Oficial", "corpo": "C", "acao": "publicar"}
        )
        self.assertEqual(resp.status_code, 302)
        post = PostEvento.objects.get(autor=self.organizador)
        self.assertEqual(post.situacao, PostEvento.SIT_PUBLICADO)
        self.assertIsNotNone(post.publicado_em)

    def test_organizador_salva_rascunho(self):
        self.client.force_login(self.organizador)
        self._post_criar({"titulo": "Rascunho", "corpo": "C", "acao": "rascunho"})
        post = PostEvento.objects.get(autor=self.organizador)
        self.assertEqual(post.situacao, PostEvento.SIT_RASCUNHO)

    # ---------------- edição ----------------
    def test_edicao_de_publicado_por_participante_volta_a_pendente(self):
        post = self._criar_post(
            self.participante, situacao=PostEvento.SIT_PUBLICADO,
            publicado_em=timezone.now(),
        )
        self.client.force_login(self.participante)
        resp = self._post_editar(post, {"titulo": "Editado", "corpo": "Novo"})
        self.assertEqual(resp.status_code, 302)
        post.refresh_from_db()
        self.assertEqual(post.situacao, PostEvento.SIT_PENDENTE)
        self.assertEqual(post.titulo, "Editado")

    def test_outro_usuario_nao_edita(self):
        post = self._criar_post(self.participante)
        self.client.force_login(self.outro)
        resp = self._post_editar(post, {"titulo": "X", "corpo": "Y"})
        self.assertEqual(resp.status_code, 403)

    # ---------------- moderação ----------------
    def test_organizador_aprova_pendente(self):
        post = self._criar_post(self.participante)
        self.client.force_login(self.organizador)
        resp = self.client.post(f"/blog/post/{post.id}/moderar/", {"acao": "aprovar"})
        self.assertEqual(resp.status_code, 302)
        post.refresh_from_db()
        self.assertEqual(post.situacao, PostEvento.SIT_PUBLICADO)

    def test_participante_nao_modera(self):
        post = self._criar_post(self.participante)
        self.client.force_login(self.participante)
        resp = self.client.post(f"/blog/post/{post.id}/moderar/", {"acao": "aprovar"})
        self.assertEqual(resp.status_code, 403)

    # ---------------- imagens privadas ----------------
    def test_capa_de_pendente_nao_vaza_para_anonimo(self):
        post = self._criar_post(self.participante, capa=_arquivo_imagem())
        url = post.capa.url
        self.assertTrue(url.startswith("/blog/privado/"))
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_capa_de_pendente_liberada_ao_autor(self):
        post = self._criar_post(self.participante, capa=_arquivo_imagem())
        self.client.force_login(self.participante)
        self.assertEqual(self.client.get(post.capa.url).status_code, 200)

    def test_foto_de_pendente_nao_vaza_para_anonimo(self):
        post = self._criar_post(self.participante)
        foto = FotoPost.objects.create(post=post, imagem=_arquivo_imagem())
        self.assertEqual(self.client.get(foto.imagem.url).status_code, 404)

    def test_capa_de_publicado_acessivel_a_anonimo(self):
        post = self._criar_post(
            self.organizador, situacao=PostEvento.SIT_PUBLICADO,
            publicado_em=timezone.now(), capa=_arquivo_imagem(),
        )
        self.assertEqual(self.client.get(post.capa.url).status_code, 200)

    # ---------------- upload inválido ----------------
    def test_upload_invalido_nao_cria_post(self):
        self.client.force_login(self.participante)
        ruim = SimpleUploadedFile("x.txt", b"isto nao e imagem", content_type="text/plain")
        resp = self._post_criar(
            {"titulo": "Com arquivo ruim", "corpo": "C"}, {"fotos": ruim}
        )
        self.assertEqual(resp.status_code, 200)  # re-renderiza com erro
        self.assertFalse(
            PostEvento.objects.filter(autor=self.participante).exists()
        )
