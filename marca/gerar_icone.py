#!/usr/bin/env python3
"""Gera icone.svg (mestre 1024) e os PNGs do iconset.

Regra de desenho: o 16x16 manda. Em 16px o corpo tem ~13px úteis, então a
marca tem direito a tres formas de 2px separadas por 2px — nada mais cabe.
Cada elemento aqui existe em duas escalas: massa que sobrevive ao 16, e
detalhe que so premia quem olha de perto (trama, brilho, fio de cor).

Sem <filter>: so paths, gradientes e patterns — assim o SVG renderiza igual
em cairosvg, Chrome, Preview e Finder.

Uso:  python3 gerar_icone.py [palha|preto]
"""
import math
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- paleta
PALHA_ALTA = "#F7EFDC"
PALHA = "#E9DCBE"
PALHA_BAIXA = "#D3C298"
PRETO = "#12110C"
PRETO_ALTO = "#26221A"
OURO_ALTO = "#F4E2A8"
OURO = "#D4AF37"
OURO_BAIXO = "#93711A"
OURO_CHAPADO = "#C9A227"    # 16 e 32px: gradiente de 5 paradas em 2px vira media lavada
AZUL_AGY = "#3A6FD8"        # tons de joia, nao de post-it: o fio e detalhe,
VIOLETA_KIMI = "#7C4DD6"    # nao concorre com o ouro
TEAL_CODEX = "#0F9C8C"

# ------------------------------------------------------------- geometria
LADO = 1024
CORPO = 824.0                 # grade Big Sur: arte 824 em canvas 1024
MARGEM = (LADO - CORPO) / 2
CENTRO = LADO / 2

HASTE_W = 124                 # ~2px em 16px
HASTE_VAO = 118               # o vao quase vale a haste: a cegueira e estrutural
HASTE_R = 16
HASTE_H_CENTRO = 566
HASTE_H_LADO = 430

CANAL_H = 156                 # o canal e a peca mais grossa: e o produto
CANAL_PROJ = 32               # ultrapassa as hastes: o canal esta aberto
CANAL_R = 18
CANAL_BORDA = 18              # separa o ouro da palha quando o pixel some

FIO_COR_H = 12                # assinatura de cor por IA, no topo de cada haste


def squircle(cx, cy, raio, n=5.0, amostras=48):
    """Superelipse |x|^n + |y|^n = r^n, suavizada por Catmull-Rom -> Bezier.

    n=5 e a curva continua que o macOS usa; um round-rect comum entrega o
    canto errado e o icone denuncia amadorismo no Dock.
    """
    e = 2.0 / n
    p = []
    for i in range(amostras):
        t = 2 * math.pi * i / amostras
        c, s = math.cos(t), math.sin(t)
        p.append((cx + raio * math.copysign(abs(c) ** e, c),
                  cy + raio * math.copysign(abs(s) ** e, s)))

    d = [f"M {p[0][0]:.2f} {p[0][1]:.2f}"]
    for i in range(amostras):
        p0 = p[(i - 1) % amostras]
        p1, p2 = p[i], p[(i + 1) % amostras]
        p3 = p[(i + 2) % amostras]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        d.append(f"C {c1[0]:.2f} {c1[1]:.2f} {c2[0]:.2f} {c2[1]:.2f} "
                 f"{p2[0]:.2f} {p2[1]:.2f}")
    d.append("Z")
    return " ".join(d)


# Grade do 16px: 1 pixel = 64 unidades do canvas. Toda medida do modo pequeno
# e multiplo de 64, entao a marca cai em pixel inteiro e nao vira cinza — o
# mesmo hinting vale de graca em 32px (1px = 32 u).
PX = LADO // 16
HINT = {
    "haste_w": 2 * PX, "haste_vao": 2 * PX, "haste_r": PX // 2,
    "h_centro": 8 * PX, "h_lado": 6 * PX,
    "canal_h": 2 * PX, "canal_proj": PX, "canal_r": PX // 2, "canal_borda": PX // 2,
}


def medidas(hint):
    if not hint:
        return {"haste_w": HASTE_W, "haste_vao": HASTE_VAO, "haste_r": HASTE_R,
                "h_centro": HASTE_H_CENTRO, "h_lado": HASTE_H_LADO,
                "canal_h": CANAL_H, "canal_proj": CANAL_PROJ,
                "canal_r": CANAL_R, "canal_borda": CANAL_BORDA}
    return dict(HINT)


def hastes(m):
    """As tres janelas: mesma largura, alturas simetricas, nenhuma se toca."""
    largura = 3 * m["haste_w"] + 2 * m["haste_vao"]
    x = CENTRO - largura / 2
    saida = []
    for i, alt in enumerate((m["h_lado"], m["h_centro"], m["h_lado"])):
        saida.append({"x": x + i * (m["haste_w"] + m["haste_vao"]),
                      "y": CENTRO - alt / 2, "w": m["haste_w"], "h": alt})
    return saida


def montar_svg(tema="palha", detalhe=True):
    """detalhe=False: versao para 16 e 32px — sem trama, vinheta, sombra,
    brilho nem fio de cor. Abaixo de 32px esses elementos nao viram forma,
    viram sujeira; um icone honesto os remove em vez de os encolher."""
    escuro = tema == "preto"
    m = medidas(hint=not detalhe)
    corpo = squircle(CENTRO, CENTRO, CORPO / 2, n=5.0)
    hs = hastes(m)
    cx0 = hs[0]["x"] - m["canal_proj"]
    cx1 = hs[2]["x"] + m["haste_w"] + m["canal_proj"]
    cores_ia = (AZUL_AGY, VIOLETA_KIMI, TEAL_CODEX)

    ouro_fill = "url(#ouro)" if detalhe else OURO_CHAPADO
    if escuro:
        base_stops = [("0", PRETO_ALTO), ("0.58", PRETO), ("1", "#0B0A07")]
        marca = "url(#palhaMarca)" if detalhe else PALHA_ALTA
        trama_cor, trama_op = "#E9DCBE", "0.055"
        vinheta_cor, vinheta_op = "#000000", "0.34"
        borda_canal = "#0B0A07"
        silhueta = "#F7EFDC"
        silhueta_op = "0.12"
        sombra_cor = "#000000"
    else:
        base_stops = [("0", PALHA_ALTA), ("0.55", PALHA), ("1", PALHA_BAIXA)]
        marca = "url(#pretaMarca)" if detalhe else PRETO
        trama_cor, trama_op = "#4A3D1D", "0.05"
        vinheta_cor, vinheta_op = "#6B5A31", "0.20"
        borda_canal = PRETO
        silhueta = "#8A7644" if detalhe else "#6B5A31"
        silhueta_op = "0.30" if detalhe else "0.60"
        sombra_cor = "#3B3116"

    p = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{LADO}" height="{LADO}" '
        f'viewBox="0 0 {LADO} {LADO}" role="img" aria-label="ia-chat">',
        "  <title>ia-chat</title>",
        "  <desc>Tres janelas que nao se veem, atravessadas por um unico canal.</desc>",
        "  <defs>",
        '    <linearGradient id="base" x1="0.12" y1="0" x2="0.88" y2="1">',
    ]
    p += [f'      <stop offset="{o}" stop-color="{c}"/>' for o, c in base_stops]
    p += [
        "    </linearGradient>",
        '    <linearGradient id="pretaMarca" x1="0" y1="0" x2="0" y2="1">',
        f'      <stop offset="0" stop-color="{PRETO_ALTO}"/>',
        f'      <stop offset="1" stop-color="{PRETO}"/>',
        "    </linearGradient>",
        '    <linearGradient id="palhaMarca" x1="0" y1="0" x2="0" y2="1">',
        f'      <stop offset="0" stop-color="{PALHA_ALTA}"/>',
        f'      <stop offset="1" stop-color="{PALHA_BAIXA}"/>',
        "    </linearGradient>",
        '    <linearGradient id="ouro" x1="0" y1="0" x2="0" y2="1">',
        f'      <stop offset="0" stop-color="{OURO_BAIXO}"/>',
        f'      <stop offset="0.14" stop-color="{OURO_ALTO}"/>',
        f'      <stop offset="0.50" stop-color="{OURO}"/>',
        f'      <stop offset="0.88" stop-color="#B8901F"/>',
        f'      <stop offset="1" stop-color="{OURO_BAIXO}"/>',
        "    </linearGradient>",
        f'    <radialGradient id="vinheta" cx="0.5" cy="0.40" r="0.80">',
        f'      <stop offset="0.52" stop-color="{vinheta_cor}" stop-opacity="0"/>',
        f'      <stop offset="1" stop-color="{vinheta_cor}" stop-opacity="{vinheta_op}"/>',
        "    </radialGradient>",
        '    <linearGradient id="sombra" x1="0" y1="0" x2="0" y2="1">',
        f'      <stop offset="0" stop-color="{sombra_cor}" stop-opacity="0.26"/>',
        f'      <stop offset="1" stop-color="{sombra_cor}" stop-opacity="0"/>',
        "    </linearGradient>",
        '    <pattern id="trama" width="34" height="34" patternUnits="userSpaceOnUse">',
        f'      <path d="M 34 0 L 0 0 0 34" fill="none" stroke="{trama_cor}" '
        f'stroke-opacity="{trama_op}" stroke-width="1.4"/>',
        "    </pattern>",
        f'    <clipPath id="corpo"><path d="{corpo}"/></clipPath>',
    ]
    for i, h in enumerate(hs):
        p.append(f'    <clipPath id="h{i}"><rect x="{h["x"]:.0f}" y="{h["y"]:.0f}" '
                 f'width="{h["w"]}" height="{h["h"]:.0f}" rx="{m["haste_r"]}"/></clipPath>')
    p += [
        "  </defs>",
        "",
        f'  <path d="{corpo}" fill="url(#base)"/>',
        '  <g clip-path="url(#corpo)">',
    ]
    if detalhe:
        p += [
            f'    <rect x="{MARGEM}" y="{MARGEM}" width="{CORPO}" height="{CORPO}" fill="url(#trama)"/>',
            f'    <rect x="{MARGEM}" y="{MARGEM}" width="{CORPO}" height="{CORPO}" fill="url(#vinheta)"/>',
        ]
    p += ["", "    <!-- tres janelas: separadas, cegas uma a outra -->"]
    if detalhe:
        for h in hs:
            p.append(f'    <rect x="{h["x"]:.0f}" y="{h["y"] + 16:.0f}" width="{h["w"]}" '
                     f'height="{h["h"]:.0f}" rx="{m["haste_r"]}" fill="url(#sombra)"/>')
    for h in hs:
        p.append(f'    <rect x="{h["x"]:.0f}" y="{h["y"]:.0f}" width="{h["w"]}" '
                 f'height="{h["h"]:.0f}" rx="{m["haste_r"]}" fill="{marca}"/>')

    if detalhe:
        p.append("")
        p.append("    <!-- assinatura de cor por IA: fio no topo, some abaixo de 64px -->")
        for i, (h, cor) in enumerate(zip(hs, cores_ia)):
            p.append(f'    <rect x="{h["x"]:.0f}" y="{h["y"]:.0f}" width="{h["w"]}" '
                     f'height="{FIO_COR_H}" fill="{cor}" clip-path="url(#h{i})"/>')

    p.append("")
    p.append("    <!-- o canal: um so, atravessa as tres, e passa alem delas -->")
    if detalhe:
        p.append(f'    <rect x="{cx0:.0f}" y="{CENTRO - m["canal_h"] / 2 + 18:.0f}" '
                 f'width="{cx1 - cx0:.0f}" height="{m["canal_h"]}" rx="{m["canal_r"]}" fill="url(#sombra)"/>')
    p.append(f'    <rect x="{cx0:.0f}" y="{CENTRO - m["canal_h"] / 2:.0f}" '
             f'width="{cx1 - cx0:.0f}" height="{m["canal_h"]}" rx="{m["canal_r"]}" '
             f'fill="{ouro_fill}" stroke="{borda_canal}" stroke-width="{m["canal_borda"]}"/>')
    if detalhe:
        p.append(f'    <rect x="{cx0 + 26:.0f}" y="{CENTRO - m["canal_h"] / 2 + 22:.0f}" '
                 f'width="{cx1 - cx0 - 52:.0f}" height="12" rx="6" fill="#FFF8E2" opacity="0.38"/>')

    p += [
        "  </g>",
        "",
        f'  <path d="{corpo}" fill="none" stroke="{silhueta}" '
        f'stroke-opacity="{silhueta_op}" stroke-width="{3 if detalhe else 20}"/>',
        "</svg>",
        "",
    ]
    return "\n".join(p)


TAMANHOS = [16, 32, 64, 128, 256, 512, 1024]
LIMITE_SIMPLES = 32           # ate aqui, versao sem detalhe

# nome no .iconset -> pixels
ICONSET = {
    "icon_16x16.png": 16, "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32, "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128, "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256, "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512, "icon_512x512@2x.png": 1024,
}


def png(tema, n, destino):
    """Renderiza no tamanho pedido a partir do SVG certo para aquele tamanho."""
    import cairosvg
    svg = montar_svg(tema, detalhe=n > LIMITE_SIMPLES)
    cairosvg.svg2png(bytestring=svg.encode(), write_to=destino,
                     output_width=n, output_height=n)


def escrever(tema, nome):
    caminho = os.path.join(AQUI, nome)
    with open(caminho, "w") as f:
        f.write(montar_svg(tema, detalhe=True))
    with open(os.path.join(AQUI, nome.replace(".svg", "-pequeno.svg")), "w") as f:
        f.write(montar_svg(tema, detalhe=False))

    pasta = os.path.join(AQUI, "render", tema)
    os.makedirs(pasta, exist_ok=True)
    for n in TAMANHOS:
        png(tema, n, os.path.join(pasta, f"icone-{n}.png"))
    print(f"{tema:6s} -> {nome} (+ -pequeno.svg) e {len(TAMANHOS)} PNGs em render/{tema}/")


def favicon():
    """favicon.ico — 16+32, tema PRETO, e o base64 que o servidor embute.

    Tema preto por medida, não por gosto: contra a aba clara do Chrome
    (#DEE1E6) o corpo palha dá 1.04:1 — a silhueta simplesmente não existe.
    O corpo preto dá 14.42:1 na aba clara e, na aba escura, quem carrega a
    forma são as três janelas em palha (16.50:1 contra o próprio corpo).

    ICO e não PNG porque a rota que o navegador pede sozinho é `/favicon.ico`,
    e ICO é o único formato que todo navegador aceita ali sem negociação.
    16 e 32 saem do vetor hintado, cada um no seu tamanho — um ICO que só
    guarda 32 e deixa o navegador encolher desfaz justamente o hinting.
    """
    import base64
    import io
    from PIL import Image

    quadros = []
    for n in (16, 32):
        buf = io.BytesIO()
        png("preto", n, buf)
        buf.seek(0)
        quadros.append(Image.open(buf).convert("RGBA"))

    alvo = os.path.join(AQUI, "favicon.ico")
    # `sizes` declara os slots; `append_images` substitui a redução automática
    # pelo quadro hintado daquele tamanho — sem isso o 16 sai de um downscale
    # do 32 e o hinting que custou o desenho todo se perde.
    quadros[1].save(alvo, format="ICO", sizes=[(16, 16), (32, 32)],
                    append_images=[quadros[0]])
    bruto = open(alvo, "rb").read()
    print(f"ico    -> {alvo} ({len(bruto)} B) · base64 {len(base64.b64encode(bruto))} B")
    return bruto


def icns(tema, nome_icns):
    """Monta o .iconset e chama iconutil (nativo do macOS)."""
    import shutil
    import subprocess
    pasta = os.path.join(AQUI, f"{tema}.iconset")
    shutil.rmtree(pasta, ignore_errors=True)
    os.makedirs(pasta)
    for arquivo, n in ICONSET.items():
        png(tema, n, os.path.join(pasta, arquivo))
    saida = os.path.join(AQUI, nome_icns)
    r = subprocess.run(["iconutil", "-c", "icns", pasta, "-o", saida],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f"iconutil FALHOU ({r.returncode}): {r.stderr.strip()}")
        print(f"os PNGs ficam em {pasta}")
        return False
    shutil.rmtree(pasta, ignore_errors=True)   # o .iconset e andaime; o .icns e a entrega
    print(f"icns   -> {saida} ({os.path.getsize(saida)} B)")
    return True


if __name__ == "__main__":
    alvo = sys.argv[1] if len(sys.argv) > 1 else "ambos"
    if alvo in ("palha", "ambos"):
        escrever("palha", "icone.svg")
        icns("palha", "icone.icns")
    if alvo in ("preto", "ambos"):
        escrever("preto", "icone-preto.svg")
        icns("preto", "icone-preto.icns")
    if alvo in ("favicon", "ambos"):
        favicon()
