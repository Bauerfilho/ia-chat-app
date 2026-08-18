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


def extrai_funcao(nome: str, texto: str = TEXTO) -> str:
    """Corpo da função bash, com chaves internas equilibradas."""
    i = texto.index(f"{nome}() {{")
    k = texto.index("{", i)
    nivel, j = 0, k
    while j < len(texto):
        if texto[j] == "{":
            nivel += 1
        elif texto[j] == "}":
            nivel -= 1
            if nivel == 0:
                return texto[i:j + 1]
        j += 1
    raise RuntimeError(f"função {nome} sem fecha-chave")


def contrato_ponte(texto: str, pasta: Path) -> bool:
    """A ponte grava HTML com a URL viva + txt irmão, sem exigir iCloud.

    É o contrato das checagens NOVAS. Serve para o arquivo real passar e
    para a cópia adulterada reprovar — a mesma função nos dois lados.
    """
    fn = extrai_funcao("registra_link", texto)
    link = pasta / "link-remoto.txt"
    ponte = pasta / "ponte" / "sala.html"
    casa = pasta / "home-sem-icloud"
    casa.mkdir(parents=True, exist_ok=True)
    url, token = "https://novo-endereco.trycloudflare.com", "TOKENNOVO"
    script = (
        f'set +e\nLINK="{link}"\nIACHAT_PONTE_CELULAR="{ponte}"\n'
        f'HOME="{casa}"\n{fn}\nregistra_link "{url}" "{token}"\n'
    )
    roda(script)
    if not ponte.is_file():
        return False
    html = ponte.read_text(encoding="utf-8")
    txt = ponte.with_suffix(".txt")
    vivo = f"{url}/?t={token}"
    if vivo not in html:
        return False
    if 'http-equiv="refresh"' not in html and "http-equiv='refresh'" not in html:
        return False
    if f'href="{vivo}"' not in html and f"href='{vivo}'" not in html:
        return False
    if not txt.is_file() or vivo not in txt.read_text(encoding="utf-8"):
        return False
    if not link.is_file() or vivo not in link.read_text(encoding="utf-8"):
        return False
    return True


def ponte_na_vigia(texto: str) -> bool:
    """A vigia atualiza a ponte DEPOIS de levantar — senão o celular fica com o velho."""
    i = texto.index('if [ "${1:-}" = "--vigiar" ]')
    j = texto.index('if [ "${1:-}" = "--parar" ]', i)
    vigia = texto[i:j]
    depois = vigia.split('"$0"', 1)[-1] if '"$0"' in vigia else ""
    return "registra_link" in depois and "pkill" not in vigia


def ponte_atomica(texto: str) -> bool:
    """HTML e txt usam arquivo temporário irmão antes da troca final."""
    return (
        'tmp="$destino.tmp.$$"' in texto
        and 'mv -f "$tmp"' in texto
        and 'tmp_txt="$txt.tmp.$$"' in texto
        and 'mv -f "$tmp_txt" "$txt"' in texto
    )


def anuncio_ponte_honesto(texto: str) -> bool:
    """Vigia e stdout só indicam a ponte depois de uma gravação comprovada."""
    condicao = 'if [ -n "$PONTE_CELULAR_GRAVADA" ]; then'
    return (
        texto.count(condicao) >= 2
        and 'PONTE_CELULAR_GRAVADA="$destino"' in texto
        and "ponte móvel não criada" in texto
    )


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

    print("— a prova não pode depender do DNS desta máquina —")
    # 18/08: o resolvedor do sistema devolvia VAZIO para *.trycloudflare.com enquanto
    # 8.8.8.8 e 1.1.1.1 resolviam. O curl usa o do sistema, então a prova dizia "fora do
    # ar" sobre um túnel que respondia 200 para o mundo — e a vigia entrou em ciclo
    # tentando consertar o que não estava quebrado.
    resp = TEXTO[TEXTO.index("responde()"):TEXTO.index("responde()") + 1400]
    checa("a prova tem rota alternativa por IP",
          "--resolve" in resp,
          "sem isso, DNS local cego = falso 'fora do ar'")
    checa("resolve por DNS público quando o do sistema falha",
          "@1.1.1.1" in resp or "@8.8.8.8" in resp,
          "o resolvedor do sistema não pode ser a única fonte")
    checa("só declara queda quando as DUAS rotas falham",
          resp.count("return 0") >= 2 and "return 1" in resp,
          "uma rota falhando não é prova de queda")

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

    print("— o celular acha o endereço sem depender do hostname do túnel —")
    checa("existe override IACHAT_PONTE_CELULAR",
          "IACHAT_PONTE_CELULAR" in TEXTO,
          "sem override, o teste não isolaria a ponte do iCloud real")
    checa("o destino padrão é o iCloud Drive, se ele existir",
          "com~apple~CloudDocs" in TEXTO and "ia-chat/sala.html" in TEXTO,
          "o caminho fixo que o celular abre")
    checa("a ponte é HTML com refresh para a URL viva",
          'http-equiv="refresh"' in TEXTO or "http-equiv='refresh'" in TEXTO)
    checa("a escrita da ponte HTML+txt é atômica (tmp + mv)",
          ponte_atomica(TEXTO),
          "o celular não pode ler HTML ou txt pela metade no meio de um sync")
    checa("falha da ponte não derruba o túnel",
          TEXTO.count("|| return 0") >= 2,
          "mkdir/mv falhando não pode ser exit 1 com set -e")
    checa("a vigia atualiza a ponte depois de levantar",
          ponte_na_vigia(TEXTO),
          "sem isso, o filho escreve e a vigia esquece; o caminho tem que ser o mesmo")
    checa("a vigia ainda não tem pkill depois da ponte",
          "pkill" not in bloco_vigia(),
          "acrescentar a ponte não pode ter afrouxado o gate de não derrubar")
    checa("só anuncia a ponte móvel depois de gravá-la",
          anuncio_ponte_honesto(TEXTO),
          "falha macia não pode virar instrução falsa no stdout")
    checa("o post da troca usa o número da queda, não o zero",
          "queda_n=$quedas" in TEXTO and '"$queda_n"' in TEXTO,
          "quedas=0 rodava antes do printf — o aviso dizia queda 0")
    checa("não publica o link em serviço externo",
          all(s not in TEXTO for s in (
              "gist.github", "ntfy.sh", "pastebin", "duckdns",
              "tunnel login", "tunnel create")),
          "conta/publicação é recomendação, não implementação")

    print("— a ponte, em isolamento —")
    with tempfile.TemporaryDirectory() as d:
        pasta = Path(d)
        checa("registra_link grava HTML+txt+link com a URL viva",
              contrato_ponte(TEXTO, pasta / "bom"),
              "a mesma função que a isca vai derrubar")

        casa = pasta / "sem-icloud"
        casa.mkdir()
        link_sozinho = pasta / "so-link.txt"
        fn = extrai_funcao("registra_link")
        roda(
            f'set +e\nLINK="{link_sozinho}"\nunset IACHAT_PONTE_CELULAR\n'
            f'HOME="{casa}"\n{fn}\n'
            'registra_link "https://sozinho.trycloudflare.com" "ABC"\n'
        )
        checa("sem iCloud e sem override, o link local ainda é gravado",
              link_sozinho.is_file()
              and "https://sozinho.trycloudflare.com/?t=ABC" in link_sozinho.read_text(encoding="utf-8"),
              "a ponte é extra; o arquivo da máquina não pode sumir")
        checa("sem iCloud e sem override, não inventa HTML em HOME",
              not any(casa.rglob("*.html")),
              "não criar pasta ia-chat fora do Drive")

        dest_impossivel = pasta / "nao" / "posso" / "criar"
        dest_impossivel.parent.mkdir(parents=True)
        dest_impossivel.write_text("sou um arquivo, não um diretório\n", encoding="utf-8")
        link_macio = pasta / "macio.txt"
        ponte_impossivel = dest_impossivel / "sala.html"
        saida = roda(
            f'set +e\nLINK="{link_macio}"\nIACHAT_PONTE_CELULAR="{ponte_impossivel}"\n'
            f'HOME="{casa}"\n{fn}\n'
            'registra_link "https://macio.trycloudflare.com" "XYZ"; '
            'echo "RC:$? PONTE:[$PONTE_CELULAR_GRAVADA]"\n'
        )
        checa("ponte impossível não aborta o script",
              "RC:0" in saida and "PONTE:[]" in saida and link_macio.is_file(),
              f"veio: {saida}")

        pasta_troca = pasta / "troca"
        contrato_ponte(TEXTO, pasta_troca)
        # segundo registro: o caminho é o mesmo, o conteúdo é o novo
        fn = extrai_funcao("registra_link")
        link = pasta_troca / "link-remoto.txt"
        ponte = pasta_troca / "ponte" / "sala.html"
        roda(
            f'set +e\nLINK="{link}"\nIACHAT_PONTE_CELULAR="{ponte}"\n'
            f'HOME="{casa}"\n{fn}\n'
            'registra_link "https://depois.trycloudflare.com" "DEPOIS"\n'
        )
        html2 = ponte.read_text(encoding="utf-8") if ponte.is_file() else ""
        checa("o caminho da ponte não muda; o conteúdo sim",
              "https://depois.trycloudflare.com/?t=DEPOIS" in html2
              and "TOKENNOVO" not in html2,
              "depois de uma queda, o celular abre o mesmo arquivo e acha o hostname novo")

    print("— controle negativo: as checagens NOVAS reprovam quando a ponte quebra —")
    with tempfile.TemporaryDirectory() as d:
        pasta = Path(d)
        agulha_refresh = 'http-equiv="refresh"'
        checa("agulha do refresh existe no arquivo real",
              agulha_refresh in TEXTO)
        quebrado = TEXTO.replace(
            'http-equiv="refresh" content="0;url=$url"',
            'http-equiv="x" content="nao-e-redirect"',
            1,
        )
        quebrado = quebrado.replace('href="$url"', 'href="#"', 1)
        checa("isca da ponte alterou o fonte de verdade",
              quebrado != TEXTO and 'href="$url"' not in extrai_funcao("registra_link", quebrado))
        checa("REPROVA: HTML sem a URL viva não passa o contrato da ponte",
              not contrato_ponte(quebrado, pasta / "isca-html"),
              "se isto passar verde, o gate novo é isca que não morde")
        checa("o arquivo real passa o contrato que derrubou a isca",
              contrato_ponte(TEXTO, pasta / "real-depois-da-isca"))

        vigia_quebrada = TEXTO.replace('    registra_link "$nu" "$nt"\n', "", 1)
        checa("agulha da vigia existia para ser removida",
              vigia_quebrada != TEXTO)
        checa("REPROVA: vigia que não atualiza a ponte depois de levantar",
              not ponte_na_vigia(vigia_quebrada),
              "tirar a linha tem que cair; senão a checagem não mede o que diz")
        checa("o arquivo real passa o gate da vigia que a isca derrubou",
              ponte_na_vigia(TEXTO))

        atomica_quebrada = TEXTO.replace(
            'tmp_txt="$txt.tmp.$$"',
            'tmp_txt="$txt"',
            1,
        )
        checa("isca da escrita atômica alterou o fonte",
              atomica_quebrada != TEXTO)
        checa("REPROVA: txt escrito no destino final sem temporário",
              not ponte_atomica(atomica_quebrada),
              "o fallback móvel também precisa ser indivisível para o sync")
        checa("o arquivo real passa o gate atômico que a isca derrubou",
              ponte_atomica(TEXTO))

        anuncio_quebrado = TEXTO.replace(
            'if [ -n "$PONTE_CELULAR_GRAVADA" ]; then',
            'if true; then',
        )
        checa("isca do anúncio alterou os dois condicionais",
              anuncio_quebrado != TEXTO)
        checa("REPROVA: stdout que promete ponte sem prova",
              not anuncio_ponte_honesto(anuncio_quebrado),
              "falha macia não autoriza instrução falsa ao dono")
        checa("o arquivo real passa o gate de anúncio honesto",
              anuncio_ponte_honesto(TEXTO))

    print("\n  NÃO CONFERIDO: túnel real de ponta a ponta (publicaria a sala na internet")
    print("  e depende de rede). A queda-e-volta com endereço novo foi exercitada só")
    print("  pelas funções, não contra o Cloudflare. O sync do iCloud Drive até o")
    print("  iPhone e o toque no sala.html no Arquivos também não foram provados daqui.")
    print(f"\n{_ok} ✔  {_falhou} ✗")
    return 1 if _falhou else 0


if __name__ == "__main__":
    raise SystemExit(main())
