#!/usr/bin/env python3
"""Prova que os quatro painéis da gaveta mostram dado — e o dado certo.

Por que este teste existe (medido em 18/08 na sala real, 29 mensagens):
a aba **Decisões** estava condenada a nascer vazia. Ela procurava o COMANDO
`/decidi` no texto das mensagens, e ele aparece **0 vezes** — o comando nem
existe ainda (`pronto:false` na lista COMANDOS do `sala.js`). Enquanto isso a
sala tinha **8 marcações reais** em 2 mensagens (#26 e #29), pela regra que o
`bin/iachat-report` usa: o MARCADOR no começo da linha.

O defeito não era visível: um painel vazio parece "ninguém decidiu nada ainda".
Por isso o gate aqui é sobre a REGRA, não sobre a aparência — e ele compara a
regra da interface com a do `iachat-report`, que é a fonte canônica da casa.
Se as duas divergirem de novo, isto reprova antes de virar painel em branco.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SALA_JS = RAIZ / "ui" / "sala.js"
INDEX = RAIZ / "ui" / "index.html"
# Fonte canônica da regra, e ela vive no repositório IRMÃO — pode não estar presente.
# O caminho do autor (`~/Projetos/ia-chat`) não é o de ninguém mais: no runner do CI o
# irmão fica ao lado, no workspace. Procurar o relativo primeiro é o que faz este gate
# comparar de verdade em vez de se declarar indisponível na máquina de quem clonou.
REPORT = next(
    (c for c in (RAIZ.parent / "ia-chat" / "bin" / "iachat-report",
                 Path.home() / "Projetos" / "ia-chat" / "bin" / "iachat-report",
                 Path.home() / ".claude" / "scripts" / "ia-chat" / "iachat-report")
     if c.is_file()),
    RAIZ.parent / "ia-chat" / "bin" / "iachat-report",
)

_ok = 0
_falhou = 0


def checa(nome: str, cond: bool, detalhe: str = "") -> None:
    """Mantém o formato binário dos testes da casa."""
    global _ok, _falhou
    if cond:
        _ok += 1
        print(f"  ✔ {nome}")
    else:
        _falhou += 1
        print(f"  ✗ {nome}" + (f"\n      {detalhe}" if detalhe else ""))


def marcas_da_ui(js: str) -> list[str]:
    """Lê a lista MARCAS do sala.js — a fonte, não uma cópia deste teste."""
    m = re.search(r"const\s+MARCAS\s*=\s*\[([^\]]+)\]", js)
    if not m:
        return []
    return re.findall(r"'([A-Z]+)'", m.group(1))


def marcas_do_report(txt: str) -> list[str]:
    """Extrai o grupo de marcadores do regex canônico do iachat-report."""
    m = re.search(r"\((DECIDIDO(?:\|[A-Z]+)+)\)", txt)
    return m.group(1).split("|") if m else []


def regra_da_ui(js: str) -> re.Pattern | None:
    """Remonta em Python o MESMO padrão que o sala.js monta em JS.

    Extrair e executar a regra real é o ponto: um teste que redigitasse o regex
    provaria a cópia, não o que a interface roda.
    """
    marcas = marcas_da_ui(js)
    m = re.search(r"const\s+RE_MARCA\s*=\s*new RegExp\(\s*\n?\s*'([^']+)'\s*\+", js)
    if not marcas or not m:
        return None
    padrao = m.group(1).replace("\\\\", "\\") + "|".join(marcas)
    fim = re.search(r"MARCAS\.join\('\|'\)\s*\+\s*'([^']+)'", js)
    if not fim:
        return None
    padrao += fim.group(1).replace("\\\\", "\\")
    return re.compile(padrao, re.I)


def ramo_vazio(js: str, painel: str) -> str | None:
    """O texto que o painel escreve quando não há dado — None se fica em branco.

    A copy exata de cada empty state era a FORMA; o mecanismo é: no ramo de
    dados vazios, o painel escreve um texto visível que nomeia o vazio. Reescrever
    a frase é melhoria legítima; sumir com o ramo (ou escrever string vazia) é o
    defeito. A função é localizada pela referência ao `#id` do painel, e o ramo
    pelo `innerHTML` condicional — `cond ? '' : 'texto'` ou `cond ? 'texto' : ''`.
    """
    i = js.find(f"$('#{painel}')")
    if i < 0:
        return None
    ini = js.rfind("function ", 0, i)
    if ini < 0:
        return None
    fim = js.find("\nfunction ", i)
    corpo = js[ini:fim if fim > 0 else len(js)]
    for a, b in re.findall(r"innerHTML\s*=\s*[^?;]+?\?\s*'([^']*)'\s*:\s*'([^']*)'", corpo):
        texto = re.sub(r"<[^>]+>", "", a or b).strip()
        if texto:
            return texto
    return None


FIXTURE = """Abertura da mensagem, sem marcador nenhum.

DECIDIDO: o cursor não vira por-sessão.
**PENDENTE:** falta ligar a rota de reservas.
  BLOQUEIO: o instalador quebra no rename.
PERGUNTA: alguém mediu o custo disso?
Isto aqui é DECIDIDO no meio da linha e não deve contar.
decidido: minúsculo também é marcador legítimo.
"""


def main() -> int:
    print("\n▸ gaveta — os quatro painéis mostram dado, e o dado certo\n")

    js = SALA_JS.read_text(encoding="utf-8")
    html = INDEX.read_text(encoding="utf-8")

    # ── G1 · a regra morta não pode voltar ────────────────────────────────
    checa(
        "a aba Decisões não procura mais o comando /decidi (0 ocorrências na sala real)",
        not re.search(r"/\\?\(decidi\|concluir\)", js),
        "o regex do comando voltou ao sala.js — ele nunca casa com o que a sala escreve",
    )

    # ── G2 · a regra da UI é a mesma do iachat-report ─────────────────────
    ui = marcas_da_ui(js)
    checa("sala.js declara a lista de marcadores (MARCAS)", bool(ui), "MARCAS não encontrada")
    if REPORT.is_file():
        canon = marcas_do_report(REPORT.read_text(encoding="utf-8"))
        checa(
            "os marcadores da interface batem com os do iachat-report",
            bool(canon) and set(ui) == set(canon),
            f"interface={sorted(ui)}  iachat-report={sorted(canon)}",
        )
    else:
        # terceiro desfecho: não-consegui-olhar não vira aprovação silenciosa
        checa(
            "fonte canônica disponível para comparar os marcadores",
            False,
            f"{REPORT} não existe — a comparação com o iachat-report NÃO foi feita",
        )

    # ── G3 · a regra REAL, rodada contra uma fixture ──────────────────────
    regra = regra_da_ui(js)
    checa("a regra de marcação do sala.js pôde ser extraída e executada", regra is not None)
    if regra is not None:
        achados = [regra.match(l) for l in FIXTURE.split("\n")]
        marcados = [m.group(1).upper() for m in achados if m]
        checa(
            "encontra os quatro marcadores, inclusive com **negrito** e indentação",
            marcados == ["DECIDIDO", "PENDENTE", "BLOQUEIO", "PERGUNTA", "DECIDIDO"],
            f"achou {marcados}",
        )
        checa(
            "não confunde a palavra no meio da linha com um marcador",
            not regra.match("Isto aqui é DECIDIDO no meio da linha e não deve contar."),
        )
        corpo = regra.match("DECIDIDO: o cursor não vira por-sessão.")
        checa(
            "separa o corpo do marcador",
            bool(corpo) and corpo.group(2) == "o cursor não vira por-sessão.",
        )

    # ── G4 · painel vazio precisa DIZER que está vazio ────────────────────
    # A copy exata era a forma; o mecanismo é o ramo de vazio existir e escrever
    # texto visível. A frase pode ser reescrita (melhoria legítima); o que não
    # pode é o painel ficar em branco fingindo que "ninguém decidiu nada ainda".
    for painel in ("decisoes", "linha", "reservas"):
        texto = ramo_vazio(js, painel)
        checa(
            f"o painel #{painel} nomeia o próprio estado vazio",
            texto is not None and len(texto) >= 8,
            f"ramo de vazio achado: {texto!r} — sem texto o painel fica em branco",
        )
    checa(
        "o painel do fio explica que espera um clique",
        'id="fio-nota"' in html and "ver o fio" in html,
    )

    # ── G5 · o painel não promete o que não entrega ───────────────────────
    checa(
        "a aba Arquivos não promete reserva do ia-claim (ela mostra citação)",
        "Arquivos reservados" not in html,
        "o título voltou a prometer reserva; a fonte continua sendo o texto das mensagens",
    )
    checa(
        "a aba Arquivos diz de onde tira o que mostra",
        "derivado da sala" in html and "ia-claim" in html,
    )
    checa(
        "a nota de Decisões ensina o marcador que funciona",
        "DECIDIDO:" in html,
        "a nota precisa dizer como registrar — /decidi está pronto:false",
    )

    print(f"\n{_ok} ✔  {_falhou} ✗")
    return 1 if _falhou else 0


if __name__ == "__main__":
    raise SystemExit(main())
