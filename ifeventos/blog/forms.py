"""Formulários do blog.

O texto é simples (o template escapa e aplica `linebreaks`), então não há campo
de HTML: evita conteúdo executável sem precisar sanitizar.
"""

from django import forms

from .models import PostEvento

TAMANHO_MAX_IMAGEM = 8 * 1024 * 1024  # 8 MB por arquivo
MAX_FOTOS_POR_POST = 12


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
        if capa and getattr(capa, "size", 0) > TAMANHO_MAX_IMAGEM:
            raise forms.ValidationError("A imagem de capa deve ter no máximo 8 MB.")
        return capa


def validar_imagem(arquivo):
    """Devolve uma mensagem de erro, ou None se o arquivo for aceitável.

    O conteúdo é validado pelo Pillow (a extensão/MIME não bastam): o upload é
    aberto e verificado antes de ser gravado.
    """
    from PIL import Image, UnidentifiedImageError

    if arquivo.size > TAMANHO_MAX_IMAGEM:
        return "cada imagem deve ter no máximo 8 MB"
    try:
        with Image.open(arquivo) as imagem:
            imagem.verify()
    except (UnidentifiedImageError, OSError, ValueError):
        return "não é uma imagem válida"
    finally:
        try:
            arquivo.seek(0)
        except (AttributeError, ValueError):
            pass
    return None
