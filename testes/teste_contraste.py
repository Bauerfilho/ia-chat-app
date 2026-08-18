#!/usr/bin/env python3
"""Contraste WCAG dos pares que a interface realmente pinta.

Este teste existe porque medir a paleta NÃO é medir a interface. Os tokens de
cor por IA foram calibrados contra `--palha-100` (#FBF6EC), mas o texto da sala
é pintado sobre `--palha-200` (#F2EADA) — mais escuro. A folga sumiu ali, e um
teste que olhasse só a tabela de cores teria dito que estava tudo bem.

Então a tabela abaixo é de PARES (tinta sobre fundo composto), não de cores: cada
linha nomeia onde o par aparece na tela, e o fundo é montado como o navegador
monta — empilhando véu translúcido sobre a superfície.

Regra aplicada: WCAG 2.1 AA — 4.5 para texto normal, 3.0 para texto grande
(≥24px, ou ≥18.66px em peso 700) e para elemento de interface. O que é puramente
decorativo (filete, sombra, pauta de papel, brilho) não entra: AA vale para
texto e para componente de interface, não para todo pixel.
"""
from __future__ import annotations

import re
from pathlib import Path

CSS = Path(__file__).resolve().parent.parent / "ui" / "estilo.css"

_ok = 0
_falhou = 0


def checa(nome: str, cond: bool, detalhe: str = "") -> None:
    global _ok, _falhou
    if cond:
        _ok += 1
        print(f"  ✔ {nome}")
    else:
        _falhou += 1
        print(f"  ✗ {nome}" + (f" — {detalhe}" if detalhe else ""))


# ── leitura dos tokens ─────────────────────────────────────────────────────
def blocos(texto: str) -> tuple[dict[str, str], dict[str, str]]:
    """Os dois blocos de token: `:root` e `:root[data-tema="carvao"]`."""
    def corpo(seletor: str) -> str:
        m = re.search(re.escape(seletor) + r"\s*\{(.*?)\n\}", texto, re.S)
        if not m:
            raise SystemExit(f"✗ bloco {seletor} não encontrado em {CSS}")
        return m.group(1)

    def pares(corpo_css: str) -> dict[str, str]:
        return {n: v.strip() for n, v in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", corpo_css)}

    return pares(corpo(":root")), pares(corpo(':root[data-tema="carvao"]'))


def resolve(nome: str, tokens: dict[str, str], base: dict[str, str]) -> str:
    """Resolve `var(--x)` em cadeia até chegar num literal."""
    visto = set()
    valor = tokens.get(nome, base.get(nome, ""))
    while valor.startswith("var("):
        alvo = valor[4:].split(")")[0].split(",")[0].strip()
        if alvo in visto:
            raise SystemExit(f"✗ ciclo em {nome}")
        visto.add(alvo)
        valor = tokens.get(alvo, base.get(alvo, ""))
    return valor.strip()


# ── cor ────────────────────────────────────────────────────────────────────
def cor(v: str) -> tuple[float, float, float, float]:
    v = v.strip()
    if v.startswith("#"):
        h = v[1:]
        return (*(int(h[i:i + 2], 16) for i in (0, 2, 4)), 1.0)
    n = [float(x) for x in re.findall(r"-?[\d.]+", v)]
    return (n[0], n[1], n[2], n[3] if len(n) > 3 else 1.0)


def sobre(frente: tuple, tras: tuple) -> tuple:
    a = frente[3]
    return (*(frente[i] * a + tras[i] * (1 - a) for i in range(3)), 1.0)


def lum(c: tuple) -> float:
    def canal(x: float) -> float:
        x /= 255
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
    return 0.2126 * canal(c[0]) + 0.7152 * canal(c[1]) + 0.0722 * canal(c[2])


def contraste(a: tuple, b: tuple) -> float:
    la, lb = lum(a), lum(b)
    if la < lb:
        la, lb = lb, la
    return (la + 0.05) / (lb + 0.05)


IAS = ("claude", "codex", "kimi", "agy", "grok", "qwen",
       "ollama", "deepseek", "dourada", "bauer", "anonima")


def pares_palha(t: dict, base: dict) -> list[tuple[str, str, tuple, float]]:
    """(onde aparece, descrição, cor, fundo, mínimo) no tema claro."""
    v = lambda n: cor(resolve(n, t, base))          # noqa: E731
    sala = v("--palha-200")                          # o fundo REAL da sala
    superf = v("--palha-100")
    veu_ouro = sobre(cor(resolve("--ouro-veu", t, base)), sala)
    carvao = v("--carvao-800")
    p = []
    for ia in IAS:
        tinta = v(f"--{ia}-t")
        p.append((f"nome de quem falou · {ia}", tinta, sala, 4.5))
        p.append((f"destinatário @{ia}", tinta, sala, 4.5))
        # a pílula de menção é de PAPEL: fundo `--superf-alta`, cor no texto e no filete
        p.append((f"menção @{ia} na sala", tinta, v("--palha-000"), 4.5))
        # dentro do cartão do dono o fundo é carvão: ali vale a variante VIVA
        viva = v(f"--{ia}")
        p.append((f"menção @{ia} no cartão do dono", viva,
                  sobre((*viva[:3], 0.10), carvao), 4.5))
    p += [
        ("ênfase em dourado", v("--ouro-tinta"), sala, 4.5),
        ("código na mensagem", v("--ouro-tinta"), veu_ouro, 4.5),
        ("faixa de destino", v("--ouro-tinta"), veu_ouro, 4.5),
        ("separador de dia", v("--ouro-tinta"), sala, 4.5),
        ("texto da mensagem", v("--tinta"), sala, 4.5),
        ("texto secundário", v("--tinta-2"), sala, 4.5),
        ("hora e contador", v("--tinta-3"), sala, 4.5),
        ("nota do painel", v("--tinta-3"), superf, 4.5),
        ("compositor · texto", v("--caixa-tinta"), v("--caixa-fundo"), 4.5),
        ("compositor · contador", v("--caixa-fraca"), v("--caixa-fundo"), 4.5),
        ("compositor · pílula", v("--caixa-pilula"), v("--caixa-fundo"), 4.5),
        ("trilho · rótulo", v("--tinta-3-carvao"), carvao, 4.5),
        ("trilho · botão", v("--palha-400"), carvao, 4.5),
        # o item destacado da paleta soma o véu dourado à superfície alta
        ("paleta · comando", v("--ouro-tinta"),
         sobre(cor(resolve("--ouro-veu", t, base)), v("--palha-000")), 4.5),
        ("paleta · quem executa", v("--tinta-2"),
         sobre(cor(resolve("--ouro-veu", t, base)), v("--palha-000")), 4.5),
        ("paleta · a implementar", v("--atencao"),
         sobre(cor(resolve("--ouro-veu", t, base)), v("--palha-000")), 4.5),
        ("faixa de destino nominada", v("--claude-t"), v("--palha-000"), 4.5),
        ("avatar do destino", v("--kimi-t"), v("--palha-000"), 4.5),
        ("botão Enviar", v("--carvao-900"), v("--ouro"), 4.5),
        ("comando na mensagem", v("--carvao-900"), v("--ouro"), 4.5),
    ]
    return p


def pares_carvao(t: dict, base: dict) -> list[tuple[str, str, tuple, float]]:
    v = lambda n: cor(resolve(n, t, base))          # noqa: E731
    fundo = v("--fundo")
    superf_alta = v("--superf-alta")
    p = []
    for ia in IAS:
        viva = v(f"--{ia}-t")   # no carvão, `-t` já aponta para a viva
        p.append((f"nome de quem falou · {ia}", viva, fundo, 4.5))
        p.append((f"cartão do painel · {ia}", viva, superf_alta, 4.5))
    p += [
        ("ênfase em dourado", v("--ouro-tinta"), fundo, 4.5),
        ("texto da mensagem", v("--tinta"), fundo, 4.5),
        ("texto secundário", v("--tinta-2"), fundo, 4.5),
        ("hora e contador", v("--tinta-3"), superf_alta, 4.5),
        ("compositor · texto", v("--caixa-tinta"), v("--caixa-fundo"), 4.5),
        ("compositor · contador", v("--caixa-fraca"), v("--caixa-fundo"), 4.5),
        ("compositor · pílula", v("--caixa-pilula"), v("--caixa-fundo"), 4.5),
        ("trilho · rótulo", v("--tinta-3-carvao"), v("--carvao-800"), 4.5),
        # o item destacado da paleta soma o véu dourado à superfície alta
        ("paleta · comando", v("--ouro-tinta"),
         sobre(cor(resolve("--ouro-veu", t, base)), superf_alta), 4.5),
        ("paleta · quem executa", v("--tinta-2"),
         sobre(cor(resolve("--ouro-veu", t, base)), superf_alta), 4.5),
        ("paleta · a implementar", v("--atencao"),
         sobre(cor(resolve("--ouro-veu", t, base)), superf_alta), 4.5),
    ]
    return p


def roda(nome: str, pares) -> None:
    print(f"— {nome} —")
    piores = []
    for onde, tinta, fundo, minimo in pares:
        r = contraste(tinta, fundo)
        if r < minimo:
            piores.append((onde, r, minimo, tinta, fundo))
    hexa = lambda c: "#%02X%02X%02X" % tuple(round(x) for x in c[:3])   # noqa: E731
    for onde, r, minimo, tinta, fundo in piores:
        checa(f"{onde}", False, f"{r:.2f} < {minimo} ({hexa(tinta)} sobre {hexa(fundo)})")
    checa(f"os {len(pares)} pares do tema {nome} passam em AA", not piores,
          f"{len(piores)} abaixo do mínimo")


def main() -> int:
    texto = CSS.read_text(encoding="utf-8")
    base, carvao = blocos(texto)
    roda("palha", pares_palha(base, base))
    roda("carvão", pares_carvao(carvao, base))
    print(f"\n{_ok} ✔ / {_falhou} ✗")
    return 1 if _falhou else 0


if __name__ == "__main__":
    raise SystemExit(main())
