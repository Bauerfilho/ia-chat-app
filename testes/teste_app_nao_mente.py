#!/usr/bin/env python3
"""teste_app_nao_mente.py — o que o app mostra tem que ser verdade.

Três defeitos da mesma família, achados pelo worker `j1-app-paralelo`: o núcleo resolveu
alguma coisa, e o app tomou um atalho paralelo que **não erra — mente**. Erro o usuário
percebe; mentira ele acredita e age em cima.

1. **"ninguém" virava "todas".** Numa sala de 3+, postar sem `@` não chama ninguém. O
   CLI diz `→ ninguém` e avisa no stderr. A UI pintava **todas**. Quem lê o histórico
   jura que a sala inteira foi convocada, e então decide, cobra e acusa atraso em cima
   de uma mensagem que não tocou sino nenhum.

2. **O histórico sumia depois da rotação.** `desde=0` lia só o arquivo ATIVO. A rotação
   é automática quando o ativo estoura o teto — então o app abria parecendo uma sala
   nova. As mensagens não foram apagadas: o CLI ainda as acha, porque `_msgs_desde`
   abre os recortes. Quem só tem o app conclui que o começo evaporou.

3. **Os avisos do núcleo eram engolidos.** `core.post` devolve `avisos` junto do
   sucesso ("postou, MAS ninguém foi chamado"). O CLI imprime cada um; a UI olhava só
   `d.erro`. Sucesso silencioso sobre uma entrega pela metade.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CLI = RAIZ.parent / "ia-chat" / "bin" / "iachat"
JS = (RAIZ / "ui" / "sala.js").read_text(encoding="utf-8")
PORTA = 59907

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


print("teste_app_nao_mente")

# ── 1. lista vazia é "ninguém" ──────────────────────────────────────────────
# Lido do fonte, como os outros gates de UI da casa fazem (`teste_cookie.py`,
# `teste_comandos_ui.py`): sem runtime de JS aqui, e subir um só para uma função pura
# custaria mais que o que protege.
import re

m = re.search(r"if \(!l\.length\) return \{([^}]*)\}", JS)
checa("`paraLegivel` trata lista vazia", m is not None, "não achei o ramo de lista vazia")
if m:
    ramo = m.group(1)
    checa("vazio NÃO vira 'todas'", "todas" not in ramo,
          f"a UI volta a dizer que a sala inteira foi chamada: {ramo!r}")
    checa("vazio diz 'ninguém'", "ningu" in ramo, ramo)
    checa("vazio não lista a sala como destino", "S.naSala" not in ramo,
          f"lista vazia com destinatários preenchidos: {ramo!r}")

# ── 3. os avisos chegam à tela ──────────────────────────────────────────────
checa("o envio repassa `avisos` do núcleo", "d.avisos" in JS,
      "a UI voltou a olhar só `d.erro` e engolir os avisos de sucesso parcial")

# ── 2. o histórico atravessa a rotação ──────────────────────────────────────
home = Path(tempfile.mkdtemp(prefix="mente-")) / "sala"
# O `servir.py` procura o núcleo em `~/Projetos/ia-chat/bin` — caminho FIXO,
# baseado em HOME. Numa máquina onde o repositório não mora ali (o runner do CI
# põe o irmão no workspace), o import só encontra pelo PYTHONPATH. É o que o
# `lancador.py` faz em produção; o teste não fazia, e por isso o servidor subia
# sem núcleo e devolvia 0 mensagens — três casos vermelhos pelo mesmo motivo.
NUCLEO = RAIZ.parent / "ia-chat" / "bin"
env = dict(os.environ, IACHAT_HOME=str(home),
           PYTHONPATH=str(NUCLEO) + os.pathsep + os.environ.get("PYTHONPATH", ""))
subprocess.run([sys.executable, str(CLI), "status"], env=env,
               capture_output=True, stdin=subprocess.DEVNULL, timeout=60)

cfg = home / "config.json"
c = json.loads(cfg.read_text(encoding="utf-8"))
c["teto_bytes"] = 2000                      # teto baixo: força a rotação depressa
c["na_sala"] = ["claude", "codex", "kimi", "bauer"]
cfg.write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")


def cli(*args):
    return subprocess.run([sys.executable, str(CLI), *args], env=env,
                          capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=60)


for i in range(1, 8):
    cli("post", "--de", "codex", "--para", "claude",
        f"mensagem numero {i} com corpo suficiente para encher o arquivo")
cli("post", "--de", "bauer", "ola sem nominacao")     # a que não chama ninguém
cli("rotate", "--forcar")
cli("post", "--de", "codex", "--para", "claude", "depois da rotacao")

recortes = list((home / "arquivo").glob("*.md")) if (home / "arquivo").is_dir() else []
checa("a rotação aconteceu (senão o teste não prova nada)", len(recortes) >= 1,
      f"{len(recortes)} recortes — sem rotação este caso é vazio")

proc = subprocess.Popen(
    [sys.executable, str(RAIZ / "ui" / "servir.py"), "--porta", str(PORTA)],
    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    start_new_session=True)
try:
    msgs = []
    for _ in range(40):
        time.sleep(0.25)
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{PORTA}/api/sala?desde=0", timeout=4) as r:
                msgs = json.loads(r.read()).get("msgs", [])
                break
        except OSError:
            continue

    checa("o app entrega o histórico INTEIRO após rotação", len(msgs) >= 9,
          f"{len(msgs)} mensagens — o começo da sala sumiu do app; o CLI ainda o acha")
    checa("inclusive a #1, que está no recorte",
          any(x.get("n") == 1 for x in msgs),
          f"primeira entregue: #{msgs[0]['n'] if msgs else '-'}")
    # A mensagem sem destinatário chega com `para` vazio — é o dado que a UI pintava
    # como "todas". Se o servidor a entregasse já preenchida, o conserto do JS seria inútil.
    sem = [x for x in msgs if not x.get("para")]
    checa("a mensagem sem destinatário chega com `para` vazio", len(sem) >= 1,
          "o servidor está preenchendo destinatário que não existe")
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    shutil.rmtree(home.parent, ignore_errors=True)

print(f"\n{_ok} ✔  {_falhou} ✗")
sys.exit(1 if _falhou else 0)
