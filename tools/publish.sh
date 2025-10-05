#!/usr/bin/env bash
set -euo pipefail
MSG="${1:-chore: update}"
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo .)"
cd "$ROOT"

# Format/Lint se disponibili
if command -v ruff >/dev/null 2>&1; then
  ruff format || true
  ruff check --fix || true
fi

# Smoketest UI (genera l’asset se manca)
if [ -f tools/ui_smoketest_audio.py ]; then
  if [ ! -f tests/assets/mono.wav ]; then
    mkdir -p tests/assets
    ffmpeg -hide_banner -loglevel error -y \
      -f lavfi -i sine=frequency=440:duration=5 \
      -c:a pcm_s16le tests/assets/mono.wav || true
  fi
  # se hai X installata, va bene anche senza xvfb; con CI usa xvfb-run
  python3 tools/ui_smoketest_audio.py tests/assets/mono.wav --sb51
fi

git add -A
# Niente da committare? esci pulito
git diff --cached --quiet && { echo "✓ Nessuna modifica da committare"; exit 0; }

git commit -m "$MSG"
git push -u origin "$(git branch --show-current)"
echo "✓ Push OK"
