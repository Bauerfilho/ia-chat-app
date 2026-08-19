#!/usr/bin/env python3
"""Contrato do groupchat: sessão da IA, sentinela de compactação e duas cores.

O teste cruza três instrumentos: executa a normalização JavaScript em Node,
chama o adaptador Python sobre um JSONL real e audita o CSS que separa
identidade de estado. Assim uma string decorativa não consegue aprovar sozinha.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.dont_write_bytecode = True

RAIZ = Path(__file__).resolve().parent.parent
UI = RAIZ / "ui"
JS = (UI / "sala.js").read_text(encoding="utf-8")
CSS = (UI / "estilo.css").read_text(encoding="utf-8")
SERVIR = UI / "servir.py"
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

_ok = 0
_falhou = 0
TETO_GROUPCHAT_CONTRATO = 48 * 1024


def checa(nome: str, cond: bool, detalhe: str = "") -> None:
    """Imprime cada gate e acumula o veredito final."""
    global _ok, _falhou
    if cond:
        _ok += 1
        print(f"  ✔ {nome}")
    else:
        _falhou += 1
        sufixo = f" — {detalhe}" if detalhe else ""
        print(f"  ✗ {nome}{sufixo}")


def trecho(inicio: str, fim: str, fonte: str = JS) -> str:
    """Recorta uma unidade nomeada; ausência vira texto vazio e reprova."""
    a = fonte.find(inicio)
    if a < 0:
        return ""
    b = fonte.find(fim, a + len(inicio))
    return fonte[a:] if b < 0 else fonte[a:b]


def normalizacao_js() -> dict:
    """Executa a função real, sem reimplementar a conta no teste."""
    funcoes = trecho("function gcNumeroPositivo", "function gcDesconhecido")
    programa = funcoes + r"""
const exact = gcContexto({
  room_bytes: 999999999,
  context: {state:'exact', last_prompt_tokens:168000,
            estimated_prompt_tokens:null, context_window_tokens:250000,
            room_bytes:999999999}
});
const compactou = gcContexto({
  context: {state:'exact', last_prompt_tokens:-1,
            estimated_prompt_tokens:null, context_window_tokens:250000}
});
const estimado = gcContexto({
  context: {state:'estimated', last_prompt_tokens:null,
            estimated_prompt_tokens:236000, context_window_tokens:1000000}
});
const zero = gcContexto({
  context: {state:'exact', last_prompt_tokens:0,
            estimated_prompt_tokens:null, context_window_tokens:250000}
});
console.log(JSON.stringify({exact, compactou, estimado, zero}));
"""
    r = subprocess.run(
        ["node", "-e", programa], capture_output=True, text=True, timeout=10
    )
    if r.returncode != 0:
        return {"erro": (r.stderr or r.stdout).strip()}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"erro": r.stdout.strip()}


def aviso_corte_js() -> dict:
    """Executa o aviso real e prova que o corte inicial não some no tick limpo."""
    bytes_fn = trecho("function bytesLegiveis", "function haQuanto")
    aviso_fn = trecho("function gcAtualizaAvisoCorte", "async function gcCarregar")
    programa = bytes_fn + aviso_fn + r"""
const fmtNum = new Intl.NumberFormat('pt-BR');
const GC = {
  aviso:{textContent:'',hidden:true}, limites:{itens:24,bytes:49152},
  corteInicial:null,corteAtual:null,itensGrandesOmitidos:0,telemetriaOmitida:0
};
gcAtualizaAvisoCorte({ativo:true,motivo:'itens',omitidas:34,pendentes:0,
  telemetria_omitida:0,sessoes_omitidas:0,direcao:'inicio'}, true);
const inicial = {texto:GC.aviso.textContent,hidden:GC.aviso.hidden};
gcAtualizaAvisoCorte({ativo:false,motivo:'nenhum',omitidas:0,pendentes:0,
  telemetria_omitida:0,sessoes_omitidas:0,direcao:'nenhuma'}, false);
const seguinte = {texto:GC.aviso.textContent,hidden:GC.aviso.hidden};
console.log(JSON.stringify({inicial,seguinte}));
"""
    r = subprocess.run(
        ["node", "-e", programa], capture_output=True, text=True, timeout=10
    )
    if r.returncode != 0:
        return {"erro": (r.stderr or r.stdout).strip()}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"erro": r.stdout.strip()}


def adaptador_python(tmp: Path) -> dict:
    """Carrega o servidor com sidecar isolado e sala falsa de peso extremo."""
    sidecar = tmp / "groupchat.jsonl"
    sidecar.write_text(
        json.dumps({
            "ia_id": "codex", "session_id": "cx_7f2a",
            "model_id": "gpt-5.6-sol", "message_n": 7,
            "context": {
                "state": "exact", "last_prompt_tokens": 168000,
                "estimated_prompt_tokens": None,
                "context_window_tokens": 250000,
                "source": "provider.usage.prompt_tokens",
                "sampled_at": "2026-08-18T15:42:08-03:00",
                "reason": None,
            },
            "liveness": {"last_signal_at": "2026-08-18T15:42:08-03:00",
                         "session_state": "running"},
            "actions": [{"description_pt": "Validar a janela da sessão",
                         "type": "Shell", "state": "completed",
                         "command": "context-meter --session cx_7f2a",
                         "output": "168000"}],
        }, ensure_ascii=False) + "\n" +
        json.dumps({
            "ia_id": "qwen", "session_id": "qw_228b",
            "model_id": "qwen", "message_n": 8,
            # Mentira deliberada do produtor: a sentinela precisa vencer `exact`.
            "context": {"state": "exact", "last_prompt_tokens": -1,
                        "estimated_prompt_tokens": None,
                        "context_window_tokens": 1000000,
                        "sampled_at": "2026-08-18T15:43:08-03:00"},
            "liveness": {"session_state": "running"},
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    os.environ["IACHAT_GROUPCHAT"] = str(sidecar)
    spec = importlib.util.spec_from_file_location("servir_groupchat_teste", SERVIR)
    if spec is None or spec.loader is None:
        return {"erro": "não carreguei servir.py"}
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    # O peso absurdo pertence à sala; não pode contaminar o snapshot da sessão.
    modulo.msgs_desde = lambda _n: [{
        "n": 7, "de": "codex", "para": ["all"],
        "ts": "2026-08-18T15:42:08-03:00", "texto": "feito",
        "bytes": 999999999,
    }]
    modulo.sala = lambda: {"na_sala": ["codex", "qwen", "kimi"]}
    return modulo.groupchat()


def cursor_python() -> dict:
    """Exercita cursor e teto contra uma sala grande, sem reimplementar o corte."""
    spec = importlib.util.spec_from_file_location("servir_groupchat_cursor", SERVIR)
    if spec is None or spec.loader is None:
        return {"erro": "não carreguei servir.py"}
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)

    # 120 falas de ~3,6 KB: o limite de itens sozinho deixaria o JSON passar de
    # 80 KB. Portanto, este fixture prova especificamente o teto de bytes.
    mensagens = [{
        "n": n,
        "de": "codex" if n % 2 else "qwen",
        "para": ["all"],
        "ts": f"2026-08-18T15:{n % 60:02d}:08-03:00",
        "texto": f"mensagem-{n}-" + ("x" * 3500),
        "bytes": 3520,
    } for n in range(1, 121)]
    chamadas: list[int] = []

    def falsas_desde(desde: int) -> list[dict]:
        chamadas.append(desde)
        return [m for m in mensagens if m["n"] > desde]

    modulo.msgs_desde = falsas_desde
    modulo.ultima = lambda: 120
    modulo.sala = lambda: {"na_sala": ["codex", "qwen"]}
    modulo._groupchat_atualizacoes = lambda: []
    modulo.CFG["papel"] = "bauer"

    inicial = modulo.groupchat(0)
    vazio = modulo.groupchat(inicial.get("ultima", 0))
    backlog = modulo.groupchat(80)

    def resumo(resposta: dict) -> dict:
        msgs = resposta.get("msgs") or []
        return {
            "bytes": len(json.dumps(resposta, ensure_ascii=False).encode()),
            "itens": len(msgs),
            "primeira": msgs[0]["n"] if msgs else None,
            "ultima_msg": msgs[-1]["n"] if msgs else None,
            "cursor": resposta.get("ultima"),
            "ultima_sala": resposta.get("ultima_sala"),
            "corte": resposta.get("corte") or {},
        }

    return {
        "teto_configurado": modulo.TETO_GROUPCHAT_RESPOSTA,
        "limite_itens": modulo.LIMITE_GROUPCHAT_ITENS,
        "chamadas": chamadas,
        "inicial": resumo(inicial),
        "vazio": resumo(vazio),
        "backlog": resumo(backlog),
    }


def porta_livre() -> int:
    """Reserva efêmera para o servidor de prova; nunca usa :8801."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def espera_http(porta: int, caminho: str, prazo: float = 10.0) -> None:
    """Só retorna quando a ponta realmente responder."""
    limite = time.time() + prazo
    ultimo = "sem resposta"
    while time.time() < limite:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{porta}{caminho}", timeout=1
            ) as r:
                if r.status == 200:
                    return
        except Exception as exc:  # a próxima sondagem carrega o detalhe novo
            ultimo = str(exc)
        time.sleep(0.1)
    raise RuntimeError(f"HTTP não ficou pronto: {ultimo}")


def cdp_chama(ws, contador: list[int], metodo: str, parametros: dict | None = None) -> dict:
    """Chamada mínima ao Chrome DevTools Protocol, esperando o próprio id."""
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


def mede_iframe(ws, contador: list[int], largura: int, porta: int) -> dict:
    """Mede no documento interno; o viewport do Chrome pai é irrelevante."""
    origem = f"http://127.0.0.1:{porta}/?janela=groupchat"
    expressao = f"""
new Promise((resolve, reject) => {{
  const velho = document.getElementById('__medida_groupchat');
  if (velho) velho.remove();
  const quadro = document.createElement('iframe');
  quadro.id = '__medida_groupchat';
  quadro.style.cssText = 'display:block;border:0;width:{largura}px;height:900px';
  quadro.src = {json.dumps(origem)};
  const limite = setTimeout(() => reject(new Error('iframe não carregou')), 8000);
  quadro.onload = () => setTimeout(() => {{
    clearTimeout(limite);
    const doc = quadro.contentDocument;
    const raiz = doc.documentElement;
    const corpo = doc.body;
    const clientWidth = raiz.clientWidth;
    const scrollWidth = Math.max(raiz.scrollWidth, corpo.scrollWidth);
    const ofensores = [...doc.querySelectorAll('body *')].map(el => {{
      const r = el.getBoundingClientRect();
      return {{tag:el.tagName.toLowerCase(), classe:String(el.className||'').slice(0,80),
               left:Math.round(r.left*10)/10, right:Math.round(r.right*10)/10}};
    }}).filter(x => x.left < -0.5 || x.right > clientWidth + 0.5).slice(0,12);
    resolve({{
      pedido:{largura}, clientWidth, scrollWidth,
      modo:raiz.dataset.janela || '',
      falas:doc.querySelectorAll('.gc-fala').length,
      barras:doc.querySelectorAll('.gc-contexto').length,
      acoes:doc.querySelectorAll('.gc-acao').length,
      ofensores
    }});
  }}, 1200);
  document.body.appendChild(quadro);
}})
"""
    resposta = cdp_chama(ws, contador, "Runtime.evaluate", {
        "expression": expressao,
        "awaitPromise": True,
        "returnByValue": True,
    })
    remoto = resposta.get("result") or {}
    if remoto.get("subtype") == "error":
        raise RuntimeError(remoto.get("description") or "erro no iframe")
    return remoto.get("value") or {}


def layout_main() -> int:
    """Prova visual exigida: três iframes, sem julgar pelo viewport do Chrome."""
    try:
        import websocket
    except ImportError:
        print("BLOCK: módulo websocket ausente")
        return 2
    if not CHROME.is_file():
        print(f"BLOCK: Chrome ausente em {CHROME}")
        return 2

    with tempfile.TemporaryDirectory(prefix="ui-groupchat-layout-") as bruto:
        tmp = Path(bruto)
        sala = tmp / "sala"
        sidecar = tmp / "groupchat.jsonl"
        perfil = tmp / "chrome"
        porta = porta_livre()
        depuracao = porta_livre()
        core_bin = RAIZ.parent / "ia-chat" / "bin"
        ambiente = dict(os.environ)
        ambiente.update({
            "IACHAT_HOME": str(sala),
            "IACHAT_GROUPCHAT": str(sidecar),
            "IACHAT_CORE": str(core_bin),
            "PYTHONPATH": str(core_bin),
            "PYTHONDONTWRITEBYTECODE": "1",
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
        })
        for nome in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                     "http_proxy", "https_proxy", "all_proxy"):
            ambiente.pop(nome, None)

        # Três falas reais, incluindo uma linha longa de terminal: é o caso que
        # faria `1fr` impor min-content e estourar a coluna.
        semente = """
import json
import iachat_core as c
c.garantir_estrutura()
cfg = c.config()
cfg['na_sala'] = ['claude','codex','kimi','qwen']
c.p_config().write_text(json.dumps(cfg, ensure_ascii=False), encoding='utf-8')
c.post(de='codex', para=['all'], texto='Validei a sessão independente e a barra exata.')
c.post(de='kimi', para=['all'], texto='Minha ocupação continua explicitamente estimada.')
c.post(de='qwen', para=['all'], texto='Compactei agora; a próxima resposta volta a medir.')
"""
        subprocess.run([sys.executable, "-c", semente], env=ambiente,
                       check=True, capture_output=True, text=True, timeout=10)
        caminho_longo = "/Users/prova/" + "segmento-muito-longo/" * 18 + "resultado.json"
        registros = [
            {"ia_id":"codex","session_id":"cx_7f2a","model_id":"gpt-5.6-sol",
             "message_n":1,"context":{"state":"exact","last_prompt_tokens":168000,
             "estimated_prompt_tokens":None,"context_window_tokens":250000,
             "sampled_at":"2026-08-18T15:42:08-03:00"},
             "liveness":{"last_signal_at":"2026-08-18T15:42:08-03:00","session_state":"running"},
             "actions":[{"description_pt":"Validar a guarda móvel de contexto",
             "type":"Shell","state":"completed","command":caminho_longo,
             "output":"PASS " + caminho_longo}]},
            {"ia_id":"kimi","session_id":"km_91c4","model_id":"kimi-k3",
             "message_n":2,"context":{"state":"estimated","last_prompt_tokens":None,
             "estimated_prompt_tokens":236000,"context_window_tokens":1000000,
             "sampled_at":"2026-08-18T15:43:08-03:00"},
             "liveness":{"last_signal_at":"2026-08-18T15:43:08-03:00","session_state":"running"}},
            {"ia_id":"qwen","session_id":"qw_228b","model_id":"qwen",
             "message_n":3,"context":{"state":"unknown","last_prompt_tokens":-1,
             "estimated_prompt_tokens":None,"context_window_tokens":1000000,
             "sampled_at":"2026-08-18T15:44:08-03:00"},
             "liveness":{"last_signal_at":"2026-08-18T15:44:08-03:00","session_state":"running"}},
        ]
        sidecar.write_text("".join(json.dumps(x, ensure_ascii=False)+"\n" for x in registros),
                           encoding="utf-8")

        servidor = subprocess.Popen(
            [sys.executable, str(SERVIR), "--porta", str(porta)],
            env=ambiente, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        chrome = None
        ws = None
        try:
            espera_http(porta, "/api/estado")
            chrome = subprocess.Popen([
                str(CHROME), "--headless=new", "--disable-gpu",
                "--no-first-run", "--no-default-browser-check",
                f"--remote-debugging-port={depuracao}",
                f"--remote-allow-origins=http://127.0.0.1:{depuracao}",
                f"--user-data-dir={perfil}", "about:blank",
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            espera_http(depuracao, "/json/version")
            with urllib.request.urlopen(
                f"http://127.0.0.1:{depuracao}/json/list", timeout=5
            ) as r:
                alvos = json.loads(r.read())
            pagina = next(x for x in alvos if x.get("type") == "page")
            ws = websocket.create_connection(
                pagina["webSocketDebuggerUrl"], timeout=12,
                origin=f"http://127.0.0.1:{depuracao}",
                http_proxy_host=None,
            )
            contador = [0]
            cdp_chama(ws, contador, "Runtime.enable")
            cdp_chama(ws, contador, "Page.enable")
            cdp_chama(ws, contador, "Page.navigate", {
                "url": f"http://127.0.0.1:{porta}/?janela=groupchat",
            })
            limite = time.time() + 10
            pronto = False
            while time.time() < limite:
                estado = cdp_chama(ws, contador, "Runtime.evaluate", {
                    "expression": "document.readyState === 'complete' && !!document.body",
                    "returnByValue": True,
                })
                if estado.get("result", {}).get("value") is True:
                    pronto = True
                    break
                time.sleep(0.1)
            if not pronto:
                raise RuntimeError("a página-pai não terminou de carregar")
            medidas = [mede_iframe(ws, contador, w, porta) for w in (360, 390, 430)]
        finally:
            if ws is not None:
                ws.close()
            if chrome is not None and chrome.poll() is None:
                chrome.terminate()
                try:
                    chrome.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    chrome.kill(); chrome.wait(timeout=5)
            if servidor.poll() is None:
                servidor.terminate()
                try:
                    servidor.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    servidor.kill(); servidor.wait(timeout=5)

    falhas = 0
    print("viewport  clientWidth  scrollWidth  falas  barras  ações  veredito")
    for m in medidas:
        passou = (m.get("clientWidth") == m.get("pedido") == m.get("scrollWidth")
                  and m.get("modo") == "groupchat"
                  and m.get("falas", 0) >= 3 and m.get("barras", 0) >= 3
                  and m.get("acoes", 0) >= 1)
        falhas += 0 if passou else 1
        print(f"{m.get('pedido'):>8}  {m.get('clientWidth'):>11}  "
              f"{m.get('scrollWidth'):>11}  {m.get('falas'):>5}  "
              f"{m.get('barras'):>6}  {m.get('acoes'):>5}  "
              f"{'PASS' if passou else 'FAIL'}")
        # A gaveta fechada e o campo de luz vivem geometricamente fora da tela,
        # por desenho, mas não ampliam o scroll. Só lista candidatos quando o
        # instrumento soberano (`scrollWidth`) confirmar estouro real.
        if m.get("scrollWidth") != m.get("clientWidth") and m.get("ofensores"):
            print("  ofensores:", json.dumps(m["ofensores"], ensure_ascii=False))
    return 1 if falhas else 0


def main() -> int:
    print("— state machine e fonte —")
    checa("há exatamente os três modos decididos",
          "new Set(['sala','enxame','groupchat'])" in JS)
    checa("o deep link entra pelo state machine",
          "pedidoJanela === 'groupchat' ? 'groupchat' : 'sala'" in JS)
    fonte_py = SERVIR.read_text(encoding="utf-8")
    checa("existe GET /api/groupchat",
          'u.path == "/api/groupchat"' in fonte_py)
    checa("o caminho da telemetria não vem da query",
          'q.get("groupchat")' not in fonte_py and 'q.get("fonte")' not in fonte_py)

    print("— cursor, lote e teto de bytes —")
    cursor = cursor_python()
    checa("a sala forjada executou o produtor real", "erro" not in cursor,
          str(cursor.get("erro", ""))[:180])
    checa("o teto contratual é independente e vale 48 KiB",
          cursor.get("teto_configurado") == TETO_GROUPCHAT_CONTRATO,
          repr(cursor.get("teto_configurado")))
    inicial = cursor.get("inicial") or {}
    backlog = cursor.get("backlog") or {}
    vazio = cursor.get("vazio") or {}
    checa("sala forjada grande não passa do teto",
          max(inicial.get("bytes", 10**9), backlog.get("bytes", 10**9))
          <= TETO_GROUPCHAT_CONTRATO,
          f"inicial={inicial.get('bytes')} backlog={backlog.get('bytes')} ")
    checa("o limite de itens também é aplicado",
          0 < inicial.get("itens", 0) <= 24 and
          0 < backlog.get("itens", 0) <= 24,
          f"inicial={inicial.get('itens')} backlog={backlog.get('itens')}")
    checa("primeiro lote traz o presente e declara o passado cortado",
          inicial.get("ultima_msg") == 120 and inicial.get("cursor") == 120 and
          inicial.get("corte", {}).get("ativo") is True and
          inicial.get("corte", {}).get("direcao") == "inicio" and
          inicial.get("corte", {}).get("omitidas", 0) > 0,
          repr(inicial))
    checa("tick no cursor não relê a sala",
          vazio.get("itens") == 0 and vazio.get("cursor") == 120 and
          cursor.get("chamadas", [])[:2] == [0, 120],
          repr({"vazio": vazio, "chamadas": cursor.get("chamadas")}))
    checa("backlog avança por lote sem saltar em silêncio",
          80 < backlog.get("cursor", 0) < 120 and
          backlog.get("corte", {}).get("pendentes", 0) > 0 and
          backlog.get("corte", {}).get("direcao") == "fim",
          repr(backlog))
    cliente_cursor = trecho("async function gcCarregar", "async function gcTick")
    checa("o cliente envia e atualiza o mesmo cursor desde",
          "url('/api/groupchat','desde='+desde)" in cliente_cursor and
          "GC.cursor = recebido" in cliente_cursor)
    checa("o corte é anunciado em região viva",
          'id="groupchat-corte" role="status" aria-live="polite"' in JS and
          "function gcAtualizaAvisoCorte" in JS)
    checa("o aviso inicial persiste após o tick seguinte",
          "GC.corteInicial" in trecho(
              "function gcAtualizaAvisoCorte", "async function gcCarregar") and
          "permanecem no histórico da sala" in JS)
    aviso = aviso_corte_js()
    checa("o aviso real executa em JavaScript", "erro" not in aviso,
          str(aviso.get("erro", ""))[:180])
    aviso_inicial = aviso.get("inicial") or {}
    aviso_seguinte = aviso.get("seguinte") or {}
    checa("o corte continua visível depois de resposta limpa",
          aviso_inicial.get("hidden") is False and
          aviso_seguinte.get("hidden") is False and
          aviso_inicial.get("texto") == aviso_seguinte.get("texto") and
          "34 mensagens anteriores" in aviso_seguinte.get("texto", ""),
          repr(aviso))

    print("— a barra mede a sessão da IA —")
    dados = normalizacao_js()
    checa("a função real executou em Node", "erro" not in dados,
          str(dados.get("erro", ""))[:180])
    exato = dados.get("exact") or {}
    checa("168k/250k resulta em 67% mesmo com sala enorme",
          exato.get("modo") == "exato" and exato.get("percentualReal") == 67
          and exato.get("tokens") == 168000,
          repr(exato))
    corpo_contexto = trecho("function gcContexto", "function gcDesconhecido")
    checa("a conta não lê bytes, peso nem mensagens da sala",
          all(x not in corpo_contexto for x in (".bytes", "room_bytes", "S.msgs", "GC.msgs")),
          "gcContexto deve depender só de registro.context")

    print("— -1 é medindo, nunca zero —")
    compactou = dados.get("compactou") or {}
    checa("-1 força desconhecido",
          compactou.get("modo") == "desconhecido", repr(compactou))
    checa("-1 escreve medindo após compactação",
          compactou.get("medindo") is True and
          "medindo" in compactou.get("leitura", "").lower(), repr(compactou))
    checa("-1 não produz percentual zero",
          "percentual" not in compactou and "0%" not in compactou.get("leitura", ""),
          repr(compactou))
    zero = dados.get("zero") or {}
    checa("zero não se passa por medida exata",
          zero.get("modo") == "desconhecido" and "percentual" not in zero,
          repr(zero))
    estimado = dados.get("estimado") or {}
    checa("estimativa permanece marcada com ≈",
          estimado.get("modo") == "estimado" and
          estimado.get("leitura", "").startswith("≈"), repr(estimado))

    print("— Python preserva o contrato —")
    with tempfile.TemporaryDirectory(prefix="ui-groupchat-") as pasta:
        carga = adaptador_python(Path(pasta))
    sessoes = {s.get("ia_id"): s for s in carga.get("sessions", [])}
    checa("o sidecar mantém session_id por IA",
          sessoes.get("codex", {}).get("session_id") == "cx_7f2a")
    checa("o peso da sala não substitui last_prompt_tokens",
          sessoes.get("codex", {}).get("context", {}).get("last_prompt_tokens") == 168000)
    checa("o servidor também força -1 para unknown",
          sessoes.get("qwen", {}).get("context", {}).get("state") == "unknown"
          and sessoes.get("qwen", {}).get("context", {}).get("reason")
          == "compacted_waiting_measurement")
    checa("IA sem medição aparece como unknown",
          sessoes.get("kimi", {}).get("context", {}).get("state") == "unknown")

    print("— identidade e estado não dividem cor —")
    identidade = trecho("/* Linha 1: identidade", "/* Linha 2: estado", CSS)
    estado = trecho("/* Linha 2: estado", ".gc-texto", CSS)
    checa("a linha de identidade usa --ia-t", "--ia-t" in identidade)
    estado_regras = re.sub(r"/\*[\s\S]*?\*/", "", estado)
    checa("a linha de estado não usa cor da IA",
          "--ia-t" not in estado_regras and "var(--codex" not in estado_regras,
          "a barra só pode usar info/atenção/erro/neutro")
    checa("a barra exata usa cor semântica info",
          ".gc-contexto-valor" in estado and "background:var(--info)" in estado)
    checa("alto risco usa atenção semântica",
          'data-risco="alto"' in JS and "background:var(--atencao)" in estado)

    print("— a ação fica dobrada —")
    checa("cada ação é um details", '<details class="gc-acao"' in JS)
    checa("a linha expõe descrição, tipo e estado",
          all(x in JS for x in ("gc-acao-titulo", "gc-acao-tipo", "gc-acao-estado")))
    checa("comando e saída ficam no corpo recolhido",
          "gc-acao-corpo" in JS and "<h4>comando</h4>" in JS and "<h4>saída</h4>" in JS)

    print("— teclado, foco e contraste —")
    i_sel = JS.find("modos.addEventListener('click'")
    seletor = JS[i_sel:i_sel + 520] if i_sel >= 0 else ""
    checa("o seletor de modos é botão nativo, não link",
          '<button type="button" class="janela-modo"' in JS)
    checa("os três botões ficam no Tab (sem tabindex -1)",
          "janela-modo" in JS and 'tabindex="-1"' not in trecho(
              "function instalaModosJanela", "const GC ="))
    checa("trocar de modo devolve o foco ao botão que clicou",
          "janelaModo(b.dataset.modoJanela)" in seletor and "b.focus()" in seletor)
    checa("voltaOFoco permanece a doutrina da gaveta",
          "function voltaOFoco" in JS)
    checa("a progressbar se nomeia com a IA, não só o percentual",
          'role="progressbar" aria-label="${esc(aria)}"' in JS and
          "registro.ia_id" in trecho("function gcBarraHTML", "function gcHora"))
    checa("a barra medindo para sob prefers-reduced-motion",
          ".gc-contexto[data-modo=\"desconhecido\"] .gc-contexto-trilho{animation:none}" in CSS)
    checa("Falhou no carvão clareia o texto, nunca a lei --erro",
          ':root[data-tema="carvao"] .gc-acao[data-estado="falhou"] .gc-acao-estado' in CSS
          and "color-mix(in srgb,var(--erro) 82%,var(--palha-100))" in CSS)

    print(f"\n{_ok} ✔ / {_falhou} ✗")
    return 1 if _falhou else 0


if __name__ == "__main__":
    raise SystemExit(layout_main() if "--layout" in sys.argv else main())
