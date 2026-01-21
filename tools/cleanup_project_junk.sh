#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

DO="${DO:-0}"   # DO=1 => cancella
say() { echo -e "[clean] $*"; }

# roba sicura da buttare (backup, copie, cache, log)
# NOTA: volutamente NON tocchiamo pkg/, DEBIAN/, resources/icons/, ecc.
patterns=(
  -name "__pycache__" -o
  -name "*.pyc" -o
  -name "*.pyo" -o
  -name ".pytest_cache" -o
  -name ".ruff_cache" -o
  -name ".mypy_cache" -o
  -name "*.bak" -o
  -name "*.bak_*" -o
  -name "*.BAK_*" -o
  -name "* (copia).old" -o
  -name "*.tmp_SAFE_*" -o
  -name "*.tmp" -o
  -name "*.log" -o
  -name "gui_debug.log"
)

say "repo: $(pwd)"
say "mode: $( [ "$DO" = "1" ] && echo DELETE || echo DRY-RUN )"

# 1) trova candidati
say "scanning..."
mapfile -t items < <(
  find . \
    -path "./.git" -prune -o \
    -path "./pkg" -prune -o \
    \( "${patterns[@]}" \) -print
)

say "items: ${#items[@]}"
if [ "${#items[@]}" -eq 0 ]; then
  say "niente da fare."
  exit 0
fi

# 2) stampa lista
printf "%s\n" "${items[@]}" | sed 's|^\./||' | sort

# 3) cancella
if [ "$DO" = "1" ]; then
  say "deleting..."
  # cancelliamo in modo robusto (dir + file)
  while IFS= read -r p; do
    rm -rf -- "$p"
  done < <(printf "%s\n" "${items[@]}")
  say "OK: deleted ${#items[@]} paths"
else
  say "DRY-RUN: per cancellare davvero -> DO=1 bash tools/cleanup_project_junk.sh"
fi
