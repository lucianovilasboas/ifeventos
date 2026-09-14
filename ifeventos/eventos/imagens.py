"""Conversão da imagem recortada enviada pelos formulários.

O recorte acontece no navegador (Cropper): o usuário escolhe o arquivo, corta
no formato do campo e o resultado vai num campo hidden `cropped_image` como data
URL (base64). A view troca o arquivo original por esse recorte.

Antes essa lógica estava copiada em cada view (perfil, evento, atividade); este
módulo concentra o mesmo mecanismo num só lugar.
"""

import base64
import uuid
from io import BytesIO

from django.core.files.base import ContentFile
from PIL import Image

# Formatos aceitos no recorte. A chave é o `format` que o Pillow reporta ao
# abrir o arquivo; o valor é a extensão canônica gravada (jpg unifica jpeg).
# O conteúdo manda, não a MIME do data URL: um "data:image/png" com bytes JPEG
# vira .jpg.
_FORMATOS_ACEITOS = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}


def imagem_cortada(request, prefixo):
    """Devolve o recorte de `cropped_image` como ContentFile, ou None se inválido.

    `prefixo` nomeia o arquivo. O sufixo curto evita colisões e nomes como
    "evento_None.png" na criação (quando o objeto ainda não tem id).
    A extensão vem do conteúdo validado pelo Pillow; o `upload_to` do campo
    refaz o caminho final. Qualquer coisa fora da whitelist (ou corrompida)
    devolve None, e a view cai no arquivo cru — que o formulário já validou.
    """
    dados = request.POST.get("cropped_image")
    if not dados:
        return None

    try:
        _formato_declarado, imgstr = dados.split(";base64,")
    except ValueError:
        return None

    try:
        conteudo = base64.b64decode(imgstr)
        with Image.open(BytesIO(conteudo)) as imagem:
            formato_real = imagem.format
            imagem.verify()
    except Exception:
        return None

    extensao = _FORMATOS_ACEITOS.get(formato_real or "")
    if not extensao:
        return None

    nome = f"{prefixo}_{uuid.uuid4().hex[:8]}.{extensao}"
    return ContentFile(conteudo, name=nome)
