#!/usr/bin/env python3
"""teste_lan_opt_in.py — o app alcança o celular quando (e só quando) o dono pede.

O `.app` subia o servidor sempre em loopback. Quem abria pelo ícone do Dock tinha uma
sala que o telefone **não alcança**: era preciso subir um `servir.py --lan` à mão, o que
anula o "dois cliques" que é a razão de o app existir. Achado do worker `i1-celular`.

`IACHAT_LAN=1` liga. É opt-in de propósito, e este teste trava as DUAS pontas:

- **ligado por padrão seria um defeito de segurança**, não uma conveniência: a sala
  passaria a aceitar conexão de qualquer máquina do Wi-Fi — inclusive o de um café —
  sem ninguém ter pedido. O token protege, mas expor uma porta é decisão do dono;
- **não funcionar quando pedido** devolve o problema original.

Por isso o teste tem os dois lados: o padrão fechado e o opt-in que abre de verdade.
Testar só um deles deixaria metade do contrato sem gate.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
LANCADOR = RAIZ / "ia-chat.app" / "Contents" / "Resources" / "lancador.py"
SERVIDOR = RAIZ / "ia-chat.app" / "Contents" / "Resources" / "ui" / "servir.py"
CORE = RAIZ.parent / "ia-chat" / "bin"

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


print("teste_lan_opt_in")

if not LANCADOR.is_file() or not SERVIDOR.is_file():
    print(f"  ⊘ bundle não montado — rode `./montar.sh` primeiro")
    sys.exit(0)

# Importa o lançador para usar o CANO REAL. Reproduzir o comando aqui testaria a minha
# cópia dele, não o que o app executa — e as duas divergiriam no primeiro reparo.
spec = importlib.util.spec_from_loader(
    "lancador", importlib.machinery.SourceFileLoader("lancador", str(LANCADOR)))
lanc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lanc)

checa("o cano usa a flag (não tem `--lan` cravado)",
      "$IACHAT_LAN_FLAG" in lanc.CANO and "--lan " not in lanc.CANO,
      "o cano voltou a ter --lan fixo ou perdeu a variável")


def sobe(lan: bool, porta: int):
    """Sobe pelo caminho do app e devolve (proc, log, tmp)."""
    tmp = Path(tempfile.mkdtemp(prefix="lanopt-"))
    amb = dict(os.environ, IACHAT_HOME=str(tmp / "sala"))
    amb.pop("IACHAT_LAN", None)
    if lan:
        amb["IACHAT_LAN"] = "1"
    velho, os.environ_backup = dict(os.environ), None
    os.environ.clear()
    os.environ.update(amb)
    lanc.LOG = tmp / "servidor.log"
    lanc.JANELA_PID = tmp / "janela.pid"
    try:
        p = lanc.sobe_servidor(sys.executable, SERVIDOR, CORE, porta, "bauer")
    finally:
        os.environ.clear()
        os.environ.update(velho)
    return p, tmp / "servidor.log", tmp


def escuta_em(porta: int) -> str:
    """`*` = todas as interfaces (alcança o celular) · `127.0.0.1` = só esta máquina."""
    r = subprocess.run(["/usr/sbin/lsof", "-nP", f"-iTCP:{porta}", "-sTCP:LISTEN"],
                       capture_output=True, text=True, timeout=15)
    for ln in r.stdout.splitlines()[1:]:
        alvo = ln.split()[-2] if len(ln.split()) > 2 else ""
        if ":" in alvo:
            return alvo.rsplit(":", 1)[0]
    return ""


for lan, porta, esperado, rotulo in ((False, 59551, "127.0.0.1", "PADRÃO"),
                                     (True, 59552, "*", "IACHAT_LAN=1")):
    proc, log, tmp = sobe(lan, porta)
    try:
        onde = ""
        for _ in range(40):
            time.sleep(0.25)
            onde = escuta_em(porta)
            if onde:
                break
        checa(f"{rotulo}: escuta em {esperado}", onde == esperado,
              f"escutando em {onde!r} — {'expôs sem pedir!' if onde == '*' else 'o celular não alcança'}")

        texto = log.read_text(errors="replace") if log.is_file() else ""
        tem_url_lan = bool(re.search(r"→\s*http://(?!127\.0\.0\.1)[0-9]", texto))
        checa(f"{rotulo}: {'imprime' if lan else 'NÃO imprime'} URL da rede local",
              tem_url_lan == lan, texto.strip()[:200])
    finally:
        # Encerra FECHANDO O CANO, que é o mecanismo desenhado: o shell fica bloqueado
        # em `cat >/dev/null` e o EOF é o que o faz seguir para o `kill "$srv"`. Um
        # `terminate()` sozinho não resolve — o SIGTERM chega ao shell, mas o trap só
        # roda quando o comando em curso retorna, e o `cat` não retorna. A primeira
        # versão deste teste usou `terminate()` e deixou os dois servidores vivos; foi
        # a checagem de rescaldo, no fim, que denunciou.
        if proc.stdin:
            proc.stdin.close()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
        time.sleep(0.6)
        shutil.rmtree(tmp, ignore_errors=True)

# Rescaldo: servidor de teste que sobrevive vira porta ocupada na próxima rodada.
sobrou = [p for p in (59551, 59552) if escuta_em(p)]
checa("nenhum servidor de teste sobreviveu", not sobrou, f"ainda escutando: {sobrou}")

print(f"\n{_ok} ✔  {_falhou} ✗")
sys.exit(1 if _falhou else 0)
