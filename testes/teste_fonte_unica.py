#!/usr/bin/env python3
"""teste_fonte_unica.py — a interface tem UM dono, e ele é `ui/`.

Havia cópias de `index.html`, `estilo.css` e `sala.js` na raiz do repositório, ao lado
das de `ui/`. Ninguém as servia: `montar.sh` copia de `ui/`, o `servir.py` serve do
diretório dele (que é `ui/`), e todos os testes leem `ui/`. Eram órfãs.

Órfã idêntica é desperdício; órfã DIVERGENTE é armadilha. E a `sala.js` da raiz já tinha
divergido — parou num commit de 04:30 enquanto a de `ui/` seguiu até 05:20. Quem clonasse
o repo, desse `ls`, visse `sala.js` na raiz (que aparece antes de `ui/` na ordem
alfabética) e a editasse, veria a mudança **não acontecer**. Sem erro, sem aviso: o
arquivo salva, o app ignora.

Esse é o pior desfecho para quem chega — não é um bug que se depura, é um chão que não
existe. Achado pelo worker `codex` na missão m2, ao responder "o que um desenvolvedor
que nunca viu isto abandonaria no meio?".

O gate impede o retorno: se um arquivo de interface reaparecer na raiz, fica vermelho.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
INTERFACE = ("index.html", "estilo.css", "sala.js", "servir.py")

_ok = 0
_falhou = 0


def checa(nome: str, cond: bool, detalhe: str = "") -> None:
    global _ok, _falhou
    if cond:
        _ok += 1
        print(f"  ✔ {nome}")
    else:
        _falhou += 1
        print(f"  ✗ {nome}" + (f"\n      {detalhe}" if detalhe else ""))


print("teste_fonte_unica")

# ── 1. nada de interface solto na raiz ──────────────────────────────────────
soltos = [f for f in INTERFACE if (RAIZ / f).is_file()]
checa("nenhum arquivo de interface na raiz", not soltos,
      f"{soltos} — a fonte é `ui/`. Cópia na raiz não é servida por ninguém e "
      f"diverge em silêncio; quem editar ali perde o trabalho sem receber erro.")

# ── 2. a fonte existe ───────────────────────────────────────────────────────
faltando = [f for f in INTERFACE if not (RAIZ / "ui" / f).is_file()]
checa("`ui/` tem a interface completa", not faltando, f"faltam {faltando}")

# ── 3. o bundle é cópia FIEL da fonte ───────────────────────────────────────
# Se divergirem, o app roda uma interface que ninguém está editando — a mesma classe
# de defeito, só que entre repo e bundle.
res = RAIZ / "ia-chat.app" / "Contents" / "Resources" / "ui"
if res.is_dir():
    divergem = []
    for f in INTERFACE:
        a, b = RAIZ / "ui" / f, res / f
        if a.is_file() and b.is_file() and a.read_bytes() != b.read_bytes():
            divergem.append(f)
    checa("o bundle bate com `ui/`", not divergem,
          f"{divergem} — rode `./montar.sh`. O app está servindo uma versão que não é "
          f"a que você edita.")
else:
    checa("bundle presente", False, f"não achei {res}")

# ── 4. o git não rastreia duplicata ─────────────────────────────────────────
# O arquivo pode ter sido removido do disco e continuar no índice, ou voltar por um
# merge. O que conta para quem clona é o que o git entrega.
r = subprocess.run(["git", "-C", str(RAIZ), "ls-files"], capture_output=True, text=True)
rastreados = [ln for ln in r.stdout.splitlines() if ln in INTERFACE]
checa("o git não entrega interface na raiz", not rastreados,
      f"{rastreados} — quem clonar recebe a armadilha mesmo que o disco daqui esteja limpo")

print(f"\n{_ok} ✔  {_falhou} ✗")
sys.exit(1 if _falhou else 0)
