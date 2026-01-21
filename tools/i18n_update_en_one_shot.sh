#!/usr/bin/env bash
set -euo pipefail
cd /mnt/Storage/Hevc_gui

TS="hevc_gui/resources/i18n/hevc_en.ts"
QM="hevc_gui/resources/i18n/hevc_en.qm"

ts="$(date +%Y%m%d_%H%M%S)"
mkdir -p /mnt/Storage/Hevc_gui/tools/_i18n_bak
cp -a "$TS" "/mnt/Storage/Hevc_gui/tools/_i18n_bak/hevc_en.ts.$ts.bak" || true
cp -a "$QM" "/mnt/Storage/Hevc_gui/tools/_i18n_bak/hevc_en.qm.$ts.bak" || true

# Prendiamo tutto il codice "vero" (escludiamo cache, build, backup, ecc.)
mapfile -d '' files < <(
  find hevc_gui scripts -type f \( -name '*.py' -o -name '*.ui' -o -name '*.qrc' \) \
    -not -path '*/__pycache__/*' \
    -not -path '*/.git/*' \
    -not -path '*/build/*' \
    -not -path '*/dist/*' \
    -not -path '*/tools/_i18n_bak/*' \
    -not -path '*/backup*/*' \
    -print0
)

echo "[i18n] files to scan: ${#files[@]}"
echo "[i18n] updating TS with pylupdate5 (-tr-function L)..."
pylupdate5 -verbose -tr-function L "${files[@]}" -ts "$TS"

# Compila QM
if command -v lrelease >/dev/null 2>&1; then
  lrelease "$TS" -qm "$QM"
elif command -v lrelease-qt5 >/dev/null 2>&1; then
  lrelease-qt5 "$TS" -qm "$QM"
else
  echo "ERROR: lrelease non trovato (installa qttools5-dev-tools o equivalente)."
  exit 2
fi

echo "[i18n] DONE."
ls -l "$TS" "$QM"
