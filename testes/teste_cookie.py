#!/usr/bin/env python3
"""O cookie que carrega o token não pode ser legível por JavaScript.

Por que isto é um teste e não um comentário: o token é a credencial de escrita
na sala. Hoje não há XSS na interface — o `sala.js` não usa `innerHTML` com
texto cru sem escapar, e o corpo das mensagens passa por `esc()`. Mas a defesa
não existe para o código de hoje: existe para o dia em que alguém escrever uma
linha errada. Com `HttpOnly`, um XSS futuro não consegue ler o token; sem ele,
consegue — e o token dá escrita na sala com o nome do dono.

O custo é zero, e este teste prova que é zero: o JS **nunca** lê `document.cookie`.
Quem manda o token pelo cookie é o navegador, sozinho, em cada requisição.
"""
from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CORE_BIN = RAIZ.parent / "ia-chat" / "bin"
SERVIR = RAIZ / "ui" / "servir.py"
SALA_JS = RAIZ / "ui" / "sala.js"

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


def porta_livre(inicio: int = 59870) -> int:
    for p in range(inicio, inicio + 60):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise RuntimeError("sem porta livre")


def sobe(home: Path, porta: int) -> tuple[subprocess.Popen[str], str]:
    """Sobe o servidor com escrita: `--escrever` já obriga o token, e é o token
    que faz o cookie existir."""
    env = dict(os.environ, IACHAT_HOME=str(home), PYTHONPATH=str(CORE_BIN))
    proc = subprocess.Popen(
        [sys.executable, str(SERVIR), "--porta", str(porta), "--escrever"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env,
    )
    token = ""
    limite = time.time() + 15
    while time.time() < limite:
        linha = proc.stdout.readline() if proc.stdout else ""
        if not linha and proc.poll() is not None:
            break
        m = re.search(r"[?&]t=([A-Za-z0-9_-]+)", linha)
        if m:
            token = m.group(1)
            break
    return proc, token


def cabecalhos(porta: int, rota: str) -> tuple[int, dict[str, str]]:
    url = f"http://127.0.0.1:{porta}{rota}"
    try:
        with urllib.request.urlopen(url, timeout=6) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}


def main() -> int:
    if not CORE_BIN.exists():
        print(f"✗ núcleo ausente em {CORE_BIN}")
        return 1

    print("— o JS não depende do cookie —")
    js = SALA_JS.read_text(encoding="utf-8")
    checa(
        "sala.js nunca lê document.cookie",
        "document.cookie" not in js,
        "se o JS lesse o cookie, HttpOnly quebraria a interface",
    )

    home = Path(tempfile.mkdtemp(prefix="iachat-cookie-"))
    porta = porta_livre()
    proc, token = sobe(home, porta)
    try:
        if not token:
            print("✗ servidor não subiu ou não anunciou o token")
            return 1

        print("— o cookie semeado na página —")
        cod, h = cabecalhos(porta, f"/?t={token}")
        checa("a página responde 200 com o token na URL", cod == 200, f"veio {cod}")
        bruto = h.get("set-cookie", "")
        checa("a página semeia o cookie", "iachat_t=" in bruto, f"Set-Cookie: {bruto!r}")

        partes = {p.strip().lower() for p in bruto.split(";")}
        checa("o cookie é HttpOnly", "httponly" in partes, f"Set-Cookie: {bruto!r}")
        checa("o cookie é SameSite=Strict", "samesite=strict" in partes, bruto)
        checa("o cookie vale para todo o app", "path=/" in partes, bruto)

        print("— o cookie continua servindo para autenticar —")
        req = urllib.request.Request(f"http://127.0.0.1:{porta}/api/estado")
        req.add_header("Cookie", f"iachat_t={token}")
        with urllib.request.urlopen(req, timeout=6) as r:
            checa("o servidor aceita o token pelo cookie", r.status == 200, f"veio {r.status}")

        req_ruim = urllib.request.Request(f"http://127.0.0.1:{porta}/api/estado")
        req_ruim.add_header("Cookie", "iachat_t=nao-e-o-token")
        try:
            with urllib.request.urlopen(req_ruim, timeout=6) as r:
                checa("cookie errado é recusado", False, f"passou com {r.status}")
        except urllib.error.HTTPError as e:
            checa("cookie errado é recusado", e.code == 401, f"veio {e.code}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=6)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(home, ignore_errors=True)

    print(f"\n{_ok} ✔ / {_falhou} ✗")
    return 1 if _falhou else 0


if __name__ == "__main__":
    raise SystemExit(main())
