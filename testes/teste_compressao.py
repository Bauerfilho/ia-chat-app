#!/usr/bin/env python3
"""A interface viaja comprimida — menos o que quebraria se comprimisse.

Ele lê a sala no celular, por um túnel, em rede móvel. Medido em 18/08: a página
inteira pesava 276 KB e o servidor não comprimia nada; com gzip são 102 KB. É a
diferença entre abrir e esperar.

O gate existe menos pela economia e mais pela **exceção**: o SSE não pode ser
comprimido. O gzip acumula bytes num buffer e só entrega quando o bloco fecha —
num stream, a mensagem chegaria quando o buffer enchesse, não quando ela fosse
escrita. A sala ao vivo pararia de ser ao vivo, e o defeito seria invisível até
alguém reclamar de atraso. Quem um dia "melhorar" isto comprimindo tudo cai aqui.
"""
from __future__ import annotations

import gzip
import http.client
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SERVIR = RAIZ / "ui" / "servir.py"
PORTA = 59_860

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


def pede(caminho: str, gzip_ok: bool, token: str = "",
         so_cabecalho: bool = False) -> tuple[int, dict, bytes]:
    """Devolve (status, cabeçalhos, corpo CRU — sem descomprimir).

    `so_cabecalho=True` para o SSE: um stream não termina, e `read()` nele
    bloqueia para sempre. Aprendido travando este próprio teste.
    """
    c = http.client.HTTPConnection("127.0.0.1", PORTA, timeout=10)
    cab = {"Accept-Encoding": "gzip"} if gzip_ok else {"Accept-Encoding": "identity"}
    alvo = caminho + (("?t=" + token) if token and "?" not in caminho else "")
    c.request("GET", alvo, headers=cab)
    r = c.getresponse()
    heads = {k.lower(): v for k, v in r.getheaders()}
    corpo = b"" if so_cabecalho else r.read()
    c.close()
    return r.status, heads, corpo


def main() -> int:
    lar = Path(tempfile.mkdtemp(prefix="m-compressao-"))
    (lar / "config.json").write_text(json.dumps({
        "na_sala": ["claude", "bauer"], "brain": "claude",
        "notificar_operador": False, "teto_bytes": 204800,
    }), encoding="utf-8")
    # uma sala com corpo, senão o JSON fica menor que o piso e não comprime
    sala = lar / "iachat.md"
    sala.write_text("".join(
        f"<!-- iachat msg={i} de=claude para=bauer ts=2026-08-18T10:00:00-03:00 -->\n"
        f"### #{i} claude\n\nmensagem de teste com texto repetido o bastante para "
        f"comprimir bem, porque conversa é texto e texto comprime.\n\n"
        for i in range(1, 60)), encoding="utf-8")

    env = {**os.environ, "IACHAT_HOME": str(lar)}
    proc = subprocess.Popen(
        [sys.executable, "-u", str(SERVIR), "--porta", str(PORTA), "--papel", "bauer"],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    # O stdout é lido numa thread daemon: `readline()` BLOQUEIA, e um `while
    # time.time() < fim` em volta dele só confere o relógio ENTRE linhas — se o
    # servidor para de escrever, o teste fica preso para sempre. Travei este
    # próprio arquivo assim.
    achado: dict[str, str] = {}

    def colhe_token() -> None:
        for linha in proc.stdout:
            m = re.search(r"[?&]t=([A-Za-z0-9_.:-]+)", linha)
            if m:
                achado["t"] = m.group(1)
                return

    threading.Thread(target=colhe_token, daemon=True).start()
    try:
        fim = time.time() + 15
        while time.time() < fim and not achado and proc.poll() is None:
            time.sleep(0.2)
        token = achado.get("t", "")
        with socket.socket() as s:
            s.settimeout(5)
            s.connect(("127.0.0.1", PORTA))

        print("— o que DEVE comprimir —")
        for caminho, nome in (("/sala.js", "sala.js"), ("/estilo.css", "estilo.css"),
                              ("/", "index.html")):
            st, h, corpo = pede(caminho, True)
            _, _, cru = pede(caminho, False)
            enc = h.get("content-encoding", "")
            checa(f"{nome} viaja em gzip", st == 200 and enc == "gzip",
                  f"status={st} encoding={enc!r}")
            checa(f"{nome} encolhe de verdade", len(corpo) < len(cru) * 0.9,
                  f"{len(cru)} → {len(corpo)} B")
            checa(f"{nome} descomprime no que o cliente pediu sem gzip",
                  gzip.decompress(corpo) == cru if enc == "gzip" else False,
                  "o corpo comprimido tem que devolver o MESMO byte do original")
            checa(f"{nome} declara Content-Length do corpo COMPRIMIDO",
                  h.get("content-length") == str(len(corpo)),
                  "se o tamanho não bate, o navegador espera bytes que não vêm")
            checa(f"{nome} avisa que varia por Accept-Encoding",
                  "accept-encoding" in h.get("vary", "").lower(),
                  "sem Vary, um cache serve o corpo comprimido a quem não aceita")

        print("— o que NÃO pode comprimir, e é o ponto deste arquivo —")
        # O SSE está protegido em DOIS níveis, e os dois são medidos.
        #
        # 1) ARQUITETURA: o stream tem caminho próprio de escrita e nem passa
        #    pelo compressor. É por isso que a checagem HTTP abaixo continua
        #    verde mesmo se alguém apagar a guarda — descobri removendo-a e
        #    vendo o gate passar. Um gate que não vê vermelho não prova nada.
        # 2) GUARDA EXPLÍCITA: a função recusa `text/event-stream` por tipo. É a
        #    defesa para o dia em que alguém rotear o stream por aqui — e ESTA
        #    se testa chamando a função, não pela borda HTTP.
        sys.path.insert(0, str(RAIZ / "ui"))
        os.environ.setdefault("IACHAT_HOME", str(lar))
        import servir  # noqa: E402  (só depois do IACHAT_HOME, que ele lê ao importar)
        grande = b"dado que passaria do piso, repetido muitas vezes. " * 60
        corpo_sse, enc_sse = servir._talvez_comprime(grande, "text/event-stream", "gzip")
        checa("a função recusa `text/event-stream` por tipo",
              enc_sse == "" and corpo_sse == grande,
              "sem esta guarda, rotear o stream pelo compressor um dia trava a "
              "sala ao vivo — e o defeito só aparece como 'está lento'")
        corpo_js, enc_js = servir._talvez_comprime(grande, "application/javascript", "gzip")
        checa("...e aceita o que é texto comum",
              enc_js == "gzip" and len(corpo_js) < len(grande),
              "a guarda não pode ser tão larga que impeça a compressão")

        st, h, _ = pede("/api/stream", True, token, so_cabecalho=True)
        checa("SSE NUNCA viaja comprimido",
              "gzip" not in h.get("content-encoding", ""),
              "gzip guarda bytes em buffer: a sala ao vivo entregaria a mensagem "
              "quando o buffer enchesse, não quando ela chegasse")
        st, h, corpo = pede("/apple-touch-icon.png", True)
        checa("PNG não é recomprimido",
              "gzip" not in h.get("content-encoding", ""),
              "já vem comprimido; regzipar gasta CPU e às vezes cresce")

        print("— quem não pede, não recebe —")
        st, h, corpo = pede("/sala.js", False)
        checa("cliente sem gzip recebe o texto cru",
              st == 200 and "gzip" not in h.get("content-encoding", "")
              and corpo[:1] != b"\x1f",
              "um cliente antigo não pode receber bytes que não sabe abrir")

        print("— o corpo pequeno não paga o cabeçalho —")
        st, h, corpo = pede("/manifest.webmanifest", True)
        checa("arquivo abaixo do piso vai sem comprimir",
              len(corpo) >= 1024 or "gzip" not in h.get("content-encoding", ""),
              f"{len(corpo)} B — comprimir isto custa mais que economiza")

        print("— a sala inteira, que é o maior recurso —")
        # Em modo leitura (o padrão) o servidor não emite token: loopback já é a
        # barreira. O token só existe com `--escrever`. Pedir sem ele é o caminho
        # normal deste modo, não um atalho.
        _, h, corpo = pede("/api/sala", True, token)
        _, _, cru = pede("/api/sala", False, token)
        checa("o JSON da sala comprime",
              h.get("content-encoding") == "gzip" and len(corpo) < len(cru) * 0.6,
              f"{len(cru)} → {len(corpo)} B — é o maior recurso da página")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(lar, ignore_errors=True)

    print(f"\n{_ok} ✔  {_falhou} ✗")
    return 1 if _falhou else 0


if __name__ == "__main__":
    raise SystemExit(main())
