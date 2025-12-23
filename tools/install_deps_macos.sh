#!/usr/bin/env bash
set -euo pipefail

# Dipendenze Python via pip (PyQt5 va benissimo su macOS)
PY_PKGS=("PyQt5" "pyqtgraph" "numpy" "psutil" "chardet")

echo "== Aggiorno pip =="
python3 -m pip install --upgrade pip wheel setuptools

echo "== Installo pacchetti Python =="
python3 -m pip install "${PY_PKGS[@]}"

# FFmpeg via Homebrew (se disponibile), altrimenti avviso
if command -v brew >/dev/null 2>&1; then
  echo "== Installo ffmpeg con Homebrew =="
  brew install ffmpeg || true
else
  echo "== ATTENZIONE =="
  echo "Non ho trovato Homebrew; installa FFmpeg manualmente:"
  echo "  - scarica un pacchetto statico (evermeet.cx o osxexperts.net) e metti ffmpeg/ffprobe/ffplay nel PATH"
fi

echo "== Test rapido =="
python3 -c "import PyQt5, pyqtgraph, numpy, psutil, chardet; print('OK deps macOS')"
echo "✔ Dipendenze macOS pronte. Avvia con: python3 main.py"

