#!/usr/bin/env python3
"""teste_demo_readme.py — a demonstração do README roda de verdade.

O README oferecia duas linhas para ver o SSE cru:

    curl -sN "http://127.0.0.1:8801/api/stream?desde=0"

E respondia `{"erro": "token inválido ou ausente"}`. Duas suposições erradas de uma vez:
que existiria um servidor na 8801 (o app nasce em porta escolhida na hora) e que ele
atenderia sem credencial (servindo em modo escrita, exige token). Faltava a linha que
sobe o servidor — e é ela que torna a demonstração possível, porque em modo leitura não
há token.

Quem chega no repositório e a primeira coisa que copia devolve um erro fecha a aba. A
promessa não era falsa em espírito: o SSE funciona, e é bonito. Só não era executável.

Achado pelo worker `codex` na missão m2, respondendo "o que um desenvolvedor que nunca
viu isto abandonaria no meio?". A mesma classe apareceu três vezes em 18/08 — o núcleo
mandando editar `config.json`, o CONTRIBUTING com um comando de bundle, e esta. Por isso
existe este gate: prosa se revisa lendo, comando se revisa **executando**.

O teste extrai os comandos DO PRÓPRIO README e os roda. Se a demonstração mudar, é a
nova que é testada.
"""
from __future__ import annotations

import os
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
README = RAIZ / "README.md"
CLI = RAIZ.parent / "ia-chat" / "bin" / "iachat"
PORTA = 59823

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


print("teste_demo_readme")

texto = README.read_text(encoding="utf-8")

# ── 1. a demo existe e sobe um servidor ─────────────────────────────────────
# O defeito não era o `curl`: era a AUSÊNCIA da linha anterior. Um README que manda
# escutar uma porta sem dizer quem a abriu supõe um servidor que o leitor não tem.
bloco = re.search(r"```bash\n([^`]*servir\.py[^`]*curl -sN[^`]*)```", texto, re.S)
checa("a demo do SSE sobe o servidor antes de escutar", bloco is not None,
      "não achei um bloco com `servir.py` seguido de `curl -sN` — se a demo mudou, "
      "atualize este gate; se a linha do servidor sumiu, o defeito voltou")

if bloco:
    linhas = [l.strip() for l in bloco.group(1).splitlines() if l.strip()]
    cmd_srv = next((l for l in linhas if "servir.py" in l), "")
    cmd_curl = next((l for l in linhas if l.startswith("curl")), "")

    # ── 2. modo leitura: sem `--escrever` e sem `--lan` ─────────────────────
    # É o que dispensa o token. Se alguém acrescentar um dos dois "para ficar mais
    # completo", a demo volta a devolver erro — e o gate avisa antes do leitor.
    checa("a demo usa modo LEITURA (é o que dispensa o token)",
          "--escrever" not in cmd_srv and "--lan" not in cmd_srv, cmd_srv)

    # ── 3. o comando roda de verdade ────────────────────────────────────────
    home = Path(tempfile.mkdtemp(prefix="demo-")) / "sala"
    # O `servir.py` procura o núcleo em `~/Projetos/ia-chat/bin` — caminho FIXO, baseado
    # em HOME. Numa máquina onde o repositório não mora ali (o runner do CI põe o irmão
    # no workspace), o import só encontra pelo PYTHONPATH. É o que o `lancador.py` faz em
    # produção; o teste não fazia, e o servidor subia sem núcleo devolvendo 0 mensagens.
    NUCLEO = RAIZ.parent / "ia-chat" / "bin"
    env = dict(os.environ, IACHAT_HOME=str(home),
               PYTHONPATH=str(NUCLEO) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    subprocess.run([sys.executable, str(CLI), "status"], env=env,
                   capture_output=True, stdin=subprocess.DEVNULL, timeout=60)

    porta_readme = re.search(r"--porta (\d+)", cmd_srv)
    proc = subprocess.Popen(
        [sys.executable, str(RAIZ / "ui" / "servir.py"), "--porta", str(PORTA)],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, start_new_session=True)
    try:
        subiu = False
        for _ in range(40):
            time.sleep(0.25)
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{PORTA}/api/estado", timeout=3) as r:
                    subiu = r.status == 200
                    break
            except (urllib.error.HTTPError, OSError):
                continue
        checa("o servidor da demo sobe e responde SEM token", subiu,
              "a demo depende de o modo leitura dispensar credencial")

        # A prova que o defeito original teria reprovado: o `curl` da demo, com a
        # rota da demo, devolvendo o fluxo — e não um JSON de erro.
        rota = re.search(r"(/api/stream[^\"']*)", cmd_curl)
        checa("dá para extrair a rota do curl", rota is not None, cmd_curl)
        if rota and subiu:
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{PORTA}{rota.group(1)}", timeout=5) as r:
                    primeira = r.readline().decode("utf-8", "replace").strip()
                    codigo = r.status
            except urllib.error.HTTPError as e:
                primeira, codigo = e.read()[:120].decode("utf-8", "replace"), e.code
            checa("o fluxo abre (era `token inválido ou ausente`)",
                  codigo == 200 and "erro" not in primeira,
                  f"HTTP {codigo} · {primeira!r}")
            checa("e a primeira linha é o handshake do SSE",
                  primeira.startswith(":"), f"veio {primeira!r}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(home.parent, ignore_errors=True)

    # ── 4. a porta do README não pode ser a do app ──────────────────────────
    # O app nasce em porta escolhida na hora; cravar uma no README é prometer um
    # servidor que talvez não exista. Aqui a porta é do próprio leitor, e por isso vale.
    checa("a demo abre a própria porta, não adivinha a do app",
          porta_readme is not None and "--porta" in cmd_srv, cmd_srv)

print(f"\n{_ok} ✔  {_falhou} ✗")
sys.exit(1 if _falhou else 0)
