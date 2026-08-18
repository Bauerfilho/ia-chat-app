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
    # Proporção, não contagem: a regra é TODA ação nascer com tabindex="-1" —
    # verdade para 3 ações ou para 7. O `== 3` anterior reprovava a quarta ação
    # legítima (copiar, abrir fio); um `>= 3` aprovaria a quarta nascida DENTRO
    # do Tab, que é o defeito real. O que se mede é o conjunto inteiro.
    acoes = re.findall(r'<[a-z]+[^>]*\bclass="[^"]*\bmsg-acao\b[^"]*"[^>]*>', JS)
    acoes += re.findall(r"className\s*=\s*'[^']*\bmsg-acao\b[^']*'[^;\n]*", JS)
    fora = [a for a in acoes
            if 'tabindex="-1"' in a or re.search(r"\btabIndex\s*=\s*-1", a)]
    checa("as ações da mensagem nascem fora do Tab (todas, em qualquer número)",
          bool(acoes) and len(fora) == len(acoes),
          f"{len(acoes) - len(fora)} de {len(acoes)} ações sem tabindex -1 — "
          "cada uma dentro do Tab é um pedágio a mais até o campo de escrita")
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
    # O NÚMERO de abas não é contrato de acessibilidade — o padrão é. A versão
    # anterior cobrava `== 4` e `== 3`, e reprovou quando a gaveta ganhou a aba
    # "Mapa": defeito nenhum, gate desatualizado. Quarta ocorrência desta classe em
    # 18/08 (lista fixa de assets, mensagem literal do zsh, linha literal do foco).
    # O que a norma exige é ROVING TABINDEX: exatamente uma parada de Tab, e todas as
    # outras fora dela — verdade para 4 abas ou para 40.
    checa("há abas na tablist", len(abas) >= 2, f"achei {len(abas)}")
    com_zero = [a for a in abas if 'tabindex="0"' in a]
    com_menos = [a for a in abas if 'tabindex="-1"' in a]
    checa("só uma aba é parada de Tab", len(com_zero) == 1, f"{len(com_zero)} com tabindex 0")
    checa("todas as outras saem do Tab", len(com_menos) == len(abas) - 1,
          f"{len(com_menos)} com tabindex -1, de {len(abas)} abas")
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

    print("— a gaveta tem dois botões, e o foco volta para quem abriu —")
    # Ele pediu o mesmo botão no canto superior. Dois controles para um painel só
    # criam duas armadilhas: estado que diverge entre eles, e foco que volta sempre
    # para o mesmo, mandando a pessoa para o outro canto da tela.
    botoes = re.findall(r'id="(btn-gaveta[\w-]*)"[^>]*aria-controls="gaveta"', HTML)
    checa("há mais de um botão controlando a gaveta", len(botoes) >= 2,
          f"achei {len(botoes)}: {botoes} — o pedido dele era ter também no topo")
    checa("o estado é escrito em TODOS eles de uma vez",
          re.search(r"botoesGaveta\(\)\.forEach\([^)]*aria-expanded", JS) is not None,
          "com um botão dizendo aberta e o outro fechada, o leitor de tela mente")
    # Medido pelo mecanismo, não pela forma: a restauração é CENTRALIZADA. Fixar o id
    # aqui reprovaria um terceiro botão legítimo amanhã; o que não pode é cada caminho
    # de fechamento escolher um botão por conta própria.
    fixos = re.findall(r"\$\('#btn-gaveta[\w-]*'\)\.focus\(\)", JS)
    checa("nenhum caminho de fechamento devolve o foco a um botão fixo",
          len(fixos) <= 1,
          f"{len(fixos)} chamadas com id cravado — quem abriu pelo topo é jogado para o rodapé")
    checa("o clique registra qual botão abriu",
          re.search(r"botoesGaveta\(\)\.forEach\(b => b\.addEventListener\('click'.*?= b", JS) is not None,
          "sem guardar quem abriu, não há para onde devolver o foco")

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
