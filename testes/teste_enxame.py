#!/usr/bin/env python3
"""O visualizador IASWARM dourado — o que a interface promete, o disco prova.

Trava as peças do pedido: o mesmo botão da gaveta no topo, a logo IASWARM
acima da luazinha, a janela que troca, a rota de leitura do enxame, e o
controle remoto por worker. Também o caso que REPROVA: o cliente não escolhe
pasta, `../` não atravessa.
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
UI = RAIZ / "ui"
HTML = (UI / "index.html").read_text(encoding="utf-8")
JS = (UI / "sala.js").read_text(encoding="utf-8")
CSS = (UI / "estilo.css").read_text(encoding="utf-8")
SERVIR = UI / "servir.py"

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


def porta_livre(inicio: int = 59110) -> int:
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


def main() -> int:
    print("— as peças na interface —")
    checa("o botão da gaveta no topo existe", 'id="btn-gaveta-topo"' in HTML)
    topo = re.search(r'<button[^>]*id="btn-gaveta-topo"[^>]*>', HTML)
    checa("o botão do topo tem o mesmo aria-controls da gaveta",
          bool(topo) and 'aria-controls="gaveta"' in topo.group(0)
          and "aria-label=" in topo.group(0))
    checa("os dois botões da gaveta compartilham o mesmo gesto",
          "function botoesGaveta" in JS and "botoesGaveta().forEach" in JS)

    checa("a logo IASWARM está escrita como o provedor escreve",
          'id="btn-enxame"' in HTML and ">IASWARM</span>" in HTML)
    # a logo fica ANTES da luazinha no rodapé do trilho — é o "em cima"
    rodape = HTML[HTML.index("trilho-rodape"):HTML.index("cabeca")]
    checa("a logo fica acima da luazinha no markup",
          rodape.index('id="btn-enxame"') < rodape.index('id="btn-tema"'),
          "a ordem no trilho-rodape é o em-cima do desktop vertical")
    checa("clicar a logo troca a janela",
          "function janelaEnxame" in JS and "$('#btn-enxame').addEventListener" in JS)
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
    (run / "workers.tsv").write_text("w-grok\tgrok\t5\n", encoding="utf-8")
    (run / "progress" / "w-grok.jsonl").write_text(
        '{"ts":"08:00:00","etapa":0,"de":5,"estado":"despachado","nota":"grok (beta)"}\n'
        '{"ts":"08:01:00","etapa":2,"de":5,"estado":"rodando","nota":"pintando o ouro"}\n',
        encoding="utf-8")
    (run / "logs" / "w-grok.log").write_text("linha 1\nlinha 2 do terminal\n", encoding="utf-8")
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
        import shutil
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
    raise SystemExit(main())
