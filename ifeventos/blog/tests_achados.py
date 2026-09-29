"""Testes dos achados da revisão do blog (2.13.0).

Estes testes descrevem o comportamento CORRETO esperado. Eles falham na versão
2.13.0 e servem de rede de segurança para as correções seguintes. Cada caso
aponta o achado que confirma (P1/P2/P3 da revisão).
"""

import tempfile
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.exceptions import SuspiciousFileOperation
from django.core.files.uploadedfile import SimpleUploadedFile
from django.conf import settings
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image

from eventos.models import Atividade, Evento, Inscricao, RegistroAuditoria

from .models import FotoPost, PostEvento, storage_blog

U = get_user_model()
SENHA = "SenhaBlog123!"


def _imagem(nome="foto.png", formato="PNG", size=(20, 20), mode="RGB"):
    buffer = BytesIO()
    Image.new(mode, size).save(buffer, format=formato)
    content_type = {
        "PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp",
    }.get(formato, "application/octet-stream")
    return SimpleUploadedFile(nome, buffer.getvalue(), content_type=content_type)


@override_settings(BLOG_PRIVATE_ROOT=Path(tempfile.mkdtemp(prefix="blog_achados_")))
class AchadosBlogTestCase(TestCase):
    def setUp(self):
        self.organizador = U.objects.create_user(
            email="org@blog.test", password=SENHA, is_organizador=True
        )
        self.participante = U.objects.create_user(
            email="part@blog.test", password=SENHA
        )
        hoje = date.today()
        self.evento = Evento.objects.create(
            title="Evento Blog", description="d", local="Auditório",
            data_inicio=hoje, data_fim=hoje, organizador=self.organizador,
        )
        agora = timezone.now()
        self.atividade = Atividade.objects.create(
            evento=self.evento, titulo="Atividade", descricao="d",
            data_hora_inicio=agora, data_hora_fim=agora + timedelta(hours=1),
            n_vagas=10,
        )
        Inscricao.objects.create(
            participante=self.participante, atividade=self.atividade
        )

    def _criar_post(self, autor, situacao, **extra):
        dados = dict(
            evento=self.evento, autor=autor, titulo="História", corpo="Corpo",
            situacao=situacao,
        )
        dados.update(extra)
        return PostEvento.objects.create(**dados)

    # ------------------------------------------------------------------ P1
    def test_moderador_ve_pendentes_do_evento_no_indice(self):
        """P1: o organizador precisa encontrar posts pendentes de OUTRAS pessoas.

        Falha em 2.13.0: o índice só mostra os posts não publicados do próprio
        usuário logado.
        """
        self._criar_post(self.participante, PostEvento.SIT_PENDENTE,
                         titulo="Pendente da Maria")
        self.client.force_login(self.organizador)
        resp = self.client.get(f"/blog/evento/{self.evento.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Pendente da Maria")

    # ------------------------------------------------------------------ P1
    def test_extensao_do_upload_nao_define_o_content_type(self):
        """P1: imagem válida com extensão .html não pode ser servida como HTML.

        Falha em 2.13.0: o caminho preserva a extensão enviada e o serving
        deriva o Content-Type dela.
        """
        post = self._criar_post(
            self.organizador, PostEvento.SIT_PUBLICADO,
            publicado_em=timezone.now(), capa=_imagem("evil.pdf", "PNG"),
        )
        resp = self.client.get(post.capa.url)
        self.assertEqual(resp.status_code, 200)
        self.assertNotEqual(resp["Content-Type"], "application/pdf")
        self.assertEqual(resp.headers.get("X-Content-Type-Options"), "nosniff")

    def test_content_type_de_extensao_inexistente_e_seguro(self):
        """P1: upload sem extensão conhecida também não vira text/html."""
        post = self._criar_post(
            self.organizador, PostEvento.SIT_PUBLICADO,
            publicado_em=timezone.now(), capa=_imagem("sem_extensao", "PNG"),
        )
        resp = self.client.get(post.capa.url)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("html", resp["Content-Type"].lower())

    def test_form_normaliza_extensao_de_capa_pelo_conteudo(self):
        """Upload web recebe extensão canônica mesmo que o nome minta."""
        self.client.force_login(self.participante)
        resp = self.client.post(
            f"/blog/evento/{self.evento.id}/novo/",
            {
                "titulo": "Imagem com nome falso", "corpo": "c", "acao": "enviar",
                "capa": _imagem("capa.pdf", "PNG"),
            },
        )
        form_errors = resp.context["form"].errors if resp.context else "sem contexto de formulário"
        self.assertEqual(resp.status_code, 302, form_errors)
        post = PostEvento.objects.get(autor=self.participante)
        self.assertTrue(post.capa.name.endswith(".png"))
        imagem_resp = self.client.get(post.capa.url)
        self.assertEqual(imagem_resp["Content-Type"], "image/png")
        self.assertEqual(imagem_resp.headers.get("X-Content-Type-Options"), "nosniff")

    def test_edicao_sem_nova_capa_preserva_caminho_e_arquivo(self):
        """Editar texto sem upload não pode renomear nem apagar a capa existente."""
        post = self._criar_post(
            self.organizador, PostEvento.SIT_RASCUNHO, capa=_imagem("original.png")
        )
        caminho = post.capa.name
        self.client.force_login(self.organizador)
        resp = self.client.post(
            f"/blog/post/{post.id}/editar/",
            {"titulo": post.titulo, "corpo": post.corpo},
        )
        self.assertEqual(resp.status_code, 302)
        post.refresh_from_db()
        self.assertEqual(post.capa.name, caminho)
        self.assertTrue(storage_blog().exists(caminho))

    def test_storage_privado_nao_pode_ficar_dentro_de_media_root(self):
        """P3: uma configuração equivocada não deve tornar os uploads públicos."""
        with override_settings(
            BLOG_PRIVATE_ROOT=Path(settings.MEDIA_ROOT) / "blog_privado"
        ):
            with self.assertRaises(SuspiciousFileOperation):
                _ = storage_blog().location

    # ------------------------------------------------------------------ P2
    def test_imagem_publicada_nao_tem_cache_publico(self):
        """P2: conteúdo que pode ser despublicado não pode ser cacheado em público.

        Falha em 2.13.0: a resposta traz `Cache-Control: public, max-age=3600`.
        """
        post = self._criar_post(
            self.organizador, PostEvento.SIT_PUBLICADO,
            publicado_em=timezone.now(), capa=_imagem(),
        )
        resp = self.client.get(post.capa.url)
        self.assertNotIn("public", resp["Cache-Control"].lower())

    # ------------------------------------------------------------------ P2
    def test_substituir_a_capa_apaga_o_arquivo_antigo(self):
        """P2: trocar a capa não pode deixar arquivo órfão no storage.

        Falha em 2.13.0: só excluir o post/foto dispara a limpeza (signals).
        """
        post = self._criar_post(
            self.organizador, PostEvento.SIT_RASCUNHO, capa=_imagem("v1.png"),
        )
        antiga = post.capa.name
        self.assertTrue(storage_blog().exists(antiga))

        self.client.force_login(self.organizador)
        resp = self.client.post(
            f"/blog/post/{post.id}/editar/",
            {"titulo": "História", "corpo": "Corpo", "capa": _imagem("v2.png")},
        )
        self.assertEqual(resp.status_code, 302)
        post.refresh_from_db()
        self.assertNotEqual(post.capa.name, antiga)
        self.assertFalse(storage_blog().exists(antiga))

    def test_remover_a_capa_apaga_o_arquivo_antigo(self):
        """Desmarcar/remover a capa também deve liberar o arquivo do storage."""
        post = self._criar_post(
            self.organizador, PostEvento.SIT_RASCUNHO, capa=_imagem("remover.png")
        )
        antiga = post.capa.name
        self.client.force_login(self.organizador)
        resp = self.client.post(
            f"/blog/post/{post.id}/editar/",
            {"titulo": post.titulo, "corpo": post.corpo, "capa-clear": "on"},
        )
        self.assertEqual(resp.status_code, 302)
        post.refresh_from_db()
        self.assertFalse(post.capa)
        self.assertFalse(storage_blog().exists(antiga))

    # ------------------------------------------------------------------ P2
    def test_imagem_com_pixels_demais_e_rejeitada(self):
        """P2: limite de dimensão/pixels contra imagens desproporcionais.

        Falha em 2.13.0: só há limite de tamanho em bytes.
        """
        self.client.force_login(self.participante)
        # 8000x8000 = 64 MP (bem acima do limite pretendido).
        gigante = _imagem("gigante.png", "PNG", size=(8000, 8000), mode="1")
        resp = self.client.post(
            f"/blog/evento/{self.evento.id}/novo/",
            {"titulo": "Grande", "corpo": "c", "acao": "enviar", "fotos": gigante},
        )
        self.assertEqual(resp.status_code, 200)  # re-renderiza com erro
        self.assertFalse(PostEvento.objects.filter(autor=self.participante).exists())

    # ------------------------------------------------------------------ P2
    def test_acao_do_admin_registra_auditoria(self):
        """P2: aprovar pelo Admin também deve entrar na trilha de auditoria.

        Falha em 2.13.0: a action usa QuerySet.update() sem registrar.
        """
        superuser = U.objects.create_superuser(
            email="admin@blog.test", password=SENHA
        )
        post = self._criar_post(self.participante, PostEvento.SIT_PENDENTE)
        self.client.force_login(superuser)
        self.client.post(
            "/admin/blog/postevento/",
            {
                "action": "aprovar",
                "select_across": "0",
                "index": "0",
                "_selected_action": [str(post.id)],
            },
            follow=True,
        )
        post.refresh_from_db()
        self.assertEqual(post.situacao, PostEvento.SIT_PUBLICADO)
        self.assertTrue(
            RegistroAuditoria.objects.filter(
                entidade="PostEvento", objeto_id=str(post.id)
            ).exists()
        )
