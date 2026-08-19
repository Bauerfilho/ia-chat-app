#!/usr/bin/env python3
"""Gate F3: o próprio `/quem` abre e recolhe sem consulta duplicada.

O contrato é observado no DOM vivo, em Chrome/CDP, sobre uma cópia temporária
da interface e uma sala temporária. O servidor também é temporário; os serviços
do operador em :8899 e :8801 nunca entram na prova.

Saídas:
- 0: contrato inteiro provado, inclusive controle negativo;
- 1: defeito funcional ou controle negativo incapaz de reprovar;
- 2: BLOCK — o instrumento runtime não conseguiu olhar.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.dont_write_bytecode = True

RAIZ = Path(__file__).resolve().parent.parent
UI = RAIZ / "ui"
SALA_JS = UI / "sala.js"
CORE_BIN = RAIZ.parent / "ia-chat" / "bin"

MARCADOR_TOGGLE_INICIO = "/* F3_TOGGLE_QUEM_INICIO */"
MARCADOR_TOGGLE_FIM = "/* F3_TOGGLE_QUEM_FIM */"

_ok = 0
_falhou = 0


def checa(nome: str, cond: bool, detalhe: str = "") -> None:
    """Imprime cada prova binária e acumula o veredito."""
    global _ok, _falhou
    if cond:
        _ok += 1
        print(f"  ✔ {nome}")
    else:
        _falhou += 1
        print(f"  ✗ {nome}" + (f" — {detalhe}" if detalhe else ""))


def acha_chrome() -> Path:
    """Prefere o headless já instalado; não instala nem baixa navegador."""
    indicado = os.environ.get("IACHAT_TEST_CHROME", "").strip()
    if indicado:
        return Path(indicado)
    cache = Path.home() / "Library" / "Caches" / "ms-playwright"
    candidatos = sorted(
        cache.glob("chromium_headless_shell-*/chrome-headless-shell-mac-*/chrome-headless-shell"),
        reverse=True,
    )
    for candidato in candidatos:
        if candidato.is_file():
            return candidato
    return Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


CHROME = acha_chrome()


class CdpWebSocket:
    """Cliente WebSocket mínimo para CDP, só com a biblioteca padrão."""

    def __init__(self, url: str, timeout: float, origin: str) -> None:
        alvo = urllib.parse.urlsplit(url)
        if alvo.scheme != "ws" or not alvo.hostname or not alvo.port:
            raise RuntimeError(f"WebSocket CDP inválido: {url}")
        self.sock = socket.create_connection((alvo.hostname, alvo.port), timeout=timeout)
        self.leitor = self.sock.makefile("rb")
        chave = base64.b64encode(os.urandom(16)).decode("ascii")
        caminho = alvo.path or "/"
        if alvo.query:
            caminho += "?" + alvo.query
        pedido = (
            f"GET {caminho} HTTP/1.1\r\n"
            f"Host: {alvo.hostname}:{alvo.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {chave}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            f"Origin: {origin}\r\n\r\n"
        )
        self.sock.sendall(pedido.encode("ascii"))
        status = self.leitor.readline().decode("ascii", "replace").strip()
        cabecalhos: dict[str, str] = {}
        while True:
            linha = self.leitor.readline()
            if linha in (b"", b"\r\n"):
                break
            nome, valor = linha.decode("ascii", "replace").split(":", 1)
            cabecalhos[nome.lower()] = valor.strip()
        esperado = base64.b64encode(hashlib.sha1(
            (chave + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")
        ).digest()).decode("ascii")
        if " 101 " not in f" {status} " or cabecalhos.get("sec-websocket-accept") != esperado:
            self.close()
            raise RuntimeError(f"handshake WebSocket CDP falhou: {status}")

    def _le(self, tamanho: int) -> bytes:
        dados = self.leitor.read(tamanho)
        if dados is None or len(dados) != tamanho:
            raise RuntimeError("WebSocket CDP fechou no meio de um frame")
        return dados

    def _envia_frame(self, opcode: int, carga: bytes = b"") -> None:
        cabecalho = bytearray([0x80 | opcode])
        tamanho = len(carga)
        if tamanho < 126:
            cabecalho.append(0x80 | tamanho)
        elif tamanho <= 0xFFFF:
            cabecalho.extend((0x80 | 126, *struct.pack("!H", tamanho)))
        else:
            cabecalho.extend((0x80 | 127, *struct.pack("!Q", tamanho)))
        mascara = os.urandom(4)
        mascarada = bytes(b ^ mascara[i % 4] for i, b in enumerate(carga))
        self.sock.sendall(bytes(cabecalho) + mascara + mascarada)

    def send(self, texto: str) -> None:
        self._envia_frame(0x1, texto.encode("utf-8"))

    def recv(self) -> str:
        partes: list[bytes] = []
        while True:
            primeiro, segundo = self._le(2)
            final = bool(primeiro & 0x80)
            opcode = primeiro & 0x0F
            mascarado = bool(segundo & 0x80)
            tamanho = segundo & 0x7F
            if tamanho == 126:
                tamanho = struct.unpack("!H", self._le(2))[0]
            elif tamanho == 127:
                tamanho = struct.unpack("!Q", self._le(8))[0]
            mascara = self._le(4) if mascarado else b""
            carga = self._le(tamanho)
            if mascarado:
                carga = bytes(b ^ mascara[i % 4] for i, b in enumerate(carga))
            if opcode == 0x8:
                raise RuntimeError("WebSocket CDP encerrou a conexão")
            if opcode == 0x9:
                self._envia_frame(0xA, carga)
                continue
            if opcode == 0x1:
                partes = [carga]
            elif opcode == 0x0:
                partes.append(carga)
            else:
                continue
            if final:
                return b"".join(partes).decode("utf-8")

    def close(self) -> None:
        try:
            if hasattr(self, "sock"):
                self._envia_frame(0x8)
        except OSError:
            pass
        if hasattr(self, "leitor"):
            self.leitor.close()
        if hasattr(self, "sock"):
            self.sock.close()


def porta_livre() -> int:
    """Pede uma porta efêmera ao kernel; nunca escolhe portas do operador."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def espera_http(porta: int, caminho: str, prazo: float = 12.0) -> None:
    """Só retorna quando a ponta temporária responder."""
    limite = time.time() + prazo
    ultimo = "sem resposta"
    while time.time() < limite:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{porta}{caminho}", timeout=1
            ) as resposta:
                if resposta.status == 200:
                    return
        except Exception as exc:
            ultimo = str(exc)
        time.sleep(0.1)
    raise RuntimeError(f"HTTP não ficou pronto: {ultimo}")


def cdp_chama(ws: CdpWebSocket, contador: list[int], metodo: str,
              parametros: dict | None = None) -> dict:
    """Faz uma chamada CDP e espera a resposta do mesmo id."""
    contador[0] += 1
    ident = contador[0]
    ws.send(json.dumps({"id": ident, "method": metodo,
                        "params": parametros or {}}, ensure_ascii=False))
    while True:
        resposta = json.loads(ws.recv())
        if resposta.get("id") != ident:
            continue
        if "error" in resposta:
            raise RuntimeError(f"CDP {metodo}: {resposta['error']}")
        return resposta.get("result") or {}


def cdp_avalia(ws: CdpWebSocket, contador: list[int], expressao: str,
               aguarda: bool = False):
    """Avalia JavaScript no documento e devolve um valor serializável."""
    resposta = cdp_chama(ws, contador, "Runtime.evaluate", {
        "expression": expressao,
        "awaitPromise": aguarda,
        "returnByValue": True,
    })
    if resposta.get("exceptionDetails"):
        detalhe = resposta["exceptionDetails"].get("exception", {}).get("description")
        raise RuntimeError(detalhe or str(resposta["exceptionDetails"]))
    remoto = resposta.get("result") or {}
    if remoto.get("subtype") == "error":
        raise RuntimeError(remoto.get("description") or "erro JavaScript")
    return remoto.get("value")


def espera_js(ws: CdpWebSocket, contador: list[int], expressao: str,
              prazo: float = 8.0):
    """Sonda uma condição do DOM sem transformar demora em PASS."""
    limite = time.time() + prazo
    ultimo = None
    while time.time() < limite:
        ultimo = cdp_avalia(ws, contador, expressao)
        if ultimo:
            return ultimo
        time.sleep(0.05)
    raise RuntimeError(f"condição do DOM não ocorreu: {expressao}; último={ultimo!r}")


def encerra(processo: subprocess.Popen | None) -> str:
    """Encerra somente o filho criado pelo teste e devolve sua saída."""
    if processo is None:
        return ""
    if processo.poll() is None:
        processo.terminate()
        try:
            processo.wait(timeout=5)
        except subprocess.TimeoutExpired:
            processo.kill()
            processo.wait(timeout=5)
    if processo.stdout is None:
        return ""
    try:
        return processo.stdout.read() or ""
    except (OSError, ValueError):
        return ""


COMANDO_QUEM_FAKE = r'''#!/usr/bin/env python3
import json
import os
import time
from pathlib import Path

home = Path(os.environ["IACHAT_HOME"])
contador = home / "teste-toggle-quem-contador.txt"
atraso = home / "teste-toggle-quem-atraso.txt"
try:
    n = int(contador.read_text(encoding="utf-8").strip()) + 1
except (FileNotFoundError, ValueError):
    n = 1
contador.write_text(str(n), encoding="utf-8")
try:
    espera = float(atraso.read_text(encoding="utf-8").strip())
except (FileNotFoundError, ValueError):
    espera = 0.0
if espera > 0:
    time.sleep(espera)
print(json.dumps({
    "missao": f"missao-{n}",
    "estado": "ativa",
    "quem": [{"ia": "codex", "estado": "vivo", "fazendo": f"rodada-{n}", "ha": "agora"}],
}, ensure_ascii=False))
'''


def prepara_copia(tmp: Path, fonte_js: Path) -> tuple[Path, Path, dict[str, str]]:
    """Monta UI, núcleo mínimo e sala inteiramente temporários."""
    if not (CORE_BIN / "iachat_core.py").is_file():
        raise RuntimeError(f"núcleo ausente em {CORE_BIN}")
    ui_tmp = tmp / "ui"
    core_tmp = tmp / "core"
    home = tmp / "sala"
    shutil.copytree(UI, ui_tmp)
    shutil.copy2(fonte_js, ui_tmp / "sala.js")
    core_tmp.mkdir()
    shutil.copy2(CORE_BIN / "iachat_core.py", core_tmp / "iachat_core.py")
    (core_tmp / "iachat-comando").write_text(COMANDO_QUEM_FAKE, encoding="utf-8")
    ambiente = dict(os.environ)
    ambiente.update({
        "IACHAT_HOME": str(home),
        "IACHAT_CORE": str(core_tmp),
        "PYTHONPATH": str(core_tmp),
        "PYTHONDONTWRITEBYTECODE": "1",
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
    })
    for nome in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                 "http_proxy", "https_proxy", "all_proxy"):
        ambiente.pop(nome, None)
    subprocess.run(
        [sys.executable, "-c", "import iachat_core as c; c.garantir_estrutura()"],
        env=ambiente, check=True, capture_output=True, text=True, timeout=10,
    )
    return ui_tmp, home, ambiente


def le_contador(home: Path) -> int:
    try:
        return int((home / "teste-toggle-quem-contador.txt").read_text(
            encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return 0


def grava_atraso(home: Path, segundos: float) -> None:
    (home / "teste-toggle-quem-atraso.txt").write_text(
        str(segundos), encoding="utf-8")


ESTADO_JS = r'''(() => {
  const p = document.getElementById('paleta');
  const t = document.getElementById('texto');
  return {
    hidden: !!p.hidden,
    painel: p.getAttribute('data-painel'),
    role: p.getAttribute('role'),
    foco: document.activeElement === t,
    texto: p.textContent.replace(/\s+/g, ' ').trim()
  };
})()'''

ACIONA_QUEM_JS = r'''(() => {
  const t = document.getElementById('texto');
  t.focus();
  t.value = '/';
  t.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'insertText', data:'/'}));
  const b = document.getElementById('cmd-quem');
  if (!b) throw new Error('a opção /quem não apareceu');
  b.click();
  return true;
})()'''


def fecha_no_browser(ws: CdpWebSocket, contador: list[int], modo: str) -> None:
    """Aciona o mesmo fechamento que o operador usa."""
    if modo == "toggle":
        cdp_avalia(ws, contador, ACIONA_QUEM_JS)
    elif modo == "esc":
        cdp_avalia(ws, contador, r'''(() => {
          const t = document.getElementById('texto');
          t.focus();
          t.dispatchEvent(new KeyboardEvent('keydown', {
            key:'Escape', bubbles:true, cancelable:true
          }));
          return true;
        })()''')
    elif modo == "x":
        cdp_avalia(ws, contador, r'''(() => {
          const b = document.querySelector('#paleta [data-cancelar]');
          if (!b) throw new Error('✕ ausente');
          b.click();
          return true;
        })()''')
    elif modo == "fora":
        cdp_avalia(ws, contador, r'''(() => {
          document.body.dispatchEvent(new PointerEvent('pointerdown', {
            bubbles:true, cancelable:true, pointerType:'mouse'
          }));
          return true;
        })()''')
    else:
        raise ValueError(modo)


def espera_contador(home: Path, esperado: int, prazo: float = 5.0) -> None:
    limite = time.time() + prazo
    while time.time() < limite:
        if le_contador(home) >= esperado:
            return
        time.sleep(0.05)
    raise RuntimeError(
        f"/api/quem não chegou à chamada {esperado}; atual={le_contador(home)}")


def executa_runtime(fonte_js: Path, basico: bool = False) -> dict:
    """Executa o contrato no navegador; erro de instrumento vira `block`."""
    if not CHROME.is_file():
        return {"block": f"Chrome ausente em {CHROME}"}

    with tempfile.TemporaryDirectory(prefix="ui-toggle-quem-") as bruto:
        tmp = Path(bruto)
        servidor = None
        chrome = None
        ws = None
        saida_servidor = ""
        saida_chrome = ""
        try:
            ui_tmp, home, ambiente = prepara_copia(tmp, fonte_js)
            porta = porta_livre()
            depuracao = porta_livre()
            perfil = tmp / "chrome"
            servidor = subprocess.Popen(
                [sys.executable, str(ui_tmp / "servir.py"), "--porta", str(porta)],
                env=ambiente, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True,
            )
            espera_http(porta, "/api/estado")
            chrome = subprocess.Popen([
                str(CHROME), "--headless=new", "--disable-gpu", "--no-sandbox",
                "--single-process", "--no-zygote", "--disable-breakpad",
                "--disable-crash-reporter", "--disable-background-networking",
                "--no-first-run", "--no-default-browser-check",
                f"--remote-debugging-port={depuracao}",
                f"--remote-allow-origins=http://127.0.0.1:{depuracao}",
                f"--user-data-dir={perfil}", "about:blank",
            ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            espera_http(depuracao, "/json/version")
            with urllib.request.urlopen(
                f"http://127.0.0.1:{depuracao}/json/list", timeout=5
            ) as resposta:
                alvos = json.loads(resposta.read())
            pagina = next(x for x in alvos if x.get("type") == "page")
            ws = CdpWebSocket(
                pagina["webSocketDebuggerUrl"], timeout=30,
                origin=f"http://127.0.0.1:{depuracao}",
            )
            seq = [0]
            cdp_chama(ws, seq, "Runtime.enable")
            cdp_chama(ws, seq, "Page.enable")
            cdp_chama(ws, seq, "Page.navigate", {
                "url": f"http://127.0.0.1:{porta}/",
            })
            espera_js(
                ws, seq,
                "document.readyState === 'complete' && !!document.getElementById('texto')",
            )
            medidas: dict = {"inicial": cdp_avalia(ws, seq, ESTADO_JS)}

            # Primeira execução: abre e consulta.
            cdp_avalia(ws, seq, ACIONA_QUEM_JS)
            espera_contador(home, 1)
            espera_js(ws, seq, "document.getElementById('paleta').textContent.includes('missao-1')")
            medidas["primeira"] = {
                "estado": cdp_avalia(ws, seq, ESTADO_JS),
                "gets": le_contador(home),
            }

            # Segunda execução, pelo mesmo caminho real: deve só recolher.
            cdp_avalia(ws, seq, ACIONA_QUEM_JS)
            time.sleep(0.2)
            medidas["segunda"] = {
                "estado": cdp_avalia(ws, seq, ESTADO_JS),
                "gets": le_contador(home),
            }
            segundo = medidas["segunda"]
            segundo_ok = (
                segundo["estado"].get("hidden") is True
                and segundo["estado"].get("painel") is None
                and segundo["estado"].get("foco") is True
                and segundo["gets"] == 1
            )
            if basico or not segundo_ok:
                return medidas

            # Terceira execução: consulta novamente e mostra conteúdo fresco.
            cdp_avalia(ws, seq, ACIONA_QUEM_JS)
            espera_contador(home, 2)
            espera_js(ws, seq, "document.getElementById('paleta').textContent.includes('missao-2')")
            medidas["terceira"] = {
                "estado": cdp_avalia(ws, seq, ESTADO_JS),
                "gets": le_contador(home),
            }
            fecha_no_browser(ws, seq, "x")
            espera_js(ws, seq, "document.getElementById('paleta').hidden === true")

            # Quatro fechamentos durante `consultando…`: nenhum pode reabrir
            # quando a resposta atrasada chegar. Depois de cada um, /quem abre
            # normalmente, provando que não sobrou identidade fantasma.
            medidas["corridas"] = {}
            proximo_get = 2
            for modo in ("toggle", "esc", "x", "fora"):
                grava_atraso(home, 0.65)
                cdp_avalia(ws, seq, ACIONA_QUEM_JS)
                proximo_get += 1
                espera_contador(home, proximo_get)
                espera_js(ws, seq, "document.getElementById('paleta').textContent.includes('consultando')")
                fecha_no_browser(ws, seq, modo)
                espera_js(ws, seq, "document.getElementById('paleta').hidden === true")
                fechado = cdp_avalia(ws, seq, ESTADO_JS)
                time.sleep(0.85)
                tardio = cdp_avalia(ws, seq, ESTADO_JS)
                gets_apos_tardio = le_contador(home)

                grava_atraso(home, 0)
                cdp_avalia(ws, seq, ACIONA_QUEM_JS)
                proximo_get += 1
                espera_contador(home, proximo_get)
                espera_js(
                    ws, seq,
                    f"document.getElementById('paleta').textContent.includes('missao-{proximo_get}')",
                )
                reabriu = cdp_avalia(ws, seq, ESTADO_JS)
                medidas["corridas"][modo] = {
                    "fechado": fechado,
                    "tardio": tardio,
                    "gets_apos_tardio": gets_apos_tardio,
                    "get_esperado": proximo_get - 1,
                    "reabriu": reabriu,
                    "gets_reabriu": le_contador(home),
                }
                fecha_no_browser(ws, seq, "x")
                espera_js(ws, seq, "document.getElementById('paleta').hidden === true")

            # Outro comando substitui o painel e limpa a identidade de /quem.
            grava_atraso(home, 0)
            cdp_avalia(ws, seq, ACIONA_QUEM_JS)
            proximo_get += 1
            espera_contador(home, proximo_get)
            espera_js(
                ws, seq,
                f"document.getElementById('paleta').textContent.includes('missao-{proximo_get}')",
            )
            cdp_avalia(ws, seq, r'''(() => {
              const t = document.getElementById('texto');
              t.focus();
              t.value = '/goal';
              t.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'insertText'}));
              document.getElementById('compositor').requestSubmit();
              return true;
            })()''')
            espera_js(ws, seq, "document.getElementById('paleta').textContent.includes('/goal')")
            outro = cdp_avalia(ws, seq, ESTADO_JS)
            cdp_avalia(ws, seq, ACIONA_QUEM_JS)
            proximo_get += 1
            espera_contador(home, proximo_get)
            espera_js(
                ws, seq,
                f"document.getElementById('paleta').textContent.includes('missao-{proximo_get}')",
            )
            medidas["outro_painel"] = {
                "outro": outro,
                "quem": cdp_avalia(ws, seq, ESTADO_JS),
                "gets": le_contador(home),
                "get_esperado": proximo_get,
            }
            return medidas
        except Exception as exc:
            return {
                "block": str(exc),
                "servidor": saida_servidor[-1200:],
                "chrome": saida_chrome[-1200:],
            }
        finally:
            if ws is not None:
                ws.close()
            saida_chrome = encerra(chrome)
            saida_servidor = encerra(servidor)


def contrato_basico_passa(medidas: dict) -> bool:
    primeira = medidas.get("primeira") or {}
    segunda = medidas.get("segunda") or {}
    p = primeira.get("estado") or {}
    s = segunda.get("estado") or {}
    return (
        p.get("hidden") is False
        and p.get("painel") == "/quem"
        and p.get("role") == "group"
        and p.get("foco") is True
        and primeira.get("gets") == 1
        and s.get("hidden") is True
        and s.get("painel") is None
        and s.get("foco") is True
        and segunda.get("gets") == 1
    )


def cria_negativo(fonte: str, destino: Path) -> tuple[bool, str]:
    """Remove só o ramo do toggle; a cópia precisa continuar JavaScript válido."""
    padrao = re.compile(
        re.escape(MARCADOR_TOGGLE_INICIO) + r"[\s\S]*?" + re.escape(MARCADOR_TOGGLE_FIM)
    )
    negativo, trocas = padrao.subn("/* controle negativo F3: ramo removido */", fonte)
    if trocas != 1:
        return False, f"esperava 1 ramo marcado; encontrei {trocas}"
    destino.write_text(negativo, encoding="utf-8")
    return True, ""


def prova_basica_cli(fonte_js: Path) -> int:
    """Modo interno usado pelo controle negativo em subprocesso real."""
    medidas = executa_runtime(fonte_js, basico=True)
    if medidas.get("block"):
        print("BLOCK controle negativo:", medidas["block"])
        return 2
    print(json.dumps(medidas, ensure_ascii=False, sort_keys=True))
    return 0 if contrato_basico_passa(medidas) else 1


def main() -> int:
    fonte = SALA_JS.read_text(encoding="utf-8")
    print("— F3 · estrutura da máquina de estado —")
    checa("a identidade do painel é separada de paletaModo",
          "paletaPainelId" in fonte and "paletaPainelCapturado" in fonte)
    checa("o painel expõe identidade semântica no DOM",
          "data-painel" in fonte and "painelPaleta(html, rotulo, identidade" in fonte)
    checa("a consulta usa abort e geração",
          "AbortController" in fonte and "paletaQuemGeracao" in fonte
          and "signal: abortador.signal" in fonte)

    print("\n— F3 · navegador real, sala e servidor temporários —")
    medidas = executa_runtime(SALA_JS)
    if medidas.get("block"):
        print("BLOCK runtime: " + medidas["block"])
        detalhe = (medidas.get("chrome") or medidas.get("servidor") or "").strip()
        if detalhe:
            print(detalhe[-1200:])
        return 2

    inicial = medidas.get("inicial") or {}
    primeira = medidas.get("primeira") or {}
    segunda = medidas.get("segunda") or {}
    p = primeira.get("estado") or {}
    s = segunda.get("estado") or {}
    checa("estado inicial: #paleta oculto", inicial.get("hidden") is True, repr(inicial))
    checa("primeiro /quem abre painel identificado, group e focado",
          p.get("hidden") is False and p.get("painel") == "/quem"
          and p.get("role") == "group" and p.get("foco") is True,
          repr(primeira))
    checa("primeiro /quem faz exatamente 1 GET",
          primeira.get("gets") == 1, repr(primeira))
    checa("segundo /quem recolhe e limpa a identidade com foco preservado",
          s.get("hidden") is True and s.get("painel") is None
          and s.get("foco") is True, repr(segunda))
    checa("segundo /quem não chama a API",
          segunda.get("gets") == 1, repr(segunda))

    if "terceira" in medidas:
        terceira = medidas["terceira"]
        t = terceira.get("estado") or {}
        checa("terceiro /quem consulta de novo e mostra dado fresco",
              t.get("hidden") is False and t.get("painel") == "/quem"
              and terceira.get("gets") == 2 and "missao-2" in t.get("texto", ""),
              repr(terceira))

        for modo, rotulo in (("toggle", "toggle"), ("esc", "Esc"),
                             ("x", "✕"), ("fora", "clique-fora")):
            corrida = (medidas.get("corridas") or {}).get(modo) or {}
            fechado = corrida.get("fechado") or {}
            tardio = corrida.get("tardio") or {}
            reabriu = corrida.get("reabriu") or {}
            checa(f"{rotulo} durante consultando limpa e mantém recolhido",
                  fechado.get("hidden") is True and fechado.get("painel") is None
                  and tardio.get("hidden") is True and tardio.get("painel") is None,
                  repr(corrida))
            checa(f"resposta tardia após {rotulo} não acrescenta GET",
                  corrida.get("gets_apos_tardio") == corrida.get("get_esperado"),
                  repr(corrida))
            checa(f"/quem abre normalmente depois de {rotulo}",
                  reabriu.get("hidden") is False and reabriu.get("painel") == "/quem"
                  and corrida.get("gets_reabriu") == corrida.get("get_esperado", 0) + 1,
                  repr(corrida))

        outro = medidas.get("outro_painel") or {}
        estado_outro = outro.get("outro") or {}
        estado_quem = outro.get("quem") or {}
        checa("outro comando limpa a identidade de /quem",
              estado_outro.get("hidden") is False
              and estado_outro.get("painel") is None
              and "/goal" in estado_outro.get("texto", ""),
              repr(outro))
        checa("/quem abre depois de outro painel, sem estado fantasma",
              estado_quem.get("hidden") is False
              and estado_quem.get("painel") == "/quem"
              and outro.get("gets") == outro.get("get_esperado"),
              repr(outro))

    print("\n— F3 · controle negativo obrigatório —")
    with tempfile.TemporaryDirectory(prefix="ui-toggle-quem-negativo-") as bruto:
        negativo = Path(bruto) / "sala-sem-toggle.js"
        criou, detalhe = cria_negativo(fonte, negativo)
        checa("a cópia sem o ramo de toggle foi construída", criou, detalhe)
        if criou:
            prova = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()),
                 "--prova-basica", str(negativo)],
                capture_output=True, text=True,
            )
            checa("a cópia sem toggle termina com falha funcional (rc=1)",
                  prova.returncode == 1,
                  f"rc={prova.returncode}; saída={(prova.stdout + prova.stderr)[-600:]}")

    print(f"\n{_ok} ✔  {_falhou} ✗")
    return 1 if _falhou else 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--prova-basica":
        raise SystemExit(prova_basica_cli(Path(sys.argv[2])))
    raise SystemExit(main())
