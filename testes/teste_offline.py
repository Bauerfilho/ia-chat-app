#!/usr/bin/env python3
"""Prova que a interface não carrega fonte, CSS ou script pela rede."""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVOS = ("index.html", "estilo.css", "sala.js")
REMOTO = re.compile(r"(?i)^\s*(?:https?://|//)")

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


class AuditorHTML(HTMLParser):
    """Examina atributos que fazem o navegador buscar recursos."""

    ATRIBUTOS_REDE = {"action", "data", "formaction", "href", "poster", "src"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.erros: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for nome, valor in attrs:
            valor = valor or ""
            if nome.lower() in self.ATRIBUTOS_REDE and REMOTO.search(valor):
                self.erros.append(f"<{tag}> {nome} remoto: {valor}")
            if nome.lower() == "srcset":
                for candidato in valor.split(","):
                    if REMOTO.search(candidato.strip().split()[0]):
                        self.erros.append(f"<{tag}> srcset remoto: {candidato.strip()}")
            if nome.lower() == "style" and re.search(
                r"(?i)url\(\s*['\"]?\s*(?:https?://|//)", valor
            ):
                self.erros.append(f"<{tag}> style remoto")


def sem_comentarios_css(texto: str) -> str:
    return re.sub(r"/\*.*?\*/", "", texto, flags=re.DOTALL)


def problemas(ui: Path) -> list[str]:
    erros: list[str] = []
    textos: dict[str, str] = {}
    for nome in ARQUIVOS:
        caminho = ui / nome
        if not caminho.is_file():
            erros.append(f"arquivo ausente: {nome}")
            continue
        textos[nome] = caminho.read_text(encoding="utf-8")

    html = textos.get("index.html", "")
    auditor = AuditorHTML()
    try:
        auditor.feed(html)
        auditor.close()
    except Exception as exc:  # HTML inválido também não pode ganhar PASS silencioso.
        erros.append(f"HTML não analisável: {type(exc).__name__}: {exc}")
    erros.extend(auditor.erros)
    if re.search(r"(?i)@import\b", html):
        erros.append("index.html contém @import")
    if re.search(r"(?i)url\(\s*['\"]?\s*(?:https?://|//)", html):
        erros.append("index.html contém url() remoto")

    css = sem_comentarios_css(textos.get("estilo.css", ""))
    if re.search(r"(?i)@import\b", css):
        erros.append("estilo.css contém @import")
    if re.search(r"(?i)https?://", css):
        erros.append("estilo.css contém http(s)://")
    if re.search(r"(?i)url\(\s*['\"]?\s*//", css):
        erros.append("estilo.css contém url(//...)")

    js = textos.get("sala.js", "")
    if re.search(r"(?i)https?://", js):
        erros.append("sala.js contém http(s)://")
    if re.search(r"['\"`]\s*//[A-Za-z0-9]", js):
        erros.append("sala.js contém URL protocol-relative")
    return erros


def modo_validar(ui: Path) -> int:
    erros = problemas(ui)
    if erros:
        print("  ✗ interface independente de rede")
        for erro in erros:
            print(f"      {erro}")
        return 1
    print("  ✔ interface independente de rede")
    return 0


def valida_filho(ui: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--validar", str(ui)],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def main() -> int:
    print("teste_offline")
    tmp = Path(tempfile.mkdtemp(prefix="iachat-offline-"))
    ui = tmp / "ui"
    try:
        shutil.copytree(RAIZ / "ui", ui, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        originais = {nome: (ui / nome).read_bytes() for nome in ARQUIVOS}

        with (ui / "index.html").open("a", encoding="utf-8") as f:
            f.write('\n<link rel="stylesheet" href="//cdn.invalid/remoto.css">\n')
        with (ui / "estilo.css").open("a", encoding="utf-8") as f:
            f.write('\n@import url("https://cdn.invalid/fonte.css");\n')
        with (ui / "sala.js").open("a", encoding="utf-8") as f:
            f.write('\nfetch("http://cdn.invalid/dados.json");\n')

        vermelho = valida_filho(ui)
        checa(
            "controle negativo: três dependências remotas fazem o gate sair 1",
            vermelho.returncode == 1
            and "<link> href remoto" in vermelho.stdout
            and "estilo.css contém @import" in vermelho.stdout
            and "sala.js contém http(s)://" in vermelho.stdout,
            vermelho.stdout + vermelho.stderr,
        )

        for nome, conteudo in originais.items():
            (ui / nome).write_bytes(conteudo)
        checa(
            "as três quebras foram desfeitas byte a byte",
            all((ui / nome).read_bytes() == conteudo for nome, conteudo in originais.items()),
        )

        verde = valida_filho(ui)
        checa(
            "index.html, estilo.css e sala.js passam sem rede",
            verde.returncode == 0 and "✔ interface independente" in verde.stdout,
            verde.stdout + verde.stderr,
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{_ok} ✔  {_falhou} ✗")
    return 1 if _falhou else 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--validar":
        raise SystemExit(modo_validar(Path(sys.argv[2]).resolve()))
    raise SystemExit(main())
