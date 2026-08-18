#!/bin/bash
# abrir-remoto.sh — publica a sala num túnel e imprime o link do celular.
#
# Existe porque o túnel gratuito do Cloudflare é EFÊMERO: o endereço muda a cada
# execução, e quem depende dele não pode depender de alguém estar por perto para
# gerar o próximo. Este script sobe os dois pedaços (servidor + túnel), espera a URL
# aparecer, e só então declara pronto — checando de fora, pelo próprio túnel.
#
#   ./abrir-remoto.sh          # sobe e imprime o link
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

echo
echo "📱  $URL/?t=$TOKEN"
echo
echo "    No iPhone: Safari → Compartilhar → Adicionar à Tela de Início."
echo "    Vira ícone e abre em tela cheia."
echo
echo "    Fechar:  $0 --parar"
