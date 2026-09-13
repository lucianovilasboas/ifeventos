"""Desenho dos icones do PWA (marca verde institucional + "NE").

Modulo puro de propositio: so depende de Pillow, nao de Django. Assim pode ser
executado tanto pelo comando `gerar_icones_pwa` quanto por um `python -c` fora
de um ambiente Django (util quando a imagem do conteiner nao tem fonte
instalada e os PNGs sao gerados no host e versionados).
"""

from pathlib import Path

# Verde institucional PANTONE 362 C, o mesmo `--accent` de tokens.css.
VERDE = (47, 158, 65, 255)
BRANCO = (255, 255, 255, 255)
TRANSPARENTE = (0, 0, 0, 0)

# Caminhos candidatos para uma fonte bold, em ordem. O host de desenvolvimento
# sem fonte DejaVu precisa de mensagem clara em vez de erro obscuro do Pillow.
FONTES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


class FonteAusente(Exception):
    """Nenhuma fonte bold disponivel para desenhar a marca."""


def _fonte(tamanho):
    from PIL import ImageFont

    for caminho in FONTES:
        if Path(caminho).is_file():
            return ImageFont.truetype(caminho, tamanho)
    raise FonteAusente("Nenhuma fonte bold encontrada. Avalie: " + ", ".join(FONTES))


def _novo_icone(tamanho, arredondado):
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (tamanho, tamanho), TRANSPARENTE)
    draw = ImageDraw.Draw(img)
    if arredondado:
        raio = int(tamanho * 0.22)
        draw.rounded_rectangle((0, 0, tamanho - 1, tamanho - 1), radius=raio, fill=VERDE)
    else:
        draw.rectangle((0, 0, tamanho - 1, tamanho - 1), fill=VERDE)
    return img, draw


def _marca(draw, tamanho, fator_texto):
    draw.text(
        (tamanho / 2, tamanho / 2),
        "NE",
        font=_fonte(int(tamanho * fator_texto)),
        fill=BRANCO,
        anchor="mm",
    )


def gerar(destino):
    """Gera todos os icones em `destino` (Path). Cria a pasta se preciso."""
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)

    # Icones "any": quadrado arredondado com cantos transparentes.
    for tamanho in (192, 512):
        img, draw = _novo_icone(tamanho, arredondado=True)
        _marca(draw, tamanho, fator_texto=0.40)
        img.save(destino / f"icon-{tamanho}.png")

    # Maskable: sem transparencia e com a marca dentro da "zona segura"
    # (~80% central), porque o Android recorta em circulo/quadrado.
    img, draw = _novo_icone(512, arredondado=False)
    _marca(draw, 512, fator_texto=0.32)
    img.save(destino / "icon-maskable-512.png")

    # Apple touch: opaco (o iOS nao lida com transparencia) e quadrado; o
    # proprio sistema aplica o canto arredondado.
    img, draw = _novo_icone(180, arredondado=False)
    _marca(draw, 180, fator_texto=0.40)
    img.save(destino / "apple-touch-icon.png")

    # Favicon multi-tamanho.
    img, draw = _novo_icone(48, arredondado=True)
    _marca(draw, 48, fator_texto=0.40)
    img.save(destino / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])

    return destino
