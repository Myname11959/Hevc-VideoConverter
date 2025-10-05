#!/usr/bin/env bash
set -euo pipefail
# ASCII puro: niente 'tree', niente sequenze ESC.
# Uso: bash tools/repo-tree.sh [ROOT=. ] [DEPTH=5] [--out FILE]

ROOT="${1:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
DEPTH="${2:-5}"
OUT=""

# opzionale --out FILE
if [[ "${3:-}" == "--out" ]]; then OUT="${4:-}"; fi
if [[ "${2:-}" == "--out" ]]; then OUT="${3:-}"; fi

# filtri esclusioni
EXC_DIRS=( ".git" ".ruff_cache" "__pycache__" ".mypy_cache" ".pytest_cache"
           ".venv" "venv" "build" "dist" "tmp" "temp" "out" "node_modules"
           ".idea" ".vscode" "packaging" "_backup" "_export" )
PRUNE=()
for d in "${EXC_DIRS[@]}"; do PRUNE+=( -name "$d" -prune -o ); done

TMP="$(mktemp)"
LC_ALL=C find "$ROOT" -mindepth 1 -maxdepth "$DEPTH" \
  \( "${PRUNE[@]}" -false \) -o -print \
| LC_ALL=C sed "s|^$ROOT/||; s|^\./||" \
| LC_ALL=C awk -F'/' '{
    depth=NF-1; pad="";
    for(i=0;i<depth;i++) pad=pad "  ";
    print pad $NF
  }' > "$TMP"

if [[ -n "$OUT" ]]; then
  mv "$TMP" "$OUT"; echo "Scritto in: $OUT"
else
  cat "$TMP"; rm -f "$TMP"
fi
