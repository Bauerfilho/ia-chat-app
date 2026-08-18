#!/usr/bin/env python3
"""A ponte entre a paleta e os comandos do dono — e a trava dela.

A decisão que este teste guarda: **leitura atravessa o servidor, destruição não.**
`/quem` lê estado e tem rota; `/parar` e `/refaz` matam processo e gastam
assinatura, e não têm rota nenhuma — nem de 127.0.0.1. O servidor roda com
`--lan`, e mesmo sem ele a loopback não é fronteira de confiança nesta máquina:
está escrito no próprio `servir.py`, em `_ok_token`, que com 127.0.0.1 apareceu
na sala uma mensagem assinada `bauer` que ninguém escreveu.

O outro lado da mesma decisão: o que não atravessa **não fica mudo**. A paleta
mostra a linha do terminal, porque comando morto na tela é pior que comando
ausente — e há um gate aqui que reprova se um comando da paleta não existir no
CLI, que é como um comando morto nasce.
"""
from __future__ import annotations

import json
import os
import re
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
COMANDO_CLI = CORE_BIN / "iachat-comando"
SERVIR = RAIZ / "ui" / "servir.py"
SALA_JS = RAIZ / "ui" / "sala.js"
ESTILO = RAIZ / "ui" / "estilo.css"

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


def porta_livre(inicio: int = 59920) -> int:
    for p in range(inicio, inicio + 60):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise RuntimeError("sem porta livre")


def sobe(home: Path, porta: int) -> tuple[subprocess.Popen[str], str]:
    """`--escrever` obriga o token, e é com token que dá para provar o 401."""
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


def pede(porta: int, rota: str, token: str | None = None,
         metodo: str = "GET") -> tuple[int, str]:
    url = f"http://127.0.0.1:{porta}{rota}"
    if token:
        url += ("&" if "?" in rota else "?") + "t=" + token
    req = urllib.request.Request(url, method=metodo)
    if metodo == "POST":
        req.data = b"{}"
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except urllib.error.URLError as e:
        return 0, str(e)


def so_codigo_py(txt: str) -> str:
    """O código sem os comentários.

    Sem isto o teste se engana com a própria prosa: o comentário do servidor
    explica que ali NÃO há `shell=True` nem `/api/comando`, e uma busca ingênua
    encontra as duas coisas — no texto que jura que elas não existem.
    """
    return "\n".join(l for l in txt.splitlines() if not l.strip().startswith("#"))


def so_codigo_js(txt: str) -> str:
    sem_bloco = re.sub(r"/\*.*?\*/", "", txt, flags=re.S)
    return "\n".join(l for l in sem_bloco.splitlines()
                     if not l.strip().startswith("//"))


def comandos_do_js() -> list[dict]:
    """Lê a tabela COMANDOS do `sala.js` — a fonte é o arquivo, não uma cópia aqui."""
    js = SALA_JS.read_text(encoding="utf-8")
    ini = js.index("const COMANDOS = [")
    bloco = js[ini:js.index("];", ini)]
    fora = []
    for linha in bloco.splitlines():
        m = re.search(r"cmd:'(/\w+)'", linha)
        if not m:
            continue
        alvo = bloco[bloco.index(linha):]
        corte = alvo.index("},") if "}," in alvo else len(alvo)
        item = alvo[:corte]
        campo = lambda nome: (re.search(nome + r":'([^']*)'", item) or [None, ""])[1]
        fora.append({
            "cmd": m.group(1),
            "onde": campo("onde"),
            "linha": campo("linha"),
            "porque": campo("porque"),
        })
    return fora


def main() -> int:
    if not CORE_BIN.exists():
        print(f"✗ núcleo ausente em {CORE_BIN}")
        return 1

    fonte = so_codigo_py(SERVIR.read_text(encoding="utf-8"))
    js = so_codigo_js(SALA_JS.read_text(encoding="utf-8"))

    print("— a allowlist é fechada, e leitura é tudo o que ela deixa passar —")
    bloco = fonte[fonte.index("COMANDOS_HTTP"):fonte.index("TETO_COMANDO_S")]
    permitidos = re.findall(r'"(\w+)":\s*\(', bloco)
    checa("COMANDOS_HTTP tem exatamente um comando, e é `quem`",
          permitidos == ["quem"], str(permitidos))
    checa("nenhum comando destrutivo na allowlist",
          not any(x in bloco for x in ("parar", "refaz", "concluir", "plan")),
          bloco[:120])

    print("— a rota nunca monta shell com texto do cliente —")
    corpo = fonte[fonte.index("def _comando"):fonte.index("def _stream")]
    checa("sem shell=True em todo o servidor", "shell=True" not in fonte)
    checa("o argv é lista de constantes, sem f-string nem concatenação",
          "[sys.executable, str(IACHAT_COMANDO), *argv]" in corpo
          and not re.search(r"subprocess\.run\(\s*f?['\"]", corpo))
    checa("`_comando` não lê query, corpo, cabeçalho nem caminho do cliente",
          not any(x in corpo for x in ("parse_qs", "self.path", "self.rfile",
                                       "self.headers", "q.get")))
    checa("o nome do comando vem de rota CRAVADA, não de parâmetro",
          'u.path == "/api/quem"' in fonte and "/api/comando" not in fonte)

    home = Path(tempfile.mkdtemp(prefix="ui-comandos-"))
    porta = porta_livre()
    proc, token = sobe(home, porta)
    try:
        if not token:
            checa("servidor subiu e anunciou o token", False, "sem token no stdout")
            return 1

        subprocess.run([sys.executable, str(COMANDO_CLI), "goal", "--calado",
                        "objetivo para o teste da rota"],
                       env=dict(os.environ, IACHAT_HOME=str(home),
                                PYTHONPATH=str(CORE_BIN)),
                       capture_output=True, text=True)

        print("— o que atravessa —")
        cod, corpo_resp = pede(porta, "/api/quem", token)
        dados = json.loads(corpo_resp) if cod == 200 else {}
        checa("GET /api/quem responde 200 com o JSON do comando",
              cod == 200 and "quem" in dados and "missao" in dados,
              f"HTTP {cod}")
        checa("a resposta traz o estado de cada IA da sala",
              isinstance(dados.get("quem"), list) and len(dados["quem"]) >= 1
              and {"ia", "estado", "fazendo"} <= set(dados["quem"][0]),
              str(dados.get("quem", [])[:1]))

        print("— o que NÃO atravessa (é aqui que a trava vive) —")
        for rota in ("/api/parar", "/api/refaz", "/api/concluir", "/api/plan",
                     "/api/decidi", "/api/comando?nome=parar"):
            cod, _ = pede(porta, rota, token)
            checa(f"REPROVA: {rota} não existe", cod == 404, f"HTTP {cod}")

        cod, _ = pede(porta, "/api/quem", token, metodo="POST")
        checa("REPROVA: POST em /api/quem não existe (comando não se escreve)",
              cod == 404, f"HTTP {cod}")

        cod, _ = pede(porta, "/api/quem")
        checa("REPROVA: /api/quem sem token devolve 401", cod == 401, f"HTTP {cod}")
        cod, _ = pede(porta, "/api/quem", "token-errado")
        checa("REPROVA: /api/quem com token errado devolve 401", cod == 401, f"HTTP {cod}")

        # O cliente pode mandar o que quiser na query: nada disso vira argumento.
        _, sem = pede(porta, "/api/quem", token)
        _, com = pede(porta, "/api/quem?run=/etc&nome=parar&--forte=1", token)
        checa("REPROVA: parâmetro do cliente não muda o comando (resposta idêntica)",
              json.loads(sem).get("quem") == json.loads(com).get("quem"))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        import shutil
        shutil.rmtree(home, ignore_errors=True)

    print("— a paleta não mostra comando morto —")
    cmds = comandos_do_js()
    checa("a tabela COMANDOS foi lida do sala.js", len(cmds) == 7, str(len(cmds)))
    checa("o campo mentiroso `pronto:` não existe mais",
          not re.search(r"\bpronto:\s*(true|false)", js))
    checa("todo comando declara onde age",
          all(c["onde"] in ("sala", "aqui", "terminal") for c in cmds),
          str([(c["cmd"], c["onde"]) for c in cmds]))

    # O GATE que impede o comando morto de nascer: o que a paleta mostra tem que
    # existir no CLI. Um `/refazer` na tabela passaria despercebido sem isto.
    ajuda = subprocess.run([sys.executable, str(COMANDO_CLI), "--help"],
                           capture_output=True, text=True)
    subcomandos = set(re.findall(r"\b(goal|plan|concluir|parar|quem|decidi|refaz)\b",
                                 ajuda.stdout))
    faltando = [c["cmd"] for c in cmds if c["cmd"].lstrip("/") not in subcomandos]
    checa("REPROVA: todo comando da paleta existe no iachat-comando",
          not faltando, f"sem par no CLI: {faltando}")

    ruins = []
    for c in cmds:
        if c["onde"] != "terminal":
            continue
        if not c["linha"].startswith("iachat-comando "):
            ruins.append((c["cmd"], "linha não começa com iachat-comando"))
            continue
        sub = c["linha"].split()[1]
        r = subprocess.run([sys.executable, str(COMANDO_CLI), sub, "--help"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            ruins.append((c["cmd"], f"`{sub} --help` deu rc={r.returncode}"))
    checa("REPROVA: a linha oferecida para copiar é executável de verdade",
          not ruins, str(ruins))
    mudos = [c["cmd"] for c in cmds
             if c["onde"] == "terminal" and not (c["linha"] and c["porque"])]
    checa("REPROVA: todo comando `terminal` traz A LINHA e o MOTIVO",
          not mudos, f"sem linha ou sem motivo: {mudos}")

    print("— o comando que não é conversa não vira mensagem —")
    corpo_envia = js[js.index("async function envia()"):]
    corpo_envia = corpo_envia[:corpo_envia.index("/api/post")]
    checa("REPROVA: `envia` consulta a tabela ANTES de postar",
          "cmdDe(txt)" in corpo_envia and "c.onde !== 'sala'" in corpo_envia,
          corpo_envia[-160:].replace("\n", " "))
    checa("`/quem` cai na rota e o resto cai na linha do terminal",
          "rodaQuem()" in corpo_envia and "mostraLinha(c)" in corpo_envia)
    checa("a interface degrada quando o servidor não tem a rota",
          "return mostraLinha({cmd:'/quem'" in js)

    print("— não invento classe: estilo.css não é minha fronteira —")
    css = ESTILO.read_text(encoding="utf-8")
    trecho = js[js.index("function painelPaleta"):js.index("function escolhePaleta")]
    classes = sorted({c for atr in re.findall(r'class="([^"]+)"', trecho)
                      for c in atr.split()})
    ausentes = [c for c in classes if f".{c}" not in css]
    checa("REPROVA: toda classe usada no painel já existe no CSS",
          not ausentes, f"inventadas: {ausentes} · usadas: {classes}")

    print()
    print(f"{_ok} ✔  {_falhou} ✗")
    return 1 if _falhou else 0


if __name__ == "__main__":
    sys.exit(main())
