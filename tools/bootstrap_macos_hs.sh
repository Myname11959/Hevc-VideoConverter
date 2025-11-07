#!/usr/bin/env bash
set -euo pipefail

echo "== HEVC-GUI — bootstrap per macOS High Sierra (10.13) =="

# 1) Python 3.8 consigliato su HS
PY_OK=0
if command -v python3 >/dev/null 2>&1; then
  PYV=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')
  echo "Trovato Python3: $PYV"
  # accettiamo 3.8/3.9; 3.10+ su HS può dare rogne di ruote
  MAJ=$(python3 -c 'import sys; print(sys.version_info[0])')
  MIN=$(python3 -c 'import sys; print(sys.version_info[1])')
  if [[ "$MAJ" -eq 3 && ( "$MIN" -eq 8 || "$MIN" -eq 9 ) ]]; then
    PY_OK=1
  fi
fi

if [[ "$PY_OK" -ne 1 ]]; then
  cat <<EOF
[AVVISO] Su High Sierra è raccomandato Python 3.8 (ok anche 3.9).
Scarica l’installer ufficiale (macOS 10.9+), installalo e riapri il terminale:
  https://www.python.org/downloads/release/python-3810/
EOF
  exit 1
fi

# 2) Aggiorna pip/setuptools/wheel
python3 -m pip install -U pip setuptools wheel

# 3) Installa dipendenze pinned
REQ_FILE="requirements_macos_hs.txt"
[[ -f "$REQ_FILE" ]] || { echo "Manca $REQ_FILE"; exit 1; }

echo "== Installo dipendenze Python =="
python3 -m pip install -r "$REQ_FILE"

# 4) Check binari di sistema minimi (ffmpeg)
need_ffmpeg=0
for b in ffmpeg ffprobe ffplay; do
  if ! command -v "$b" >/dev/null 2>&1; then
    need_ffmpeg=1
  fi
done

if [[ "$need_ffmpeg" -eq 1 ]]; then
  cat <<'EOF'
[INFO] Non trovo ffmpeg/ffprobe/ffplay nel PATH.
Esegui:  tools/install_ffmpeg_macos_hs.sh
(o installa ffmpeg con un tuo metodo).
EOF
else
  echo "== ffmpeg già presente, ok."
fi

echo "== Bootstrap completato. Avvio di prova =="
python3 main.py || true
