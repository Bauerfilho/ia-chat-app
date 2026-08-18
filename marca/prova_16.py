#!/usr/bin/env python3
"""Folha de prova do ícone: o teste do 16x16, sem maquiagem.

Amplia com NEAREST — mostra o pixel que o Finder realmente desenha. Reduzir
e suavizar mentiria sobre o que se lê no menor tamanho. Também emite a fileira
em tamanho real, que é como o ícone aparece de fato na lista do Finder.
"""
import os
from PIL import Image, ImageDraw

AQUI = os.path.dirname(os.path.abspath(__file__))
TEMAS = ["palha", "preto"]
TAMS = [16, 32, 64, 128]
CELULA = 128
CLARO = (232, 232, 234)
ESCURO = (38, 38, 40)


def carregar(tema, t):
    return Image.open(os.path.join(AQUI, "render", tema, f"icone-{t}.png")).convert("RGBA")


def sobre(im, cor):
    b = Image.new("RGBA", im.size, cor + (255,))
    b.alpha_composite(im)
    return b.convert("RGB")


def zoom():
    linhas = [(tema, fundo, nome) for tema in TEMAS
              for fundo, nome in ((CLARO, "claro"), (ESCURO, "escuro"))]
    larg = 40 + len(TAMS) * (CELULA + 36)
    alt = 30 + len(linhas) * (CELULA + 52)
    fora = Image.new("RGB", (larg, alt), (252, 252, 252))
    d = ImageDraw.Draw(fora)
    for li, (tema, fundo, nome) in enumerate(linhas):
        y = 20 + li * (CELULA + 52)
        for ci, t in enumerate(TAMS):
            x = 24 + ci * (CELULA + 36)
            im = carregar(tema, t)
            f = CELULA // t
            fora.paste(sobre(im.resize((t * f, t * f), Image.NEAREST), fundo), (x, y))
            d.text((x, y + CELULA + 8), f"{tema} · {t}px · fundo {nome}", fill=(110, 110, 110))
    saida = os.path.join(AQUI, "render", "prova-16.png")
    fora.save(saida)
    print(saida, fora.size)


def real():
    """Tamanho real, 1:1 — o teste honesto: dá para reconhecer assim?"""
    fora = Image.new("RGB", (560, 200), (246, 246, 246))
    d = ImageDraw.Draw(fora)
    for li, (fundo, nome) in enumerate(((CLARO, "claro"), (ESCURO, "escuro"))):
        y = 30 + li * 90
        d.rectangle([0, y - 22, 560, y + 62], fill=fundo)
        x = 30
        for tema in TEMAS:
            for t in [16, 32, 64]:
                im = carregar(tema, t)
                fora.paste(sobre(im, fundo), (x, y + (64 - t) // 2))
                x += t + 26
        d.text((470, y + 20), nome, fill=(140, 140, 140))
    saida = os.path.join(AQUI, "render", "prova-real.png")
    fora.save(saida)
    print(saida)


if __name__ == "__main__":
    zoom()
    real()
