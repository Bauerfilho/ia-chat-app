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
import secrets
import sys
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path.home() / "Projetos" / "ia-chat" / "bin"))
import iachat_core as core  # noqa: E402

UI = Path(__file__).resolve().parent
CFG = {"escrever": False, "papel": "bauer", "token": ""}


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
                f"iachat_t={CFG['token']}; Path=/; SameSite=Strict; Max-Age=86400",
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
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
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
