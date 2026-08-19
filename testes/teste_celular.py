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
    regra_rodape = re.search(r"\.trilho-rodape\{([^}]*)\}", estreito)
    checa("o rodapé também vira faixa horizontal",
          bool(regra_rodape)
          and "flex-direction:row" in regra_rodape.group(1)
          and "width:auto" in regra_rodape.group(1))
    regra_sino = re.search(r"#btn-sino\{([^}]*)\}", estreito)
    checa("a separação vertical do sino zera no trilho deitado",
          bool(regra_sino) and "margin-block-end:0" in regra_sino.group(1))
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
    # O mecanismo tem duas metades: a moldura é dirigida pela variável que o
    # visualViewport alimenta (provado abaixo), e o fallback dela é uma unidade
    # de viewport DINÂMICA — `dvh`, `svh` ou `lvh` respondem às barras do
    # navegador; `vh` ou px não. O literal `100dvh` era a forma, não a regra.
    m_moldura = re.search(r"\.moldura\{([^}]*)\}", CSS)
    altura_moldura = ""
    if m_moldura:
        h = re.search(r"height:([^;}]+)", m_moldura.group(1))
        altura_moldura = h.group(1).strip() if h else ""
    checa("a moldura segue o viewport dinâmico (variável do visualViewport, "
          "fallback em dvh/svh/lvh)",
          re.search(r"var\(--altura-viva\s*,\s*100(?:dvh|svh|lvh)\)",
                    altura_moldura) is not None,
          f"moldura height: {altura_moldura or 'sem regra'} — sem a variável o "
          "teclado não ajusta; sem dvh/svh/lvh as barras não ajustam")
    checa("quem alimenta a altura é o visualViewport",
          "visualViewport" in JS and "--altura-viva" in JS)
    checa("o app reage ao viewport mudar",
          "visualViewport.addEventListener('resize', alturaViva)" in JS)

    print("— alvo de dedo —")
    checa("existe o bloco de ponteiro grosso", bool(dedo))
    # O contrato é o PISO de 44 px, não a lista `44|48`: `56px` é a HIG indo
    # além do mínimo — melhoria legítima que a lista reprovava. O que se mede
    # é o valor, qualquer que seja a propriedade de altura usada.
    for alvo in (".pilula-cmd", ".aba", ".trilho-btn", ".msg-acao", ".enviar", ".selo"):
        regra = re.search(re.escape(alvo) + r"\{([^}]*)\}", dedo)
        corpo = regra.group(1) if regra else ""
        alturas = [int(v) for v in re.findall(r"(?:min-)?height:\s*(\d+)px", corpo)]
        checa(f"{alvo} tem alvo de dedo ≥ 44 px",
              bool(regra) and any(v >= 44 for v in alturas),
              corpo or "sem regra")
    logo_estreito = re.search(r"#btn-enxame\{([^}]*)\}", estreito)
    corpo_logo_estreito = logo_estreito.group(1) if logo_estreito else ""
    largura_logo = re.search(r"\bwidth:\s*(\d+)px", corpo_logo_estreito)
    altura_logo = re.search(r"\bheight:\s*(\d+)px", corpo_logo_estreito)
    checa("o botão IASWARM cabe na faixa e mantém 44 px de altura",
          bool(largura_logo) and 44 <= int(largura_logo.group(1)) <= 56
          and bool(altura_logo) and int(altura_logo.group(1)) >= 44,
          corpo_logo_estreito or "sem regra")
    logo_dedo = re.search(r"#btn-enxame\{([^}]*)\}", dedo)
    corpo_logo_dedo = logo_dedo.group(1) if logo_dedo else ""
    minimos_logo = {
        nome: int(valor)
        for nome, valor in re.findall(r"(min-(?:width|height)):\s*(\d+)px", corpo_logo_dedo)
    }
    checa("o IASWARM tem alvo coarse específico de pelo menos 44 px",
          minimos_logo.get("min-width", 0) >= 44
          and minimos_logo.get("min-height", 0) >= 44,
          corpo_logo_dedo or "sem regra")
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
    # A colisão é o defeito; o `52px` era a fotografia dela. O que se mede: a
    # folga à direita das abas cobre a largura do ✕ — que no ponteiro grosso
    # cresce para 44px. ✕ maior com folga maior é melhoria (HIG), não defeito.
    regra_abas = re.search(r"\.gaveta-abas\{([^}]*)\}", estreito)
    folga = 0
    if regra_abas:
        mfolga = re.search(r"(?:padding|margin)-right:(\d+)px", regra_abas.group(1))
        folga = int(mfolga.group(1)) if mfolga else 0
    larguras_x = [int(v) for v in
                  re.findall(r"\.gaveta-fecha\{[^}]*?width:(\d+)px", CSS)]
    checa("as abas param antes do ✕ (folga ≥ largura dele)",
          bool(regra_abas) and bool(larguras_x) and folga >= max(larguras_x),
          f"folga {folga}px × ✕ {max(larguras_x) if larguras_x else '?'}px — "
          "sem folga suficiente o ✕ cobre a última aba")

    print("— áreas seguras (notch e barra inferior) —")
    for lado in ("right", "bottom", "left"):
        checa(f"a moldura respeita a margem {lado}", f"env(safe-area-inset-{lado})" in CSS)
    checa("o trilho respeita o topo no celular",
          "env(safe-area-inset-top)" in estreito,
          "no celular ele é a primeira coisa sob o notch")
    checa("o HTML pede a tela inteira", 'viewport-fit=cover' in HTML)

    print("— o foco automático é de desktop —")
    # O que importa é o MECANISMO: todo `E.texto.focus()` de arranque tem que estar
    # atrás da guarda `pointer:fine`. A versão anterior comparava a LINHA INTEIRA, e
    # reprovou quando alguém a melhorou — o `L3b` acrescentou "e não na janela do
    # enxame", que está certo e continua respeitando a guarda.
    #
    # Gate que cobra texto literal mede a memória de quem o escreveu, não o
    # comportamento: ele reprova melhoria e aprova qualquer reescrita que mantenha a
    # string. Terceira ocorrência disto em 18/08 (a lista fixa de assets no `teste_e2e`
    # e a mensagem de erro do zsh foram as outras).
    import re as _re

    arranques = [ln for ln in JS.splitlines()
                 if "E.texto.focus()" in ln and ln.lstrip().startswith("if ")]
    checa("existe a guarda de arranque do foco", bool(arranques),
          "sumiu o `if ... E.texto.focus()` de arranque")
    checa("o campo só recebe foco no ponteiro fino",
          all("matchMedia('(pointer:fine)')" in ln for ln in arranques),
          "no celular isso abriria o teclado sozinho e comeria metade da tela · "
          + " | ".join(l.strip()[:80] for l in arranques))

    print(f"\n{_ok} ✔ / {_falhou} ✗")
    return 1 if _falhou else 0


if __name__ == "__main__":
    raise SystemExit(main())
