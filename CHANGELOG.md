# CHANGELOG — ia-chat-app

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
