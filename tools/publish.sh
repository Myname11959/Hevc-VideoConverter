#!/usr/bin/env bash
set -euo pipefail

MSG="${1:-chore: update}"
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo .)"
cd "$ROOT"

# ───────────────────────── Format/Lint (se presenti) ─────────────────────────
if command -v ruff >/dev/null 2>&1; then
  ruff format || true
  ruff check --fix || true
fi

# ─────────────────────── Smoketest UI (opzionale) ────────────────────────────
# Genera un asset di test minimo se serve (mono.wav)
if [ -f tools/ui_smoketest_audio.py ]; then
  if [ ! -f tests/assets/mono.wav ]; then
    mkdir -p tests/assets
    if command -v ffmpeg >/dev/null 2>&1; then
      ffmpeg -hide_banner -loglevel error -y \
        -f lavfi -i sine=frequency=440:duration=5 \
        -c:a pcm_s16le tests/assets/mono.wav || true
    fi
  fi
  # con X disponibile va bene così; su CI puoi usare xvfb-run
  if command -v python3 >/dev/null 2>&1; then
    python3 tools/ui_smoketest_audio.py tests/assets/mono.wav --sb51 || true
  fi
fi

# ─────────────────────── Mantieni cartella tests/assets ──────────────────────
mkdir -p tests/assets
[ -f tests/assets/.gitkeep ] || touch tests/assets/.gitkeep

# ─────────────── Toglie dal tracking i file ora ignorati (una tantum) ────────
# Esempi: log, asset generati, cache, ecc. (dipende dal tuo .gitignore)
git ls-files -z -i --exclude-from=.gitignore | xargs -0 -r git rm --cached || true

# ─────────────────────────── Commit & Push puliti ────────────────────────────
git add -A

# Niente da committare? esci pulito
if git diff --cached --quiet; then
  echo "✓ Nessuna modifica da committare"
  exit 0
fi

git commit -m "$MSG"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
git push -u origin "$BRANCH"

echo "✓ Push OK"

