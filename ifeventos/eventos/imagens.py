"""Conversão da imagem recortada enviada pelos formulários.

O recorte acontece no navegador (Cropper): o usuário escolhe o arquivo, corta
no formato do campo e o resultado vai num campo hidden `cropped_image` como data
URL (base64). A view troca o arquivo original por esse recorte.

Antes essa lógica estava copiada em cada view (perfil, evento, atividade); este
módulo concentra o mesmo mecanismo num só lugar.
"""

import base64
import uuid

from django.core.files.base import ContentFile


def imagem_cortada(request, prefixo):
    """Devolve o recorte de `cropped_image` como ContentFile, ou None se ausente.

    `prefixo` nomeia o arquivo. O sufixo curto evita colisões e nomes como
    "evento_None.png" na criação (quando o objeto ainda não tem id).
    A extensão vem do data URL; o `upload_to` do campo refaz o caminho final.
    """
    dados = request.POST.get("cropped_image")
    if not dados:
        return None

    try:
        formato, imgstr = dados.split(";base64,")
    except ValueError:
        return None

    extensao = (formato.split("/")[-1] or "png").lower()
    conteudo = base64.b64decode(imgstr)
    nome = f"{prefixo}_{uuid.uuid4().hex[:8]}.{extensao}"
    return ContentFile(conteudo, name=nome)
