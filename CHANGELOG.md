# CHANGELOG — ia-chat-app

## 2026-08-18 (fim de tarde) — desempenho medido, e os gates param de medir a forma de ontem

> Bateria: **27 arquivos verdes**, medido por exit code.

### A interface viaja comprimida: 276 KB → 102 KB

Ele pediu para priorizar o desempenho e eu não tinha medido nada. A página pesava
276 KB de texto e o servidor não comprimia uma linha — e ele lê a sala no celular,
por um túnel, em rede móvel.

    /              15.827 →   4.932 B        sala.js    96.658 → 30.857 B  (69%)
    estilo.css     70.546 →  17.288 B        /api/sala  71.338 → 26.485 B  (63%)
    ─────────────────────────────────────────────────────────────────────
    total         276.444 → 101.637 B  (64% menor)

O `apple-touch-icon.png` fica fora — PNG já vem comprimido. Abaixo de 1 KB também
não vale o cabeçalho.

⚠️ **O SSE nunca passa pelo compressor.** gzip acumula bytes num buffer e entrega
quando o bloco fecha; num stream, a mensagem chegaria quando o buffer enchesse, e o
defeito apareceria como "está lento", nunca como erro.

### Sete gates paravam de medir mecanismo

O alvo de dedo aceitava só `44px` ou `48px` — os 56 px da HIG eram reprovados como
se fossem defeito. As ações da mensagem cobravam `== 3`. A folga das abas cobrava a
substring exata do CSS. Cada um quebraria quando o produto melhorasse.

E o gate de offline confundia comentário com dependência: ele procurava `http://` no
texto inteiro do `sala.js`, e o CSS já era limpo de comentários antes de medir. A
assimetria é que estava errada.

### O túnel do celular ganhou vigia

`abrir-remoto.sh --vigiar` mantém no ar. A vigia **não** derruba um túnel que
responde: reiniciar por precaução trocaria o endereço em uso, e o remédio mataria o
paciente. A prova é de fora, por um GET no próprio endereço — `pgrep` não distingue
processo vivo de processo que não responde.

### E o modo do enxame virou endereço

`?modo=neon` e `?modo=dourado` fecham a família dos deep-links. Quem mandava a alguém
o link do painel neon via o dourado.

## 2026-08-18 (tarde) — o dourado recupera o que faltava, e o mapa vira leitura de verdade

> Bateria: **25 arquivos verdes**, medido por exit code — o laço antigo julgava pelo
> TEXTO da última linha e, no repo vizinho, deu 22 vermelhos falsos de 38.

### As 6 funções do neon que faltavam no IASWARM dourado

Ele pediu a janela do enxame em dourado *"preservando TODAS as suas funções"*. Uma
auditoria independente contou uma a uma: **19 de 25**. As seis que faltavam voltaram:

- o **foco de teclado** se perdia a cada 2 s. O neon devolvia scroll *e* foco depois de
  cada tick; o dourado devolvia só o scroll, o que tornava a janela inutilizável sem
  mouse. Era o mais grave;
- o **relógio do run** sumiu do cartão — voltou o `entregues · HH:MM` da última
  evidência, e ele some quando não há evidência, em vez de mostrar hora inventada;
- a **paleta** encolhera de ~44 marcas para 14, sem os apelidos: `k2`, `dashscope`,
  `gpt`, `mistral`, `nvidia` e `azure` caíam num tom por hash;
- o **deep link `?abrir=`** trocara de função — no neon expandia um worker, no dourado
  abria a doca. Endereço é contrato: quem salvou um link chegava noutro lugar;
- a **animação de estreia** voltou, só na primeira pintura e desligada sob
  `prefers-reduced-motion`;
- o **modo snapshot** ficou de fora DE PROPÓSITO, e agora está escrito no `DESIGN.md`
  §15. Ele existia porque o neon abria por `file://` sem servidor. O problema nunca foi
  a ausência — foi ela não estar declarada.

Quatro cores tiveram o **tom** ajustado para caber no papel dourado, mantendo a
identidade: `xai`, `huggingface`, `modal`, `moonshot`. Branco e lima-neon somem ou
gritam sobre palha.

### O mapa de retomada virou leitura, não texto morto

Ele lê o `caminho.md` no celular, pela aba Mapa. Três coisas que só aparecem olhando a
tela: o endereço do painel era texto que não abre; `[[wikilink]]` aparecia cru; e um
caminho longo quebrava no meio da palavra (`/.clau` numa linha, `de/` na outra).

Agora `http`/`https` viram link em aba nova — e **só** eles: `javascript:` e `data:` não,
que é onde mora o abuso numa sala que recebe texto de quatro IAs. O wikilink vira rótulo
com os colchetes visíveis, deliberadamente **não** clicável: o vault não é servido aqui,
e link que não abre mente. E cada `/` do caminho ganhou ponto de quebra.

### O foco volta para o botão que abriu a gaveta

Ele pediu o mesmo botão da barra lateral também no topo. Os dois estavam lá, mas fechar
devolvia o foco sempre ao de baixo — quem abria pelo topo era jogado para o outro canto
da tela; no celular, para um botão fora de vista.

### E o "confirmar antes" passou a viver no servidor

A auditoria provou que `POST /api/parar` com `{"confirmado":true}` e nada antes voltava
200 e matava o processo. Agora a previsão devolve um recibo de uso único, amarrado ao
comando e aos argumentos. Detalhe no CHANGELOG do `ia-chat`.


## 2026-08-18 (madrugada) — o app parou de mentir, e passou a alcançar o celular

> Bateria: **22 arquivos verdes.** Oito correções, todas achadas por auditoria externa
> (workers `i1`, `j1` e `codex`), todas com gate e isca que vê vermelho.

### O que o app dizia e não era verdade

O núcleo resolvia, e o app tomava um atalho paralelo. Isso não produz erro — produz
**mentira**, e mentira o usuário acredita e age em cima.

| o app mostrava | a verdade |
|---|---|
| mensagem sem `@` → **"todas"** | não chamou **ninguém** |
| depois da rotação, sala vazia | as mensagens existem; o CLI as acha nos recortes |
| `/goal` `/plan` `/concluir`: "as IAs leem e agem" | viravam post de texto; nenhuma missão aberta |
| post OK, silêncio | o núcleo devolvia avisos que a UI engolia |

O caso dos comandos tinha a resposta escrita no próprio arquivo, para o `/decidi`:
*"postado como mensagem ele não entra no registro, e o que existe na sala mas não no
registro é a dívida dos dois instrumentos de volta"*. Missão sem `estado.json` é isso.

### O celular

O `.app` subia **sempre em loopback** — o telefone não alcança loopback, e usar a sala
no celular exigia subir um servidor à mão, o que anula os dois cliques que são a razão
de o app existir. `IACHAT_LAN=1` liga, e é opt-in de propósito: ligado por padrão, a
sala aceitaria conexão de qualquer máquina do Wi-Fi — inclusive o de um café.

Dois defeitos de segurança vieram junto:

- **o anti-CSRF só aceitava a primeira interface.** Com Wi-Fi e Ethernet, quem abrisse a
  segunda URL impressa via a sala carregar e tomava 403 ao ENVIAR — o pior tipo de
  defeito, o que parece funcionar;
- **o token ficava na barra de endereço.** Favoritar no celular gravaria o segredo
  dentro do ícone, sobrevivendo à troca do token.

### Identidade

`papel` era `"bauer"` cravado: quem clonasse o repositório postaria com o nome do autor
na própria sala. Trocar cru por `$USER` consertaria o estranho e quebraria o dono (o
usuário do sistema dele não é o apelido que a sala conhece), então a regra pergunta ao
disco — e no caso ambíguo, com dois humanos, **não escolhe**.

### Fonte única

`index.html`, `estilo.css` e `sala.js` existiam na raiz **e** em `ui/`. Ninguém servia a
raiz, e a `sala.js` de lá já tinha divergido. Quem clonasse, desse `ls` e editasse a da
raiz veria a mudança não acontecer — sem erro, sem aviso.

### A demo do README não rodava

`curl -sN "http://127.0.0.1:8801/api/stream?desde=0"` devolvia `{"erro": "token inválido
ou ausente"}`: faltava a linha que sobe o servidor, e é ela que torna a demonstração
possível (em modo leitura não há token). O gate novo **executa** a demo extraída do
README — prosa se revisa lendo, comando se revisa rodando.

### Publicação

O ZIP não instalava (sem `.git`, o instalador não sabia de onde clonar, e a mensagem de
erro trazia reticências literais que quebram no copiar-e-colar), e o CI ficaria vermelho
no primeiro push por repo irmão ainda não publicado. Aqui a ausência do irmão ZERA a
cobertura — todo teste importa `iachat_core` —, então o job não finge verde: pula a
bateria e escreve "**Bateria NÃO executada — isto não é um teste que passou**".

## 2026-08-18 — o app nasce, quebra, e é consertado

> Bateria: **7 arquivos, 59 casos, todos verdes** — os primeiros deste repositório.

### O app não abria, e ninguém saberia

Três `print()` sem `flush=True`. O lançador descobre o token do servidor **lendo o log**;
com stdout redirecionado a arquivo, o Python usa buffer de bloco (131.072 B medidos), as
~150 bytes da URL nunca o enchem, e o log fica **vazio para sempre**. O lançador não acha
o token, bate em `/api/estado` sem ele, toma 401, conclui *"o servidor não respondeu"* e
mata o app aos 20 s — com o servidor vivo e respondendo.

**Só aparece no caminho do usuário final.** Rodando no terminal, o stdout é linha-a-linha
e o token sai na hora. Foi assim que passou.

### Segurança: três defesas, provadas em execução

- **a identidade de quem posta é do SERVIDOR, nunca do cliente.** Aceitar `de` do payload
  permitia a qualquer um com o token assinar como outra IA — foi a causa de uma mensagem
  assinada com o nome do dono que ele não escreveu;
- **anti-CSRF por `Origin`**, nos dois servidores;
- **teto de 256 KB** no corpo do POST.

Provas: sem token **401** · com token **200** · origem forjada **403** · corpo de 300 KB
**413** · POST assinando `claude` sai assinado `bauer`.

### A sala no celular

`--lan` expõe na rede local **com token obrigatório**, semeado uma vez pela URL e mantido
em cookie. As URLs saem das interfaces **físicas** primeiro (`en0`, `en1`): com VPN ativa,
a rota default devolve o IP do túnel, que o telefone não alcança.

### A bateria

`teste_lancamento` (o token chega ao log pelo caminho do usuário final) · `teste_montagem`
· `teste_instalacao` (o instalador é contido) · `teste_bundle` · `teste_offline` (a
interface não busca nada remoto) · `teste_servidores` · `teste_coerencia_servidores`.

Todos em `IACHAT_HOME` temporário e portas 59900+, derrubando o que sobem. A sala viva do
dono é intocável.
