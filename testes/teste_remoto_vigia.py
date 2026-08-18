#!/usr/bin/env python3
"""A vigia do túnel não pode derrubar um túnel que está funcionando.

O túnel gratuito do Cloudflare cai sozinho e volta com OUTRO endereço. Se ele
está na rua quando isso acontece, perde a sala — e o endereço novo só existe
num log da máquina dele.

A vigia resolve metade: ressuscita. Mas ela carrega um risco maior que o
problema, e é esse risco que este arquivo trava: **uma vigia que reinicia por
precaução troca o endereço que ele está usando NAQUELE momento**. O remédio
mataria o paciente. Por isso a regra é: só age quando o túnel comprovadamente
não responde — e a prova é de FORA, pelo próprio endereço, nunca pelo pid.

O que este teste NÃO faz: não sobe túnel de verdade (isso publica coisa na
internet e depende de rede). Ele exercita as funções do script em isolamento e
lê o fluxo. O que não dá para provar aqui está dito no fim, em vez de fingido.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "abrir-remoto.sh"
TEXTO = SCRIPT.read_text(encoding="utf-8")

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


def bloco_vigia() -> str:
    """O trecho entre `--vigiar` e o `--parar` — o caminho que roda na vigia."""
    i = TEXTO.index('if [ "${1:-}" = "--vigiar" ]')
    j = TEXTO.index('if [ "${1:-}" = "--parar" ]', i)
    return TEXTO[i:j]


def roda(script: str) -> str:
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    return (r.stdout + r.stderr).strip()


def main() -> int:
    print("— o script continua válido —")
    r = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    checa("sintaxe do abrir-remoto.sh", r.returncode == 0, r.stderr[:200])
    checa("o modo --vigiar existe", '"--vigiar"' in TEXTO)
    checa("o modo --parar continua existindo", '"--parar"' in TEXTO,
          "a vigia não pode ter engolido o jeito de desligar")

    print("— a vigia não derruba quem está de pé —")
    vigia = bloco_vigia()
    # O `--parar` tem pkill, e deve ter. A VIGIA não pode ter: derrubar um túnel
    # que responde troca o endereço que ele está usando naquele instante.
    checa("o caminho da vigia não contém pkill",
          "pkill" not in vigia,
          "reiniciar por precaução troca o endereço em uso — o remédio mataria o paciente")
    checa("a vigia só age depois de checar",
          re.search(r"if\s+responde\b[\s\S]{0,120}continue", vigia) is not None,
          "sem o `continue` no caminho saudável, ela agiria a cada volta")
    checa("a prova é de fora, pelo endereço",
          "curl" in TEXTO and "%{http_code}" in TEXTO,
          "pid vivo não prova que responde — é a bronca do instrumento que mente")
    checa("a vigia não confia só no pid",
          "tunel_vivo" not in vigia or "responde" in vigia,
          "se ela decidir por pgrep, um túnel zumbi passa por saudável")

    print("— a vigia tem freio: sem ele, o remédio mata o paciente —")
    # 18/08: a vigia rodou 6 vezes em 6 minutos. Como cada tentativa MATA o servidor para
    # subir outro, ela derrubava um servidor bom a cada volta, e o dono não conseguia
    # abrir o link. O gate original provava que ela não derruba quem RESPONDE — não
    # provava o que acontece quando ninguém responde e ela insiste para sempre.
    checa("existe teto de quedas seguidas", "TETO_QUEDAS" in vigia or "TETO_QUEDAS" in TEXTO,
          "sem teto, ela tenta para sempre e derruba servidor bom a cada volta")
    checa("a vigia PARA ao estourar o teto",
          re.search(r"quedas.*-gt.*TETO_QUEDAS[\s\S]{0,400}exit 1", vigia) is not None,
          "avisar e sair é melhor que insistir num remédio que não cura")
    checa("há recuo entre tentativas",
          re.search(r"espera=.*INTERVALO\s*\*\s*quedas", vigia) is not None,
          "tentar sempre no mesmo intervalo é martelar")
    # ⚠️ A medida certa é o zeramento DEPOIS de levantar, não em qualquer lugar: a
    # inicialização antes do laço também é `quedas=0`, e com ela o gate passava verde
    # mesmo sem o zeramento que importa. Descobri removendo a linha e vendo passar.
    depois_de_levantar = vigia.split('"$0"', 1)[-1] if '"$0"' in vigia else ""
    checa("o contador zera DEPOIS de levantar com sucesso",
          re.search(r"^\s*quedas=0", depois_de_levantar, re.M) is not None,
          "senão uma queda isolada por hora soma até o teto e a vigia desiste sem motivo")

    print("— o endereço fica onde dá para achar —")
    checa("existe arquivo de link", "LINK=" in TEXTO and "registra_link" in TEXTO)
    checa("o link é registrado ao subir", TEXTO.count("registra_link") >= 2,
          "definir a função e não chamá-la é pior que não ter")
    checa("quando o endereço muda, a sala é avisada",
          "iachat" in vigia and "post" in vigia,
          "a sala é o único canal que sobrevive à troca de endereço")
    checa("a limitação está declarada, não escondida",
          "conta Cloudflare" in TEXTO or "túnel nomeado" in TEXTO,
          "endereço fixo exige conta; fingir que a vigia resolve tudo seria mentira")

    print("— as funções, em isolamento —")
    with tempfile.TemporaryDirectory() as d:
        tun, srv = Path(d) / "t.log", Path(d) / "s.log"
        tun.write_text("INF |  https://alpha-beta-gama.trycloudflare.com  |\n"
                       "INF |  https://segundo-endereco.trycloudflare.com  |\n", encoding="utf-8")
        srv.write_text("no ar http://127.0.0.1:8899/?t=PRIMEIRO\n"
                       "no ar http://127.0.0.1:8899/?t=SEGUNDO\n", encoding="utf-8")
        base = f'LOG_TUN="{tun}"; LOG_SRV="{srv}"; PORTA=8899\n'
        # as funções vêm do arquivo, não reescritas aqui
        for fn in ("url_do_log", "token_do_log"):
            m = re.search(rf"^{fn}\(\).*$", TEXTO, re.M)
            base += m.group(0) + "\n"
        saida = roda(base + 'echo "$(url_do_log)|$(token_do_log)"')
        checa("pega o ÚLTIMO endereço do log, não o primeiro",
              saida.startswith("https://segundo-endereco."),
              f"veio: {saida} — depois de uma queda, o endereço certo é o mais recente")
        checa("pega o ÚLTIMO token", saida.endswith("|SEGUNDO"), f"veio: {saida}")

        vazio = roda(f'LOG_TUN="{d}/nao-existe.log"; LOG_SRV="{d}/nao-existe.log"; PORTA=8899\n'
                     + re.search(r"^url_do_log\(\).*$", TEXTO, re.M).group(0)
                     + '\necho "[$(url_do_log)]"')
        checa("log ausente devolve vazio, não erro", vazio == "[]", f"veio: {vazio}")

    print("\n  NÃO CONFERIDO: túnel real de ponta a ponta (publicaria a sala na internet")
    print("  e depende de rede). A queda-e-volta com endereço novo foi exercitada só")
    print("  pelas funções, não contra o Cloudflare.")
    print(f"\n{_ok} ✔  {_falhou} ✗")
    return 1 if _falhou else 0


if __name__ == "__main__":
    raise SystemExit(main())
