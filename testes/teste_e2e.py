#!/usr/bin/env python3
"""O ciclo do produto, ponta a ponta: abrir → a sala carrega → postar → chegar.

A bateria prova PEÇAS. Este arquivo prova o CONJUNTO, e existe por um defeito real:
o `flush` do servidor. Cada peça estava certa — o token era gerado, o log era
escrito, o lançador sabia procurar — e o app não abria, porque com o stdout num
arquivo o Python usa buffer de bloco e as ~150 bytes da URL nunca saíam. Nenhum
teste de peça podia pegar isso. Um teste de ciclo pega.

Alvo: `ui/servir.py`, que é o servidor que o `lancador.py` de fato sobe. O esboço
do bundle é reserva e tem cobertura própria em `teste_coerencia_servidores.py`.

Sala em `IACHAT_HOME` temporário e portas 59970+: a sala viva não é tocada.
"""
from __future__ import annotations

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
import uuid
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
UI = RAIZ / "ui"
SERVIDOR = UI / "servir.py"
CORE_BIN = RAIZ.parent / "ia-chat" / "bin"
LSOF = Path("/usr/sbin/lsof")
PAPEL = "codex"                 # quem o servidor assina
DESTINO = "claude"              # quem é nominado
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


def sobe(servidor: Path, porta: int, sala: Path, home: Path, log: Path,
         espera: float = 12.0) -> tuple[subprocess.Popen, str]:
    """Sobe como o LANÇADOR sobe, e o detalhe é o teste: stdout num ARQUIVO e
    sem `-u`. É a única condição em que o defeito do buffer aparece — subir com
    o terminal na frente esconde o defeito, porque tty é line-buffered.

    Devolve token vazio quando o log não entrega: é o vermelho, não uma exceção.
    """
    with log.open("wb") as saida:
        proc = subprocess.Popen(
            [sys.executable, str(servidor), "--porta", str(porta),
             "--escrever", "--papel", PAPEL],
            env=ambiente(sala, home), stdout=saida, stderr=subprocess.STDOUT,
        )
    limite = time.time() + espera
    while time.time() < limite:
        if proc.poll() is not None:
            break
        achado = re.search(r"\?t=([A-Za-z0-9_-]+)",
                           log.read_text(encoding="utf-8", errors="replace"))
        if achado:
            return proc, achado.group(1)
        time.sleep(0.1)
    return proc, ""


def responde(porta: int, token: str, prazo: float = 10.0) -> bool:
    limite = time.time() + prazo
    while time.time() < limite:
        try:
            if pede(porta, "/api/estado", token)[0] == 200:
                return True
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.1)
    return False


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
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(pedido, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read())
        except ValueError:
            return exc.code, {}


def mensagens_no_arquivo(sala: Path) -> list[dict]:
    """Lê o `iachat.md` como o núcleo o escreveu — a prova fora do servidor.

    Perguntar à API se o post entrou é perguntar ao réu. O arquivo é a sala.
    """
    md = (sala / "iachat.md").read_text(encoding="utf-8")
    marcas = list(RE_META.finditer(md))
    saida = []
    for i, m in enumerate(marcas):
        fim = marcas[i + 1].start() if i + 1 < len(marcas) else len(md)
        saida.append({
            "n": int(m.group(1)), "de": m.group(2),
            "para": [p for p in m.group(3).split(",") if p],
            "corpo": md[m.end():fim],
        })
    return saida


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


# ── SSE em socket cru: deadline em toda leitura, nunca um recv que trava ──────
def abre_sse(porta: int, token: str, desde: int = 0) -> tuple[socket.socket, str, bytes]:
    """`desde` importa e não é detalhe: a interface abre o stream com o número que
    já carregou pelo `/api/sala`. Com `desde=0` o servidor reprisa o histórico —
    correto, e é o que faz uma janela nova nascer cheia."""
    s = socket.create_connection(("127.0.0.1", porta), timeout=5)
    s.sendall(
        f"GET {com_token(f'/api/stream?desde={desde}', token)} HTTP/1.1\r\n"
        f"Host: 127.0.0.1:{porta}\r\nAccept: text/event-stream\r\n\r\n".encode()
    )
    buf = b""
    limite = time.time() + 5
    while b"\r\n\r\n" not in buf and time.time() < limite:
        try:
            pedaco = s.recv(4096)
        except (socket.timeout, TimeoutError):
            break
        if not pedaco:
            break
        buf += pedaco
    cabecalho, _, resto = buf.partition(b"\r\n\r\n")
    return s, cabecalho.decode(errors="replace"), resto


def escuta_sse(s: socket.socket, inicio: bytes, alvo: str,
               prazo: float) -> tuple[bool, str]:
    """Escuta até achar `alvo` ou o prazo acabar. Nunca bloqueia além do prazo."""
    buf = inicio
    s.settimeout(0.5)
    limite = time.time() + prazo
    while time.time() < limite:
        if alvo in buf.decode(errors="replace"):
            break
        try:
            pedaco = s.recv(4096)
        except (socket.timeout, TimeoutError):
            continue
        except OSError:
            break
        if not pedaco:
            break
        buf += pedaco
    texto = buf.decode(errors="replace")
    return alvo in texto, texto


# ═════════════════════════════════════════════════════════════════════════════
def ciclo(tmp: Path, porta: int) -> None:
    sala, home = tmp / "sala", tmp / "home"
    log = tmp / "servidor.log"

    # ── 1 · abrir pelo caminho do usuário final ──────────────────────────────
    proc, token = sobe(SERVIDOR, porta, sala, home, log)
    try:
        checa("1 · o token aparece no log com stdout em arquivo e sem -u",
              bool(token), log.read_text(errors="replace")[:300])
        checa("1 · o servidor responde na porta que o lançador usaria",
              responde(porta, token))
        if not token:
            return

        # ── 2 · a sala carrega inteira ───────────────────────────────────────
        status, corpo = pede(porta, "/", token)
        html = corpo.decode("utf-8", errors="replace")
        checa("2 · GET / devolve 200", status == 200, f"status={status}")
        checa("2 · a página é a interface, não um esqueleto",
              "<html" in html and "sala.js" in html and "estilo.css" in html)
        # Os assets saem do PRÓPRIO HTML: se a interface ganhar um arquivo novo
        # e o servidor não o servir, este teste pega sem ninguém editar a lista.
        ativos = sorted({
            a for a in re.findall(r'(?:href|src)="([^"]+)"', html)
            if not a.startswith(("#", "data:", "http"))
        })
        checa("2 · o HTML referencia os assets esperados",
              set(ativos) == {"/favicon.ico", "estilo.css", "sala.js"}, str(ativos))
        for ativo in ativos:
            rota = ativo if ativo.startswith("/") else "/" + ativo
            st, dados = pede(porta, rota, token)
            checa(f"2 · {rota} devolve 200 e não vem vazio",
                  st == 200 and len(dados) > 0, f"status={st} bytes={len(dados)}")
        # Controle: sem isto, um servidor que responde 200 a tudo passaria.
        checa("2 · asset inexistente devolve 404 (controle)",
              pede(porta, "/nao-existe.css", token)[0] == 404)

        # ── 3 · postar entra na sala DE VERDADE ──────────────────────────────
        marca = f"e2e-{uuid.uuid4().hex[:10]}"
        st, resposta = posta(porta, token, {"texto": marca, "para": [DESTINO]})
        checa("3 · POST /api/post devolve 200", st == 200, f"status={st} {resposta}")
        n_msg = resposta.get("n")
        msgs = mensagens_no_arquivo(sala)
        entrou = [m for m in msgs if marca in m["corpo"]]
        checa("3 · a mensagem está no iachat.md do IACHAT_HOME temporário",
              len(entrou) == 1, f"achadas={len(entrou)}")
        checa("3 · texto nunca postado não aparece no arquivo (controle)",
              not any("e2e-jamais-postado" in m["corpo"] for m in msgs))
        checa("3 · o número devolvido pela API é o número no arquivo",
              bool(entrou) and entrou[0]["n"] == n_msg,
              f"api={n_msg} arquivo={entrou[0]['n'] if entrou else None}")

        # ── 4 · a identidade é do SERVIDOR, nunca do cliente ─────────────────
        marca4 = f"e2e-identidade-{uuid.uuid4().hex[:8]}"
        st4, _ = posta(porta, token,
                       {"de": "claude", "texto": marca4, "para": [DESTINO]})
        checa("4 · POST com `de` forjado é aceito (não é erro, é ignorado)",
              st4 == 200, f"status={st4}")
        forjada = [m for m in mensagens_no_arquivo(sala) if marca4 in m["corpo"]]
        checa(f"4 · a mensagem saiu assinada `{PAPEL}`, o --papel do servidor",
              len(forjada) == 1 and forjada[0]["de"] == PAPEL,
              f"de={forjada[0]['de'] if forjada else None}")
        checa("4 · o `de` do payload NÃO virou assinatura",
              bool(forjada) and forjada[0]["de"] != "claude")

        # ── 5 · o destinatário recebe, e o autor não ─────────────────────────
        # É a promessa central do ia-chat: o sino toca só para quem foi chamado.
        flag_destino = sala / "pendente" / f"{DESTINO}.md"
        flag_autor = sala / "pendente" / f"{PAPEL}.md"
        checa(f"5 · o destinatário @{DESTINO} recebeu o flag com a mensagem #{n_msg}",
              flag_destino.is_file() and f"#{n_msg}" in flag_destino.read_text(),
              f"existe={flag_destino.is_file()}")
        checa(f"5 · anti-eco: o autor @{PAPEL} NÃO recebeu flag da própria mensagem",
              not flag_autor.is_file() or f"#{n_msg}" not in flag_autor.read_text())

        # ── 6 · a leitura pela API bate com o arquivo ────────────────────────
        msgs = mensagens_no_arquivo(sala)
        ultima_arquivo = max(m["n"] for m in msgs)
        st, cru = pede(porta, "/api/estado", token)
        estado = json.loads(cru)
        checa("6 · o contador de /api/estado é o último número do arquivo",
              estado.get("ultima") == ultima_arquivo,
              f"api={estado.get('ultima')} arquivo={ultima_arquivo}")
        api_sala = json.loads(pede(porta, "/api/sala", token)[1])
        checa("6 · /api/sala devolve exatamente as mensagens do arquivo",
              len(api_sala.get("msgs", [])) == len(msgs),
              f"api={len(api_sala.get('msgs', []))} arquivo={len(msgs)}")
        checa("6 · /api/sala traz a sala (quem está nela e quem assina)",
              api_sala.get("sala", {}).get("papel") == PAPEL
              and DESTINO in api_sala.get("sala", {}).get("na_sala", []))
        dirigida = json.loads(pede(porta, f"/api/sala?desde={ultima_arquivo}", token)[1])
        checa("6 · leitura dirigida: desde=última não devolve nada (controle)",
              dirigida.get("msgs") == [], str(dirigida.get("msgs"))[:120])
        uma = json.loads(pede(porta, f"/api/sala?desde={ultima_arquivo - 1}", token)[1])
        checa("6 · leitura dirigida: desde=última-1 devolve exatamente uma",
              len(uma.get("msgs", [])) == 1, str(len(uma.get("msgs", []))))

        # ── 7 · o ao vivo ────────────────────────────────────────────────────
        # Janela nova: abre em desde=0 e nasce com o histórico na tela.
        s0, cab0, resto0 = abre_sse(porta, token, desde=0)
        try:
            checa("7 · /api/stream abre como text/event-stream",
                  "200" in cab0.split("\r\n")[0]
                  and "text/event-stream" in cab0.lower(), cab0.split("\r\n")[0])
            veio, texto0 = escuta_sse(s0, resto0, marca, 6.0)
            checa("7 · janela nova (desde=0) recebe o histórico pelo stream",
                  veio, texto0[-200:])
        finally:
            s0.close()

        # Janela em dia: abre no número que já tem e só recebe o que for novo.
        s, cabecalho, resto = abre_sse(porta, token, desde=ultima_arquivo)
        try:
            # Controle: se um `event: msg` aparecesse ANTES do post, o evento que
            # vamos ver depois não provaria nada. Foi por não passar `desde` que
            # este controle acusou vermelho na primeira rodada — o histórico
            # chegava sozinho, e chegava certo.
            houve_antes, _ = escuta_sse(s, resto, "event: msg", 2.0)
            checa("7 · janela em dia: nada de `event: msg` no silêncio (controle)",
                  not houve_antes)

            marca7 = f"e2e-aovivo-{uuid.uuid4().hex[:8]}"
            posta(porta, token, {"texto": marca7, "para": [DESTINO]})
            chegou, texto = escuta_sse(s, b"", marca7, 12.0)
            checa("7 · o evento da mensagem nova chega pelo stream",
                  chegou, texto[-200:])
            checa("7 · o evento vem no formato SSE, com id e event",
                  chegou and "event: msg" in texto and "id: " in texto)
        finally:
            s.close()
    finally:
        rescaldo, detalhe = encerra(proc, porta)
        checa(f"· o servidor morreu e a porta {porta} não tem LISTEN",
              rescaldo, detalhe)


def controle_do_flush(tmp: Path, porta: int) -> None:
    """O caso que REPROVA o item 1 — o defeito histórico, reproduzido de propósito.

    Numa CÓPIA da `ui/` (o original nunca é tocado), tira-se o `flush=True` de
    todos os prints. O servidor sobe e atende igual; o log fica vazio; o lançador
    nunca acha o token. É exatamente o que aconteceu, e é o que o item 1 pega.
    """
    copia = tmp / "ui-sem-flush"
    shutil.copytree(UI, copia, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    alvo = copia / "servir.py"
    texto = alvo.read_text(encoding="utf-8")
    checa("N · o ponto da mutação existe no servidor real",
          ", flush=True)" in texto)
    alvo.write_text(texto.replace(", flush=True)", ")"), encoding="utf-8")
    checa("N · a cópia mutada não tem mais nenhum flush",
          ", flush=True)" not in alvo.read_text(encoding="utf-8"))

    proc, token = sobe(alvo, porta, tmp / "sala-neg", tmp / "home-neg",
                       tmp / "neg.log", espera=6.0)
    try:
        checa("N · sem flush, o token NÃO aparece no log — o app não abriria",
              token == "", f"token achado: {token!r}")
        checa("N · e o servidor estava vivo o tempo todo (o defeito é só o log)",
              proc.poll() is None)
    finally:
        rescaldo, detalhe = encerra(proc, porta)
        checa(f"N · o controle negativo não deixou LISTEN na porta {porta}",
              rescaldo, detalhe)
    checa("N · o `ui/servir.py` do repo continua com os flushes intactos",
          ", flush=True)" in SERVIDOR.read_text(encoding="utf-8"))


def main() -> int:
    print("teste_e2e")
    checa("núcleo iachat_core.py disponível", (CORE_BIN / "iachat_core.py").is_file())
    checa("lsof disponível para o rescaldo", LSOF.is_file())
    checa("o servidor do app existe", SERVIDOR.is_file())
    if not (CORE_BIN / "iachat_core.py").is_file() or not LSOF.is_file():
        print(f"\n{_ok} ✔  {_falhou} ✗")
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="iachat-e2e-"))
    try:
        porta = porta_livre(59970)
        ciclo(tmp, porta)
        controle_do_flush(tmp, porta_livre(porta + 1))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{_ok} ✔  {_falhou} ✗")
    return 1 if _falhou else 0


if __name__ == "__main__":
    raise SystemExit(main())
