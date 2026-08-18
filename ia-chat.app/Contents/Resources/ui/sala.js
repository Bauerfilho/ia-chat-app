/* ═══════════════════════════════════════════════════════════════════════════
   ia-chat · a sala — comportamento
   Vanilla, sem dependência. Fala com o servidor do `idea-servidor`:
     GET  /api/estado        -> {ultima}
     GET  /api/sala?desde=N  -> {ultima, desde, msgs[], sala{}}
     GET  /api/stream?desde=N-> SSE, event:msg
     POST /api/post          -> {de, texto, para[]}
   Endpoints opcionais (/api/quem /api/decisoes /api/reservas /api/fio) degradam:
   quando não existem, a interface deriva o que dá da própria sala e diz que derivou.
   ═══════════════════════════════════════════════════════════════════════════ */
'use strict';

/* ── doutrina de cor por IA (a quebra da paleta) ─────────────────────────── */
const IAS = ['claude','codex','kimi','agy','grok','qwen','ollama','deepseek','dourada','bauer'];
const DONO = 'bauer';

/* ── comandos do dono ────────────────────────────────────────────────────── */
const COMANDOS = [
  {cmd:'/goal',     desc:'Enunciar o objetivo da rodada',                quem:'ninguém executa',    pronto:true},
  {cmd:'/plan',     desc:'A frota ativa planeja junta e devolve o plano', quem:'todas as IAs vivas', pronto:true},
  {cmd:'/concluir', desc:'Autorizar: pode aplicar',                      quem:'quem foi designado', pronto:true},
  {cmd:'/parar',    desc:'Abortar a missão em andamento',                quem:'o servidor',         pronto:false},
  {cmd:'/quem',     desc:'Quem está vivo, no quê, há quanto tempo',      quem:'ia-roster',          pronto:false},
  {cmd:'/decidi',   desc:'Registrar decisão que todas obedecem',         quem:'ia-decide',          pronto:false},
  {cmd:'/refaz',    desc:'Redisparar worker morto de onde parou',        quem:'o servidor',         pronto:false},
];

const $  = (s,r=document)=>r.querySelector(s);
const $$ = (s,r=document)=>[...r.querySelectorAll(s)];

const E = {
  fio:$('#fio'), vazio:$('#vazio'), sala:$('#sala'), presenca:$('#presenca'),
  contador:$('#contador'), peso:$('#peso'), elo:$('#elo'), texto:$('#texto'),
  destino:$('#destino'), destinoTxt:$('#destino-texto'), destinoAlvos:$('#destino-alvos'),
  enviar:$('#enviar'), enviarRot:$('#enviar-rotulo'), conta:$('#conta'),
  paleta:$('#paleta'), busca:$('#busca'), avisos:$('#avisos'),
  descer:$('#descer'), descerN:$('#descer-n'), moldura:$('.moldura'),
};

const S = {
  msgs:[], ultima:0, sala:{na_sala:[],escrever:false,papel:DONO},
  naSala:[], sinos:{}, colado:true, novas:0, filtro:'', fio:null, fonte:null,
};

/* ── utilidades ──────────────────────────────────────────────────────────── */
const TOKEN = new URLSearchParams(location.search).get('t') || '';
const url = (rota, q='') => rota + (TOKEN||q ? '?' + [q, TOKEN?'t='+encodeURIComponent(TOKEN):''].filter(Boolean).join('&') : '');
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
  // caminho de verdade: precisa de uma segunda barra ou de extensão
  h = h.replace(/(^|[\s(])(~?\/[\w.~-]+(?:\/[\w.~-]+)+\/?|~?\/[\w~-]+\.\w{2,4})/g,
    '$1<span class="caminho">$2</span>');
  h = h.replace(/(^|\s)@(all|todas)\b/gi, '$1<span class="mencao mencao--todas">@todas</span>');
  h = h.replace(/(^|\s)@([a-z0-9_-]{2,20})\b/gi,
    // as DUAS variantes: `-t` para o papel palha, viva para o cartão do dono (carvão)
    (_,a,n)=>{ const c = corDe(n.toLowerCase());
      return `${a}<span class="mencao" style="--ia-t:var(--${c}-t);--ia:var(--${c})">@${esc(n)}</span>`; });

  return h.split(/\n{2,}/).map(bloco=>{
    const linhas = bloco.split('\n');
    if (linhas.every(l => /^\s*[-*·]\s+/.test(l) || !l.trim()))
      return '<ul>' + linhas.filter(l=>l.trim()).map(l=>`<li>${l.replace(/^\s*[-*·]\s+/,'')}</li>`).join('') + '</ul>';
    return '<p>' + linhas.join('<br>') + '</p>';
  }).join('');
}

/* ── render da sala ──────────────────────────────────────────────────────── */
function paraLegivel(para){
  const l = Array.isArray(para) ? para : (para ? [para] : []);
  if (!l.length) return {html:'<b>todas</b>', lista:S.naSala};
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
  art.innerHTML = `
    <div class="msg-cabeca">
      <span class="msg-de">${esc(m.de)}</span>
      <span class="msg-seta" aria-hidden="true">→</span>
      <span class="msg-para">${paraLegivel(m.para).html}</span>
      <span class="msg-hora"><span class="msg-n">#${m.n}</span> · ${fmtHora.format(d)}</span>
    </div>
    <div class="msg-corpo">${corpoHTML(m.texto)}</div>
    <div class="msg-pe">
      <button type="button" class="msg-acao" data-acao="fio">ver o fio</button>
      <button type="button" class="msg-acao" data-acao="responder">responder a ${esc(m.de)}</button>
      <button type="button" class="msg-acao" data-acao="copiar">copiar</button>
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
}

/** mensagem nova: anexa só ela. A lista não é redesenhada a cada evento. */
function anexaMsg(m){
  if (S.filtro) return desenhaMsgs();
  const dia = new Date(m.ts).toDateString();
  if (dia !== E.fio.dataset.dia){ E.fio.append(noDia(m.ts)); E.fio.dataset.dia = dia; }
  E.fio.append(noMsg(m));
  E.vazio.hidden = true;
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

function desenhaDecisoes(){
  const el = $('#decisoes');
  const achadas = S.msgs.filter(m => /(^|\s)\/(decidi|concluir)\b/i.test(m.texto));
  el.innerHTML = achadas.length ? '' :
    '<li class="nada">Nenhuma decisão registrada ainda.</li>';
  achadas.reverse().forEach(m=>{
    const li = document.createElement('li');
    li.className = 'cartao';
    li.style.setProperty('--ia-t', `var(--${corDe(m.de)}-t)`);
    li.innerHTML = `<div class="decisao-txt">${corpoHTML(m.texto.replace(/^\s*\/\w+\s*/,''))}</div>
      <div class="decisao-pe"><span class="selo-ia">${esc(m.de)}</span>
      <span>·</span><span>#${m.n} · há ${haQuanto(m.ts)}</span></div>`;
    li.addEventListener('click', ()=> irPara(m.n));
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
                    <span class="reserva-quem">${esc(quem)}</span>`;
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
    E.destinoTxt.innerHTML = 'isto vai para <b>todas</b> as IAs da sala';
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
let paletaIdx = 0;
function abrePaleta(prefixo){
  const itens = COMANDOS.filter(c => c.cmd.startsWith(prefixo));
  if (!itens.length){ E.paleta.hidden = true; return; }
  paletaIdx = 0;
  E.paleta.hidden = false;
  E.paleta.innerHTML = itens.map((c,i)=>`
    <button type="button" class="paleta-item" role="option" data-cmd="${c.cmd}"
            data-vindouro="${c.pronto?'nao':'sim'}" aria-selected="${i===0}">
      <span class="paleta-cmd" translate="no">${c.cmd}</span>
      <span class="paleta-desc">${c.desc}</span>
      <span class="paleta-quem">${c.pronto ? c.quem : 'a implementar'}</span>
    </button>`).join('');
  $$('.paleta-item', E.paleta).forEach(b=>
    b.addEventListener('click', ()=> escolhePaleta(b.dataset.cmd)));
}
function escolhePaleta(cmd){
  E.texto.value = cmd + ' ';
  E.paleta.hidden = true;
  E.texto.focus();
  ajustaAltura(); atualizaDestino();
}
function navegaPaleta(passo){
  const itens = $$('.paleta-item', E.paleta);
  if (!itens.length) return;
  paletaIdx = (paletaIdx + passo + itens.length) % itens.length;
  itens.forEach((b,i)=> b.setAttribute('aria-selected', i===paletaIdx));
  itens[paletaIdx].scrollIntoView({block:'nearest'});
}

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
    desenhaMsgs(); desenhaPresenca(); desenhaCabeca(); desenhaGaveta(); atualizaDestino();
    requestAnimationFrame(()=> desce(false));
    elo('viva', S.sala.escrever ? 'sala aberta' : 'somente leitura');
    if (!S.sala.escrever) E.enviar.disabled = true;
    abreFluxo();
  }catch(e){
    elo('caiu','sem conexão');
    avisa('Não consegui ler a sala. <b>Confira se o servidor está no ar.</b>','erro');
  }
}

function abreFluxo(){
  if (S.fonte) S.fonte.close();
  S.fonte = new EventSource(url('/api/stream','desde='+S.ultima));
  S.fonte.addEventListener('open', ()=> elo('viva', S.sala.escrever ? 'sala aberta' : 'somente leitura'));
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
    E.texto.value = ''; ajustaAltura(); atualizaDestino();
    E.paleta.hidden = true; S.colado = true;
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
  if (/^\/\w*$/.test(v)) abrePaleta(v); else E.paleta.hidden = true;
});

E.texto.addEventListener('keydown', ev=>{
  if (!E.paleta.hidden){
    if (ev.key === 'ArrowDown'){ ev.preventDefault(); return navegaPaleta(1); }
    if (ev.key === 'ArrowUp'){ ev.preventDefault(); return navegaPaleta(-1); }
    if (ev.key === 'Escape'){ ev.preventDefault(); E.paleta.hidden = true; return; }
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

function abreAba(qual){
  $$('.aba').forEach(a=>{
    const ativo = a.dataset.pnl === qual;
    a.setAttribute('aria-selected', ativo);
    $('#pnl-' + a.dataset.pnl).hidden = !ativo;
  });
}
$$('.aba').forEach(a=>{
  a.addEventListener('click', ()=> abreAba(a.dataset.pnl));
  a.addEventListener('keydown', ev=>{
    if (ev.key !== 'ArrowRight' && ev.key !== 'ArrowLeft') return;
    const abas = $$('.aba'), i = abas.indexOf(a);
    const alvo = abas[(i + (ev.key === 'ArrowRight' ? 1 : -1) + abas.length) % abas.length];
    alvo.focus(); abreAba(alvo.dataset.pnl);
  });
});

function abreGaveta(forcar){
  const aberta = forcar !== undefined ? forcar : E.moldura.dataset.gaveta !== 'aberta';
  E.moldura.dataset.gaveta = aberta ? 'aberta' : 'fechada';
  $('#btn-gaveta').setAttribute('aria-expanded', String(aberta));
}
$('#btn-gaveta').addEventListener('click', ()=> abreGaveta());

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
  if (ev.key === 'Escape' && document.activeElement === E.busca){
    E.busca.value = ''; S.filtro = ''; desenhaMsgs(); E.texto.focus();
  }
});

/* ── arranque ────────────────────────────────────────────────────────────── */
E.moldura.dataset.gaveta = 'aberta';
try{ const t = localStorage.getItem('ia-chat-tema'); if (t) tema(t); }catch(e){}
if (window.CONGELADO){                       // export offline: a sala vem dentro do HTML
  const d = window.CONGELADO;
  S.msgs = d.msgs||[]; S.ultima = d.ultima||0; S.sala = d.sala||S.sala;
  S.naSala = (S.sala.na_sala||[]).filter(x => x && x !== S.sala.papel);
  desenhaMsgs(); desenhaPresenca(); desenhaCabeca(); desenhaGaveta(); atualizaDestino();
  elo('caiu','cópia congelada'); E.enviar.disabled = true;
  requestAnimationFrame(()=> desce(false));
} else {
  carrega();
}
ajustaAltura();
// foco inicial: desktop, campo primário único — é onde a mão dele já está
if (matchMedia('(pointer:fine)').matches) E.texto.focus();
