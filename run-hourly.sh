#!/bin/bash
# Radar de Virais — job de hora em hora (recolhe + publica no GitHub Pages).
# Uso: run-hourly.sh [slug]   (default: marcelo)
# Chamado pelo launchd (Mac) ou por cron (VPS). PATH explicito pq launchd nao herda o shell.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
SLUG="${1:-marcelo}"
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$HOME/Library/Logs/radar-virais-${SLUG}.log"
cd "$DIR" || exit 1

echo "===== $(date '+%Y-%m-%d %H:%M:%S') :: coletar $SLUG =====" >> "$LOG"
/usr/bin/python3 coletar_virais.py --cliente "$SLUG" --max-videos 18 >> "$LOG" 2>&1

git add -A >> "$LOG" 2>&1
if git diff --cached --quiet; then
  echo "nada novo pra publicar" >> "$LOG"
  exit 0
fi
git -c user.name="MediaGrowth Deploy" -c user.email="mediagrowthmkt@gmail.com" \
  commit -q -m "radar de virais: atualiza seed $SLUG ($(date '+%F %H:%M'))" >> "$LOG" 2>&1

TOKEN="$(gh auth token 2>/dev/null)"
if [ -n "$TOKEN" ]; then
  git push "https://x-access-token:${TOKEN}@github.com/mediagrowthmkt-debug/radar-virais.git" main >> "$LOG" 2>&1
else
  git push origin main >> "$LOG" 2>&1
fi
echo "publicado." >> "$LOG"
