#!/usr/bin/env python3
"""A ponte entre a paleta e os comandos do dono — e as TRÊS travas dela.

A decisão que este teste guarda mudou em 18/08 (fase 9), por ordem do dono: os
comandos de barra FUNCIONAM a partir do app. A versão anterior deste gate
provia o contrário ("leitura atravessa, destruição não") — e estava certa para
o tempo dela: a paleta mentiu primeiro (`sala`), silenciou depois (`terminal`),
e só agora atravessa de verdade. O que não muda nas três eras é a régua, e ela
fica escrita nas três travas que este teste prova:

1. ALLOWLIST FECHADA — argv constante, sem shell, sem texto do cliente na linha
   de comando. O texto variável entra pelo STDIN do comando (`--via-app`), e o
   CLI recusa chave fora do mapa. Chave contrabandeada (`forcar`, `--forte`)
   tem que REPROVAR.
2. IDENTIDADE DO SERVIDOR — `--de` sai de CFG["papel"], nunca do cliente.
   `?de=kimi` na URL ou `de` no payload não trocam a assinatura: foi aceitando
   identidade do cliente que apareceu na sala, em 17/08, uma mensagem assinada
   `bauer` que ele não escreveu.
3. MOSTRAR ANTES DE GASTAR OU MATAR — `plan`/`parar`/`refaz` só aceitam a
   confirmação acompanhada do recibo server-side, curto e descartável, emitido
   pela previsão correspondente. A confirmação é gate, não cortesia do JavaScript.

E o achado crítico de 17/08 vale para TODOS os gates desta casa: teste que só
vê sala NOVA não pega destruição de histórico. Este aqui cria a sala com
mensagens ANTES de qualquer comando e prova que o histórico sobrevive.
"""
from __future__ import annotations

import json
import os
import re
import runpy
import signal
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
IACHAT_CLI = CORE_BIN / "iachat"
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


def porta_livre(inicio: int = 59930) -> int:
    for p in range(inicio, inicio + 60):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise RuntimeError("sem porta livre")


def sobe(home: Path, porta: int, escrever: bool = True,
         raiz_iaswarm: Path | None = None,
         despacho: Path | None = None) -> tuple[subprocess.Popen, str]:
    """Sobe o servidor. `--escrever` obriga token, e é com token que o 401 é provado."""
    argv = [sys.executable, str(SERVIR), "--porta", str(porta)]
    if escrever:
        argv.append("--escrever")
    env = dict(os.environ, IACHAT_HOME=str(home), PYTHONPATH=str(CORE_BIN))
    if raiz_iaswarm is not None:
        env["IASWARM_RAIZ"] = str(raiz_iaswarm)
    if despacho is not None:
        env["IACHAT_DESPACHO"] = str(despacho)
    proc = subprocess.Popen(
        argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
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
        # modo leitura não gera token: a primeira URL anunciada já prova o servidor
        if f":{porta}/" in linha:
            break
    return proc, token


def pede(porta: int, rota: str, token: str | None = None,
         metodo: str = "GET", corpo: dict | None = None) -> tuple[int, str]:
    url = f"http://127.0.0.1:{porta}{rota}"
    if token:
        url += ("&" if "?" in rota else "?") + "t=" + token
    dados = json.dumps(corpo).encode() if corpo is not None else (
        b"{}" if metodo == "POST" else None)
    req = urllib.request.Request(url, method=metodo, data=dados)
    if dados is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
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


def posta(home: Path, de: str, texto: str) -> None:
    subprocess.run([sys.executable, str(IACHAT_CLI), "post",
                    "--de", de, "--para", "all", texto],
                   env=dict(os.environ, IACHAT_HOME=str(home),
                            PYTHONPATH=str(CORE_BIN)),
                   capture_output=True, text=True, timeout=30)


def main() -> int:
    if not CORE_BIN.exists():
        print(f"✗ núcleo ausente em {CORE_BIN}")
        return 1

    fonte = so_codigo_py(SERVIR.read_text(encoding="utf-8"))
    js = so_codigo_js(SALA_JS.read_text(encoding="utf-8"))

    print("— trava 1: a allowlist é fechada e o argv é constante —")
    bloco = fonte[fonte.index("COMANDOS_POST"):fonte.index("EXIGEM_CONFIRMACAO")]
    # Subconjunto — a mesma solução que o lado JS já tomou em `esperados <= nomes`
    # (trava 2): o conjunto EXATO reprova o sétimo comando POST nascido inteiro
    # (CLI + UI + servidor), crescimento legítimo e não defeito. O contrato é
    # duplo: os seis conhecidos continuam na allowlist, e a allowlist continua
    # FECHADA — o que quem prova são os gates ao lado (sem shell=True, argv de
    # constantes) e os REPROVA vivos (rota fora da lista → 404, chave
    # contrabandeada → 409), não a contagem de nomes.
    permitidos = set(re.findall(r'"(\w+)":\s*\(', bloco))
    conhecidos = {"goal", "plan", "concluir", "parar", "refaz", "decidi"}
    checa("os seis comandos conhecidos continuam na allowlist COMANDOS_POST",
          conhecidos <= permitidos,
          f"faltam {sorted(conhecidos - permitidos)} · na allowlist: {sorted(permitidos)}")
    checa("`quem` continua na allowlist de LEITURA, sozinho",
          re.search(r'COMANDOS_HTTP[^}]*"quem"', fonte) is not None)
    checa("sem shell=True em todo o servidor", "shell=True" not in fonte)
    corpo = fonte[fonte.index("def _comando_post"):fonte.index("def _garante_sino")]
    checa("o argv do POST é montado de constantes + papel do servidor",
          'argv += ["--de", CFG["papel"]]' in corpo
          and 'argv.append("--via-app")' in corpo
          and not re.search(r"argv\s*\+?=\s*\[?f['\"]", corpo))
    checa("`_comando_post` não lê query, corpo, cabeçalho nem caminho para o argv",
          not any(x in corpo for x in ("parse_qs", "self.path", "self.headers", "q.get")))
    checa("rota paramétrica `/api/comando` não existe", "/api/comando" not in fonte)
    checa("todo POST de comando passa pelo gate de confirmação",
          "EXIGEM_CONFIRMACAO" in corpo and '"confirmado"' in corpo)
    modulo_servidor = runpy.run_path(str(SERVIR))
    emite_recibo = modulo_servidor.get("_emite_recibo")
    consome_recibo = modulo_servidor.get("_consome_recibo")
    ttl_recibo = modulo_servidor.get("RECIBO_TTL_S")
    checa("recibo tem validade curta, em minutos",
          isinstance(ttl_recibo, int) and 60 <= ttl_recibo <= 600,
          str(ttl_recibo))
    checa("servidor possui emissão e consumo próprios do recibo",
          callable(emite_recibo) and callable(consome_recibo))
    if callable(emite_recibo) and callable(consome_recibo) and isinstance(ttl_recibo, int):
        recibo_expira = emite_recibo(
            "refaz", {"ia": "codex", "seco": True}, "previsão exata", agora=1000.0)
        aceito, motivo = consome_recibo(
            "refaz", {"ia": "codex", "confirmado": True,
                      "recibo": recibo_expira}, agora=1000.0 + ttl_recibo + 0.1)
        checa("REPROVA: recibo expirado não confirma",
              aceito is False and "expir" in motivo.lower(), motivo)

    print("— trava 2: a paleta chama de verdade, e o CLI é quem existe —")
    cmds = comandos_do_js()
    # A contagem existe para provar que o PARSER leu, não para congelar quantos comandos
    # o produto tem. `== 7` reprovaria o oitavo comando sem haver defeito — e o dono já
    # pediu que os comandos evoluíssem. O que é contrato são os sete NOMES conhecidos
    # estarem lá; o que é acidente é o total.
    #
    # Prevenção com evidência, não especulação: esta classe (gate que cobra forma em vez
    # de comportamento) reprovou crescimento legítimo QUATRO vezes em 18/08 — lista fixa
    # de assets, mensagem literal do zsh, linha literal do foco, contagem de abas.
    nomes = {c["cmd"] for c in cmds}
    esperados = {"/goal", "/plan", "/concluir", "/quem", "/parar", "/refaz", "/decidi"}
    checa("a tabela COMANDOS foi lida do sala.js", len(cmds) >= 1, str(len(cmds)))
    checa("os comandos conhecidos continuam na tabela", esperados <= nomes,
          f"faltam {sorted(esperados - nomes)}")
    checa("o campo mentiroso `pronto:` não existe",
          not re.search(r"\bpronto:\s*(true|false)", js))
    checa("os sete comandos atravessam o servidor (`onde:'aqui'`)",
          all(c["onde"] == "aqui" for c in cmds),
          str([(c["cmd"], c["onde"]) for c in cmds]))
    ajuda = subprocess.run([sys.executable, str(COMANDO_CLI), "--help"],
                           capture_output=True, text=True)
    subcomandos = set(re.findall(r"\b(goal|plan|concluir|parar|quem|decidi|refaz)\b",
                                 ajuda.stdout))
    faltando = [c["cmd"] for c in cmds if c["cmd"].lstrip("/") not in subcomandos]
    checa("REPROVA: todo comando da paleta existe no iachat-comando",
          not faltando, f"sem par no CLI: {faltando}")
    ruins = []
    for c in cmds:
        if not c["linha"]:
            continue
        sub = c["linha"].split()[1]
        r = subprocess.run([sys.executable, str(COMANDO_CLI), sub, "--help"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            ruins.append((c["cmd"], f"`{sub} --help` deu rc={r.returncode}"))
    checa("REPROVA: a linha de degradação oferecida é executável de verdade",
          not ruins, str(ruins))
    corpo_envia = js[js.index("async function envia()"):]
    corpo_envia = corpo_envia[:corpo_envia.index("/api/post")]
    checa("REPROVA: `envia` consulta a tabela ANTES de postar",
          "cmdDe(txt)" in corpo_envia and "rodaComando(c" in corpo_envia,
          corpo_envia[-160:].replace("\n", " "))
    checa("a interface degrada para a linha do terminal quando falta rota",
          "degrada" in js and "mostraLinha(c)" in js)

    print("— as classes do painel não são inventadas —")
    css = ESTILO.read_text(encoding="utf-8")
    trecho = js[js.index("function painelPaleta"):js.index("function escolhePaleta")]
    classes = sorted({c for atr in re.findall(r'class="([^"]+)"', trecho)
                      for c in atr.split()})
    ausentes = [c for c in classes if f".{c}" not in css]
    checa("REPROVA: toda classe usada nos painéis já existe no CSS",
          not ausentes, f"inventadas: {ausentes} · usadas: {classes}")

    print("— o controle remoto tem exatamente as duas ações contratadas —")
    botoes_remotos = re.findall(r'data-remoto-acao="([^"]+)"', js)
    checa("a página do worker oferece só parar e refaz",
          sorted(botoes_remotos) == ["parar", "refaz"], str(botoes_remotos))
    checa("as ações remotas usam o mesmo prever → recibo → confirmar",
          "async function acaoRemota" in js
          and "seco:true" in js
          and "confirmado:true" in js
          and "recibo" in js)
    checa("o remoto envia run e ia como dados, nunca como linha de comando",
          re.search(r"\{run:[^,]+,\s*ia:[^,]+,\s*seco:true\}", js) is not None)

    home = Path(tempfile.mkdtemp(prefix="ui-comandos-"))
    raiz_iaswarm = home / "iaswarm-runs"
    run_seguro = raiz_iaswarm / "run-seguro"
    for nome in ("logs", "resultados", "progress", "contratos"):
        (run_seguro / nome).mkdir(parents=True, exist_ok=True)
    (run_seguro / "workers.tsv").write_text(
        "codex\tcodex\t2\tcontratos/codex.md\n"
        "kimi\tkimi\t2\tcontratos/kimi.md\n",
        encoding="utf-8",
    )
    (run_seguro / "contratos" / "codex.md").write_text(
        "# worker falso seguro\n", encoding="utf-8"
    )
    (run_seguro / "contratos" / "kimi.md").write_text(
        "# worker morto de controle\n", encoding="utf-8"
    )
    despacho_fake = home / "despacho-falso.py"
    despacho_fake.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "from pathlib import Path\n"
        "Path(sys.argv[4]).write_text('worker falso redisparado\\n', encoding='utf-8')\n"
        "Path(sys.argv[5]).write_text('missão: worker falso\\nresultado: seguro\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )
    despacho_fake.chmod(0o700)
    fake_swarm = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(300)",
         str(run_seguro / "contratos" / "codex.md")],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    (run_seguro / "logs" / "codex.pid").write_text(
        f"{fake_swarm.pid}\n", encoding="utf-8"
    )
    (run_seguro / "logs" / "kimi.pid").write_text("999999\n", encoding="utf-8")
    porta = porta_livre()
    proc, token = sobe(
        home, porta, raiz_iaswarm=raiz_iaswarm, despacho=despacho_fake
    )
    fake = None
    try:
        if not token:
            checa("servidor subiu e anunciou o token", False, "sem token no stdout")
            return 1

        print("— identificadores IASWARM morrem também na borda do servidor —")
        invalidos_http = (
            ("/api/parar", {"run": "../fora", "ia": "codex", "seco": True}),
            ("/api/refaz", {"run": "../fora", "ia": "codex", "seco": True}),
            ("/api/parar", {"run": "run-seguro", "ia": "co/dex", "seco": True}),
            ("/api/refaz", {"run": "run-seguro", "ia": "co dex", "seco": True}),
            ("/api/parar", {"run": "r" * 81, "ia": "codex", "seco": True}),
            ("/api/refaz", {"run": "run-seguro", "ia": "i" * 81, "seco": True}),
        )
        for rota, payload_ruim in invalidos_http:
            cod, corpo_resp = pede(porta, rota, token, "POST", payload_ruim)
            checa(
                f"REPROVA no servidor: {rota} recusa identificador ruim",
                cod == 400 and "identificador" in corpo_resp.lower(),
                f"HTTP {cod}: {corpo_resp[:160]}",
            )

        print("— controle remoto IASWARM: dois tempos e worker falso seguro —")
        alvo = {"run": "run-seguro", "ia": "codex"}
        cod, corpo_resp = pede(
            porta, "/api/parar", token, "POST", {**alvo, "seco": True}
        )
        d = json.loads(corpo_resp) if corpo_resp else {}
        recibo_parar_cruzado = d.get("recibo")
        checa("previsão de parar o worker exato traz recibo",
              cod == 200 and isinstance(recibo_parar_cruzado, str)
              and str(fake_swarm.pid) in d.get("saida", ""),
              f"HTTP {cod}: {corpo_resp[:180]}")
        checa("a previsão IASWARM não mata", fake_swarm.poll() is None)

        cod, corpo_resp = pede(
            porta, "/api/refaz", token, "POST",
            {**alvo, "confirmado": True, "recibo": recibo_parar_cruzado},
        )
        checa("REPROVA: recibo de parar não confirma refaz no mesmo worker",
              cod == 400 and "recibo" in corpo_resp.lower(),
              f"HTTP {cod}: {corpo_resp[:150]}")

        cod, corpo_resp = pede(
            porta, "/api/parar", token, "POST", {**alvo, "seco": True}
        )
        recibo_ia = (json.loads(corpo_resp) if corpo_resp else {}).get("recibo")
        cod, corpo_resp = pede(
            porta, "/api/parar", token, "POST",
            {"run": "run-seguro", "ia": "kimi", "confirmado": True,
             "recibo": recibo_ia},
        )
        checa("REPROVA: recibo de --ia codex não confirma --ia kimi",
              cod == 400 and "argumentos" in corpo_resp.lower(),
              f"HTTP {cod}: {corpo_resp[:150]}")

        cod, corpo_resp = pede(
            porta, "/api/parar", token, "POST", {**alvo, "seco": True}
        )
        d = json.loads(corpo_resp) if corpo_resp else {}
        recibo_parar = d.get("recibo")
        cod, corpo_resp = pede(
            porta, "/api/parar", token, "POST",
            {**alvo, "confirmado": True, "recibo": recibo_parar},
        )
        time.sleep(0.4)
        checa("caminho honesto: parar confirmado mata só o worker falso",
              cod == 200 and fake_swarm.poll() is not None,
              f"HTTP {cod}: {corpo_resp[:180]}")

        cod, corpo_resp = pede(
            porta, "/api/refaz", token, "POST", {**alvo, "seco": True}
        )
        d = json.loads(corpo_resp) if corpo_resp else {}
        recibo_refaz_run = d.get("recibo")
        checa("previsão de refaz do worker parado traz recibo",
              cod == 200 and isinstance(recibo_refaz_run, str),
              f"HTTP {cod}: {corpo_resp[:180]}")
        cod, corpo_resp = pede(
            porta, "/api/refaz", token, "POST",
            {**alvo, "confirmado": True, "recibo": recibo_refaz_run},
        )
        limite_resultado = time.time() + 4
        resultado_fake = run_seguro / "resultados" / "codex.md"
        while time.time() < limite_resultado and not resultado_fake.exists():
            time.sleep(0.05)
        checa("caminho honesto: refaz confirmado aciona o dispatcher seguro",
              cod == 200 and resultado_fake.is_file()
              and "resultado: seguro" in resultado_fake.read_text(encoding="utf-8"),
              f"HTTP {cod}: {corpo_resp[:180]}")

        print("— trava 3: confirmação enviada de primeira morre no servidor —")
        confirmacoes_sem_previsao = (
            ("/api/plan", {"confirmado": True}),
            ("/api/parar", {"confirmado": True}),
            ("/api/refaz", {"ia": "codex", "confirmado": True}),
        )
        for rota, payload_direto in confirmacoes_sem_previsao:
            cod, corpo_resp = pede(porta, rota, token, "POST", payload_direto)
            checa(f"REPROVA: {rota} confirmado direto exige previsão + recibo",
                  cod == 400 and "recibo" in corpo_resp.lower(),
                  f"HTTP {cod}: {corpo_resp[:140]}")

        print("— sala COM HISTÓRIA antes de qualquer comando (achado de 17/08) —")
        posta(home, "claude", "primeira mensagem da sala de teste")
        posta(home, "codex", "segunda mensagem, anterior a qualquer comando")
        chat = (home / "iachat.md")
        antes = chat.read_text(encoding="utf-8") if chat.exists() else ""
        checa("a sala de teste nasce com duas mensagens anteriores",
              "primeira mensagem da sala de teste" in antes
              and "segunda mensagem" in antes)

        print("— trava 3 (ida): goal atravessa e assina com o papel do servidor —")
        cod, corpo_resp = pede(porta, "/api/goal", token, "POST",
                               {"texto": "objetivo aberto pelo app no gate"})
        d = json.loads(corpo_resp) if corpo_resp else {}
        checa("POST /api/goal responde 200 com ok", cod == 200 and d.get("ok") is True,
              f"HTTP {cod}: {corpo_resp[:120]}")
        estado = json.loads((home / "comando" / "estado.json").read_text())
        checa("a missão abre no disco com o texto exato do dono",
              estado.get("goal") == "objetivo aberto pelo app no gate",
              str(estado.get("goal")))
        checa("o autor é o PAPEL DO SERVIDOR (bauer), nunca o cliente",
              estado.get("de") == "bauer", str(estado.get("de")))

        cod, _ = pede(porta, "/api/goal?de=kimi&forcar=1&novo=1", token, "POST",
                      {"texto": "tentativa de trocar a assinatura"})
        estado2 = json.loads((home / "comando" / "estado.json").read_text())
        checa("REPROVA: ?de=kimi na URL não troca a assinatura",
              estado2.get("de") == "bauer", str(estado2.get("de")))

        depois = chat.read_text(encoding="utf-8")
        checa("o histórico ANTIGO sobrevive ao comando (o achado de 17/08)",
              "primeira mensagem da sala de teste" in depois
              and "segunda mensagem" in depois)
        checa("o anúncio do goal entra DEPOIS do histórico, não no lugar dele",
              depois.index("primeira mensagem") < depois.index("objetivo aberto pelo app"))

        print("— trava 3 (volta): gastar/matar exige previsão + confirmação —")
        cod, corpo_resp = pede(porta, "/api/parar", token, "POST", {})
        checa("REPROVA: parar sem previsão nem confirmação morre com 400",
              cod == 400 and "seco" in corpo_resp and "confirmado" in corpo_resp,
              f"HTTP {cod}: {corpo_resp[:140]}")
        cod, corpo_resp = pede(porta, "/api/plan", token, "POST", {"colher": False})
        checa("REPROVA: plan sem previsão nem confirmação morre com 400",
              cod == 400, f"HTTP {cod}")
        cod, corpo_resp = pede(porta, "/api/refaz", token, "POST", {"ia": "codex"})
        checa("REPROVA: refaz sem previsão nem confirmação morre com 400",
              cod == 400, f"HTTP {cod}")
        cod, corpo_resp = pede(porta, "/api/plan", token, "POST", {"seco": True})
        d = json.loads(corpo_resp)
        checa("a previsão atravessa sem confirmação (é leitura)",
              cod == 200 and d.get("ok") is True
              and "seriam despachadas" in d.get("saida", ""),
              f"HTTP {cod}: {corpo_resp[:140]}")
        checa("a previsão de plan traz recibo nascido no servidor",
              isinstance(d.get("recibo"), str) and len(d["recibo"]) >= 32,
              corpo_resp[:180])

        print("— o parar de verdade, contra um worker vivo —")
        missao = home / "comando" / "m1"
        prompt = missao / "logs" / "fake.prompt.txt"
        prompt.parent.mkdir(parents=True, exist_ok=True)
        prompt.write_text("prompt fake do gate\n", encoding="utf-8")
        fake = subprocess.Popen(
            ["python3", "-c", "import time; time.sleep(300)", str(prompt)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
        time.sleep(0.4)
        lstart = subprocess.run(["ps", "-o", "lstart=", "-p", str(fake.pid)],
                                capture_output=True, text=True).stdout.strip()
        estado = json.loads((home / "comando" / "estado.json").read_text())
        estado["workers"] = {"fake": {
            "braco": "codex", "papel": "worker de teste", "pid": fake.pid,
            "lstart": lstart, "inicio": "2026-08-18T07:00:00-03:00",
            "estado": "rodando", "tentativas": 1,
            "log": str(missao / "logs" / "fake.log"),
            "plano": str(missao / "planos" / "fake.md"),
            "prompt": str(prompt),
        }, "codex": {
            "braco": "codex", "papel": "worker morto de teste", "pid": 999999,
            "lstart": "", "inicio": "2026-08-18T06:00:00-03:00",
            "estado": "falhou", "tentativas": 1,
            "log": str(missao / "logs" / "codex.log"),
            "plano": str(missao / "planos" / "codex.md"),
            "prompt": str(missao / "logs" / "codex.prompt.txt"),
        }}
        (home / "comando" / "estado.json").write_text(
            json.dumps(estado, indent=2), encoding="utf-8")

        cod, corpo_resp = pede(porta, "/api/parar", token, "POST", {"seco": True})
        d = json.loads(corpo_resp)
        recibo_cruzado = d.get("recibo")
        checa("a previsão mostra o worker vivo, com pid",
              cod == 200 and str(fake.pid) in d.get("saida", ""),
              corpo_resp[:160])
        checa("a previsão de parar traz recibo server-side",
              isinstance(recibo_cruzado, str) and len(recibo_cruzado) >= 32,
              corpo_resp[:180])
        checa("a previsão NÃO mata", fake.poll() is None)

        cod, corpo_resp = pede(porta, "/api/plan", token, "POST",
                               {"confirmado": True, "recibo": recibo_cruzado})
        checa("REPROVA: recibo de parar não confirma plan",
              cod == 400 and "recibo" in corpo_resp.lower(),
              f"HTTP {cod}: {corpo_resp[:140]}")

        cod, corpo_resp = pede(porta, "/api/refaz", token, "POST",
                               {"ia": "codex", "seco": True})
        d = json.loads(corpo_resp)
        recibo_refaz = d.get("recibo")
        checa("a previsão de refaz traz recibo server-side",
              cod == 200 and isinstance(recibo_refaz, str) and len(recibo_refaz) >= 32,
              f"HTTP {cod}: {corpo_resp[:180]}")
        cod, corpo_resp = pede(porta, "/api/refaz", token, "POST",
                               {"ia": "kimi", "confirmado": True,
                                "recibo": recibo_refaz})
        checa("REPROVA: recibo de refaz codex não confirma refaz kimi",
              cod == 400 and "recibo" in corpo_resp.lower(),
              f"HTTP {cod}: {corpo_resp[:140]}")
        cod, corpo_resp = pede(porta, "/api/refaz", token, "POST",
                               {"ia": "codex", "confirmado": True,
                                "recibo": recibo_refaz})
        checa("REPROVA: recibo que falhou por argumentos já queimou",
              cod == 400 and "recibo" in corpo_resp.lower(),
              f"HTTP {cod}: {corpo_resp[:140]}")

        cod, corpo_resp = pede(porta, "/api/parar", token, "POST", {"seco": True})
        d = json.loads(corpo_resp)
        recibo_parar = d.get("recibo")
        checa("nova previsão emite recibo novo para o caminho honesto",
              isinstance(recibo_parar, str) and recibo_parar != recibo_cruzado,
              corpo_resp[:180])

        cod, corpo_resp = pede(porta, "/api/parar", token, "POST",
                               {"confirmado": True, "recibo": recibo_parar})
        d = json.loads(corpo_resp)
        time.sleep(0.4)
        morto = fake.poll() is not None
        checa("o disparo confirmado mata o worker", cod == 200 and morto,
              f"HTTP {cod}: {corpo_resp[:140]}")
        cod_replay, corpo_replay = pede(
            porta, "/api/parar", token, "POST",
            {"confirmado": True, "recibo": recibo_parar})
        checa("REPROVA: segundo clique não reutiliza recibo queimado",
              cod_replay == 400 and "recibo" in corpo_replay.lower(),
              f"HTTP {cod_replay}: {corpo_replay[:140]}")
        estado = json.loads((home / "comando" / "estado.json").read_text())
        checa("o estado da missão registra o parar",
              estado.get("estado") == "parada"
              and estado["workers"]["fake"].get("estado") == "parado",
              f"{estado.get('estado')} / {estado['workers']['fake'].get('estado')}")

        print("— a allowlist recusa o que deve recusar —")
        cod, corpo_resp = pede(porta, "/api/goal", token, "POST",
                               {"texto": "x", "forcar": True})
        checa("REPROVA: chave `forcar` contrabandeada morre na borda do CLI",
              cod == 409 and "allowlist" in corpo_resp, corpo_resp[:140])
        cod, corpo_resp = pede(porta, "/api/parar", token, "POST",
                               {"seco": True, "--forte": True})
        checa("REPROVA: `--forte` contrabandeado não endurece o parar",
              cod == 409 and "allowlist" in corpo_resp, corpo_resp[:140])
        cod, corpo_resp = pede(porta, "/api/plan", token, "POST",
                               {"seco": True, "esperar": 9999})
        checa("REPROVA: `esperar` contrabandeado não bloqueia o servidor",
              cod == 409 and "allowlist" in corpo_resp, corpo_resp[:140])

        for rota in ("/api/naoexiste", "/api/comando?nome=parar"):
            cod, _ = pede(porta, rota, token, "POST", {})
            checa(f"REPROVA: POST {rota} não existe", cod == 404, f"HTTP {cod}")
        for rota in ("/api/goal", "/api/parar", "/api/decidi"):
            cod, _ = pede(porta, rota, token)
            checa(f"REPROVA: GET {rota} não existe (comando é POST)",
                  cod == 404, f"HTTP {cod}")
        cod, _ = pede(porta, "/api/quem", token, "POST", {})
        checa("REPROVA: POST em /api/quem não existe (comando não se escreve)",
              cod == 404, f"HTTP {cod}")
        cod, _ = pede(porta, "/api/quem")
        checa("REPROVA: /api/quem sem token devolve 401", cod == 401, f"HTTP {cod}")
        cod, _ = pede(porta, "/api/goal", None, "POST", {"texto": "x"})
        checa("REPROVA: POST /api/goal sem token devolve 401", cod == 401, f"HTTP {cod}")
        cod, _ = pede(porta, "/api/goal", "token-errado", "POST", {"texto": "x"})
        checa("REPROVA: POST /api/goal com token errado devolve 401",
              cod == 401, f"HTTP {cod}")

        print("— concluir e decidi, com as recusas deles —")
        cod, corpo_resp = pede(porta, "/api/concluir", token, "POST",
                               {"texto": "autorização sem plano"})
        checa("REPROVA: concluir sem plano no disco é assinar em branco (409)",
              cod == 409 and "plano" in corpo_resp, corpo_resp[:140])
        planos = missao / "planos"
        planos.mkdir(parents=True, exist_ok=True)
        (planos / "fake.md").write_text("plano fake do gate\n", encoding="utf-8")
        cod, corpo_resp = pede(porta, "/api/concluir", token, "POST",
                               {"texto": "aplicar só o passo 1"})
        d = json.loads(corpo_resp) if corpo_resp else {}
        estado = json.loads((home / "comando" / "estado.json").read_text())
        checa("concluir com plano autoriza e registra",
              cod == 200 and estado.get("estado") == "autorizada",
              f"HTTP {cod} · {estado.get('estado')}")
        cod, corpo_resp = pede(porta, "/api/decidi", token, "POST", {"texto": "d"})
        checa("REPROVA: decidi sem motivo morre no gate do CLI",
              cod == 409 and "porque" in corpo_resp.lower(), corpo_resp[:140])
        cod, corpo_resp = pede(porta, "/api/decidi", token, "POST",
                               {"texto": "decisão do gate L2",
                                "porque": "prova de que o registro atravessa",
                                "sobre": "gate"})
        decisoes = (home / "decisoes.md")
        depois = chat.read_text(encoding="utf-8")
        checa("decidi grava no registro E anuncia com a marca DECIDIDO:",
              cod == 200 and decisoes.exists()
              and "decisão do gate L2" in decisoes.read_text(encoding="utf-8")
              and "DECIDIDO:" in depois,
              f"HTTP {cod}")
        checa("o histórico antigo continua inteiro depois de tudo",
              "primeira mensagem da sala de teste" in depois
              and "segunda mensagem" in depois)

        _, sem = pede(porta, "/api/quem", token)
        _, com = pede(porta, "/api/quem?run=/etc&nome=parar&--forte=1", token)
        checa("REPROVA: parâmetro do cliente não muda o comando (resposta idêntica)",
              json.loads(sem).get("quem") == json.loads(com).get("quem"))
    finally:
        if fake is not None and fake.poll() is None:
            fake.terminate()
            try:
                fake.wait(timeout=5)
            except subprocess.TimeoutExpired:
                fake.kill()
        if fake_swarm.poll() is None:
            fake_swarm.terminate()
            try:
                fake_swarm.wait(timeout=5)
            except subprocess.TimeoutExpired:
                fake_swarm.kill()
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        import shutil
        shutil.rmtree(home, ignore_errors=True)

    print("— servidor em modo leitura: comando não atravessa —")
    home2 = Path(tempfile.mkdtemp(prefix="ui-comandos-ro-"))
    porta2 = porta_livre(porta + 30)
    proc2, _token2 = sobe(home2, porta2, escrever=False)
    try:
        cod, corpo_resp = pede(porta2, "/api/goal", None, "POST", {"texto": "x"})
        checa("REPROVA: sem --escrever, POST de comando toma 403",
              cod == 403, f"HTTP {cod}")
        cod, _ = pede(porta2, "/api/quem")
        checa("…mas a leitura continua aberta", cod == 200, f"HTTP {cod}")
    finally:
        proc2.terminate()
        try:
            proc2.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc2.kill()
        import shutil
        shutil.rmtree(home2, ignore_errors=True)

    print()
    print(f"{_ok} ✔  {_falhou} ✗")
    return 1 if _falhou else 0


if __name__ == "__main__":
    sys.exit(main())
