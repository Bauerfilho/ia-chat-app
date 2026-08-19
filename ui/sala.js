/* ═══════════════════════════════════════════════════════════════════════════
   ia-chat · a sala — comportamento
   Vanilla, sem dependência. Fala com o servidor do `idea-servidor`:
   GET  /api/estado        -> {ultima}
   GET  /api/sala?desde=N  -> {ultima, desde, msgs[], sala{}}
   GET  /api/sino          -> {notificar_operador, escrever}
   GET  /api/stream?desde=N-> SSE, event:msg
   GET  /api/quem          -> presença (allowlist de leitura)
   GET  /api/iaswarm       -> {fonte, raiz, vivo, runs[]}
   GET  /api/iaswarm/remoto-> {eventos, log, resultado}  (leitura, um worker)
   GET  /api/groupchat?desde=N -> {ultima, limites, corte, sessions, snapshots, msgs}
   POST /api/post          -> {de, texto, para[]}
   POST /api/sino          -> {notificar_operador}
   POST /api/<goal|plan|concluir|parar|refaz|decidi>
                           -> comandos do dono, allowlist fechada: argv constante,
                              payload JSON pelo stdin do comando (--via-app), --de
                              do servidor; plan/parar/refaz exigem "seco" (previsão)
                              e depois "confirmado" (gate do servidor)
   Endpoints opcionais (/api/quem /api/decisoes /api/reservas /api/fio) degradam:
   quando não existem, a interface deriva o que dá da própria sala e diz que derivou.
   ═══════════════════════════════════════════════════════════════════════════ */
'use strict';

/* ── doutrina de cor por IA (a quebra da paleta) ─────────────────────────── */
const IAS = ['claude','codex','kimi','agy','grok','qwen','ollama','deepseek','dourada','bauer'];
const DONO = 'bauer';

/* ── comandos do dono ──────────────────────────────────────────────────────
   `onde` diz ONDE o comando age, e a paleta MOSTRA isso. A história desta
   tabela tem três eras, e cada uma pagou um preço:

   1. `sala` — os comandos viravam post de TEXTO: nenhum abria missão, nenhum
      despachava, nenhum gravava `comando/estado.json`. A paleta prometia e
      mentia. Comando morto na tela é pior que comando ausente.
   2. `terminal` — pararam de prometer: a paleta mostrava a linha para copiar.
      Honesto, mas não era o que o dono queria — ele quer os comandos
      FUNCIONANDO no app (decisão dele, fase 9, 18/08).
   3. `aqui` — a era atual: a paleta chama o `iachat-comando` DE VERDADE,
      através do servidor, com três travas que vivem em `servir.py`:
        · allowlist FECHADA — argv constante, texto do dono entra pelo stdin
          do comando (`--via-app`), nunca como argumento;
        · `--de` é o papel do SERVIDOR, nunca do cliente — foi aceitando
          identidade do cliente que apareceu na sala uma mensagem assinada
          `bauer` que ele não escreveu;
        · o que gasta ou mata (`/plan`, `/parar`, `/refaz`) exige confirmação
          EXPLÍCITA: a previsão aparece no painel ANTES, e só o botão confirma.

   `linha` e `porque` ficam na tabela como DEGRADAÇÃO: se o servidor não tiver
   a rota (bundle velho), a paleta mostra a linha do terminal, como o `/quem`
   sempre fez. `/decidi` atravessa como os demais: quem grava no registro é o
   CLI, não a mensagem. */
const COMANDOS = [
  {cmd:'/goal',     desc:'Enunciar o objetivo da rodada',                 onde:'aqui', quem:'abre a missão no disco',
   linha:'iachat-comando goal "<o objetivo>"',
   porque:'sem servidor, o terminal abre a missão.'},
  {cmd:'/plan',     desc:'A frota planeja junta — o tamanho da tarefa escolhe quantas e quais', onde:'aqui', quem:'despacha quem o nível pede',
   confirma:'despachar agora',
   linha:'iachat-comando plan',
   porque:'sem servidor, o terminal despacha.'},
  {cmd:'/concluir', desc:'Autorizar: pode aplicar',                       onde:'aqui', quem:'a única etapa que muda o mundo',
   linha:'iachat-comando concluir',
   porque:'sem servidor, o terminal autoriza.'},
  {cmd:'/quem',     desc:'Quem está vivo, no quê, há quanto tempo',       onde:'aqui', quem:'lê o estado e responde aqui'},
  {cmd:'/parar',    desc:'Abortar a missão em andamento',                 onde:'aqui', quem:'mata processo',
   confirma:'parar a missão agora',
   linha:'iachat-comando parar',
   porque:'sem servidor, o terminal para.'},
  {cmd:'/refaz',    desc:'Redisparar worker morto de onde parou',         onde:'aqui', quem:'gasta assinatura',
   confirma:'redisparar agora',
   linha:'iachat-comando refaz --ia <ia>',
   porque:'sem servidor, o terminal redispara.'},
  {cmd:'/decidi',   desc:'Registrar decisão que todas obedecem',          onde:'aqui', quem:'grava no registro',
   linha:'iachat-comando decidi --porque "<o motivo>" "<a decisão>"',
   porque:'sem servidor, o terminal registra.'},
];
const ONDE = {
  sala:     {rotulo:'vai para a sala',       vindouro:'nao'},
  aqui:     {rotulo:'atravessa o servidor',  vindouro:'nao'},
  terminal: {rotulo:'só no terminal',        vindouro:'sim'},
};
/* O comando é a PRIMEIRA palavra, e só. `/parar` não casa `/parardetudo`, e
   texto que apenas cita `/parar` no meio da frase continua sendo conversa. */
const cmdDe = txt => COMANDOS.find(c => txt === c.cmd || txt.startsWith(c.cmd + ' '));

const $  = (s,r=document)=>r.querySelector(s);
const $$ = (s,r=document)=>[...r.querySelectorAll(s)];

const E = {
  fio:$('#fio'), vazio:$('#vazio'), sala:$('#sala'), presenca:$('#presenca'),
  contador:$('#contador'), peso:$('#peso'), elo:$('#elo'), texto:$('#texto'),
  destino:$('#destino'), destinoTxt:$('#destino-texto'), destinoAlvos:$('#destino-alvos'),
  enviar:$('#enviar'), enviarRot:$('#enviar-rotulo'), conta:$('#conta'),
  paleta:$('#paleta'), busca:$('#busca'), avisos:$('#avisos'),
  descer:$('#descer'), descerN:$('#descer-n'), moldura:$('.moldura'),
  veu:$('#veu-gaveta'), sino:$('#btn-sino'), sinoGlifo:$('#sino-glifo'),
  mapa:$('#mapa'), versao:$('#aviso-versao'), estadoVersao:$('#estado-versao'),
  recarregarVersao:$('#recarregar-versao'),
};

const S = {
  msgs:[], ultima:0,
  sala:{na_sala:[],escrever:false,papel:DONO,notificar_operador:false},
  naSala:[], sinos:{}, colado:true, novas:0, filtro:'', fio:null, fonte:null,
  ativa:null, sinoMudando:false, // a troca não concorre com a sincronização
};

/* ── três modos, um só chassi ─────────────────────────────────────────────
   `index.html` continua sendo a casa única. O terceiro modo entra como um
   filho da mesma `.moldura`, usa o mesmo cabeçalho e o mesmo compositor; não
   nasce uma página paralela. O seletor é montado aqui porque a fronteira desta
   fase não inclui o HTML, e fica visível também no celular. */
const JANELAS = new Set(['sala','enxame','groupchat']);

function instalaModosJanela(){
  const cabeca = $('.cabeca');
  if (!cabeca || $('#groupchat')) return;

  const modos = document.createElement('nav');
  modos.className = 'janela-modos';
  modos.setAttribute('aria-label', 'Modo da janela');
  modos.innerHTML = ['sala','enxame','groupchat'].map(modo =>
    `<button type="button" class="janela-modo" data-modo-janela="${modo}" ` +
    `aria-pressed="${modo === 'sala'}">${modo}</button>`).join('');
  cabeca.insertBefore(modos, $('.cabeca-busca'));

  const groupchat = document.createElement('section');
  groupchat.className = 'groupchat';
  groupchat.id = 'groupchat';
  groupchat.hidden = true;
  groupchat.setAttribute('aria-label', 'Groupchat das sessões independentes');
  groupchat.innerHTML = `
    <main class="groupchat-conversa" id="groupchat-conversa" aria-label="Conversa entre as IAs">
      <div class="groupchat-fio" id="groupchat-fio" role="log" aria-live="polite"
           aria-relevant="additions"></div>
    </main>
    <aside class="groupchat-lateral" aria-label="Estado das sessões">
      <h2>Janelas das IAs</h2>
      <p>Ocupação da sessão atual. Nunca soma a sala.</p>
      <p class="gc-fonte" id="groupchat-fonte">telemetria: aguardando</p>
      <p class="gc-fonte" id="groupchat-corte" role="status" aria-live="polite" hidden></p>
      <div id="groupchat-sessoes"></div>
    </aside>`;
  E.moldura.append(groupchat);

  modos.addEventListener('click', ev=>{
    const b = ev.target.closest('[data-modo-janela]');
    if (!b) return;
    janelaModo(b.dataset.modoJanela);
    // voltaOFoco: quem trocou o modo recebe o foco de volta. janelaModo manda
    // o compositor focar no desktop; sem isto o Tab some do seletor.
    if (document.contains(b)) b.focus();
  });
}

instalaModosJanela();

const GC = {
  raiz:$('#groupchat'), conversa:$('#groupchat-conversa'), fio:$('#groupchat-fio'),
  sessoes:$('#groupchat-sessoes'), fonte:$('#groupchat-fonte'),
  aviso:$('#groupchat-corte'), snapshots:[], sessions:[], msgs:[],
  cursor:0, carregada:false, ocupado:false, timer:null, limites:{},
  fioHTML:null, sessoesHTML:null,
  corteInicial:null, corteAtual:null, itensGrandesOmitidos:0,
  telemetriaOmitida:0,
};

/* ── utilidades ──────────────────────────────────────────────────────────── */
const TOKEN = new URLSearchParams(location.search).get('t') || '';
const url = (rota, q='') => rota + (TOKEN||q ? '?' + [q, TOKEN?'t='+encodeURIComponent(TOKEN):''].filter(Boolean).join('&') : '');
const INTERVALO_VERSAO_MS = 60_000;
const VERSAO_EMBUTIDA = $('meta[name="ia-chat-versao"]')?.content || '';
let versaoCarregada = /^[a-f0-9]{64}$/.test(VERSAO_EMBUTIDA) ? VERSAO_EMBUTIDA : null;
let versaoConsultando = false;

async function verificaVersao(){
  if (versaoConsultando || !E.versao || !E.versao.hidden) return;
  versaoConsultando = true;
  try{
    const r = await fetch(url('/api/versao'), {cache:'no-store', credentials:'same-origin'});
    const d = await r.json();
    if (!r.ok || typeof d.hash !== 'string' || !d.hash)
      throw new Error(d.erro || ('HTTP ' + r.status));
    if (versaoCarregada === null) versaoCarregada = d.hash;
    else if (d.hash !== versaoCarregada){
      E.versao.hidden = false;
      if (E.estadoVersao)
        E.estadoVersao.textContent = 'Nova versão disponível. Use o botão recarregar.';
    }
  }catch(e){
    console.warn('não consegui verificar a versão da interface:', e);
  }finally{
    versaoConsultando = false;
  }
}

function iniciaVigiaVersao(){
  if (window.CONGELADO || !E.versao || !E.recarregarVersao) return;
  E.recarregarVersao.addEventListener('click', ()=> location.reload());
  verificaVersao();
  window.setInterval(()=>{
    if (document.visibilityState === 'visible') verificaVersao();
  }, INTERVALO_VERSAO_MS);
  window.addEventListener('focus', verificaVersao);
  document.addEventListener('visibilitychange', ()=>{
    if (document.visibilityState === 'visible') verificaVersao();
  });
}

const esc = t => String(t).replace(/[&<>"']/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const corDe = n => IAS.includes(n) ? n : 'anonima';
const inicial = n => (n||'?').slice(0,2).toUpperCase();

const fmtHora = new Intl.DateTimeFormat('pt-BR',{hour:'2-digit',minute:'2-digit'});
const fmtDia  = new Intl.DateTimeFormat('pt-BR',{day:'2-digit',month:'long'});
const fmtNum  = new Intl.NumberFormat('pt-BR');

function bytesLegiveis(b){
  if (b < 1024) return b + ' B';
  if (b < 1024*1024) return fmtNum.format(Math.round(b/1024)) + ' KB';
  return (b/1048576).toFixed(1).replace('.',',') + ' MB';
}
function haQuanto(ts){
  const s = (Date.now() - new Date(ts).getTime())/1000;
  if (s < 60) return 'agora';
  if (s < 3600) return Math.round(s/60) + ' min';
  if (s < 86400) return Math.round(s/3600) + ' h';
  return Math.round(s/86400) + ' d';
}
/** resumo: tira os marcadores de markdown, que em texto curto viram ruído */
const seco = t => String(t).replace(/[*`]/g,'').replace(/\s+/g,' ').trim();
function vidaDe(ts){
  const min = (Date.now() - new Date(ts).getTime())/60000;
  return min < 5 ? 'ativa' : (min < 45 ? 'morna' : 'fria');
}

/* ── mensagens flutuantes ────────────────────────────────────────────────── */
function avisa(html, tipo='ok'){
  const d = document.createElement('div');
  d.className = 'aviso'; d.dataset.tipo = tipo;
  d.innerHTML = `<span class="aviso-glifo" aria-hidden="true">${tipo==='erro'?'⚠':'◈'}</span><span>${html}</span>`;
  E.avisos.append(d);
  setTimeout(()=>{ d.classList.add('aviso--saindo'); setTimeout(()=>d.remove(),200); }, 4200);
}

/* ── o texto da mensagem: markdown mínimo + a ÊNFASE EM DOURADO ──────────── */
function corpoHTML(txt){
  let h = esc(txt);
  h = h.replace(/`([^`\n]+)`/g, (_,c)=>`<code translate="no">${c}</code>`);
  h = h.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');       // ênfase -> dourado
  h = h.replace(/(^|[\s(])\*([^*\n]+)\*/g, '$1<em>$2</em>');
  // comando ANTES de caminho: senão `/concluir` é confundido com um path
  h = h.replace(/(^|\s)(\/(?:goal|plan|concluir|parar|quem|decidi|refaz))\b/g,
    '$1<span class="cmd" translate="no">$2</span>');
  /* caminho de verdade: precisa de uma segunda barra ou de extensão.
     O `<wbr>` depois de cada `/` dá ao navegador onde quebrar. Sem ele, um caminho
     longo quebrava no meio da palavra — na tela saía `/.clau` numa linha e `de/` na
     outra, e no celular isso é a regra, não a exceção. `<wbr>` não entra na cópia:
     quem copia da tela leva o caminho inteiro. */
  h = h.replace(/(^|[\s(])(~?\/[\w.~-]+(?:\/[\w.~-]+)+\/?|~?\/[\w~-]+\.\w{2,4})/g,
    (_, antes, p) => `${antes}<span class="caminho">${p.replace(/\//g, '/<wbr>')}</span>`);
  /* Endereço vira link. Ele lê o mapa de retomada no celular, e a linha do painel
     (`painel — ` seguido do endereço local) era texto morto: dá para ver e não dá
     para ir. Só `http`/`https` — nada de `javascript:` ou `data:`, que é onde mora
     o abuso — e `noopener` porque a aba nova não tem por que alcançar esta. O texto
     já passou por `esc()` lá em cima, então o que casa aqui é a forma escapada.
     ⚠️ Sem endereço literal neste comentário: o gate de offline procura o esquema no
     arquivo inteiro e não distingue comentário de código. Ele está certo — a
     disciplina é minha. */
  h = h.replace(/\bhttps?:\/\/[^\s<>"')\]]+/g, u => {
    const limpo = u.replace(/[.,;:]+$/, '');          // pontuação final é da frase
    const resto = u.slice(limpo.length);
    return `<a href="${limpo}" target="_blank" rel="noopener noreferrer">${limpo}</a>${resto}`;
  });
  // Wikilink do Obsidian: ele pediu o documento "na versão renderizada do Obsidian",
  // e `[[nome]]` é a marca dela. Vira rótulo legível — sem virar link para lugar
  // nenhum, porque o vault não é servido por aqui e um link que não abre mente.
  h = h.replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g,
    (_, alvo, rotulo) => `<span class="wikilink">${(rotulo || alvo).trim()}</span>`);
  h = h.replace(/(^|\s)@(all|todas)\b/gi, '$1<span class="mencao mencao--todas">@todas</span>');
  h = h.replace(/(^|\s)@([a-z0-9_-]{2,20})\b/gi,
    // as DUAS variantes: `-t` para o papel palha, viva para o cartão do dono (carvão)
    (_,a,n)=>{ const c = corDe(n.toLowerCase());
      return `${a}<span class="mencao" style="--ia-t:var(--${c}-t);--ia:var(--${c})">@${esc(n)}</span>`; });

  return h.split(/\n{2,}/).map(bloco=>{
    const linhas = bloco.split('\n');
    // `---` sozinho é régua, não parágrafo. O mapa de retomada usa uma antes do
    // fecho e ela aparecia como três hifens soltos no meio do texto.
    if (/^\s*-{3,}\s*$/.test(bloco)) return '<hr class="regua">';
    if (linhas.every(l => /^\s*[-*·]\s+/.test(l) || !l.trim()))
      return '<ul>' + linhas.filter(l=>l.trim()).map(l=>`<li>${l.replace(/^\s*[-*·]\s+/,'')}</li>`).join('') + '</ul>';
    return '<p>' + linhas.join('<br>') + '</p>';
  }).join('');
}

/* ── render da sala ──────────────────────────────────────────────────────── */
function paraLegivel(para){
  const l = Array.isArray(para) ? para : (para ? [para] : []);
  // Lista VAZIA é "ninguém", nunca "todas". Numa sala de 3+, postar sem `@` não chama
  // ninguém — o CLI diz isso na cara (`→ ninguém` + aviso no stderr) e a UI pintava
  // **todas**. Quem lê o histórico jura que a sala inteira foi convocada; decide, cobra,
  // acusa atraso — em cima de uma mensagem que não tocou sino nenhum.
  //
  // "todas" tem um significado exato: `para` contendo `all`/`todas`. Ausência de
  // destinatário não é sinônimo de todos os destinatários; é o oposto.
  // Achado do worker `j1-app-paralelo`, medido contra `iachat_core.py:376-380`.
  if (!l.length) return {html:'<i>ninguém nominado</i>', lista:[]};
  if (l.length === 1 && /^(all|todas)$/i.test(l[0])) return {html:'<b>todas</b>', lista:S.naSala};
  return {html: l.map(n=>`<b style="--ia-t:var(--${corDe(n)}-t)">@${esc(n)}</b>`).join(', '), lista:l};
}

function noMsg(m, atraso=0){
  const d = new Date(m.ts);
  const art = document.createElement('article');
  art.className = 'msg' + (m.de === DONO ? ' msg--dono' : '');
  art.style.setProperty('--ia-t', `var(--${corDe(m.de)}-t)`);
  art.style.animationDelay = atraso + 'ms';
  art.dataset.n = m.n;
  art.id = 'msg-' + m.n;   // alvo do aria-activedescendant do log
  art.innerHTML = `
    <div class="msg-cabeca">
      <span class="msg-de">${esc(m.de)}</span>
      <span class="msg-seta" aria-hidden="true">→</span>
      <span class="msg-para">${paraLegivel(m.para).html}</span>
      <span class="msg-hora"><span class="msg-n">#${m.n}</span> · ${fmtHora.format(d)}</span>
    </div>
    <div class="msg-corpo">${corpoHTML(m.texto)}</div>
    <div class="msg-pe">
      <button type="button" class="msg-acao" tabindex="-1" data-acao="fio">ver o fio</button>
      <button type="button" class="msg-acao" tabindex="-1" data-acao="responder">responder a ${esc(m.de)}</button>
      <button type="button" class="msg-acao" tabindex="-1" data-acao="copiar">copiar</button>
    </div>`;
  return art;
}
function noDia(ts){
  const sep = document.createElement('div');
  sep.className = 'dia';
  sep.innerHTML = `<span class="dia-rot">${fmtDia.format(new Date(ts))}</span>`;
  return sep;
}

function desenhaMsgs(){
  const lista = S.filtro
    ? S.msgs.filter(m => (m.texto+' '+m.de).toLowerCase().includes(S.filtro))
    : S.msgs;
  E.vazio.hidden = lista.length > 0;
  // `aria-busy` enquanto a lista é refeita: sem isto, filtrar a busca recria 31 nós
  // dentro de uma região viva e o leitor de tela lê a sala inteira de novo.
  E.fio.setAttribute('aria-busy', 'true');
  E.fio.replaceChildren();
  let diaAtual = '';
  const frag = document.createDocumentFragment();
  lista.forEach((m,i)=>{
    const dia = new Date(m.ts).toDateString();
    if (dia !== diaAtual){ diaAtual = dia; frag.append(noDia(m.ts)); }
    frag.append(noMsg(m, Math.max(0, i - (lista.length - 9)) * 28));
  });
  E.fio.append(frag);
  E.fio.dataset.dia = diaAtual;
  E.fio.setAttribute('aria-busy', 'false');
  // a mensagem escolhida pode ter saído do filtro
  if (S.ativa && !E.fio.querySelector(`[data-n="${S.ativa}"]`)){
    S.ativa = null; E.fio.removeAttribute('aria-activedescendant');
  } else if (S.ativa) mensagemAtiva(S.ativa);
}

/** mensagem nova: anexa só ela. A lista não é redesenhada a cada evento. */
function anexaMsg(m){
  if (S.filtro) return desenhaMsgs();
  const dia = new Date(m.ts).toDateString();
  if (dia !== E.fio.dataset.dia){ E.fio.append(noDia(m.ts)); E.fio.dataset.dia = dia; }
  E.fio.append(noMsg(m));
  E.vazio.hidden = true;
}

/* ── groupchat: uma fala, duas linhas, uma sessão própria ─────────────────
   A linha 1 responde QUEM falou. A linha 2 responde COMO está a janela dessa
   sessão. O tamanho da sala (`m.bytes`, contador, peso) não participa de
   nenhuma conta abaixo — são grandezas diferentes. */
function gcNumeroPositivo(v){
  return typeof v === 'number' && Number.isFinite(v) && v > 0;
}
function gcTokens(v){
  if (!gcNumeroPositivo(v)) return '—';
  if (v >= 1000000) return (v/1000000).toFixed(v%1000000?1:0).replace('.',',') + 'M';
  if (v >= 1000) return Math.round(v/1000) + 'k';
  return String(Math.round(v));
}
function gcContexto(registro){
  const c = registro && registro.context && typeof registro.context === 'object'
    ? registro.context : {};
  const janela = c.context_window_tokens;
  const compactou = c.last_prompt_tokens === -1 ||
    c.reason === 'compacted_waiting_measurement';
  if (compactou) return {modo:'desconhecido', medindo:true, leitura:'medindo após compactação'};

  let tokens = null, modo = 'desconhecido';
  if (c.state === 'exact' && gcNumeroPositivo(c.last_prompt_tokens)){
    tokens = c.last_prompt_tokens; modo = 'exato';
  } else if (c.state === 'estimated' && gcNumeroPositivo(c.estimated_prompt_tokens)){
    tokens = c.estimated_prompt_tokens; modo = 'estimado';
  }
  if (modo === 'desconhecido' || !gcNumeroPositivo(janela))
    return {modo:'desconhecido', medindo:false, leitura:'contexto desconhecido'};

  const percentualReal = Math.max(0, Math.round(tokens / janela * 100));
  const percentual = Math.min(100, percentualReal);
  const aprox = modo === 'estimado' ? '≈' : '';
  return {
    modo, tokens, janela, percentual, percentualReal,
    risco: percentualReal >= 85 ? 'alto' : 'normal',
    leitura:`${aprox}${percentualReal}% · ${gcTokens(tokens)}/${gcTokens(janela)}`,
  };
}
function gcDesconhecido(ia){
  return {ia_id:ia,session_id:'',model_id:'',context:{state:'unknown'},
    liveness:{session_state:'unknown'},actions:[]};
}
function gcRegistroDaFala(m){
  const candidatos = GC.snapshots.filter(x => x && x.ia_id === m.de);
  const porNumero = candidatos.find(x => Number(x.message_n) === Number(m.n));
  if (porNumero) return porNumero;
  const instante = new Date(m.ts).getTime();
  let melhor = null, melhorTs = -Infinity;
  for (const item of candidatos){
    const ts = new Date((item.context||{}).sampled_at).getTime();
    // A telemetria da resposta pode ser gravada poucos segundos depois da
    // mensagem. Nunca usa um snapshot arbitrariamente futuro.
    if (Number.isFinite(ts) && ts <= instante + 30000 && ts > melhorTs){
      melhor = item; melhorTs = ts;
    }
  }
  if (melhor) return melhor;
  if (candidatos.length === 1) return candidatos[0];
  return GC.sessions.find(x => x && x.ia_id === m.de) || gcDesconhecido(m.de);
}
function gcBarraHTML(registro, compacto=false){
  const c = gcContexto(registro);
  const alto = c.risco === 'alto' ? ' data-risco="alto"' : '';
  const tipo = c.modo === 'estimado' ? 'estimado' :
    c.modo === 'exato' ? (c.risco === 'alto' ? 'exato · atenção' : 'exato') : 'desconhecido';
  const aria = c.modo === 'desconhecido'
    ? `Contexto de ${registro.ia_id || 'IA'} ${c.leitura}`
    : `Contexto ${c.modo} de ${registro.ia_id || 'IA'}: ${c.leitura}`;
  const progresso = c.modo === 'desconhecido'
    ? `<span class="gc-contexto-trilho" role="progressbar" aria-label="${esc(aria)}" aria-valuetext="${esc(c.leitura)}"></span>`
    : `<span class="gc-contexto-trilho" role="progressbar" aria-label="${esc(aria)}" aria-valuemin="0" ` +
      `aria-valuemax="${c.janela}" aria-valuenow="${c.tokens}" ` +
      `aria-valuetext="${esc(c.leitura)}"><span class="gc-contexto-valor" ` +
      `style="--gc-valor:${c.percentual}%"></span></span>`;
  return `<div class="gc-contexto${compacto?' gc-contexto--compacto':''}" ` +
    `data-modo="${c.modo}"${alto}>` +
    `<span class="gc-contexto-tipo">${tipo}</span>${progresso}` +
    `<span class="gc-contexto-leitura">${esc(c.leitura)}</span></div>`;
}
function gcHora(ts){
  const d = new Date(ts);
  return Number.isFinite(d.getTime()) ? fmtHora.format(d) : '—';
}
function gcEstadoAcao(valor){
  const v = String(valor||'').toLowerCase();
  if (['running','executing','executando','rodando','in_progress'].includes(v))
    return {chave:'rodando',rotulo:'Executando'};
  if (['completed','complete','success','succeeded','concluido','concluída','concluida'].includes(v))
    return {chave:'concluida',rotulo:'Concluído'};
  if (['failed','failure','error','erro','falhou'].includes(v))
    return {chave:'falhou',rotulo:'Falhou'};
  if (['pending','queued','fila','pendente'].includes(v))
    return {chave:'pendente',rotulo:'Pendente'};
  return {chave:'desconhecido',rotulo:'Estado desconhecido'};
}
function gcTextoAcao(v){
  if (Array.isArray(v)) return v.map(x=>String(x)).join(' ');
  if (v && typeof v === 'object') return JSON.stringify(v, null, 2);
  return String(v == null ? '' : v);
}
function gcAcoesHTML(registro){
  const acoes = registro && Array.isArray(registro.actions) ? registro.actions : [];
  if (!acoes.length) return '';
  const linhas = acoes.map((acao,i)=>{
    const a = acao && typeof acao === 'object'
      ? acao : {description_pt:gcTextoAcao(acao)};
    const estado = gcEstadoAcao(a.state || a.estado || a.status);
    const descricao = a.description_pt || a.descricao || a.description || a.title ||
      `Ação de terminal ${i+1}`;
    const tipo = a.type || a.tipo || a.tool || a.tool_name || 'Terminal';
    const comando = gcTextoAcao(a.command != null ? a.command : a.comando);
    const saida = gcTextoAcao(a.output != null ? a.output :
      (a.saida != null ? a.saida : (a.stderr != null ? a.stderr : a.stdout)));
    const corpo = `<div class="gc-acao-corpo">
      <h4>comando</h4><pre><code>${esc(comando || 'não reportado')}</code></pre>
      <h4>saída</h4><pre><code>${esc(saida || 'não reportada')}</code></pre>
    </div>`;
    return `<details class="gc-acao" data-estado="${estado.chave}">
      <summary><span class="gc-acao-estado">${estado.rotulo}</span>
        <span class="gc-acao-titulo">${esc(descricao)}</span>
        <span class="gc-acao-tipo">${esc(tipo)}</span></summary>${corpo}</details>`;
  }).join('');
  return `<section class="gc-acoes" aria-label="Ações de terminal desta resposta">
    <h3>Ações <span class="num">${acoes.length}</span></h3>${linhas}</section>`;
}
function gcFalaHTML(m){
  const registro = gcRegistroDaFala(m);
  const ia = corDe(m.de);
  const modelo = registro.model_id || 'modelo não informado';
  const sessao = registro.session_id || 'sessão não informada';
  return `<article class="gc-fala" style="--ia-t:var(--${ia}-t)" data-msg="${Number(m.n)||0}">
    <header class="gc-identidade">
      <span class="gc-identidade-ponto" aria-hidden="true"></span>
      <strong>${esc(m.de)}</strong>
      <span class="gc-modelo">${esc(modelo)} · ${esc(sessao)}</span>
      <time datetime="${esc(m.ts||'')}">${gcHora(m.ts)}</time>
    </header>
    ${gcBarraHTML(registro)}
    <div class="gc-texto">${corpoHTML(m.texto||'')}</div>
    ${gcAcoesHTML(registro)}
  </article>`;
}
function gcVivacidade(registro){
  const vivo = registro && registro.liveness || {};
  const ts = vivo.last_signal_at;
  const idade = ts ? (Date.now() - new Date(ts).getTime())/1000 : Infinity;
  if (vivo.session_state === 'error' || vivo.session_state === 'dead')
    return {estado:'erro',rotulo:'sem sinal'};
  if (idade <= 90) return {estado:'ok',rotulo:'fresco'};
  if (idade <= 300) return {estado:'atencao',rotulo:'lento'};
  return {estado:'erro',rotulo:ts ? 'sem sinal' : 'desconhecido'};
}
function gcRenderSessoes(){
  if (!GC.sessoes) return;
  const html = GC.sessions.length ? GC.sessions.map(registro=>{
    const ia = corDe(registro.ia_id), vida = gcVivacidade(registro);
    return `<section class="gc-sessao" style="--ia-t:var(--${ia}-t)">
      <header><span class="gc-identidade-ponto" aria-hidden="true"></span>
        <strong>${esc(registro.ia_id)}</strong>
        <span class="gc-vida" data-estado="${vida.estado}">${vida.rotulo}</span></header>
      <p>${esc(registro.model_id||'modelo não informado')} · ${esc(registro.session_id||'sessão não informada')}</p>
      ${gcBarraHTML(registro, true)}
    </section>`;
  }).join('') : `<section class="gc-estado-vazio"><span aria-hidden="true">◇</span>
    <h3>Nenhuma IA ativa</h3><p>As sessões aparecem quando entram na sala.</p></section>`;
  if (GC.sessoesHTML === html) return;
  GC.sessoes.innerHTML = html;
  GC.sessoesHTML = html;
}
function gcRender(){
  if (!GC.fio) return;
  const msgs = (GC.carregada ? GC.msgs :
    S.msgs.filter(m=>m.de !== S.sala.papel)).slice(-80);
  const html = msgs.length ? msgs.map(gcFalaHTML).join('') :
    `<section class="gc-estado-vazio"><span aria-hidden="true">◇</span>
      <h3>O groupchat está em silêncio</h3><p>Sem @, o compositor abaixo envia a todas as IAs ativas.</p></section>`;
  // Compara a saída derivada, não o DOM vivo: um <details> aberto pelo dono não
  // pode transformar o tick limpo em motivo para reconstruir a conversa inteira.
  if (GC.fioHTML !== html){
    GC.fio.innerHTML = html;
    GC.fioHTML = html;
  }
  gcRenderSessoes();
}

function gcAtualizaAvisoCorte(corte, primeira){
  if (!GC.aviso) return;
  const c = corte && typeof corte === 'object' ? corte : {};
  const motivo = String(c.motivo || '');
  const omitidas = Math.max(0, Number(c.omitidas) || 0);
  const pendentes = Math.max(0, Number(c.pendentes) || 0);
  const telemetria = Math.max(0, Number(c.telemetria_omitida) || 0) +
    Math.max(0, Number(c.sessoes_omitidas) || 0);

  // O corte inicial não desaparece no tick limpo de dois segundos depois. Ele
  // é parte do contexto desta tela e fica visível enquanto a aba estiver aberta.
  if (primeira && c.ativo && c.direcao === 'inicio' && omitidas){
    GC.corteInicial = {omitidas, limites:{...GC.limites}};
  }
  GC.corteAtual = c.ativo && pendentes ? {pendentes} : null;
  if (motivo.includes('item_maior_que_teto')){
    GC.itensGrandesOmitidos += Math.max(1, omitidas - pendentes);
  }
  GC.telemetriaOmitida = Math.max(GC.telemetriaOmitida, telemetria);

  const partes = [];
  if (GC.corteInicial){
    const lim = GC.corteInicial.limites || {};
    partes.push(`Contexto inicial limitado a ${Number(lim.itens)||'—'} mensagens / ` +
      `${bytesLegiveis(Number(lim.bytes)||0)}; ${GC.corteInicial.omitidas} mensagens ` +
      `anteriores permanecem no histórico da sala.`);
  }
  if (GC.corteAtual){
    partes.push(`${GC.corteAtual.pendentes} mensagens novas aguardam o próximo ciclo.`);
  }
  if (GC.itensGrandesOmitidos){
    partes.push(`${GC.itensGrandesOmitidos} mensagens excederam o teto da resposta; ` +
      `permanecem no histórico da sala.`);
  }
  if (GC.telemetriaOmitida){
    partes.push(`Telemetria reduzida: ${GC.telemetriaOmitida} registros ficaram fora da resposta.`);
  }
  const texto = partes.join(' ');
  if (GC.aviso.textContent !== texto) GC.aviso.textContent = texto;
  GC.aviso.hidden = !texto;
}

async function gcCarregar(){
  const primeira = !GC.carregada;
  const desde = Number.isSafeInteger(GC.cursor) && GC.cursor >= 0 ? GC.cursor : 0;
  const r = await fetch(url('/api/groupchat','desde='+desde), {cache:'no-store'});
  if (!r.ok) throw new Error('HTTP '+r.status);
  const d = await r.json();
  GC.snapshots = Array.isArray(d.snapshots) ? d.snapshots : [];
  GC.sessions = Array.isArray(d.sessions) ? d.sessions : [];
  GC.limites = d.limites && typeof d.limites === 'object' ? d.limites : GC.limites;
  const novas = Array.isArray(d.msgs) ? d.msgs : [];
  if (primeira){
    GC.msgs = novas.slice(-80);
  } else {
    const vistas = new Set(GC.msgs.map(m=>Number(m.n)));
    for (const m of novas){
      const n = Number(m.n);
      if (!vistas.has(n)){ GC.msgs.push(m); vistas.add(n); }
    }
    GC.msgs = GC.msgs.slice(-80);
  }
  const recebido = Number(d.ultima);
  if (Number.isSafeInteger(recebido) && recebido >= desde) GC.cursor = recebido;
  GC.carregada = true;
  gcAtualizaAvisoCorte(d.corte, primeira);
  if (GC.fonte) GC.fonte.textContent = 'telemetria: ' + (d.fonte || 'desconhecida');
}
async function gcTick(){
  if (GC.ocupado || !GC.raiz) return;
  GC.ocupado = true;
  try{ await gcCarregar(); }
  catch(e){
    if (!GC.carregada) GC.msgs = S.msgs.filter(m=>m.de !== S.sala.papel);
    GC.sessions = S.naSala.map(gcDesconhecido);
    GC.snapshots = [];
    if (GC.fonte) GC.fonte.textContent = 'telemetria: indisponível';
  } finally {
    gcRender(); GC.ocupado = false;
  }
}

function desenhaPresenca(){
  E.presenca.innerHTML = '';
  S.naSala.forEach(ia=>{
    const ult = [...S.msgs].reverse().find(m => m.de === ia);
    const vida = ult ? vidaDe(ult.ts) : 'fria';
    const sino = S.sinos[ia] || 0;
    const li = document.createElement('li');
    li.innerHTML = `<div class="selo" data-vida="${vida}" style="--ia:var(--${corDe(ia)})"
        title="${esc(ia)} — ${ult ? 'última fala há '+haQuanto(ult.ts) : 'ainda não falou'}">
        ${inicial(ia)}
        <span class="selo-vida" aria-hidden="true"></span>
        ${sino ? `<span class="selo-sino">${sino}</span>` : ''}
        <span class="oculto-visual">${esc(ia)}, ${vida === 'ativa' ? 'ativa agora' : vida === 'morna' ? 'ativa há pouco' : 'em silêncio'}${sino ? `, ${sino} mensagens pendentes` : ''}</span>
      </div>`;
    E.presenca.append(li);
  });
}

function desenhaCabeca(){
  E.contador.textContent = fmtNum.format(S.ultima);
  E.peso.textContent = bytesLegiveis(S.msgs.reduce((a,m)=>a+(m.bytes||0),0));
}

/* ── gaveta: fio, decisões, dia, arquivos ────────────────────────────────── */
function desenhaFio(){
  const lista = $('#fio-lista'), nota = $('#fio-nota');
  lista.innerHTML = '';
  if (!S.fio){ nota.hidden = false; return; }
  nota.hidden = true;
  const base = S.msgs.find(m => m.n === S.fio);
  if (!base) return;
  const par = new Set([base.de, ...(Array.isArray(base.para)?base.para:[base.para]).filter(Boolean)]);
  const doFio = S.msgs.filter(m=>{
    const alvos = (Array.isArray(m.para)?m.para:[m.para]).filter(Boolean);
    return par.has(m.de) && (alvos.some(a=>par.has(a)) || alvos.length === 0);
  });
  doFio.forEach(m=>{
    const li = document.createElement('li');
    li.className = 'fio-msg';
    li.style.setProperty('--ia-t', `var(--${corDe(m.de)}-t)`);
    li.innerHTML = `<div class="fio-de">${esc(m.de)} <span style="color:var(--tinta-3);font-weight:400">#${m.n}</span></div>
                    <div class="fio-txt">${esc(seco(m.texto))}</div>`;
    li.addEventListener('click', ()=> irPara(m.n));
    lista.append(li);
  });
}

/* ⚠️ MEDIDO 18/08 na sala real: a regra antiga desta aba procurava o COMANDO
   `/decidi` (ou `/concluir`) no texto — e ele aparece **0 vezes** em 29
   mensagens, então a aba estava condenada a nascer vazia. `/decidi` não é digitado
   na sala: está como `onde:'terminal'` na lista COMANDOS aqui em cima, porque o
   registro durável dele é um arquivo que só o CLI escreve.
   O que a sala usa de verdade é o MARCADOR no começo da linha, e é isso que o
   `bin/iachat-report` (RE_MARCA) extrai — 8 marcações em 2 mensagens (#26, #29).
   Esta regra é a mesma dele, byte a byte no conjunto de marcadores: uma
   mensagem pode carregar várias, e cada uma vira um cartão. */
const MARCAS = ['DECIDIDO','PENDENTE','BLOQUEIO','PERGUNTA'];
const RE_MARCA = new RegExp(
  '^[ \\t]*(?:[*_]{0,2})(' + MARCAS.join('|') + ')(?:[*_]{0,2})[ \\t]*:[ \\t]*(.+)$', 'i');
function marcacoesDe(txt){
  const fora = [];
  for (const linha of String(txt||'').split('\n')){
    const m = RE_MARCA.exec(linha);
    if (m) fora.push({marca:m[1].toUpperCase(), corpo:m[2].trim()});
  }
  return fora;
}

function desenhaDecisoes(){
  const el = $('#decisoes');
  const itens = [];
  [...S.msgs].reverse().forEach(m =>                       // mensagem mais nova primeiro,
    marcacoesDe(m.texto).forEach(x =>                      // ordem interna preservada
      itens.push({...x, de:m.de, n:m.n, ts:m.ts})));
  el.innerHTML = itens.length ? '' :
    '<li class="nada">Nada marcado ainda. Comece uma linha com <code translate="no">DECIDIDO:</code> — também valem PENDENTE:, BLOQUEIO: e PERGUNTA:.</li>';
  itens.forEach(x=>{
    const li = document.createElement('li');
    li.className = 'cartao';
    li.dataset.marca = x.marca;
    li.style.setProperty('--ia-t', `var(--${corDe(x.de)}-t)`);
    li.innerHTML = `<div class="decisao-txt"><span class="marca-selo">${esc(x.marca)}</span>${corpoHTML(x.corpo)}</div>
      <div class="decisao-pe"><span class="selo-ia">${esc(x.de)}</span>
      <span>·</span><span>#${x.n} · há ${haQuanto(x.ts)}</span></div>`;
    li.addEventListener('click', ()=> irPara(x.n));
    el.append(li);
  });
}

function desenhaDia(){
  const hoje = new Date().toDateString();
  const doDia = S.msgs.filter(m => new Date(m.ts).toDateString() === hoje);
  const vozes = new Set(doDia.map(m=>m.de));
  $('#medidas').innerHTML = [
    ['mensagens', fmtNum.format(doDia.length)],
    ['IAs que falaram', String(vozes.size)],
    ['peso do dia', bytesLegiveis(doDia.reduce((a,m)=>a+(m.bytes||0),0))],
    ['na sala', String(S.naSala.length)],
  ].map(([r,n])=>`<div class="medida"><span class="medida-n">${n}</span><span class="medida-rot">${r}</span></div>`).join('');

  const linha = $('#linha');
  linha.innerHTML = doDia.length ? '' : '<li class="nada">Nada aconteceu hoje ainda.</li>';
  [...doDia].reverse().slice(0,24).forEach(m=>{
    const li = document.createElement('li');
    li.className = 'linha-item';
    li.style.setProperty('--ia-t', `var(--${corDe(m.de)}-t)`);
    li.innerHTML = `<div class="linha-hora">${fmtHora.format(new Date(m.ts))}</div>
      <div class="linha-txt"><b>${esc(m.de)}</b> — ${esc(seco(m.texto).slice(0,88))}${m.texto.length>88?'…':''}</div>`;
    li.addEventListener('click', ()=> irPara(m.n));
    linha.append(li);
  });
}

/* Esta aba NÃO mostra reserva de `ia-claim` — mostra arquivo CITADO na sala,
   derivado do texto das mensagens. A reserva de verdade vive em
   `$IACHAT_HOME/claims/*.json` e não trafega por nenhuma rota do servidor
   (`/api/estado`, `/api/sala`, `/api/stream` são as três que existem), então a
   interface não tem como saber dela. Conferido em 18/08: a pasta `claims/` nem
   existe ainda. O título e a nota do painel dizem isso — a aba não promete
   reserva e entrega citação. */
function desenhaReservas(){
  const el = $('#reservas');
  const mapa = new Map();
  S.msgs.forEach(m=>{
    (m.texto.match(/(?:~|\/Users)[\w./~-]{8,}/g)||[]).forEach(a=>mapa.set(a,m.de));
  });
  el.innerHTML = mapa.size ? '' :
    '<li class="nada">Nenhum arquivo citado na sala.</li>';
  [...mapa].slice(0,30).forEach(([arq,quem])=>{
    const li = document.createElement('li');
    li.className = 'reserva';
    li.style.setProperty('--ia-t', `var(--${corDe(quem)}-t)`);
    li.innerHTML = `<span class="reserva-arq" title="${esc(arq)}">${esc(arq)}</span>
                    <span class="reserva-quem" title="última menção">${esc(quem)}</span>`;
    el.append(li);
  });
}

function desenhaGaveta(){ desenhaFio(); desenhaDecisoes(); desenhaDia(); desenhaReservas(); }

/* ── A REGRA QUE MUDA O PROTOCOLO: sem @ = todas ─────────────────────────── */
function alvosDoTexto(t){
  const m = [...t.matchAll(/(^|\s)@([a-z0-9_-]{2,20})\b/gi)].map(x=>x[2].toLowerCase());
  if (m.some(n=>/^(all|todas)$/.test(n))) return [];
  return [...new Set(m)];
}

function atualizaDestino(){
  const alvos = alvosDoTexto(E.texto.value);
  const todas = alvos.length === 0;

  E.destino.dataset.modo = todas ? 'todas' : 'nominada';
  if (todas){
    E.destino.style.removeProperty('--alvo');
    E.destinoTxt.innerHTML = document.documentElement.dataset.janela === 'groupchat'
      ? 'sem <code>@</code>: isto vai para <b>todas as IAs ativas</b>'
      : 'isto vai para <b>todas</b> as IAs da sala';
    E.enviarRot.textContent = 'Enviar a Todas';
  } else {
    E.destino.style.setProperty('--alvo', `var(--${corDe(alvos[0])}-t)`);
    E.destinoTxt.innerHTML = alvos.length === 1
      ? `só <b>@${esc(alvos[0])}</b> será notificada`
      : `só <b>${alvos.length}</b> serão notificadas: ${alvos.map(a=>'@'+esc(a)).join(', ')}`;
    E.enviarRot.textContent = 'Enviar a ' + alvos.map(a=>'@'+a).join(', ');
  }

  E.destinoAlvos.innerHTML = S.naSala.map(ia=>{
    const aceso = todas || alvos.includes(ia);
    return `<li class="destino-alvo" data-aceso="${aceso?'sim':'nao'}"
      style="--ia-t:var(--${corDe(ia)}-t)" title="${esc(ia)}${aceso?' será notificada':' não será notificada'}">${inicial(ia)}</li>`;
  }).join('');
}

/* ── paleta de comandos ──────────────────────────────────────────────────── */
/* O foco fica no campo de texto enquanto a paleta está aberta — é o que permite
   continuar digitando. Para o leitor de tela saber qual comando está sob as setas,
   o campo vira `combobox` ENQUANTO a paleta existe e aponta a opção ativa por
   `aria-activedescendant`. Fechada, o campo volta a ser um textarea comum: quem
   escreve na sala não deve ouvir "caixa combinada" o tempo todo. */
let paletaIdx = 0;
/* A paleta tem dois modos e eles não se misturam: `lista` é o combobox de
   comandos (setas navegam, Enter escolhe); `painel` é a RESPOSTA — o resultado
   do `/quem` ou a linha do terminal. No painel não há opção para navegar, e as
   setas não podem fingir que há. */
let paletaModo = 'lista';
function abrePaleta(prefixo){
  const itens = COMANDOS.filter(c => c.cmd.startsWith(prefixo));
  if (!itens.length) return fechaPaleta();
  paletaIdx = 0;
  paletaModo = 'lista';
  E.paleta.setAttribute('role', 'listbox');
  E.paleta.removeAttribute('aria-label');
  E.paleta.hidden = false;
  E.paleta.innerHTML = itens.map((c,i)=>`
    <button type="button" class="paleta-item" role="option" tabindex="-1"
            id="cmd-${c.cmd.slice(1)}" data-cmd="${c.cmd}"
            data-vindouro="${ONDE[c.onde].vindouro}" aria-selected="${i===0}">
      <span class="paleta-cmd" translate="no">${c.cmd}</span>
      <span class="paleta-desc">${esc(c.desc)}</span>
      <span class="paleta-quem">${ONDE[c.onde].rotulo}</span>
    </button>`).join('');
  $$('.paleta-item', E.paleta).forEach(b=>
    b.addEventListener('click', ()=> escolhePaleta(b.dataset.cmd)));
  E.texto.setAttribute('role', 'combobox');
  E.texto.setAttribute('aria-expanded', 'true');
  E.texto.setAttribute('aria-controls', 'paleta');
  E.texto.setAttribute('aria-autocomplete', 'list');
  marcaPaleta();
}
function fechaPaleta(){
  E.paleta.hidden = true;
  E.paleta.classList.remove('paleta--painel');
  paletaModo = 'lista';
  E.texto.removeAttribute('role');
  E.texto.removeAttribute('aria-expanded');
  E.texto.removeAttribute('aria-controls');
  E.texto.removeAttribute('aria-autocomplete');
  E.texto.removeAttribute('aria-activedescendant');
}
function marcaPaleta(){
  const itens = $$('.paleta-item', E.paleta);
  itens.forEach((b,i)=> b.setAttribute('aria-selected', String(i === paletaIdx)));
  const sel = itens[paletaIdx];
  if (!sel) return;
  E.texto.setAttribute('aria-activedescendant', sel.id);
  sel.scrollIntoView({block:'nearest'});
}
/* ── a paleta como SUPERFÍCIE DE RESPOSTA ─────────────────────────────────
   Tudo o que este recurso desenha vive dentro de `#paleta`, que é meu. Três
   agentes trabalham nesta pasta e `estilo.css` não é minha fronteira — por isso
   nenhuma classe nova: só `.paleta-item`, `.paleta-cmd`, `.paleta-desc` e
   `.paleta-quem`, que já existem. */
function painelPaleta(html, rotulo){
  fechaPaleta();                       // limpa o combobox: aqui não há opção
  paletaModo = 'painel';
  E.paleta.setAttribute('role', 'group');
  E.paleta.setAttribute('aria-label', rotulo);
  // Painel de RESULTADO não flutua: o combobox de "/" pode flutuar porque tem
  // meia dúzia de linhas; o resultado do /quem cresce com a frota e, flutuando,
  // cobria a conversa pelo meio (defeito apontado pelo dono, 18/08). No fluxo,
  // o compositor cresce e o chat SOBE; o ✕ e o Esc fazem descer.
  E.paleta.classList.add('paleta--painel');
  E.paleta.innerHTML =
    `<div class="paleta-topo"><span class="paleta-rotulo">${esc(rotulo)}</span>` +
    `<button type="button" class="paleta-fecha" data-cancelar aria-label="fechar painel">✕</button></div>` + html;
  E.paleta.hidden = false;
  requestAnimationFrame(()=> E.paleta.scrollIntoView({block:'nearest'}));
  const b = $('[data-copiar]', E.paleta);
  if (b) b.addEventListener('click', ()=> copia(b.dataset.copiar));
  // Confirmação dos comandos que gastam ou matam: o botão carrega o comando,
  // os argumentos e o recibo server-side da previsão; `confirmaComando`
  // acrescenta `confirmado` e chama.
  $$('[data-confirmar]', E.paleta).forEach(bt =>
    bt.addEventListener('click', ()=> confirmaComando(bt.dataset.confirmar, bt.dataset.payload)));
  $$('[data-cancelar]', E.paleta).forEach(bt =>
    bt.addEventListener('click', ()=> { fechaPaleta(); E.texto.focus(); }));
}

/* Painel de resultado fecha ao clicar FORA — pergunta do dono ("fica pra cima o
   tempo todo?"). Esc e ✕ continuam; clicar dentro (copiar, confirmar) não fecha.
   Só vale no modo 'painel': o combobox de "/" já fecha pelos próprios caminhos. */
document.addEventListener('pointerdown', ev => {
  if (paletaModo !== 'painel' || E.paleta.hidden) return;
  if (E.paleta.contains(ev.target) || document.getElementById('compositor')?.contains(ev.target)) return;
  fechaPaleta();
});

async function copia(txt){
  try{
    await navigator.clipboard.writeText(txt);
    avisa('Linha copiada. <b>Cole no terminal.</b>');
  }catch{
    // Sem permissão de área de transferência a linha continua na tela, e
    // selecionável — dizer "copiei" sem ter copiado seria o mesmo defeito
    // que este recurso existe para matar.
    avisa('Não consegui copiar — a linha está aí para selecionar.', 'erro');
  }
}

/* O que NÃO atravessa não fica mudo: mostra a linha e o porquê. */
function mostraLinha(c){
  painelPaleta(`
    <div class="paleta-item">
      <span class="paleta-cmd" translate="no">${c.cmd}</span>
      <span class="paleta-desc"><b>Só no terminal.</b> ${esc(c.porque || '')}</span>
      <span class="paleta-quem">não atravessa</span>
    </div>
    <div class="paleta-item">
      <code class="paleta-desc" translate="no">${esc(c.linha)}</code>
      <button type="button" class="paleta-cmd" data-copiar="${esc(c.linha)}">copiar</button>
    </div>`, `${c.cmd}: a linha para o terminal`);
}

/* `/quem` atravessa porque só LÊ. Os demais comandos do dono também
   atravessam (decisão dele, fase 9) — mas com allowlist fechada, `--de` do
   servidor e confirmação explícita; quem os chama é `rodaComando`, abaixo. */
async function rodaQuem(){
  painelPaleta('<div class="paleta-item"><span class="paleta-desc">consultando…</span></div>',
               '/quem: consultando');
  let d;
  try{
    const r = await fetch(url('/api/quem'));
    d = await r.json();
    if (!r.ok || d.erro) throw new Error(d.erro || ('HTTP ' + r.status));
  }catch(e){
    // Degrada como o cabeçalho deste arquivo promete: servidor sem a rota (o
    // do bundle é reserva e não tem) vira a linha do terminal, não um erro sem saída.
    return mostraLinha({cmd:'/quem', linha:'iachat-comando quem',
      porque:'este servidor não respondeu (' + e.message + '), mas o CLI responde.'});
  }
  const linhas = (d.quem || []).map(x=>`
    <div class="paleta-item">
      <span class="paleta-cmd" translate="no">${esc(x.ia)}</span>
      <span class="paleta-desc">${esc(x.estado)} · ${esc(x.fazendo)}</span>
      <span class="paleta-quem">${esc(x.ha || '')}</span>
    </div>`).join('');
  painelPaleta(`
    <div class="paleta-item">
      <span class="paleta-cmd" translate="no">${esc(d.missao || '—')}</span>
      <span class="paleta-desc">${esc(d.estado || 'nenhuma missão aberta')}</span>
      <span class="paleta-quem">agora</span>
    </div>${linhas}`, '/quem: quem está vivo');
}

/* ── os comandos do dono, DE VERDADE, pelo servidor ──────────────────────
   A paleta chama o `iachat-comando` através da allowlist de `servir.py`:
   argv constante, texto do dono pelo stdin do comando (`--via-app`), `--de`
   é o papel do servidor. O que gasta ou mata passa por `painelConfirma`:
   a previsão (`seco`) aparece ANTES, e só o botão confirma — o servidor
   RECUSA o pedido sem o recibo daquela previsão, então isto é gate, não cortesia.
   Servidor sem a rota (bundle velho) degrada para a linha do terminal. */
const ROTAS_CMD = {
  '/goal':'/api/goal', '/plan':'/api/plan', '/concluir':'/api/concluir',
  '/parar':'/api/parar', '/refaz':'/api/refaz', '/decidi':'/api/decidi',
};

/** POST na rota do comando. `{degrada:true}` quando o servidor não tem a
    rota (404/501/rede) — o painel mostra a linha do terminal, não um beco. */
async function pedeComando(c, payload){
  try{
    const r = await fetch(url(ROTAS_CMD[c.cmd]), {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(payload || {}),
    });
    if (r.status === 404 || r.status === 501) return {degrada:true};
    let d = {}; try{ d = await r.json(); }catch(e){}
    if (!r.ok && !('ok' in d)) d = {ok:false, erro: d.erro || ('HTTP ' + r.status)};
    return d;
  }catch(e){
    return {degrada:true};
  }
}

function rodaComando(c, txt){
  const arg = txt.slice(c.cmd.length).trim();
  if (c.cmd === '/quem')      return rodaQuem();
  if (c.cmd === '/goal')      return rodaGoal(c, arg);
  if (c.cmd === '/plan')      return rodaPlan(c, arg);
  if (c.cmd === '/concluir')  return rodaConcluir(c, arg);
  if (c.cmd === '/parar')     return rodaParar(c);
  if (c.cmd === '/refaz')     return rodaRefaz(c, arg);
  if (c.cmd === '/decidi')    return rodaDecidi(c, arg);
  return mostraLinha(c);
}

function painelEspera(c, acao){
  painelPaleta(`<div class="paleta-item"><span class="paleta-desc">${acao}</span></div>`,
               `${c.cmd}: ${acao.replace('…','')}`);
}
function painelUso(c, titulo, ex){
  painelPaleta(`
    <div class="paleta-item">
      <span class="paleta-cmd" translate="no">${c.cmd}</span>
      <span class="paleta-desc">${esc(titulo)}</span>
      <span class="paleta-quem">como usar</span>
    </div>
    <div class="paleta-item">
      <code class="paleta-desc" translate="no">${esc(ex)}</code>
    </div>`, `${c.cmd}: como usar`);
}
function painelResultado(c, d){
  if (d.ok === false || d.erro){
    // Recusa do CLI (exit 2/3) é resposta, não defeito: mostra tal qual.
    return painelPaleta(`
      <div class="paleta-item">
        <span class="paleta-cmd" translate="no">${c.cmd}</span>
        <span class="paleta-desc"><code translate="no" style="white-space:pre-wrap">${esc(d.erro || 'o comando recusou')}</code></span>
        <span class="paleta-quem">recusado</span>
      </div>`, `${c.cmd}: resposta do comando`);
  }
  const aviso = d.aviso ? `
    <div class="paleta-item">
      <span class="paleta-desc"><code translate="no" style="white-space:pre-wrap">${esc(d.aviso)}</code></span>
    </div>` : '';
  painelPaleta(`
    <div class="paleta-item">
      <span class="paleta-cmd" translate="no">${c.cmd}</span>
      <span class="paleta-desc"><code translate="no" style="white-space:pre-wrap">${esc(d.saida || 'feito.')}</code></span>
      <span class="paleta-quem">feito</span>
    </div>${aviso}`, `${c.cmd}: resposta do comando`);
}
/** Previsão no painel + botão de confirmar. Nada aconteceu ainda: quem prova
    é o `seco` do CLI; o botão devolve o recibo emitido pelo servidor. */
function painelConfirma(c, previsao, payload, recibo){
  const confirmacao = Object.assign({}, payload || {}, {recibo});
  painelPaleta(`
    <div class="paleta-item">
      <span class="paleta-cmd" translate="no">${c.cmd}</span>
      <span class="paleta-desc"><code translate="no" style="white-space:pre-wrap">${esc(previsao)}</code></span>
      <span class="paleta-quem">previsão — nada aconteceu ainda</span>
    </div>
    <button type="button" class="paleta-item" data-confirmar="${c.cmd}"
            data-payload="${esc(JSON.stringify(confirmacao))}">
      <span class="paleta-cmd">confirmar</span>
      <span class="paleta-desc">${esc(c.confirma || 'executar agora')}</span>
      <span class="paleta-quem">gasta ou mata</span>
    </button>
    <button type="button" class="paleta-item" data-cancelar="1">
      <span class="paleta-cmd">cancelar</span>
      <span class="paleta-desc">não fazer nada</span>
      <span class="paleta-quem">voltar</span>
    </button>`, `${c.cmd}: confirmar antes de ${c.cmd === '/parar' ? 'parar' : 'gastar'}`);
}
async function confirmaComando(cmd, payloadJson){
  const c = COMANDOS.find(x => x.cmd === cmd);
  if (!c) return;
  let payload = {};
  try{ payload = JSON.parse(payloadJson || '{}'); }catch(e){}
  payload.confirmado = true;
  painelEspera(c, 'executando…');
  const d = await pedeComando(c, payload);
  if (d.degrada) return mostraLinha(c);
  painelResultado(c, d);
}

async function rodaGoal(c, arg){
  if (!arg) return painelUso(c, 'diga o enunciado da rodada', '/goal <o objetivo>');
  painelEspera(c, 'abrindo a missão…');
  const d = await pedeComando(c, {texto: arg});
  if (d.degrada) return mostraLinha(c);
  painelResultado(c, d);
}
function argsPlan(arg){
  /* O confirmar-antes mostra o que o CLI estimou. As saídas de escape
     (--nivel, --ias, --todas) atravessam o JSON do via-app, nunca o argv:
     o servidor continua com allowlist constante. */
  const out = {};
  const toks = String(arg || '').trim().split(/\s+/).filter(Boolean);
  for (let i = 0; i < toks.length; i++){
    const t = toks[i];
    if (t === 'colher'){ out.colher = true; continue; }
    if (t === '--todas'){ out.todas = true; continue; }
    if (t === '--nivel' || t.startsWith('--nivel=')){
      const v = t.includes('=') ? t.slice(t.indexOf('=') + 1) : toks[++i];
      if (v === '1' || v === '2' || v === '3') out.nivel = Number(v);
      continue;
    }
    if (t === '--ias' || t.startsWith('--ias=')){
      const v = t.includes('=') ? t.slice(t.indexOf('=') + 1) : toks[++i];
      if (v) out.ias = [v];
    }
  }
  return out;
}
async function rodaPlan(c, arg){
  const extra = argsPlan(arg);
  if (extra.colher){
    // colher só lê os planos do disco e devolve o resumo à sala: sem confirmação.
    painelEspera(c, 'colhendo os planos…');
    const d = await pedeComando(c, {colher: true});
    if (d.degrada) return mostraLinha(c);
    return painelResultado(c, d);
  }
  const payload = {seco: true};
  if (extra.todas) payload.todas = true;
  if (extra.nivel) payload.nivel = extra.nivel;
  if (extra.ias) payload.ias = extra.ias;
  painelEspera(c, 'prevendo o despacho…');
  const d = await pedeComando(c, payload);
  if (d.degrada) return mostraLinha(c);
  if (d.ok === false || d.erro) return painelResultado(c, d);
  const confirmacao = {};
  if (extra.todas) confirmacao.todas = true;
  if (extra.nivel) confirmacao.nivel = extra.nivel;
  if (extra.ias) confirmacao.ias = extra.ias;
  painelConfirma(c, d.saida, confirmacao, d.recibo);
}
async function rodaConcluir(c, arg){
  painelEspera(c, 'autorizando…');
  const d = await pedeComando(c, {texto: arg});
  if (d.degrada) return mostraLinha(c);
  painelResultado(c, d);
}
async function rodaParar(c){
  painelEspera(c, 'vendo o que seria parado…');
  const d = await pedeComando(c, {seco: true});
  if (d.degrada) return mostraLinha(c);
  if (d.ok === false || d.erro) return painelResultado(c, d);
  painelConfirma(c, d.saida, {}, d.recibo);
}
async function rodaRefaz(c, arg){
  if (!arg){
    // Sem o nome da IA, mostra quem está na missão para ele escolher.
    painelEspera(c, 'vendo quem está na missão…');
    try{
      const r = await fetch(url('/api/quem'));
      const q = await r.json();
      const linhas = (q.quem || [])
        .filter(x => x.fazendo && x.fazendo !== '—')
        .map(x => `<div class="paleta-item">
          <span class="paleta-cmd" translate="no">${esc(x.ia)}</span>
          <span class="paleta-desc">${esc(x.estado)} · ${esc(x.fazendo)}</span>
        </div>`).join('');
      return painelPaleta(`
        <div class="paleta-item">
          <span class="paleta-cmd" translate="no">/refaz</span>
          <span class="paleta-desc">diga qual IA: <code translate="no">/refaz &lt;ia&gt;</code></span>
          <span class="paleta-quem">como usar</span>
        </div>${linhas}`, '/refaz: qual IA?');
    }catch(e){ return painelUso(c, 'diga qual IA redisparar', '/refaz <ia>'); }
  }
  painelEspera(c, 'prevendo a retomada…');
  const d = await pedeComando(c, {ia: arg, seco: true});
  if (d.degrada) return mostraLinha(c);
  if (d.ok === false || d.erro) return painelResultado(c, d);
  painelConfirma(c, d.saida, {ia: arg}, d.recibo);
}
async function rodaDecidi(c, arg){
  // A sintaxe do app: `/decidi <a decisão> | <o motivo>`. O motivo é
  // obrigatório — gate do iachat-decide — e o `|` é o jeito de pedir os dois
  // sem montar flag nenhuma no cliente.
  const corte = arg.indexOf('|');
  if (corte < 0)
    return painelUso(c, 'a decisão e o motivo, separados por |',
                     '/decidi <a decisão> | <o motivo>');
  const texto = arg.slice(0, corte).trim();
  const porque = arg.slice(corte + 1).trim();
  if (!texto || !porque)
    return painelUso(c, 'decisão e motivo precisam de conteúdo',
                     '/decidi <a decisão> | <o motivo>');
  painelEspera(c, 'registrando a decisão…');
  const d = await pedeComando(c, {texto, porque});
  if (d.degrada) return mostraLinha(c);
  painelResultado(c, d);
}

function escolhePaleta(cmd){
  if (cmd === '/quem'){
    E.texto.value = '';
    fechaPaleta();
    E.texto.focus();
    ajustaAltura(); atualizaDestino();
    E.conta.textContent = fmtNum.format(0);
    return rodaQuem();
  }
  E.texto.value = cmd + ' ';
  fechaPaleta();
  E.texto.focus();
  ajustaAltura(); atualizaDestino();
}
function navegaPaleta(passo){
  const itens = $$('.paleta-item', E.paleta);
  if (!itens.length) return;
  paletaIdx = (paletaIdx + passo + itens.length) % itens.length;
  marcaPaleta();
}

/* ── o log é UMA parada de Tab ────────────────────────────────────────────
   Três botões por mensagem davam 93 paradas antes do campo de escrita, com 31
   mensagens — e a sala cresce até 200 KB. Aqui o `#fio` é o ponto de entrada:
   ↑↓ escolhem a mensagem (marcada por `aria-activedescendant`, que é como um
   leitor de tela sabe onde está sem o foco sair do log), e só as ações DELA
   entram no Tab. As ações continuam alcançáveis; deixam de ser um pedágio. */
function mensagemAtiva(n){
  $$('.msg', E.fio).forEach(el=>{
    const ativa = Number(el.dataset.n) === n;
    el.classList.toggle('msg--ativa', ativa);
    $$('.msg-acao', el).forEach(b => b.tabIndex = ativa ? 0 : -1);
  });
  const el = E.fio.querySelector(`[data-n="${n}"]`);
  if (!el) return;
  S.ativa = n;
  E.fio.setAttribute('aria-activedescendant', el.id);
  el.scrollIntoView({block:'nearest'});
}

function andaMensagem(passo){
  const ns = $$('.msg', E.fio).map(el => Number(el.dataset.n));
  if (!ns.length) return;
  const i = ns.indexOf(S.ativa);
  if (i === -1) return mensagemAtiva(passo > 0 ? ns[0] : ns[ns.length - 1]);
  mensagemAtiva(ns[Math.min(ns.length - 1, Math.max(0, i + passo))]);
}

E.fio.addEventListener('keydown', ev=>{
  const teclas = {ArrowDown:1, ArrowUp:-1, PageDown:5, PageUp:-5};
  if (ev.key in teclas){ ev.preventDefault(); return andaMensagem(teclas[ev.key]); }
  if (ev.key === 'Home' || ev.key === 'End'){
    ev.preventDefault();
    const ns = $$('.msg', E.fio).map(el => Number(el.dataset.n));
    if (ns.length) mensagemAtiva(ev.key === 'Home' ? ns[0] : ns[ns.length - 1]);
    return;
  }
  if (ev.key === 'Enter' && S.ativa){
    ev.preventDefault(); S.fio = S.ativa; desenhaFio(); abreAba('fio'); abreGaveta(true);
  }
});
// entrar no log sem mensagem escolhida: começa pela última, que é a que importa
E.fio.addEventListener('focus', ()=>{
  if (S.ativa && E.fio.querySelector(`[data-n="${S.ativa}"]`)) return;
  const ns = $$('.msg', E.fio).map(el => Number(el.dataset.n));
  if (ns.length) mensagemAtiva(ns[ns.length - 1]);
});

/* ── rolagem: a sala NÃO pula sozinha (bug conhecido do painel) ──────────── */
function perto(){ return E.sala.scrollHeight - E.sala.scrollTop - E.sala.clientHeight < 120; }
function desce(suave=true){
  E.sala.scrollTo({top:E.sala.scrollHeight, behavior: suave ? 'smooth' : 'auto'});
  S.colado = true; S.novas = 0; E.descer.hidden = true;
}
function irPara(n){
  const el = E.fio.querySelector(`[data-n="${n}"]`);
  if (!el) return;
  el.scrollIntoView({block:'center', behavior:'smooth'});
  el.animate([{background:'var(--ouro-veu)'},{background:'transparent'}],
             {duration:1400, easing:'cubic-bezier(.32,.08,.24,1)'});
}

function ajustaAltura(){
  E.texto.style.height = 'auto';
  E.texto.style.height = Math.min(E.texto.scrollHeight, window.innerHeight*0.34) + 'px';
}

/* ── rede ────────────────────────────────────────────────────────────────── */
function elo(estado, texto){
  E.elo.dataset.estado = estado;
  $('.elo-texto', E.elo).textContent = texto;
}

/* ── sino do dono: UMA decisão, no config.json do núcleo ─────────────────
   O app não guarda cópia em localStorage nem em cookie. Ele reflete o campo
   vindo do servidor e o consulta de novo enquanto está aberto, inclusive se
   `iachat sino on|off` tiver sido usado no terminal. */
function desenhaSinoOperador(){
  if (!E.sino) return;
  const ligado = S.sala.notificar_operador === true;
  const podeMudar = S.sala.escrever && !window.CONGELADO;
  E.sino.dataset.ligado = ligado ? 'sim' : 'nao';
  E.sino.setAttribute('aria-checked', String(ligado));
  E.sino.disabled = S.sinoMudando || !podeMudar;
  E.sinoGlifo.textContent = ligado ? '🔔' : '🔕';
  if (S.sinoMudando){
    E.sino.setAttribute('aria-label', 'Alterando sino do dono');
    E.sino.title = 'Alterando sino…';
  }else if (!podeMudar){
    E.sino.setAttribute('aria-label',
      `Sino do dono ${ligado?'ligado':'desligado'}; controle indisponível em modo leitura`);
    E.sino.title = 'Controle indisponível em modo leitura';
  }else{
    E.sino.setAttribute('aria-label',
      `Sino do dono ${ligado?'ligado':'desligado'}. ${ligado?'Desligar':'Ligar'} notificações do macOS`);
    E.sino.title = `${ligado?'Desligar':'Ligar'} sino do dono`;
  }
}

async function sincronizaSinoOperador(){
  if (window.CONGELADO || S.sinoMudando) return;
  try{
    const r = await fetch(url('/api/sino'));
    if (!r.ok) return;
    const d = await r.json();
    if (typeof d.notificar_operador !== 'boolean') return;
    S.sala.notificar_operador = d.notificar_operador;
    if (typeof d.escrever === 'boolean') S.sala.escrever = d.escrever;
    desenhaSinoOperador();
  }catch(e){ /* a conexão principal já mostra o estado; não duplica alerta */ }
}

async function alternaSinoOperador(){
  if (!S.sala.escrever || window.CONGELADO || S.sinoMudando) return;
  const ligar = S.sala.notificar_operador !== true;
  S.sinoMudando = true; desenhaSinoOperador();
  try{
    const r = await fetch(url('/api/sino'), {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({ligado:ligar}),
    });
    const d = await r.json();
    if (!r.ok || typeof d.notificar_operador !== 'boolean')
      throw new Error(d.erro || ('HTTP ' + r.status));
    S.sala.notificar_operador = d.notificar_operador;
    avisa(d.notificar_operador
      ? '<b>Sino ligado.</b> As mensagens da sala chegam pelo macOS.'
      : '<b>Sino desligado.</b> Nenhuma mensagem gera notificação.');
  }catch(e){
    avisa('Não alterei o sino: ' + esc(e.message), 'erro');
    S.sinoMudando = false;
    await sincronizaSinoOperador();
  }finally{
    S.sinoMudando = false; desenhaSinoOperador();
  }
}

/* O token entra pela URL (`?t=…`) e o servidor semeia um cookie HttpOnly na primeira
   visita. A URL, porém, ficava na barra — e quem abre no celular pelo QR normalmente
   favorita ou põe na Tela de Início, o que **grava o segredo dentro do ícone**, visível
   a quem pegar o aparelho e sobrevivendo a qualquer troca de token.

   Só limpa depois de PROVAR que o cookie autentica sozinho: uma chamada sem `?t=`. Se
   o cookie não tiver sido semeado (Safari em modo restrito, por exemplo), a URL fica
   como está — perder o único meio de entrar seria trocar um vazamento por um bloqueio.
   `TOKEN` já está em memória e continua indo nas chamadas: limpar a barra não desautentica
   esta aba. Achado do worker `i1-celular` (`sala.js:82` repetia o token em toda API). */
async function limpaTokenDaBarra(){
  if (!TOKEN) return;
  try{
    const r = await fetch('/api/estado', {credentials:'same-origin'});
    if (!r.ok) return;                       // sem cookie válido: a URL é o que resta
    const limpa = new URL(location.href);
    limpa.searchParams.delete('t');
    history.replaceState(null, '', limpa.pathname + limpa.search + limpa.hash);
  }catch(e){ /* rede instável não é motivo para mexer na barra */ }
}


async function carrega(){
  try{
    const r = await fetch(url('/api/sala','desde=0'));
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();
    S.msgs = d.msgs || []; S.ultima = d.ultima || 0; S.sala = d.sala || S.sala;
    // o dono não é par: ele sai da presença e nunca é alvo de "todas"
    S.naSala = (S.sala.na_sala || []).filter(x => x && x !== S.sala.papel);
    if (!S.naSala.length)
      S.naSala = [...new Set(S.msgs.map(m=>m.de))].filter(x => x !== S.sala.papel);
    desenhaMsgs(); desenhaPresenca(); desenhaCabeca(); desenhaGaveta();
    atualizaDestino(); desenhaSinoOperador();
    requestAnimationFrame(()=> desce(false));
    elo('viva', S.sala.escrever ? 'sala aberta' : 'somente leitura');
    if (!S.sala.escrever) E.enviar.disabled = true;
    abreFluxo();
    limpaTokenDaBarra();
  }catch(e){
    elo('caiu','sem conexão');
    avisa('Não consegui ler a sala. <b>Confira se o servidor está no ar.</b>','erro');
  }
}

function abreFluxo(){
  if (S.fonte) S.fonte.close();
  S.fonte = new EventSource(url('/api/stream','desde='+S.ultima));
  S.fonte.addEventListener('open', ()=>{
    elo('viva', S.sala.escrever ? 'sala aberta' : 'somente leitura');
    sincronizaSinoOperador();
  });
  S.fonte.addEventListener('msg', ev=>{
    const m = JSON.parse(ev.data);
    if (S.msgs.some(x=>x.n === m.n)) return;
    S.msgs.push(m); S.ultima = Math.max(S.ultima, m.n);
    if (m.de !== S.sala.papel){
      const alvos = (Array.isArray(m.para)?m.para:[m.para]).filter(Boolean);
      (alvos.length ? alvos : [S.sala.papel]).forEach(a=>{ S.sinos[a] = (S.sinos[a]||0)+1; });
      avisa(`<b>${esc(m.de)}</b> escreveu na sala`);
    }
    anexaMsg(m); desenhaPresenca(); desenhaCabeca(); desenhaGaveta();
    if (S.colado) desce();
    else { S.novas++; E.descer.hidden = false;
           E.descerN.textContent = S.novas === 1 ? '1 nova' : `${S.novas} novas`; }
  });
  S.fonte.addEventListener('error', ()=> elo('caiu','reconectando…'));
}

async function envia(){
  const txt = E.texto.value.trim();
  if (!txt) return;
  // Comando que não é conversa não vira mensagem. Antes, `/parar` no campo era
  // postado no chat como texto — a sala recebia a palavra e nada parava.
  // Agora os sete atravessam o servidor (`rodaComando`) — e o campo é consumido:
  // o painel mostra a resposta, e o que sobrou de texto não fica boiando.
  const c = cmdDe(txt);
  if (c && c.onde !== 'sala'){
    E.texto.value = ''; ajustaAltura(); atualizaDestino();
    E.conta.textContent = fmtNum.format(0);
    return rodaComando(c, txt);
  }
  const alvos = alvosDoTexto(txt);
  E.enviar.disabled = true;
  const rotulo = E.enviarRot.textContent;
  E.enviarRot.textContent = 'Enviando…';
  try{
    const r = await fetch(url('/api/post'), {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({de:S.sala.papel, texto:txt, para: alvos.length ? alvos : ['all']}),
    });
    const d = await r.json();
    if (!r.ok || d.erro) throw new Error(d.erro || ('HTTP '+r.status));
    // O núcleo devolve `avisos` junto com o sucesso: "postou, MAS ninguém foi chamado",
    // "postou, MAS a sala vai rotacionar". O CLI imprime cada um no stderr; a UI olhava
    // só `d.erro` e engolia o resto — sucesso silencioso sobre uma entrega pela metade.
    // O fallback antigo (`servidor.py`) mostrava; a interface nova perdeu.
    // Achado do worker `j1-app-paralelo`.
    // Sem tipo novo: `avisa` só conhece 'ok' e 'erro', e um 'atencao' inventado cairia
    // num estilo que não existe. Aviso não é erro — o post foi feito.
    (d.avisos || []).forEach(a => avisa(esc(a)));
    E.texto.value = ''; ajustaAltura(); atualizaDestino();
    fechaPaleta(); S.colado = true;
  }catch(e){
    avisa('Não enviei: ' + esc(e.message) + '. <b>O texto continua no campo.</b>','erro');
  }finally{
    E.enviar.disabled = !S.sala.escrever;
    E.enviarRot.textContent = rotulo;
    E.texto.focus();
  }
}

/* ── ligações ────────────────────────────────────────────────────────────── */
E.texto.addEventListener('input', ()=>{
  ajustaAltura(); atualizaDestino();
  E.conta.textContent = fmtNum.format(E.texto.value.length);
  const v = E.texto.value;
  if (/^\/\w*$/.test(v)) abrePaleta(v); else fechaPaleta();
});

E.texto.addEventListener('keydown', ev=>{
  // No modo `painel` a paleta está VISÍVEL mas não é uma lista de opções: navegar
  // ali marcaria `aria-selected` numa linha de resposta e o Enter escolheria um
  // `data-cmd` que não existe. Escape continua fechando, porque fechar é sempre
  // uma saída legítima.
  if (!E.paleta.hidden && paletaModo === 'painel'){
    if (ev.key === 'Escape'){ ev.preventDefault(); fechaPaleta(); return; }
  } else if (!E.paleta.hidden){
    if (ev.key === 'ArrowDown'){ ev.preventDefault(); return navegaPaleta(1); }
    if (ev.key === 'ArrowUp'){ ev.preventDefault(); return navegaPaleta(-1); }
    if (ev.key === 'Escape'){ ev.preventDefault(); fechaPaleta(); return; }
    if (ev.key === 'Enter' || ev.key === 'Tab'){
      const sel = $$('.paleta-item', E.paleta)[paletaIdx];
      if (sel){ ev.preventDefault(); return escolhePaleta(sel.dataset.cmd); }
    }
  }
  if (ev.key === 'Enter' && (ev.metaKey || ev.ctrlKey)){ ev.preventDefault(); envia(); }
});

$('#compositor').addEventListener('submit', ev=>{ ev.preventDefault(); envia(); });

$$('.pilula-cmd').forEach(b => b.addEventListener('click', ()=>{
  const c = b.dataset.insere;
  E.texto.value += (E.texto.value && !E.texto.value.endsWith(' ') ? ' ' : '') + c;
  E.texto.focus(); E.texto.dispatchEvent(new Event('input'));
}));

E.fio.addEventListener('click', ev=>{
  const b = ev.target.closest('.msg-acao'); if (!b) return;
  const art = b.closest('.msg'), n = Number(art.dataset.n);
  const m = S.msgs.find(x=>x.n === n); if (!m) return;
  if (b.dataset.acao === 'fio'){
    S.fio = n; desenhaFio(); abreAba('fio'); abreGaveta(true);
  } else if (b.dataset.acao === 'responder'){
    E.texto.value = `@${m.de} `; E.texto.focus();
    E.texto.dispatchEvent(new Event('input'));
  } else {
    navigator.clipboard.writeText(m.texto).then(()=> avisa('Mensagem copiada.'));
  }
});

E.busca.addEventListener('input', ()=>{ S.filtro = E.busca.value.trim().toLowerCase(); desenhaMsgs(); });

E.sala.addEventListener('scroll', ()=>{
  S.colado = perto();
  if (S.colado){ S.novas = 0; E.descer.hidden = true; }
});
E.descer.addEventListener('click', ()=> desce());

/* Roving tabindex: o conjunto de abas é UMA parada de Tab, e as setas andam
   entre elas — é o que o padrão ARIA de tablist exige. Antes eram quatro. */
/* ── o mapa de retomada ────────────────────────────────────────────────────
   Busca SÓ quando a aba abre, e não a cada tick: o `caminho.md` muda em
   compactação, não em mensagem. Puxá-lo no ciclo da sala seria pagar leitura de
   disco a cada 2 s por um arquivo que passa horas parado. */
let mapaCarregado = false;

function tituloOuBloco(bruto){
  // `.trim()` antes de testar: o YAML removido deixa um `\n` na frente do primeiro
  // bloco, e `^#` não casava — o título do documento aparecia com o `#` cru na tela
  // enquanto `## Onde parou` virava seção. Achado olhando a captura, não o código:
  // o defeito era invisível na leitura e óbvio na imagem.
  const bloco = bruto.trim();
  if (!bloco) return '';
  const m = bloco.match(/^(#{1,3})\s+(.*)$/);
  if (!m) return corpoHTML(bloco);
  // Nível 1 é o título do próprio documento e já está no cabeçalho do painel —
  // repetir daria dois títulos dizendo a mesma coisa.
  const tag = m[1].length === 1 ? 'h3' : 'h4';
  return `<${tag} class="mapa-sec">${esc(m[2])}</${tag}>`;
}

async function desenhaMapa(forcar){
  if (!E.mapa || (mapaCarregado && !forcar)) return;
  mapaCarregado = true;
  E.mapa.innerHTML = '<p class="painel-nota">lendo…</p>';
  try{
    const r = await fetch(url('/api/mapa'), {cache:'no-store'});
    const d = await r.json();
    if (!r.ok) throw new Error(d.erro || ('HTTP ' + r.status));
    if (!d.existe){
      E.mapa.innerHTML = `<p class="painel-nota">${esc(d.porque || 'sem mapa ainda.')}</p>`;
      return;
    }
    const corpo = String(d.texto || '')
      // O bloco de metadados YAML é para a máquina; quem lê quer o mapa.
      .replace(/^---\n[\s\S]*?\n---\n/, '')
      .split(/\n{2,}/).map(tituloOuBloco).join('');
    E.mapa.innerHTML = corpo +
      `<p class="painel-nota mapa-rodape">${esc(d.em)} · ${esc(bytesLegiveis(d.bytes))} · ` +
      `<code translate="no">${esc(d.caminho)}</code></p>`;
  }catch(e){
    mapaCarregado = false;   // deixa tentar de novo na próxima abertura
    E.mapa.innerHTML = `<p class="painel-nota">não consegui ler o mapa: ${esc(e.message)}</p>`;
  }
}

function abreAba(qual){
  $$('.aba').forEach(a=>{
    const ativo = a.dataset.pnl === qual;
    a.setAttribute('aria-selected', String(ativo));
    a.tabIndex = ativo ? 0 : -1;
    $('#pnl-' + a.dataset.pnl).hidden = !ativo;
  });
  if (qual === 'mapa') desenhaMapa(true);
}
$$('.aba').forEach(a=>{
  a.addEventListener('click', ()=> abreAba(a.dataset.pnl));
  a.addEventListener('keydown', ev=>{
    const abas = $$('.aba'), i = abas.indexOf(a);
    let j = null;
    if (ev.key === 'ArrowRight') j = (i + 1) % abas.length;
    else if (ev.key === 'ArrowLeft') j = (i - 1 + abas.length) % abas.length;
    else if (ev.key === 'Home') j = 0;
    else if (ev.key === 'End') j = abas.length - 1;
    if (j === null) return;
    ev.preventDefault();
    abreAba(abas[j].dataset.pnl);
    abas[j].focus();
  });
});

/* No celular a gaveta é uma folha que cobre a tela — então ela nasce FECHADA e
   tem três saídas: o botão do trilho, o ✕ dentro dela e o véu atrás. Medido em
   390 px antes disto: ela nascia aberta sobre 86% da tela e nenhum dos botões
   que a fechavam estava visível. */
const estreito = () => matchMedia('(max-width:760px)').matches;

function botoesGaveta(){
  return [$('#btn-gaveta'), $('#btn-gaveta-topo')].filter(Boolean);
}
/* Quem abriu é quem recebe o foco de volta. São dois botões para a mesma gaveta —
   o do rodapé do trilho e o do topo — e devolver o foco a um deles fixo mandaria a
   pessoa para o outro canto da tela. No celular é pior: o de baixo pode nem estar
   visível quando a gaveta fecha. */
let abriuAGaveta = null;
function voltaOFoco(){
  const alvo = (abriuAGaveta && document.contains(abriuAGaveta)) ? abriuAGaveta : $('#btn-gaveta');
  if (alvo) alvo.focus();
}
function abreGaveta(forcar){
  const aberta = forcar !== undefined ? forcar : E.moldura.dataset.gaveta !== 'aberta';
  E.moldura.dataset.gaveta = aberta ? 'aberta' : 'fechada';
  botoesGaveta().forEach(b => b.setAttribute('aria-expanded', String(aberta)));
  if (aberta && estreito()) $('#gaveta-fecha').focus();
}
botoesGaveta().forEach(b => b.addEventListener('click', ()=>{ abriuAGaveta = b; abreGaveta(); }));
$('#gaveta-fecha').addEventListener('click', ()=>{ abreGaveta(false); voltaOFoco(); });
E.veu.addEventListener('click', ()=> abreGaveta(false));
E.sino.addEventListener('click', alternaSinoOperador);

/* A altura que o teclado do celular deixa. `dvh` responde às barras do navegador,
   não ao teclado virtual: em iOS o layout não encolhe quando ele sobe, e o
   compositor fica atrás dele. `visualViewport` é o único que enxerga isso. */
function alturaViva(){
  const vv = window.visualViewport;
  if (!vv) return;
  document.documentElement.style.setProperty('--altura-viva', vv.height + 'px');
  // o teclado subiu: garante que a última mensagem continua à vista
  if (S.colado) requestAnimationFrame(()=> desce(false));
}
if (window.visualViewport){
  visualViewport.addEventListener('resize', alturaViva);
  visualViewport.addEventListener('scroll', alturaViva);
  alturaViva();
}

function tema(t){
  document.documentElement.dataset.tema = t;
  $('meta[name="theme-color"]').content = t === 'carvao' ? '#100E0A' : '#F2EADA';
  try{ localStorage.setItem('ia-chat-tema', t); }catch(e){}
}
$('#btn-tema').addEventListener('click', ()=>
  tema(document.documentElement.dataset.tema === 'carvao' ? 'palha' : 'carvao'));

document.addEventListener('keydown', ev=>{
  const meta = ev.metaKey || ev.ctrlKey;
  if (meta && ev.key.toLowerCase() === 'k'){ ev.preventDefault(); E.busca.focus(); E.busca.select(); }
  if (meta && ev.key.toLowerCase() === 'j'){ ev.preventDefault(); abreGaveta(); }
  if (meta && ev.shiftKey && ev.key.toLowerCase() === 'l'){ ev.preventDefault(); $('#btn-tema').click(); }
  if (ev.key === 'Escape' && typeof fechaRemotoEnxame === 'function' && fechaRemotoEnxame()){
    ev.preventDefault(); return;
  }
  if (ev.key === 'Escape' && typeof fechaDocaEnxame === 'function' && fechaDocaEnxame()){
    ev.preventDefault(); return;
  }
  if (ev.key === 'Escape' && estreito() && E.moldura.dataset.gaveta === 'aberta'){
    ev.preventDefault(); abreGaveta(false); voltaOFoco(); return;
  }
  if (ev.key === 'Escape' && document.activeElement === E.busca){
    E.busca.value = ''; S.filtro = ''; desenhaMsgs(); E.texto.focus();
  }
});

/* ── arranque ────────────────────────────────────────────────────────────── */
// no celular ela cobriria a conversa inteira; no desktop tem coluna própria
abreGaveta(!matchMedia('(max-width:760px)').matches);
/* Tema: a URL manda, depois o que ficou guardado. `?tema=carvao` existe pelo mesmo
   motivo do `?aba=` e do `?janela=` — endereço que abre como você quer é favoritável,
   e no celular vira ícone na Tela de Início já no tema certo.
   Só dois valores; qualquer outro é ignorado em vez de pintar a interface de nada. */
try{
  const pedido = new URLSearchParams(location.search).get('tema');
  const guardado = localStorage.getItem('ia-chat-tema');
  const t = ['palha', 'carvao'].includes(pedido) ? pedido : guardado;
  if (t) tema(t);
}catch(e){}
if (window.CONGELADO){                       // export offline: a sala vem dentro do HTML
  const d = window.CONGELADO;
  S.msgs = d.msgs||[]; S.ultima = d.ultima||0; S.sala = d.sala||S.sala;
  S.naSala = (S.sala.na_sala||[]).filter(x => x && x !== S.sala.papel);
  desenhaMsgs(); desenhaPresenca(); desenhaCabeca(); desenhaGaveta();
  atualizaDestino(); desenhaSinoOperador();
  elo('caiu','cópia congelada'); E.enviar.disabled = true;
  requestAnimationFrame(()=> desce(false));
} else {
  carrega();
  iniciaVigiaVersao();
  // O CLI e o app controlam o MESMO campo. Enquanto a janela está visível,
  // cinco segundos é o teto para o app refletir uma troca feita no terminal.
  window.setInterval(()=>{
    if (document.visibilityState === 'visible') sincronizaSinoOperador();
  }, 5000);
  window.addEventListener('focus', sincronizaSinoOperador);
}
ajustaAltura();
// foco inicial: desktop, campo primário único — é onde a mão dele já está
// só no ponteiro fino: no celular, focar sozinho abre o teclado e come metade da tela
if (matchMedia('(pointer:fine)').matches && !/[?&]janela=(?:enxame|groupchat)/.test(location.search)) E.texto.focus();

/* ═══════════════════════════════════════════════════════════════════════════
   IASWARM · janela dourada — mesma leitura do painel neon, outro humor.
   Funções portadas: reatores, doca, recolher um/todos, métricas, caminhos,
   jsonl ao vivo, filtros, foco, ritmo medido, transições, modo neon.
   Controle remoto (pedido novo): clicar o NOME da IA abre dados + terminal.
   ═══════════════════════════════════════════════════════════════════════════ */
const EX_CORES = {
  agy:'#4285F4', kimi:'#856EFF', codex:'#12A594', grok:'#5F6977',
  qwen:'#B866CD', ollama:'#E0982A', deepseek:'#4F80F0', hermes:'#C9A227',
  copilot:'#4285F4', dourada:'#C9A227', claude:'#D97757',
  openai:'#12A594', anthropic:'#D97757', google:'#4285F4', gemini:'#4285F4',
  mistral:'#FF7000', meta:'#0064E0', llama:'#0064E0', cohere:'#39594D',
  perplexity:'#20808D', groq:'#F55036', together:'#0F6FFF', openrouter:'#6467F2',
  xai:'#5F6977', nvidia:'#76B900', nim:'#76B900', huggingface:'#B08918',
  azure:'#0078D4', bedrock:'#FF9900', vertex:'#4285F4', moonshot:'#856EFF',
  alibaba:'#FF6A00', zhipu:'#3859FF', glm:'#3859FF', minimax:'#E8437E',
  yi:'#00A6A6', stability:'#8B5CF6', replicate:'#EA4C89', fireworks:'#F0533B',
  lmstudio:'#4F46E5', vllm:'#00B8D9', llamacpp:'#8FBF3F', cerebras:'#F05A28',
  sambanova:'#EE3124', baseten:'#3B82F6', modal:'#3E8B3A', fal:'#C026D3',
};
const EX_CASCA = {
  qwclaude:'qwen', dsclaude:'deepseek', 'deepseek-claude':'deepseek',
  'ds-claude':'deepseek', qwclaudex:'qwen', 'kimi-claude':'kimi',
  'grok-claude':'grok', 'agy-claude':'agy', hermes2:'hermes',
};
const EX_ALIAS = {
  gpt:'openai','gpt-4':'openai','gpt-5':'openai',o1:'openai',o3:'openai','gpt-oss':'openai',
  opus:'anthropic',sonnet:'anthropic',haiku:'anthropic',fable:'anthropic',
  k2:'kimi',k3:'kimi','kimi-k2':'kimi','kimi-k3':'kimi',
  antigravity:'agy','gemini-flash':'gemini','gemini-pro':'gemini',
  nemotron:'nvidia',hf:'huggingface',
  qwen3:'qwen',qwq:'qwen',wan:'qwen',bailian:'alibaba',dashscope:'alibaba',
  'deepseek-v4':'deepseek',r1:'deepseek',ds:'deepseek',
  phi:'azure',mixtral:'mistral',codestral:'mistral',magistral:'mistral',
};
const EX_TERMINAL = new Set(['entregue','falhou','pulado']);
const EX_ROTULO = {fila:'na fila',despachado:'despachado',rodando:'trabalhando',
  concluida:'trabalhando',entregue:'entregue',falhou:'FALHOU',pulado:'pulado'};

function exCorBraco(braco){
  const b = String(braco||'').toLowerCase().split(':')[0].split('/')[0].trim();
  if (EX_CASCA[b] && EX_CORES[EX_CASCA[b]]) return EX_CORES[EX_CASCA[b]];
  if (EX_CORES[b]) return EX_CORES[b];
  if (EX_ALIAS[b] && EX_CORES[EX_ALIAS[b]]) return EX_CORES[EX_ALIAS[b]];
  for (const k of Object.keys(EX_CORES)) if (b.startsWith(k)) return EX_CORES[k];
  for (const k of Object.keys(EX_ALIAS)) if (b.startsWith(k)) return EX_CORES[EX_ALIAS[k]];
  let h = 0; for (let i = 0; i < b.length; i++) h = (h * 31 + b.charCodeAt(i)) >>> 0;
  return `hsl(${40+(h%300)} 42% 42%)`;
}
function exSeg(hhmmss){
  const m = /^(\d{1,2}):(\d{2}):(\d{2})$/.exec(String(hhmmss||'').trim());
  return m ? (+m[1])*3600+(+m[2])*60+(+m[3]) : null;
}
function exHhmm(s){
  return s==null ? '—' : `${String(Math.floor(s/3600)).padStart(2,'0')}:${String(Math.floor(s/60)%60).padStart(2,'0')}`;
}
function exDur(s){
  if (s == null || s < 0) return '—';
  if (s < 60) return s + 's';
  const m = Math.floor(s/60);
  return m < 60 ? `${m}m ${String(s%60).padStart(2,'0')}s` : `${Math.floor(m/60)}h ${String(m%60).padStart(2,'0')}m`;
}
function exBytes(b){
  if (b == null || !Number.isFinite(b)) return null;
  if (b < 1024) return b + ' B';
  if (b < 1048576) return (b/1024).toFixed(b<10240?1:0) + ' KB';
  return (b/1048576).toFixed(1) + ' MB';
}
function exPeriodo(passoS){
  const s = Math.max(5, passoS || 60);
  const k = Math.min(1, Math.max(0, (Math.log(s)-Math.log(20))/(Math.log(900)-Math.log(20))));
  return 0.9 + 3.1*k;
}
function exInferirBraco(id, tsv, evs){
  if (tsv && tsv.braco) return {braco:tsv.braco, origem:'workers.tsv'};
  const cmd = (evs.find(e => e.nota && (e.etapa===0 || e.estado==='despachado'))||{}).nota||'';
  const tok = cmd.trim().split(/[\s:]+/)[0].toLowerCase();
  if (tok && /^[a-z0-9._-]{2,}$/.test(tok)) return {braco:tok, origem:'comando de despacho', variante:cmd.trim()};
  const suf = String(id).split('-').slice(1).join('-').toLowerCase();
  if (suf) return {braco:suf, origem:'nome do worker'};
  return {braco:'desconhecido', origem:'—'};
}
function exMontarWorker(id, evs, tsv, temResultado){
  const inf = exInferirBraco(id, tsv, evs);
  const etapas = Math.max(1, (tsv && +tsv.etapas)||0, ...evs.map(e=>+e.de||0), ...evs.map(e=>+e.etapa||0));
  let feitas = 0, estado = 'fila', nota = '', ts = '', tsIni = '', tsDesp = '';
  const passos = [];
  for (const ev of evs){
    if (ev.ts){ ts = ev.ts; if (!tsIni) tsIni = ev.ts;
      if (!tsDesp && (ev.etapa===0 || ev.estado==='despachado')) tsDesp = ev.ts; }
    if (ev.nota) nota = ev.nota;
    if (ev.estado) estado = ev.estado;
    const et = +ev.etapa;
    if (Number.isInteger(et) && et > feitas && et <= etapas) feitas = et;
    passos.push({etapa:ev.etapa, estado:ev.estado||'', nota:ev.nota||'', ts:ev.ts||''});
  }
  if (estado === 'concluida') estado = 'rodando';
  if (temResultado && !['falhou','pulado'].includes(estado)){ estado = 'entregue'; feitas = etapas; }
  let passo = null;
  const anc = [];
  passos.forEach((p,i)=>{ const s = exSeg(p.ts); if (s != null) anc.push([i,s]); });
  if (anc.length >= 2){
    const a = anc[0], b = anc[anc.length-1];
    if (b[0] > a[0] && b[1] >= a[1]) passo = Math.max(2, (b[1]-a[1])/(b[0]-a[0]));
  }
  const cor = exCorBraco(inf.braco);
  const chave = String(inf.braco).toLowerCase().split(':')[0];
  return {id, braco:inf.braco, origemBraco:inf.origem, variante:inf.variante||(tsv&&tsv.braco)||inf.braco,
    casca:EX_CASCA[chave]||null, marca:EX_CASCA[chave]||chave,
    etapas, feitas, estado, nota, ts, tsIni, tsDesp, passos, cor, passo,
    eventos:evs.length, noTsv:!!tsv};
}
function exMontarOndas(ws){
  const porTs = new Map();
  for (const w of ws) if (w.tsDesp){ if (!porTs.has(w.tsDesp)) porTs.set(w.tsDesp,[]); porTs.get(w.tsDesp).push(w); }
  const familia = new Map();
  for (const w of ws){ if (!w.tsDesp) continue; const f = w.id[0].toLowerCase(); if (!familia.has(f)) familia.set(f,w.tsDesp); }
  for (const w of ws) if (!w.tsDesp){
    const t = familia.get(w.id[0].toLowerCase());
    if (t){ porTs.get(t).push(w); } else { if (!porTs.has('')) porTs.set('',[]); porTs.get('').push(w); }
  }
  return [...porTs.entries()]
    .sort((a,b)=>(exSeg(a[0])??1e9)-(exSeg(b[0])??1e9))
    .map(([ts,lista],i)=>({n:i+1, ts, workers:lista.sort((a,b)=>a.id.localeCompare(b.id,'pt'))}));
}
function exMontarRun(cru){
  const ws = Object.entries(cru.progress||{})
    .map(([id,evs])=>exMontarWorker(id, evs, (cru.tsv||{})[id], (cru.resultados||[]).includes(id)));
  for (const [id,t] of Object.entries(cru.tsv||{}))
    if (!cru.progress || !(id in cru.progress)) ws.push(exMontarWorker(id, [], t, (cru.resultados||[]).includes(id)));
  const validos = ws.map(w=>w.passo).filter(p=>Number.isFinite(p)&&p>0).sort((a,b)=>a-b);
  const tipico = validos.length ? validos[validos.length>>1] : 60;
  const tam = cru.tamanhos||{}, lg = cru.logs||{};
  for (const w of ws){
    if (!(w.passo>0)) w.passo = tipico;
    if (w.id in tam) w.resultadoBytes = tam[w.id];
    if (w.id in lg) w.logBytes = lg[w.id];
  }
  return {id:cru.id, missao:cru.missao||'', caminho:cru.caminho||'',
    resultados:cru.resultados||[], workers:ws, ondas:exMontarOndas(ws)};
}
function exVivacidade(w, agora){
  if (EX_TERMINAL.has(w.estado)) return {classe:'', rotulo:EX_ROTULO[w.estado]||w.estado, vivo:false};
  const t = exSeg(w.ts); if (t==null || agora==null) return {classe:'', rotulo:EX_ROTULO[w.estado]||w.estado, vivo:false};
  const p = agora - t;
  if (p <= 90)  return {classe:'viv', rotulo:EX_ROTULO[w.estado]||w.estado, vivo:true, parado:p};
  if (p <= 300) return {classe:'viv', rotulo:'lento '+exDur(p), vivo:true, parado:p};
  if (p <= 900) return {classe:'sil', rotulo:'silêncio '+exDur(p), vivo:false, parado:p, alerta:true};
  return {classe:'sil', rotulo:'sem sinal '+exDur(p), vivo:false, parado:p, alerta:true};
}

const EX = {
  raiz: $('#enxame'), reatores: $('#enxame-reatores'), doca: $('#enxame-doca'),
  remoto: $('#enxame-remoto'), placar: $('#enxame-placar'), fonte: $('#enxame-fonte'),
  log: $('#enxame-log'), filtro:'todos', swarm:null, remotoAlvo:null, remotoAcao:null,
  anterior: new Map(), primeira:true, ocupado:false, vivo:false, rotulo:'—',
  runs:[], dados:[], timer:null,
  sig:{reatores:null,doca:null,placar:null,fonte:null,erro:null},
};
const EX_DOBRA_CHAVE = 'iaswarm.dourado.recolhidos';
let EX_DOBRADOS = new Set();
try { EX_DOBRADOS = new Set(JSON.parse(localStorage.getItem(EX_DOBRA_CHAVE)||'[]')); } catch(e){}
function exGravarDobra(){ try{ localStorage.setItem(EX_DOBRA_CHAVE, JSON.stringify([...EX_DOBRADOS])); }catch(e){} }
const EX_ABRIR_URL = new Set();

function janelaModo(pedido){
  const modo = JANELAS.has(pedido) ? pedido : 'sala';
  const anterior = document.documentElement.dataset.janela || 'sala';
  document.documentElement.dataset.janela = modo;

  const enxame = $('#enxame'), groupchat = $('#groupchat');
  if (enxame) enxame.hidden = modo !== 'enxame';
  if (groupchat) groupchat.hidden = modo !== 'groupchat';
  const btn = $('#btn-enxame');
  if (btn) btn.setAttribute('aria-pressed', String(modo === 'enxame'));
  $$('.janela-modo').forEach(b=>{
    const ativo = b.dataset.modoJanela === modo;
    b.setAttribute('aria-pressed', String(ativo));
    if (ativo) b.setAttribute('aria-current', 'page');
    else b.removeAttribute('aria-current');
  });

  const tit = $('.cabeca-titulo'), sub = $('.cabeca-sub');
  if (tit) tit.dataset.sala = tit.dataset.sala || tit.innerHTML;
  if (modo === 'enxame'){
    if (tit) tit.textContent = 'IASWARM';
    exTick();
    if (!EX.timer) EX.timer = setInterval(()=>{
      if (document.documentElement.dataset.janela === 'enxame' && document.visibilityState === 'visible') exTick();
    }, 2000);
  } else if (modo === 'groupchat'){
    if (tit) tit.textContent = 'groupchat';
    gcTick();
    if (!GC.timer) GC.timer = setInterval(()=>{
      if (document.documentElement.dataset.janela === 'groupchat' &&
          document.visibilityState === 'visible') gcTick();
    }, 2000);
  } else {
    if (tit && tit.dataset.sala) tit.innerHTML = tit.dataset.sala;
  }
  if (anterior === 'enxame' && modo !== 'enxame' && EX.timer){
    clearInterval(EX.timer); EX.timer = null;
  }
  if (anterior === 'groupchat' && modo !== 'groupchat' && GC.timer){
    clearInterval(GC.timer); GC.timer = null;
  }
  if (modo !== 'enxame' && matchMedia('(pointer:fine)').matches) E.texto.focus();
  atualizaDestino();
  return modo;
}

function janelaEnxame(abrir){
  const on = abrir !== undefined ? abrir : document.documentElement.dataset.janela !== 'enxame';
  return janelaModo(on ? 'enxame' : 'sala');
}
function janelaGroupchat(abrir){
  const on = abrir !== undefined ? abrir : document.documentElement.dataset.janela !== 'groupchat';
  return janelaModo(on ? 'groupchat' : 'sala');
}
function fechaRemotoEnxame(){
  if (!EX.remoto || EX.remoto.hidden) return false;
  EX.remotoAlvo = null; EX.remotoAcao = null;
  EX.remoto.hidden = true; EX.remoto.innerHTML = '';
  return true;
}
function fechaDocaEnxame(){
  if (!EX.swarm) return false;
  EX.swarm = null; exTick();
  return true;
}

async function exCarregar(){
  const r = await fetch(url('/api/iaswarm'), {cache:'no-store'});
  if (!r.ok) throw new Error('HTTP '+r.status);
  const d = await r.json();
  EX.vivo = !!d.vivo; EX.rotulo = d.fonte === 'disco' ? 'ao vivo · disco' : (d.fonte||'—');
  return (d.runs||[]).map(exMontarRun);
}
function exPassa(w){
  if (EX.filtro === 'todos') return true;
  if (EX.filtro === 'vivos') return !EX_TERMINAL.has(w.estado);
  return w.estado === EX.filtro;
}
function exModeloReator(w, run){
  const v = w._v || {};
  return [
    w.id,w.braco,w.origemBraco,w.variante,w.casca,w.marca,w.etapas,w.feitas,
    w.estado,w.nota,w.ts,w.tsIni,w.tsDesp,w.eventos,w.passo,w.cor,w.noTsv,
    (run.resultados||[]).includes(w.id),
    [v.classe||'',v.rotulo||'',!!v.vivo,v.parado??null,!!v.alerta],
    w.passos.map(p=>[p.etapa??null,p.estado||'',p.nota||'',p.ts||'']),
  ];
}
function exSigReatores(runs){
  const modelo = runs.map(run=>[
    run.id,run.missao||'',EX_DOBRADOS.has(run.id),EX.swarm===run.id,
    [run._m.ok,run._m.viv,run._m.fal,run._m.sil,run._m.n,run._m.agora,run._m.filete],
    run.ondas.map(o=>{
      const workers = o.workers.filter(exPassa);
      return workers.length
        ? [o.n,o.ts||'',o.workers.length,workers.map(w=>exModeloReator(w,run))]
        : null;
    }).filter(Boolean),
  ]);
  return JSON.stringify([EX.filtro,EX.swarm,[...EX_DOBRADOS].sort(),modelo]);
}
function exSigDoca(runs){
  const run = runs.find(r=>r.id===EX.swarm);
  if (!run) return JSON.stringify([null]);
  const ordem = run.workers.map(w=>w.id);
  const workers = [...run.workers].sort((a,b)=>a.id.localeCompare(b.id,'pt')).map(w=>{
    const v = w._v || {};
    return [
      w.id,w.marca,w.braco,w.cor,w.estado,w.nota,w.feitas,w.etapas,w.eventos,
      w.tsIni,w.ts,w.passo,w.resultadoBytes??null,w.logBytes??null,
      [v.rotulo||'',!!v.alerta],(run.resultados||[]).includes(w.id),
    ];
  });
  return JSON.stringify([
    EX.swarm,EX.rotulo,run.id,run.missao||'',run.caminho||'',
    (run.resultados||[]).slice().sort(),ordem,workers,
    [run._m.ok,run._m.viv,run._m.fal,run._m.sil,run._m.n,run._m.filete],
    run.ondas.map(o=>[o.n,o.ts||'',o.workers.map(w=>w.id)]),
  ]);
}
function exAtualizaDobrar(){
  const bd = $('#ex-dobrar');
  const tudo = EX.runs.length && EX.runs.every(id=>EX_DOBRADOS.has(id));
  if (bd){
    bd.setAttribute('aria-pressed', String(!!tudo));
    bd.textContent = tudo ? 'expandir todos' : 'recolher todos';
  }
}
function exLinhaWorker(w, runId){
  const chave = runId+'/'+w.id, prev = EX.anterior.get(chave);
  const avancou = !EX.primeira && prev && (prev.feitas !== w.feitas || prev.estado !== w.estado);
  const v = w._v;
  const abertoDom = document.querySelector(`.enxame-w[data-k="${CSS.escape(chave)}"].aberto`) != null;
  const aberto = avancou ? false : (abertoDom || (EX.primeira && EX_ABRIR_URL.has(w.id)));
  const cls = ['enxame-w', v.classe, w.estado, avancou?'avancou':'', aberto?'aberto':''].filter(Boolean).join(' ');
  const estCls = v.alerta ? 'est-silencio' : 'est-'+w.estado;
  let segs = '';
  for (let k = 1; k <= w.etapas; k++){
    const c = k <= w.feitas ? 'enxame-seg feito' :
      (k === w.feitas+1 && !EX_TERMINAL.has(w.estado) && !v.alerta) ? 'enxame-seg ativo' : 'enxame-seg';
    segs += `<span class="${c}" style="--i:${k}"></span>`;
  }
  const t0 = exSeg(w.tsIni), t1 = exSeg(w.ts);
  const decorrido = (t0!=null && t1!=null && t1>=t0) ? exDur(t1-t0) : '—';
  const tinta = IAS.includes(w.marca) ? `var(--${w.marca}-t)` : 'var(--ouro-tinta)';
  return `<div class="${cls}" style="--cor:${w.cor};--glow:${w.cor};--ia-t:${tinta};--per:${exPeriodo(w.passo).toFixed(2)}s" data-k="${esc(chave)}" data-run="${esc(runId)}" data-worker="${esc(w.id)}">
    <button class="enxame-w-cab" type="button" data-foco="w:${esc(chave)}" aria-expanded="${aberto}"
            aria-label="${esc(w.id)}, ${esc(w.braco)}, etapa ${w.feitas} de ${w.etapas}, ${esc(v.rotulo)}">
      <span class="enxame-chip" aria-hidden="true"></span>
      <span class="enxame-nome"><b translate="no" data-remoto="${esc(runId)}/${esc(w.id)}">${esc(w.marca)}${w.casca?`<span class="enxame-casca">casca</span>`:''}</b>
        <small translate="no">${esc(w.id)}${w.casca?' · '+esc(w.braco):''}${w.origemBraco==='nome do worker'?' · braço suposto':''}</small></span>
      <span class="enxame-trilha" role="img" aria-label="etapa ${w.feitas} de ${w.etapas}">${segs}</span>
      <span class="enxame-nota">${esc(w.nota||'—')}</span>
      <span class="enxame-tempo"><b>${w.feitas}/${w.etapas}</b>${esc(decorrido)}</span>
      <span class="enxame-est ${estCls}">${esc(v.rotulo)}</span>
    </button>
    <div class="enxame-detalhe">
      <p class="enxame-meta">
        <span>braço <b translate="no">${esc(w.variante)}</b></span>
        <span>origem <b>${esc(w.origemBraco)}</b></span>
        <span>início <b translate="no">${esc(w.tsIni||'—')}</b></span>
        <span>último sinal <b translate="no">${esc(w.ts||'—')}</b></span>
        <span>eventos <b>${w.eventos}</b></span>
        ${v.parado!=null?`<span>parado há <b>${esc(exDur(v.parado))}</b></span>`:''}
      </p>
      <ol>${w.passos.length?w.passos.map(p=>`<li><b>${p.etapa===-1?'✕':esc(p.etapa)}</b>
        <i translate="no">${esc(p.ts||'·')}</i><span>${esc(p.nota||EX_ROTULO[p.estado]||p.estado||'—')}</span></li>`).join('')
        :'<li><span>nenhum evento gravado ainda.</span></li>'}</ol>
    </div></div>`;
}
function exRenderDoca(runs){
  const doca = EX.doca, run = runs.find(r => r.id === EX.swarm);
  if (!run){ doca.hidden = true; doca.innerHTML = ''; EX.raiz.dataset.doca = 'nao'; return; }
  const rolagem = doca.scrollTop;
  doca.hidden = false; EX.raiz.dataset.doca = 'sim';
  doca.style.setProperty('--filete', run._m.filete);
  const m = run._m, ws = run.workers;
  const etapasFeitas = ws.reduce((s,w)=>s+w.feitas,0), etapasTotal = ws.reduce((s,w)=>s+w.etapas,0);
  const eventos = ws.reduce((s,w)=>s+w.eventos,0);
  const inicios = ws.map(w=>exSeg(w.tsIni)).filter(v=>v!=null);
  const fins = ws.map(w=>exSeg(w.ts)).filter(v=>v!=null);
  const janela = (inicios.length && fins.length) ? Math.max(...fins)-Math.min(...inicios) : null;
  const durs = ws.map(w=>{const a=exSeg(w.tsIni),b=exSeg(w.ts);
    return (a!=null&&b!=null&&b>=a)?{w,s:b-a}:null;}).filter(Boolean).sort((a,b)=>a.s-b.s);
  const passos = ws.map(w=>w.passo).filter(p=>p>0).sort((a,b)=>a-b);
  const cadencia = passos.length ? passos[passos.length>>1] : null;
  const totBytes = ws.reduce((s,w)=>s+(w.resultadoBytes||0),0);
  const temBytes = ws.some(w=>w.resultadoBytes!=null);
  const cel = (r,v,c)=>`<div class="enxame-det-cel ${c||''}"><dt>${r}</dt><dd>${v}</dd></div>`;
  const men = v => `<small>${esc(v)}</small>`;
  const porBraco = new Map();
  for (const w of ws){ const k = w.marca||w.braco;
    if (!porBraco.has(k)) porBraco.set(k,{n:0,cor:w.cor,ok:0});
    const e = porBraco.get(k); e.n++; if (w.estado==='entregue') e.ok++; }
  const bracos = [...porBraco.entries()].sort((a,b)=>b[1].n-a[1].n);
  const classeDe = w => w.estado==='entregue'?'ok':w.estado==='falhou'?'fal':
    (w._v&&w._v.alerta)?'sil':EX_TERMINAL.has(w.estado)?'':'viv';
  const base = run.caminho || ('~/.claude/iaswarm-runs/'+run.id);
  const caminho = rel => `<code translate="no">${esc(base+'/'+rel)}</code>`;
  const entregues = ws.filter(w=>w.estado==='entregue'||(run.resultados||[]).includes(w.id));
  const maus = ws.filter(w=>w.estado==='falhou'||(w._v&&w._v.alerta));
  doca.innerHTML = `
    <div class="enxame-doca-topo">
      <div><h3 translate="no">${esc(run.id)}</h3><p class="enxame-missao">${esc(run.missao||'sem missao.md')}</p></div>
      <button class="enxame-fecha" type="button" id="ex-fecha-doca" aria-label="fechar o detalhe">✕</button>
    </div>
    <h3 class="enxame-det-h">métricas</h3>
    <div class="enxame-det-grade">
      ${cel('workers',m.n)}${cel('entregues',m.ok,'ok')}${cel('falhas',m.fal,m.fal?'fal':'')}
      ${cel('silêncio',m.sil,m.sil?'sil':'')}${cel('em curso',m.viv,m.viv?'viv':'')}
      ${cel('ondas',run.ondas.length)}${cel('etapas',etapasFeitas+`<small>/${etapasTotal}</small>`)}
      ${cel('eventos',eventos)}${cel('janela',men(exDur(janela)))}${cel('cadência',men(cadencia?exDur(Math.round(cadencia)):'—'))}
    </div>
    ${durs.length?`<p class="enxame-det-rodape" style="margin-top:10px;border:0;padding-top:0">
      mais rápido <b translate="no">${esc(durs[0].w.id)}</b> (${esc(exDur(durs[0].s))})
      · mais lento <b translate="no">${esc(durs[durs.length-1].w.id)}</b> (${esc(exDur(durs[durs.length-1].s))})</p>`:''}
    <h3 class="enxame-det-h">frota <i>${bracos.length} braço${bracos.length>1?'s':''}</i></h3>
    <div class="enxame-det-barra" role="img" aria-label="distribuição por braço">
      ${bracos.map(([,e])=>`<i style="width:${e.n/m.n*100}%;background:${e.cor}"></i>`).join('')}</div>
    <div class="enxame-det-legenda">${bracos.map(([k,e])=>
      `<span><em style="background:${e.cor}"></em><b translate="no">${esc(k)}</b> ${e.ok}/${e.n}</span>`).join('')}</div>
    <h3 class="enxame-det-h">ondas <i>${run.ondas.length}</i></h3>
    <div class="enxame-det-ondas">${run.ondas.map(o=>`<div class="enxame-det-onda">
      <b>onda ${o.n}</b><span translate="no">${esc(o.ts||'—')}</span>
      <span class="enxame-det-pontos">${o.workers.map(w=>`<i class="${classeDe(w)}" title="${esc(w.id)}"></i>`).join('')}</span>
    </div>`).join('')}</div>
    <h3 class="enxame-det-h">relatórios <i>${entregues.length}${temBytes?' · '+esc(exBytes(totBytes)):''}</i></h3>
    ${entregues.length?`<div class="enxame-det-lista">${entregues.map(w=>`<div class="enxame-det-item">
      <i style="background:${w.cor}"></i>
      <span><b translate="no">${esc(w.id)}</b>${caminho('resultados/'+w.id+'.md')}</span>
      <span class="peso">${esc(exBytes(w.resultadoBytes)||'')}</span></div>`).join('')}</div>`
      :'<p class="enxame-vazio">nenhum resultado em disco ainda.</p>'}
    <h3 class="enxame-det-h">atenção <i>${maus.length}</i></h3>
    ${maus.length?`<div class="enxame-det-lista">${maus.map(w=>`<div class="enxame-det-item ${w.estado==='falhou'?'mau':'morno'}">
      <i style="background:${w.estado==='falhou'?'var(--erro)':'var(--atencao)'}"></i>
      <span><b translate="no">${esc(w.id)}</b><code>${esc(w._v?w._v.rotulo:w.estado)}${w.nota?' · '+esc(w.nota):''}</code>
        ${caminho('logs/'+w.id+'.log')}</span>
      <span class="peso">${esc(exBytes(w.logBytes)||'')}</span></div>`).join('')}</div>`
      :'<p class="enxame-vazio">nada em falha nem em silêncio.</p>'}
    <p class="enxame-det-rodape">run <code>${esc(base)}</code><br>
      dados desta doca: <b>${esc(EX.rotulo)}</b>${temBytes?' · tamanhos medidos no disco':' · tamanhos indisponíveis nesta fonte'}</p>`;
  doca.scrollTop = rolagem;
}
/* Quando o modelo visual muda, este envelope impede que a troca necessária
   mate o scroll ou o foco de teclado. Tick sem mudança não entra aqui. */
function exTrocando(alvo, fn){
  const palco = alvo && alvo.parentElement;
  const y = palco ? palco.scrollTop : 0;
  const x = palco ? palco.scrollLeft : 0;
  const h = alvo ? alvo.offsetHeight : 0;
  const raiz = document.activeElement;
  const marca = raiz && raiz.closest ? raiz.closest('[data-foco]') : null;
  const chave = marca ? marca.dataset.foco : null;
  if (h) alvo.style.minHeight = h + 'px';
  fn();
  if (palco){
    if (palco.scrollTop !== y) palco.scrollTop = y;
    if (palco.scrollLeft !== x) palco.scrollLeft = x;
  }
  if (chave){
    let volta = null;
    try { volta = document.querySelector('[data-foco="'+CSS.escape(chave)+'"]'); } catch(e){}
    if (volta && typeof volta.focus === 'function') volta.focus({preventScroll:true});
  }
  requestAnimationFrame(()=>{ if (alvo) alvo.style.minHeight = ''; });
}
function exExpiraClasse(alvo, classe, espera){
  if (!alvo || !alvo.classList.contains(classe)) return;
  const tira = ()=>{
    alvo.removeEventListener('animationend', animou);
    if (alvo.classList.contains(classe)) alvo.classList.remove(classe);
  };
  const animou = ev=>{ if (ev.target===alvo || alvo.contains(ev.target)) tira(); };
  alvo.addEventListener('animationend', animou);
  setTimeout(tira, espera);
}
function exDetectar(runs){
  const novo = new Map(); const eventos = [];
  for (const r of runs) for (const w of r.workers){
    const k = r.id+'/'+w.id, p = EX.anterior.get(k);
    if (p && !EX.primeira && (p.feitas !== w.feitas || p.estado !== w.estado))
      eventos.push({w, txt: p.estado!==w.estado ? (EX_ROTULO[w.estado]||w.estado) : `etapa ${w.feitas}/${w.etapas}`});
    novo.set(k, {feitas:w.feitas, estado:w.estado});
  }
  EX.anterior = novo;
  if (!eventos.length || !EX.log) return;
  for (const e of eventos){
    const p = document.createElement('p');
    p.innerHTML = `<i translate="no">${esc(e.w.ts||'—')}</i><b translate="no">${esc(e.w.id)}</b> · ${esc(e.txt)}${e.w.nota?' · '+esc(e.w.nota):''}`;
    EX.log.prepend(p);
  }
  while (EX.log.children.length > 60) EX.log.lastChild.remove();
}
function exRender(runs){
  let vivos=0, ok=0, fal=0, sil=0, tot=0;
  const html = [];
  EX.runs = runs.map(r=>r.id);
  if (EX.swarm && !EX.runs.includes(EX.swarm)) EX.swarm = null;
  if (EX.swarm) runs = [...runs].sort((a,b)=>(b.id===EX.swarm)-(a.id===EX.swarm));
  EX.dados = runs;
  for (const run of runs){
    const agora = Math.max(0, ...run.workers.map(w=>exSeg(w.ts)??0)) || null;
    let rOk=0, rViv=0, rFal=0, rSil=0;
    for (const w of run.workers){
      tot++; w._v = exVivacidade(w, agora);
      if (w.estado==='entregue') ok++, rOk++;
      else if (w.estado==='falhou') fal++, rFal++;
      else if (w._v.alerta) sil++, rSil++;
      else if (!EX_TERMINAL.has(w.estado)) vivos++, rViv++;
    }
    const n = run.workers.length || 1;
    const cores = run.workers.map(w=>w.cor);
    run._m = {ok:rOk, viv:rViv, fal:rFal, sil:rSil, n:run.workers.length, agora,
      filete: cores.length ? cores[Math.floor(cores.length/2)] : 'var(--ouro)'};
    const dobrado = EX_DOBRADOS.has(run.id), alvoDoca = (EX.swarm===run.id);
    const ondas = run.ondas.map(o=>{
      const linhas = o.workers.filter(exPassa).map(w=>exLinhaWorker(w, run.id)).join('');
      if (!linhas) return '';
      return `<section class="enxame-onda"><h3 class="enxame-onda-cab">onda ${o.n}
        ${o.ts?`· <b translate="no">${esc(o.ts)}</b>`:''} · ${o.workers.length} worker${o.workers.length>1?'s':''}</h3>${linhas}</section>`;
    }).join('');
    html.push(`<article class="enxame-reator${dobrado?' recolhido':''}${alvoDoca?' selecionado':''}" style="--filete:${run._m.filete}">
      <div class="enxame-reator-topo">
        <button class="enxame-dobra" type="button" data-dobra="${esc(run.id)}" data-foco="dobra:${esc(run.id)}"
                aria-expanded="${!dobrado}" aria-label="${dobrado?'expandir':'recolher'} ${esc(run.id)}"><b>▾</b></button>
        <div class="enxame-abre" role="button" tabindex="0" data-abre="${esc(run.id)}" data-foco="abre:${esc(run.id)}"
             aria-pressed="${alvoDoca}" aria-label="abrir o detalhe de ${esc(run.id)}">
          <h3 translate="no">${esc(run.id)}</h3>
          <p class="enxame-missao">${esc(run.missao||'sem missao.md')}</p>
        </div>
        <div class="enxame-num"><b style="color:${rFal?'var(--erro)':'var(--ok)'}">${rOk}<small style="color:var(--tinta-3);font-size:15px">/${n}</small></b>
          <span>entregues${agora!=null?` · <b style="font-size:9.5px;letter-spacing:.14em" translate="no">${esc(exHhmm(agora))}</b>`:''}</span></div>
      </div>
      <div class="enxame-agg" role="img" aria-label="${rOk} de ${n} entregues, ${rFal} falhas, ${rSil} em silêncio">
        <i class="i-ok" style="width:${rOk/n*100}%"></i>
        <i class="i-fal" style="width:${rFal/n*100}%"></i>
        <i class="i-viv" style="width:${rViv/n*100}%"></i>
        <i class="i-sil" style="width:${rSil/n*100}%"></i>
      </div>
      <div class="enxame-corpo">${ondas||'<p class="enxame-vazio">nenhum worker neste filtro.</p>'}</div>
    </article>`);
  }
  const sigReatores = exSigReatores(runs);
  if (EX.sig.reatores !== sigReatores){
    const estreia = EX.primeira;
    if (EX.raiz && estreia) EX.raiz.classList.toggle('estreia', true);
    exTrocando(EX.reatores, ()=>{
      EX.reatores.innerHTML = html.join('') || '<p class="enxame-vazio">nenhum swarm encontrado em ~/.claude/iaswarm-runs.</p>';
    });
    EX.sig.reatores = sigReatores;
    exAtualizaDobrar();
    if (EX.raiz && estreia) exExpiraClasse(EX.raiz, 'estreia', 700);
    $$('.enxame-w.avancou', EX.reatores).forEach(w=>exExpiraClasse(w, 'avancou', 700));
  }
  const sigDoca = exSigDoca(runs);
  if (EX.sig.doca !== sigDoca){
    exRenderDoca(runs);
    EX.sig.doca = sigDoca;
  }
  const placar = [
    ['swarms',runs.length,''],['workers',tot,''],
    ['em curso',vivos,'viv'],['entregues',ok,'ok'],
    ['silêncio',sil,'sil'],['falhas',fal,'fal']
  ];
  const sigPlacar = JSON.stringify(placar.map(([,v])=>v));
  if (EX.sig.placar !== sigPlacar){
    EX.placar.innerHTML = placar
      .map(([r,v,c])=>`<div class="enxame-tile ${c}"><dt>${r}</dt><dd>${v}</dd></div>`).join('');
    EX.sig.placar = sigPlacar;
  }
  const sigFonte = JSON.stringify([EX.vivo,EX.rotulo]);
  if (EX.sig.fonte !== sigFonte){
    EX.fonte.className = 'enxame-fonte'+(EX.vivo?' vivo':'');
    EX.fonte.innerHTML = `<span class="enxame-led" aria-hidden="true"></span>fonte <b translate="no">${esc(EX.rotulo)}</b>`;
    EX.sig.fonte = sigFonte;
  }
  exDetectar(runs);
  EX.sig.erro = null;
  EX.primeira = false;
}
async function exTick(){
  if (EX.ocupado || !EX.raiz) return;
  EX.ocupado = true;
  try { exRender(await exCarregar()); }
  catch(e){
    const mensagem = String(e.message||e);
    const sigErro = JSON.stringify(['falhou',mensagem]);
    if (EX.sig.erro !== sigErro){
      EX.reatores.innerHTML = `<p class="enxame-vazio">sem dados: ${esc(mensagem)}. A leitura é /api/iaswarm — se a rota não existir, o servidor é o velho.</p>`;
      EX.fonte.innerHTML = `<span class="enxame-led" aria-hidden="true"></span>fonte <b>falhou</b>`;
      EX.sig.erro = sigErro;
      EX.sig.reatores = null;
      EX.sig.fonte = null;
    }
  }
  finally { EX.ocupado = false; }
}

function remotoRestauraBotoes(){
  $$('[data-remoto-acao]', EX.remoto).forEach(b=>{
    b.disabled = false;
    b.setAttribute('aria-pressed', 'false');
    b.textContent = b.dataset.remotoAcao === 'parar' ? 'parar esta IA' : 'redisparar';
  });
}
function remotoResposta(html, erro=false){
  const alvo = $('#ex-remoto-acao-saida', EX.remoto);
  if (!alvo) return;
  alvo.innerHTML = html;
  alvo.dataset.erro = erro ? 'sim' : 'nao';
}
/** Um clique prevê; o segundo clique NO MESMO botão confirma com o recibo.
    Os dois botões são a allowlist visual inteira desta página. */
async function acaoRemota(nome){
  const opcoes = {
    parar: {cmd:'/parar', esperando:'vendo o que seria parado…', confirmar:'confirmar: parar esta IA'},
    refaz: {cmd:'/refaz', esperando:'prevendo a retomada…', confirmar:'confirmar: redisparar'},
  };
  const opcao = opcoes[nome];
  const alvo = EX.remotoAlvo;
  if (!opcao || !alvo) return;
  const c = COMANDOS.find(x=>x.cmd===opcao.cmd);
  if (!c) return;
  const anterior = EX.remotoAcao;
  const confirmando = anterior && anterior.nome === nome && anterior.recibo;
  const botoes = $$('[data-remoto-acao]', EX.remoto);
  botoes.forEach(b=>b.disabled=true);
  remotoResposta(`<b>${esc(confirmando?'executando…':opcao.esperando)}</b>`);

  let payload;
  if (confirmando){
    payload = {run:alvo.run, ia:alvo.worker, confirmado:true, recibo:anterior.recibo};
  } else {
    payload = {run:alvo.run, ia:alvo.worker, seco:true};
  }
  const d = await pedeComando(c, payload);
  // Uma resposta atrasada da página anterior nunca redesenha o worker novo.
  if (!EX.remotoAlvo || EX.remotoAlvo.run !== alvo.run ||
      EX.remotoAlvo.worker !== alvo.worker) return;

  if (d.degrada){
    EX.remotoAcao = null; remotoRestauraBotoes();
    return remotoResposta('<b>Este servidor ainda não tem a rota de ação.</b>', true);
  }
  if (d.ok === false || d.erro){
    EX.remotoAcao = null; remotoRestauraBotoes();
    return remotoResposta(`<b>recusado</b><br><code translate="no" style="white-space:pre-wrap">${esc(d.erro||'o comando recusou')}</code>`, true);
  }
  if (confirmando){
    EX.remotoAcao = null; remotoRestauraBotoes();
    const aviso = d.aviso ? `<br><code translate="no" style="white-space:pre-wrap">${esc(d.aviso)}</code>` : '';
    return remotoResposta(`<b>feito</b><br><code translate="no" style="white-space:pre-wrap">${esc(d.saida||'feito.')}</code>${aviso}`);
  }
  if (typeof d.recibo !== 'string' || !d.recibo){
    EX.remotoAcao = null; remotoRestauraBotoes();
    return remotoResposta('<b>previsão sem recibo: não vou oferecer confirmação.</b>', true);
  }
  EX.remotoAcao = {nome, recibo:d.recibo};
  remotoRestauraBotoes();
  const botao = $$('[data-remoto-acao]', EX.remoto)
    .find(b=>b.dataset.remotoAcao===nome);
  if (botao){
    botao.setAttribute('aria-pressed', 'true');
    botao.textContent = opcao.confirmar;
  }
  remotoResposta(`<b>previsão — nada aconteceu ainda</b><br><code translate="no" style="white-space:pre-wrap">${esc(d.saida||'')}</code>`);
}

async function abreRemoto(runId, workerId){
  EX.remotoAlvo = {run:runId, worker:workerId};
  EX.remotoAcao = null;
  EX.remoto.hidden = false;
  EX.remoto.innerHTML = `<p class="enxame-vazio">lendo o controle remoto de <b>${esc(workerId)}</b>…</p>`;
  try {
    const r = await fetch(url('/api/iaswarm/remoto', 'run='+encodeURIComponent(runId)+'&worker='+encodeURIComponent(workerId)), {cache:'no-store'});
    const d = await r.json();
    if (!r.ok) throw new Error(d.erro || ('HTTP '+r.status));
    const evs = d.eventos || [];
    const ultima = evs.length ? evs[evs.length-1] : {};
    const linhas = String(d.log||'').split('\n');
    const term = linhas.length ? linhas.map(ln=>{
      const m = ln.match(/^(\s*)(\S.*)$/);
      if (!m) return `<p class="enxame-term-linha">${esc(ln)}</p>`;
      return `<p class="enxame-term-linha">${esc(m[1])}<b>${esc(m[2].slice(0,48))}</b>${esc(m[2].slice(48))}</p>`;
    }).join('') : '<p class="enxame-term-linha">sem log em disco — o worker ainda não escreveu, ou o arquivo não chegou.</p>';
    EX.remoto.innerHTML = `
      <div class="enxame-doca-topo">
        <div>
          <h3 translate="no">${esc(d.worker)}</h3>
          <p class="enxame-missao">braço <b>${esc(d.braco||'—')}</b> · run <b translate="no">${esc(d.run)}</b>
            · ${esc(ultima.estado||'sem sinal')}${ultima.nota?' · '+esc(ultima.nota):''}</p>
        </div>
        <button class="enxame-fecha" type="button" id="ex-fecha-remoto" aria-label="fechar o controle remoto">✕</button>
      </div>
      <div class="enxame-controle" role="group" aria-label="ações para ${esc(d.worker)}">
        <button class="enxame-btn" type="button" data-remoto-acao="parar" aria-pressed="false">parar esta IA</button>
        <button class="enxame-btn" type="button" data-remoto-acao="refaz" aria-pressed="false">redisparar</button>
      </div>
      <p class="enxame-det-rodape" id="ex-remoto-acao-saida" role="status" aria-live="polite">
        Escolha uma ação para ver a previsão. Nada acontece no primeiro clique.
      </p>
      <div class="enxame-remoto-grade">
        <div>
          <h3 class="enxame-det-h">o que ela está fazendo</h3>
          <p class="enxame-meta">
            <span>etapas <b>${esc(d.etapas)}</b></span>
            <span>eventos <b>${evs.length}</b></span>
            ${d.log_bytes!=null?`<span>log <b>${esc(exBytes(d.log_bytes))}</b></span>`:''}
            ${d.resultado_bytes!=null?`<span>resultado <b>${esc(exBytes(d.resultado_bytes))}</b></span>`:''}
          </p>
          <ol>${evs.length?evs.map(p=>`<li><b>${p.etapa===-1?'✕':esc(p.etapa)}</b>
            <i translate="no">${esc(p.ts||'·')}</i><span>${esc(p.nota||p.estado||'—')}</span></li>`).join('')
            :'<li><span>nenhum evento em progress/*.jsonl.</span></li>'}</ol>
          ${d.caminho_log?`<p class="enxame-det-rodape">log <code>${esc(d.caminho_log)}</code></p>`:''}
          ${d.caminho_resultado?`<p class="enxame-det-rodape">resultado <code>${esc(d.caminho_resultado)}</code></p>`:''}
          ${d.resultado?`<h3 class="enxame-det-h">cabeçalho do resultado</h3>
            <p class="enxame-missao">${esc(d.resultado.split('\n').slice(0,8).join(' · '))}</p>`:''}
        </div>
        <div>
          <h3 class="enxame-det-h">terminal <i>cauda de ${TETO_VISIVEL_LOG()}</i></h3>
          <div class="enxame-term" role="log" aria-label="cauda do log">${term}</div>
          <p class="enxame-det-rodape">Isto é leitura: <b>digitar</b> no terminal da IA não atravessa o app, e
            não vai atravessar — stdin livre para um processo que roda com a sua conta é outra categoria de risco.
            <b>Parar</b> e <b>redisparar</b> já atravessam, pelos comandos <code>/parar</code> e <code>/refaz</code>,
            que mostram a previsão antes e só executam com o recibo daquela previsão.</p>
        </div>
      </div>`;
    EX.remoto.scrollIntoView({block:'nearest', behavior:'smooth'});
  } catch(e){
    EX.remoto.innerHTML = `<div class="enxame-doca-topo"><div><h3>controle remoto</h3>
      <p class="enxame-missao">não deu: ${esc(e.message||e)}</p></div>
      <button class="enxame-fecha" type="button" id="ex-fecha-remoto" aria-label="fechar">✕</button></div>`;
  }
}
function TETO_VISIVEL_LOG(){ return '8 KB'; }

if (EX.raiz){
  $('#btn-enxame').addEventListener('click', ()=> janelaEnxame());
  EX.raiz.addEventListener('click', ev=>{
    const nome = ev.target.closest('[data-remoto]');
    if (nome){
      ev.preventDefault(); ev.stopPropagation();
      const [runId, workerId] = nome.dataset.remoto.split('/');
      abreRemoto(runId, workerId); return;
    }
    const acao = ev.target.closest('[data-remoto-acao]');
    if (acao){
      ev.preventDefault();
      acaoRemota(acao.dataset.remotoAcao);
      return;
    }
    if (ev.target.closest('#ex-fecha-remoto')){ fechaRemotoEnxame(); return; }
    if (ev.target.closest('#ex-fecha-doca')){ fechaDocaEnxame(); return; }
    const cab = ev.target.closest('.enxame-w-cab');
    if (cab){
      const w = cab.closest('.enxame-w');
      w.classList.toggle('aberto');
      cab.setAttribute('aria-expanded', w.classList.contains('aberto'));
      return;
    }
    const dob = ev.target.closest('[data-dobra]');
    if (dob){
      const id = dob.dataset.dobra;
      if (EX_DOBRADOS.has(id)) EX_DOBRADOS.delete(id); else EX_DOBRADOS.add(id);
      exGravarDobra();
      const card = dob.closest('.enxame-reator');
      if (card){ card.classList.toggle('recolhido', EX_DOBRADOS.has(id));
        dob.setAttribute('aria-expanded', String(!EX_DOBRADOS.has(id))); }
      exAtualizaDobrar();
      EX.sig.reatores = exSigReatores(EX.dados);
      return;
    }
    const abre = ev.target.closest('[data-abre]');
    if (abre){ EX.swarm = (EX.swarm === abre.dataset.abre) ? null : abre.dataset.abre; exTick(); return; }
    const filtro = ev.target.closest('.enxame-btn[data-filtro]');
    if (filtro){
      EX.filtro = filtro.dataset.filtro;
      $$('.enxame-btn[data-filtro]').forEach(x=>x.setAttribute('aria-pressed', String(x===filtro)));
      exTick();
    }
  });
  EX.raiz.addEventListener('keydown', ev=>{
    if (ev.key !== 'Enter' && ev.key !== ' ') return;
    const abre = ev.target.closest && ev.target.closest('[data-abre]');
    if (abre){ ev.preventDefault(); EX.swarm = (EX.swarm===abre.dataset.abre)?null:abre.dataset.abre; exTick(); }
  });
  $('#ex-foco').addEventListener('click', e=>{
    const on = EX.raiz.dataset.foco === 'sim' ? 'nao' : 'sim';
    EX.raiz.dataset.foco = on;
    e.currentTarget.setAttribute('aria-pressed', String(on==='sim'));
  });
  $('#ex-dobrar').addEventListener('click', ()=>{
    const tudo = EX.runs.length && EX.runs.every(id=>EX_DOBRADOS.has(id));
    if (tudo) EX_DOBRADOS.clear(); else for (const id of EX.runs) EX_DOBRADOS.add(id);
    exGravarDobra(); exTick();
  });
  /* Um lugar só decide o modo, e o botão e a URL entram por ele. Duas funções
     escrevendo o mesmo `data-enxame-modo` divergiriam no rótulo ou no
     `aria-pressed` — foi o que aconteceu com os dois botões da gaveta hoje. */
  function poeModo(neon){
    const b = $('#ex-modo');
    document.documentElement.dataset.enxameModo = neon ? 'neon' : 'dourado';
    if (b){
      b.setAttribute('aria-pressed', String(neon));
      b.textContent = neon ? 'modo dourado' : 'modo neon';
    }
  }
  $('#ex-modo').addEventListener('click', ()=>
    poeModo(document.documentElement.dataset.enxameModo !== 'neon'));
  /* `?modo=neon` fecha a família dos endereços: tema, aba, janela, abrir, swarm
     e remoto já eram favoritáveis; o modo do enxame não era. Quem manda um link
     do painel neon esperando ver neon chegava no dourado. Só dois valores; nome
     desconhecido é ignorado, e o modo continua o que já estava. */
  { const pedido = new URLSearchParams(location.search).get('modo');
    if (pedido === 'neon' || pedido === 'dourado') poeModo(pedido === 'neon'); }
}

{
  const q = new URLSearchParams(location.search);
  const swarm = (q.get('swarm') || '').trim();
  const abrir = q.get('abrir');
  const remoto = q.get('remoto');
  if (swarm) EX.swarm = swarm;
  if (abrir){
    for (const w of abrir.split(',')){
      const id = w.trim();
      if (id) EX_ABRIR_URL.add(id);
    }
  }
  const pedidoJanela = q.get('janela');
  if (swarm || abrir || remoto || pedidoJanela === 'enxame') {
    janelaModo('enxame');
    if (remoto && remoto.includes('/')) {
      const [rid, wid] = remoto.split('/');
      setTimeout(()=> abreRemoto(rid, wid), 600);
    }
  } else {
    janelaModo(pedidoJanela === 'groupchat' ? 'groupchat' : 'sala');
  }
}

/* `?aba=mapa` abre a gaveta já na aba pedida. Existe pelo mesmo motivo do
   `?janela=enxame`: quem quer voltar direto a uma seção não deveria precisar de dois
   cliques toda vez — e um endereço que abre onde interessa é favoritável, inclusive na
   Tela de Início do celular. A allowlist é o próprio DOM: só abre aba que existe, então
   `?aba=qualquer-coisa` não faz nada em vez de quebrar. */
{
  const alvo = new URLSearchParams(location.search).get('aba');
  if (alvo && $('#aba-' + alvo)) {
    abreGaveta(true);
    abreAba(alvo);
  }
}
