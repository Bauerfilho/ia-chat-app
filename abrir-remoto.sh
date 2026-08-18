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
# Ponto fixo do celular: iCloud Drive/ia-chat/sala.html. Sobrescreva o caminho
# com IACHAT_PONTE_CELULAR (os testes apontam para pasta temporária — a bateria
# nunca escreve no iCloud real).
INTERVALO="${IACHAT_VIGIA_S:-60}"
TETO_QUEDAS="${IACHAT_VIGIA_TETO:-5}"
PONTE_CELULAR_GRAVADA=""

url_do_log() { grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG_TUN" 2>/dev/null | tail -1; }
token_do_log() { grep -oE '\?t=[A-Za-z0-9_-]+' "$LOG_SRV" 2>/dev/null | tail -1 | cut -d= -f2; }
tunel_vivo() { pgrep -f "cloudflared tunnel --url http://127.0.0.1:$PORTA" >/dev/null 2>&1; }

registra_link() {   # url token — deixa o endereço onde o celular acha sem ler log
  # O túnel gratuito troca o hostname. O CAMINHO desta ponte não troca: o celular
  # abre sempre o mesmo arquivo e é mandado para o endereço vivo. Sem isso, o
  # aviso na sala é circular — a sala só se alcança pelo endereço que acabou de
  # mudar.
  [ -n "${1:-}" ] && [ -n "${2:-}" ] || return 0
  local destino dir tmp tmp_txt txt url
  url="$1/?t=$2"
  printf '%s\n# gerado em %s\n' "$url" "$(date '+%Y-%m-%d %H:%M:%S')" > "$LINK"
  chmod 600 "$LINK" 2>/dev/null || true

  destino="${IACHAT_PONTE_CELULAR:-}"
  if [ -z "$destino" ] && [ -d "$HOME/Library/Mobile Documents/com~apple~CloudDocs" ]; then
    destino="$HOME/Library/Mobile Documents/com~apple~CloudDocs/ia-chat/sala.html"
  fi
  [ -n "$destino" ] || return 0
  dir="$(dirname "$destino")"
  mkdir -p "$dir" 2>/dev/null || return 0
  tmp="$destino.tmp.$$"
  cat > "$tmp" <<EOF || { rm -f "$tmp"; return 0; }
<!DOCTYPE html>
<html lang="pt-BR">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="0;url=$url">
<title>ia-chat</title>
<p style="font:20px/1.4 -apple-system,sans-serif;margin:2rem">
<a href="$url">abrir a sala</a>
</p>
</html>
EOF
  chmod 600 "$tmp" 2>/dev/null || true
  mv -f "$tmp" "$destino" 2>/dev/null || { rm -f "$tmp"; return 0; }
  case "$destino" in
    *.html)
      txt="${destino%.html}.txt"
      tmp_txt="$txt.tmp.$$"
      if printf '%s\n' "$url" > "$tmp_txt" 2>/dev/null; then
        chmod 600 "$tmp_txt" 2>/dev/null || true
        mv -f "$tmp_txt" "$txt" 2>/dev/null || rm -f "$tmp_txt"
      else
        rm -f "$tmp_txt"
      fi
      ;;
  esac
  PONTE_CELULAR_GRAVADA="$destino"
  return 0
}

responde() {   # url token — a prova é de FORA, pelo próprio túnel, não pelo pid
  #
  # ⚠️ O DNS DESTA MÁQUINA PODE ESTAR CEGO. Medido em 18/08: `dig` pelo 8.8.8.8 e pelo
  # 1.1.1.1 resolviam `*.trycloudflare.com`, e o resolvedor do sistema devolvia VAZIO. O
  # `curl` usa o do sistema, então esta função dizia "fora do ar" sobre um túnel que
  # respondia 200 para o mundo — e a vigia entrou em ciclo tentando consertar o que não
  # estava quebrado. Eu quase reportei "o Cloudflare caiu".
  #
  # Então: tenta pelo caminho normal e, se falhar, RESOLVE por um DNS público e conecta
  # pelo IP com `--resolve`. Só declara queda quando as DUAS rotas falham.
  [ -n "${1:-}" ] && [ -n "${2:-}" ] || return 1
  local host code ip
  host="${1#https://}"; host="${host%%/*}"
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$1/?t=$2" 2>/dev/null)"
  [ "$code" = "200" ] && return 0
  for ip in $(dig +short +time=5 @1.1.1.1 "$host" 2>/dev/null | head -2); do
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 \
            --resolve "$host:443:$ip" "https://$host/?t=$2" 2>/dev/null)"
    [ "$code" = "200" ] && return 0
  done
  return 1
}

# ── vigiar ──────────────────────────────────────────────────────────────────
# O túnel gratuito cai sozinho, e quando volta o endereço é OUTRO. Se ele está
# na rua quando isso acontece, perde a sala e nem sabe qual é o link novo.
# Esta vigia ADOTA o que já está no ar — nunca derruba um túnel que responde,
# porque derrubar para "consertar" trocaria o endereço que ele está usando.
#
# Quando o endereço muda, a ponte (iCloud Drive/ia-chat/sala.html) é o ponto
# fixo que o celular abre — o caminho não muda, só o conteúdo. A sala ainda
# recebe o aviso (outro Mac / sessão que já estava aberta). Endereço fixo de
# verdade exige túnel nomeado com conta Cloudflare; é decisão dele.
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
    # ⚠️ RECUO E TETO. Sem eles, a vigia vira o problema: em 18/08 ela tentou 6 vezes em 6
    # minutos, e como cada tentativa MATA o servidor para subir outro, ela derrubava um
    # servidor bom a cada volta. O remédio matando o paciente, exatamente o risco que o
    # gate desta peça previa — e que eu só vi quando o dono não conseguiu abrir o link.
    if [ "$quedas" -gt "$TETO_QUEDAS" ]; then
      echo "[$(date '+%H:%M:%S')] $quedas quedas seguidas — PARO de tentar."
      echo "  Insistir aqui é derrubar servidor bom em looping. Veja /tmp/iachat-remoto-vigia.log"
      echo "  e suba à mão com:  $0"
      exit 1
    fi
    espera=$(( INTERVALO * quedas ))     # recuo linear: 60s, 120s, 180s…
    echo "[$(date '+%H:%M:%S')] caiu (queda $quedas de $TETO_QUEDAS) — levantando…"
    if ! "$0" >/tmp/iachat-remoto-vigia.log 2>&1; then
      echo "[$(date '+%H:%M:%S')] não consegui levantar; próxima tentativa em ${espera}s"
      sleep "$espera"; continue
    fi
    queda_n=$quedas                       # guarda ANTES de zerar: o post não pode dizer 0
    quedas=0                              # levantou: o contador zera
    nu="$(url_do_log)"; nt="$(token_do_log)"
    registra_link "$nu" "$nt"
    if [ "$nu" != "$u" ] && [ -n "$nu" ]; then
      echo "[$(date '+%H:%M:%S')] ENDEREÇO NOVO: $nu/?t=$nt"
      # a sala ainda é avisada: quem já estava nela (outro aparelho, LAN)
      # vê o endereço novo. O celular na rua usa a ponte, não este post.
      if [ -n "$PONTE_CELULAR_GRAVADA" ]; then
        aviso_celular="No celular: Arquivos → iCloud Drive → ia-chat → sala.html"
      else
        aviso_celular="Ponte iCloud não gravada; link local: $LINK"
      fi
      printf '📱 O endereço do túnel mudou (queda %s). O novo é:\n\n%s/?t=%s\n\n%s\n' \
        "$queda_n" "$nu" "$nt" "$aviso_celular" \
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
: > "$LOG_TUN"   # mesmo motivo do servidor
nohup cloudflared tunnel --url "http://127.0.0.1:$PORTA" --no-autoupdate > "$LOG_TUN" 2>&1 &
URL=""
for _ in $(seq 1 40); do
  sleep 1
  URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG_TUN" | head -1 || true)"
  [ -n "$URL" ] && break
done
[ -n "$URL" ] || { echo "✗ o túnel não subiu em 40 s. Veja $LOG_TUN" >&2; exit 1; }

# 2. o servidor, já sabendo a origem
# ⚠️ ESPERAR A PORTA LIBERAR DE VERDADE. `kill` + `sleep 1` não basta: o socket fica em
# TIME_WAIT e o servidor novo morre com `OSError: [Errno 48] Address already in use`.
# Medido em 18/08: isso derrubou o túnel do dono e pôs a vigia em LOOP — 6 quedas em 6
# minutos, cada ciclo matando um servidor bom e falhando ao subir o próximo. Na ponta o
# sintoma era 401, porque o token lido do log pertencia a um servidor que já não existia.
pid="$(/usr/sbin/lsof -nP -iTCP:$PORTA -sTCP:LISTEN -t 2>/dev/null | head -1 || true)"
[ -n "$pid" ] && kill "$pid" 2>/dev/null || true
for _ in $(seq 1 30); do
  /usr/sbin/lsof -nP -iTCP:$PORTA -sTCP:LISTEN -t >/dev/null 2>&1 || break
  sleep 0.5
done
if /usr/sbin/lsof -nP -iTCP:$PORTA -sTCP:LISTEN -t >/dev/null 2>&1; then
  echo "✗ a porta $PORTA não liberou em 15 s — não vou subir por cima." >&2; exit 1
fi
# o log é truncado: o token tem que ser o DESTE servidor. Log acumulativo faz o `tail -1`
# mentir com confiança — foi o que aconteceu.
: > "$LOG_SRV"
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

registra_link "$URL" "$TOKEN"

echo
echo "📱  $URL/?t=$TOKEN"
echo
echo "    No iPhone: Safari → Compartilhar → Adicionar à Tela de Início."
echo "    Vira ícone e abre em tela cheia."
echo
if [ -n "$PONTE_CELULAR_GRAVADA" ]; then
  echo "    Se o endereço mudar (túnel gratuito cai e volta outro):"
  echo "    iPhone → Arquivos → iCloud Drive → ia-chat → sala.html"
  echo "    Esse caminho não muda. Só o conteúdo."
else
  echo "    ⚠ ponte móvel não criada; confira o iCloud Drive ou IACHAT_PONTE_CELULAR."
fi
echo
echo "    O link também fica em: $LINK"
echo "    Manter no ar:  $0 --vigiar   (ressuscita se cair)"
echo "    Fechar:        $0 --parar"
