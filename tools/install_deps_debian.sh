#!/usr/bin/env bash
set -euo pipefail

# Installa le dipendenze di runtime su Debian/Ubuntu/Mint
# Uso:
#   tools/install_deps_debian.sh

need_sudo() { [ "${EUID:-$(id -u)}" -ne 0 ]; }

PKGS_MIN=(
  python3
  python3-pyqt5
  python3-pyqt5.qtmultimedia
  python3-pyqtgraph
  python3-numpy
  python3-psutil
  python3-chardet
  ffmpeg
)

PKGS_RECO=(
  gnome-terminal
  cpulimit
)

echo "== Aggiorno indici APT…"
if need_sudo; then sudo apt update; else apt update; fi

echo "== Installo pacchetti minimi…"
if need_sudo; then sudo apt install -y "${PKGS_MIN[@]}"; else apt install -y "${PKGS_MIN[@]}"; fi

echo "== (Opzionale) Strumenti consigliati…"
if need_sudo; then sudo apt install -y "${PKGS_RECO[@]}"; else apt install -y "${PKGS_RECO[@]}"; fi

echo "✔ Dipendenze installate."
