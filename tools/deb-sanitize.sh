#!/usr/bin/env bash
set -euo pipefail

# deb-sanitize.sh — “ripulisce” la root da artefatti .deb/build e doppioni.
# Uso:
#   ./tools/deb-sanitize.sh                 # DRY-RUN
#   ./tools/deb-sanitize.sh --apply         # sposta in packaging/deb-archive/<ts>/
#   ./tools/deb-sanitize.sh --apply --mode trash
#   ./tools/deb-sanitize.sh --apply --mode delete

MODE="move"   # move | trash | delete
APPLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) APPLY=1; shift ;;
    --mode) MODE="${2:-move}"; shift 2 ;;
    *) echo "Argomento sconosciuto: $1" >&2; exit 2;;
  esac
done

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"

timestamp() { date +%Y%m%d-%H%M%S; }

DEST=""
case "$MODE" in
  move)   DEST="packaging/deb-archive/$(timestamp)";;
  trash)  DEST=".trash/$(timestamp)";;
  delete) DEST="";;
  *) echo "MODE non valido: $MODE (usa move|trash|delete)"; exit 2;;
esac

# Attiva glob, evita errore su pattern senza match
shopt -s nullglob dotglob

TARGETS=(
  "_backup"
  "_export"
  "hevc-gui_*"                 # cartelle staging / .deb
  "hevc_queue_core_bundle.tgz"
  "build-deb.sh"
  "build.log"
  "uninstall.sh"
  "repo-tree.txt"
  "hevc_tree.txt"

  # Doppioni con spazi nel nome:
  "hevc_gui/core/constants (copia).py"
  "hevc_gui/core/helpers (copia).py"
  "hevc_gui/gui/main_window (copia).py"

  # File “_” duplicati puntuali (se presenti in root)
  "icon_helper_.py"
  "oscilloscope_preview_.py"
)

# Espansione robusta dei glob, preservando gli spazi:
EXPANDED=()
OLDIFS="$IFS"; IFS=$'\n'
for pat in "${TARGETS[@]}"; do
  # espandi pattern → array temporaneo
  matches=( $pat )
  for hit in "${matches[@]}"; do
    [[ -e "$hit" ]] && EXPANDED+=("$hit")
  done
done
IFS="$OLDIFS"

if [[ ${#EXPANDED[@]} -eq 0 ]]; then
  echo "Niente da pulire. (Nessun target presente)"
  exit 0
fi

echo "Bersagli trovati:"
for p in "${EXPANDED[@]}"; do echo "  - $p"; done
echo

if [[ $APPLY -ne 1 ]]; then
  echo "DRY-RUN: nessuna modifica effettuata. Usa --apply per procedere."
  exit 0
fi

if [[ "$MODE" == "delete" ]]; then
  echo "ATTENZIONE: modalità DELETE. Elimino definitivamente i bersagli."
  read -r -p "Confermi? [yes/NO] " yn
  [[ "$yn" == "yes" ]] || { echo "Annullato."; exit 1; }
  for p in "${EXPANDED[@]}"; do
    rm -rf -- "$p"
    echo "deleted: $p"
  done
  exit 0
fi

# move / trash
mkdir -p -- "$DEST"
for p in "${EXPANDED[@]}"; do
  mv -v -- "$p" "$DEST"/
done

echo
echo "✔ Spostati in: $DEST"
echo "Suggerimento: controlla e poi commit:"
echo "  git add -A && git commit -m 'chore: move packaging artifacts to $DEST'"

