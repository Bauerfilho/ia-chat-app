# Contribuir com o `ia-chat` — o app

Este repositório é a **casca**: um `.app` nativo do macOS, a interface e o servidor que
a serve. O motor — núcleo, CLI, skills, sala — mora no repositório `ia-chat`, e o app o
importa em tempo de execução. Duas consequências práticas antes de qualquer coisa:

- **sem o outro repositório o app não sobe.** O servidor faz `sys.path.insert` apontando
  para `bin/` do `ia-chat`; se ele não estiver no disco, nada roda. O `instalar-app.sh`
  clona quando não encontra;
- **defeito de sala, numeração, cursor ou rotação não se conserta aqui.** É núcleo, e o
  outro repositório tem gate próprio para isso. Aqui se conserta o que o usuário vê.

## A bateria

Cada arquivo é executável, sem runner nem framework:

```bash
cd ~/Projetos/ia-chat-app
for f in testes/teste_*.py; do
  python3 "$f" >/dev/null 2>&1 && echo "✔ $(basename $f)" || echo "✗ $(basename $f)"
done
```

A bateria inteira leva **~16 s** nesta máquina. De propósito não digo quantos arquivos
são: enquanto este documento estava sendo escrito, a contagem foi de 10 para 13. Número
de teste no meio de um texto é a mesma armadilha da âncora `arquivo:linha` — envelhece
sozinho, sem avisar, e quem lê confia. **O laço acima é a verdade.**

**Portas: 59900 e acima.** Os testes que sobem servidor usam essa faixa de propósito, para
nunca colidirem com o app que o dono pode estar usando (8801) nem com o protótipo (8787).
Escolha uma porta livre dentro dela e **derrube o que subir**, inclusive quando o teste
falha no meio:

```bash
python3 -u ui/servir.py --porta 59900 &   # ou dentro do seu teste
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:59900/
pkill -f "servir.py --porta 59900"
```

Servidor esquecido vivo é a falha mais chata daqui: o teste seguinte encontra a porta
ocupada e reprova por um motivo que não tem nada a ver com o que ele testa.

E, como no outro repositório: **`IACHAT_HOME` temporário sempre.** A sala real é dado de
trabalho do dono e das IAs abertas naquele momento.

## O CI roda o mesmo laço — e num Python que o seu talvez não seja

`.github/workflows/testes.yml` faz exatamente o que está escrito acima: `montar.sh`,
depois a bateria inteira, arquivo por arquivo. Nada de framework novo, nada de subconjunto.

Ele roda em **macOS**, e não em Ubuntu, porque a bateria mede coisas que só existem aqui
— `.icns` e `Info.plist` por `sips`/`iconutil`/`plutil`, e o rescaldo por `/usr/sbin/lsof`,
que no Linux mora noutro lugar quando existe. Num runner Linux esses testes ficariam
vermelhos por falta de ferramenta, ou se declarariam não-aplicáveis: as duas saídas são
piores que não rodar. O arquivo do workflow traz a justificativa por extenso.

Roda em **duas pernas de Python**, e a que costuma pegar defeito é a primeira:

```bash
# a perna `sistema` — o Python que já vem no Mac, e a promessa do projeto
for f in testes/teste_*.py; do
  /usr/bin/python3 "$f" >/dev/null 2>&1 && echo "✔ $(basename $f)" || echo "✗ $(basename $f)"
done
```

Se você tem um Python moderno no `PATH` — e provavelmente tem —, um `match`, um
`X | Y` fora de anotação ou um `tomllib` passa despercebido no seu terminal e quebra
no Mac de quem clonar. **Rode a perna `sistema` antes de abrir PR**; é um comando, e é
o que separa "passou aqui" de "passa lá".

Duas coisas que o CI se recusa a fazer, e que valem saber:

- **não fica verde sem rodar teste.** Se o glob não achar nada, ele reprova com a
  mensagem dizendo isso. Verde de bateria vazia é a mentira mais barata que existe;
- **não pula calado.** Um teste que se declara não-aplicável (`⊘`) aparece contado na
  tabela do resumo e num aviso do job. Exclusão declarada é aceitável; invisível, não.

**Sobre o badge:** o `README.md` ainda não tem um, de propósito. Badge só entra depois da
primeira execução real, quando a URL existe e reflete um estado medido — badge apontando
para workflow que nunca rodou é enfeite que mente. Depois do primeiro push, a linha é:

```markdown
[![testes](https://github.com/DONO/ia-chat-app/actions/workflows/testes.yml/badge.svg)](https://github.com/DONO/ia-chat-app/actions/workflows/testes.yml)
```

## `montar.sh` é obrigatório — e não é zelo

O `.app` é versionado **montado**, para que quem baixa não precise de `iconutil` nem de
um passo extra. Mas ícone e interface têm dono em outro lugar do repositório: a fonte é
`marca/` e `ui/`, e a cópia dentro do bundle é derivada.

**Mexeu em `ui/` ou em `marca/`? Rode antes de testar:**

```bash
bash montar.sh
```

Sem isso a mudança **não existe para o app instalado**. O modo de falha é perverso: você
edita, roda o servidor do repositório, vê a correção funcionando, e jura que corrigiu —
enquanto o `.app` continua com a versão antiga. O `testes/teste_montagem.py` existe
exatamente para pegar essa dessincronia.

**A armadilha dentro do `montar.sh`:** ele copia de `ui/` uma **lista fixa de quatro
nomes** — `index.html`, `estilo.css`, `sala.js`, `servir.py`. Um arquivo novo que você
crie em `ui/` existe no repositório e **falta no bundle**. Foi por isso que o favicon não
virou um arquivo solto em `ui/`: ele viaja em base64 dentro do `servir.py`, que é copiado.
Se precisar mesmo de um arquivo novo servido pelo app, a lista do `montar.sh` tem que
crescer junto — e o `teste_montagem` tem que passar a conferi-lo.

## `flush=True` em stdout de servidor

Toda linha que um servidor imprime e que alguém lê **precisa** de `flush=True`.

O caso, de 18/08: o lançador do `.app` sobe o servidor com stdout redirecionado para um
log e descobre o token **lendo esse log**. Com stdout em arquivo, o Python usa buffer de
bloco — medido: **131.072 B**. As ~150 bytes das linhas de abertura nunca enchem esse
buffer, e como o servidor não imprime mais nada depois, o log fica **vazio para sempre**.
O lançador não achava o token, batia em `/api/estado` sem ele, tomava 401, concluía "não
respondeu" e **matava o app aos 20 s** — com um alerta enganoso, porque o servidor estava
vivo e respondendo o tempo todo.

Este defeito só aparece no caminho do usuário final: rodando o servidor à mão, no
terminal, o stdout é um tty, o buffer é de linha e tudo funciona. Quem contornou com
`python3 -u` e seguiu em frente deixou o defeito de pé exatamente onde ele quebrava o
produto.

Regra: `print(..., flush=True)` em qualquer coisa que o lançador leia, e teste o caminho
real (`testes/teste_lancamento.py`), não só o terminal.

## Por que existem dois servidores

| arquivo | é o quê | porta |
|---|---|---|
| `ui/servir.py` | **o servidor do app** — interface completa, token por cookie, SSE | 8801 |
| `ia-chat.app/Contents/Resources/servidor.py` | o protótipo da fase 6, mantido como reserva | 8787 |

O lançador tenta uma cascata e o primeiro que existir ganha: a variável `IACHAT_SERVIDOR`,
depois `ui/servir.py` do repositório vivo (é o que faz quem está mexendo na interface ver
a mudança na hora), depois a cópia congelada no bundle, e o `servidor.py` como reserva
final. `IACHAT_SERVIDOR` existe justamente para você apontar um servidor seu sem tocar
no bundle nem no repositório.

Os dois falam o mesmo protocolo básico, e é isso que o
`testes/teste_coerencia_servidores.py` cobra: ele sobe os dois e compara os contratos
HTTP essenciais. **Mudou rota, código de status ou formato de resposta em um, confira o
outro** — ou mate o segundo de vez, com o lançador ajustado. O que não pode é
divergirem em silêncio: a reserva só serve se ela ainda servir.

## Todo teste precisa do caso que REPROVA

Vale igual aqui: gate que nunca viu vermelho não é gate. Quebre a peça de propósito,
confirme o vermelho, desfaça. Se não conseguir fazer o teste falhar, ele não está
testando nada — e dá confiança, que é o pior defeito possível num gate.

## Mexeu na marca

`marca/gerar_icone.py` gera os SVGs, os PNGs, os dois `.icns` e o `favicon.ico`;
`marca/prova_16.py` gera as folhas de prova; `marca/prancha.py` gera a peça de
apresentação. O critério de projeto do ícone é o **16×16** — a regra e as medições estão
em `marca/MARCA.md`, incluindo por que o ouro nunca encosta na palha sem leito preto.

```bash
python3 marca/gerar_icone.py     # SVG + PNG + .icns + favicon.ico
python3 marca/prova_16.py        # as provas, para olhar antes de aprovar
bash montar.sh                   # sem isto o bundle continua com o ícone velho
```

Trocou o favicon? O `.ico` também precisa ser reembutido em base64 no `ui/servir.py` —
o procedimento está no comentário acima do bloco `FAVICON`, e o motivo está acima, na
armadilha do `montar.sh`.

## Antes de abrir o PR

1. `bash montar.sh` rodado, se você tocou em `ui/` ou `marca/`.
2. Bateria inteira verde (o laço lá em cima), não só o teste da sua peça — e verde
   também com `/usr/bin/python3`, que é a perna do CI que pega o que o seu Python esconde.
3. Nenhum servidor **seu** de pé. Confira pela **porta**, não pelo nome do processo:
   nesta máquina há servidores legítimos rodando o tempo todo (o app do dono, o de outro
   contribuidor), e `pgrep -f servir.py` acusa todos eles.
   ```bash
   lsof -ti :59900 || echo "livre"
   ```
4. Nenhum `IACHAT_HOME` apontando para a sala real.
5. Instalou para testar? Em pasta temporária — `IA_CHAT_DEST=$(mktemp -d) bash instalar-app.sh` —
   e apague depois. Nunca em `/Applications` para teste.
6. Teste novo? Provado vermelho ao menos uma vez, de propósito.

## Mexeu no lançador? `montar.sh` não basta

`montar.sh` monta o bundle **dentro do repo**. `open -a ia-chat` abre o de
**`/Applications`**. São dois arquivos diferentes, e só o `instalar-app.sh` copia um
para o outro.

Isso custou uma medição inteira em 18/08: uma mudança no `lancador.py` foi montada,
testada com `open -a ia-chat`, e o app subiu **sem ela** — porque quem abriu foi a
versão instalada, antiga. O diagnóstico apontava para a variável de ambiente, que
estava certa o tempo todo:

```bash
launchctl getenv IACHAT_LAN                                   # → 1   (certo)
grep -c IACHAT_LAN_FLAG /Applications/ia-chat.app/…/lancador.py   # → 0   (a causa)
grep -c IACHAT_LAN_FLAG ./ia-chat.app/…/lancador.py               # → 2
```

**A verificação que resolve em um segundo:** compare o bundle instalado com o do repo
antes de acreditar em qualquer teste de comportamento do app.

```bash
diff -r ia-chat.app/Contents/Resources /Applications/ia-chat.app/Contents/Resources
```

Diferente? `./instalar-app.sh` antes de testar. A bateria não pega isso: `teste_bundle.py`
e `teste_lan_opt_in.py` leem o bundle **do repo**, que é o certo para eles — o defeito só
existe no caminho que passa pelo Finder.
