#!/usr/bin/env python3
"""Compara os contratos HTTP essenciais dos dois servidores e cataloga dívidas."""
from __future__ import annotations

import http.client
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
import urllib.parse
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CORE_BIN = RAIZ.parent / "ia-chat" / "bin"
LSOF = Path("/usr/sbin/lsof")
SERVIDORES = {
    "ui": RAIZ / "ui/servir.py",
    "bundle": RAIZ / "ia-chat.app/Contents/Resources/servidor.py",
}
HISTORICO = "histórico pré-existente para comparar servidores"
POST_CURTO = "post válido da comparação"

_ok = 0
_falhou = 0


def checa(nome: str, cond: bool, detalhe: str = "") -> None:
    global _ok, _falhou
    if cond:
        _ok += 1
        print(f"  ✔ {nome}")
    else:
        _falhou += 1
        print(f"  ✗ {nome}" + (f"\n      {detalhe}" if detalhe else ""))


def porta_livre(inicio: int) -> int:
    for porta in range(max(59900, inicio), 60000):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", porta))
            except OSError:
                continue
            return porta
    raise RuntimeError("nenhuma porta livre entre 59900 e 59999")


def ambiente(sala: Path, home: Path) -> dict[str, str]:
    amb = dict(os.environ)
    amb.update(
        HOME=str(home),
        IACHAT_HOME=str(sala),
        IACHAT_BIN=str(CORE_BIN),
        IACHAT_CORE=str(CORE_BIN),
        PYTHONPATH=str(CORE_BIN),
        PYTHONDONTWRITEBYTECODE="1",
        NO_PROXY="127.0.0.1,localhost",
        no_proxy="127.0.0.1,localhost",
    )
    for nome in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        amb.pop(nome, None)
    return amb


def prepara_historico(sala: Path, home: Path) -> subprocess.CompletedProcess[str]:
    codigo = (
        "import iachat_core as c; "
        "c.garantir_estrutura(); "
        f"c.post(de='codex', para='claude', texto={HISTORICO!r})"
    )
    return subprocess.run(
        [sys.executable, "-c", codigo],
        env=ambiente(sala, home),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def com_token(rota: str, token: str | None) -> str:
    if token is None:
        return rota
    separador = "&" if "?" in rota else "?"
    return rota + separador + urllib.parse.urlencode({"t": token})


def pede(
    porta: int,
    rota: str,
    token: str | None,
    *,
    metodo: str = "GET",
    dados: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    url = f"http://127.0.0.1:{porta}{com_token(rota, token)}"
    pedido = urllib.request.Request(url, data=dados, method=metodo, headers=headers or {})
    try:
        with urllib.request.urlopen(pedido, timeout=8) as resposta:
            return resposta.status, dict(resposta.headers.items()), resposta.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers.items()), exc.read()


def post_sem_content_length(porta: int, token: str) -> int:
    conexao = http.client.HTTPConnection("127.0.0.1", porta, timeout=8)
    try:
        conexao.putrequest("POST", com_token("/api/post", token))
        conexao.putheader("Content-Type", "application/json")
        conexao.endheaders()
        resposta = conexao.getresponse()
        resposta.read()
        return resposta.status
    finally:
        conexao.close()


def sem_listener(porta: int) -> tuple[bool, str]:
    prova = subprocess.run(
        [str(LSOF), "-nP", f"-iTCP:{porta}", "-sTCP:LISTEN", "-t"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    return prova.returncode == 1 and not prova.stdout.strip(), prova.stdout + prova.stderr


def encerra(proc: subprocess.Popen[bytes], porta: int) -> tuple[bool, str]:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    livre, detalhe = sem_listener(porta)
    return proc.poll() is not None and livre, detalhe


def sobe(
    servidor: Path,
    porta: int,
    sala: Path,
    home: Path,
    log: Path,
    *,
    escrever: bool,
) -> tuple[subprocess.Popen[bytes], str]:
    comando = [sys.executable, str(servidor), "--porta", str(porta)]
    if escrever:
        comando.extend(("--escrever", "--papel", "codex"))
    with log.open("wb") as saida:
        proc = subprocess.Popen(
            comando,
            env=ambiente(sala, home),
            stdout=saida,
            stderr=subprocess.STDOUT,
        )

    token = ""
    pronto = False
    for _ in range(80):
        if proc.poll() is not None:
            break
        texto = log.read_text(encoding="utf-8", errors="replace")
        achado = re.search(r"\?t=([A-Za-z0-9_-]+)", texto)
        if achado:
            token = achado.group(1)
        if escrever and not token:
            time.sleep(0.1)
            continue
        try:
            # A sonda não usa /api/estado porque o controle negativo quebra
            # justamente essa rota; prontidão e conformidade são perguntas distintas.
            status, _, _ = pede(porta, "/api/sala", token if escrever else None)
            if status == 200:
                pronto = True
                break
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.1)
    if not pronto:
        encerra(proc, porta)
        raise RuntimeError(f"servidor não ficou pronto; log={log.read_text(errors='replace')}")
    return proc, token


def suite(servidor: Path, porta: int, sala: Path, home: Path, log: Path) -> dict:
    proc, token = sobe(servidor, porta, sala, home, log, escrever=True)
    resultado: dict[str, object] = {}
    try:
        raiz = pede(porta, "/", token)
        estado = pede(porta, "/api/estado", token)
        sala_resp = pede(porta, "/api/sala", token)
        inexistente = pede(porta, "/rota-inexistente", token)
        sem_token = pede(porta, "/api/estado", None)
        token_errado = pede(porta, "/api/estado", "token-errado")

        corpo_curto = json.dumps(
            {"de": "claude", "texto": POST_CURTO, "para": ["claude"]},
            ensure_ascii=False,
        ).encode()
        post_valido = pede(
            porta,
            "/api/post",
            token,
            metodo="POST",
            dados=corpo_curto,
            headers={"Content-Type": "application/json"},
        )
        sala_depois = json.loads(pede(porta, "/api/sala", token)[2])
        identidade = any(
            m.get("texto") == POST_CURTO and m.get("de") == "codex"
            for m in sala_depois.get("msgs", [])
        )

        origem_hostil = pede(
            porta,
            "/api/post",
            token,
            metodo="POST",
            dados=corpo_curto,
            headers={"Content-Type": "application/json", "Origin": "http://evil.invalid"},
        )
        sem_texto = pede(
            porta,
            "/api/post",
            token,
            metodo="POST",
            dados=b"{}",
            headers={"Content-Type": "application/json"},
        )
        grande = json.dumps({"texto": "x" * 262200, "para": ["claude"]}).encode()
        corpo_grande = pede(
            porta,
            "/api/post",
            token,
            metodo="POST",
            dados=grande,
            headers={"Content-Type": "application/json"},
        )
        exportar = pede(porta, "/export", token)
        css = pede(porta, "/estilo.css", token)
        sem_tamanho = post_sem_content_length(porta, token)

        sala_json = json.loads(sala_resp[2])
        estado_json = json.loads(estado[2])
        resultado = {
            "raiz": raiz[0],
            "estado": estado[0],
            "sala": sala_resp[0],
            "historico": any(m.get("texto") == HISTORICO for m in sala_json.get("msgs", [])),
            "ultima": int(estado_json.get("ultima", 0)) >= 1,
            "inexistente": inexistente[0],
            "sem_token": sem_token[0],
            "token_errado": token_errado[0],
            "post_valido": post_valido[0],
            "identidade_servidor": identidade,
            "origem_hostil": origem_hostil[0],
            "campos_sala": sorted(sala_json.get("sala", {}).keys()),
            "sem_texto": sem_texto[0],
            "corpo_grande": corpo_grande[0],
            "export": exportar[0],
            "estilo_css": css[0],
            "sem_content_length": sem_tamanho,
        }
    finally:
        rescaldo, detalhe = encerra(proc, porta)
        resultado["rescaldo"] = rescaldo
        resultado["detalhe_rescaldo"] = detalhe
    return resultado


def essenciais(resultado: dict) -> dict:
    chaves = (
        "raiz",
        "estado",
        "sala",
        "historico",
        "ultima",
        "inexistente",
        "sem_token",
        "token_errado",
        "post_valido",
        "identidade_servidor",
        "origem_hostil",
        "rescaldo",
    )
    return {chave: resultado.get(chave) for chave in chaves}


def main() -> int:
    print("teste_coerencia_servidores")
    checa("núcleo disponível", (CORE_BIN / "iachat_core.py").is_file())
    checa("lsof disponível", LSOF.is_file())
    if not (CORE_BIN / "iachat_core.py").is_file() or not LSOF.is_file():
        print(f"\n{_ok} ✔  {_falhou} ✗")
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="iachat-coerencia-"))
    proxima = 59940
    try:
        # Gate negativo deliberado: remove somente a rota estado numa cópia do servidor UI.
        ui_quebrada = tmp / "ui-quebrada"
        shutil.copytree(RAIZ / "ui", ui_quebrada,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        servidor_quebrado = ui_quebrada / "servir.py"
        original = servidor_quebrado.read_bytes()
        texto = original.decode()
        agulha = 'if u.path == "/api/estado":'
        checa("ponto da mutação negativa existe", agulha in texto)
        servidor_quebrado.write_text(texto.replace(
            agulha, 'if False and u.path == "/api/estado":', 1), encoding="utf-8")
        sala_neg, home_neg = tmp / "sala-neg", tmp / "home-neg"
        preparo_neg = prepara_historico(sala_neg, home_neg)
        checa("histórico do controle negativo preparado", preparo_neg.returncode == 0,
              preparo_neg.stdout + preparo_neg.stderr)
        porta = porta_livre(proxima)
        proxima = porta + 1
        proc_neg, _ = sobe(
            servidor_quebrado, porta, sala_neg, home_neg, tmp / "neg.log", escrever=False
        )
        try:
            estado_neg = pede(porta, "/api/estado", None)[0]
        finally:
            rescaldo_neg, detalhe_neg = encerra(proc_neg, porta)
        checa("controle negativo: rota estado removida devolve 404", estado_neg == 404,
              f"status={estado_neg}")
        checa("controle negativo sem listener órfão", rescaldo_neg, detalhe_neg)
        servidor_quebrado.write_bytes(original)
        checa("servidor temporário foi restaurado byte a byte",
              servidor_quebrado.read_bytes() == original)

        resultados: dict[str, dict] = {}
        for nome, servidor in SERVIDORES.items():
            sala, home = tmp / f"sala-{nome}", tmp / f"home-{nome}"
            preparo = prepara_historico(sala, home)
            checa(f"{nome}: histórico pré-existente preparado", preparo.returncode == 0,
                  preparo.stdout + preparo.stderr)
            porta = porta_livre(proxima)
            proxima = porta + 1
            try:
                resultados[nome] = suite(
                    servidor, porta, sala, home, tmp / f"{nome}.log"
                )
            except Exception as exc:  # Falha de instrumento precisa aparecer como vermelho.
                resultados[nome] = {"erro": f"{type(exc).__name__}: {exc}"}
                checa(f"{nome}: suite executável", False, resultados[nome]["erro"])

        if set(resultados) == {"ui", "bundle"} and not any(
            "erro" in resultado for resultado in resultados.values()
        ):
            ui, bundle = resultados["ui"], resultados["bundle"]
            esperado_essencial = {
                "raiz": 200,
                "estado": 200,
                "sala": 200,
                "historico": True,
                "ultima": True,
                "inexistente": 404,
                "sem_token": 401,
                "token_errado": 401,
                "post_valido": 200,
                "identidade_servidor": True,
                "origem_hostil": 403,
                "rescaldo": True,
            }
            checa("ui cumpre o contrato essencial", essenciais(ui) == esperado_essencial,
                  json.dumps(essenciais(ui), ensure_ascii=False))
            checa("bundle cumpre o contrato essencial", essenciais(bundle) == esperado_essencial,
                  json.dumps(essenciais(bundle), ensure_ascii=False))
            checa("os dois servidores concordam no essencial",
                  essenciais(ui) == essenciais(bundle),
                  json.dumps({"ui": essenciais(ui), "bundle": essenciais(bundle)},
                             ensure_ascii=False))

            print("\n  dívidas medidas (não escondidas pelo PASS essencial):")
            print("  cenário                    ui  bundle")
            for chave in ("corpo_grande", "export", "estilo_css", "sem_texto",
                          "sem_content_length"):
                print(f"  {chave:<26} {str(ui[chave]):>3} {str(bundle[chave]):>7}")
            print(f"  {'campos_sala':<26} {ui['campos_sala']} | {bundle['campos_sala']}")

            divergencias_status = {
                chave for chave in ("corpo_grande", "export", "estilo_css", "sem_texto",
                                     "sem_content_length")
                if ui[chave] != bundle[chave]
            }
            permitidas = {
                "corpo_grande", "export", "estilo_css", "sem_texto", "sem_content_length"
            }
            checa("toda divergência não essencial está catalogada",
                  divergencias_status <= permitidas,
                  str(sorted(divergencias_status - permitidas)))

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{_ok} ✔  {_falhou} ✗")
    return 1 if _falhou else 0


if __name__ == "__main__":
    raise SystemExit(main())
