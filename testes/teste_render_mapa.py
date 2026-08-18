#!/usr/bin/env python3
"""O que o mapa de retomada vira na tela — e o que ele NÃO pode virar.

Ele lê este documento no celular. Endereço que não abre é endereço inútil, e
`[[nome]]` cru é ruído. Mas transformar texto em link é justamente onde mora o
abuso: este arquivo trava as duas pontas.

Roda o `corpoHTML` de verdade, extraído do `sala.js` — não uma reimplementação
em Python, que provaria só que eu sei escrever a mesma regex duas vezes.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "ui"
JS = (UI / "sala.js").read_text(encoding="utf-8")
CSS = (UI / "estilo.css").read_text(encoding="utf-8")

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


def recorta(nome: str) -> str:
    """Tira uma declaração do sala.js — `function X(){}` ou `const X = …;`.

    Recorta a fonte VIVA em vez de reimplementar: um teste que reescreve a regex
    em Python prova só que eu sei escrevê-la duas vezes.
    """
    if f"function {nome}(" in JS:                     # corpo entre chaves
        i = JS.index(f"function {nome}(")
        k, nivel = JS.index("{", i), 0
        while k < len(JS):
            if JS[k] == "{":
                nivel += 1
            elif JS[k] == "}":
                nivel -= 1
                if nivel == 0:
                    return JS[i:k + 1]
            k += 1
        raise ValueError(f"{nome}: chave não fechou")
    if f"const {nome} =" in JS:                       # statement até o `;` de nível 0
        i = JS.index(f"const {nome} =")
        k, nivel = i, 0
        while k < len(JS):
            c = JS[k]
            if c in "{([":
                nivel += 1
            elif c in "})]":
                nivel -= 1
            elif c == ";" and nivel == 0:
                return JS[i:k + 1]
            k += 1
        raise ValueError(f"{nome}: statement não fechou")
    raise ValueError(f"{nome}: não achei a declaração")


def render(entradas: list[str]) -> list[str]:
    """Executa o corpoHTML real no node e devolve o HTML de cada entrada."""
    fonte = "\n".join([
        recorta("IAS"), recorta("esc"), recorta("corDe"), recorta("corpoHTML"),
        "const _e = " + json.dumps(entradas) + ";",
        "console.log(JSON.stringify(_e.map(corpoHTML)));",
    ])
    r = subprocess.run(["node", "-e", fonte], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[:400])
    return json.loads(r.stdout)


def main() -> int:
    if not shutil.which("node"):
        print("— node ausente: as provas de render não rodam —")
        print("  ⚠ NÃO CONFERIDO (o terceiro desfecho: não é verde nem vermelho)")
        # sem node não dá para provar comportamento; o que resta é a estrutura
        checa("o CSS do link existe", ".msg-corpo a" in CSS)
        checa("o CSS do wikilink existe", ".wikilink{" in CSS)
        print(f"\n{_ok} ✔  {_falhou} ✗")
        return 1 if _falhou else 0

    print("— o endereço abre —")
    (link, ponto, wiki, wiki_rot, regua, perigo, dado, texto) = render([
        "painel — http://127.0.0.1:49857/",
        "veja https://exemplo.com/a, depois volte",
        "ver [[reference-iaswarm]] no vault",
        "ver [[reference-iaswarm|o enxame]] aqui",
        "antes\n\n---\n\ndepois",
        "clique em javascript:alert(1) agora",
        "veja data:text/html;base64,PHNjcmlwdD4= aqui",
        "sem endereço nenhum aqui",
    ])
    checa("endereço http vira link", '<a href="http://127.0.0.1:49857/"' in link, link)
    checa("o link abre em aba nova, sem alcançar esta",
          'target="_blank"' in link and 'rel="noopener noreferrer"' in link)
    checa("a vírgula da frase fica FORA do endereço",
          '<a href="https://exemplo.com/a"' in ponto and "</a>," in ponto, ponto)

    print("— e o que NÃO pode virar link —")
    checa("`javascript:` não vira link", "<a " not in perigo, perigo)
    checa("`data:` não vira link", "<a " not in dado, dado)
    checa("texto sem endereço continua sem link", "<a " not in texto)

    print("— a marca do Obsidian —")
    checa("wikilink vira rótulo", 'class="wikilink">reference-iaswarm<' in wiki, wiki)
    checa("wikilink NÃO vira link para lugar nenhum", "<a " not in wiki,
          "o vault não é servido aqui; link que não abre mente")
    checa("wikilink com rótulo mostra o rótulo",
          'class="wikilink">o enxame<' in wiki_rot, wiki_rot)
    checa("`---` vira régua, não três hifens", "<hr" in regua and "---" not in regua, regua)

    print("— o estilo existe nos dois temas —")
    checa("o link tem cor própria", ".msg-corpo a" in CSS)
    checa("o wikilink se distingue de link de verdade",
          '.wikilink::before{content:"[["' in CSS,
          "sem os colchetes, ele parece clicável e não é")

    print(f"\n{_ok} ✔  {_falhou} ✗")
    return 1 if _falhou else 0


if __name__ == "__main__":
    raise SystemExit(main())
