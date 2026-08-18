#!/bin/bash
# ia-chat-app — sincroniza o bundle com as fontes do repo.
#
# O `.app` é versionado montado (quem baixa não deve precisar de `iconutil` nem
# de passo extra), mas ícone e interface têm dono em outro lugar do repo. Este
# script é o único ponto onde os dois entram no bundle — rode depois de mexer
# em `marca/` ou em `ui/`.
set -euo pipefail
RAIZ="$(cd "$(dirname "$0")" && pwd)"
RES="$RAIZ/ia-chat.app/Contents/Resources"

[ -d "$RES" ] || { echo "✗ bundle ausente em $RAIZ/ia-chat.app"; exit 1; }

if [ -f "$RAIZ/marca/icone.icns" ]; then
  cp "$RAIZ/marca/icone.icns" "$RES/icone.icns"
  echo "• ícone      marca/icone.icns"
fi

if [ -f "$RAIZ/ui/index.html" ]; then
  mkdir -p "$RES/ui"
  # Só os arquivos que a interface serve. `rsync --delete` cairia em cima de
  # qualquer coisa que aparecesse ali — este cp não apaga nada que não seja meu.
  for f in index.html estilo.css sala.js servir.py; do
    [ -f "$RAIZ/ui/$f" ] && cp "$RAIZ/ui/$f" "$RES/ui/$f"
  done
  echo "• interface  ui/ ($(ls "$RES/ui" | wc -l | tr -d ' ') arquivos)"
fi

chmod +x "$RAIZ/ia-chat.app/Contents/MacOS/ia-chat"
touch "$RAIZ/ia-chat.app"
echo "✔ bundle montado"
