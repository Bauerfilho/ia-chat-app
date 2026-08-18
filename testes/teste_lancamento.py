#!/usr/bin/env python3
"""teste_lancamento.py — o app precisa ABRIR no duplo clique.

POR QUE ESTE TESTE EXISTE, e por que ele é o primeiro deste repositório.

Em 18/08 uma auditoria externa achou que **o app não abria**. A causa não estava no
lançador, nem no bundle, nem no `Info.plist`: estava em três `print()` sem `flush=True`.

O mecanismo, que é o mais traiçoeiro que este projeto encontrou até agora:

  1. o lançador sobe o servidor com stdout redirecionado para um log;
  2. e descobre o **token** lendo esse log;
  3. com stdout num arquivo, o Python usa buffer de bloco (131.072 B nesta máquina);
  4. as ~150 bytes da URL nunca enchem o buffer, e o servidor não imprime mais nada;
  5. o log fica **vazio para sempre**;
  6. o lançador não acha o token, bate em `/api/estado` sem ele, toma **401**;
  7. conclui "o servidor não respondeu" e mata o app aos 20 s — com um alerta
     **enganoso**, porque o servidor estava vivo e respondendo perfeitamente.

Nada disso aparece quando se roda o servidor no terminal: ali o stdout é linha-a-linha e
o token sai na hora. O defeito só existe no caminho que o usuário final usa.

Este teste roda pelo caminho do usuário final: **stdout num arquivo**, como o lançador
faz. É a única forma de vê-lo.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SERVIDORES = [
    RAIZ / "ui" / "servir.py",
    RAIZ / "ia-chat.app" / "Contents" / "Resources" / "servidor.py",
]
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


print("teste_lancamento")

for i, servidor in enumerate(SERVIDORES):
    nome = servidor.name
    if not servidor.is_file():
        checa(f"{nome}: presente", False, f"não achei {servidor}")
        continue

    porta = PORTA + i
    tmp = Path(tempfile.mkdtemp(prefix="lanc-"))
    log = tmp / "servidor.log"

    # O cano do lançador, reproduzido: stdout NUM ARQUIVO e SEM `python3 -u`.
    # Rodar com `-u` aqui esconderia exatamente o defeito que este teste procura.
    with log.open("wb") as saida:
        proc = subprocess.Popen(
            [sys.executable, str(servidor), "--porta", str(porta),
             "--escrever", "--papel", "bauer"],
            stdout=saida, stderr=subprocess.STDOUT,
        )
    try:
        token = ""
        for _ in range(40):                     # 8 s — o lançador real espera 20
            time.sleep(0.2)
            m = re.search(r"\?t=([A-Za-z0-9_-]+)", log.read_text(errors="replace"))
            if m:
                token = m.group(1)
                break

        checa(f"{nome}: o token chega ao log (é assim que o lançador o descobre)",
              bool(token),
              f"log com {log.stat().st_size} B e sem token — "
              f"falta `flush=True` no print da URL. O app morre aos 20 s "
              f"dizendo 'o servidor não respondeu', e ele estava respondendo.")

        if token:
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{porta}/api/estado?t={token}", timeout=5) as r:
                    ok = r.status == 200
            except Exception as e:                     # noqa: BLE001
                ok = False
                print(f"      ({e})")
            checa(f"{nome}: e o servidor responde com esse token", ok)

            # O outro lado: sem token tem que NEGAR. Se respondesse 200 sem token, o
            # lançador funcionaria por acidente — e a sala ficaria aberta na rede.
            codigo = 0
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{porta}/api/estado", timeout=5) as r:
                    codigo = r.status
            except urllib.error.HTTPError as e:
                codigo = e.code
            except Exception:                          # noqa: BLE001
                codigo = -1
            checa(f"{nome}: sem token, NEGA (401)", codigo == 401, f"devolveu {codigo}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)

# ── checagens de FONTE: cada um dos dois defeitos, isolado ──────────────────
# O runtime acima pega o SINTOMA (token não chega ao log). Estes dois pegam a
# CAUSA. Se alguém tirar o `flush=True` ou o `?t=` do probe, fica vermelho
# mesmo que o runtime ainda passe por acidente (python -u, tty, etc.).
SERVIR_FONTE = RAIZ / "ui" / "servir.py"
LANCADOR_FONTE = RAIZ / "ia-chat.app" / "Contents" / "Resources" / "lancador.py"

fonte_servir = SERVIR_FONTE.read_text(encoding="utf-8") if SERVIR_FONTE.is_file() else ""
checa("fonte servir.py: o arquivo existe", bool(fonte_servir), str(SERVIR_FONTE))
prints_http = re.findall(r"print\((?:[^()]|\([^()]*\))*\)", fonte_servir)
prints_url = [p for p in prints_http if "http://" in p]
checa("fonte servir.py: existe print da URL", bool(prints_url),
      "sem print da URL o lançador não tem o que ler no log")
for i, p in enumerate(prints_url, 1):
    checa(f"fonte servir.py: print da URL #{i} tem flush=True",
          "flush=True" in p,
          "print sem flush — o token fica preso no buffer de bloco e o app "
          f"morre aos 20 s:\n      {p[:180]}")
# A linha da sala também é lida pelo humano no log do app.
prints_sala = [p for p in prints_http if "sala:" in p]
for i, p in enumerate(prints_sala, 1):
    checa(f"fonte servir.py: print da sala #{i} tem flush=True",
          "flush=True" in p, p[:180])

fonte_lanc = LANCADOR_FONTE.read_text(encoding="utf-8") if LANCADOR_FONTE.is_file() else ""
checa("fonte lancador.py: o arquivo existe", bool(fonte_lanc), str(LANCADOR_FONTE))
bloco = re.search(r"def responde\b.*?(?=\ndef |\Z)", fonte_lanc, flags=re.S)
checa("fonte lancador.py: existe responde()", bloco is not None)
if bloco:
    corpo = bloco.group(0)
    checa("fonte lancador.py: responde() recebe o token",
          re.search(r"def responde\([^)]*\btoken\b", corpo) is not None,
          "responde() sem parâmetro token — o probe não tem como autenticar")
    checa("fonte lancador.py: o probe de /api/estado anexa ?t=",
          "/api/estado" in corpo and "?t=" in corpo,
          "responde() bate em /api/estado sem o token — 401 eterno, "
          "alerta 'o servidor não respondeu' com o servidor vivo")
checa("fonte lancador.py: espera_pronto sonda COM o token do log",
      "responde(porta, token" in fonte_lanc,
      "espera_pronto() não passa o token ao probe")

print(f"\n{_ok} ✔  {_falhou} ✗")
sys.exit(1 if _falhou else 0)
