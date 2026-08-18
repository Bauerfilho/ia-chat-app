#!/usr/bin/env python3
"""Limites de recurso dos dois servidores: corpo do POST e conexões SSE.

Três achados da auditoria de 18/08, cada um com o caso que REPROVA antes da correção:

  M1  corpo do POST sem teto no servidor do bundle -> memória do processo à mercê
      do cliente. O `ui/servir.py` já recusava com 413 aos 256 KB.
  M2  `Content-Length` ausente virava `KeyError` -> `except Exception` -> 500.
      Um 500 diz "erro meu"; a causa era do pedido, e o cliente merecia saber.
  M4  `/api/stream` sem teto: um laço infinito por conexão, uma thread por laço,
      e nada segurando quantos. Em `--lan` isso sai do loopback.

Sala em `IACHAT_HOME` temporário e portas 59960+: a sala viva não é tocada.
"""
from __future__ import annotations

import http.client
import json
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
LSOF = Path("/usr/sbin/lsof")
SERVIDORES = {
    "ui": RAIZ / "ui/servir.py",
    "bundle": RAIZ / "ia-chat.app/Contents/Resources/servidor.py",
}

TETO_CORPO = 262144            # 256 KB, o mesmo dos dois servidores
TETO_SSE = 16                  # o mesmo dos dois servidores
# `Content-Length` ausente: os dois recusam, com códigos diferentes de propósito.
# O bundle responde 411 (é exatamente "falta o Content-Length"); o `ui/servir.py`
# lê corpo vazio e o núcleo recusa a mensagem vazia com 400. Nenhum dos dois é 500,
# que era o defeito. A divergência é catalogada em teste_coerencia_servidores.py.
SEM_TAMANHO_ESPERADO = {"ui": 400, "bundle": 411}

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


def porta_livre(inicio: int) -> int:
    for porta in range(max(59900, inicio), 60000):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", porta))
            except OSError:
                continue
            return porta
    raise RuntimeError("nenhuma porta livre entre 59900 e 59999")


def ambiente(sala: Path, home: Path) -> dict:
    amb = dict(os.environ)
    amb.update(
        HOME=str(home),
        IACHAT_HOME=str(sala),
        IACHAT_BIN=str(CORE_BIN),
        IACHAT_CORE=str(CORE_BIN),
        PYTHONPATH=str(CORE_BIN),
        PYTHONDONTWRITEBYTECODE="1",
        NO_PROXY="127.0.0.1,localhost",
        no_proxy="127.0.0.1,localhost",
    )
    for nome in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                 "http_proxy", "https_proxy", "all_proxy"):
        amb.pop(nome, None)
    return amb


def com_token(rota: str, token: str) -> str:
    return f"{rota}?t={token}" if token else rota


def pede(porta: int, rota: str, token: str, metodo: str = "GET",
         dados: bytes | None = None, headers: dict | None = None) -> tuple[int, bytes]:
    pedido = urllib.request.Request(
        f"http://127.0.0.1:{porta}{com_token(rota, token)}",
        data=dados, method=metodo, headers=headers or {},
    )
    try:
        with urllib.request.urlopen(pedido, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def post_sem_content_length(porta: int, token: str) -> int:
    conexao = http.client.HTTPConnection("127.0.0.1", porta, timeout=8)
    try:
        conexao.putrequest("POST", com_token("/api/post", token))
        conexao.putheader("Content-Type", "application/json")
        conexao.endheaders()
        resposta = conexao.getresponse()
        resposta.read()
        return resposta.status
    finally:
        conexao.close()


def abre_stream(porta: int, token: str) -> tuple[tuple, int, str]:
    """Abre um SSE e só volta quando o servidor já contou a vaga (headers na mão).

    Devolve a conexão E a resposta, e quem chama tem que segurar as DUAS. Custou
    um diagnóstico: guardando só a conexão, o `HTTPResponse` era coletado, o
    `close()` dele derrubava o socket (a resposta vem com `Connection: close`), o
    servidor via o cliente sumir e devolvia a vaga — o teto real nunca enchia e o
    teste dava vermelho num produto correto. Instrumento mente até ser provado.
    """
    conexao = http.client.HTTPConnection("127.0.0.1", porta, timeout=10)
    conexao.putrequest("GET", com_token("/api/stream", token))
    conexao.endheaders()
    resposta = conexao.getresponse()
    retry = resposta.headers.get("Retry-After", "")
    if resposta.status == 200:
        resposta.read(1)          # `: sala aberta` — a thread já está no laço
    else:
        resposta.read()
    return (conexao, resposta), resposta.status, retry


def sem_listener(porta: int) -> tuple[bool, str]:
    if not LSOF.is_file():
        return False, f"instrumento ausente: {LSOF}"
    prova = subprocess.run(
        [str(LSOF), "-nP", f"-iTCP:{porta}", "-sTCP:LISTEN", "-t"],
        capture_output=True, text=True, check=False,
    )
    return not prova.stdout.strip(), prova.stdout.strip()


def encerra(proc: subprocess.Popen, porta: int) -> tuple[bool, str]:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    livre, detalhe = sem_listener(porta)
    return proc.poll() is not None and livre, detalhe


def sobe(servidor: Path, porta: int, sala: Path, home: Path,
         log: Path) -> tuple[subprocess.Popen, str]:
    with log.open("wb") as saida:
        proc = subprocess.Popen(
            [sys.executable, str(servidor), "--porta", str(porta),
             "--escrever", "--papel", "codex"],
            env=ambiente(sala, home), stdout=saida, stderr=subprocess.STDOUT,
        )
    token = ""
    for _ in range(100):
        if proc.poll() is not None:
            break
        achado = re.search(r"\?t=([A-Za-z0-9_-]+)",
                           log.read_text(encoding="utf-8", errors="replace"))
        if achado:
            token = achado.group(1)
        if not token:
            time.sleep(0.1)
            continue
        try:
            if pede(porta, "/api/sala", token)[0] == 200:
                return proc, token
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.1)
    encerra(proc, porta)
    raise RuntimeError(f"servidor não subiu; log={log.read_text(errors='replace')}")


# ─────────────────────────────────────────────────────────────────────────────
def prova_corpo(nome: str, porta: int, token: str) -> None:
    """M1 — o teto recusa o abusivo e deixa passar o legítimo."""
    grande = json.dumps({"texto": "x" * (TETO_CORPO + 64), "para": ["claude"]}).encode()
    status, _ = pede(porta, "/api/post", token, "POST", grande,
                     {"Content-Type": "application/json"})
    checa(f"{nome} · M1: corpo de {len(grande)} B recusado com 413",
          status == 413, f"status={status}")
    # Recusar não pode deixar o servidor sujo: o pedido seguinte tem que funcionar.
    checa(f"{nome} · M1: servidor segue de pé depois da recusa",
          pede(porta, "/api/estado", token)[0] == 200)
    # Controle: sem um post legítimo passando, um teto de zero também daria 413.
    curto = json.dumps({"texto": "post legítimo sob o teto", "para": ["claude"]}).encode()
    status_curto, _ = pede(porta, "/api/post", token, "POST", curto,
                           {"Content-Type": "application/json"})
    checa(f"{nome} · M1: post legítimo continua aceito (controle)",
          status_curto == 200, f"status={status_curto}")


def prova_sem_tamanho(nome: str, porta: int, token: str) -> None:
    """M2 — sem `Content-Length` a culpa é do pedido, e o código tem que dizer isso."""
    status = post_sem_content_length(porta, token)
    checa(f"{nome} · M2: Content-Length ausente não vira 500",
          status != 500, f"status={status}")
    checa(f"{nome} · M2: Content-Length ausente responde {SEM_TAMANHO_ESPERADO[nome]}",
          status == SEM_TAMANHO_ESPERADO[nome], f"status={status}")


def prova_teto_sse(nome: str, porta: int, token: str) -> None:
    """M4 — o teto segura, avisa, e devolve a vaga quando a janela some."""
    abertas = []
    try:
        for i in range(TETO_SSE):
            viva, status, _ = abre_stream(porta, token)
            abertas.append(viva)
            if status != 200:
                checa(f"{nome} · M4: as {TETO_SSE} primeiras conexões são aceitas",
                      False, f"a {i + 1}ª veio {status}")
                break
        else:
            checa(f"{nome} · M4: as {TETO_SSE} primeiras conexões são aceitas", True)

        excedente, status, retry = abre_stream(porta, token)
        abertas.append(excedente)
        checa(f"{nome} · M4: o teto encheu de verdade (16 vivas na hora da recusa)",
              len(abertas) == TETO_SSE + 1, f"abertas={len(abertas)}")
        checa(f"{nome} · M4: a conexão {TETO_SSE + 1} é recusada com 503",
              status == 503, f"status={status}")
        checa(f"{nome} · M4: a recusa traz Retry-After", bool(retry), f"Retry-After={retry!r}")
        # Recusar SSE não pode derrubar o resto do servidor.
        checa(f"{nome} · M4: as rotas comuns seguem atendendo com o teto cheio",
              pede(porta, "/api/estado", token)[0] == 200)
    finally:
        for conexao, resposta in abertas:
            resposta.close()
            conexao.close()

    # A vaga tem que voltar sozinha: teto que não devolve vaga trava o dono de fora.
    devolvida, prazo = False, time.time() + 10
    while time.time() < prazo:
        (conexao, resposta), status, _ = abre_stream(porta, token)
        resposta.close()
        conexao.close()
        if status == 200:
            devolvida = True
            break
        time.sleep(0.5)
    checa(f"{nome} · M4: vaga devolvida depois que as conexões fecham", devolvida)


def main() -> int:
    print("teste_limites")
    checa("núcleo iachat_core.py disponível", (CORE_BIN / "iachat_core.py").is_file())
    checa("lsof disponível para o rescaldo", LSOF.is_file())
    if not (CORE_BIN / "iachat_core.py").is_file() or not LSOF.is_file():
        print(f"\n{_ok} ✔  {_falhou} ✗")
        return 1

    # Os limites do teste e os do código têm que ser o MESMO número, senão o teste
    # mede uma coisa e o produto faz outra.
    for nome, servidor in SERVIDORES.items():
        fonte = servidor.read_text(encoding="utf-8")
        checa(f"{nome}: teto de corpo no código é {TETO_CORPO}", str(TETO_CORPO) in fonte)
        checa(f"{nome}: teto de SSE no código é {TETO_SSE}",
              re.search(rf"\bTETO_SSE\b\s*=\s*{TETO_SSE}\b", fonte) is not None)

    tmp = Path(tempfile.mkdtemp(prefix="iachat-limites-"))
    proxima = 59960
    try:
        for nome, servidor in SERVIDORES.items():
            sala, home = tmp / f"sala-{nome}", tmp / f"home-{nome}"
            porta = porta_livre(proxima)
            proxima = porta + 1
            try:
                proc, token = sobe(servidor, porta, sala, home, tmp / f"{nome}.log")
            except RuntimeError as exc:
                checa(f"{nome}: servidor sobe", False, str(exc))
                continue
            try:
                prova_corpo(nome, porta, token)
                prova_sem_tamanho(nome, porta, token)
                prova_teto_sse(nome, porta, token)
            finally:
                rescaldo, detalhe = encerra(proc, porta)
                checa(f"{nome}: processo morto e porta {porta} sem LISTEN",
                      rescaldo, detalhe)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{_ok} ✔  {_falhou} ✗")
    return 1 if _falhou else 0


if __name__ == "__main__":
    raise SystemExit(main())
