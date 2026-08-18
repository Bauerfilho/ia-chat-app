#!/bin/bash
# ia-chat-app — instalador do app desktop.
#
# Dois caminhos, decididos por PROVA e não por pergunta:
#
#   • quem já tem o `ia-chat` no disco  ->  instala SÓ o app;
#   • quem chegou por aqui              ->  leva o pacote completo: clona o repo
#                                           original, roda o `install.sh` dele
#                                           (CLI + skills + sala) e depois o app.
#
# Variáveis:
#   IA_CHAT_REPO   URL do repo original (default: o irmão do remoto deste repo)
#   IA_CHAT_SRC    onde clonar/procurar o original (default: ~/Projetos/ia-chat)
#   IA_CHAT_DEST   onde instalar o .app (default: /Applications, senão ~/Applications)
set -euo pipefail
RAIZ="$(cd "$(dirname "$0")" && pwd)"
APP="$RAIZ/ia-chat.app"
SRC="${IA_CHAT_SRC:-$HOME/Projetos/ia-chat}"

[ -d "$APP" ] || { echo "✗ não achei $APP — rode este script de dentro do repo"; exit 1; }

# ── 1. o original já está no disco? ──────────────────────────────────────────
# A prova é o arquivo que o app realmente precisa importar, não a existência de
# uma pasta com o nome certo. Pasta vazia clonada pela metade também tem nome.
achar_core() {
  for d in "$SRC/bin" "${IACHAT_SCRIPTS:-$HOME/.claude/scripts/ia-chat}"; do
    [ -f "$d/iachat_core.py" ] && { echo "$d"; return 0; }
  done
  return 1
}

if CORE="$(achar_core)"; then
  echo "• ia-chat já instalado  ($CORE)  →  instalo só o app"
else
  echo "• ia-chat não encontrado  →  levo o pacote completo"
  URL="${IA_CHAT_REPO:-}"
  if [ -z "$URL" ]; then
    # o irmão deste repo: .../ia-chat-app(.git) -> .../ia-chat(.git)
    ORIGEM="$(git -C "$RAIZ" remote get-url origin 2>/dev/null || true)"
    [ -n "$ORIGEM" ] && URL="$(printf '%s' "$ORIGEM" | sed 's#ia-chat-app#ia-chat#')"
  fi
  if [ -z "$URL" ]; then
    cat >&2 <<'FIM'
✗ não sei de onde clonar o ia-chat: este repo não tem remoto configurado.
  Informe a origem e rode de novo:

      IA_CHAT_REPO=https://…/ia-chat.git ./instalar-app.sh
FIM
    exit 1
  fi
  echo "  git clone $URL  →  $SRC"
  mkdir -p "$(dirname "$SRC")"
  git clone --depth 1 "$URL" "$SRC"
  echo "  $SRC/install.sh"
  bash "$SRC/install.sh"
  CORE="$(achar_core)" || { echo "✗ clonei mas não achei o iachat_core.py"; exit 1; }
fi

# ── 2. o app ─────────────────────────────────────────────────────────────────
bash "$RAIZ/montar.sh"          # ícone e interface entram no bundle antes de copiar

if [ -n "${IA_CHAT_DEST:-}" ]; then DEST="$IA_CHAT_DEST"
elif [ -w /Applications ]; then DEST="/Applications"
else DEST="$HOME/Applications"; fi
# `mkdir -p` para os TRÊS caminhos, não só para o fallback.
#
# Achado de 18/08, auditando a instalação numa máquina que nunca teve o repositório:
# com `IA_CHAT_DEST` apontando para um diretório que ainda não existe, o `cp` falhava
# com "No such file or directory" — e o script seguia até o fim imprimindo os ✔, porque
# o erro do `cp` não derrubava a execução. Quem usa a variável é justamente quem instala
# fora do padrão: outro disco, pasta de testes, máquina compartilhada.
mkdir -p "$DEST"

ALVO="$DEST/ia-chat.app"
[ -d "$ALVO" ] && rm -rf "$ALVO"
# Sem `|| exit`, uma cópia que falha deixa o script anunciar sucesso sobre nada.
cp -R "$APP" "$ALVO" || { echo "✗ não consegui copiar o app para $ALVO" >&2; exit 1; }
chmod +x "$ALVO/Contents/MacOS/ia-chat"

# Baixado como .zip, o app chega com quarentena e o Gatekeeper trava o duplo
# clique num app sem assinatura. Este repo é código-fonte aberto que o dono
# acabou de ler: tirar a quarentena aqui é o que faz "dois cliques" ser verdade.
xattr -dr com.apple.quarantine "$ALVO" 2>/dev/null || true
touch "$ALVO"

LSREG=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister
[ -x "$LSREG" ] && "$LSREG" -f "$ALVO" >/dev/null 2>&1 || true

echo
echo "✔ app      $ALVO"
echo "✔ núcleo   $CORE"
echo "✔ sala     ${IACHAT_HOME:-$HOME/ia-chat-global}"
echo
echo "Abra pelo Launchpad, pelo Finder ou:  open -a ia-chat"

# ── 3. o aviso que evita o primeiro susto ────────────────────────────────────
# O app abre a sala em modo escrita como `bauer`. Quem não está em `na_sala` tem
# o post recusado pelo núcleo — melhor dizer agora do que descobrir no botão.
PAPEL="${IACHAT_PAPEL:-bauer}"
CFG="${IACHAT_HOME:-$HOME/ia-chat-global}/config.json"
if [ -f "$CFG" ] && ! grep -q "\"$PAPEL\"" "$CFG"; then
  echo
  echo "⚠  '$PAPEL' não está em na_sala ($CFG)."
  echo "   Ler funciona; enviar vai voltar recusado até você entrar na sala."
  echo "   Antes de entrar, saiba que isso muda quem o @all chama."
fi
