#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C.UTF-8

ROOT="${1:-.}"
cd "$ROOT"

# Assicurati che git esista
if [ ! -d .git ]; then
  ./tools/init-git.sh .
fi

# Crea branch dedicato (con secondi per evitare collisioni entro il minuto)
STAMP="$(date +%Y%m%d-%H%M%S)"
BASE="chore/ruff-clean-$STAMP"
BR="$BASE"

# Se (comunque) esiste, aggiungi suffisso -2, -3, ...
i=2
while git rev-parse --verify --quiet "$BR" >/dev/null; do
  BR="$BASE-$i"
  i=$((i+1))
done

# switch (compatibile)
if git switch -c "$BR" >/dev/null 2>&1; then
  :
else
  git checkout -b "$BR"
fi

# Esegui ruff (apply)
if [ -x ./tools/ruff-clean.sh ]; then
  ./tools/ruff-clean.sh --apply
else
  echo "tools/ruff-clean.sh non trovato o non eseguibile." >&2
  exit 1
fi

# Commit
git add -A
git commit -m "chore: ruff clean"

echo
echo "✔ Fatto sul branch: $BR"
echo "→ Controlla con:    git show --stat"
echo "→ Quando ok:         git push -u origin $BR"

