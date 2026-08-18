#!/usr/bin/env python3
"""Prova que montar.sh sincroniza seus cinco arquivos sem apagar os demais."""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PARES = (
    ("marca/icone.icns", "ia-chat.app/Contents/Resources/icone.icns"),
    ("ui/index.html", "ia-chat.app/Contents/Resources/ui/index.html"),
    ("ui/estilo.css", "ia-chat.app/Contents/Resources/ui/estilo.css"),
    ("ui/sala.js", "ia-chat.app/Contents/Resources/ui/sala.js"),
    ("ui/servir.py", "ia-chat.app/Contents/Resources/ui/servir.py"),
)

_ok = 0
_falhou = 0


def checa(nome: str, cond: bool, detalhe: str = "") -> None:
    """Mantém o formato binário dos testes da casa."""
    global _ok, _falhou
    if cond:
        _ok += 1
        print(f"  ✔ {nome}")
    else:
        _falhou += 1
        print(f"  ✗ {nome}" + (f"\n      {detalhe}" if detalhe else ""))


def sha256(caminho: Path) -> str:
    """Calcula o conteúdo real, sem confiar em data ou tamanho."""
    h = hashlib.sha256()
    with caminho.open("rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


def divergencias(raiz: Path) -> list[str]:
    """Lista pares fonte/bundle ausentes ou com bytes diferentes."""
    erros: list[str] = []
    for fonte_rel, bundle_rel in PARES:
        fonte, bundle = raiz / fonte_rel, raiz / bundle_rel
        if not fonte.is_file() or not bundle.is_file():
            erros.append(f"ausente: {fonte_rel} ou {bundle_rel}")
        elif sha256(fonte) != sha256(bundle):
            erros.append(f"hash diferente: {fonte_rel} != {bundle_rel}")
    return erros


def modo_validar(raiz: Path) -> int:
    """Modo filho: fornece um gate que pode ser observado vermelho e verde."""
    erros = divergencias(raiz)
    if erros:
        print("  ✗ sincronização por SHA-256")
        for erro in erros:
            print(f"      {erro}")
        return 1
    print("  ✔ sincronização por SHA-256")
    return 0


def roda_validador(raiz: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--validar", str(raiz)],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def main() -> int:
    global _ok, _falhou
    print("teste_montagem")
    tmp = Path(tempfile.mkdtemp(prefix="iachat-montagem-"))
    copia = tmp / "repo"
    try:
        shutil.copytree(
            RAIZ,
            copia,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
        )

        # Arquivos sem dono no montar.sh: um dentro de ui/ e outro em Resources/.
        sentinela_ui = copia / "ia-chat.app/Contents/Resources/ui/nao-apagar.txt"
        sentinela_res = copia / "ia-chat.app/Contents/Resources/nao-apagar.dat"
        sentinela_ui.write_text("preservar-ui\n", encoding="utf-8")
        sentinela_res.write_bytes(b"preservar-resources\n")

        # Cria drift apenas nas fontes da cópia. O gate precisa ficar vermelho.
        for indice, (fonte_rel, _) in enumerate(PARES, start=1):
            with (copia / fonte_rel).open("ab") as f:
                f.write(f"\ncontrole-negativo-{indice}\n".encode())
        vermelho = roda_validador(copia)
        checa(
            "controle negativo: divergência deliberada faz o gate sair 1",
            vermelho.returncode == 1 and "✗ sincronização" in vermelho.stdout,
            f"rc={vermelho.returncode}; saída={vermelho.stdout!r}",
        )

        montagem = subprocess.run(
            ["/bin/bash", str(copia / "montar.sh")],
            cwd=copia,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        checa(
            "montar.sh termina com exit 0 na cópia temporária",
            montagem.returncode == 0,
            montagem.stdout + montagem.stderr,
        )

        verde = roda_validador(copia)
        checa(
            "os cinco pares ficam idênticos por SHA-256",
            verde.returncode == 0 and "✔ sincronização" in verde.stdout,
            f"rc={verde.returncode}; saída={verde.stdout!r}",
        )
        checa(
            "montar.sh não apaga arquivo alheio dentro de Resources/ui",
            sentinela_ui.read_text(encoding="utf-8") == "preservar-ui\n",
        )
        checa(
            "montar.sh não apaga arquivo alheio dentro de Resources",
            sentinela_res.read_bytes() == b"preservar-resources\n",
        )

        # Quebra agora o destino, observa novo vermelho e usa o próprio montar para desfazer.
        alvo_quebrado = copia / PARES[1][1]
        alvo_quebrado.write_text("bundle quebrado de propósito\n", encoding="utf-8")
        segundo_vermelho = roda_validador(copia)
        checa(
            "controle negativo pós-montagem também é detectado",
            segundo_vermelho.returncode == 1,
            segundo_vermelho.stdout,
        )
        restauracao = subprocess.run(
            ["/bin/bash", str(copia / "montar.sh")],
            cwd=copia,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        restaurado = roda_validador(copia)
        checa(
            "a quebra foi desfeita e o mesmo gate voltou a exit 0",
            restauracao.returncode == 0 and restaurado.returncode == 0,
            restauracao.stdout + restauracao.stderr + restaurado.stdout,
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{_ok} ✔  {_falhou} ✗")
    return 1 if _falhou else 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--validar":
        raise SystemExit(modo_validar(Path(sys.argv[2]).resolve()))
    raise SystemExit(main())
