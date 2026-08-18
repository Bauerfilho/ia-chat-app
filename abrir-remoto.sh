#!/bin/bash
# abrir-remoto.sh — publica a sala num túnel e imprime o link do celular.
#
# Existe porque o túnel gratuito do Cloudflare é EFÊMERO: o endereço muda a cada
# execução, e quem depende dele não pode depender de alguém estar por perto para
# gerar o próximo. Este script sobe os dois pedaços (servidor + túnel), espera a URL
# aparecer, e só então declara pronto — checando de fora, pelo próprio túnel.
#
#   ./abrir-remoto.sh          # sobe e imprime o link
#   ./abrir-remoto.sh --vigiar # mantém no ar; ressuscita se cair (adota o que já existe)
#   ./abrir-remoto.sh --parar  # derruba tudo
#
# ⚠️ ISTO PUBLICA A SALA NA INTERNET. Quem tiver o link COM o token entra e escreve;
# sem o token, 401. O endereço é aleatório e não indexado, mas o token viaja na URL —
# ele vaza em histórico de navegador e em captura de tela. Feche quando terminar.
set -euo pipefail
RAIZ="$(cd "$(dirname "$0")" && pwd)"
PORTA="${IACHAT_PORTA_REMOTA:-8899}"
LOG_SRV=/tmp/iachat-remoto-servidor.log
LOG_TUN=/tmp/iachat-remoto-tunel.log
LINK="${IACHAT_LINK_REMOTO:-$HOME/ia-chat-global/link-remoto.txt}"
INTERVALO="${IACHAT_VIGIA_S:-60}"

url_do_log() { grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG_TUN" 2>/dev/null | tail -1; }
token_do_log() { grep -oE '\?t=[A-Za-z0-9_-]+' "$LOG_SRV" 2>/dev/null | tail -1 | cut -d= -f2; }
tunel_vivo() { pgrep -f "cloudflared tunnel --url http://127.0.0.1:$PORTA" >/dev/null 2>&1; }
responde() {   # url token — a prova é de FORA, pelo próprio túnel, não pelo pid
  [ -n "${1:-}" ] && [ -n "${2:-}" ] || return 1
  [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$1/?t=$2" 2>/dev/null)" = "200" ]
}

# ── vigiar ──────────────────────────────────────────────────────────────────
# O túnel gratuito cai sozinho, e quando volta o endereço é OUTRO. Se ele está
# na rua quando isso acontece, perde a sala e nem sabe qual é o link novo.
# Esta vigia ADOTA o que já está no ar — nunca derruba um túnel que responde,
# porque derrubar para "consertar" trocaria o endereço que ele está usando.
#
# ⚠️ O que esta vigia NÃO resolve: quando o endereço MUDA, ele precisa descobrir
# o novo, e o caminho para descobrir é a própria sala — que ele só alcança pelo
# endereço. Endereço fixo exige túnel nomeado com conta Cloudflare; é decisão
# dele, e está anotado aqui em vez de fingido.
if [ "${1:-}" = "--vigiar" ]; then
  command -v cloudflared >/dev/null || { echo "✗ cloudflared ausente" >&2; exit 1; }
  quedas=0
  echo "👁  vigiando a cada ${INTERVALO}s · Ctrl-C para sair"
  while :; do
    u="$(url_do_log)"; t="$(token_do_log)"
    if responde "$u" "$t"; then
      sleep "$INTERVALO"; continue
    fi
    quedas=$((quedas + 1))
    echo "[$(date '+%H:%M:%S')] caiu (queda $quedas) — levantando…"
    "$0" >/tmp/iachat-remoto-vigia.log 2>&1 || { sleep "$INTERVALO"; continue; }
    nu="$(url_do_log)"; nt="$(token_do_log)"
    if [ "$nu" != "$u" ] && [ -n "$nu" ]; then
      echo "[$(date '+%H:%M:%S')] ENDEREÇO NOVO: $nu/?t=$nt"
      # a sala é o único canal que sobrevive à troca: quem abrir de qualquer
      # outro lugar vê o endereço novo escrito lá.
      printf '📱 O endereço do túnel mudou (queda %s). O novo é:\n\n%s/?t=%s\n' \
        "$quedas" "$nu" "$nt" \
        | "${IACHAT_CLI:-$HOME/Projetos/ia-chat/bin/iachat}" post --de claude --para bauer 2>/dev/null \
        || echo "   (não consegui postar na sala — o link está em $LINK)"
    fi
    sleep "$INTERVALO"
  done
fi

if [ "${1:-}" = "--parar" ]; then
  pkill -f "cloudflared tunnel --url http://127.0.0.1:$PORTA" 2>/dev/null || true
  pid="$(/usr/sbin/lsof -nP -iTCP:$PORTA -sTCP:LISTEN -t 2>/dev/null | head -1 || true)"
  [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
  echo "✔ túnel e servidor encerrados — a sala saiu da internet."
  exit 0
fi

command -v cloudflared >/dev/null || { echo "✗ cloudflared ausente:  brew install cloudflared" >&2; exit 1; }

# 1. o túnel PRIMEIRO, porque o servidor precisa saber a origem para o anti-CSRF
#    aceitar o POST. Na ordem inversa, a sala carrega e o ENVIO toma 403 — o pior
#    tipo de defeito, o que parece funcionar.
pkill -f "cloudflared tunnel --url http://127.0.0.1:$PORTA" 2>/dev/null || true
nohup cloudflared tunnel --url "http://127.0.0.1:$PORTA" --no-autoupdate > "$LOG_TUN" 2>&1 &
URL=""
for _ in $(seq 1 40); do
  sleep 1
  URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG_TUN" | head -1 || true)"
  [ -n "$URL" ] && break
done
[ -n "$URL" ] || { echo "✗ o túnel não subiu em 40 s. Veja $LOG_TUN" >&2; exit 1; }

# 2. o servidor, já sabendo a origem
pid="$(/usr/sbin/lsof -nP -iTCP:$PORTA -sTCP:LISTEN -t 2>/dev/null | head -1 || true)"
[ -n "$pid" ] && kill "$pid" 2>/dev/null || true
sleep 1
IACHAT_ORIGEM="$URL" nohup python3 -u "$RAIZ/ui/servir.py" \
  --porta "$PORTA" --escrever --papel "${IACHAT_PAPEL:-bauer}" > "$LOG_SRV" 2>&1 &

TOKEN=""
for _ in $(seq 1 30); do
  sleep 0.5
  TOKEN="$(grep -oE '\?t=[A-Za-z0-9_-]+' "$LOG_SRV" | tail -1 | cut -d= -f2 || true)"
  [ -n "$TOKEN" ] && break
done
[ -n "$TOKEN" ] || { echo "✗ o servidor não imprimiu o token. Veja $LOG_SRV" >&2; exit 1; }

# 3. PROVA pelo próprio túnel — não basta ter subido, tem que responder de fora.
CODIGO="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$URL/?t=$TOKEN" || echo 000)"
[ "$CODIGO" = "200" ] || { echo "✗ o túnel respondeu HTTP $CODIGO — não vou dizer que está pronto." >&2; exit 1; }

registra_link() {   # url token — deixa o endereço onde dá para achar sem ler log
  printf '%s/?t=%s\n' "$1" "$2" > "$LINK"
  printf '# gerado em %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" >> "$LINK"
}
registra_link "$URL" "$TOKEN"

echo
echo "📱  $URL/?t=$TOKEN"
echo
echo "    No iPhone: Safari → Compartilhar → Adicionar à Tela de Início."
echo "    Vira ícone e abre em tela cheia."
echo
echo "    O link também fica em: $LINK"
echo "    Manter no ar:  $0 --vigiar   (ressuscita se cair)"
echo "    Fechar:        $0 --parar"
