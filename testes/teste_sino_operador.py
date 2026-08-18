#!/usr/bin/env python3
"""Gate do sino do dono: estado único, API segura e controle negativo real.

Tudo roda em `IACHAT_HOME` temporário, com `/usr/bin/python3` e um instalador
falso dentro do temporário. A sala viva e o LaunchAgent real nunca são tocados.
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
from pathlib import Path
from typing import Optional

RAIZ = Path(__file__).resolve().parent.parent
CORE_BIN = RAIZ.parent / "ia-chat" / "bin"
SERVIR = RAIZ / "ui" / "servir.py"
INDEX = RAIZ / "ui" / "index.html"
SALA_JS = RAIZ / "ui" / "sala.js"
ESTILO = RAIZ / "ui" / "estilo.css"
PYTHON = Path("/usr/bin/python3")

_ok = 0
_falhou = 0


def checa(nome: str, condicao: bool, detalhe: str = "") -> None:
    global _ok, _falhou
    if condicao:
        _ok += 1
        print(f"  ✔ {nome}")
    else:
        _falhou += 1
        print(f"  ✗ {nome}" + (f" — {detalhe}" if detalhe else ""))


def porta_livre(inicio: int = 59720) -> int:
    for porta in range(inicio, 59820):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", porta))
                return porta
            except OSError:
                continue
    raise RuntimeError("sem porta livre para o teste")


def cria_instalador(pasta: Path, rc: int = 0) -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    alvo = pasta / "ia-bell-install-daemon.sh"
    alvo.write_text(
        "#!/bin/bash\n"
        "printf '%s\\n' \"$1|$2|$IACHAT_HOME\" >> "
        "\"$IACHAT_HOME/instalador-sino-chamado.log\"\n"
        f"exit {rc}\n",
        encoding="utf-8",
    )
    alvo.chmod(0o755)
    return alvo


def ambiente(base: Path, sala: Path, scripts: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        HOME=str(base / "home"),
        IACHAT_HOME=str(sala),
        IACHAT_SCRIPTS=str(scripts),
        PYTHONPATH=str(CORE_BIN),
        PYTHONDONTWRITEBYTECODE="1",
        NO_PROXY="127.0.0.1,localhost",
        no_proxy="127.0.0.1,localhost",
    )
    for nome in (
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
        "http_proxy", "https_proxy", "all_proxy",
    ):
        env.pop(nome, None)
    return env


def sobe(servidor: Path, base: Path, somente_leitura: bool = False,
         instalador_rc: int = 0) -> tuple[subprocess.Popen[str], int, str, Path]:
    sala = base / "sala"
    scripts = base / "scripts"
    cria_instalador(scripts, instalador_rc)
    porta = porta_livre()
    args = [str(PYTHON), str(servidor), "--porta", str(porta)]
    if not somente_leitura:
        args.append("--escrever")
    proc = subprocess.Popen(
        args,
        env=ambiente(base, sala, scripts),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    linha = proc.stdout.readline() if proc.stdout else ""
    token = ""
    achado = re.search(r"[?&]t=([A-Za-z0-9_-]+)", linha)
    if achado:
        token = achado.group(1)
    return proc, porta, token, sala


def encerra(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def pede(porta: int, rota: str, token: str = "", corpo: Optional[object] = None,
         origem: Optional[str] = None) -> tuple[int, dict]:
    if token:
        rota += ("&" if "?" in rota else "?") + "t=" + token
    url = f"http://127.0.0.1:{porta}{rota}"
    dados = None if corpo is None else json.dumps(corpo).encode()
    cabecalhos = {}
    if corpo is not None:
        cabecalhos["Content-Type"] = "application/json"
    if origem is not None:
        cabecalhos["Origin"] = origem
    req = urllib.request.Request(
        url,
        data=dados,
        headers=cabecalhos,
        method="POST" if corpo is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resposta:
            return resposta.status, json.loads(resposta.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b"{}")
        except json.JSONDecodeError:
            return exc.code, {}


def le_config(sala: Path) -> dict:
    return json.loads((sala / "config.json").read_text(encoding="utf-8"))


def espera_texto(caminho: Path, trecho: str, prazo: float = 5.0) -> bool:
    limite = time.time() + prazo
    while time.time() < limite:
        if caminho.is_file() and trecho in caminho.read_text(
            encoding="utf-8", errors="replace"
        ):
            return True
        time.sleep(0.05)
    return False


def posta_temporario(env: dict[str, str], texto: str) -> subprocess.CompletedProcess[str]:
    codigo = (
        "import iachat_core as c; "
        f"c.post(de='codex', para='bauer', texto={texto!r})"
    )
    return subprocess.run(
        [str(PYTHON), "-c", codigo], env=env,
        capture_output=True, text=True, timeout=10, check=False,
    )


def contrato_basico(servidor: Path, base: Path) -> bool:
    """Devolve o veredito que a isca precisa derrubar."""
    proc, porta, token, sala = sobe(servidor, base)
    try:
        cod, inicial = pede(porta, "/api/sala", token)
        origem = f"http://127.0.0.1:{porta}"
        cod_on, on = pede(
            porta, "/api/sino", token, {"ligado": True}, origem
        )
        disco = le_config(sala).get("notificar_operador")
        return (
            cod == 200
            and inicial.get("sala", {}).get("notificar_operador") is False
            and cod_on == 200
            and on.get("notificar_operador") is True
            and disco is True
        )
    finally:
        encerra(proc)


def main() -> int:
    if not PYTHON.is_file():
        print(f"✗ /usr/bin/python3 ausente: {PYTHON}")
        return 1
    if not (CORE_BIN / "iachat_core.py").is_file():
        print(f"✗ núcleo ausente: {CORE_BIN}")
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="iachat-sino-operador-"))
    try:
        print("— contrato positivo: o app lê e grava o MESMO config.json —")
        positivo = tmp / "positivo"
        proc, porta, token, sala = sobe(SERVIR, positivo)
        try:
            checa("servidor de escrita anunciou token", bool(token))
            cod, inicial = pede(porta, "/api/sala", token)
            cfg_antes = le_config(sala)
            checa(
                "sino nasce desligado no payload e no disco",
                cod == 200
                and inicial.get("sala", {}).get("notificar_operador") is False
                and cfg_antes.get("notificar_operador") is False,
                f"HTTP {cod} payload={inicial}",
            )
            cod_sino, sino_inicial = pede(porta, "/api/sino", token)
            checa(
                "GET /api/sino reflete o mesmo false",
                cod_sino == 200
                and sino_inicial.get("notificar_operador") is False
                and sino_inicial.get("escrever") is True,
                f"HTTP {cod_sino} payload={sino_inicial}",
            )

            origem = f"http://127.0.0.1:{porta}"
            cod, _ = pede(porta, "/api/sino", token, {"ligado": "sim"}, origem)
            checa(
                "REPROVA tipo ambíguo e não muda o arquivo",
                cod == 400 and le_config(sala).get("notificar_operador") is False,
                f"HTTP {cod}",
            )
            cod, _ = pede(porta, "/api/sino", "", {"ligado": True}, origem)
            checa(
                "REPROVA pedido sem token e não muda o arquivo",
                cod == 401 and le_config(sala).get("notificar_operador") is False,
                f"HTTP {cod}",
            )
            cod, _ = pede(
                porta, "/api/sino", token, {"ligado": True}, "http://malicioso"
            )
            checa(
                "REPROVA origem alheia e não muda o arquivo",
                cod == 403 and le_config(sala).get("notificar_operador") is False,
                f"HTTP {cod}",
            )

            cod, resposta = pede(
                porta, "/api/sino", token, {"ligado": True}, origem
            )
            cfg_on = le_config(sala)
            chamada = (sala / "instalador-sino-chamado.log").read_text()
            checa(
                "LIGAR prova a perna macOS antes de gravar true",
                cod == 200
                and resposta.get("notificar_operador") is True
                and cfg_on.get("notificar_operador") is True
                and chamada.startswith("--operador|15|"),
                f"HTTP {cod} resposta={resposta} chamada={chamada!r}",
            )
            _, sino_on = pede(porta, "/api/sino", token)
            checa(
                "GET /api/sino reflete a troca para true",
                sino_on.get("notificar_operador") is True,
                str(sino_on),
            )
            checa(
                "ligar preserva os outros campos do config",
                all(cfg_on.get(k) == cfg_antes.get(k)
                    for k in ("na_sala", "brain", "teto_bytes")),
                f"antes={cfg_antes} depois={cfg_on}",
            )

            cod, resposta = pede(
                porta, "/api/sino", token, {"ligado": False}, origem
            )
            chamadas_depois = (sala / "instalador-sino-chamado.log").read_text()
            checa(
                "DESLIGAR grava false e não cria segunda decisão",
                cod == 200
                and resposta.get("notificar_operador") is False
                and le_config(sala).get("notificar_operador") is False
                and chamadas_depois == chamada,
                f"HTTP {cod} resposta={resposta}",
            )
            _, sino_off = pede(porta, "/api/sino", token)
            checa(
                "GET /api/sino reflete a troca para false",
                sino_off.get("notificar_operador") is False,
                str(sino_off),
            )
        finally:
            encerra(proc)

        print("— falha de infraestrutura: nunca grava ligado sem sino pronto —")
        falha = tmp / "instalador-falha"
        proc, porta, token, sala = sobe(SERVIR, falha, instalador_rc=7)
        try:
            pede(porta, "/api/sala", token)
            cod, _ = pede(
                porta, "/api/sino", token, {"ligado": True},
                f"http://127.0.0.1:{porta}",
            )
            checa(
                "REPROVA instalador falho e mantém false",
                cod == 503 and le_config(sala).get("notificar_operador") is False,
                f"HTTP {cod}",
            )
        finally:
            encerra(proc)

        print("— servidor somente leitura: refletir pode, controlar não —")
        leitura = tmp / "leitura"
        proc, porta, token, sala = sobe(SERVIR, leitura, somente_leitura=True)
        try:
            cod_get, _ = pede(porta, "/api/sala")
            cod_post, _ = pede(
                porta, "/api/sino", corpo={"ligado": True},
                origem=f"http://127.0.0.1:{porta}",
            )
            checa(
                "REPROVA mutação em modo leitura",
                cod_get == 200 and cod_post == 403,
                f"GET {cod_get} POST {cod_post}",
            )
        finally:
            encerra(proc)

        print("— controle negativo: a isca MUDA o arquivo e o gate cai —")
        quebrado = tmp / "ui-quebrada"
        quebrado.mkdir(parents=True)
        fonte = SERVIR.read_text(encoding="utf-8")
        agulha = "cfg = core.configurar_notificacao_operador(ligado)"
        isca = "cfg = core.config(); cfg[\"notificar_operador\"] = ligado"
        checa("agulha da isca existe exatamente uma vez", fonte.count(agulha) == 1)
        quebrado_servidor = quebrado / "servir.py"
        quebrado_servidor.write_text(fonte.replace(agulha, isca, 1), encoding="utf-8")
        checa(
            "isca alterou o arquivo temporário de verdade",
            quebrado_servidor.read_bytes() != SERVIR.read_bytes()
            and isca in quebrado_servidor.read_text(encoding="utf-8"),
        )
        checa(
            "REPROVA: gate detecta resposta verde sem mudança no config",
            not contrato_basico(quebrado_servidor, tmp / "negativo"),
        )
        checa(
            "arquivo real passa o mesmo contrato que derrubou a isca",
            contrato_basico(SERVIR, tmp / "positivo-repetido"),
        )

        print("— superfície do app: switch acessível, sem estado paralelo —")
        html = INDEX.read_text(encoding="utf-8")
        js = SALA_JS.read_text(encoding="utf-8")
        css = ESTILO.read_text(encoding="utf-8")
        checa(
            "app expõe um switch de sino com estado inicial desligado",
            'id="btn-sino"' in html
            and 'role="switch"' in html
            and 'aria-checked="false"' in html,
        )
        checa(
            "switch atualiza aria, rótulo e glifo ligado/desligado",
            "setAttribute('aria-checked', String(ligado))" in js
            and "E.sinoGlifo.textContent = ligado" in js
            and "Sino do dono ${ligado?'ligado':'desligado'}" in js,
        )
        checa(
            "clique controla /api/sino com booleano, não com texto",
            "async function alternaSinoOperador()" in js
            and "fetch(url('/api/sino')," in js
            and "JSON.stringify({ligado:ligar})" in js,
        )
        trecho_sino = js[
            js.index("/* ── sino do dono"):js.index("/* O token entra pela URL")
        ]
        codigo_sino = re.sub(r"/\*.*?\*/", "", trecho_sino, flags=re.S)
        codigo_sino = "\n".join(
            linha for linha in codigo_sino.splitlines()
            if not linha.strip().startswith("//")
        )
        checa(
            "decisão não ganha cópia em localStorage/cookie",
            "localStorage" not in codigo_sino and "document.cookie" not in codigo_sino,
        )
        checa(
            "app ressincroniza troca feita pelo CLI",
            "async function sincronizaSinoOperador()" in js
            and "window.setInterval" in js
            and "window.addEventListener('focus', sincronizaSinoOperador)" in js,
        )
        checa(
            "CSS distingue ligado e bloqueia mutação em modo leitura",
            '#btn-sino[data-ligado="sim"]' in css
            and "#btn-sino:disabled" in css,
        )
        for nome in ("index.html", "estilo.css", "sala.js", "servir.py"):
            fonte = RAIZ / "ui" / nome
            bundle = RAIZ / "ia-chat.app" / "Contents" / "Resources" / "ui" / nome
            checa(
                f"bundle usa a mesma fonte: {nome}",
                fonte.read_bytes() == bundle.read_bytes(),
            )

        print("— daemon: off é silêncio inteiro; on chama o macOS —")
        base_daemon = tmp / "daemon"
        sala_daemon = base_daemon / "sala"
        scripts_daemon = base_daemon / "scripts"
        bin_falso = base_daemon / "bin-falso"
        scripts_daemon.mkdir(parents=True)
        bin_falso.mkdir(parents=True)
        # O daemon é o REAL. Só o `osascript` é dublê, para provar a chamada
        # sem exibir banner nem som durante o trabalho do dono.
        osascript_falso = bin_falso / "osascript"
        osascript_falso.write_text(
            "#!/bin/bash\nprintf '%s\\n' \"$*\" >> \"$IACHAT_TEST_OSA_LOG\"\n",
            encoding="utf-8",
        )
        osascript_falso.chmod(0o755)
        env_daemon = ambiente(base_daemon, sala_daemon, scripts_daemon)
        env_daemon["PATH"] = (
            str(bin_falso) + ":/usr/bin:/bin:/usr/sbin:/sbin"
        )
        log_osa = base_daemon / "osascript.log"
        env_daemon["IACHAT_TEST_OSA_LOG"] = str(log_osa)
        sala_daemon.mkdir(parents=True)
        (sala_daemon / "config.json").write_text(
            json.dumps({
                "na_sala": ["codex", "bauer"],
                "brain": "codex",
                "teto_bytes": 204800,
                "notificar_operador": False,
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        daemon = subprocess.Popen(
            ["/bin/bash", str(CORE_BIN / "ia-bell-daemon.sh"),
             "--operador", "0.1"],
            env=env_daemon,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        log_daemon = sala_daemon / "ia-bell-operador.log"
        try:
            time.sleep(0.2)
            p1 = posta_temporario(env_daemon, "off não toca @bauer")
            viu_1 = espera_texto(log_daemon, "#1")
            checa(
                "OFF processa a nominação sem chamar osascript",
                p1.returncode == 0 and viu_1 and not log_osa.exists(),
                p1.stdout + p1.stderr,
            )

            liga = subprocess.run(
                [str(PYTHON), str(CORE_BIN / "iachat"), "sino", "on"],
                env=env_daemon, capture_output=True, text=True,
                timeout=10, check=False,
            )
            p2 = posta_temporario(env_daemon, "on toca @bauer")
            tocou = espera_texto(log_osa, "mensagem #2")
            chamada_on = log_osa.read_text(encoding="utf-8") if log_osa.exists() else ""
            checa(
                "ON entrega a nominação ao comando de notificação macOS",
                liga.returncode == 0 and p2.returncode == 0 and tocou
                and "codex → bauer" in chamada_on
                and "display notification" in chamada_on,
                f"liga={liga.stdout!r} chamada={chamada_on!r}",
            )

            desliga = subprocess.run(
                [str(PYTHON), str(CORE_BIN / "iachat"), "sino", "off"],
                env=env_daemon, capture_output=True, text=True,
                timeout=10, check=False,
            )
            p3 = posta_temporario(env_daemon, "off de novo @bauer")
            viu_3 = espera_texto(log_daemon, "#3")
            chamada_off = log_osa.read_text(encoding="utf-8")
            checa(
                "OFF posterior não deixa nem mensagem importante tocar",
                desliga.returncode == 0 and p3.returncode == 0 and viu_3
                and chamada_off == chamada_on,
                f"antes={chamada_on!r} depois={chamada_off!r}",
            )

            # Config corrompida é o terceiro desfecho: não consegui ler. Para
            # notificação, ele se funde com OFF, nunca com ON.
            (sala_daemon / "config.json").write_text("{inválido\n", encoding="utf-8")
            p4 = posta_temporario(env_daemon, "config inválido @bauer")
            viu_4 = espera_texto(log_daemon, "#4")
            chamada_invalida = log_osa.read_text(encoding="utf-8")
            checa(
                "config ilegível falha mudo",
                p4.returncode == 0 and viu_4 and chamada_invalida == chamada_on,
                p4.stdout + p4.stderr,
            )
        finally:
            daemon.terminate()
            try:
                daemon.wait(timeout=5)
            except subprocess.TimeoutExpired:
                daemon.kill()
                daemon.wait(timeout=5)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{_ok} ✔  {_falhou} ✗")
    return 1 if _falhou else 0


if __name__ == "__main__":
    sys.exit(main())
