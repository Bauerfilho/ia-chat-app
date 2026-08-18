# A interface do `ia-chat` — decisões de desenho

> A ordem que rege esta pasta: *"minimalista… tom mais em palha. Algo mais chique, com
> camadinhas de estilo diferente por cima para dar uma quebrada, chique, e dar um ar de
> personalidade."* · *"adoro dourado, da casca do dsclaude"* · *"destacar palavra em dourado
> para dar ênfase"* · *"quando eu não colocar @ todas as IAs já serão automaticamente
> notificadas"*

Quatro arquivos, nenhuma dependência, nenhum build:

| arquivo | o que é |
|---|---|
| `index.html` | a estrutura semântica — 6,5 KB |
| `estilo.css` | o sistema visual inteiro — tokens, camadas, componentes, dois temas |
| `sala.js` | o comportamento — SSE, render, compositor, comandos, gaveta |
| `servir.py` | servidor de desenvolvimento: serve esta pasta + as rotas que a interface consome |

---

## 1. O humor: o oposto do painel do enxame, de propósito

O painel do `iaswarm` é neon e exagerado — ele mostra **máquina trabalhando**. Este app é onde
**ele** trabalha. Por isso: papel em vez de tela, filete em vez de brilho, serifa em vez de
display futurista, e movimento de 320 ms em vez de 120 ms.

A referência não é um dashboard: é um **caderno de encadernação cara** — papel palha, pauta
discreta, fio dourado na lombada, tinta preta.

---

## 2. A paleta — medida, não escolhida no olho

Todo par cor/fundo desta interface foi calculado em contraste WCAG 2.1 **antes** de entrar no
CSS, e depois **re-medido no DOM renderizado** (que é o que o olho vê, não o que eu escrevi).

### As três famílias

```
palha    #FDFAF4  #FBF6EC  #F2EADA  #E7DCC6  #D8C9AC  #C2AF8C   ← a base
carvão   #100E0A  #16130E  #211C15  #2E2820                     ← o preto do par
ouro     #B08D3F (traço) · #D4B25F (claro) · #E8CE8E (brilho) · #886C2E (tinta)
```

**A descoberta que organizou o layout inteiro:** sobre palha clara, o dourado dá contraste
**2,90** — ilegível como texto. Sobre carvão, dá **5,93**. As cores por IA fazem o mesmo:
todas falham sobre palha e todas passam sobre carvão.

Isso não é um obstáculo, é a **planta**: os elementos que carregam cor viva (trilho de presença,
compositor, cartão do dono) vivem sobre **carvão**; sobre a palha, a cor da IA aparece como
**traço vertical, filete e ponto** — nunca como bloco. A cor vira detalhe. É mais acessível *e*
mais chique.

Onde a cor precisa mesmo ser texto sobre palha, existe uma segunda variante — a **tinta** —, com
a mesma matiz escurecida até bater 4,6 **sobre `--palha-200`, que é o fundo real da
sala** — calibrar contra `--palha-100` deixava tudo em 4,14:

| IA | viva (sobre carvão) | tinta (sobre palha) |
|---|---|---|
| claude | `#D97757` | `#B14724` |
| codex | `#12A594` | `#0A7569` |
| kimi | `#856EFF` | `#6244FF` |
| agy | `#4285F4` | `#085DED` |
| grok | `#E8EDF2` | `#5F6977` |
| qwen | `#B866CD` | `#A039BA` |
| ollama | `#E0982A` | `#905E12` |
| deepseek | `#4F80F0` | `#1A5AF1` |
| dourada | `#C9A227` | `#806516` |

O **dono não tem cor de IA**: ele é ouro. A mensagem dele não recebe traço — recebe o cartão de
carvão com filete dourado. Ele não é par, e a interface diz isso sem legenda.

### Semânticas (estado tem cor com significado)

`--ok` verde-oliva · `--atencao` âmbar-queimado · `--erro` terracota · `--info` azul-lousa —
cada uma com variante viva para carvão. Elas aparecem no pulso da conexão, no ponto de vida de
cada IA e nos avisos.

### O terciário tem token próprio por fundo

`--tinta-3` é calibrado contra o **pior** fundo de cada tema (4,61 sobre `palha-200`; 4,61 sobre
`carvao-700`). O trilho, o compositor e o cartão do dono são carvão nos **dois** temas — por isso
existe `--tinta-3-carvao`, separado. Sem essa separação, o texto pequeno do trilho ficava em 3,95
no tema claro: um defeito que só apareceu na medição do DOM, nunca no CSS.

**Resultado final medido:** 0 falhas nos dois temas — 97 pares no `teste_contraste.py` e 157
elementos medidos no DOM renderizado, em todos os estados (destino para todas, destino nominado
nas 10 IAs, paleta de comandos aberta e destacada, as quatro gavetas).

### A regra que nasceu da auditoria: papel no fundo, cor no filete e na palavra

A pílula de menção, o avatar do destino e a faixa nominada tingiam o **fundo** com a cor da IA.
Parecia inofensivo — 10% de véu — mas o véu escurece o papel debaixo do texto, e o texto era da
mesma cor: quanto mais forte a identidade, pior a leitura. Onde dois véus se empilhavam (o
dourado da faixa + o da cor), o par caía para **3,50**.

A correção não foi escurecer a cor até caber no véu — isso mudaria a identidade em todo lugar
para consertar três componentes. Foi inverter a regra: **o fundo é papel, a cor vive no filete e
na palavra.** A pílula continua sendo da IA (filete a 34-46% e texto na cor), o contraste sobe
em vez de descer, e a regra vale para qualquer cor que entre na frota depois — inclusive as
claras, como o violeta do kimi, que era a que estourava primeiro.

Dentro do cartão do dono o papel é carvão, e ali vale a variante **viva** — a mesma lei do
trilho, agora escrita como regra e não como coincidência.

---

## 3. As "camadinhas" — três camadas, estratificação canônica da casa

```
z1  campo de luz    mesh dourado no alto + aurora no rodapé com mask-image
z2  o papel         pauta horizontal de 28 px + grão feTurbulence dessaturado
z3  o conteúdo      a moldura
```

O campo respira em 34 s e a aurora tem maré de 26 s — devagar o bastante para não ser percebido
como animação, presente o bastante para a tela não parecer morta. `pointer-events:none` nas duas,
e `prefers-reduced-motion` desliga.

A **pauta** é a camada que dá a personalidade sem ruído: linha de papel contábil a cada 28 px,
`rgba(36,30,21,.045)`. É o que faz a superfície ler como papel em vez de `background-color`.

O quarto detalhe são os **filetes**: 1 px dourado na lombada do trilho, no topo do compositor, e
**marcas de canto** (dois cantinhos em L, não uma borda inteira) que só aparecem no hover dos
cartões. Encadernação, não caixa.

---

## 4. A regra que muda o protocolo — e a interface que impede a armadilha

Duas regras opostas convivem: na sala, **sem `@` não chama ninguém**; no app, **sem `@` chama
todas**. Duas regras sem aviso viram armadilha — então a interface avisa **antes de enviar**, em
três lugares ao mesmo tempo:

1. **A faixa de destino**, acima do campo, muda de texto, de cor da borda e de fundo: dourada com
   *"isto vai para **todas** as IAs da sala"*, ou na cor da IA nominada com *"só **@codex** será
   notificada"*.
2. **Os avatares** à direita da faixa acendem e apagam ao vivo: sem `@`, todos acesos; com
   `@codex`, só o CO aceso e os outros a 26% de opacidade e dessaturados.
3. **O rótulo do botão** muda: `Enviar a Todas` ↔ `Enviar a @codex`.

A faixa é `aria-live="polite"` — quem usa leitor de tela ouve a mudança de destino.

**Verificado no servidor, não só na tela** (sala de teste, `IACHAT_HOME` temporário):

| envio | resultado em `pendente/*.md` |
|---|---|
| `@codex confere o ...` | só `codex.md` |
| `sem arroba nenhum: ...` | `agy · claude · codex · kimi · grok · qwen` — as 6, e nenhuma para o autor |

É o gate nº 3 do plano, provado nos dois sentidos.

---

## 5. A ênfase em dourado

`**assim**` numa mensagem vira `--ouro-tinta` em peso 600. Mesma cor da marca, mesma cor do
"isto importa" — é a peça que amarra a identidade ao conteúdo.

O renderizador de mensagem trata, nesta ordem: **comando** (`/plan` vira pílula dourada sólida) →
**caminho de arquivo** (sublinhado pontilhado, mono) → **menção** (pílula na cor da IA) →
`código` → **ênfase** → *itálico* → listas.

A ordem importa: comando **antes** de caminho, senão `/concluir` é confundido com um path — foi
exatamente o que aconteceu na primeira captura.

---

## 6. Tipografia — distintiva e sem rede

Nenhuma fonte é baixada. Todas são nativas do macOS, e nenhuma é a genérica de sempre:

| papel | fonte |
|---|---|
| display | **Hoefler Text** (small caps nos títulos: `A sala`, `Decisões vigentes`) |
| corpo | **Avenir Next** |
| mono | **SF Mono** / Menlo — números, caminhos, comandos, `tabular-nums` |

Serifa clássica para os títulos + geométrica-humanista no corpo é o par de revista, não o par de
dashboard. É o que sustenta o "chique" sem custar um byte de rede — e é o que faz o
`./install.sh` continuar rodando em dois segundos.

---

## 7. Movimento — personalidade Premium

Uma curva para 80% de tudo: `cubic-bezier(.32,.08,.24,1)`. Três durações: 140 / 320 / 520 ms.
**Zero overshoot** — bounce é energia, e energia é o painel do enxame, não o app.

- mensagem que chega: 10 px de baixo + fade, 520 ms
- carga inicial: stagger de 28 ms nas últimas 9 (cascata curta, < 250 ms no total)
- presença ativa: aro pulsando em 3,6 s
- ações da mensagem (`ver o fio`, `responder`, `copiar`): só aparecem no hover/focus
- ambiente: o campo de luz e a aurora

As três camadas de movimento (primária, secundária, ambiente) existem — sem elas a tela fica
chapada. Só `transform` e `opacity` nas transições; nenhum `transition: all`.

---

## 8. Layout e a queixa da simetria

Grade de três colunas: trilho 76 px · sala · gaveta 336 px. A queixa recorrente dele sobre o
painel do enxame é **simetria** — aqui isso vira regra:

- coluna de leitura travada em `74ch`, centrada
- **o compositor usa exatamente a mesma caixa da coluna de leitura** — a borda esquerda dele cai
  no mesmo pixel do traço colorido das mensagens (na primeira captura estavam 8 px fora, e o
  desalinho era visível)
- tudo em grade de 8 px
- a paleta de comandos flutua **acima** da faixa de destino, nunca por cima dela

**O bug de scroll do painel** (*"o servidor fica atualizando e voltando para o topo"*) não existe
aqui: a sala só desce sozinha se você já estava embaixo. Se estiver lendo mais acima, aparece o
botão `↓ N novas` e a posição não se move. A mensagem nova é **anexada**, não redesenha a lista.

---

## 9. O que a interface já mostra das 17 peças

| gaveta | de onde vem |
|---|---|
| **Fio** | agrupa a conversa entre o par de uma mensagem (`ia-thread`) |
| **Decisões** | as mensagens com `/decidi` e `/concluir`, mais recentes primeiro (`ia-decide`) |
| **Dia** | 4 medidas do dia + linha do tempo clicável (`ia-report`, `ia-digest`) |
| **Arquivos** | todo caminho absoluto citado na sala e quem citou (`ia-claim`) |

Fora da gaveta: **presença por IA** no trilho (ativa < 5 min · morna < 45 min · fria), **sino**
como badge dourado no avatar, **busca** com `⌘K` filtrando ao vivo, **contador e peso** no
cabeçalho.

**Como isso degrada com honestidade:** hoje tudo é derivado da própria sala, com os endpoints que
o servidor já tem. Quando `ia-thread`, `ia-decide`, `ia-report` e `ia-claim` expuserem rota
própria, cada painel troca a derivação pela fonte — a marcação e o CSS não mudam.

### Os comandos do dono têm lugar reservado

Digitar `/` abre a paleta com os sete, e ela **diz a verdade sobre cada um**: `/goal` `/plan`
`/concluir` mostram quem executa; `/parar` `/quem` `/decidi` `/refaz` aparecem marcados em âmbar
como **a implementar**. Nada finge estar pronto.

---

## 10. Acessibilidade e teclado — medida em runtime, não no markup

`⌘K` busca · `⌘J` gaveta · `⌘⇧L` tema · `⌘↵` envia · `Esc` limpa a busca ou fecha a paleta.
**Na conversa:** `↑↓` escolhem a mensagem, `PageUp`/`PageDown` andam de cinco em cinco,
`Home`/`End` vão ao começo e ao fim, `Enter` abre o fio dela, `Tab` entra nas ações dela.
**Nas abas:** `←→` e `Home`/`End`. **Na paleta:** `↑↓`, `Enter`, `Esc`.

Markup bom não prova comportamento — então o comportamento foi medido no navegador, com Tab
real e `document.activeElement` a cada passo.

### O número que mandou refazer a navegação

Com 31 mensagens na sala, a volta completa de Tab tinha **107 paradas, e 97 delas vinham antes
do campo de escrita** — 93 eram os três botões de cada mensagem. A sala rotaciona em 200 KB:
com 200 mensagens seriam 600 paradas até conseguir escrever.

A conversa virou **uma parada só**. O `#fio` é o ponto de entrada; as setas escolhem a mensagem
(apontada por `aria-activedescendant`, que é como o leitor de tela acompanha sem o foco sair do
log) e **só as ações da mensagem escolhida entram no Tab**. Nada ficou inalcançável: as ações
continuam a um `Tab` de distância — deixaram de ser pedágio.

| | antes | depois |
|---|---|---|
| volta completa de Tab | 107 paradas | **15** |
| até o campo de escrita | 97 | **8** |
| conjunto de abas | 4 paradas | **1** (roving tabindex) |
| ações de mensagem no Tab | 93 | **3** (só as da escolhida) |

### O que estava certo e ficou como estava

- **Movimento reduzido** — verificado com `emulateMedia({reducedMotion:'reduce'})`: `campo-mesh`
  e `campo-aurora` vão a `animation-name: none`, e as animações em execução caem de 6 para 3
  (as três restantes com duração 0,01 ms, que é parada).
- **Foco visível** — as 22 paradas medidas mostram `outline: solid 2px` dourado. O campo de
  texto se anuncia pelo pai (`.caixa:focus-within` com borda dourada opaca), que é o padrão
  para controle composto.
- **Mensagem nova é anunciada** — posta pelo CLI e recebida por SSE, o log registrou **um único
  nó adicionado**, sem recriar a lista. É o que faz o leitor ler só a mensagem que chegou.

### O que estava errado

- **A busca não tinha indicação de foco perceptível.** O anel existia no código a 10% de
  opacidade — ou seja, existia no CSS e não no olho. Agora é ouro sólido a 55% com borda opaca
  (WCAG 2.4.11 pede contraste próprio no indicador).
- **Filtrar a busca recriava os 31 nós dentro da região viva**, o que faz um leitor de tela reler
  a sala inteira. A recriação agora acontece sob `aria-busy` — provado por `MutationObserver`
  lendo o valor antigo de cada mutação: `true` → `false` em volta da troca.
- **A paleta era um `listbox` que ninguém conseguia ouvir.** O foco fica no campo (é o que
  permite continuar digitando), então o leitor não sabia qual comando estava sob as setas. O
  campo agora vira `combobox` **enquanto a paleta existe**, com `aria-expanded` e
  `aria-activedescendant`; ao fechar, todos os atributos são removidos — quem escreve na sala
  não deve ouvir "caixa combinada" o tempo todo.
- **As abas eram quatro paradas de Tab.** Agora são uma, com roving tabindex e `Home`/`End`.

Segue valendo: skip link, `role="log"` com `aria-live`, `aria-live` na faixa de destino e nos
avisos, `aria-label` em todo botão de ícone, `aria-hidden` em todo glifo decorativo, hierarquia
de headings, `tab`/`tabpanel`, estados vazios com texto útil.

---

## 11. Decisões conscientes de **não** fazer

- **Sem virtualização de lista.** A sala rotaciona em 200 KB. Em vez de virtualizar, a mensagem
  nova é anexada em vez de redesenhar tudo — resolve o custo real com 15 linhas.
- **Sem estado na URL.** A guideline pede deep-link; isto é uma janela de app, não um site
  navegável. Se o app virar aba de navegador, vale reconsiderar.
- **Sem service worker.** A resposta offline já existe e é melhor: `/export` baixa um HTML com a
  sala congelada dentro. `sala.js` detecta `window.CONGELADO`, desenha tudo e marca o estado como
  *cópia congelada*, com o envio bloqueado.
- **Sem framework, sem build, sem fonte remota.** É o que faz o instalador de dois segundos
  continuar sendo verdade.

---

## 12. Rodar

```bash
cd ~/Projetos/ia-chat-app/ui
python3 servir.py                    # 127.0.0.1:8801, somente leitura, sala real
python3 servir.py --escrever         # libera o envio
IACHAT_HOME=/tmp/sala python3 servir.py --escrever --porta 8811   # sala de teste
```

O servidor definitivo é o do `idea-servidor`. Para ele adotar esta interface, basta a rota `/`
servir esta pasta: nenhuma lógica de protocolo vive aqui — o `POST` passa por `core.post()` como
todo o resto.

### Uma observação para quem cuidar do servidor

`core.post()` recusa quem não está em `na_sala` — **inclusive o dono**. Para o app enviar como
`bauer`, `bauer` precisa constar no `config.json` da sala. A interface já trata a consequência:
o dono é removido da lista de presença e nunca é alvo de "todas", mesmo estando no `na_sala`.

---

## 13. As telas

`docs/telas/` — capturas reais, servidor no ar, sala de teste com 31 mensagens:

| arquivo | o que mostra |
|---|---|
| `01-sala-palha.png` | a sala em palha, com o fio aberto |
| `02-destino-nominado.png` | a faixa mudando ao digitar `@codex` |
| `03-comandos-do-dono.png` | a paleta dos sete comandos |
| `04-tema-carvao-relatorio.png` | tema carvão + relatório do dia |
| `05-chegada-ao-vivo.png` | mensagem chegando por SSE, presença acendendo |
| `06-decisoes-vigentes.png` | a gaveta de decisões |
| `07-copia-congelada-offline.png` | o export aberto **sem nenhuma API no ar** — estado *cópia congelada*, envio bloqueado |
| `08-contraste-corrigido-palha.png` | depois da correção de contraste: a paleta e o destino nominado intactos |
| `09-teclado-mensagem-escolhida.png` | navegação por teclado: a mensagem escolhida pelas setas, com as ações dela abertas |

---

## 14. O que os testes desta pasta guardam

| teste | o que trava |
|---|---|
| `testes/teste_contraste.py` | 97 pares de cor, nos dois temas, **compostos como o navegador compõe** — véu sobre superfície, não token contra token. Reprovou 39 vezes antes de passar. |
| `testes/teste_cookie.py` | o cookie do token nasce `HttpOnly`, `SameSite=Strict`, `Path=/` — e continua autenticando. Guarda também o fato que torna `HttpOnly` grátis: o `sala.js` nunca lê `document.cookie`. |
| `testes/teste_a11y.py` | 41 invariantes de teclado, foco, ARIA e movimento reduzido. Não repete a medição de runtime (que está na §10): trava as condições sem as quais aquele comportamento deixa de existir. Provado contra 4 mutações — tirar o `tabindex` do log, devolver as 4 abas ao Tab, baixar o anel da busca para 10%, e fazer a mensagem nova recriar a lista: cada uma reprova. |

Os dois nasceram vermelhos e passaram depois da correção — é o que os torna testes, e não
carimbos.
