#!/usr/bin/env python3
"""teste_python_sistema.py — o APP tem que rodar no Python que JÁ VEM no Mac.

O gate do `ia-chat` (`~/Projetos/ia-chat/tests/teste_python_sistema.py`) já prova
CLI + núcleo em `/usr/bin/python3` (3.9). Este arquivo é o buraco que faltava:
o `.app`. O `lancador.py` declara `/usr/bin/python3` na lista e o wrapper
`Contents/MacOS/ia-chat` também. Se o servidor ou a interface exigirem 3.10+,
o duplo clique falha na maioria dos Macs — os que só têm o Python do sistema.

O núcleo não se retesta aqui: cita-se o gate irmão. Aqui é compile + sobe +
escolhe + E2E, tudo sob o 3.9, com o caso que reprova (sintaxe `match`) visto
vermelho numa CÓPIA e desfeito. O produto não é editado.

Se `/usr/bin/python3` não existir (Linux, CI), o teste se declara **não
aplicável** em vez de inventar verde.
"""
from __future__ import annotations

import ast
import hashlib
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
PY_SISTEMA = Path("/usr/bin/python3")
LSOF = Path("/usr/sbin/lsof")
LANCADOR = RAIZ / "ia-chat.app" / "Contents" / "Resources" / "lancador.py"
WRAPPER = RAIZ / "ia-chat.app" / "Contents" / "MacOS" / "ia-chat"
SERVIDOR_UI = RAIZ / "ui" / "servir.py"
SERVIDOR_BUNDLE = RAIZ / "ia-chat.app" / "Contents" / "Resources" / "servidor.py"
SERVIDOR_UI_BUNDLE = RAIZ / "ia-chat.app" / "Contents" / "Resources" / "ui" / "servir.py"
PAPEL = "codex"
DESTINO = "claude"
MARCA_E2E = "f1-app-python-sistema-e2e"
RE_TOKEN = re.compile(r"\?t=([A-Za-z0-9_-]+)")
RE_META = re.compile(r"<!-- iachat msg=(\d+) de=(\S+) para=(\S*) ts=(\S+) -->")

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


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def py_do_produto() -> list[Path]:
    """Todo .py do produto. Testes ficam de fora: o gate é sobre o que o usuário roda."""
    ignorar = {RAIZ / "testes"}
    saida = []
    for p in sorted(RAIZ.rglob("*.py")):
        if any(ign in p.parents or p.parent == ign for ign in ignorar):
            continue
        if "__pycache__" in p.parts:
            continue
        saida.append(p)
    return saida


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
        PYTHONPATH=str(CORE_BIN) + os.pathsep + os.environ.get("PYTHONPATH", ""),
        PYTHONDONTWRITEBYTECODE="1",
        NO_PROXY="127.0.0.1,localhost",
        no_proxy="127.0.0.1,localhost",
    )
    for nome in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                 "http_proxy", "https_proxy", "all_proxy"):
        amb.pop(nome, None)
    return amb


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


def com_token(rota: str, token: str) -> str:
    sep = "&" if "?" in rota else "?"
    return f"{rota}{sep}t={token}" if token else rota


def pede(porta: int, rota: str, token: str) -> tuple[int, bytes]:
    alvo = f"http://127.0.0.1:{porta}{com_token(rota, token)}"
    try:
        with urllib.request.urlopen(alvo, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def posta(porta: int, token: str, carga: dict) -> tuple[int, dict]:
    pedido = urllib.request.Request(
        f"http://127.0.0.1:{porta}{com_token('/api/post', token)}",
        data=json.dumps(carga, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(pedido, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read())
        except ValueError:
            return exc.code, {}


def lista_escolher_python(fonte: str) -> list[str]:
    """Extrai a tupla de candidatos de `escolher_python` — prova no fonte, não no palpite."""
    arvore = ast.parse(fonte)
    for no in arvore.body:
        if isinstance(no, ast.FunctionDef) and no.name == "escolher_python":
            for filho in ast.walk(no):
                if isinstance(filho, ast.For):
                    candidatos = []
                    for elt in getattr(filho.iter, "elts", []):
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            candidatos.append(elt.value)
                    if "/usr/bin/python3" in candidatos:
                        return candidatos
    return []


def lista_wrapper(texto: str) -> list[str]:
    achado = re.search(r"for PY in ([^\n;]+);", texto)
    if not achado:
        return []
    return re.findall(r"(/[^\s]+python3)", achado.group(1))


def sobe_39(servidor: Path, porta: int, sala: Path, home: Path, log: Path,
            espera: float = 12.0) -> tuple[subprocess.Popen, str]:
    """Sobe como o lançador: interpretador do sistema, stdout num arquivo, sem `-u`."""
    with log.open("wb") as saida:
        proc = subprocess.Popen(
            [str(PY_SISTEMA), str(servidor), "--porta", str(porta),
             "--escrever", "--papel", PAPEL],
            env=ambiente(sala, home), stdout=saida, stderr=subprocess.STDOUT,
        )
    limite = time.time() + espera
    while time.time() < limite:
        if proc.poll() is not None:
            break
        achado = RE_TOKEN.search(log.read_text(encoding="utf-8", errors="replace"))
        if achado:
            return proc, achado.group(1)
        time.sleep(0.1)
    return proc, ""


def mensagens_no_arquivo(sala: Path) -> list[dict]:
    md = (sala / "iachat.md").read_text(encoding="utf-8")
    marcas = list(RE_META.finditer(md))
    saida = []
    for i, m in enumerate(marcas):
        fim = marcas[i + 1].start() if i + 1 < len(marcas) else len(md)
        saida.append({
            "n": int(m.group(1)),
            "de": m.group(2),
            "corpo": md[m.end():fim],
        })
    return saida


def main() -> int:
    print("teste_python_sistema")
    print("  (app — o CLI já está no gate do ia-chat; aqui não se repete)")

    if not PY_SISTEMA.is_file():
        print(f"  ⊘ {PY_SISTEMA} não existe — teste não aplicável neste sistema")
        return 0

    versao = subprocess.run(
        [str(PY_SISTEMA), "--version"], capture_output=True, text=True,
    ).stdout.strip() or "?"
    print(f"  ({versao}, contra o {sys.version.split()[0]} que roda a bateria)")
    checa("o Python do sistema é 3.9.x", versao.startswith("Python 3.9"), versao)
    checa("núcleo iachat_core.py está disponível", (CORE_BIN / "iachat_core.py").is_file())
    checa("lsof está disponível para o rescaldo", LSOF.is_file())

    alvos = py_do_produto()
    checa("há Python de produto para compilar", bool(alvos), "nenhum .py fora de testes/")
    for obrigatorio in (LANCADOR, SERVIDOR_UI, SERVIDOR_BUNDLE, SERVIDOR_UI_BUNDLE):
        checa(f"presente: {obrigatorio.relative_to(RAIZ)}", obrigatorio.is_file())

    hashes_antes = {p: sha256(p) for p in alvos if p.is_file()}

    # ── 1. compila no 3.9 ───────────────────────────────────────────────────
    quebrados = []
    for f in alvos:
        r = subprocess.run(
            [str(PY_SISTEMA), "-m", "py_compile", str(f)],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            cauda = (r.stderr or r.stdout).strip().splitlines()
            quebrados.append(f"{f.relative_to(RAIZ)}: {(cauda[-1] if cauda else '?')[:90]}")
    checa(f"tudo compila no Python do sistema ({len(alvos)} arquivos)",
          not quebrados, "\n      ".join(quebrados))

    # ── caso que REPROVA: match (3.10) numa CÓPIA, nunca no produto ────────
    tmp_oraculo = Path(tempfile.mkdtemp(prefix="f1-oraculo-"))
    try:
        copia = tmp_oraculo / "servir-match.py"
        original = SERVIDOR_UI.read_text(encoding="utf-8")
        copia.write_text(
            original + "\n\ndef _oraculo_310(x):\n    match x:\n        case 1:\n            return 1\n",
            encoding="utf-8",
        )
        r_red = subprocess.run(
            [str(PY_SISTEMA), "-m", "py_compile", str(copia)],
            capture_output=True, text=True,
        )
        checa("oráculo: `match` (sintaxe 3.10) REPROVA no 3.9",
              r_red.returncode != 0 and "SyntaxError" in (r_red.stderr + r_red.stdout),
              (r_red.stderr or r_red.stdout)[-200:])
        r_green = subprocess.run(
            [str(PY_SISTEMA), "-m", "py_compile", str(SERVIDOR_UI)],
            capture_output=True, text=True,
        )
        checa("oráculo desfeito: o servir.py original volta a compilar",
              r_green.returncode == 0, r_green.stderr[-160:])
        checa("oráculo não tocou o produto (sha256 idêntico)",
              sha256(SERVIDOR_UI) == hashes_antes[SERVIDOR_UI])
    finally:
        shutil.rmtree(tmp_oraculo, ignore_errors=True)

    # ── 3. o lançador escolhe certo ─────────────────────────────────────────
    fonte_lanc = LANCADOR.read_text(encoding="utf-8")
    candidatos = lista_escolher_python(fonte_lanc)
    checa("escolher_python lista `/usr/bin/python3`",
          "/usr/bin/python3" in candidatos, str(candidatos))
    checa("a lista do lançador tem os três caminhos absolutos clássicos",
          {"/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"}
          <= set(candidatos),
          str(candidatos))

    # A prova é a MESMA do lançador (lancador.py:106-119): importar o núcleo.
    prova = "import sys;sys.path.insert(0,%r);import iachat_core" % str(CORE_BIN)
    r_imp = subprocess.run([str(PY_SISTEMA), "-c", prova], capture_output=True, text=True)
    checa("o 3.9 é ACEITO: importa iachat_core (a prova do lançador)",
          r_imp.returncode == 0,
          (r_imp.stderr or r_imp.stdout)[-200:] or "rejeitado — achado: o app quebraria no Mac só com o Python do sistema")

    # O wrapper do bundle é o primeiro filtro do duplo clique.
    if WRAPPER.is_file():
        wrap = lista_wrapper(WRAPPER.read_text(encoding="utf-8"))
        checa("o wrapper MacOS/ia-chat também lista `/usr/bin/python3`",
              "/usr/bin/python3" in wrap, str(wrap))

    # ── 2 + 4. servidor sobe + E2E, os dois servidores de produto ───────────
    # ui/servir.py é o que o lançador escolhe no repo; Resources/servidor.py é a reserva.
    if not LSOF.is_file() or not (CORE_BIN / "iachat_core.py").is_file():
        print(f"\n{_ok} ✔  {_falhou} ✗")
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="f1-app-py39-"))
    proxima = 59980
    try:
        for rotulo, servidor in (
            ("ui/servir.py", SERVIDOR_UI),
            ("Resources/servidor.py", SERVIDOR_BUNDLE),
        ):
            porta = porta_livre(proxima)
            proxima = porta + 1
            sala = tmp / f"sala-{porta}"
            home = tmp / f"home-{porta}"
            log = tmp / f"log-{porta}.txt"
            proc, token = sobe_39(servidor, porta, sala, home, log)
            try:
                checa(f"{rotulo}: token no log sob /usr/bin/python3",
                      bool(token), log.read_text(errors="replace")[:240])
                if not token:
                    continue
                st_raiz, corpo_raiz = pede(porta, "/", token)
                checa(f"{rotulo}: GET / = 200",
                      st_raiz == 200 and b"<html" in corpo_raiz.lower(),
                      f"status={st_raiz} bytes={len(corpo_raiz)}")
                st_sala, corpo_sala = pede(porta, "/api/sala", token)
                try:
                    sala_json = json.loads(corpo_sala)
                except ValueError:
                    sala_json = {}
                checa(f"{rotulo}: GET /api/sala = 200",
                      st_sala == 200 and isinstance(sala_json.get("msgs"), list),
                      f"status={st_sala} keys={list(sala_json)[:6]}")

                st_post, resp = posta(porta, token, {
                    "texto": f"{MARCA_E2E}:{rotulo}", "para": [DESTINO],
                })
                checa(f"{rotulo}: POST /api/post = 200",
                      st_post == 200 and "n" in resp,
                      f"status={st_post} {resp}")
                chat = sala / "iachat.md"
                texto_chat = chat.read_text(encoding="utf-8") if chat.is_file() else ""
                entrou = [m for m in mensagens_no_arquivo(sala)
                          if f"{MARCA_E2E}:{rotulo}" in m["corpo"]] if chat.is_file() else []
                checa(f"{rotulo}: a mensagem está no iachat.md (IACHAT_HOME temp)",
                      len(entrou) == 1 and entrou[0]["de"] == PAPEL,
                      f"achadas={len(entrou)} de={entrou[0]['de'] if entrou else None}")
                checa(f"{rotulo}: controle — texto nunca postado não aparece",
                      "f1-jamais-postado" not in texto_chat)
            finally:
                rescaldo, detalhe = encerra(proc, porta)
                checa(f"{rotulo}: processo morto e porta {porta} sem LISTEN (lsof)",
                      rescaldo, detalhe)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    hashes_depois = {p: sha256(p) for p in alvos if p.is_file()}
    checa("nenhum .py de produto mudou de sha256",
          hashes_antes == hashes_depois,
          str(sorted(p.relative_to(RAIZ) for p in hashes_antes if hashes_antes[p] != hashes_depois.get(p))))

    print(f"\n{_ok} ✔  {_falhou} ✗")
    return 1 if _falhou else 0


if __name__ == "__main__":
    raise SystemExit(main())
