#!/usr/bin/env python3
"""lancador.py — o invólucro nativo do ia-chat.

Sobe o servidor da sala numa porta livre, espera ele responder, abre a janela e —
o motivo real deste arquivo existir — **mata o servidor quando a janela fecha**.

    Contents/MacOS/ia-chat  ->  este arquivo

O ciclo de vida, inteiro, em três garantias:

 1. **Nada de porta órfã.** O servidor não é filho direto deste processo: é neto,
    através de um `sh` que fica bloqueado lendo um cano vindo daqui. Se este
    processo morrer — saída limpa, SIGTERM do Dock ou `kill -9` do Monitor de
    Atividade —, o cano fecha, o `sh` acorda no EOF e mata o servidor. Não existe
    caminho de morte deste lançador que deixe o servidor de pé.
 2. **Uma instância só.** Segundo duplo-clique não sobe segundo servidor: acha a
    instância viva pelo `instancia.json`, confere que ela responde de verdade
    (probe HTTP com o token) e reabre a janela naquela URL.
 3. **Só o que é meu.** Todo `kill` daqui é no grupo de processos que este
    lançador criou (`start_new_session=True`) ou no navegador que ele mesmo
    abriu, num perfil dedicado. Nenhum PID de terceiro é tocado.

A janela fechada é detectada de fora, sem tocar no servidor: a página mantém uma
conexão SSE aberta em `/api/stream`, então "existe conexão TCP estabelecida nesta
porta" é o sinal de que alguém está olhando. Zero conexão por
`ESPERA_SEM_JANELA` segundos = ninguém olhando = hora de morrer.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SUPORTE = Path.home() / "Library" / "Application Support" / "ia-chat-app"
INSTANCIA = SUPORTE / "instancia.json"
LOG = SUPORTE / "servidor.log"
PERFIL = SUPORTE / "janela"          # perfil próprio do navegador: nunca o do dono
JANELA_PID = SUPORTE / "janela.pid"  # o cano lê daqui se o lançador for morto a -9

PORTA_PREFERIDA = 8787               # a do servidor; se ocupada, o SO escolhe
ESPERA_SERVIDOR = 20.0               # s até o servidor anunciar a URL
ESPERA_PRIMEIRA_JANELA = 60.0        # s de carência até a página conectar
ESPERA_SEM_JANELA = 12.0             # s sem nenhuma conexão = janela fechada
INTERVALO = 1.5                      # s entre rondas de vigia


# ─────────────────────────────────────────────────────────────────────────────
# ONDE ESTÃO AS PEÇAS
# ─────────────────────────────────────────────────────────────────────────────
def achar_core() -> Path | None:
    """A pasta que contém `iachat_core.py` — o núcleo que o servidor importa.

    Cuidado herdado do repo: `IACHAT_BIN` no `install.sh` significa "onde ficam os
    symlinks do PATH" (`~/.local/bin`), e ali NÃO mora o `iachat_core.py`. O
    servidor usa a mesma variável com outro sentido. Por isso aqui a pasta é
    encontrada por prova — a presença do arquivo — e nunca por confiança na env.
    """
    for c in (
        os.environ.get("IACHAT_CORE"),
        Path.home() / "Projetos" / "ia-chat" / "bin",
        os.environ.get("IACHAT_SCRIPTS"),
        Path.home() / ".claude" / "scripts" / "ia-chat",
    ):
        if c and (Path(c) / "iachat_core.py").is_file():
            return Path(c)
    return None


def achar_servidor() -> Path | None:
    """Qual servidor subir. A ordem é a que faz o app se comportar nos dois papéis.

    Rodando de dentro do repo (`~/Projetos/ia-chat-app/ia-chat.app`), o irmão
    `ui/servir.py` existe e ganha: quem está mexendo na interface vê a mudança no
    duplo clique seguinte, sem remontar nada. Instalado em `/Applications`, esse
    irmão não existe e vale a cópia congelada dentro do bundle — que é o que um
    app instalado deve ser: fechado em si.

    O esboço do `idea-servidor` fica por último, como reserva: ele carrega a
    página embutida no Python e serve a sala mesmo sem a pasta `ui/`.
    """
    aqui = Path(__file__).resolve().parent
    repo = aqui.parent.parent.parent          # …/ia-chat-app/ia-chat.app/… -> repo
    for c in (
        os.environ.get("IACHAT_SERVIDOR"),
        repo / "ui" / "servir.py",            # o repo vivo, quando é o caso
        aqui / "ui" / "servir.py",            # a cópia congelada no bundle
        Path.home() / "Projetos" / "ia-chat" / "bin" / "servidor.py",
        aqui / "servidor.py",                 # o esboço, reserva final
    ):
        if c and Path(c).is_file():
            return Path(c)
    return None


def escolher_python(core: Path) -> str | None:
    """O primeiro python3 que CONSEGUE importar o núcleo. Prova, não palpite."""
    prova = "import sys;sys.path.insert(0,%r);import iachat_core" % str(core)
    vistos = []
    for py in (
        sys.executable,
        "/opt/homebrew/bin/python3",
        "/usr/local/bin/python3",
        "/usr/bin/python3",
        shutil.which("python3"),
    ):
        if not py or py in vistos or not os.path.exists(py):
            continue
        vistos.append(py)
        r = subprocess.run([py, "-c", prova], capture_output=True)
        if r.returncode == 0:
            return py
    return None


# ─────────────────────────────────────────────────────────────────────────────
# PORTA E INSTÂNCIA
# ─────────────────────────────────────────────────────────────────────────────
def porta_livre() -> int:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", PORTA_PREFERIDA))
            return PORTA_PREFERIDA
        except OSError:
            pass
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def responde(porta: int, token: str, prazo: float = 1.5) -> bool:
    """Prova de vida do servidor: `/api/estado` devolve o contador da sala."""
    url = "http://127.0.0.1:%d/api/estado" % porta
    if token:
        url += "?t=" + token
    try:
        with urllib.request.urlopen(url, timeout=prazo) as r:
            return "ultima" in json.loads(r.read().decode())
    except (urllib.error.URLError, OSError, ValueError):
        return False


def instancia_viva() -> dict | None:
    """Instância anterior que ainda está de pé — ou None (e limpa o rastro)."""
    try:
        d = json.loads(INSTANCIA.read_text())
    except (OSError, ValueError):
        return None
    pid, porta = d.get("pid"), d.get("porta")
    if not pid or not porta:
        return None
    try:
        os.kill(int(pid), 0)          # PID vivo (pode ser reciclado: por isso o probe)
    except OSError:
        INSTANCIA.unlink(missing_ok=True)
        return None
    if responde(int(porta), d.get("token", "")):
        return d
    INSTANCIA.unlink(missing_ok=True)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# A JANELA
# ─────────────────────────────────────────────────────────────────────────────
NAVEGADORES = (
    ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "Chrome"),
    ("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge", "Edge"),
)


def abrir_janela(url: str):
    """Janela sem abas nem barra de endereço quando dá; aba comum quando não dá.

    O `--user-data-dir` é o que torna isto honesto: a instância aberta aqui é
    OUTRA, com perfil próprio dentro de `Application Support`. O Chrome do dono —
    abas, sessão, extensões — não é tocado, e o processo que este lançador mata no
    fim é só o que ele mesmo abriu.
    """
    for exe, nome in NAVEGADORES:
        if os.path.exists(exe):
            PERFIL.mkdir(parents=True, exist_ok=True)
            p = subprocess.Popen(
                [
                    exe,
                    "--app=" + url,
                    "--user-data-dir=" + str(PERFIL),
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--no-service-autorun",
                    "--window-size=980,880",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return p, nome + " (modo app)"
    if Path("/Applications/Safari.app").exists():
        subprocess.run(["/usr/bin/open", "-a", "Safari", url], check=False)
        return None, "Safari (aba)"
    subprocess.run(["/usr/bin/open", url], check=False)
    return None, "navegador padrão (aba)"


def conexoes(porta: int) -> int:
    """Conexões TCP estabelecidas nesta porta — o pulso da janela aberta."""
    try:
        saida = subprocess.run(
            ["/usr/sbin/netstat", "-an", "-p", "tcp"],
            capture_output=True, text=True, timeout=5,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return 1          # sem instrumento não se declara morte: mantém vivo
    alvo = ".%d" % porta
    n = 0
    for linha in saida.splitlines():
        c = linha.split()
        if len(c) >= 6 and c[-1] == "ESTABLISHED" and c[3].endswith(alvo):
            n += 1
    return n


# ─────────────────────────────────────────────────────────────────────────────
# O SERVIDOR — neto, através de um cano que só existe enquanto este processo vive
# ─────────────────────────────────────────────────────────────────────────────
CANO = r'''
"$IACHAT_PY" "$IACHAT_SRV" --porta "$IACHAT_PORTA" --escrever --papel "$IACHAT_PAPEL" \
    >>"$IACHAT_LOG" 2>&1 &
srv=$!
trap 'kill "$srv" 2>/dev/null' EXIT INT TERM
cat >/dev/null          # bloqueia até o cano do lançador fechar (EOF = pai morreu)
kill "$srv" 2>/dev/null
# Se o lançador levou um -9, ele não conseguiu fechar a janela: sobrava uma
# página morta apontando para um servidor que já não existe. O PID dela fica
# neste arquivo justamente para o cano poder terminar o serviço.
if [ -s "$IACHAT_JANELA" ]; then kill "$(cat "$IACHAT_JANELA")" 2>/dev/null; fi
wait "$srv" 2>/dev/null
'''


def sobe_servidor(py: str, servidor: Path, core: Path, porta: int,
                  papel: str) -> subprocess.Popen:
    amb = dict(os.environ)
    amb.update(
        IACHAT_BIN=str(core),        # o esboço lê esta para achar o núcleo
        IACHAT_CORE=str(core),
        # O `ui/servir.py` procura o núcleo num caminho fixo (`~/Projetos/ia-chat/bin`).
        # Quando esse caminho não existe — repo instalado por `install.sh` e apagado —
        # o import cai no PYTHONPATH e encontra assim mesmo. Custa uma variável e
        # dispensa mexer no arquivo de outro dono.
        PYTHONPATH=str(core) + os.pathsep + os.environ.get("PYTHONPATH", ""),
        IACHAT_PY=py,
        IACHAT_SRV=str(servidor),
        IACHAT_PORTA=str(porta),
        IACHAT_PAPEL=papel,
        IACHAT_LOG=str(LOG),
        IACHAT_JANELA=str(JANELA_PID),
    )
    return subprocess.Popen(
        ["/bin/sh", "-c", CANO],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,      # grupo próprio: o killpg no fim só pega o meu
        env=amb,
    )


def token_do_log(marca: int) -> str:
    """O token, quando o servidor gera um (o esboço gera; o `ui/servir.py` não).

    Sai do log em vez de ser combinado por contrato: assim o lançador serve os
    dois servidores sem precisar saber qual está rodando.
    """
    try:
        with LOG.open("r", encoding="utf-8", errors="replace") as f:
            f.seek(marca)
            m = re.search(r"\?t=([A-Za-z0-9_-]+)", f.read())
            return m.group(1) if m else ""
    except OSError:
        return ""


def espera_pronto(porta: int, marca: int) -> str | None:
    """A URL da sala, quando ela responde de verdade.

    Quem manda é o probe HTTP, não uma linha de log: o log diz o que o servidor
    pretendia, e o probe diz o que ele está fazendo.
    """
    limite = time.time() + ESPERA_SERVIDOR
    token = ""
    while time.time() < limite:
        token = token or token_do_log(marca)
        if responde(porta, token, prazo=1.0):
            sufixo = "?t=" + token if token else ""
            return "http://127.0.0.1:%d/%s" % (porta, sufixo)
        time.sleep(0.3)
    return None


def encerrar(proc: subprocess.Popen | None, janela) -> None:
    """Mata o que é meu, na ordem: navegador dedicado, depois o grupo do servidor."""
    if janela is not None and janela.poll() is None:
        try:
            os.killpg(os.getpgid(janela.pid), signal.SIGTERM)
        except OSError:
            pass
    if proc is not None:
        try:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()          # EOF: o `sh` acorda e mata o servidor
        except OSError:
            pass
        try:
            grupo = os.getpgid(proc.pid)
        except OSError:
            grupo = None
        if grupo:
            try:
                os.killpg(grupo, signal.SIGTERM)
            except OSError:
                pass
        limite = time.time() + 5.0
        while proc.poll() is None and time.time() < limite:
            time.sleep(0.1)
        if proc.poll() is None and grupo:
            try:
                os.killpg(grupo, signal.SIGKILL)
            except OSError:
                pass
    INSTANCIA.unlink(missing_ok=True)
    JANELA_PID.unlink(missing_ok=True)


def erro(msg: str) -> int:
    """Falha visível: o app é clicado no Finder, onde ninguém lê stderr."""
    print("ia-chat: " + msg, file=sys.stderr)
    subprocess.run(
        ["/usr/bin/osascript", "-e",
         'display alert "ia-chat" message %s as critical' % json.dumps(msg)],
        check=False, capture_output=True,
    )
    return 1


# ─────────────────────────────────────────────────────────────────────────────
def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)   # lançado sem tty: sem isto, silêncio
    SUPORTE.mkdir(parents=True, exist_ok=True)

    viva = instancia_viva()
    if viva:
        _, como = abrir_janela(viva["url"])
        print("instância já viva na porta %s — janela trazida de volta (%s)"
              % (viva["porta"], como))
        return 0

    core = achar_core()
    if core is None:
        return erro("não achei o iachat_core.py. Instale o ia-chat primeiro:\n\n"
                    "    git clone <ia-chat> ~/Projetos/ia-chat && "
                    "~/Projetos/ia-chat/install.sh")
    servidor = achar_servidor()
    if servidor is None:
        return erro("não achei o servidor.py — nem no repo, nem dentro do app.")
    py = escolher_python(core)
    if py is None:
        return erro("nenhum python3 desta máquina consegue importar o núcleo em\n%s"
                    % core)

    papel = os.environ.get("IACHAT_PAPEL", "bauer")
    porta = porta_livre()

    marca = LOG.stat().st_size if LOG.exists() else 0
    with LOG.open("a", encoding="utf-8") as f:
        f.write("\n=== %s · porta %d · %s · %s\n"
                % (time.strftime("%Y-%m-%d %H:%M:%S"), porta, py, servidor))

    proc = sobe_servidor(py, servidor, core, porta, papel)
    janela = None
    encerrado = [False]

    def fechar(*_):
        if not encerrado[0]:
            encerrado[0] = True
            encerrar(proc, janela)
        sys.exit(0)

    signal.signal(signal.SIGTERM, fechar)
    signal.signal(signal.SIGINT, fechar)
    signal.signal(signal.SIGHUP, fechar)

    try:
        url = espera_pronto(porta, marca)
        if not url:
            encerrar(proc, None)
            return erro("o servidor não respondeu em %ds. Log:\n%s"
                        % (int(ESPERA_SERVIDOR), LOG))
        token = url.split("?t=")[1] if "?t=" in url else ""

        INSTANCIA.write_text(json.dumps(
            {"pid": os.getpid(), "porta": porta, "url": url,
             "token": token, "desde": time.time()}, ensure_ascii=False))

        janela, como = abrir_janela(url)
        JANELA_PID.write_text(str(janela.pid) if janela else "")
        print("sala em %s  ·  janela: %s" % (url, como))

        # ── vigia: sem conexão viva, ninguém está olhando ────────────────────
        nascimento = time.time()
        viu_alguem = False
        vazio_desde = None
        while True:
            time.sleep(INTERVALO)
            if proc.poll() is not None:
                print("o servidor caiu sozinho — encerrando")
                break
            n = conexoes(porta)
            if n > 0:
                viu_alguem = True
                vazio_desde = None
                continue
            if not viu_alguem:
                if time.time() - nascimento > ESPERA_PRIMEIRA_JANELA:
                    print("a janela nunca conectou em %ds — encerrando"
                          % int(ESPERA_PRIMEIRA_JANELA))
                    break
                continue
            vazio_desde = vazio_desde or time.time()
            if time.time() - vazio_desde >= ESPERA_SEM_JANELA:
                print("janela fechada — encerrando o servidor")
                break
    finally:
        if not encerrado[0]:
            encerrado[0] = True
            encerrar(proc, janela)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
