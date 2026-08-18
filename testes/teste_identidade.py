#!/usr/bin/env python3
"""teste_identidade.py — o app posta com o nome de quem está usando, não com o do autor.

`papel` era `os.environ.get("IACHAT_PAPEL", "bauer")`. Quem clonasse o repositório e
abrisse o app postaria como **bauer** na própria sala — a identidade de um estranho no
lugar da sua. Não quebra nada, e é justamente por isso que passa: ninguém procura uma
variável de ambiente para consertar algo que não sabia que estava errado.

Trocar cru por `$USER` conserta o estranho e quebra o dono: na máquina dele o usuário
do sistema é `bauervieiracesarfilhovieira` e a sala inteira o conhece como `bauer`.

Por isso a regra pergunta ao disco em vez de adivinhar, e quem JÁ está na sala tem
precedência. Este gate trava os quatro cenários — inclusive o ambíguo, onde a resposta
certa é não escolher. Achado do worker `codex` na missão m2.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
LANCADOR = RAIZ / "ia-chat.app" / "Contents" / "Resources" / "lancador.py"

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


print("teste_identidade")

if not LANCADOR.is_file():
    print(f"  ⊘ {LANCADOR} ausente — bundle não montado")
    sys.exit(0)

# O nome cravado não pode voltar por descuido: é o defeito original, e ele é invisível
# em uso (o app funciona, só assina errado).
fonte = LANCADOR.read_text(encoding="utf-8")
checa('sem `"bauer"` cravado como padrão', 'get("IACHAT_PAPEL", "bauer")' not in fonte,
      "o nome do autor voltou a ser o padrão de quem instala")

spec = importlib.util.spec_from_loader(
    "lanc", importlib.machinery.SourceFileLoader("lanc", str(LANCADOR)))
lanc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lanc)


def papel_com(na_sala, user, papel_env=None):
    d = Path(tempfile.mkdtemp(prefix="ident-"))
    (d / "config.json").write_text(json.dumps({"na_sala": na_sala}), encoding="utf-8")
    velho = dict(os.environ)
    try:
        os.environ["IACHAT_HOME"] = str(d)
        os.environ["USER"] = user
        os.environ.pop("IACHAT_PAPEL", None)
        if papel_env:
            os.environ["IACHAT_PAPEL"] = papel_env
        return lanc.papel_padrao()
    finally:
        os.environ.clear()
        os.environ.update(velho)
        shutil.rmtree(d, ignore_errors=True)


# 1. O DONO. A sala o conhece por um apelido que não é o usuário do sistema — e é o
# apelido que vale, senão o conserto do estranho quebraria quem já usa.
r = papel_com(["claude", "codex", "kimi", "bauer"], "bauervieiracesarfilhovieira")
checa("dono: usa o apelido que está na sala", r == "bauer", f"devolveu {r!r}")

# 2. O ESTRANHO, sala recém-criada (só as IAs). É o caso que o defeito estragava.
r = papel_com(["claude", "codex", "kimi"], "maria")
checa("estranho: usa o próprio nome, não o do autor", r == "maria", f"devolveu {r!r}")

# 3. Quem já entrou na sala com o próprio nome.
r = papel_com(["claude", "maria"], "maria")
checa("já na sala: usa o próprio nome", r == "maria", f"devolveu {r!r}")

# 4. AMBÍGUO — dois humanos. A resposta certa é não escolher: chutar qual dos dois é
# "o dono" poria uma pessoa a assinar pela outra, que é o defeito original de novo,
# só que entre usuários reais.
r = papel_com(["claude", "bauer", "joao"], "maria")
checa("ambíguo: não adivinha, cai no próprio usuário", r == "maria", f"devolveu {r!r}")

# 5. A variável explícita manda em tudo — mas a precedência vive no CHAMADOR
# (`os.environ.get("IACHAT_PAPEL") or papel_padrao()`), não dentro da função. A primeira
# versão deste caso chamava `papel_padrao()` direto com a env posta e cobrava dela um
# comportamento que nunca foi dela: o teste falhou por medir o lugar errado, e o produto
# estava certo. Aqui a checagem é sobre a expressão, que é onde a regra mora.
checa("`IACHAT_PAPEL` tem precedência sobre o padrão",
      'os.environ.get("IACHAT_PAPEL") or papel_padrao()' in fonte,
      "o chamador deixou de consultar a variável antes de calcular o padrão")

# 6. Sem sala legível, um nome que existe é melhor que um herdado.
velho = dict(os.environ)
try:
    os.environ["IACHAT_HOME"] = "/caminho/que/nao/existe"
    os.environ["USER"] = "maria"
    os.environ.pop("IACHAT_PAPEL", None)
    r = lanc.papel_padrao()
finally:
    os.environ.clear()
    os.environ.update(velho)
checa("sem sala: cai no usuário do sistema", r == "maria", f"devolveu {r!r}")

print(f"\n{_ok} ✔  {_falhou} ✗")
sys.exit(1 if _falhou else 0)
