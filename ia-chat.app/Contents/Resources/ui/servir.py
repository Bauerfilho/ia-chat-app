#!/usr/bin/env python3
"""Servidor da INTERFACE — serve `ui/` e as rotas que a interface consome.

O protocolo é o mesmo do esboço do `idea-servidor` (todo POST passa por
`core.post()`; a leitura usa o contador em vez de varrer a sala). A única
diferença é a rota `/`: em vez de uma página embutida no Python, ela serve
os arquivos desta pasta — que é o que permite a interface ser trabalhada
como interface.

    python3 servir.py                       # 127.0.0.1:8801, somente leitura
    python3 servir.py --escrever            # libera o POST
    IACHAT_HOME=/tmp/sala python3 servir.py --escrever   # sala de teste

Quando o servidor oficial entrar no repo, ele só precisa apontar `/` para
esta pasta — nenhuma lógica de protocolo vive aqui.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import base64
import secrets
import select
import socket
import sys
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path.home() / "Projetos" / "ia-chat" / "bin"))
import iachat_core as core  # noqa: E402

UI = Path(__file__).resolve().parent
CFG = {"escrever": False, "papel": "bauer", "token": ""}

# O favicon viaja DENTRO deste arquivo, em base64, e não como um arquivo ao lado.
# Motivo medido, não estético: `montar.sh` copia para o bundle uma lista fixa de
# quatro nomes (index.html, estilo.css, sala.js, servir.py). Um `favicon.ico`
# solto em `ui/` existiria no repo e faltaria no `.app` — o app instalado ficaria
# sem ícone na aba, que é exatamente o defeito que se quer fechar. São 1786 B.
# Fonte: marca/favicon.ico (16 e 32 px, ambos renderizados do vetor). Para
# regerar depois de mexer na marca:  python3 marca/gerar_icone.py favicon
FAVICON = base64.b64decode(
    "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"
    "gXNOTKiVGgAAAABJRU5ErkJggg=="
)


# ─── TETO DE CONEXÕES AO VIVO ────────────────────────────────────────────────
# Cada `/api/stream` é um laço infinito numa thread própria. Sem teto, quantas
# threads existem é decisão de quem se conecta — e com `--lan` quem se conecta não é
# necessariamente o dono.
#
# 16, e o critério é demanda real × folga: o dono em até três aparelhos (Mac, celular,
# tablet), uma janela segura UM stream, e a reconexão do EventSource pode sobrepor o
# stream velho ao novo por instantes — pico honesto perto de 6. 16 dá ~2,5× de folga e
# ainda assim é um número, não o infinito. Teto que nunca dispara é enfeite; teto
# apertado recusa o dono na própria casa. Mesmo número do servidor do bundle.
TETO_SSE = 16
_SSE = {"vivas": 0}
_SSE_TRAVA = threading.Lock()


def ultima() -> int:
    try:
        return int(json.loads(core.p_estado().read_text())["ultima"])
    except Exception:
        return 0


def msgs_desde(n: int) -> list[dict]:
    with core.travado():
        brutas = core._msgs_desde(n) if n > 0 else core.parse(core.p_chat().read_text())
    saida = []
    for m in brutas:
        if m["n"] <= n:
            continue
        corpo = m["bruto"]
        corte = corpo.find("\n\n")
        saida.append({
            "n": m["n"], "de": m["de"], "para": m["para"], "ts": m["ts"],
            "texto": corpo[corte + 2:].rstrip() if corte > 0 else corpo,
            "bytes": len(m["bruto"].encode()),
        })
    return saida


def sala() -> dict:
    cfg = core.config()
    return {
        "na_sala": [core.normaliza_ia(x) for x in cfg.get("na_sala", [])],
        "brain": core.normaliza_ia(cfg.get("brain", "")),
        "escrever": CFG["escrever"], "papel": CFG["papel"],
    }


class Sala(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "iachat-ui/0.1"

    def log_message(self, fmt, *a):
        pass

    def _json(self, obj, code=200):
        corpo = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    # — autorização ————————————————————————————————————————————————————
    # Loopback protege da REDE, não da MÁQUINA: em 17/08, com o servidor em
    # 127.0.0.1 e escrita liberada sem token, apareceu na sala uma mensagem
    # assinada `bauer` que ninguém aqui escreveu. Esta máquina roda várias IAs
    # ao mesmo tempo, e todas alcançam a loopback. Quem escreve, se identifica.
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

    def _nega(self):
        self._json({"erro": "token inválido ou ausente"}, 401)

    def _lotado(self):
        """503 + Retry-After: a sala está cheia de ouvintes, não quebrada.

        503 e não 429: não é limite por cliente, é capacidade do servidor. O
        `Retry-After` é o que separa "volte já" de "desista" — e é o que um cliente
        automático precisa para não martelar a porta.
        """
        corpo = json.dumps(
            {"erro": f"limite de {TETO_SSE} conexões ao vivo atingido"},
            ensure_ascii=False,
        ).encode()
        self.send_response(503)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Retry-After", "5")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def _peer_sumiu(self) -> bool:
        """O cliente foi embora? Descobre sem escrever nada.

        O laço só percebia a aba fechada na escrita seguinte — até 15 s depois, no
        keep-alive. Sem teto isso era só uma thread ociosa; COM teto é uma VAGA presa,
        e o dono que fecha e reabre a janela algumas vezes tomaria 503 na própria casa.
        `select` sem espera + `MSG_PEEK` de zero byte é o fim de arquivo do TCP: não
        consome nada de quem continua vivo.
        """
        try:
            pronto, _, _ = select.select([self.connection], [], [], 0)
            return bool(pronto) and self.connection.recv(1, socket.MSG_PEEK) == b""
        except OSError:
            return True

    def _estatico(self, nome: str, semear: bool = False):
        alvo = (UI / nome).resolve()
        if not alvo.is_file() or UI not in alvo.parents:
            return self._json({"erro": "não encontrado"}, 404)
        corpo = alvo.read_bytes()
        tipo = mimetypes.guess_type(alvo.name)[0] or "application/octet-stream"
        self.send_response(200)
        # o token entra uma vez pela URL e vira cookie — o JS não o carrega em
        # toda chamada de API, e ele não fica no histórico de cada requisição.
        if semear and CFG["token"]:
            self.send_header(
                "Set-Cookie",
                # `HttpOnly` porque o JS desta interface NUNCA lê o cookie — quem o
                # devolve é o navegador, sozinho. Sem ele, um XSS futuro leria o token,
                # que dá escrita na sala com o nome do dono. A defesa custa zero e
                # existe para o dia em que alguém errar uma linha. (teste_cookie.py)
                f"iachat_t={CFG['token']}; Path=/; SameSite=Strict; HttpOnly; "
                "Max-Age=86400",
            )
        self.send_header("Content-Type", f"{tipo}; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)

        if not self._ok_token(q):
            return self._nega()

        if u.path == "/":
            return self._estatico("index.html", semear=True)
        if u.path == "/favicon.ico":
            # O navegador pede esta rota sozinho, sem ninguém mandar. Responder
            # 204 fazia a aba e a janela em modo app caírem no ícone genérico.
            self.send_response(200)
            self.send_header("Content-Type", "image/x-icon")
            self.send_header("Content-Length", str(len(FAVICON)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(FAVICON)
            return
        if u.path == "/api/estado":
            return self._json({"ultima": ultima()})
        if u.path == "/api/sala":
            desde = int((q.get("desde") or ["0"])[0])
            return self._json({"ultima": ultima(), "desde": desde,
                               "msgs": msgs_desde(desde), "sala": sala()})
        if u.path == "/api/stream":
            return self._stream(int((q.get("desde") or ["0"])[0]))
        if u.path.count("/") == 1 and u.path[1:]:
            return self._estatico(u.path[1:])
        self._json({"erro": "rota inexistente"}, 404)

    def _stream(self, desde: int):
        with _SSE_TRAVA:
            if _SSE["vivas"] >= TETO_SSE:
                return self._lotado()
            _SSE["vivas"] += 1
        try:
            self._transmite(desde)
        finally:
            with _SSE_TRAVA:
                _SSE["vivas"] -= 1

    def _transmite(self, desde: int):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        visto, batida = desde, 0.0
        try:
            self.wfile.write(b": sala aberta\n\n")
            self.wfile.flush()
            while True:
                n = ultima()
                if n > visto:
                    for m in msgs_desde(visto):
                        self.wfile.write((
                            f"id: {m['n']}\nevent: msg\n"
                            f"data: {json.dumps(m, ensure_ascii=False)}\n\n").encode())
                    self.wfile.flush()
                    visto, batida = n, 0.0
                else:
                    batida += 1.0
                    if batida >= 15.0:
                        self.wfile.write(b": .\n\n")
                        self.wfile.flush()
                        batida = 0.0
                if self._peer_sumiu():
                    return          # devolve a vaga em ≤1 s, não em ≤15 s
                time.sleep(1.0)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def do_POST(self):
        u = urlparse(self.path)
        if not self._ok_token(parse_qs(u.query)):
            return self._nega()
        if u.path != "/api/post":
            return self._json({"erro": "rota inexistente"}, 404)
        if not CFG["escrever"]:
            return self._json({"erro": "servidor em modo leitura"}, 403)
        # ANTI-CSRF. Sem isto, qualquer página aberta no navegador do dono pode
        # mandar um POST para este servidor e falar na sala com o nome dele. Um
        # form cross-site não consegue mudar o Origin nem forjar Sec-Fetch-Site.
        porta = self.server.server_address[1]
        origem = self.headers.get("Origin")
        if origem and origem not in (
            f"http://127.0.0.1:{porta}",
            f"http://localhost:{porta}",
            f"http://{_ip_local()}:{porta}",
        ):
            return self._json({"erro": f"origem recusada: {origem}"}, 403)
        # Corpo sem teto esgota a memória do processo: 256 KB é folgado para uma
        # mensagem de sala e barato de recusar.
        n = int(self.headers.get("Content-Length") or 0)
        if n > 262144:
            return self._json({"erro": "corpo grande demais"}, 413)
        try:
            dados = json.loads(self.rfile.read(n) or b"{}")
            # A identidade é do SERVIDOR, nunca do cliente. Auditoria de 18/08:
            # aceitar `de` do payload permitia a qualquer um com o token postar
            # assinando como @claude, @codex ou @bauer — foi assim que apareceu na
            # sala, em 17/08, uma mensagem assinada `bauer` que ele não escreveu.
            # Quem escolhe quem assina é o `--papel` com que o servidor subiu.
            return self._json(core.post(
                de=CFG["papel"],
                texto=(dados.get("texto") or "").strip(),
                para=dados.get("para"),
            ))
        except ValueError as e:
            return self._json({"erro": str(e)}, 400)
        except Exception as e:
            return self._json({"erro": f"{type(e).__name__}: {e}"}, 500)


def _ips_lan() -> list[str]:
    """Os IPs que o CELULAR alcança — que não são necessariamente o da rota default.

    Ele usa VPN (Surfshark/WireGuard). Com o túnel ativo, a rota default sai por
    `utun*` e o IP de lá é inútil para um telefone na mesma casa: o celular fala
    com o Mac pela LAN, não pela VPN. Por isso a ordem é interface FÍSICA primeiro
    (en0 Wi-Fi, en1/en2 Ethernet ou adaptador), e a rota default só como último
    recurso. Devolve a lista inteira porque quem sabe qual rede o telefone está
    usando é ele, não eu.
    """
    import socket
    import subprocess

    ips: list[str] = []
    for iface in ("en0", "en1", "en2"):
        try:
            r = subprocess.run(["ipconfig", "getifaddr", iface],
                               capture_output=True, text=True, timeout=2)
            ip = r.stdout.strip()
            if ip and ip not in ips:
                ips.append(ip)
        except (OSError, subprocess.SubprocessError):
            pass

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        rota = s.getsockname()[0]
        if rota not in ips:
            ips.append(rota)          # último da fila: pode ser o IP da VPN
    except OSError:
        pass
    finally:
        s.close()

    return ips or ["127.0.0.1"]


def _ip_local() -> str:
    return _ips_lan()[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--porta", type=int, default=8801)
    ap.add_argument("--escrever", action="store_true")
    ap.add_argument("--papel", default="bauer")
    ap.add_argument("--lan", action="store_true",
                    help="expor na rede local — celular no mesmo Wi-Fi (exige token)")
    a = ap.parse_args()
    CFG["escrever"], CFG["papel"] = a.escrever, a.papel

    # token nos DOIS casos, não em um: exposto na rede OU com escrita liberada.
    if a.lan or a.escrever:
        CFG["token"] = secrets.token_urlsafe(16)

    host = "0.0.0.0" if a.lan else "127.0.0.1"
    sufixo = f"?t={CFG['token']}" if CFG["token"] else ""

    # `flush=True` NÃO é zelo — é o que faz o app abrir.
    #
    # O lançador do `.app` sobe este servidor com stdout redirecionado para um log e
    # descobre o token LENDO esse log. Com stdout num arquivo, o Python usa buffer de
    # bloco (medido: 131.072 B); estas ~150 bytes nunca o enchem, e como o servidor não
    # imprime mais nada depois, o log fica **vazio para sempre**. O lançador não acha o
    # token, bate em `/api/estado` sem ele, toma 401, conclui "não respondeu" e mata o
    # app aos 20 s — com um alerta enganoso, porque o servidor estava vivo e respondendo.
    #
    # Achado por auditoria externa em 18/08, e eu tinha visto o sintoma horas antes: subi
    # o servidor, o log saiu vazio, contornei com `python3 -u` e segui. Contornar sem
    # diagnosticar deixou o defeito de pé exatamente onde ele quebrava o produto.
    if a.lan:
        # Uma URL por interface: com VPN ligada, só uma delas serve para o celular.
        for i, ip in enumerate(_ips_lan()):
            marca = "→" if i == 0 else " ·"
            print(f"{marca} http://{ip}:{a.porta}/{sufixo}", flush=True)
    else:
        print(f"→ http://127.0.0.1:{a.porta}/{sufixo}", flush=True)
    print(f"  sala: {core.home()}   "
          f"{'escrita liberada' if a.escrever else 'somente leitura'}"
          f"{'   · na rede local' if a.lan else ''}", flush=True)
    ThreadingHTTPServer((host, a.porta), Sala).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
