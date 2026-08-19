#!/usr/bin/env python3
"""O visualizador IASWARM dourado — o que a interface promete, o disco prova.

Trava as peças do pedido: o mesmo botão da gaveta no topo, a logo IASWARM
acima da luazinha, a janela que troca, a rota de leitura do enxame, e o
controle remoto por worker. Também o caso que REPROVA: o cliente não escolhe
pasta, `../` não atravessa.
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
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
UI = RAIZ / "ui"
HTML = (UI / "index.html").read_text(encoding="utf-8")
JS = (UI / "sala.js").read_text(encoding="utf-8")
CSS = (UI / "estilo.css").read_text(encoding="utf-8")
SERVIR = UI / "servir.py"


def acha_chrome() -> Path:
    """Prefere o headless de testes; cai no Chrome do operador sem instalar nada."""
    indicado = os.environ.get("IACHAT_TEST_CHROME", "").strip()
    if indicado:
        return Path(indicado)
    cache = Path.home() / "Library" / "Caches" / "ms-playwright"
    headless = sorted(
        cache.glob("chromium_headless_shell-*/chrome-headless-shell-mac-*/chrome-headless-shell"),
        reverse=True,
    )
    for candidato in headless:
        if candidato.is_file():
            return candidato
    return Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


CHROME = acha_chrome()


class CdpWebSocket:
    """Cliente WebSocket mínimo para o CDP local, sem dependência externa."""

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
        cabecalhos = {}
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
        partes = []
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


def elemento_por_id(html: str, tag: str, ident: str) -> str:
    """Extrai um elemento simples pelo id, incluindo abertura e fechamento."""
    abertura = re.search(
        rf'<{tag}\b(?=[^>]*\bid="{re.escape(ident)}")[^>]*>', html,
        re.I,
    )
    if not abertura:
        return ""
    fim = html.find(f"</{tag}>", abertura.end())
    return "" if fim < 0 else html[abertura.start():fim + len(tag) + 3]


def rota_iaswarm_tem_wordmark(botao: str, documento: str) -> bool:
    """Valida a rota compacta e rejeita o antigo letreiro textual."""
    abertura = re.match(r"<button\b[^>]*>", botao, re.I)
    svg = re.search(
        r'<svg\b[^>]*\bclass="[^"]*\benxame-logo-trilho\b[^"]*"[^>]*>'
        r'[\s\S]*?</svg>',
        botao,
        re.I,
    )
    if not abertura or not svg:
        return False

    cabecalho = abertura.group(0)
    desenho = svg.group(0)
    ids = re.findall(r'\bid="([^"]+)"', desenho)
    documento_sem_botao = documento.replace(botao, "", 1)
    ids_fora = set(re.findall(r'\bid="([^"]+)"', documento_sem_botao))
    wordmark = re.search(r"<text\b[^>]*>\s*IASWARM\s*</text>", desenho, re.I)
    filete = re.search(
        r'<rect\b(?=[^>]*\bx="42")(?=[^>]*\bwidth="536")'
        r'(?=[^>]*\bheight="3")[^>]*/?>',
        desenho,
        re.I,
    )

    return all((
        'type="button"' in cabecalho,
        'aria-controls="enxame"' in cabecalho,
        'aria-pressed="false"' in cabecalho,
        bool(wordmark),
        bool(filete),
        len(ids) >= 3,
        len(ids) == len(set(ids)),
        all(ident.startswith("iaswarm-trilho-") for ident in ids),
        not (set(ids) & ids_fora),
        'aria-hidden="true"' in desenho,
        'focusable="false"' in desenho,
        "enxame-letreiro" not in botao,
    ))


def porta_livre(inicio: int = 59900) -> int:
    for p in range(inicio, inicio + 60):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise RuntimeError("sem porta livre")


def sobe(home: Path, porta: int, enxame: Path) -> tuple[subprocess.Popen[str], str]:
    env = dict(os.environ, IACHAT_HOME=str(home), IASWARM_RAIZ=str(enxame))
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


def pede(porta: int, rota: str, token: str | None = None) -> tuple[int, str]:
    url = f"http://127.0.0.1:{porta}{rota}"
    if token:
        url += ("&" if "?" in rota else "?") + "t=" + token
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except urllib.error.URLError as e:
        return 0, str(e)


def espera_http(porta: int, caminho: str, prazo: float = 10.0) -> None:
    """Espera a ponta temporária responder; ausência é BLOCK, nunca verde."""
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


def cdp_chama(ws, contador: list[int], metodo: str,
              parametros: dict | None = None) -> dict:
    """Faz uma chamada mínima ao Chrome DevTools Protocol."""
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


def cdp_avalia(ws, contador: list[int], expressao: str) -> object:
    """Executa JavaScript real na página e devolve somente valor serializável."""
    resposta = cdp_chama(ws, contador, "Runtime.evaluate", {
        "expression": expressao,
        "awaitPromise": True,
        "returnByValue": True,
    })
    if resposta.get("exceptionDetails"):
        detalhe = resposta["exceptionDetails"].get("text") or "exceção JavaScript"
        raise RuntimeError(detalhe)
    remoto = resposta.get("result") or {}
    if remoto.get("subtype") == "error":
        raise RuntimeError(remoto.get("description") or "erro JavaScript")
    return remoto.get("value")


def estabilidade_enxame_browser(porta: int, token: str, run: Path) -> dict:
    """Prova o gate F1 no DOM vivo, inclusive 30 s de polling imóvel."""
    if not CHROME.is_file():
        return {"block": f"Chrome ausente em {CHROME}"}

    depuracao = porta_livre(60000)
    perfil = Path(tempfile.mkdtemp(prefix="ui-enxame-chrome-"))
    chrome = None
    ws = None
    medidas: dict = {}
    try:
        chrome = subprocess.Popen([
            str(CHROME), "--headless=new", "--disable-gpu", "--no-sandbox",
            "--single-process", "--no-zygote",
            "--disable-breakpad", "--disable-crash-reporter",
            "--no-first-run", "--no-default-browser-check",
            f"--remote-debugging-port={depuracao}",
            f"--remote-allow-origins=http://127.0.0.1:{depuracao}",
            f"--user-data-dir={perfil}", "about:blank",
        ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            espera_http(depuracao, "/json/version")
        except Exception as exc:
            if chrome.poll() is None:
                chrome.terminate()
            try:
                saida_chrome = chrome.communicate(timeout=3)[0]
            except subprocess.TimeoutExpired:
                chrome.kill()
                saida_chrome = chrome.communicate(timeout=3)[0]
            raise RuntimeError(
                f"{exc}; Chrome rc={chrome.returncode}: {saida_chrome[-900:]}"
            ) from exc
        with urllib.request.urlopen(
            f"http://127.0.0.1:{depuracao}/json/list", timeout=5
        ) as resposta:
            alvos = json.loads(resposta.read())
        pagina = next(x for x in alvos if x.get("type") == "page")
        ws = CdpWebSocket(
            pagina["webSocketDebuggerUrl"], timeout=45,
            origin=f"http://127.0.0.1:{depuracao}",
        )
        contador = [0]
        cdp_chama(ws, contador, "Runtime.enable")
        cdp_chama(ws, contador, "Page.enable")

        # Conta setters por alvo desde antes do primeiro JavaScript da página.
        cdp_chama(ws, contador, "Page.addScriptToEvaluateOnNewDocument", {
            "source": r"""
(() => {
  const mapa = {
    'enxame-reatores':'reatores', 'enxame-doca':'doca',
    'enxame-placar':'placar', 'enxame-fonte':'fonte',
    'enxame-remoto':'remoto'
  };
  window.__f1Writes = {reatores:0,doca:0,placar:0,fonte:0,remoto:0};
  const real = Object.getOwnPropertyDescriptor(Element.prototype, 'innerHTML');
  Object.defineProperty(Element.prototype, 'innerHTML', {
    configurable:true, enumerable:real.enumerable, get:real.get,
    set(valor){
      const alvo = mapa[this.id];
      if (alvo) window.__f1Writes[alvo] += 1;
      return real.set.call(this, valor);
    }
  });
})();
""",
        })
        cdp_chama(ws, contador, "Page.navigate", {
            "url": f"http://127.0.0.1:{porta}/?janela=enxame&t={token}",
        })
        limite = time.time() + 12
        pronto = False
        while time.time() < limite:
            pronto = bool(cdp_avalia(ws, contador,
                "document.readyState === 'complete' && !EX.ocupado && "
                "document.querySelectorAll('.enxame-reator').length === 1"))
            if pronto:
                break
            time.sleep(0.1)
        if not pronto:
            raise RuntimeError("a janela do enxame não concluiu a primeira carga")

        medidas["primeira"] = cdp_avalia(
            ws, contador, "({...window.__f1Writes})")
        time.sleep(2.25)
        medidas["tick_igual"] = cdp_avalia(
            ws, contador, "({...window.__f1Writes})")

        # Um observador por região classifica toda escrita: atributo, texto ou filho.
        cdp_avalia(ws, contador, r"""
(() => {
  if (window.__f1Observer) window.__f1Observer.disconnect();
  const zero = () => ({reatores:0,doca:0,placar:0,fonte:0,remoto:0,outro:0,total:0,reconstrucoes:0});
  window.__f1M = zero();
  window.__f1Bucket = (no, atributo) => {
    const el = no && no.nodeType === 1 ? no : no && no.parentElement;
    if (!el) return 'outro';
    const controles = ['ex-todos','ex-vivos','ex-falha','ex-ok','ex-dobrar'];
    if (controles.includes(el.id) || controles.some(id => el.closest && el.closest('#'+id))) return 'reatores';
    if (el.id === 'enxame' && atributo === 'data-doca') return 'doca';
    for (const [id,chave] of Object.entries({
      'enxame-reatores':'reatores','enxame-doca':'doca','enxame-placar':'placar',
      'enxame-fonte':'fonte','enxame-remoto':'remoto'})) {
      const alvo = document.getElementById(id);
      if (alvo && (el === alvo || alvo.contains(el))) return chave;
    }
    return 'outro';
  };
  window.__f1Take = () => {
    const atual = {...window.__f1M};
    window.__f1M = zero();
    return atual;
  };
  window.__f1Observer = new MutationObserver(lista => {
    for (const m of lista) {
      const chave = window.__f1Bucket(m.target, m.attributeName || '');
      window.__f1M[chave] += 1;
      window.__f1M.total += 1;
      if (m.type === 'childList' && m.target.id === 'enxame-reatores')
        window.__f1M.reconstrucoes += 1;
    }
  });
  window.__f1Observer.observe(document.getElementById('enxame'), {
    subtree:true, childList:true, attributes:true, characterData:true
  });
  window.__f1Take();
  return true;
})()
""")

        medidas["filtro"] = cdp_avalia(ws, contador, r"""
(async () => {
  __f1Take();
  document.getElementById('ex-ok').click();
  while (EX.ocupado) await new Promise(r => setTimeout(r, 20));
  await new Promise(r => setTimeout(r, 180));
  return __f1Take();
})()
""")
        medidas["worker_aberto"] = cdp_avalia(ws, contador, r"""
(async () => {
  __f1Take();
  document.querySelector('.enxame-w[data-worker="w-grok"] .enxame-w-cab').click();
  await new Promise(r => setTimeout(r, 80));
  return __f1Take();
})()
""")
        medidas["dobra"] = cdp_avalia(ws, contador, r"""
(async () => {
  __f1Take();
  document.querySelector('[data-dobra="prova-dourado"]').click();
  await new Promise(r => setTimeout(r, 80));
  return __f1Take();
})()
""")
        medidas["abre_doca"] = cdp_avalia(ws, contador, r"""
(async () => {
  __f1Take();
  document.querySelector('[data-abre="prova-dourado"]').click();
  while (EX.ocupado) await new Promise(r => setTimeout(r, 20));
  await new Promise(r => setTimeout(r, 180));
  return __f1Take();
})()
""")
        medidas["abre_remoto"] = cdp_avalia(ws, contador, r"""
(async () => {
  __f1Take();
  document.querySelector('[data-remoto="prova-dourado/w-grok"]').click();
  const limite = Date.now() + 5000;
  while (!document.getElementById('ex-fecha-remoto') && Date.now() < limite)
    await new Promise(r => setTimeout(r, 40));
  await new Promise(r => setTimeout(r, 80));
  return __f1Take();
})()
""")

        # Doca com scroll/foco e remoto com recibo pendente: são as invariantes
        # que uma reconstrução seguida de "restauração visual" não pode maquiar.
        cdp_avalia(ws, contador, r"""
(async () => {
  const doca = document.getElementById('enxame-doca');
  doca.style.height = '100px';
  doca.style.overflow = 'auto';
  doca.scrollTop = 60;
  EX.remotoAcao = {nome:'parar', recibo:'recibo-f1-pendente'};
  const saida = document.getElementById('ex-remoto-acao-saida');
  if (saida) saida.innerHTML = '<b>previsão pendente F1</b>';
  const botao = document.querySelector('[data-remoto-acao="parar"]');
  if (botao) { botao.setAttribute('aria-pressed','true'); botao.textContent='confirmar: parar esta IA'; }
  await new Promise(r => setTimeout(r, 900));
  doca.scrollTop = 60;
  const foco = document.getElementById('ex-fecha-doca');
  foco.focus();
  window.__f1Refs = {
    card:document.querySelector('.enxame-reator'),
    dobra:document.querySelector('[data-dobra="prova-dourado"]'),
    worker:document.querySelector('.enxame-w[data-worker="w-grok"]'),
    doca:document.querySelector('#enxame-doca .enxame-doca-topo'),
    remoto:document.querySelector('#enxame-remoto .enxame-doca-topo'),
    foco
  };
  window.__f1Estado = {
    scroll:doca.scrollTop,
    remoto:document.getElementById('enxame-remoto').innerHTML
  };
  __f1Take();
  return true;
})()
""")

        medidas["imovel_30s"] = cdp_avalia(ws, contador, r"""
(async () => {
  await new Promise(r => setTimeout(r, 30000));
  const contagens = __f1Take();
  const refs = window.__f1Refs;
  const card = document.querySelector('.enxame-reator');
  const dobra = document.querySelector('[data-dobra="prova-dourado"]');
  const worker = document.querySelector('.enxame-w[data-worker="w-grok"]');
  const docaNo = document.querySelector('#enxame-doca .enxame-doca-topo');
  const remotoNo = document.querySelector('#enxame-remoto .enxame-doca-topo');
  const doca = document.getElementById('enxame-doca');
  return {contagens, identidade:{
      card:refs.card.isSameNode(card), dobra:refs.dobra.isSameNode(dobra),
      worker:refs.worker.isSameNode(worker), doca:refs.doca.isSameNode(docaNo),
      remoto:refs.remoto.isSameNode(remotoNo)
    }, estado:{
      dobrado:card.classList.contains('recolhido'),
      dobraAria:dobra.getAttribute('aria-expanded') === 'false',
      workerAberto:worker.classList.contains('aberto'),
      workerAria:worker.querySelector('.enxame-w-cab').getAttribute('aria-expanded') === 'true',
      filtro:document.getElementById('ex-ok').getAttribute('aria-pressed') === 'true',
      swarm:EX.swarm === 'prova-dourado', scroll:doca.scrollTop === window.__f1Estado.scroll,
      foco:document.activeElement === refs.foco,
      remoto:document.getElementById('enxame-remoto').innerHTML === window.__f1Estado.remoto,
      recibo:EX.remotoAcao && EX.remotoAcao.recibo === 'recibo-f1-pendente'
    }};
})()
""")

        with (run / "progress" / "w-grok.jsonl").open("a", encoding="utf-8") as arq:
            arq.write('{"ts":"08:11:00","etapa":3,"de":5,"estado":"rodando","nota":"passo novo F1"}\n')
        medidas["progresso"] = cdp_avalia(ws, contador, r"""
(async () => {
  __f1Take();
  const limite = Date.now() + 4500;
  while (!document.getElementById('enxame-reatores').textContent.includes('passo novo F1') && Date.now() < limite)
    await new Promise(r => setTimeout(r, 80));
  const apareceu = document.getElementById('enxame-reatores').textContent.includes('passo novo F1');
  await new Promise(r => setTimeout(r, 1100));
  return {apareceu, contagens:__f1Take()};
})()
""")
        medidas["estavel_6s"] = cdp_avalia(ws, contador, r"""
(async () => {
  __f1Take();
  await new Promise(r => setTimeout(r, 6000));
  return __f1Take();
})()
""")

        with (run / "logs" / "w-codex.log").open("a", encoding="utf-8") as arq:
            arq.write("x" * 2600)
        medidas["log"] = cdp_avalia(ws, contador, r"""
(async () => {
  __f1Take();
  const limite = Date.now() + 4500;
  while (!(document.querySelector('.enxame-det-item.mau .peso') || {}).textContent?.includes('KB') && Date.now() < limite)
    await new Promise(r => setTimeout(r, 80));
  await new Promise(r => setTimeout(r, 220));
  return {
    apareceu:!!document.querySelector('.enxame-det-item.mau .peso') &&
      document.querySelector('.enxame-det-item.mau .peso').textContent.includes('KB'),
    contagens:__f1Take()
  };
})()
""")

        medidas["erro_primeiro"] = cdp_avalia(ws, contador, r"""
(async () => {
  while (EX.ocupado) await new Promise(r => setTimeout(r, 20));
  window.__f1FetchReal = window.fetch;
  window.fetch = (...args) => String(args[0]||'').includes('/api/iaswarm') &&
    !String(args[0]||'').includes('/remoto')
      ? Promise.reject(new Error('falha F1 repetida')) : window.__f1FetchReal(...args);
  __f1Take();
  await exTick();
  await new Promise(r => setTimeout(r, 80));
  return __f1Take();
})()
""")
        medidas["erro_repetido"] = cdp_avalia(ws, contador, r"""
(async () => {
  while (EX.ocupado) await new Promise(r => setTimeout(r, 20));
  __f1Take();
  await exTick();
  await new Promise(r => setTimeout(r, 80));
  return __f1Take();
})()
""")
        medidas["recuperacao"] = cdp_avalia(ws, contador, r"""
(async () => {
  window.fetch = window.__f1FetchReal;
  while (EX.ocupado) await new Promise(r => setTimeout(r, 20));
  __f1Take();
  await exTick();
  await new Promise(r => setTimeout(r, 120));
  const contagens = __f1Take();
  window.__f1Observer.disconnect();
  return {contagens, recuperou:document.getElementById('enxame-reatores').textContent.includes('prova-dourado')};
})()
""")
    except Exception as exc:
        return {"block": str(exc), "parcial": medidas}
    finally:
        if ws is not None:
            ws.close()
        if chrome is not None and chrome.poll() is None:
            chrome.terminate()
            try:
                chrome.wait(timeout=5)
            except subprocess.TimeoutExpired:
                chrome.kill()
                chrome.wait(timeout=5)
        shutil.rmtree(perfil, ignore_errors=True)
    return medidas


def servidor_runtime_main() -> int:
    """Mantém fixture/servidor efêmeros vivos para um navegador MCP externo."""
    home = Path(tempfile.mkdtemp(prefix="ui-enxame-runtime-home-"))
    enxame = Path(tempfile.mkdtemp(prefix="ui-enxame-runtime-runs-"))
    run = enxame / "prova-dourado"
    (run / "progress").mkdir(parents=True)
    (run / "logs").mkdir()
    (run / "resultados").mkdir()
    (run / "missao.md").write_text("# missão de prova do visualizador\n", encoding="utf-8")
    (run / "workers.tsv").write_text(
        "w-grok\tgrok\t5\n"
        "w-codex\tcodex\t4\n",
        encoding="utf-8")
    (run / "progress" / "w-grok.jsonl").write_text(
        '{"ts":"08:00:00","etapa":0,"de":5,"estado":"despachado","nota":"grok (beta)"}\n'
        '{"ts":"08:10:00","etapa":2,"de":5,"estado":"rodando","nota":"pintando o ouro"}\n',
        encoding="utf-8")
    (run / "progress" / "w-codex.jsonl").write_text(
        '{"ts":"08:02:00","etapa":0,"de":4,"estado":"despachado","nota":"codex"}\n'
        '{"ts":"08:08:00","etapa":2,"de":4,"estado":"falhou","nota":"falha de prova"}\n',
        encoding="utf-8")
    (run / "logs" / "w-grok.log").write_text("linha 1\nlinha 2 do terminal\n", encoding="utf-8")
    (run / "logs" / "w-codex.log").write_text("falha inicial\n", encoding="utf-8")
    (run / "resultados" / "w-grok.md").write_text(
        "missão: prova\nresultado: ok\n", encoding="utf-8")

    porta = porta_livre(59900)
    proc, token = sobe(home, porta, enxame)
    if not token:
        print("BLOCK runtime externo: servidor sem token", flush=True)
        return 2
    print("RUNTIME_F1 " + json.dumps({
        "url": f"http://127.0.0.1:{porta}/?janela=enxame&t={token}",
        "run": str(run), "porta": porta,
    }, ensure_ascii=False), flush=True)
    try:
        return proc.wait()
    except KeyboardInterrupt:
        return 0
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        shutil.rmtree(home, ignore_errors=True)
        shutil.rmtree(enxame, ignore_errors=True)


def main() -> int:
    print("— as peças na interface —")
    checa("o botão da gaveta no topo existe", 'id="btn-gaveta-topo"' in HTML)
    topo = re.search(r'<button[^>]*id="btn-gaveta-topo"[^>]*>', HTML)
    checa("o botão do topo tem o mesmo aria-controls da gaveta",
          bool(topo) and 'aria-controls="gaveta"' in topo.group(0)
          and "aria-label=" in topo.group(0))
    checa("os dois botões da gaveta compartilham o mesmo gesto",
          "function botoesGaveta" in JS and "botoesGaveta().forEach" in JS)

    botao_enxame = elemento_por_id(HTML, "button", "btn-enxame")
    checa("a rota inferior usa o wordmark SVG histórico com filete",
          rota_iaswarm_tem_wordmark(botao_enxame, HTML),
          "esperado button type=button + aria-controls + SVG prefixado; "
          "letreiro textual não vale como logo")
    falso_textual = (
        '<button type="button" id="btn-enxame" aria-controls="enxame" '
        'aria-pressed="false"><span>IASWARM</span></button>'
    )
    checa("controle negativo rejeita IASWARM escrito em span",
          not rota_iaswarm_tem_wordmark(falso_textual, falso_textual))

    # O rodapé inteiro é contrato: sino, rota, tema e gaveta, nessa ordem.
    rodape = HTML[HTML.index("trilho-rodape"):HTML.index("cabeca")]
    ordem_rodape = [rodape.find(f'id="{ident}"') for ident in
                    ("btn-sino", "btn-enxame", "btn-tema", "btn-gaveta")]
    checa("o rodapé preserva sino, IASWARM, tema e gaveta nessa ordem",
          all(pos >= 0 for pos in ordem_rodape)
          and ordem_rodape == sorted(ordem_rodape),
          repr(ordem_rodape))
    checa("clicar a logo troca a janela",
          "function janelaEnxame" in JS
          and JS.count("$('#btn-enxame').addEventListener") == 1
          and "$('#btn-enxame').addEventListener('click', ()=> janelaEnxame())" in JS,
          "a rota deve manter um único listener e passar por janelaEnxame()")
    i_modo = JS.find("function janelaModo")
    i_enxame = JS.find("function janelaEnxame", i_modo)
    bloco_modo = JS[i_modo:i_enxame] if i_modo >= 0 and i_enxame > i_modo else ""
    checa("o estado ativo da rota inferior nasce em janelaModo",
          "$('#btn-enxame')" in bloco_modo
          and "setAttribute('aria-pressed'" in bloco_modo)
    checa("a janela IASWARM existe no HTML", 'id="enxame"' in HTML and 'id="enxame-reatores"' in HTML)
    checa("a malha quadriculada dourada existe", ".enxame-malha{" in CSS
          and "repeating-linear-gradient" in CSS[CSS.index(".enxame-malha{"):CSS.index(".enxame-malha{")+500])
    checa("o modo neon é o outro modo, não o padrão",
          "dataset.enxameModo" in JS and "modo neon" in HTML)

    print("— funções do neon que sobreviveram —")
    for pedaco, onde in (
        ("reatores por run", "enxame-reator"),
        ("doca de detalhe", "enxame-doca"),
        ("recolher um", "data-dobra"),
        ("recolher todos", "ex-dobrar"),
        ("métricas/placar", "enxame-placar"),
        ("leitura ao vivo", "/api/iaswarm"),
        ("filtros", "data-filtro"),
        ("foco", "ex-foco"),
        ("transições", "enxame-log"),
        ("controle remoto", "abreRemoto"),
    ):
        checa(f"existe {pedaco}", onde in JS or onde in HTML)

    print("— M4 · foco de teclado sobrevive ao tick —")
    checa("M4: envelope exTrocando existe", "function exTrocando" in JS)
    checa("M4: o envelope lê document.activeElement",
          "function exTrocando" in JS and "document.activeElement" in JS[JS.index("function exTrocando"):JS.index("function exTrocando")+700]
          if "function exTrocando" in JS else False)
    checa("M4: devolve o foco com preventScroll",
          "preventScroll" in JS and "data-foco" in JS)
    checa("M4: data-foco no recolher do run", 'data-foco="dobra:' in JS)
    checa("M4: data-foco no abrir da doca", 'data-foco="abre:' in JS)
    checa("M4: exRender troca o DOM pelo envelope",
          "exTrocando(EX.reatores" in JS)

    print("— F1 · assinatura semântica por alvo —")
    bloco_ex = re.search(r"const EX\s*=\s*\{([\s\S]*?)\n\};", JS)
    corpo_ex = bloco_ex.group(1) if bloco_ex else ""
    checa("F1: EX.sig guarda exatamente os cinco alvos",
          "sig:" in corpo_ex and all(
              re.search(rf"\b{nome}\s*:\s*null\b", corpo_ex)
              for nome in ("reatores", "doca", "placar", "fonte", "erro")
          ))
    checa("F1: a serialização é determinística e sem hash criptográfico",
          "JSON.stringify" in JS and "crypto.subtle" not in JS)
    checa("F1: animações transitórias expiram sem depender do próximo tick",
          "setTimeout" in JS and "avancou" in JS and "estreia" in JS)

    print("— M3 · relógio da última evidência no cartão —")
    checa("M3: helper exHhmm existe", "function exHhmm" in JS)
    checa("M3: o cartão imprime entregues · HH:MM",
          "exHhmm(agora)" in JS and "entregues" in JS)
    checa("M3: o relógio só aparece com evidência",
          bool(re.search(r"agora\s*!=\s*null.*exHhmm\(agora\)", JS)))

    print("— M5 · paleta ampla + apelidos, no humor dourado —")
    checa("M5: mapa EX_ALIAS existe", "const EX_ALIAS" in JS)
    checa("M5: k2 aponta para kimi", bool(re.search(r'\bk2\s*:\s*[\'"]kimi[\'"]', JS)))
    checa("M5: dashscope aponta para alibaba",
          bool(re.search(r'dashscope\s*:\s*[\'"]alibaba[\'"]', JS)))
    checa("M5: gpt aponta para openai", bool(re.search(r'\bgpt\s*:\s*[\'"]openai[\'"]', JS)))
    checa("M5: mistral tem cor doutrinada", bool(re.search(r'\bmistral\s*:\s*[\'"]#', JS)))
    checa("M5: nvidia tem cor doutrinada", bool(re.search(r'\bnvidia\s*:\s*[\'"]#', JS)))
    checa("M5: azure tem cor doutrinada", bool(re.search(r'\bazure\s*:\s*[\'"]#', JS)))
    checa("M5: exCorBraco consulta EX_ALIAS",
          "EX_ALIAS[b]" in JS and "EX_CORES[EX_ALIAS[b]]" in JS)

    print("— M2 · deep link: abrir=worker, swarm=doca —")
    checa("M2: ?swarm= abre a doca",
          'q.get("swarm")' in JS or "q.get('swarm')" in JS)
    checa("M2: ?abrir= não vira doca",
          not re.search(r"if\s*\(\s*abrir\s*\)\s*EX\.swarm", JS))
    checa("M2: conjunto EX_ABRIR_URL existe", "EX_ABRIR_URL" in JS)
    checa("M2: ?abrir= expande o worker na primeira pintura",
          "EX_ABRIR_URL.has(w.id)" in JS)

    print("— M1 · snapshot: declarado, não portado —")
    design = (UI / "DESIGN.md").read_text(encoding="utf-8")
    checa("M1: DESIGN.md registra o snapshot como deliberado",
          "fonte=snapshot" in design and "deliberado" in design.lower())

    print("— M7 · estreia decorativa, uma vez —")
    checa("M7: marca estreia só na primeira pintura",
          "classList.toggle('estreia'" in JS or 'classList.toggle("estreia"' in JS)
    checa("M7: CSS da entrada existe",
          "enxame-sobe" in CSS and "#enxame.estreia" in CSS)
    checa("M7: prefers-reduced-motion desliga a malha e a respiração",
          "@media (prefers-reduced-motion:reduce)" in CSS
          and ".enxame-malha" in CSS[CSS.index("@media (prefers-reduced-motion:reduce)"):])

    print("— a rota é leitura, e o cliente não escolhe pasta —")
    fonte = SERVIR.read_text(encoding="utf-8")
    checa("existe /api/iaswarm", 'u.path == "/api/iaswarm"' in fonte)
    checa("existe /api/iaswarm/remoto", 'u.path == "/api/iaswarm/remoto"' in fonte)
    checa("a raiz não vem da query", "q.get(\"raiz\")" not in fonte and "q.get('path')" not in fonte)
    checa("o id do run passa por allowlist", "RE_IASWARM_ID" in fonte)
    checa("a pasta resolve e recusa escape", "relative_to(raiz)" in fonte)

    home = Path(tempfile.mkdtemp(prefix="ui-enxame-sala-"))
    enxame = Path(tempfile.mkdtemp(prefix="ui-enxame-runs-"))
    run = enxame / "prova-dourado"
    (run / "progress").mkdir(parents=True)
    (run / "logs").mkdir()
    (run / "resultados").mkdir()
    (run / "missao.md").write_text("# missão de prova do visualizador\n", encoding="utf-8")
    (run / "workers.tsv").write_text(
        "w-grok\tgrok\t5\n"
        "w-codex\tcodex\t4\n",
        encoding="utf-8")
    (run / "progress" / "w-grok.jsonl").write_text(
        '{"ts":"08:00:00","etapa":0,"de":5,"estado":"despachado","nota":"grok (beta)"}\n'
        '{"ts":"08:10:00","etapa":2,"de":5,"estado":"rodando","nota":"pintando o ouro"}\n',
        encoding="utf-8")
    (run / "progress" / "w-codex.jsonl").write_text(
        '{"ts":"08:02:00","etapa":0,"de":4,"estado":"despachado","nota":"codex"}\n'
        '{"ts":"08:08:00","etapa":2,"de":4,"estado":"falhou","nota":"falha de prova"}\n',
        encoding="utf-8")
    (run / "logs" / "w-grok.log").write_text("linha 1\nlinha 2 do terminal\n", encoding="utf-8")
    (run / "logs" / "w-codex.log").write_text("falha inicial\n", encoding="utf-8")
    (run / "resultados" / "w-grok.md").write_text("missão: prova\nresultado: ok\n", encoding="utf-8")

    porta = porta_livre()
    proc, token = sobe(home, porta, enxame)
    try:
        if not token:
            checa("servidor subiu e anunciou o token", False, "sem token no stdout")
            return 1

        print("— o que atravessa —")
        cod, corpo = pede(porta, "/api/iaswarm", token)
        dados = json.loads(corpo) if cod == 200 else {}
        checa("GET /api/iaswarm responde 200", cod == 200, f"HTTP {cod} {corpo[:160]}")
        runs = dados.get("runs") or []
        checa("a resposta traz o run de prova",
              any(r.get("id") == "prova-dourado" for r in runs), str([r.get("id") for r in runs]))
        checa("o progresso do worker chegou",
              any("w-grok" in (r.get("progress") or {}) for r in runs))

        cod, corpo = pede(porta, "/api/iaswarm/remoto?run=prova-dourado&worker=w-grok", token)
        remoto = json.loads(corpo) if cod == 200 else {}
        checa("GET /api/iaswarm/remoto responde 200", cod == 200, f"HTTP {cod}")
        checa("o remoto traz a cauda do terminal",
              "linha 2 do terminal" in (remoto.get("log") or ""), str(remoto.get("log"))[:80])
        checa("o remoto traz os eventos",
              isinstance(remoto.get("eventos"), list) and len(remoto["eventos"]) == 2)

        print("— F1 · gate rápido + navegador real —")
        estabilidade = estabilidade_enxame_browser(porta, token, run)
        checa("F1: o instrumento conseguiu olhar o navegador real",
              "block" not in estabilidade,
              str(estabilidade.get("block", ""))[:220])
        primeira = estabilidade.get("primeira") or {}
        tick_igual = estabilidade.get("tick_igual") or {}
        checa("F1: a primeira carga escreve uma vez por alvo",
              all(primeira.get(k) == 1 for k in ("reatores", "doca", "placar", "fonte")),
              repr(primeira))
        checa("F1: a mesma resposta não acrescenta setter",
              tick_igual == primeira, repr({"primeira": primeira, "tick": tick_igual}))

        somente = lambda m, permitidos: (
            m.get("total", 0) > 0 and
            all(m.get(k, 0) == 0 for k in
                ({"reatores", "doca", "placar", "fonte", "remoto", "outro"} - set(permitidos)))
        )
        filtro = estabilidade.get("filtro") or {}
        checa("F1: filtro muda somente os reatores",
              filtro.get("reatores", 0) > 0 and somente(filtro, {"reatores"}), repr(filtro))
        aberto = estabilidade.get("worker_aberto") or {}
        checa("F1: abrir worker é mutação local dos reatores",
              aberto.get("reatores", 0) > 0 and somente(aberto, {"reatores"}), repr(aberto))
        dobra = estabilidade.get("dobra") or {}
        checa("F1: dobra muda somente os reatores",
              dobra.get("reatores", 0) > 0 and somente(dobra, {"reatores"}), repr(dobra))
        doca = estabilidade.get("abre_doca") or {}
        checa("F1: selecionar doca muda somente reatores e doca",
              doca.get("reatores", 0) > 0 and doca.get("doca", 0) > 0
              and somente(doca, {"reatores", "doca"}), repr(doca))

        imovel = estabilidade.get("imovel_30s") or {}
        cont_imovel = imovel.get("contagens") or {}
        print("  medição imóvel 30 s:", json.dumps(cont_imovel, ensure_ascii=False, sort_keys=True))
        checa("F1: 30 s imóveis produzem exatamente zero mutações",
              cont_imovel.get("total") == 0, repr(cont_imovel))
        checa("F1: cartão, dobra, worker, doca e remoto são os mesmos nós",
              imovel.get("identidade") and all(imovel["identidade"].values()),
              repr(imovel.get("identidade")))
        checa("F1: dobra, aberto, filtro, scroll, foco, seleção e recibo sobrevivem",
              imovel.get("estado") and all(imovel["estado"].values()),
              repr(imovel.get("estado")))

        progresso = estabilidade.get("progresso") or {}
        mut_progresso = progresso.get("contagens") or {}
        checa("F1: append no progress aparece sem worker novo",
              progresso.get("apareceu") is True, repr(progresso))
        checa("F1: etapa/nota atualiza reatores e doca, não os outros alvos",
              mut_progresso.get("reatores", 0) > 0 and mut_progresso.get("doca", 0) > 0
              and somente(mut_progresso, {"reatores", "doca"}), repr(mut_progresso))
        estavel = estabilidade.get("estavel_6s") or {}
        checa("F1: após a atualização, seis segundos voltam a zero",
              estavel.get("total") == 0, repr(estavel))

        log = estabilidade.get("log") or {}
        mut_log = log.get("contagens") or {}
        checa("F1: crescimento de log aparece na doca aberta",
              log.get("apareceu") is True, repr(log))
        checa("F1: log isolado atualiza somente a doca",
              mut_log.get("doca", 0) > 0 and somente(mut_log, {"doca"}), repr(mut_log))
        erro_um = estabilidade.get("erro_primeiro") or {}
        erro_dois = estabilidade.get("erro_repetido") or {}
        checa("F1: o primeiro erro escreve reatores e fonte",
              erro_um.get("reatores", 0) > 0 and erro_um.get("fonte", 0) > 0,
              repr(erro_um))
        checa("F1: o mesmo erro repetido faz zero escrita",
              erro_dois.get("total") == 0, repr(erro_dois))
        recuperacao = estabilidade.get("recuperacao") or {}
        checa("F1: recuperação volta aos dados e invalida os alvos necessários",
              recuperacao.get("recuperou") is True
              and (recuperacao.get("contagens") or {}).get("reatores", 0) > 0
              and (recuperacao.get("contagens") or {}).get("fonte", 0) > 0,
              repr(recuperacao))

        print("— o que REPROVA —")
        for rota, esperado in (
            ("/api/iaswarm?run=../etc", 404),
            ("/api/iaswarm?run=..%2F..%2Fetc", 404),
            ("/api/iaswarm/remoto?run=../etc&worker=w-grok", 400),
            ("/api/iaswarm/remoto?run=prova-dourado&worker=../../passwd", 400),
            ("/api/iaswarm/remoto", 400),
        ):
            # 404 ou 400: o importante é não ser 200 com dado de fora
            cod, corpo = pede(porta, rota, token)
            checa(f"REPROVA: {rota} não entrega disco alheio",
                  cod in (400, 404) and "etc" not in corpo and "passwd" not in corpo,
                  f"HTTP {cod} {corpo[:120]}")

        cod, _ = pede(porta, "/api/iaswarm")
        checa("REPROVA: /api/iaswarm sem token devolve 401", cod == 401, f"HTTP {cod}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(home, ignore_errors=True)
        shutil.rmtree(enxame, ignore_errors=True)

    print()
    print("— o modo do enxame é endereço, e entra por um lugar só —")
    # A família dos deep-links: tema, aba, janela, abrir, swarm, remoto. O modo
    # ficava de fora — quem mandava um link do painel neon chegava no dourado.
    checa("M8: `?modo=` é lido da URL", "get('modo')" in JS)
    checa("M8: só neon e dourado são aceitos",
          "=== 'neon' || pedido === 'dourado'" in JS,
          "nome desconhecido não pode apagar o modo atual")
    checa("M8: um lugar só escreve o modo",
          JS.count("dataset.enxameModo =") == 1,
          "dois lugares escrevendo divergem no rótulo ou no aria-pressed — "
          "foi o que aconteceu com os dois botões da gaveta hoje")
    checa("M8: o botão e a URL passam pela mesma função",
          "function poeModo" in JS and JS.count("poeModo(") >= 3)

    print(f"{_ok} ✔  {_falhou} ✗")
    return 1 if _falhou else 0


if __name__ == "__main__":
    raise SystemExit(servidor_runtime_main() if "--runtime-server" in sys.argv else main())
