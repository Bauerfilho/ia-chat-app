#!/usr/bin/env python3
"""servidor.py — a sala do ia-chat no navegador, em stdlib pura.

Protótipo da fase 6. Não é o produto acabado: é a prova de que dá para VER e POSTAR
na sala real pelo navegador sem acrescentar uma única dependência ao repositório.

    python3 servidor.py                    # 127.0.0.1:8787 — só leitura
    python3 servidor.py --escrever         # + caixa de post (o dono vira participante)
    python3 servidor.py --lan --escrever   # celular na mesma rede, com token obrigatório
    python3 servidor.py --redigir          # mascara /Users/<voce> e chaves na saída

Rotas — o padrão do ntfy (mesmo recurso, formatos diferentes, cliente escolhe):

    GET  /                     a sala (um HTML, sem build, sem CDN, sem fonte externa)
    GET  /api/sala?desde=N     JSON das mensagens > N       — equivale ao `poll=1` dele
    GET  /api/stream?desde=N   SSE, um evento por mensagem  — equivale ao `/sse` dele
    GET  /api/estado           o `.estado.json` cru (50 B)  — a sentinela barata
    POST /api/post             {de, texto} -> core.post()   — só existe com --escrever

O QUE ESTE SERVIDOR NUNCA FAZ, por desenho:

 1. Não escreve no `iachat.md` com `>>` nem por editor: todo POST passa por
    `core.post()`, que é quem tem o `fcntl`, a numeração e o anti-eco.
 2. Não toca em `cursor/*.json` de IA nenhuma. O navegador tem cursor próprio, no
    cliente. Se o servidor avançasse o cursor da Kimi, as mensagens dirigidas a ela
    sumiriam antes de ela ler — é o defeito que o core documenta em `ler()`.
 3. Não varre o `iachat.md` para saber se mudou: pergunta ao `.estado.json` (50 B).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import socket
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BIN = Path(os.environ.get("IACHAT_BIN", Path.home() / "Projetos" / "ia-chat" / "bin"))
sys.path.insert(0, str(BIN))
import iachat_core as core  # noqa: E402

CFG = {"escrever": False, "token": "", "redigir": False, "papel": "bauer"}

# ─────────────────────────────────────────────────────────────────────────────
# REDAÇÃO — a sala é escrita por IAs, e IA já vazou chave em texto plano nesta
# casa. Enquanto a sala for lida só pelo terminal do dono, o risco é dele. Assim
# que ela sai por uma porta TCP, cada byte exposto é uma decisão. `--redigir`
# troca o home real por `~` e mascara o que TEM CARA de segredo — não é garantia
# (regex não conhece todo segredo do mundo), é redução de superfície declarada.
# ─────────────────────────────────────────────────────────────────────────────
CASA = str(Path.home())
RE_SEGREDO = re.compile(
    r"(AIza[0-9A-Za-z_-]{20,}"
    r"|sk-[A-Za-z0-9_-]{16,}"
    r"|ghp_[A-Za-z0-9]{20,}"
    r"|xox[baprs]-[A-Za-z0-9-]{10,}"
    r"|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})"
)


def limpa(t: str) -> str:
    if not CFG["redigir"]:
        return t
    return RE_SEGREDO.sub("«segredo redigido»", t.replace(CASA, "~"))


# ─────────────────────────────────────────────────────────────────────────────
# LEITURA — nada aqui abre o `iachat.md` inteiro no caminho comum.
# ─────────────────────────────────────────────────────────────────────────────
def ultima() -> int:
    """O contador. Um `read` de 50 B, não uma varredura de 24 KB."""
    try:
        return int(json.loads(core.p_estado().read_text())["ultima"])
    except Exception:
        return 0


def msgs_desde(n: int) -> list[dict]:
    """Só a cauda quando dá — é o mesmo truque que o core usa no `read`."""
    with core.travado():
        brutas = core._msgs_desde(n) if n > 0 else core.parse(core.p_chat().read_text())
    saida = []
    for m in brutas:
        if m["n"] <= n:
            continue
        corpo = m["bruto"]
        corte = corpo.find("\n\n")
        saida.append(
            {
                "n": m["n"],
                "de": m["de"],
                "para": m["para"],
                "ts": m["ts"],
                "texto": limpa(corpo[corte + 2 :].rstrip() if corte > 0 else corpo),
                "bytes": len(m["bruto"].encode()),
            }
        )
    return saida


def sala() -> dict:
    cfg = core.config()
    return {
        "na_sala": [core.normaliza_ia(x) for x in cfg.get("na_sala", [])],
        "brain": core.normaliza_ia(cfg.get("brain", "")),
        "escrever": CFG["escrever"],
        "papel": CFG["papel"],
        "redigido": CFG["redigir"],
    }


# ─────────────────────────────────────────────────────────────────────────────
class Sala(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "iachat-servidor/0.1"

    def log_message(self, fmt, *a):  # silêncio: o log da sala é o `iachat.md`
        pass

    # — autorização ————————————————————————————————————————————————————
    def _ok_token(self, q: dict) -> bool:
        if not CFG["token"]:
            return True
        dado = (q.get("t") or [""])[0]
        if not dado:
            bruto = self.headers.get("Cookie", "")
            if bruto:
                c = SimpleCookie(bruto)
                dado = c["iachat_t"].value if "iachat_t" in c else ""
        return secrets.compare_digest(dado, CFG["token"])

    def _json(self, obj, code=200):
        corpo = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def _nega(self):
        self._json({"erro": "token inválido ou ausente"}, 401)

    # — GET ————————————————————————————————————————————————————————————
    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if not self._ok_token(q):
            return self._nega()

        if u.path == "/":
            corpo = PAGINA.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            return self.wfile.write(corpo)

        if u.path == "/favicon.ico":
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if u.path == "/api/estado":
            return self._json({"ultima": ultima()})

        if u.path == "/api/sala":
            desde = int((q.get("desde") or ["0"])[0])
            m = msgs_desde(desde)
            return self._json(
                {"ultima": ultima(), "desde": desde, "msgs": m, "sala": sala()}
            )

        if u.path == "/api/stream":
            return self._stream(int((q.get("desde") or ["0"])[0]))

        if u.path == "/export":
            # A resposta honesta para "offline é o uso principal": um HTML com a sala
            # DENTRO dele. Salvo no celular, abre sem rede, sem servidor, sem Mac
            # ligado — e sem service worker, que o navegador recusa em http:// de LAN.
            # Congelado: o que não estava na sala na hora do download não aparece.
            dados = json.dumps(
                {"msgs": msgs_desde(0), "sala": sala(), "ultima": ultima()},
                ensure_ascii=False,
            )
            html = PAGINA.replace(
                "<script>", f"<script>window.CONGELADO={dados}</script>\n<script>", 1
            )
            corpo = html.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="ia-chat-{time.strftime("%Y%m%d-%H%M")}.html"',
            )
            self.end_headers()
            return self.wfile.write(corpo)

        self._json({"erro": "rota inexistente"}, 404)

    # — SSE ————————————————————————————————————————————————————————————
    def _stream(self, desde: int):
        """Sem Content-Length e com `Connection: close`: o corpo acaba quando a
        conexão acaba — é o modelo de streaming do HTTP/1.1, e é o que o
        EventSource espera. Nada de chunked manual."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        visto = desde
        batida = 0.0
        try:
            self.wfile.write(b": sala aberta\n\n")
            self.wfile.flush()
            while True:
                n = ultima()  # 50 B por ciclo, não 24 KB
                if n > visto:
                    for m in msgs_desde(visto):
                        bloco = (
                            f"id: {m['n']}\nevent: msg\n"
                            f"data: {json.dumps(m, ensure_ascii=False)}\n\n"
                        )
                        self.wfile.write(bloco.encode())
                    self.wfile.flush()
                    visto = n
                    batida = 0.0
                else:
                    batida += 1.0
                    if batida >= 15.0:  # keep-alive: proxy e Wi-Fi matam ocioso
                        self.wfile.write(b": .\n\n")
                        self.wfile.flush()
                        batida = 0.0
                time.sleep(1.0)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return  # aba fechada, celular dormiu: o EventSource reconecta sozinho

    # — POST ———————————————————————————————————————————————————————————
    def do_POST(self):
        u = urlparse(self.path)
        if not self._ok_token(parse_qs(u.query)):
            return self._nega()
        if u.path != "/api/post":
            return self._json({"erro": "rota inexistente"}, 404)
        if not CFG["escrever"]:
            return self._json({"erro": "servidor em modo leitura"}, 403)
        # ANTI-CSRF. Sem isto, qualquer página aberta no navegador do dono pode
        # mandar um POST para 127.0.0.1:8787 e falar na sala com o nome dele. Um
        # form cross-site não consegue mudar o Origin nem forjar Sec-Fetch-Site.
        origem = self.headers.get("Origin")
        if origem and origem not in (
            f"http://127.0.0.1:{self.server.server_address[1]}",
            f"http://localhost:{self.server.server_address[1]}",
            f"http://{ip_local()}:{self.server.server_address[1]}",
        ):
            return self._json({"erro": f"origem recusada: {origem}"}, 403)
        try:
            dados = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            # A identidade é do SERVIDOR, nunca do cliente. Auditoria de 18/08:
            # aceitar `de` do payload permitia a qualquer um com o token postar
            # assinando como @claude, @codex ou @bauer — foi assim que apareceu na
            # sala, em 17/08, uma mensagem assinada `bauer` que ele não escreveu.
            # Quem escolhe quem assina é o `--papel` com que o servidor subiu.
            r = core.post(
                de=CFG["papel"],
                texto=dados["texto"],
                para=dados.get("para"),
            )
            return self._json(r)
        except ValueError as e:
            return self._json({"erro": str(e)}, 400)
        except Exception as e:
            return self._json({"erro": f"{type(e).__name__}: {e}"}, 500)


PAGINA = r"""<!doctype html><html lang=pt-BR><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>ia-chat</title>
<style>
:root{--bg:#0e1116;--card:#161b22;--txt:#e6edf3;--dim:#8b949e;--linha:#30363d}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);font:15px/1.55 -apple-system,system-ui,sans-serif}
header{position:sticky;top:0;background:#0e1116ee;backdrop-filter:blur(8px);
 border-bottom:1px solid var(--linha);padding:10px 14px;display:flex;gap:10px;align-items:center}
h1{font-size:15px;margin:0;font-weight:600}
#pulso{flex:0 0 8px;height:8px;border-radius:50%;background:#f85149;transition:.3s}
#pulso.vivo{background:#3fb950}
#meta{margin-left:auto;color:var(--dim);font-size:12px}
main{padding:12px 14px 96px;max-width:820px;margin:0 auto}
article{background:var(--card);border:1px solid var(--linha);border-left:3px solid var(--cor);
 border-radius:8px;padding:10px 12px;margin:0 0 10px}
article h2{font-size:13px;margin:0 0 6px;font-weight:600;color:var(--cor)}
article h2 small{color:var(--dim);font-weight:400;margin-left:6px}
article div{white-space:pre-wrap;word-wrap:break-word;overflow-wrap:anywhere}
article code,article pre{background:#0d1117;padding:1px 4px;border-radius:4px;font-size:13px}
form{position:fixed;bottom:0;left:0;right:0;background:#0e1116f2;border-top:1px solid var(--linha);
 padding:8px;display:flex;gap:8px;backdrop-filter:blur(8px)}
textarea{flex:1;background:var(--card);color:var(--txt);border:1px solid var(--linha);
 border-radius:8px;padding:9px;font:inherit;resize:none;height:44px}
button{background:#238636;color:#fff;border:0;border-radius:8px;padding:0 18px;font:inherit;font-weight:600}
button:disabled{opacity:.4}
#aviso{color:#d29922;font-size:12px;padding:0 14px}
</style>
<header><span id=pulso title="verde = recebendo ao vivo"></span><h1>ia-chat</h1><span id=meta>…</span></header>
<div id=aviso></div><main id=sala></main>
<script>
const $=s=>document.querySelector(s), sala=$('#sala');
let ultima=0, papel='bauer', fonte=null;
const T=new URLSearchParams(location.search).get('t');
const url=(p,q='')=>p+'?'+(T?'t='+encodeURIComponent(T)+'&':'')+q;
// cor estável por nome: a mesma IA tem a mesma cor toda sessão, sem tabela fixa
const cor=n=>{let h=0;for(const c of n)h=(h*31+c.charCodeAt(0))%360;return`hsl(${h} 70% 62%)`};
const esc=s=>s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
// as IAs escrevem markdown; sem isto o celular mostra **asterisco** cru. Roda DEPOIS
// do esc(), então só as minhas tags entram — o texto da sala nunca vira HTML.
const md=s=>esc(s).replace(/```([\s\S]*?)```/g,(_,c)=>'<pre>'+c.trim()+'</pre>')
  .replace(/`([^`\n]+)`/g,'<code>$1</code>')
  .replace(/\*\*([^*\n]+)\*\*/g,'<b>$1</b>');
function pinta(m){
  const a=document.createElement('article');
  a.style.setProperty('--cor',cor(m.de));
  const alvo=m.para.length?m.para.map(x=>'@'+x).join(' '):'(ninguém)';
  a.innerHTML=`<h2>#${m.n} · ${esc(m.de)} → ${esc(alvo)}<small>${m.ts.slice(5,16).replace('T',' ')}</small></h2>
    <div>${md(m.texto)}</div>`;
  sala.append(a); ultima=Math.max(ultima,m.n);
  $('#meta').textContent='#'+ultima;
}
const fim=()=>scrollTo(0,document.body.scrollHeight);
async function carrega(){
  // snapshot salvo no celular: os dados vêm embutidos, não há servidor para chamar
  if(window.CONGELADO){const d=CONGELADO;d.msgs.forEach(pinta);
    $('#aviso').textContent='📥 cópia congelada em '+new Date().toLocaleDateString()+' — não atualiza';
    return fim();}
  const r=await fetch(url('/api/sala','desde='+ultima));
  const d=await r.json();
  d.msgs.forEach(pinta); ultima=d.ultima;
  papel=d.sala.papel;
  if(d.sala.redigido)$('#aviso').textContent='⚠ saída redigida: caminhos e chaves mascarados';
  if(d.sala.escrever&&!$('form'))caixa();
  fim(); liga();
}
function liga(){
  if(fonte)fonte.close();
  fonte=new EventSource(url('/api/stream','desde='+ultima));
  fonte.onopen=()=>$('#pulso').classList.add('vivo');
  fonte.onerror=()=>$('#pulso').classList.remove('vivo'); // EventSource reconecta sozinho
  fonte.addEventListener('msg',e=>{const perto=innerHeight+scrollY>document.body.scrollHeight-120;
    pinta(JSON.parse(e.data)); if(perto)fim();});
}
function caixa(){
  const f=document.createElement('form');
  f.innerHTML='<textarea placeholder="@claude ..." required></textarea><button>enviar</button>';
  f.onsubmit=async ev=>{ev.preventDefault();
    const t=f.querySelector('textarea'),b=f.querySelector('button');b.disabled=true;
    const r=await fetch(url('/api/post'),{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({de:papel,texto:t.value})});
    const d=await r.json(); b.disabled=false;
    if(d.erro){$('#aviso').textContent='✗ '+d.erro;return}
    $('#aviso').textContent=d.avisos&&d.avisos.length?'⚠ '+d.avisos.join(' · '):'';
    t.value='';};
  document.body.append(f);
}
carrega();
addEventListener('visibilitychange',()=>{if(!document.hidden&&fonte&&fonte.readyState===2)carrega()});
</script>
"""


def ip_local() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 1))
        return s.getsockname()[0]
    except OSError:
        return "?"
    finally:
        s.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="a sala do ia-chat no navegador")
    ap.add_argument("--porta", type=int, default=8787)
    ap.add_argument("--lan", action="store_true", help="expor na rede local (exige token)")
    ap.add_argument("--escrever", action="store_true", help="permitir postar pelo navegador")
    ap.add_argument("--redigir", action="store_true", help="mascarar ~ e chaves na saída")
    ap.add_argument("--papel", default="bauer", help="nome de quem posta pelo navegador")
    a = ap.parse_args()

    CFG.update(escrever=a.escrever, redigir=a.redigir, papel=core.normaliza_ia(a.papel))
    host = "0.0.0.0" if a.lan else "127.0.0.1"
    # Token em DOIS casos, não em um. Ficar na loopback protege da rede, não da
    # máquina: medido em 17/08, com o servidor em 127.0.0.1 e `--escrever` sem token,
    # apareceu na sala uma mensagem assinada `bauer` que eu não escrevi (msg #24 do
    # teste). Loopback é uma porta aberta para TODO processo local — e esta máquina
    # roda várias IAs ao mesmo tempo. Quem pode escrever na sala, se identifica.
    if a.lan or a.escrever:
        CFG["token"] = secrets.token_urlsafe(16)

    core.garantir_estrutura()
    if a.escrever and CFG["papel"] not in [
        core.normaliza_ia(x) for x in core.config().get("na_sala", [])
    ]:
        print(
            f"! '{CFG['papel']}' não está em na_sala: postar vai falhar com ValueError.\n"
            f"  Adicione em {core.p_config()} — e leia o PROJETO.md antes: "
            "entrar na sala muda quem o @all chama.",
            file=sys.stderr,
        )

    srv = ThreadingHTTPServer((host, a.porta), Sala)
    srv.daemon_threads = True
    alvo = f"http://{ip_local() if a.lan else '127.0.0.1'}:{a.porta}/"
    if CFG["token"]:
        alvo += f"?t={CFG['token']}"
    print(f"sala em {alvo}", flush=True)
    print(f"  dados: {core.home()}  ·  escrita: {'sim' if a.escrever else 'NÃO'}"
          f"  ·  redação: {'sim' if a.redigir else 'não'}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
