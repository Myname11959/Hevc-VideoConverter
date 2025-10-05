#!/usr/bin/env bash
set -euo pipefail
# ruff-clean.sh — format + lint “sicuri” con Ruff, senza toccare encoding.
# Uso:
#   ./tools/ruff-clean.sh            # dry-run (mostra diff)
#   ./tools/ruff-clean.sh --apply    # applica modifiche
# Opzioni:
#   --path DIR     directory target (default: .)
#   --select CODE  limitare a regole (ripetibile)
#   --ignore CODE  ignorare regole (ripetibile)

APPLY=0
TARGET="."
SELECT=()
IGNORE=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) APPLY=1; shift ;;
    --path) TARGET="${2:-.}"; shift 2 ;;
    --select) SELECT+=("$2"); shift 2 ;;
    --ignore) IGNORE+=("$2"); shift 2 ;;
    *) echo "Argomento sconosciuto: $1" >&2; exit 2;;
  esac
done

# Preferisci C.UTF-8 per evitare “caratteri di merda” in output di terminale
export LC_ALL=C.UTF-8

# Esclusioni standard (Ruff rispetta pyproject, ma qui aggiungiamo sicurezza)
EXCLUDES=".git,__pycache__,.ruff_cache,.mypy_cache,.pytest_cache,build,dist,venv,.venv,node_modules,packaging"

# Trova ruff (pipx/venv/system)
if command -v ruff >/dev/null 2>&1; then
  RUFF="ruff"
else
  # Tentativo via python -m
  if python - <<<'import ruff' >/dev/null 2>&1; then
    RUFF="python -m ruff"
  else
    echo "Ruff non trovato. Installa con:  pipx install ruff  (consigliato)" >&2
    exit 1
  fi
fi

SEL_FLAGS=()
for s in "${SELECT[@]}"; do SEL_FLAGS+=( "--select" "$s" ); done
IGN_FLAGS=()
for i in "${IGNORE[@]}"; do IGN_FLAGS+=( "--ignore" "$i" ); done

echo ">> Target: $TARGET"
echo ">> Exclude: $EXCLUDES"
echo ">> Mode   : $([[ $APPLY -eq 1 ]] && echo APPLY || echo DRY-RUN)"

if [[ $APPLY -eq 1 ]]; then
  # 1) Format (idempotente, non cambia encoding)
  $RUFF format "$TARGET" --exclude "$EXCLUDES" "${SEL_FLAGS[@]}" "${IGN_FLAGS[@]}"
  # 2) Lint + fix
  $RUFF check  "$TARGET" --fix --exclude "$EXCLUDES" "${SEL_FLAGS[@]}" "${IGN_FLAGS[@]}"
else
  # Dry-run: mostra cosa farebbe (senza toccare i file)
  $RUFF format "$TARGET" --exclude "$EXCLUDES" --diff "${SEL_FLAGS[@]}" "${IGN_FLAGS[@]}"
  echo
  $RUFF check  "$TARGET" --fix --exclude "$EXCLUDES" --diff "${SEL_FLAGS[@]}" "${IGN_FLAGS[@]}"
fi

echo
echo ">> Fatto. Suggerimento: controlla 'git status' prima di fare commit."

