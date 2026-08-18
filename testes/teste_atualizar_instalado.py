#!/usr/bin/env python3
"""`instalar-app.sh --atualizar` troca a interface de um app instalado sem reinstalar.

Isto existe por um defeito real, visto duas vezes em 18/08: o `/Applications/ia-chat.app`
estava com a interface de horas antes — sem o modo novo — enquanto o repositório já estava
publicado. Quem abre o app com dois cliques via a versão velha e **não tinha como saber**.

A instalação normal resolve, mas do jeito errado para este caso: ela faz `rm -rf` no bundle
antes de copiar, e o app costuma estar **aberto**. Apagar o bundle debaixo de um processo
vivo é receita de comportamento estranho para o dono, que está do outro lado da tela.

O que este teste trava:
  · atualizar copia a interface e deixa os arquivos idênticos por conteúdo;
  · atualizar **não** apaga o bundle nem toca no binário — o `rm -rf` não pode voltar aqui;
  · rodar duas vezes seguidas não faz trabalho à toa (a segunda diz "já estava sincronizado");
  · apontar para um app inexistente falha com mensagem, em vez de fingir sucesso.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SCRIPT = RAIZ / "instalar-app.sh"

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


def roda(destino: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ, IA_CHAT_DEST=str(destino))
    return subprocess.run(["bash", str(SCRIPT), "--atualizar"],
                          capture_output=True, text=True, env=env, cwd=str(RAIZ), timeout=120)


def main() -> int:
    print("— o script continua válido —")
    r = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    checa("sintaxe do instalar-app.sh", r.returncode == 0, r.stderr[:160])

    origem = RAIZ / "ia-chat.app" / "Contents" / "Resources" / "ui"
    if not origem.is_dir():
        print("  ! o bundle do repo não tem ui/ — rode ./montar.sh antes")
        return 2

    with tempfile.TemporaryDirectory() as d:
        destino = Path(d)
        alvo = destino / "ia-chat.app"
        (alvo / "Contents" / "Resources" / "ui").mkdir(parents=True)
        (alvo / "Contents" / "MacOS").mkdir(parents=True)
        binario = alvo / "Contents" / "MacOS" / "ia-chat"
        binario.write_text("#!/bin/sh\necho binário original\n", encoding="utf-8")
        marca_binario = binario.read_text(encoding="utf-8")
        # uma interface velha: mesmo nome, conteúdo diferente
        alvos = sorted(p.name for p in origem.iterdir() if p.is_file())
        for nome in alvos:
            (alvo / "Contents" / "Resources" / "ui" / nome).write_text("versão velha\n",
                                                                       encoding="utf-8")

        print("— atualizar troca a interface —")
        r = roda(destino)
        checa("sai com 0", r.returncode == 0, (r.stdout + r.stderr)[:200])
        iguais = all(
            (alvo / "Contents" / "Resources" / "ui" / n).read_bytes() == (origem / n).read_bytes()
            for n in alvos)
        checa("os arquivos ficam idênticos ao bundle do repo", iguais,
              "é exatamente a divergência que fez o dono abrir o app sem o modo novo")

        print("— e NÃO destrói o que estava lá —")
        checa("o bundle não foi apagado", alvo.is_dir())
        checa("o binário não foi tocado",
              binario.is_file() and binario.read_text(encoding="utf-8") == marca_binario,
              "o `rm -rf` da instalação normal não pode voltar por este caminho")

        print("— rodar de novo não inventa trabalho —")
        r2 = roda(destino)
        checa("a segunda vez diz que já estava sincronizado",
              "já estava sincronizado" in (r2.stdout + r2.stderr),
              f"veio: {(r2.stdout + r2.stderr).strip()[:120]}")

        print("— apontar para o vazio falha, não finge —")
        vazio = Path(d) / "sem-app"
        vazio.mkdir()
        r3 = roda(vazio)
        checa("recusa quando não há app instalado", r3.returncode != 0,
              "anunciar sucesso sobre nada é pior que falhar")
        checa("e a mensagem diz o que fazer",
              "não está instalado" in (r3.stdout + r3.stderr),
              f"veio: {(r3.stdout + r3.stderr).strip()[:120]}")

    print(f"\n{_ok} ✔  {_falhou} ✗")
    return 1 if _falhou else 0


if __name__ == "__main__":
    raise SystemExit(main())
