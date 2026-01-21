#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

APPLY="${APPLY:-0}"

# usa cestino se disponibile, altrimenti rm -rf
trash_or_rm() {
  local p="$1"
  if command -v gio >/dev/null 2>&1; then
    gio trash -- "$p" 2>/dev/null || rm -rf -- "$p"
  else
    rm -rf -- "$p"
  fi
}

# prende SOLO untracked (??) da git
mapfile -d '' UNTRACKED < <(git status --porcelain=v1 -z | awk -v RS='\0' '$0 ~ /^\?\? / {print substr($0,4) "\0"}')

want_delete() {
  local p="$1"
  local b="${p##*/}"

  # cache python
  [[ "$b" == "__pycache__" ]] && return 0
  [[ "$p" == */__pycache__/* ]] && return 0
  [[ "$b" == *.pyc || "$b" == *.pyo || "$b" == *.pyd ]] && return 0

  # log / core / temp
  [[ "$b" == *.log || "$b" == *.core || "$b" == core || "$b" == core.* ]] && return 0
  [[ "$b" == *.tmp || "$b" == *.swp || "$b" == *.swo ]] && return 0

  # backup vari
  [[ "$b" == *.bak* ]] && return 0
  [[ "$b" == *".bak_"* ]] && return 0

  # copie “(copia …)” / “un'altra copia”
  [[ "$b" == *" (copia"* ]] && return 0
  [[ "$b" == *"un'altra copia"* ]] && return 0

  # pro/ts temporanei generati dai codemod (se untracked)
  [[ "$p" == tools/i18n_full_*.pro ]] && return 0
  [[ "$p" == i18n_full_*.pro ]] && return 0

  return 1
}

DEL=()
for p in "${UNTRACKED[@]}"; do
  [[ -z "$p" ]] && continue
  # niente roba dentro /backup/ (quella è volutamente un archivio)
  [[ "$p" == backup/* ]] && continue
  if want_delete "$p"; then
    DEL+=("$p")
  fi
done

echo "== cleanup_untracked =="
echo "Repo: $(pwd)"
echo "Candidati alla rimozione (untracked): ${#DEL[@]}"
printf '%s\n' "${DEL[@]}"

if [[ "${APPLY}" != "1" ]]; then
  echo
  echo "DRY-RUN: nessun file rimosso."
  echo "Se l'elenco ti va bene:  APPLY=1 bash tools/cleanup_untracked.sh"
  exit 0
fi

echo
echo "== APPLY=1: rimozione in corso =="
for p in "${DEL[@]}"; do
  trash_or_rm "$p"
done
echo "Fatto."
