#!/usr/bin/env python3
"""Os invariantes de acessibilidade que, se caírem, quebram o teclado.

O comportamento foi medido no navegador (Tab real, setas reais, `emulateMedia`
para movimento reduzido, MutationObserver na região viva) — os números estão no
`ui/DESIGN.md`. Este arquivo NÃO repete a medição: ele trava as condições sem as
quais aquele comportamento deixa de existir, e roda em qualquer máquina, sem
navegador, junto com o resto da bateria.

O que cada bloco guarda está dito no nome do caso. Onde o teste não consegue
provar comportamento — anúncio de leitor de tela, por exemplo — ele não finge:
guarda a condição estrutural e o `DESIGN.md` registra o que foi medido à mão.
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


def main() -> int:
    print("— a conversa é UMA parada de Tab —")
    fio = re.search(r'<div class="sala-fio"[^>]*>', HTML)
    checa("o log existe e é focável", bool(fio) and 'tabindex="0"' in fio.group(0),
          "sem tabindex no #fio, as setas não têm onde acontecer")
    checa("o log continua sendo região viva",
          bool(fio) and 'role="log"' in fio.group(0) and 'aria-live="polite"' in fio.group(0))
    checa("as ações da mensagem nascem fora do Tab",
          JS.count('class="msg-acao" tabindex="-1"') == 3,
          "três botões por mensagem × N mensagens era o pedágio até o campo de escrita")
    checa("cada mensagem tem id (alvo do aria-activedescendant)",
          "art.id = 'msg-' + m.n" in JS)
    checa("o log aponta a mensagem escolhida",
          "aria-activedescendant" in JS and "E.fio.setAttribute('aria-activedescendant'" in JS)
    for tecla in ("ArrowDown", "ArrowUp", "PageDown", "PageUp", "Home", "End"):
        checa(f"o log responde a {tecla}", tecla in JS)
    checa("as ações da mensagem ativa voltam ao Tab",
          "b.tabIndex = ativa ? 0 : -1" in JS,
          "sem isto as ações ficariam inalcançáveis por teclado")

    print("— as abas seguem o padrão ARIA de tablist —")
    abas = re.findall(r'<button class="aba"[^>]*>', HTML)
    checa("são quatro abas", len(abas) == 4, f"achei {len(abas)}")
    com_zero = [a for a in abas if 'tabindex="0"' in a]
    com_menos = [a for a in abas if 'tabindex="-1"' in a]
    checa("só uma aba é parada de Tab", len(com_zero) == 1, f"{len(com_zero)} com tabindex 0")
    checa("as outras três saem do Tab", len(com_menos) == 3, f"{len(com_menos)} com tabindex -1")
    checa("a aba de Tab é a selecionada",
          bool(com_zero) and 'aria-selected="true"' in com_zero[0])
    checa("trocar de aba move o tabindex junto",
          "a.tabIndex = ativo ? 0 : -1" in JS,
          "senão o roving quebra na primeira troca")
    for tecla in ("ArrowRight", "ArrowLeft", "Home", "End"):
        checa(f"as abas respondem a {tecla}", f"'{tecla}'" in JS)

    print("— a paleta de comandos fala com o leitor de tela —")
    checa("as opções têm id", "id=\"cmd-${c.cmd.slice(1)}\"" in JS)
    checa("as opções ficam fora do Tab", 'role="option" tabindex="-1"' in JS,
          "o foco fica no campo; a opção é apontada, não focada")
    checa("o campo vira combobox enquanto a paleta existe",
          "setAttribute('role', 'combobox')" in JS and "setAttribute('aria-expanded', 'true')" in JS)
    checa("o campo aponta a opção ativa",
          "E.texto.setAttribute('aria-activedescendant', sel.id)" in JS)
    checa("fechar a paleta limpa TODOS os atributos",
          all(f"removeAttribute('{a}')" in JS
              for a in ("role", "aria-expanded", "aria-controls", "aria-activedescendant")),
          "quem escreve na sala não deve ouvir 'caixa combinada' o tempo todo")
    checa("nada fecha a paleta por fora da função",
          JS.count("E.paleta.hidden = true") == 1,
          "um caminho que esqueça de limpar deixa o campo mentindo para o leitor")

    print("— a região viva não repete a sala inteira —")
    checa("recriar a lista acontece sob aria-busy",
          "setAttribute('aria-busy', 'true')" in JS and "setAttribute('aria-busy', 'false')" in JS,
          "filtrar a busca recria os nós dentro da região viva")
    checa("mensagem nova é anexada, não recriada",
          "function anexaMsg" in JS and "E.fio.append(noMsg(m))" in JS)
    checa("o stream usa o caminho que anexa", "anexaMsg(m);" in JS)

    print("— foco visível —")
    checa("existe regra global de foco visível",
          re.search(r":focus-visible\{outline:2px solid", CSS) is not None)
    m = re.search(r"#busca:focus-visible\{[^}]*box-shadow:0 0 0 3px rgba\(176,141,63,\.(\d+)\)", CSS)
    checa("a busca substitui o outline por um anel com contraste próprio",
          bool(m) and int(m.group(1)) >= 40,
          "a 10% o anel existia no código e não existia no olho (WCAG 2.4.11)")
    checa("o campo de texto se anuncia pelo pai",
          ".caixa:focus-within{border-color:var(--ouro)" in CSS)
    checa("a mensagem escolhida tem realce próprio",
          ".sala-fio:focus-visible .msg--ativa" in CSS,
          "o foco fica no log; sem realce na mensagem, o teclado anda às cegas")

    print("— movimento —")
    bloco = re.search(r"@media \(prefers-reduced-motion:reduce\)\{(.*?)\n\}", CSS, re.S)
    checa("existe bloco de movimento reduzido", bool(bloco))
    if bloco:
        corpo = bloco.group(1)
        checa("as animações caem para instantâneas", "animation-duration:.01ms !important" in corpo)
        checa("o campo de luz e a aurora param",
              ".campo-mesh,.campo-aurora{animation:none}" in corpo,
              "são as duas que respiram sozinhas na tela")

    print("— rótulos —")
    for bid, nome in (("btn-tema", "alternar tema"), ("btn-gaveta", "abrir o painel")):
        b = re.search(rf'<button[^>]*id="{bid}"[^>]*>', HTML)
        checa(f"o botão de {nome} tem aria-label", bool(b) and "aria-label=" in b.group(0))
    checa("todo glifo decorativo é escondido do leitor",
          HTML.count('aria-hidden="true"') >= 8)
    checa("os campos têm rótulo", HTML.count('class="oculto-visual" for=') >= 2)

    print(f"\n{_ok} ✔ / {_falhou} ✗")
    return 1 if _falhou else 0


if __name__ == "__main__":
    raise SystemExit(main())
