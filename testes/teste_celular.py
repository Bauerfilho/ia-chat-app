#!/usr/bin/env python3
"""Os invariantes do celular — que é o caminho principal do dono.

Medido em 390×844 ANTES destas regras: a gaveta ocupava 336 px de 390 (86% da
tela), sobreposta e quase vazia, e os dois botões que a fechavam viviam no
trilho — que estava `display:none`. Não havia saída: nem fechar a gaveta, nem
trocar de tema, nem ver quem estava na sala. O app era inutilizável no telefone.

O comportamento foi verificado num contexto de navegador móvel real (toque, DPR 3,
user agent de iPhone) — os números estão no `ui/DESIGN.md`. Este arquivo trava as
condições sem as quais aquilo volta a quebrar, e roda sem navegador.

O que NÃO está aqui, e por quê: o teclado virtual do iOS não é emulável. O que se
pode provar é o mecanismo (a altura da moldura segue `--altura-viva`, alimentada
por `visualViewport`), e é isso que este teste guarda. Que o iOS dispare o evento
continua sendo verificação de dispositivo.
"""
from __future__ import annotations

import re
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "ui"
HTML = (UI / "index.html").read_text(encoding="utf-8")
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


def bloco(consulta: str) -> str:
    """O corpo de uma @media, com as chaves internas equilibradas."""
    i = CSS.find("@media " + consulta)
    if i < 0:
        return ""
    j = CSS.index("{", i)
    nivel, k = 1, j + 1
    while nivel and k < len(CSS):
        if CSS[k] == "{":
            nivel += 1
        elif CSS[k] == "}":
            nivel -= 1
        k += 1
    return CSS[j + 1:k - 1]


def main() -> int:
    estreito = bloco("(max-width:760px)")
    dedo = bloco("(pointer:coarse)")

    print("— existe uma saída no celular —")
    checa("o breakpoint estreito existe", bool(estreito))
    # a regra INTEIRA, não uma string exata: `display:none` no meio de outras
    # propriedades esconde o trilho do mesmo jeito e passaria por um `not in`
    regra_trilho = re.search(r"\.trilho\{([^}]*)\}", estreito)
    checa("o trilho NÃO some (ele guarda a única saída da gaveta)",
          bool(regra_trilho) and "display:none" not in regra_trilho.group(1),
          "com o trilho oculto, nada fecha a gaveta nem troca o tema")
    checa("o trilho vira faixa horizontal", "flex-direction:row" in estreito)
    checa("a presença rola na horizontal",
          ".presenca{flex-direction:row" in estreito and "overflow-x:auto" in estreito)
    checa("a gaveta nasce fora da tela", "transform:translateX(100%)" in estreito)
    checa("a gaveta entra só quando aberta",
          '.moldura[data-gaveta="aberta"] .gaveta{transform:none}' in estreito)

    print("— três jeitos de fechar a gaveta com o polegar —")
    checa("existe o botão ✕ dentro da gaveta", 'id="gaveta-fecha"' in HTML)
    checa("o ✕ tem rótulo", re.search(r'id="gaveta-fecha"[^>]*aria-label=', HTML) is not None)
    checa("o ✕ fecha", "$('#gaveta-fecha').addEventListener('click'" in JS)
    checa("existe o véu atrás", 'id="veu-gaveta"' in HTML)
    checa("o véu fecha", "E.veu.addEventListener('click', ()=> abreGaveta(false))" in JS)
    checa("Escape fecha quando ela está por cima",
          "estreito() && E.moldura.dataset.gaveta === 'aberta'" in JS)
    m = re.search(r"\.veu-gaveta\{display:block;position:fixed;inset:0;z-index:(\d+)", estreito)
    checa("o véu fica ABAIXO da gaveta", bool(m) and int(m.group(1)) < 30,
          "com z-index acima, o véu engole os toques nas abas — medido")

    print("— a gaveta não nasce cobrindo a conversa —")
    checa("o estado inicial segue a largura da tela",
          "abreGaveta(!matchMedia('(max-width:760px)').matches)" in JS,
          "aberta por padrão no celular = 86% da tela coberta ao abrir o app")

    print("— o teclado virtual —")
    checa("a altura da moldura é variável",
          "height:var(--altura-viva,100dvh)" in CSS,
          "`dvh` responde às barras do navegador, não ao teclado")
    checa("quem alimenta a altura é o visualViewport",
          "visualViewport" in JS and "--altura-viva" in JS)
    checa("o app reage ao viewport mudar",
          "visualViewport.addEventListener('resize', alturaViva)" in JS)

    print("— alvo de dedo —")
    checa("existe o bloco de ponteiro grosso", bool(dedo))
    for alvo in (".pilula-cmd", ".aba", ".trilho-btn", ".msg-acao", ".enviar", ".selo"):
        regra = re.search(re.escape(alvo) + r"\{([^}]*)\}", dedo)
        tem = bool(regra) and ("min-height:44px" in regra.group(1)
                               or "height:44px" in regra.group(1)
                               or "min-height:48px" in regra.group(1))
        checa(f"{alvo} tem 44 px de alvo", tem, regra.group(1) if regra else "sem regra")
    checa("as ações da mensagem aparecem sem hover",
          ".msg-pe{opacity:1" in dedo,
          "no dedo não existe hover: escondê-las ali é escondê-las para sempre")

    print("— o que não cabe em uma linha de 390 px —")
    checa("o cabeçalho vira grade de duas linhas", ".cabeca{display:grid" in estreito)
    checa("a busca ocupa a linha inteira", "grid-column:1 / -1" in estreito,
          "espremida com o título, sobravam 98 px: só a lupa cabia")
    checa("o pé do compositor quebra", ".caixa-pe{flex-wrap:wrap" in estreito,
          "o botão Enviar cobria a pílula @nominar")
    checa("o atalho ⌘↵ some do botão", ".enviar kbd{display:none}" in estreito)
    checa("as abas param antes do ✕", ".gaveta-abas{padding-right:52px}" in estreito)

    print("— áreas seguras (notch e barra inferior) —")
    for lado in ("right", "bottom", "left"):
        checa(f"a moldura respeita a margem {lado}", f"env(safe-area-inset-{lado})" in CSS)
    checa("o trilho respeita o topo no celular",
          "env(safe-area-inset-top)" in estreito,
          "no celular ele é a primeira coisa sob o notch")
    checa("o HTML pede a tela inteira", 'viewport-fit=cover' in HTML)

    print("— o foco automático é de desktop —")
    checa("o campo só recebe foco no ponteiro fino",
          "if (matchMedia('(pointer:fine)').matches) E.texto.focus();" in JS,
          "no celular isso abriria o teclado sozinho e comeria metade da tela")

    print(f"\n{_ok} ✔ / {_falhou} ✗")
    return 1 if _falhou else 0


if __name__ == "__main__":
    raise SystemExit(main())
