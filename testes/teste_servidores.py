#!/usr/bin/env python3
"""Sobe os dois servidores offline, exercita rotas e prova o rescaldo."""
from __future__ import annotations

import json
import os
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
SERVIDORES = (
    ("ui/servir.py", RAIZ / "ui" / "servir.py"),
    ("Resources/servidor.py", RAIZ / "ia-chat.app/Contents/Resources/servidor.py"),
)
HISTORICO = "histórico pré-existente da bateria c1"

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
    """Escolhe deterministicamente a primeira porta alta livre."""
    for porta in range(max(59900, inicio), 60000):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", porta))
            except OSError:
                continue
            return porta
    raise RuntimeError("nenhuma porta livre entre 59900 e 59999")


def ambiente(sala: Path, home: Path) -> dict[str, str]:
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
    for nome in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        amb.pop(nome, None)
    return amb


def prepara_historico(sala: Path, home: Path) -> subprocess.CompletedProcess[str]:
    """Cria histórico ANTES do servidor, pelo núcleo real e em IACHAT_HOME temporário."""
    codigo = (
        "import iachat_core as c; "
        "c.garantir_estrutura(); "
        f"c.post(de='codex', para='claude', texto={HISTORICO!r})"
    )
    return subprocess.run(
        [sys.executable, "-c", codigo],
        env=ambiente(sala, home),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def requisita(porta: int, rota: str) -> tuple[int, str, bytes]:
    pedido = urllib.request.Request(f"http://127.0.0.1:{porta}{rota}")
    try:
        with urllib.request.urlopen(pedido, timeout=3) as resposta:
            return resposta.status, resposta.headers.get("Content-Type", ""), resposta.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Content-Type", ""), exc.read()


def sem_listener(porta: int) -> tuple[bool, str]:
    if not LSOF.is_file():
        return False, f"instrumento ausente: {LSOF}"
    prova = subprocess.run(
        [str(LSOF), "-nP", f"-iTCP:{porta}", "-sTCP:LISTEN", "-t"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    return prova.returncode == 1 and not prova.stdout.strip(), prova.stdout + prova.stderr


def encerra(proc: subprocess.Popen[str], porta: int) -> tuple[bool, str]:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    saida, erro = proc.communicate(timeout=5)
    livre, detalhe_lsof = sem_listener(porta)
    return proc.poll() is not None and livre, saida + erro + detalhe_lsof


def sobe_e_exercita(servidor: Path, porta: int, sala: Path, home: Path) -> dict:
    proc = subprocess.Popen(
        [sys.executable, str(servidor), "--porta", str(porta)],
        env=ambiente(sala, home),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    pronto = False
    rotas: dict[str, tuple[int, str, bytes]] = {}
    detalhe = ""
    try:
        for _ in range(60):
            if proc.poll() is not None:
                break
            try:
                estado = requisita(porta, "/api/estado")
                if estado[0] == 200:
                    pronto = True
                    break
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(0.1)
        if pronto:
            for rota in ("/", "/api/sala", "/api/estado", "/rota-que-nao-existe"):
                rotas[rota] = requisita(porta, rota)
    finally:
        rescaldo, detalhe = encerra(proc, porta)
    return {"pronto": pronto, "rotas": rotas, "rescaldo": rescaldo, "detalhe": detalhe}


def contrato_rotas(evidencia: dict) -> tuple[bool, str]:
    rotas = evidencia["rotas"]
    try:
        raiz = rotas["/"]
        sala = rotas["/api/sala"]
        estado = rotas["/api/estado"]
        ausente = rotas["/rota-que-nao-existe"]
        sala_json = json.loads(sala[2])
        estado_json = json.loads(estado[2])
        mensagens = sala_json.get("msgs", [])
        texto_presente = any(m.get("texto") == HISTORICO for m in mensagens)
        ok = (
            evidencia["pronto"]
            and raiz[0] == 200
            and raiz[1].lower().startswith("text/html")
            and b"<html" in raiz[2].lower()
            and sala[0] == 200
            and isinstance(mensagens, list)
            and texto_presente
            and estado[0] == 200
            and int(estado_json.get("ultima", 0)) >= 1
            and ausente[0] == 404
        )
        return ok, json.dumps(
            {
                "status": {rota: valor[0] for rota, valor in rotas.items()},
                "historico_presente": texto_presente,
                "ultima": estado_json.get("ultima"),
            },
            ensure_ascii=False,
        )
    except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return False, f"contrato incompleto: {type(exc).__name__}: {exc}; rotas={rotas.keys()}"


def main() -> int:
    print("teste_servidores")
    checa("núcleo iachat_core.py está disponível", (CORE_BIN / "iachat_core.py").is_file())
    checa("lsof está disponível para o rescaldo", LSOF.is_file())
    if not (CORE_BIN / "iachat_core.py").is_file() or not LSOF.is_file():
        print(f"\n{_ok} ✔  {_falhou} ✗")
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="iachat-servidores-"))
    proxima_porta = 59920
    try:
        # Controle negativo: o servidor funciona, mas a raiz quebrada viola o contrato.
        ui_quebrada = tmp / "ui-quebrada"
        shutil.copytree(RAIZ / "ui", ui_quebrada,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        index_original = (ui_quebrada / "index.html").read_bytes()
        (ui_quebrada / "index.html").unlink()
        sala_neg = tmp / "sala-negativa"
        home_neg = tmp / "home-negativa"
        preparo_neg = prepara_historico(sala_neg, home_neg)
        checa("histórico do controle negativo foi preparado", preparo_neg.returncode == 0,
              preparo_neg.stdout + preparo_neg.stderr)
        porta = porta_livre(proxima_porta)
        proxima_porta = porta + 1
        negativo = sobe_e_exercita(ui_quebrada / "servir.py", porta, sala_neg, home_neg)
        negativo_ok, negativo_detalhe = contrato_rotas(negativo)
        checa(
            "controle negativo: index.html ausente faz o contrato reprovar",
            not negativo_ok and negativo["rotas"].get("/", (0, "", b""))[0] == 404,
            negativo_detalhe + negativo["detalhe"],
        )
        checa("controle negativo não deixou listener", negativo["rescaldo"], negativo["detalhe"])
        (ui_quebrada / "index.html").write_bytes(index_original)
        checa("index.html temporário foi restaurado byte a byte",
              (ui_quebrada / "index.html").read_bytes() == index_original)

        for nome, servidor in SERVIDORES:
            sala = tmp / f"sala-{porta}"
            home = tmp / f"home-{porta}"
            preparo = prepara_historico(sala, home)
            checa(f"{nome}: histórico pré-existente preparado", preparo.returncode == 0,
                  preparo.stdout + preparo.stderr)
            porta = porta_livre(proxima_porta)
            proxima_porta = porta + 1
            evidencia = sobe_e_exercita(servidor, porta, sala, home)
            rotas_ok, detalhe_rotas = contrato_rotas(evidencia)
            checa(f"{nome}: /, /api/sala, /api/estado e 404 corretos",
                  rotas_ok, detalhe_rotas + evidencia["detalhe"])
            checa(f"{nome}: processo morto e porta {porta} sem LISTEN",
                  evidencia["rescaldo"], evidencia["detalhe"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{_ok} ✔  {_falhou} ✗")
    return 1 if _falhou else 0


if __name__ == "__main__":
    raise SystemExit(main())
