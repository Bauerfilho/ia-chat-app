#!/usr/bin/env python3
"""Prancha de apresentação da marca: marca.png.

É a peça que vai no README — o rosto do repositório antes de qualquer código.
Grade explícita (duas colunas, calha de 60), nada posicionado no olho: cada
bloco declara topo e altura, e a checagem no fim do arquivo reprova se algum
invadir o vizinho ou a margem.
"""
import os
from PIL import Image, ImageDraw, ImageFont

AQUI = os.path.dirname(os.path.abspath(__file__))

L, A = 1600, 1260
M = 80
ESQ_X, ESQ_W = M, 680
DIR_X, DIR_W = 820, 700          # 820 + 700 = 1520 = L - M

PALHA_ALTA = "#F7EFDC"
PALHA = "#E9DCBE"
PALHA_BAIXA = "#D3C298"
PRETO = "#12110C"
OURO = "#D4AF37"
OURO_TINTA = "#7A5E10"
TINTA = "#3B3116"
CINZA = "#8A7B5C"
TRAMA = (240, 231, 209)

MONO = "/System/Library/Fonts/Menlo.ttc"
SERIF = "/System/Library/Fonts/Supplemental/Didot.ttc"
SANS = "/System/Library/Fonts/Avenir Next.ttc"

ocupado = []                      # (nome, x0, y0, x1, y1) para a checagem


def marcar(nome, x0, y0, x1, y1):
    ocupado.append((nome, x0, y0, x1, y1))


def f(caminho, tam, i=0):
    return ImageFont.truetype(caminho, tam, index=i)


def tracking(d, xy, txt, fonte, cor, esp=0):
    """PIL não tem letter-spacing; caixa alta pequena sem tracking fica suja."""
    x, y = xy
    for ch in txt:
        d.text((x, y), ch, font=fonte, fill=cor)
        x += d.textlength(ch, font=fonte) + esp
    return x


def icone(tema, n):
    p = os.path.join(AQUI, "render", tema, "icone-1024.png")
    return Image.open(p).convert("RGBA").resize((n, n), Image.LANCZOS)


def tira(im, d, tema, x0, base, fnum):
    """Os tamanhos reais, alinhados pela base — como o Finder empilha."""
    x = x0
    for t in (128, 64, 32, 16):
        p = Image.open(os.path.join(AQUI, "render", tema, f"icone-{t}.png")).convert("RGBA")
        im.paste(p, (x, base - t), p)
        d.text((x + t / 2, base + 10), str(t), font=fnum, fill=CINZA, anchor="ma")
        x += t + 40
    return x


def main():
    im = Image.new("RGB", (L, A), PALHA_ALTA)
    d = ImageDraw.Draw(im)
    for x in range(0, L, 68):
        d.line([(x, 0), (x, A)], fill=TRAMA, width=1)
    for y in range(0, A, 68):
        d.line([(0, y), (L, y)], fill=TRAMA, width=1)

    t_nome = f(MONO, 92, 1)
    t_frase = f(SERIF, 33, 1)
    t_rot = f(SANS, 14, 1)
    t_corpo = f(SANS, 18)
    t_sw = f(SANS, 17, 1)
    t_hex = f(MONO, 13)
    t_num = f(MONO, 12)
    t_leg = f(SANS, 15)

    # ===================================================== coluna esquerda
    lado = 320
    im.paste(icone("palha", lado), (ESQ_X, 140), icone("palha", lado))
    im.paste(icone("preto", lado), (ESQ_X + 360, 140), icone("preto", lado))
    marcar("icones", ESQ_X, 140, ESQ_X + 680, 460)

    d.text((ESQ_X, 476), "icone.icns", font=t_sw, fill=TINTA)
    d.text((ESQ_X, 498), "palha · o ícone do app", font=t_hex, fill=CINZA)
    d.text((ESQ_X + 360, 476), "icone-preto.icns", font=t_sw, fill=TINTA)
    d.text((ESQ_X + 360, 498), "preto · menu e fundo claro", font=t_hex, fill=CINZA)
    marcar("rotulos icones", ESQ_X, 476, ESQ_X + 680, 514)

    tracking(d, (ESQ_X, 566), "O TESTE DO 16", t_rot, TINTA, 2.4)
    marcar("titulo tira", ESQ_X, 566, ESQ_X + 200, 584)

    fim = tira(im, d, "palha", ESQ_X, 730, t_num)
    tira(im, d, "preto", ESQ_X, 880, t_num)
    marcar("tiras", ESQ_X, 602, max(fim, ESQ_X + 400), 896)

    d.text((ESQ_X, 930),
           "sem downscale: cada tamanho sai do vetor. Em 16 e 32 entra a versão sem\n"
           "trama, sem sombra e sem fio de cor, com a geometria travada na grade de\n"
           "pixel — abaixo de 32px o detalhe não vira forma, vira sujeira.",
           font=t_leg, fill=CINZA, spacing=8)
    marcar("legenda tira", ESQ_X, 930, ESQ_X + 680, 1000)

    by = 1032
    d.rounded_rectangle([ESQ_X, by, ESQ_X + ESQ_W, by + 88], radius=14, fill=PRETO)
    d.text((ESQ_X + 26, by + 20), "ouro sobre palha", font=t_corpo, fill=PALHA)
    d.text((ESQ_X + 196, by + 20), "1.55:1", font=f(MONO, 18, 1), fill="#E07A5F")
    d.text((ESQ_X + 296, by + 20), "ouro sobre preto", font=t_corpo, fill=PALHA)
    d.text((ESQ_X + 466, by + 20), "8.99:1", font=f(MONO, 18, 1), fill=OURO)
    d.text((ESQ_X + 26, by + 52), "o ouro nunca encosta na palha sem leito preto.",
           font=t_corpo, fill=PALHA_BAIXA)
    marcar("regra", ESQ_X, by, ESQ_X + ESQ_W, by + 88)

    # ====================================================== coluna direita
    d.text((DIR_X, 128), "ia-chat", font=t_nome, fill=PRETO)
    marcar("nome", DIR_X, 128, DIR_X + 500, 244)

    d.text((DIR_X, 262), "Três janelas que não se veem.", font=t_frase, fill=TINTA)
    d.text((DIR_X, 306), "Um canal que atravessa as três.", font=t_frase, fill=TINTA)
    marcar("frase", DIR_X, 262, DIR_X + DIR_W, 352)

    ry = 396
    d.rounded_rectangle([DIR_X, ry, DIR_X + DIR_W, ry + 56], radius=13, fill=PRETO)
    d.rounded_rectangle([DIR_X + 15, ry + 15, DIR_X + DIR_W - 15, ry + 41],
                        radius=7, fill=OURO)
    marcar("regua", DIR_X, ry, DIR_X + DIR_W, ry + 56)

    tracking(d, (DIR_X, 494), "PALETA", t_rot, TINTA, 2.4)
    marcar("titulo paleta", DIR_X, 494, DIR_X + 120, 512)

    sw, passo = 140, 280
    paleta = [(PALHA_ALTA, "palha alta", "papel"),
              (PALHA, "palha", "base"),
              (PALHA_BAIXA, "palha baixa", "sombra"),
              (PRETO, "preto", "par do ouro"),
              (OURO, "ouro", "acento · sobre preto"),
              (OURO_TINTA, "ouro tinta", "texto sobre palha 4.5:1")]
    for i, (cor, nome, papel) in enumerate(paleta):
        x = DIR_X + (i % 3) * passo
        y = 528 + (i // 3) * 230
        borda = PRETO if cor in (PALHA_ALTA, PALHA, PALHA_BAIXA) else None
        d.rounded_rectangle([x, y, x + sw, y + sw], radius=12, fill=cor,
                            outline=borda, width=1)
        d.text((x, y + sw + 12), nome, font=t_sw, fill=TINTA)
        d.text((x, y + sw + 34), cor.upper(), font=t_hex, fill=CINZA)
        d.text((x, y + sw + 54), papel, font=t_hex, fill=CINZA)
    marcar("paleta", DIR_X, 528, DIR_X + 2 * passo + sw, 528 + 230 + sw + 70)

    tracking(d, (DIR_X, 1012), "COR POR IA — A QUEBRA", t_rot, TINTA, 2.4)
    marcar("titulo ia", DIR_X, 1012, DIR_X + 300, 1030)

    ia = [("#3A6FD8", "agy"), ("#7C4DD6", "kimi"), ("#0F9C8C", "codex"),
          ("#C9D6E8", "grok"), ("#6D3FD1", "qwen"), ("#D4AF37", "dourada")]
    lado_ia, passo_ia = 76, (DIR_W - 76) / 5
    for i, (cor, nome) in enumerate(ia):
        x = DIR_X + i * passo_ia
        d.rounded_rectangle([x, 1046, x + lado_ia, 1046 + lado_ia], radius=10,
                            fill=cor, outline=PRETO if nome == "grok" else None, width=1)
        d.text((x, 1134), nome, font=t_hex, fill=CINZA)
    marcar("cores ia", DIR_X, 1046, DIR_X + DIR_W, 1152)

    checar()
    saida = os.path.join(AQUI, "marca.png")
    im.save(saida)
    print(f"{saida}  {im.size}")


def checar():
    """Reprova sobreposição e estouro de margem — a queixa recorrente dele
    é justamente margem mal alocada; deixar isso para o olho é apostar."""
    erros = []
    for nome, x0, y0, x1, y1 in ocupado:
        if x0 < M or y0 < M or x1 > L - M or y1 > A - M:
            erros.append(f"{nome} estoura a margem: ({x0},{y0})-({x1},{y1})")
    for i, a in enumerate(ocupado):
        for b in ocupado[i + 1:]:
            if a[1] < b[3] and b[1] < a[3] and a[2] < b[4] and b[2] < a[4]:
                erros.append(f"{a[0]} x {b[0]} se sobrepõem")
    if erros:
        raise SystemExit("PRANCHA REPROVADA:\n  " + "\n  ".join(erros))
    print(f"grade ok: {len(ocupado)} blocos, sem sobreposição, dentro da margem {M}")


if __name__ == "__main__":
    main()
