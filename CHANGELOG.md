# CHANGELOG — ia-chat-app

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
