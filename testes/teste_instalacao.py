#!/usr/bin/env python3
"""Executa instalar-app.sh confinado a uma cópia e a IA_CHAT_DEST temporário."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SANDBOX = Path("/usr/bin/sandbox-exec")
LSREGISTER = Path(
    "/System/Library/Frameworks/CoreServices.framework/Frameworks/"
    "LaunchServices.framework/Support/lsregister"
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


def inventario(raiz: Path) -> dict[str, str]:
    """Compara conteúdo de árvore; mtimes não são prova de alteração material."""
    return {
        str(p.relative_to(raiz)): sha256(p)
        for p in sorted(raiz.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    }


def escapa_perfil(caminho: Path) -> str:
    return str(caminho.resolve()).replace("\\", "\\\\").replace('"', '\\"')


def perfil_sandbox(repo: Path, destino: Path) -> str:
    """Permite leitura/execução, mas escrita só no repo-cópia e no destino."""
    repo_s = escapa_perfil(repo)
    destino_s = escapa_perfil(destino)
    lsreg_s = escapa_perfil(LSREGISTER)
    return (
        '(version 1)\n'
        '(allow default)\n'
        '(deny file-write*)\n'
        f'(allow file-write* (subpath "{repo_s}"))\n'
        f'(allow file-write* (subpath "{destino_s}"))\n'
        '(allow file-write* (literal "/dev/null"))\n'
        f'(deny process-exec (literal "{lsreg_s}"))\n'
    )


def ambiente(repo: Path, destino: Path, fora: Path) -> dict[str, str]:
    amb = dict(os.environ)
    amb.update(
        HOME=str(fora / "home-proibida"),
        IA_CHAT_DEST=str(destino),
        IA_CHAT_SRC=str(repo / ".fonte-ia-chat"),
        IACHAT_SCRIPTS=str(repo / ".scripts-inexistentes"),
        IACHAT_HOME=str(fora / "sala-proibida"),
        IACHAT_PAPEL="bauer",
    )
    return amb


def roda(script: Path, repo: Path, destino: Path, fora: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SANDBOX), "-p", perfil_sandbox(repo, destino), "/bin/bash", str(script)],
        cwd=repo,
        env=ambiente(repo, destino, fora),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def main() -> int:
    print("teste_instalacao")
    checa("sandbox-exec do macOS está disponível", SANDBOX.is_file())
    if not SANDBOX.is_file():
        print(f"\n{_ok} ✔  {_falhou} ✗")
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="iachat-instalacao-")).resolve()
    repo = tmp / "repo"
    destino = tmp / "destino"
    fora = tmp / "fora-do-repo-e-destino"
    try:
        shutil.copytree(
            RAIZ,
            repo,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
        )
        destino.mkdir()
        fora.mkdir()
        sentinela = fora / "sentinela.txt"
        sentinela.write_text("não tocar\n", encoding="utf-8")

        # Evita clone e rede: o instalador encontra exatamente o arquivo que procura.
        core = repo / ".fonte-ia-chat/bin/iachat_core.py"
        core.parent.mkdir(parents=True)
        core.write_text("# núcleo-sentinela do teste\n", encoding="utf-8")

        # Prova que o instrumento realmente bloqueia uma escrita fora das duas raízes.
        controle = subprocess.run(
            [str(SANDBOX), "-p", perfil_sandbox(repo, destino),
             "/usr/bin/touch", str(fora / "escape-do-controle")],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        checa(
            "controle negativo: escrita fora do repo/destino é negada",
            controle.returncode != 0 and not (fora / "escape-do-controle").exists(),
            f"rc={controle.returncode}; stderr={controle.stderr!r}",
        )

        # Adultera SOMENTE uma cópia adicional do instalador para fazê-lo escapar.
        quebrado = repo / "instalar-app-quebrado.sh"
        texto = (repo / "instalar-app.sh").read_text(encoding="utf-8")
        antigo = 'ALVO="$DEST/ia-chat.app"'
        novo = 'ALVO="${IA_CHAT_ESCAPE}/ia-chat.app"'
        checa("linha-alvo da mutação existe", antigo in texto)
        quebrado.write_text(texto.replace(antigo, novo, 1), encoding="utf-8")
        amb_quebrado = ambiente(repo, destino, fora)
        amb_quebrado["IA_CHAT_ESCAPE"] = str(fora)
        vermelho = subprocess.run(
            [str(SANDBOX), "-p", perfil_sandbox(repo, destino),
             "/bin/bash", str(quebrado)],
            cwd=repo,
            env=amb_quebrado,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        checa(
            "caso adulterado reprova sem criar app fora da fronteira",
            vermelho.returncode != 0 and not (fora / "ia-chat.app").exists(),
            f"rc={vermelho.returncode}; saída={vermelho.stdout + vermelho.stderr}",
        )
        quebrado.unlink()
        checa("a adulteração temporária foi removida", not quebrado.exists())

        antes_repo = inventario(repo)
        antes_fora = inventario(fora)
        execucao = roda(repo / "instalar-app.sh", repo, destino, fora)
        depois_repo = inventario(repo)
        depois_fora = inventario(fora)

        checa(
            "instalador real termina com exit 0 sob contenção",
            execucao.returncode == 0,
            f"rc={execucao.returncode}\n{execucao.stdout}{execucao.stderr}",
        )
        instalado = destino / "ia-chat.app"
        checa("app foi criado somente em IA_CHAT_DEST", instalado.is_dir())
        checa(
            "nenhum conteúdo do repo-cópia mudou durante a execução boa",
            antes_repo == depois_repo,
            f"antes={len(antes_repo)} arquivos; depois={len(depois_repo)} arquivos",
        )
        checa(
            "nada mudou fora do repo e de IA_CHAT_DEST",
            antes_fora == depois_fora == {"sentinela.txt": sha256(sentinela)},
            f"antes={antes_fora}; depois={depois_fora}",
        )
        checa(
            "bundle instalado é byte a byte igual ao bundle montado",
            inventario(instalado) == inventario(repo / "ia-chat.app"),
        )
        checa(
            "saída confirma o núcleo temporário e o destino explícito",
            str(core.parent) in execucao.stdout and str(instalado) in execucao.stdout,
            execucao.stdout,
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{_ok} ✔  {_falhou} ✗")
    return 1 if _falhou else 0


if __name__ == "__main__":
    raise SystemExit(main())
