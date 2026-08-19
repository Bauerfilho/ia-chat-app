#!/usr/bin/env python3
"""Contrato da atualização da janela aberta e do caminho imediato de `/quem`."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CORE_BIN = RAIZ.parent / "ia-chat" / "bin"
UI = RAIZ / "ui"
SERVIR = UI / "servir.py"
SALA_JS = UI / "sala.js"

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


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def sobe(home: Path, porta: int) -> subprocess.Popen[str]:
    env = dict(
        os.environ,
        IACHAT_HOME=str(home),
        IACHAT_CORE=str(CORE_BIN),
        PYTHONPATH=str(CORE_BIN),
        PYTHONDONTWRITEBYTECODE="1",
        NO_PROXY="127.0.0.1,localhost",
        no_proxy="127.0.0.1,localhost",
    )
    for nome in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        env.pop(nome, None)
    return subprocess.Popen(
        [sys.executable, str(SERVIR), "--porta", str(porta)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        env=env,
    )


def pede(porta: int, rota: str) -> tuple[int, dict[str, str], bytes]:
    with urllib.request.urlopen(f"http://127.0.0.1:{porta}{rota}", timeout=6) as r:
        return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()


def espera_http(porta: int) -> None:
    limite = time.time() + 10
    while time.time() < limite:
        try:
            if pede(porta, "/api/estado")[0] == 200:
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("servidor não ficou pronto")


def main() -> int:
    if not CORE_BIN.exists():
        print(f"✗ núcleo ausente em {CORE_BIN}")
        return 1

    js = SALA_JS.read_text(encoding="utf-8")
    html = (UI / "index.html").read_text(encoding="utf-8")
    css = (UI / "estilo.css").read_text(encoding="utf-8")

    print("— a janela sabe que existe versão nova —")
    checa(
        "a faixa persistente tem texto e botão de recarga",
        'id="aviso-versao"' in html
        and "nova versão" in html
        and 'id="recarregar-versao"' in html,
    )
    checa(
        "a versão carregada vem embutida no HTML servido",
        'name="ia-chat-versao" content="__IACHAT_UI_HASH__"' in html
        and "VERSAO_EMBUTIDA" in js,
    )
    checa(
        "a faixa anuncia a mudança em uma região viva já montada",
        'id="estado-versao" role="status" aria-live="polite"' in html
        and "E.estadoVersao.textContent" in js,
    )
    checa(
        "o cliente consulta a versão a cada minuto e no foco",
        "INTERVALO_VERSAO_MS = 60_000" in js
        and "window.addEventListener('focus', verificaVersao)" in js
        and "url('/api/versao')" in js,
    )
    checa("o botão recarrega a página", "location.reload()" in js)
    checa(
        "service worker continua adiado",
        "serviceWorker" not in js and not (UI / "sw.js").exists(),
    )

    print("— `/quem` executa pelo caminho que o dono usa —")
    escolhe = js[js.index("function escolhePaleta") : js.index("function navegaPaleta")]
    checa(
        "selecionar `/quem` executa em vez de só preencher o campo",
        "cmd === '/quem'" in escolhe and "return rodaQuem()" in escolhe,
    )
    painel = js[js.index("function painelPaleta") : js.index("async function copia")]
    checa(
        "o painel é trazido para a área visível",
        "E.paleta.scrollIntoView({block:'nearest'})" in painel,
    )
    esconder_enxame = css[
        css.index('html[data-janela="enxame"] .moldura') :
        css.index(".enxame{display:none")
    ]
    checa(
        "o compositor permanece disponível no enxame",
        ".compositor{display:none}" not in esconder_enxame
        and '"trilho comp gaveta"' in esconder_enxame,
    )
    paleta_css = css[css.index(".paleta{") : css.index(".paleta.paleta--painel")]
    checa(
        "a paleta fica acima do palco do enxame",
        "z-index:20" in paleta_css,
    )

    home = Path(tempfile.mkdtemp(prefix="iachat-atualizacao-"))
    porta = porta_livre()
    proc = sobe(home, porta)
    try:
        espera_http(porta)
        print("— o servidor entrega bytes revalidáveis e hash real —")
        pagina = b""
        for rota in ("/", "/sala.js", "/estilo.css"):
            cod, cabecalhos, corpo = pede(porta, rota)
            if rota == "/":
                pagina = corpo
            checa(
                f"{rota} usa Cache-Control: no-cache",
                cod == 200 and cabecalhos.get("cache-control") == "no-cache",
                repr(cabecalhos.get("cache-control")),
            )
        cod, cabecalhos, corpo = pede(porta, "/api/versao")
        resposta = json.loads(corpo)
        esperado = hashlib.sha256(SALA_JS.read_bytes()).hexdigest()
        checa(
            "/api/versao devolve o SHA-256 do sala.js servido",
            cod == 200 and resposta.get("hash") == esperado,
            repr(resposta),
        )
        checa(
            "o HTML servido embute o mesmo SHA-256",
            f'content="{esperado}"'.encode() in pagina
            and b"__IACHAT_UI_HASH__" not in pagina,
        )
        checa(
            "/api/versao nunca é cacheado",
            cabecalhos.get("cache-control") == "no-store",
            repr(cabecalhos.get("cache-control")),
        )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=6)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=6)
        shutil.rmtree(home, ignore_errors=True)

    print(f"\n{_ok} ✔ / {_falhou} ✗")
    return 1 if _falhou else 0


if __name__ == "__main__":
    raise SystemExit(main())
