"""Blog do evento — histórias e fotos publicadas por organizadores e participantes.

O blog é o par de cada evento: não existe uma tabela "Blog" — o blog É o conjunto
de posts de um `eventos.Evento`. Por isso o app é separado: cria apenas tabelas
novas e referencia o evento/o usuário sem tocar no schema existente.

Privacidade das imagens: como `/media/` é servido publicamente, as imagens do
blog NÃO ficam lá. São gravadas em `blog_privado/` (fora do MEDIA_ROOT) e
liberadas por uma view que confere a visibilidade do post (`blog.views.
arquivo_privado`). Assim um post pendente/oculto não vaza a foto pela URL.
"""

import os
import uuid
from pathlib import Path

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.db import models
from django.utils import timezone
from PIL import Image, UnidentifiedImageError

from eventos.crachas import pode_gerenciar_evento
from eventos.tempo import local_legivel


def storage_blog():
    """Storage das imagens do blog, fora do MEDIA_ROOT (privado por padrão).

    Função (e não instância) para o Django serializar a referência na migração
    sem gravar um caminho absoluto da máquina onde a migração foi gerada.
    """
    return BlogStorage()


class BlogStorage(FileSystemStorage):
    """Storage privado do blog.

    Resolve a `location` a cada acesso (em vez de congelá-la no import) para que
    o destino acompanhe `settings.BASE_DIR` — é o que permite redirecionar os
    arquivos em teste via `override_settings`.
    """

    @property
    def base_location(self):
        return Path(settings.BLOG_PRIVATE_ROOT)

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    @property
    def base_url(self):
        return "/blog/privado/"


def capa_upload(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    return f"capas/{uuid.uuid4().hex}{ext}"


def foto_upload(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    return f"fotos/{uuid.uuid4().hex}{ext}"


MAX_LADO_CAPA = (1280, 960)
MAX_LADO_FOTO = (1600, 1600)


def redimensionar_imagem(campo, maximo):
    """Reduz a imagem gravada para caber em `maximo`, preservando a proporção.

    Mesmo padrão de Evento/Atividade (Pillow no save), mas sem deixar um arquivo
    corrompido derrubar o salvamento: qualquer falha é ignorada.
    """
    if not campo:
        return
    try:
        caminho = campo.path
    except (NotImplementedError, ValueError):
        return
    try:
        with Image.open(caminho) as imagem:
            imagem.load()
            if imagem.mode in ("RGBA", "P", "LA"):
                imagem = imagem.convert("RGB")
            imagem.thumbnail(maximo)
            imagem.save(caminho, optimize=True, quality=85)
    except (UnidentifiedImageError, OSError, ValueError):
        return


class PostEvento(models.Model):
    """Uma história publicada no blog de um evento."""

    SIT_RASCUNHO = "rascunho"
    SIT_PENDENTE = "pendente"
    SIT_PUBLICADO = "publicado"
    SIT_OCULTO = "oculto"
    SITUACAO_CHOICES = [
        (SIT_RASCUNHO, "Rascunho"),
        (SIT_PENDENTE, "Aguardando aprovação"),
        (SIT_PUBLICADO, "Publicado"),
        (SIT_OCULTO, "Oculto"),
    ]

    evento = models.ForeignKey(
        "eventos.Evento", on_delete=models.CASCADE, related_name="posts_blog"
    )
    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="posts_blog",
    )
    # Snapshot do nome: o post continua legível se a conta for excluída.
    autor_nome = models.CharField(max_length=255, blank=True, default="")

    titulo = models.CharField(max_length=255)
    resumo = models.CharField(max_length=300, blank=True, default="")
    corpo = models.TextField()
    capa = models.ImageField(
        upload_to=capa_upload, storage=storage_blog, blank=True, null=True
    )

    situacao = models.CharField(
        max_length=12, choices=SITUACAO_CHOICES, default=SIT_PENDENTE, db_index=True
    )
    fixado = models.BooleanField(default=False)

    publicado_em = models.DateTimeField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-fixado", "-publicado_em", "-criado_em"]
        verbose_name = "Post do blog"
        verbose_name_plural = "Posts do blog"
        indexes = [
            models.Index(
                fields=["evento", "situacao", "-publicado_em"],
                name="blog_evento_situacao_idx",
            ),
        ]

    def __str__(self):
        return self.titulo

    @property
    def publicado(self):
        return self.situacao == self.SIT_PUBLICADO

    def visivel_para(self, usuario):
        """Pode ver o post? Publicado é público; o resto só autor e moderadores."""
        if self.publicado:
            return True
        if not usuario or not getattr(usuario, "is_authenticated", False):
            return False
        if self.autor_id == usuario.id:
            return True
        return pode_gerenciar_evento(usuario, self.evento)

    def save(self, *args, **kwargs):
        # Marca a publicação na primeira vez que o post fica publicado.
        if self.publicado and not self.publicado_em:
            self.publicado_em = timezone.now()
        if not self.autor_nome and self.autor_id:
            nome = self.autor.get_full_name() or self.autor.username
            self.autor_nome = nome
        # `_committed` só é False quando um upload novo foi atribuído: assim a
        # imagem não é recomprimida a cada edição do texto.
        nova_capa = bool(self.capa) and not getattr(self.capa, "_committed", True)
        super().save(*args, **kwargs)
        if nova_capa:
            redimensionar_imagem(self.capa, MAX_LADO_CAPA)

    def quando_publicado(self):
        return local_legivel(self.publicado_em or self.criado_em, "%d/%m/%Y")


class FotoPost(models.Model):
    """Foto anexada a um post (com legenda opcional)."""

    post = models.ForeignKey(
        PostEvento, on_delete=models.CASCADE, related_name="fotos"
    )
    imagem = models.ImageField(upload_to=foto_upload, storage=storage_blog)
    legenda = models.CharField(max_length=255, blank=True, default="")
    ordem = models.PositiveSmallIntegerField(default=0)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["ordem", "id"]
        verbose_name = "Foto do post"
        verbose_name_plural = "Fotos do post"

    def __str__(self):
        return self.legenda or f"Foto #{self.pk}"

    def save(self, *args, **kwargs):
        nova = not getattr(self.imagem, "_committed", True)
        super().save(*args, **kwargs)
        if nova:
            redimensionar_imagem(self.imagem, MAX_LADO_FOTO)
