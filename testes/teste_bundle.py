#!/usr/bin/env python3
"""Valida completude e coerência interna do bundle macOS após montar.sh."""
from __future__ import annotations

import hashlib
import os
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile
from xml.parsers.expat import ExpatError
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
UI = ("index.html", "estilo.css", "sala.js", "servir.py")
CHAVES_TEXTO = (
    "CFBundleName",
    "CFBundleIdentifier",
    "CFBundleExecutable",
    "CFBundleIconFile",
    "CFBundlePackageType",
    "CFBundleInfoDictionaryVersion",
    "CFBundleShortVersionString",
    "CFBundleVersion",
)

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


def sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with caminho.open("rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


def problemas(raiz: Path) -> list[str]:
    """Retorna todos os problemas; lista vazia é o único PASS possível."""
    erros: list[str] = []
    contents = raiz / "ia-chat.app/Contents"
    plist = contents / "Info.plist"
    dados: dict = {}
    try:
        with plist.open("rb") as f:
            lido = plistlib.load(f)
        if not isinstance(lido, dict):
            erros.append("Info.plist não contém um dicionário")
        else:
            dados = lido
    except (OSError, plistlib.InvalidFileException, ValueError, TypeError, ExpatError) as exc:
        erros.append(f"Info.plist ilegível: {type(exc).__name__}: {exc}")

    for chave in CHAVES_TEXTO:
        if not isinstance(dados.get(chave), str) or not dados.get(chave, "").strip():
            erros.append(f"Info.plist sem texto válido em {chave}")
    if dados.get("CFBundlePackageType") != "APPL":
        erros.append("CFBundlePackageType precisa ser APPL")

    executavel_nome = dados.get("CFBundleExecutable", "")
    executavel = contents / "MacOS" / executavel_nome
    if not executavel.is_file():
        erros.append(f"executável declarado ausente: MacOS/{executavel_nome}")
    elif not os.access(executavel, os.X_OK):
        erros.append(f"executável sem bit +x: MacOS/{executavel_nome}")

    icone_nome = dados.get("CFBundleIconFile", "")
    if icone_nome and not Path(icone_nome).suffix:
        icone_nome += ".icns"
    icone = contents / "Resources" / icone_nome
    if not icone.is_file():
        erros.append(f"ícone declarado ausente: Resources/{icone_nome}")
    elif icone.stat().st_size < 8 or icone.read_bytes()[:4] != b"icns":
        erros.append(f"ícone inválido: Resources/{icone_nome}")

    pkginfo = contents / "PkgInfo"
    if not pkginfo.is_file() or pkginfo.read_bytes() != b"APPL????":
        erros.append("PkgInfo ausente ou diferente de APPL????")

    for nome in UI:
        fonte = raiz / "ui" / nome
        interno = contents / "Resources" / "ui" / nome
        if not fonte.is_file() or not interno.is_file():
            erros.append(f"UI ausente: ui/{nome} ou Resources/ui/{nome}")
        elif sha256(fonte) != sha256(interno):
            erros.append(f"UI divergente por SHA-256: {nome}")
    return erros


def modo_validar(raiz: Path) -> int:
    erros = problemas(raiz)
    if erros:
        print("  ✗ bundle completo e coerente")
        for erro in erros:
            print(f"      {erro}")
        return 1
    print("  ✔ bundle completo e coerente")
    return 0


def valida_filho(raiz: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--validar", str(raiz)],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def main() -> int:
    print("teste_bundle")
    tmp = Path(tempfile.mkdtemp(prefix="iachat-bundle-"))
    copia = tmp / "repo"
    try:
        shutil.copytree(
            RAIZ,
            copia,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
        )
        montagem = subprocess.run(
            ["/bin/bash", str(copia / "montar.sh")],
            cwd=copia,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        checa("montar.sh prepara a cópia", montagem.returncode == 0,
              montagem.stdout + montagem.stderr)

        contents = copia / "ia-chat.app/Contents"
        plist = contents / "Info.plist"
        plist_original = plist.read_bytes()
        plist.write_bytes(b"<plist><dict>quebrado")
        vermelho_plist = valida_filho(copia)
        checa(
            "controle negativo: plist ilegível reprova",
            vermelho_plist.returncode == 1 and "Info.plist ilegível" in vermelho_plist.stdout,
            vermelho_plist.stdout + vermelho_plist.stderr,
        )
        plist.write_bytes(plist_original)

        executavel = contents / "MacOS/ia-chat"
        modo_original = stat.S_IMODE(executavel.stat().st_mode)
        executavel.chmod(modo_original & ~0o111)
        vermelho_exec = valida_filho(copia)
        checa(
            "controle negativo: executável sem +x reprova",
            vermelho_exec.returncode == 1 and "sem bit +x" in vermelho_exec.stdout,
            vermelho_exec.stdout,
        )
        executavel.chmod(modo_original)

        icone = contents / "Resources/icone.icns"
        icone_original = icone.read_bytes()
        icone.write_bytes(b"nao-e-icns")
        vermelho_icone = valida_filho(copia)
        checa(
            "controle negativo: ícone inválido reprova",
            vermelho_icone.returncode == 1 and "ícone inválido" in vermelho_icone.stdout,
            vermelho_icone.stdout,
        )
        icone.write_bytes(icone_original)

        ui_interna = contents / "Resources/ui/sala.js"
        ui_interna.write_text("quebrado de propósito\n", encoding="utf-8")
        vermelho_ui = valida_filho(copia)
        checa(
            "controle negativo: UI divergente reprova",
            vermelho_ui.returncode == 1 and "UI divergente" in vermelho_ui.stdout,
            vermelho_ui.stdout,
        )

        restauracao = subprocess.run(
            ["/bin/bash", str(copia / "montar.sh")],
            cwd=copia,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        verde = valida_filho(copia)
        checa(
            "todas as quebras foram desfeitas",
            plist.read_bytes() == plist_original
            and stat.S_IMODE(executavel.stat().st_mode) == modo_original
            and icone.read_bytes() == icone_original
            and restauracao.returncode == 0,
            restauracao.stdout + restauracao.stderr,
        )
        checa(
            "bundle completo e coerente volta a exit 0",
            verde.returncode == 0 and "✔ bundle completo" in verde.stdout,
            verde.stdout,
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{_ok} ✔  {_falhou} ✗")
    return 1 if _falhou else 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--validar":
        raise SystemExit(modo_validar(Path(sys.argv[2]).resolve()))
    raise SystemExit(main())
