#!/usr/bin/env python3
"""Contrato da aba IAs: a Janela das IAs mora na gaveta, não num aside.

Gate binário da migração do painel de sessões do groupchat para a sexta aba
da gaveta lateral direita, à direita do Mapa. Escrito ANTES do patch e
provado vermelho: cada checagem falha no código sem a migração e passa com
ela aplicada. Não sobe servidor nem Node — audita os três arquivos-fonte.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True

RAIZ = Path(__file__).resolve().parent.parent
UI = RAIZ / "ui"
HTML = (UI / "index.html").read_text(encoding="utf-8")
JS = (UI / "sala.js").read_text(encoding="utf-8")
CSS = (UI / "estilo.css").read_text(encoding="utf-8")

_ok = 0
_falhou = 0


def checa(nome: str, cond: bool, detalhe: str = "") -> None:
    """Imprime cada gate e acumula o veredito final."""
    global _ok, _falhou
    if cond:
        _ok += 1
        print(f"  ✔ {nome}")
    else:
        _falhou += 1
        sufixo = f" — {detalhe}" if detalhe else ""
        print(f"  ✗ {nome}{sufixo}")


def trecho(inicio: str, fim: str, fonte: str = JS) -> str:
    """Recorta uma unidade nomeada; ausência vira texto vazio e reprova."""
    a = fonte.find(inicio)
    if a < 0:
        return ""
    b = fonte.find(fim, a + len(inicio))
    return fonte[a:] if b < 0 else fonte[a:b]


def main() -> int:
    print("— a aba entra na tablist, à direita do Mapa —")
    aba = re.search(r'<button class="aba"[^>]*id="aba-ias"[^>]*>', HTML)
    checa("a aba IAs existe com o contrato ARIA da casa",
          bool(aba) and 'role="tab"' in aba.group(0) and
          'aria-controls="pnl-ias"' in aba.group(0) and
          'aria-selected="false"' in aba.group(0) and
          'tabindex="-1"' in aba.group(0) and
          'data-pnl="ias"' in aba.group(0),
          aba.group(0) if aba else "aba-ias ausente")
    checa("a aba IAs vem depois da aba Mapa na tablist",
          bool(aba) and 0 < HTML.find('id="aba-mapa"') < aba.start())

    print("— o painel segue a convenção da gaveta —")
    pnl = re.search(r'<section class="painel"[^>]*id="pnl-ias"[^>]*>', HTML)
    checa("o painel IAs é tabpanel rotulado pela aba e nasce oculto",
          bool(pnl) and 'role="tabpanel"' in pnl.group(0) and
          'aria-labelledby="aba-ias"' in pnl.group(0) and
          "hidden" in pnl.group(0),
          pnl.group(0) if pnl else "pnl-ias ausente")
    checa("o painel IAs vem depois do painel Mapa",
          bool(pnl) and 0 < HTML.find('id="pnl-mapa"') < pnl.start())

    print("— o miolo sai do aside e nasce dentro do painel —")
    instala = trecho("function instalaModosJanela", "instalaModosJanela();")
    checa("o template do groupchat não monta mais o aside lateral",
          "groupchat-lateral" not in instala and "<aside" not in instala)
    checa("o miolo é anexado ao painel da gaveta",
          "$('#pnl-ias')" in instala)
    checa("os ids vivos do miolo continuam nascendo no JavaScript",
          'id="groupchat-sessoes"' in instala and 'id="groupchat-fonte"' in instala)
    checa("a região viva do aviso de corte sobrevive byte a byte",
          'id="groupchat-corte" role="status" aria-live="polite"' in JS)
    checa("nenhuma referência ao aside sobrou no cliente",
          "groupchat-lateral" not in JS)

    print("— a telemetria vive nos três modos —")
    checa("existe um sincronizador único do poll",
          "function gcSincronizaPoll" in JS)
    sync = trecho("function gcSincronizaPoll", "\nfunction ")
    checa("o poll combina modo groupchat OU aba IAs com gaveta aberta",
          "dataset.janela" in sync and "aba-ias" in sync and
          "dataset.gaveta" in sync and "setInterval" in sync and
          "clearInterval" in sync,
          sync[:160])
    checa("o sincronizador é chamado pelas três bordas (modo, aba, gaveta)",
          JS.count("gcSincronizaPoll()") >= 3,
          f"{JS.count('gcSincronizaPoll()')} chamadas")

    print("— o groupchat vira coluna única e o painel ganha trilho —")
    grid = trecho(".groupchat{display:none", "}", CSS)
    checa("o grid do groupchat perde a coluna fixa de 310 px",
          "310px" not in grid and "minmax(0,1fr)" in grid, grid)
    checa("o aside lateral sai do CSS por inteiro",
          ".groupchat-lateral" not in CSS)
    trilho = trecho(".pnl-ias-trilho{", "}", CSS)
    checa("o trilho dos cartões rola na horizontal com snap",
          "overflow-x:auto" in trilho and "scroll-snap-type" in trilho,
          trilho)

    print(f"\n{_ok} ✔ / {_falhou} ✗")
    return 1 if _falhou else 0


if __name__ == "__main__":
    raise SystemExit(main())
