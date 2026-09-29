"""Formulários do blog.

O texto é simples (o template escapa e aplica `linebreaks`), então não há campo
de HTML: evita conteúdo executável sem precisar sanitizar.

Uploads: a validação abre o arquivo com o Pillow (conteúdo manda, não a
extensão/MIME), limita tamanho e dimensões e **renomeia para a extensão canônica
do formato real** — assim o nome gravado nunca dita um tipo de conteúdo perigoso.
"""

import os
import warnings

from django import forms
from PIL import Image, UnidentifiedImageError

from .models import PostEvento

TAMANHO_MAX_IMAGEM = 8 * 1024 * 1024  # 8 MB por arquivo
# Limite de pixels: barra imagens com dimensões desproporcionais ("bomba" de
# descompressão) antes de decodificá-las por completo.
MAX_PIXELS = 40_000_000
MAX_FOTOS_POR_POST = 12

# Formatos aceitos → extensão canônica (jpeg unifica jpg) e MIME usado no serving.
FORMATOS_EXT = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}
FORMATOS_MIME = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}


class PostForm(forms.ModelForm):
    class Meta:
        model = PostEvento
        fields = ["titulo", "resumo", "corpo", "capa"]
        widgets = {
            "titulo": forms.TextInput(
                attrs={"class": "form-control", "maxlength": 255,
                       "placeholder": "Ex.: Como foi o primeiro dia"}
            ),
            "resumo": forms.TextInput(
                attrs={"class": "form-control", "maxlength": 300,
                       "placeholder": "Uma frase de chamada (opcional)"}
            ),
            "corpo": forms.Textarea(
                attrs={"class": "form-control", "rows": 10,
                       "placeholder": "Conte a história do evento..."}
            ),
            "capa": forms.ClearableFileInput(
                attrs={"class": "form-control", "accept": "image/*"}
            ),
        }

    def clean_capa(self):
        capa = self.cleaned_data.get("capa")
        if not capa:
            return capa
        # Em uma edição sem novo upload, `capa` é o FieldFile já persistido.
        # Não normalize seu nome: ele inclui o caminho relativo do storage.
        if getattr(capa, "_committed", False):
            return capa
        erro = validar_imagem(capa)
        if erro:
            raise forms.ValidationError("A capa " + erro)
        return capa


def validar_imagem(arquivo):
    """Valida e normaliza o upload. Devolve uma mensagem de erro, ou None.

    Em caso de sucesso, reescreve `arquivo.name` com a extensão do formato real
    detectado pelo Pillow. O conteúdo é verificado de fato (a extensão e o MIME
    enviados não são confiáveis).
    """
    if arquivo.size > TAMANHO_MAX_IMAGEM:
        return "deve ter no máximo 8 MB"
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(arquivo) as imagem:
                formato = (imagem.format or "").upper()
                largura, altura = imagem.size
                if largura * altura > MAX_PIXELS:
                    return "tem dimensões grandes demais"
                imagem.verify()
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        ValueError,
    ):
        return "não é uma imagem válida"
    finally:
        try:
            arquivo.seek(0)
        except (AttributeError, ValueError):
            pass

    ext = FORMATOS_EXT.get(formato)
    if not ext:
        return "deve estar em PNG, JPG ou WEBP"

    base = os.path.splitext(os.path.basename(arquivo.name or ""))[0]
    arquivo.name = f"{base or 'imagem'}.{ext}"
    return None
