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
import gzip
import json
import mimetypes
import os
import re
import base64
import secrets
import select
import socket
import subprocess
import sys
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

def _acha_nucleo() -> Path:
    """Onde mora o `iachat_core`, em ordem de confiança.

    Era um caminho ÚNICO e fixo: `~/Projetos/ia-chat/bin`. Funciona na máquina do autor
    e em nenhuma outra — o repositório irmão pode estar em qualquer lugar, e no runner
    do CI ele fica no workspace. O `lancador.py` já contornava por `PYTHONPATH`, o que
    salvava o app em produção e deixava o servidor sozinho em todo resto.

    O preço foi medido no primeiro push do repositório público: ONZE testes vermelhos,
    todos com o mesmo sintoma — servidor sobe, responde 0 mensagem. Quando onze testes
    caem pela mesma causa, o defeito é do produto, não dos testes.

    O irmão RELATIVO é o que faz isto funcionar em qualquer clone: quem baixa os dois
    repositórios lado a lado — que é o que os dois READMEs mandam fazer — tem o núcleo
    em `../ia-chat/bin` e não precisa saber disso.
    """
    daqui = Path(__file__).resolve().parent           # …/ia-chat-app/ui
    for c in (Path(os.environ["IACHAT_CORE"]) if os.environ.get("IACHAT_CORE") else None,
              daqui.parent.parent / "ia-chat" / "bin",          # irmão do repo
              daqui.parent.parent.parent / "ia-chat" / "bin",   # irmão do bundle
              Path.home() / "Projetos" / "ia-chat" / "bin",     # o caminho do autor
              Path.home() / ".claude" / "scripts" / "ia-chat"): # o que o install.sh deixa
        if c and (c / "iachat_core.py").is_file():
            return c
    return Path.home() / "Projetos" / "ia-chat" / "bin"


sys.path.insert(0, str(_acha_nucleo()))
import iachat_core as core  # noqa: E402

UI = Path(__file__).resolve().parent
CFG = {"escrever": False, "papel": "bauer", "token": ""}

# — os comandos do dono que ATRAVESSAM o servidor ————————————————————————
#
# Decisão do dono (fase 9, 18/08): os comandos de barra FUNCIONAM a partir do
# app — não viram post de texto nem linha para copiar. A régua de segurança é a
# mesma do CLI, fechada em três travas:
#
# 1. ALLOWLIST FECHADA, argv CONSTANTE. Cada rota é cravada no código e mapeia
#    para um subcomando fixo. Não há shell=True, não há string concatenada, e o
#    cliente não escolhe o comando nem um argumento sequer. Texto do dono NUNCA
#    vira argumento de linha de comando: ele entra como UM OBJETO JSON pelo
#    stdin do comando (flag `--via-app`, validada chave a chave no próprio
#    `iachat-comando`, em `le_via_app` — chave fora do mapa é recusada antes de
#    tocar no despacho).
#
# 2. IDENTIDADE DO SERVIDOR, nunca do cliente. O `--de` sai de CFG["papel"] —
#    o papel com que este servidor subiu. Foi aceitando identidade do payload
#    que apareceu na sala, em 17/08, uma mensagem assinada `bauer` que ele não
#    escreveu; e o CLI ajuda: sem terminal e sem `--de`, ele RECUSA assinar
#    pelo dono (`autor()` no iachat-comando). Por isso o servidor sempre passa
#    `--de` — o dele.
#
# 3. MOSTRAR ANTES DE GASTAR OU MATAR. `plan` (despacha frota paga), `parar`
#    (mata processo) e `refaz` (gasta assinatura) só atravessam em dois tempos:
#    primeiro o pedido com `"seco": true` — a previsão do CLI, sem efeito
#    colateral — e só depois o pedido com `"confirmado": true`. Sem um dos
#    dois, o pedido morre aqui com 400: a confirmação é gate do SERVIDOR, não
#    cortesia do JavaScript. A prova de identidade do alvo continua valendo é
#    na hora do kill (`confere_dono`, fail-closed), porque entre a previsão e o
#    clique há uma pausa humana em que um PID pode ser reciclado — a previsão
#    mostra o presente; quem prova é o instante.
#
# `quem` é o único GET: só lê. Todo o resto é POST, porque muda o mundo.
# Mesmo raciocínio do núcleo: o comando vive ao lado dele, onde quer que ele esteja.
IACHAT_COMANDO = _acha_nucleo() / "iachat-comando"
COMANDOS_HTTP: dict[str, tuple[str, ...]] = {"quem": ("quem", "--json")}
# Rotas de POST. nome → (subcomando, aceita `--de`). `refaz` não assina nada
# (não posta na sala), por isso é o único sem `--de`.
COMANDOS_POST: dict[str, tuple[str, bool]] = {
    "goal": ("goal", True),
    "plan": ("plan", True),
    "concluir": ("concluir", True),
    "parar": ("parar", True),
    "refaz": ("refaz", False),
    "decidi": ("decidi", True),
}
# Os que gastam ou matam: a previsão `seco` recebe um recibo efêmero nascido
# neste processo. A execução precisa devolver esse recibo junto de
# `confirmado`; um booleano sozinho não prova que a previsão existiu.
# (`plan --colher` só lê os planos; o tratamento está em `_comando_post`.)
EXIGEM_CONFIRMACAO = ("plan", "parar", "refaz")
# Teto de tempo: o `quem` varre a tabela de processos. Se travar, a thread do
# servidor fica presa e a vaga não volta — o mesmo problema do SSE sem teto.
TETO_COMANDO_S = 8
# POST despacha frota (vários Popen, cada um sondando o `lstart`) ou mata com
# espera educada de SIGTERM — custa mais que uma leitura. 20 s cobre com folga
# sem virar thread presa.
TETO_COMANDO_POST_S = 20

# Recibos do mostrar-antes. Três minutos são tempo humano para ler e clicar,
# mas não uma autorização reaproveitável horas depois. O dicionário é memória
# do processo: reiniciar o servidor invalida tudo por construção. O teto evita
# que um cliente autenticado acumule previsões sem limite dentro da janela.
RECIBO_TTL_S = 180
TETO_RECIBOS = 256
_RECIBOS: dict[str, dict] = {}
_RECIBOS_TRAVA = threading.Lock()

# O sino do DONO usa a infraestrutura que o ia-chat já possui. O estado não
# mora aqui: continua sendo `config.json:notificar_operador`. Ao ligar pelo app,
# este instalador apenas garante a perna macOS (LaunchAgent) para ESSA sala.
IACHAT_SCRIPTS = Path(os.environ.get(
    "IACHAT_SCRIPTS", str(Path.home() / ".claude" / "scripts" / "ia-chat")
)).expanduser()
INSTALADOR_SINO = IACHAT_SCRIPTS / "ia-bell-install-daemon.sh"
TETO_INSTALAR_SINO_S = 15

# — o visualizador IASWARM lê o disco do enxame, nunca escreve ——————————————
# A raiz é cravada (ou vem de IASWARM_RAIZ no ambiente, para o teste). O cliente
# não escolhe pasta: um `?run=../../` morre no RE_ID antes de tocar o disco.
# Cauda de log é teto de 8 KB — o remoto mostra o fim, não o arquivo inteiro.
IASWARM_RAIZ = Path(os.environ.get(
    "IASWARM_RAIZ", str(Path.home() / ".claude" / "iaswarm-runs")
)).expanduser()
RE_IASWARM_ID = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
TETO_LOG_IASWARM = 8192

# — groupchat: mensagens da sala + snapshots da sessão de cada IA —————————
# O log comum já chega por `msgs_desde`; ele NÃO mede contexto. A telemetria
# vem de um sidecar JSONL separado, uma atualização por linha, exatamente no
# contrato de `PROJETO-groupchat.md` §8. O caminho é fixo para o processo (ou
# declarado no ambiente para o produtor da telemetria); nunca vem da query.
# Ausência do sidecar é um estado válido: a API devolve `unknown`, não inventa
# percentual com bytes da sala.
GROUPCHAT_FONTE = Path(os.environ.get(
    "IACHAT_GROUPCHAT", str(core.home() / "groupchat.jsonl")
)).expanduser()
TETO_GROUPCHAT_JSONL = 1024 * 1024

# Limites da resposta do groupchat, medidos na sala real em 18/08.
# Uma mensagem ocupa 1.537 B na mediana e 3.172 B no p95; o envelope atual,
# sem mensagens, ocupa 5.328 B. Assim, 24 itens caberiam em ~42 KiB no caso
# mediano, enquanto o teto duro de 48 KiB segura mensagens longas e mantém
# aproximadamente as 20 falas mais recentes no primeiro carregamento.
LIMITE_GROUPCHAT_ITENS = 24
LIMITE_GROUPCHAT_SNAPSHOTS = 48
TETO_GROUPCHAT_RESPOSTA = 48 * 1024
# A resposta reserva espaço para preencher o aviso de corte depois da seleção.
# O gate final ainda mede o JSON exato; esta margem evita retirar item no fim.
MARGEM_GROUPCHAT_CORTE = 1024

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


def _argumentos_recibo(dados: dict) -> str:
    """Serializa só os argumentos reais; controles HTTP não fazem parte deles."""
    argumentos = {
        k: v for k, v in dados.items()
        if k not in ("seco", "confirmado", "recibo")
    }
    return json.dumps(
        argumentos, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _emite_recibo(nome: str, dados: dict, previsao: str,
                   agora: float | None = None) -> str:
    """Guarda no servidor uma autorização curta ligada ao comando e previsão."""
    instante = time.monotonic() if agora is None else agora
    registro = {
        "comando": nome,
        "argumentos": _argumentos_recibo(dados),
        "previsao": previsao,
        "expira": instante + RECIBO_TTL_S,
    }
    with _RECIBOS_TRAVA:
        expirados = [chave for chave, item in _RECIBOS.items()
                     if item["expira"] <= instante]
        for chave in expirados:
            _RECIBOS.pop(chave, None)
        while len(_RECIBOS) >= TETO_RECIBOS:
            mais_antigo = min(_RECIBOS, key=lambda chave: _RECIBOS[chave]["expira"])
            _RECIBOS.pop(mais_antigo, None)
        recibo = secrets.token_urlsafe(32)
        while recibo in _RECIBOS:
            recibo = secrets.token_urlsafe(32)
        _RECIBOS[recibo] = registro
    return recibo


def _consome_recibo(nome: str, dados: dict,
                     agora: float | None = None) -> tuple[bool, str]:
    """Queima o recibo antes de validar: erro ou segundo clique não o reutilizam."""
    recibo = dados.get("recibo")
    if not isinstance(recibo, str) or not recibo.strip():
        return False, "recibo ausente: peça a previsão antes de confirmar"
    instante = time.monotonic() if agora is None else agora
    with _RECIBOS_TRAVA:
        registro = _RECIBOS.pop(recibo, None)
    if registro is None:
        return False, "recibo desconhecido ou já usado: peça uma nova previsão"
    if registro["expira"] <= instante:
        return False, "recibo expirado: peça uma nova previsão"
    if registro["comando"] != nome:
        return False, "recibo pertence a outro comando: peça a previsão correta"
    if registro["argumentos"] != _argumentos_recibo(dados):
        return False, "recibo pertence a outros argumentos: peça nova previsão"
    return True, "ok"


def ultima() -> int:
    try:
        return int(json.loads(core.p_estado().read_text())["ultima"])
    except Exception:
        return 0


def msgs_desde(n: int) -> list[dict]:
    with core.travado():
        # SEMPRE `core._msgs_desde`, inclusive com n==0. O atalho `parse(p_chat())` lia
        # só o arquivo ATIVO e ignorava os recortes — então, depois de uma rotação
        # (que é automática quando o ativo estoura o teto), o app abria parecendo uma
        # sala nova. As mensagens antigas não foram apagadas: o CLI ainda as acha,
        # porque `_msgs_desde` abre os recortes quando falta faixa. Quem só usa o app
        # concluiria que o começo da conversa evaporou.
        #
        # É o mesmo desenho do `--lan` e do `entrar`: o núcleo resolveu, o app tomou um
        # atalho paralelo. Achado do worker `j1-app-paralelo`, medido com
        # `iachat rotate --forcar` (7 msgs → recorte-01, ativo em #8).
        brutas = core._msgs_desde(n)
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
        "notificar_operador": cfg.get("notificar_operador", False) is True,
        "escrever": CFG["escrever"], "papel": CFG["papel"],
    }


def _groupchat_atualizacoes() -> list[dict]:
    """Lê a cauda do sidecar sem transformar sala em contexto.

    A validação deliberadamente só garante a forma externa. O cliente aplica
    de novo as regras numéricas antes de desenhar a barra; auditoria em duas
    camadas evita que um produtor marque `exact` com numerador inválido.
    """
    if not GROUPCHAT_FONTE.is_file():
        return []
    try:
        bruto = GROUPCHAT_FONTE.read_bytes()
    except OSError:
        return []
    if len(bruto) > TETO_GROUPCHAT_JSONL:
        bruto = bruto[-TETO_GROUPCHAT_JSONL:]
        # A primeira linha pode ter começado antes do corte.
        _, _, bruto = bruto.partition(b"\n")
    saida: list[dict] = []
    for linha in bruto.splitlines():
        try:
            item = json.loads(linha)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(item, dict):
            continue
        ia = core.normaliza_ia(str(item.get("ia_id") or ""))
        contexto = item.get("context")
        if not ia or not isinstance(contexto, dict):
            continue
        estado = contexto.get("state")
        if estado not in ("exact", "estimated", "unknown"):
            contexto = {**contexto, "state": "unknown",
                        "reason": contexto.get("reason") or "invalid_state"}
        # A sentinela é soberana mesmo se o produtor escrever `state: exact`.
        if contexto.get("last_prompt_tokens") == -1:
            contexto = {**contexto, "state": "unknown",
                        "reason": "compacted_waiting_measurement"}
        saida.append({
            "ia_id": ia,
            "session_id": str(item.get("session_id") or ""),
            "model_id": str(item.get("model_id") or ""),
            "message_n": item.get("message_n"),
            "context": contexto,
            "liveness": item.get("liveness")
                if isinstance(item.get("liveness"), dict) else {},
            # O adaptador de eventos estruturados pode anexar ações à mesma
            # atualização. A etapa visual as dobra; texto bruto nunca vira HTML.
            "actions": item.get("actions")
                if isinstance(item.get("actions"), list) else [],
        })
    return saida


def _groupchat_bytes(resposta: dict) -> int:
    """Mede o mesmo JSON que `_json` envia, antes da compressão HTTP."""
    return len(json.dumps(resposta, ensure_ascii=False).encode())


def groupchat(desde: int = 0) -> dict:
    """Lote incremental legível pelo terceiro modo, sem escrita no núcleo.

    `desde` segue a gramática já usada por `/api/sala`: é o último número que
    o cliente consumiu. No primeiro carregamento (`desde=0`) entram as falas
    mais recentes; depois, entram somente números maiores que o cursor.
    """
    desde = max(0, int(desde))
    # Esta é a mudança central: depois do primeiro lote, o núcleo já pode abrir
    # só a faixa posterior ao cursor, em vez de reler a sala inteira a cada 2 s.
    brutas = msgs_desde(desde)
    fim_lote = max([desde, *(int(m.get("n") or desde) for m in brutas)])
    mensagens = [m for m in brutas if m.get("de") != CFG["papel"]]
    atualizacoes = _groupchat_atualizacoes()
    ultimas: dict[str, dict] = {}
    for item in atualizacoes:
        ultimas[item["ia_id"]] = item

    # IA ativa sem telemetria continua visível, explicitamente desconhecida.
    ias = list(sala().get("na_sala") or [])
    for m in mensagens:
        ia = core.normaliza_ia(str(m.get("de") or ""))
        if ia and ia not in ias:
            ias.append(ia)
    for ia in ias:
        if ia == CFG["papel"] or ia in ultimas:
            continue
        ultimas[ia] = {
            "ia_id": ia, "session_id": "", "model_id": "",
            "context": {
                "state": "unknown", "last_prompt_tokens": None,
                "estimated_prompt_tokens": None,
                "context_window_tokens": None,
                "source": None, "sampled_at": None,
                "reason": "telemetry_unavailable",
            },
            "liveness": {"last_signal_at": None,
                         "session_state": "unknown"},
            "actions": [],
        }
    snapshots = atualizacoes[-LIMITE_GROUPCHAT_SNAPSHOTS:]
    telemetria_omitida = max(0, len(atualizacoes) - len(snapshots))
    sessoes = list(ultimas.values())
    resposta = {
        "fonte": str(GROUPCHAT_FONTE) if GROUPCHAT_FONTE.is_file()
                 else "sem telemetria",
        "desde": desde,
        # `ultima` é o cursor realmente consumido; `ultima_sala` permite à UI
        # distinguir "estou em dia" de "há outro lote para buscar".
        "ultima": desde,
        "ultima_sala": max(ultima(), fim_lote),
        "limites": {
            "itens": LIMITE_GROUPCHAT_ITENS,
            "bytes": TETO_GROUPCHAT_RESPOSTA,
        },
        "corte": {
            "ativo": False,
            "motivo": "nenhum",
            "omitidas": 0,
            "pendentes": 0,
            "telemetria_omitida": telemetria_omitida,
            "sessoes_omitidas": 0,
            "direcao": "nenhuma",
        },
        "sessions": sessoes,
        "snapshots": snapshots,
        "msgs": [],
    }

    # A telemetria também é entrada externa. Se ela crescer ou trouxer uma ação
    # enorme, perde os snapshots mais antigos antes de roubar o teto da conversa.
    while (_groupchat_bytes(resposta) >
           TETO_GROUPCHAT_RESPOSTA - MARGEM_GROUPCHAT_CORTE and snapshots):
        snapshots.pop(0)
        telemetria_omitida += 1

    # Um produtor pode anexar saídas grandes às sessões atuais. Mantém a sessão
    # e sua barra de contexto, mas dobra fora as ações se o envelope estourar.
    if (_groupchat_bytes(resposta) >
            TETO_GROUPCHAT_RESPOSTA - MARGEM_GROUPCHAT_CORTE):
        for i, sessao in enumerate(list(sessoes)):
            acoes = sessao.get("actions")
            if not acoes:
                continue
            sessoes[i] = {**sessao, "actions": []}
            telemetria_omitida += len(acoes)
            if (_groupchat_bytes(resposta) <=
                    TETO_GROUPCHAT_RESPOSTA - MARGEM_GROUPCHAT_CORTE):
                break

    # Última defesa para um sidecar patológico: sessão omitida é declarada no
    # mesmo aviso de corte; o JSON nunca ultrapassa o teto em silêncio.
    sessoes_omitidas = 0
    while (_groupchat_bytes(resposta) >
           TETO_GROUPCHAT_RESPOSTA - MARGEM_GROUPCHAT_CORTE and sessoes):
        sessoes.pop(0)
        sessoes_omitidas += 1

    limite_bytes = TETO_GROUPCHAT_RESPOSTA - MARGEM_GROUPCHAT_CORTE
    selecionadas: list[dict] = []
    motivo_bytes = False
    motivo_itens = False
    omitidas_grandes = 0

    if desde == 0:
        # Primeiro carregamento: contexto recente, em ordem cronológica. Começa
        # da fala mais nova e recua enquanto houver item e bytes disponíveis.
        for mensagem in reversed(mensagens):
            if len(selecionadas) >= LIMITE_GROUPCHAT_ITENS:
                motivo_itens = True
                break
            proposta = [mensagem, *selecionadas]
            resposta["msgs"] = proposta
            if _groupchat_bytes(resposta) > limite_bytes:
                resposta["msgs"] = selecionadas
                motivo_bytes = True
                break
            selecionadas = proposta
        # O lote inicial deliberadamente ancora no presente; o aviso informa
        # quantas falas antigas ficaram fora, sem fingir que nada foi cortado.
        resposta["ultima"] = fim_lote
    else:
        # Atualizações caminham para a frente. Mensagens do próprio papel não
        # aparecem no groupchat, mas ainda avançam o cursor para não serem
        # relidas para sempre.
        cursor = desde
        for mensagem in brutas:
            numero = int(mensagem.get("n") or cursor)
            if mensagem.get("de") == CFG["papel"]:
                cursor = max(cursor, numero)
                continue
            if len(selecionadas) >= LIMITE_GROUPCHAT_ITENS:
                motivo_itens = True
                break
            resposta["msgs"] = [*selecionadas, mensagem]
            if _groupchat_bytes(resposta) > limite_bytes:
                resposta["msgs"] = selecionadas
                motivo_bytes = True
                if not selecionadas:
                    # Uma fala maior que o teto não pode congelar o cursor. Ela
                    # fica na sala canônica e a omissão aparece no aviso.
                    cursor = max(cursor, numero)
                    omitidas_grandes += 1
                    continue
                break
            selecionadas.append(mensagem)
            cursor = max(cursor, numero)
        resposta["ultima"] = cursor

    resposta["msgs"] = selecionadas
    omitidas = max(0, len(mensagens) - len(selecionadas))
    pendentes = (sum(1 for m in mensagens
                     if int(m.get("n") or 0) > resposta["ultima"])
                 if desde > 0 else 0)
    motivos = []
    if motivo_itens:
        motivos.append("itens")
    if motivo_bytes:
        motivos.append("bytes")
    if telemetria_omitida or sessoes_omitidas:
        motivos.append("telemetria")
    if omitidas_grandes:
        motivos.append("item_maior_que_teto")
    corte_ativo = bool(omitidas or telemetria_omitida or sessoes_omitidas)
    resposta["corte"] = {
        "ativo": corte_ativo,
        "motivo": "+".join(dict.fromkeys(motivos)) if motivos else "nenhum",
        "omitidas": omitidas,
        "pendentes": pendentes,
        "telemetria_omitida": telemetria_omitida,
        "sessoes_omitidas": sessoes_omitidas,
        "direcao": "inicio" if desde == 0 and omitidas else
                   "fim" if desde > 0 and omitidas else "nenhuma",
    }

    # Gate dentro do produtor: a conta final inclui o aviso real, não uma
    # estimativa. A margem acima torna esta defesa normalmente um no-op.
    while _groupchat_bytes(resposta) > TETO_GROUPCHAT_RESPOSTA and selecionadas:
        if desde == 0:
            selecionadas.pop(0)       # preserva as falas mais recentes
        else:
            selecionadas.pop()        # preserva um prefixo sem buraco
        resposta["msgs"] = selecionadas
        resposta["corte"]["ativo"] = True
        resposta["corte"]["motivo"] = "bytes"
        resposta["corte"]["omitidas"] += 1
        if desde > 0:
            resposta["ultima"] = (int(selecionadas[-1].get("n") or desde)
                                   if selecionadas else desde)
    return resposta


# ── compressão ───────────────────────────────────────────────────────────────
# Ele lê a sala no celular, por um túnel, em rede móvel. Medido em 18/08: a
# interface pesava 183 KB de texto e o servidor não comprimia nada — 53 KB com
# gzip, 71% a menos. É a diferença entre abrir e esperar, e não custa nada.
#
# ⚠️ O SSE (`text/event-stream`) NUNCA passa por aqui, e não é descuido: o gzip
# guarda bytes num buffer até fechar o bloco, e um stream comprimido entrega a
# mensagem quando o buffer enche — não quando ela chega. A sala ao vivo pararia
# de ser ao vivo, e o defeito seria invisível até alguém reclamar de atraso.
MIN_GZIP = 1024              # abaixo disto o cabeçalho custa mais que a economia
TIPOS_GZIP = ("text/", "application/json", "application/javascript",
              "image/svg+xml", "application/manifest+json")


def _talvez_comprime(corpo: bytes, tipo: str, aceita: str) -> tuple[bytes, str]:
    """(corpo, encoding) — comprime só o que vale a pena e só se pedirem."""
    if "gzip" not in aceita.lower():
        return corpo, ""
    if len(corpo) < MIN_GZIP:
        return corpo, ""
    if tipo.startswith("text/event-stream"):
        return corpo, ""          # ao vivo não se enfileira em buffer
    if not any(tipo.startswith(t) for t in TIPOS_GZIP):
        return corpo, ""          # png/ico já vêm comprimidos; regzipar só gasta CPU
    return gzip.compress(corpo, 6), "gzip"


class Sala(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "iachat-ui/0.1"

    def log_message(self, fmt, *a):
        pass

    def _json(self, obj, code=200):
        corpo = json.dumps(obj, ensure_ascii=False).encode()
        # A sala inteira sai por aqui, e é o maior recurso da página: 71 KB de
        # JSON contra 95 KB de JS. Texto de conversa comprime muito — deixá-lo
        # de fora seria consertar metade do problema.
        corpo, encoding = _talvez_comprime(
            corpo, "application/json", self.headers.get("Accept-Encoding", ""))
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        if encoding:
            self.send_header("Content-Encoding", encoding)
            self.send_header("Vary", "Accept-Encoding")
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
        corpo, encoding = _talvez_comprime(corpo, tipo, self.headers.get("Accept-Encoding", ""))
        self.send_header("Content-Type", f"{tipo}; charset=utf-8")
        if encoding:
            self.send_header("Content-Encoding", encoding)
            self.send_header("Vary", "Accept-Encoding")
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
        if u.path == "/api/sino":
            cfg = core.config()
            return self._json({
                "notificar_operador":
                    cfg.get("notificar_operador", False) is True,
                "escrever": CFG["escrever"],
            })
        if u.path == "/api/sala":
            desde = int((q.get("desde") or ["0"])[0])
            return self._json({"ultima": ultima(), "desde": desde,
                               "msgs": msgs_desde(desde), "sala": sala()})
        if u.path == "/api/stream":
            return self._stream(int((q.get("desde") or ["0"])[0]))
        # UMA rota por comando permitido, com o nome CRAVADO no código. Não existe
        # `/api/comando?nome=…`: uma rota paramétrica convidaria o cliente a
        # escolher o que roda, e a allowlist viraria a última linha de defesa em
        # vez da única porta. `q` nem é lido aqui.
        if u.path == "/api/quem":
            return self._comando("quem")
        if u.path == "/api/iaswarm":
            return self._iaswarm(q)
        if u.path == "/api/iaswarm/remoto":
            return self._iaswarm_remoto(q)
        if u.path == "/api/groupchat":
            try:
                desde_groupchat = int((q.get("desde") or ["0"])[0])
            except (TypeError, ValueError):
                return self._json({"erro": "desde precisa ser inteiro"}, 400)
            if desde_groupchat < 0:
                return self._json({"erro": "desde não pode ser negativo"}, 400)
            return self._json(groupchat(desde_groupchat))
        if u.path == "/api/mapa":
            return self._mapa()
        if u.path.count("/") == 1 and u.path[1:]:
            return self._estatico(u.path[1:])
        self._json({"erro": "rota inexistente"}, 404)

    def _mapa(self) -> None:
        """O `caminho.md` — o mapa curto que a skill `ia-compactacao` grava.

        O dono pediu que "esse documento possa ser aberto para minha leitura no app, se
        possível a versão renderizada do Obsidian". Não embuti renderizador: a interface
        já sabe desenhar markdown (`corpoHTML` em `sala.js`), e acrescentar um segundo
        seria manter duas gramáticas que divergem no primeiro reparo.

        LEITURA PURA e caminho CRAVADO: o cliente não escolhe arquivo. Um `?arq=` viraria
        leitura arbitrária de disco pela rede — a sala roda com `--lan` e já foi publicada
        por túnel hoje.
        """
        alvo = core.home() / "caminho.md"
        if not alvo.is_file():
            return self._json({
                "existe": False,
                "porque": "ainda não houve compactação nesta sala — o mapa nasce no "
                          "PreCompact, ou por `ia-compactacao --mapa`.",
            })
        try:
            texto = alvo.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return self._json({"erro": f"não consegui ler o mapa: {e}"}, 500)
        return self._json({
            "existe": True,
            "texto": texto,
            "bytes": len(texto.encode()),
            "em": time.strftime("%d/%m %H:%M", time.localtime(alvo.stat().st_mtime)),
            "caminho": str(alvo),
        })

    def _iaswarm_id(self, bruto: str) -> str | None:
        if not isinstance(bruto, str):
            return None
        nome = bruto.strip()
        if not RE_IASWARM_ID.fullmatch(nome) or ".." in nome:
            return None
        return nome

    def _iaswarm_pasta(self, run_id: str) -> Path | None:
        raiz = IASWARM_RAIZ.resolve()
        alvo = (raiz / run_id).resolve()
        try:
            alvo.relative_to(raiz)
        except ValueError:
            return None
        if not alvo.is_dir():
            return None
        return alvo

    def _iaswarm_linhas(self, path: Path) -> list[dict]:
        saida = []
        try:
            texto = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return saida
        for ln in texto.splitlines():
            s = ln.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                saida.append(obj)
        return saida

    def _iaswarm_run(self, pasta: Path) -> dict | None:
        if pasta.name.startswith("_") or pasta.name.startswith("."):
            return None
        progress: dict[str, list] = {}
        prog = pasta / "progress"
        if prog.is_dir():
            for f in sorted(prog.iterdir()):
                if f.suffix == ".jsonl" and RE_IASWARM_ID.match(f.stem):
                    progress[f.stem] = self._iaswarm_linhas(f)
        tsv: dict[str, dict] = {}
        for nome in ("workers.tsv", "state.json"):
            arq = pasta / nome
            if nome == "workers.tsv" and arq.is_file():
                try:
                    for ln in arq.read_text(encoding="utf-8", errors="replace").splitlines():
                        c = ln.strip().split("\t")
                        if len(c) >= 3 and c[0] and not c[0].startswith("#") and RE_IASWARM_ID.match(c[0]):
                            tsv[c[0]] = {"braco": c[1], "etapas": int(c[2]) if c[2].isdigit() else 5}
                except OSError:
                    pass
            if nome == "state.json" and arq.is_file():
                try:
                    st = json.loads(arq.read_text(encoding="utf-8"))
                    for w in st.get("workers") or []:
                        wid = str(w.get("worker") or "")
                        if RE_IASWARM_ID.match(wid) and wid not in tsv:
                            tsv[wid] = {
                                "braco": w.get("variante") or w.get("braco") or "",
                                "etapas": int(w.get("etapas") or 5),
                            }
                except (OSError, json.JSONDecodeError, TypeError, ValueError):
                    pass
        resultados: list[str] = []
        tamanhos: dict[str, int] = {}
        res = pasta / "resultados"
        if res.is_dir():
            for f in res.iterdir():
                if f.suffix == ".md" and RE_IASWARM_ID.match(f.stem) and f.is_file():
                    try:
                        tam = f.stat().st_size
                    except OSError:
                        continue
                    if tam > 0:
                        resultados.append(f.stem)
                        tamanhos[f.stem] = tam
        logs: dict[str, int] = {}
        lg = pasta / "logs"
        if lg.is_dir():
            for f in lg.iterdir():
                if f.suffix == ".log" and RE_IASWARM_ID.match(f.stem) and f.is_file():
                    try:
                        logs[f.stem] = f.stat().st_size
                    except OSError:
                        continue
        missao = ""
        md = pasta / "missao.md"
        if md.is_file():
            try:
                missao = md.read_text(encoding="utf-8", errors="replace").split("\n", 1)[0]
                missao = re.sub(r"^#+\s*", "", missao).strip()
            except OSError:
                missao = ""
        if not progress and not tsv:
            return None
        return {
            "id": pasta.name,
            "missao": missao,
            "caminho": str(pasta),
            "tsv": tsv,
            "progress": progress,
            "resultados": resultados,
            "tamanhos": tamanhos,
            "logs": logs,
        }

    def _iaswarm(self, q: dict):
        """Lista os runs do enxame. Leitura pura; o cliente não escolhe pasta."""
        raiz = IASWARM_RAIZ
        if not raiz.is_dir():
            return self._json({"fonte": "ausente", "raiz": str(raiz), "runs": []})
        bruto_run = (q.get("run") or [""])[0]
        pedido = self._iaswarm_id(bruto_run) if bruto_run else None
        if bruto_run and not pedido:
            return self._json({"erro": "run inválido"}, 400)
        runs = []
        try:
            alvos = []
            if pedido:
                pasta = self._iaswarm_pasta(pedido)
                if pasta is None:
                    return self._json({"erro": "run inexistente"}, 404)
                alvos = [pasta]
            else:
                for p in sorted(raiz.iterdir(), key=lambda x: x.name):
                    if p.is_dir() and not p.name.startswith(("_", ".")):
                        alvos.append(p)
            for pasta in alvos:
                cru = self._iaswarm_run(pasta)
                if cru:
                    runs.append(cru)
        except OSError as e:
            return self._json({"erro": f"não li o enxame: {e}"}, 500)
        return self._json({
            "fonte": "disco",
            "raiz": str(raiz.resolve()),
            "vivo": True,
            "runs": runs,
        })

    def _iaswarm_remoto(self, q: dict):
        """Dados + cauda do log de UM worker. Sem path do cliente."""
        run_id = self._iaswarm_id((q.get("run") or [""])[0])
        worker = self._iaswarm_id((q.get("worker") or [""])[0])
        if not run_id or not worker:
            return self._json({"erro": "run e worker obrigatórios"}, 400)
        pasta = self._iaswarm_pasta(run_id)
        if pasta is None:
            return self._json({"erro": "run inexistente"}, 404)
        cru = self._iaswarm_run(pasta)
        if cru is None:
            return self._json({"erro": "run vazio"}, 404)
        evs = (cru.get("progress") or {}).get(worker) or []
        tsv = (cru.get("tsv") or {}).get(worker) or {}
        log_path = pasta / "logs" / f"{worker}.log"
        cauda = ""
        if log_path.is_file():
            try:
                data = log_path.read_bytes()
                if len(data) > TETO_LOG_IASWARM:
                    data = data[-TETO_LOG_IASWARM:]
                cauda = data.decode("utf-8", "replace")
            except OSError:
                cauda = ""
        res_path = pasta / "resultados" / f"{worker}.md"
        resultado = ""
        if res_path.is_file():
            try:
                resultado = res_path.read_text(encoding="utf-8", errors="replace")[:4000]
            except OSError:
                resultado = ""
        return self._json({
            "run": run_id,
            "worker": worker,
            "braco": tsv.get("braco", ""),
            "etapas": tsv.get("etapas", 5),
            "eventos": evs,
            "log": cauda,
            "log_bytes": (cru.get("logs") or {}).get(worker),
            "resultado": resultado,
            "resultado_bytes": (cru.get("tamanhos") or {}).get(worker),
            "caminho_log": str(log_path) if log_path.is_file() else "",
            "caminho_resultado": str(res_path) if res_path.is_file() else "",
        })

    def _comando(self, nome: str):
        """Roda UM comando de LEITURA da allowlist e devolve o JSON dele.

        Nada do cliente entra no argv. Se um dia alguém acrescentar o nome aqui
        sem acrescentar em `COMANDOS_HTTP`, o pedido morre neste `if`, não no
        shell. Os comandos que MUDAM o mundo têm outra porta: `_comando_post`.
        """
        argv = COMANDOS_HTTP.get(nome)
        if argv is None:
            return self._json(
                {"erro": f"'{nome}' não atravessa o servidor — só no terminal"}, 403)
        if not IACHAT_COMANDO.is_file():
            # 501 e não 500: não é defeito, é ausência. A interface usa esta resposta
            # para mostrar a linha do terminal em vez de um erro sem saída.
            return self._json(
                {"erro": "iachat-comando não está instalado nesta máquina",
                 "linha": f"iachat-comando {argv[0]}"}, 501)
        try:
            r = subprocess.run(
                [sys.executable, str(IACHAT_COMANDO), *argv],
                capture_output=True, text=True, timeout=TETO_COMANDO_S,
                env={**os.environ, "IACHAT_HOME": str(core.home())},
            )
        except subprocess.TimeoutExpired:
            return self._json({"erro": f"o comando passou de {TETO_COMANDO_S}s"}, 504)
        except OSError as e:
            return self._json({"erro": f"não consegui rodar: {e}"}, 500)
        if r.returncode != 0:
            return self._json(
                {"erro": (r.stderr or "o comando falhou").strip()[:400]}, 500)
        try:
            return self._json(json.loads(r.stdout))
        except json.JSONDecodeError:
            return self._json({"erro": "o comando não devolveu JSON"}, 500)

    def _comando_post(self, nome: str, dados: dict):
        """Roda UM comando da allowlist de POST, com o payload no stdin dele.

        O argv é constante: só o subcomando (mapeado em `COMANDOS_POST`), o
        `--de` do papel com que ESTE servidor subiu (quando o comando assina
        algo) e `--via-app`. Nada do cliente entra na linha de comando — o JSON
        vai pelo stdin e é validado no CLI, chave a chave (`le_via_app`).

        Gate do mostrar-antes: `plan` (fora colher), `parar` e `refaz` (fora
        seco) exigem `"confirmado": true` MAIS o recibo efêmero emitido pela
        previsão correspondente. Quem pula a previsão, troca os argumentos ou
        clica duas vezes morre aqui — a confirmação é gate do servidor.
        """
        alvo = COMANDOS_POST.get(nome)
        if alvo is None:
            return self._json({"erro": f"'{nome}' não atravessa o servidor"}, 404)
        sub, aceita_de = alvo
        if nome in ("parar", "refaz"):
            # Defesa em profundidade: o CLI repete esta validação ao ler o
            # JSON. Esta ponta recusa ANTES do recibo e ANTES do subprocesso;
            # ``run``/``ia`` são IDs opacos, nunca texto livre nem caminho.
            for campo in ("run", "ia"):
                if campo in dados and self._iaswarm_id(dados[campo]) is None:
                    return self._json({
                        "erro": f"`{campo}` é identificador IASWARM inválido; "
                                "use 1–80 caracteres [A-Za-z0-9._-], sem `/`, "
                                "espaço ou `..`"
                    }, 400)
        if nome in EXIGEM_CONFIRMACAO:
            so_leitura = dados.get("seco") is True or (
                nome == "plan" and dados.get("colher") is True)
            if not so_leitura:
                if dados.get("confirmado") is not True:
                    return self._json(
                        {"erro": "este comando gasta ou mata: primeiro a previsão "
                                 "(payload com \"seco\": true), que devolve um "
                                 "recibo; só depois envie \"confirmado\": true "
                                 "com esse recibo."}, 400)
                aceito, motivo = _consome_recibo(nome, dados)
                if not aceito:
                    return self._json({"erro": motivo}, 400)
        if not IACHAT_COMANDO.is_file():
            return self._json(
                {"erro": "iachat-comando não está instalado nesta máquina",
                 "linha": f"iachat-comando {sub}"}, 501)
        argv = [sys.executable, str(IACHAT_COMANDO), sub]
        if aceita_de:
            # Identidade do SERVIDOR, nunca do cliente (trava 2 da allowlist).
            argv += ["--de", CFG["papel"]]
        argv.append("--via-app")
        # `confirmado` e `recibo` são travas DESTA camada; o CLI não os conhece.
        payload = {k: v for k, v in dados.items()
                   if k not in ("confirmado", "recibo")}
        try:
            r = subprocess.run(
                argv, capture_output=True, text=True,
                input=json.dumps(payload, ensure_ascii=False),
                timeout=TETO_COMANDO_POST_S,
                env={**os.environ, "IACHAT_HOME": str(core.home())},
            )
        except subprocess.TimeoutExpired:
            return self._json(
                {"erro": f"o comando passou de {TETO_COMANDO_POST_S}s"}, 504)
        except OSError as e:
            return self._json({"erro": f"não consegui rodar: {e}"}, 500)
        saida = (r.stdout or "").strip()
        aviso = (r.stderr or "").strip()
        if r.returncode == 0:
            resposta = {"ok": True, "comando": nome,
                        "saida": saida[:8000], "aviso": aviso[:2000]}
            if nome in EXIGEM_CONFIRMACAO and dados.get("seco") is True:
                previsao = json.dumps(
                    {"saida": resposta["saida"], "aviso": resposta["aviso"]},
                    ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                resposta["recibo"] = _emite_recibo(nome, dados, previsao)
                resposta["recibo_expira_em_s"] = RECIBO_TTL_S
            return self._json(resposta)
        # Recusa do comando (exit 2/3) não é defeito do servidor: é o
        # fail-closed do CLI falando. A interface mostra tal qual.
        return self._json({"ok": False, "comando": nome, "codigo": r.returncode,
                           "erro": (aviso or saida)[:4000]}, 409)

    def _garante_sino_operador(self) -> tuple[bool, str]:
        """Instala/recarrega o LaunchAgent só depois do clique em LIGAR.

        O argv é constante, sem shell e sem texto do cliente. A configuração
        ainda está `false` enquanto o instalador roda; portanto, instalar nunca
        dispara uma notificação por conta própria.
        """
        if not INSTALADOR_SINO.is_file():
            return False, f"instalador do sino ausente: {INSTALADOR_SINO}"
        try:
            r = subprocess.run(
                ["/bin/bash", str(INSTALADOR_SINO), "--operador", "15"],
                capture_output=True,
                text=True,
                timeout=TETO_INSTALAR_SINO_S,
                env={
                    **os.environ,
                    "IACHAT_HOME": str(core.home()),
                    "IACHAT_SCRIPTS": str(IACHAT_SCRIPTS),
                },
            )
        except subprocess.TimeoutExpired:
            return False, f"instalador passou de {TETO_INSTALAR_SINO_S}s"
        except OSError as exc:
            return False, f"não consegui iniciar o instalador: {exc}"
        if r.returncode != 0:
            detalhe = (r.stderr or r.stdout or "instalador falhou").strip()[:400]
            return False, detalhe
        return True, (r.stdout or "sino do Mac pronto").strip()[:400]

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
        # Rotas cravadas: `/api/post`, `/api/sino` e UM POST por comando da
        # allowlist. Não existe `/api/comando?nome=…` — rota paramétrica
        # convidaria o cliente a escolher o que roda.
        nome_comando = u.path[len("/api/"):] if u.path.startswith("/api/") else ""
        if u.path not in ("/api/post", "/api/sino") and nome_comando not in COMANDOS_POST:
            return self._json({"erro": "rota inexistente"}, 404)
        if not CFG["escrever"]:
            return self._json({"erro": "servidor em modo leitura"}, 403)
        # ANTI-CSRF. Sem isto, qualquer página aberta no navegador do dono pode
        # mandar um POST para este servidor e falar na sala com o nome dele. Um
        # form cross-site não consegue mudar o Origin nem forjar Sec-Fetch-Site.
        porta = self.server.server_address[1]
        origem = self.headers.get("Origin")
        # TODAS as interfaces físicas, não só a primeira. `--lan` imprime uma URL por
        # interface, e a allowlist aceitava apenas `_ip_local()` — o primeiro item da
        # mesma lista. Numa máquina com Wi-Fi E Ethernet, quem abrisse a SEGUNDA URL
        # impressa veria a sala carregar (GET não checa Origin) e tomaria 403 ao ENVIAR:
        # o pior tipo de defeito, o que parece funcionar. Hoje só `en0` tem IP nesta
        # máquina, então a armadilha está armada e não disparou. Achado do worker
        # `i1-celular`, medido com `Origin: http://10.211.55.2:18931` → 403.
        permitidas = {f"http://127.0.0.1:{porta}", f"http://localhost:{porta}"}
        permitidas |= {f"http://{ip}:{porta}" for ip in _ips_lan()}
        # Origem EXTRA, declarada pelo dono em `IACHAT_ORIGEM` (uma por linha ou
        # separada por vírgula). Existe para um caso real: quando a sala é publicada por
        # um túnel (Cloudflare, ngrok), o navegador manda `Origin: https://algo.example`,
        # que não é loopback nem LAN — e o envio tomava 403 depois de a página carregar,
        # o pior tipo de defeito, o que parece funcionar.
        #
        # É OPT-IN e literal de propósito: sem curinga, sem "aceita qualquer https". Quem
        # abre a porta é quem digita o endereço. O anti-CSRF continua fechado para todo o
        # resto — alargar por necessidade não é o mesmo que afrouxar.
        extra = os.environ.get("IACHAT_ORIGEM", "")
        permitidas |= {o.strip() for o in extra.replace("\n", ",").split(",") if o.strip()}
        if origem and origem not in permitidas:
            return self._json({"erro": f"origem recusada: {origem}"}, 403)
        # Corpo sem teto esgota a memória do processo: 256 KB é folgado para uma
        # mensagem de sala e barato de recusar.
        n = int(self.headers.get("Content-Length") or 0)
        if n > 262144:
            return self._json({"erro": "corpo grande demais"}, 413)
        try:
            dados = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(dados, dict):
                return self._json({"erro": "corpo JSON precisa ser objeto"}, 400)
            if nome_comando in COMANDOS_POST:
                # Allowlist de POST: o payload inteiro viaja pelo stdin do
                # comando, nunca pelo argv. O gate de confirmação mora em
                # `_comando_post`.
                return self._comando_post(nome_comando, dados)
            if u.path == "/api/sino":
                ligado = dados.get("ligado")
                if type(ligado) is not bool:
                    return self._json(
                        {"erro": "`ligado` precisa ser booleano"}, 400
                    )
                # Liga: prova primeiro que a perna macOS existe; só depois grava
                # `true`. Desliga: grava `false` imediatamente e o daemon fica mudo
                # no próximo ciclo, sem segundo arquivo de estado.
                if ligado:
                    ok, detalhe = self._garante_sino_operador()
                    if not ok:
                        return self._json(
                            {"erro": f"sino do Mac não ficou pronto: {detalhe}"}, 503
                        )
                cfg = core.configurar_notificacao_operador(ligado)
                return self._json({
                    "notificar_operador":
                        cfg.get("notificar_operador", False) is True,
                })
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
        except (json.JSONDecodeError, ValueError) as e:
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
