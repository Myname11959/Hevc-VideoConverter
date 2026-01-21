#!/usr/bin/env bash
set -euo pipefail

cd /mnt/Storage/Hevc_gui

MODE="${1:-dry}"   # dry | apply
ts="$(date +%Y%m%d_%H%M%S)"
ATTIC="backup/_ATTIC_repo_cleanup_${ts}"
mkdir -p "$ATTIC"

echo "== Repo: $(pwd)"
echo "== Mode: $MODE"
echo "== Attic: $ATTIC"
echo

# --- 1) Directory intere da spostare (archivi/trash) ---
mapfile -t JUNK_DIRS < <(
  find . -type d \( \
    -name "_ARCHIVE_*" -o \
    -name "_TRASH_*" -o \
    -path "./hevc_gui/resources/i18n/_backup_ts_*" -o \
    -path "./hevc_gui/resources/i18n/_old_extra_ts" \
  \) -print
)

# --- 2) File singoli da spostare ---
mapfile -t JUNK_FILES < <(
  find . -type f \( \
    -name "*.bak*" -o \
    -name "*.BAK*" -o \
    -name "*.BROKEN*" -o \
    -name "*~" -o \
    -name "*.swp" -o \
    -name "*.orig" -o \
    -name "*.rej" -o \
    -name ".DS_Store" -o \
    -path "./hevc_gui/dvd_ripper.tar.gz" \
  \) -print
)

# --- Filtri di sicurezza: NON toccare i file canonici i18n ---
# (sposterà i bak, ma non i principali)
KEEP_REGEX='^./hevc_gui/resources/i18n/(hevc_en\.ts|hevc_en\.qm|hevc_it\.ts|hevc_it\.qm)$'

filtered_files=()
for f in "${JUNK_FILES[@]}"; do
  if [[ "$f" =~ $KEEP_REGEX ]]; then
    continue
  fi
  filtered_files+=("$f")
done

echo "== Candidate dirs : ${#JUNK_DIRS[@]}"
echo "== Candidate files: ${#filtered_files[@]}"
echo

report="$ATTIC/_cleanup_report.txt"
{
  echo "MODE=$MODE"
  echo "ATTIC=$ATTIC"
  echo
  echo "[DIRS]"
  printf '%s\n' "${JUNK_DIRS[@]}"
  echo
  echo "[FILES]"
  printf '%s\n' "${filtered_files[@]}"
} > "$report"

echo "Report scritto in: $report"
echo

move_one() {
  local path="$1"
  local dest="$ATTIC/${path#./}"
  mkdir -p "$(dirname "$dest")"
  if git ls-files --error-unmatch "$path" >/dev/null 2>&1; then
    # se per caso è tracciato, lo rimuoviamo dal repo ma lo salviamo in attic
    cp -a -- "$path" "$dest"
    git rm -f --quiet -- "$path"
    echo "git rm  + saved -> $path"
  else
    mv -- "$path" "$dest"
    echo "mv -> $path"
  fi
}

if [[ "$MODE" == "dry" ]]; then
  echo "DRY-RUN: niente viene spostato."
  echo "Per applicare:  bash tools/cleanup_repo_attic_safe.sh apply"
  exit 0
fi

echo "== Sposto directory (dal più profondo per evitare incastri)"
# ordina per profondità (più slash prima)
IFS=$'\n' JUNK_DIRS_SORTED=($(printf '%s\n' "${JUNK_DIRS[@]}" | awk '{print gsub(/\//,"/"), $0}' | sort -rn | cut -d' ' -f2-))
unset IFS

for d in "${JUNK_DIRS_SORTED[@]}"; do
  # se già spostata da una dir padre, skip
  [[ -e "$d" ]] || continue
  move_one "$d"
done

echo
echo "== Sposto file"
for f in "${filtered_files[@]}"; do
  [[ -e "$f" ]] || continue
  move_one "$f"
done

echo
echo "Fatto. Controlla git status e poi fai i test."

