#!/usr/bin/env python3
"""teste_origem_lan.py — a allowlist de Origin cobre TODAS as interfaces, não a primeira.

`--lan` imprime uma URL por interface física. A allowlist do anti-CSRF aceitava apenas
`_ip_local()` — que é o PRIMEIRO item da mesma lista que gerou as URLs.

Numa máquina com Wi-Fi **e** Ethernet, quem abrisse a segunda URL impressa veria a sala
carregar normalmente (o GET não checa Origin) e tomaria **403 ao enviar**. É o pior tipo
de defeito: o que parece funcionar. A pessoa lê a conversa inteira, escreve a resposta,
aperta enviar e o produto recusa sem explicar que o problema é por qual URL ela entrou.

Hoje esta máquina só tem `en0` com IP, então a armadilha está armada e nunca disparou —
razão pela qual um teste que dependesse do hardware presente não a pegaria. Este aqui
força a lista de interfaces, e por isso vale em qualquer máquina.

Achado do worker `i1-celular`, medido com `Origin: http://10.211.55.2:18931` → 403.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SERVIR = RAIZ / "ui" / "servir.py"
PORTA = 59418

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


print("teste_origem_lan")

# Duas interfaces FALSAS: é o cenário que esta máquina não tem e que quebra usuários
# reais. Injetadas por um wrapper que importa o servidor e troca `_ips_lan` antes de
# subir — sem tocar no produto.
FALSAS = ["10.0.0.7", "192.168.55.9"]
home = Path(tempfile.mkdtemp(prefix="origem-")) / "sala"

wrapper = home.parent / "sobe.py"
home.parent.mkdir(parents=True, exist_ok=True)
wrapper.write_text(f"""
import sys
sys.path.insert(0, {str(SERVIR.parent)!r})
sys.argv = ["servir.py", "--porta", "{PORTA}", "--escrever", "--papel", "bauer"]
import servir
servir._ips_lan = lambda: {FALSAS!r}
servir.main()
""", encoding="utf-8")

env = dict(os.environ, IACHAT_HOME=str(home))
CLI = RAIZ.parent / "ia-chat" / "bin" / "iachat"
subprocess.run([sys.executable, str(CLI), "status"],
               env=env, capture_output=True, stdin=subprocess.DEVNULL, timeout=60)
# `bauer` não nasce em `na_sala`: sem isto todo POST volta 400 ("não está na sala") e o
# teste mediria a checagem de sala em vez do Origin — verde ou vermelho pelo motivo
# errado, que é pior que vermelho. Usa o mesmo comando que o produto ensina ao usuário.
subprocess.run([sys.executable, str(CLI), "entrar", "bauer"],
               env=env, capture_output=True, stdin=subprocess.DEVNULL, timeout=60)

log = home.parent / "servidor.log"
proc = subprocess.Popen([sys.executable, str(wrapper)], env=env,
                        stdout=open(log, "w"), stderr=subprocess.STDOUT,
                        start_new_session=True)   # sem isto o SIGHUP do pai o mata

token = ""
for _ in range(40):
    time.sleep(0.25)
    if log.is_file():
        t = log.read_text(errors="replace")
        if "?t=" in t:
            token = t.split("?t=")[1].split()[0].strip()
            break

try:
    checa("o servidor subiu e imprimiu o token", bool(token),
          log.read_text(errors="replace")[:200] if log.is_file() else "sem log")

    def posta(origem: str) -> int:
        req = urllib.request.Request(
            f"http://127.0.0.1:{PORTA}/api/post?t={token}",
            data=json.dumps({"texto": f"origem {origem}", "para": ["claude"]}).encode(),
            headers={"Content-Type": "application/json", "Origin": origem},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code
        except OSError:
            return 0

    if token:
        # A PRIMEIRA interface sempre funcionou — é o que o código antigo cobria.
        checa("1ª interface física: aceita",
              posta(f"http://{FALSAS[0]}:{PORTA}") == 200, f"código {posta(f'http://{FALSAS[0]}:{PORTA}')}")
        # A SEGUNDA é a regressão. Com o código antigo isto dava 403.
        checa("2ª interface física: aceita (era 403 — o defeito)",
              posta(f"http://{FALSAS[1]}:{PORTA}") == 200,
              f"código {posta(f'http://{FALSAS[1]}:{PORTA}')} — a allowlist voltou a cobrir só a primeira")
        checa("loopback: aceita", posta(f"http://127.0.0.1:{PORTA}") == 200)
        # E o anti-CSRF continua fechado: alargar a allowlist não pode virar abrir a porta.
        checa("origem alheia: RECUSA (o anti-CSRF continua de pé)",
              posta("http://evil.example.com") == 403,
              f"código {posta('http://evil.example.com')} — a allowlist ficou permissiva demais")
        checa("IP fora da lista: RECUSA",
              posta(f"http://10.9.9.9:{PORTA}") == 403)
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    shutil.rmtree(home.parent, ignore_errors=True)

print(f"\n{_ok} ✔  {_falhou} ✗")
sys.exit(1 if _falhou else 0)
