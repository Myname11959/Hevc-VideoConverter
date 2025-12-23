#!/usr/bin/env bash
set -euo pipefail

# ───────────────────────── repo paths ─────────────────────────
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PKGDIR="$ROOT/pkg"
DIST="$ROOT/dist"
CONTROL="$PKGDIR/DEBIAN/control"
VER_FILE="$ROOT/hevc_gui/VERSION"

# ───────────────────────── sanity ─────────────────────────
[[ -f "$VER_FILE" ]] || { echo "ERRORE: mancante $VER_FILE" >&2; exit 1; }
[[ -f "$CONTROL"  ]] || { echo "ERRORE: mancante $CONTROL"  >&2; exit 1; }

# ───────────────────────── versioni ─────────────────────────
# Versione base (upstream) dal file, o override con RELEASE_VERSION
BASE_VER="${RELEASE_VERSION:-$(tr -d ' \r\n' < "$VER_FILE")}"

# Leggi l'attuale Version dal control *prima* di modificarlo (per auto-bump)
ORIG_CTRL_VER="$(sed -n 's/^Version: //p' "$CONTROL" | head -n1 || true)"
ORIG_BASE=""; ORIG_REV=""

if [[ -n "$ORIG_CTRL_VER" ]]; then
  if [[ "$ORIG_CTRL_VER" == *-* ]]; then
    ORIG_BASE="${ORIG_CTRL_VER%-*}"
    ORIG_REV="${ORIG_CTRL_VER##*-}"
  else
    ORIG_BASE="$ORIG_CTRL_VER"
    ORIG_REV=""
  fi
fi

# Calcolo della Debian revision:
# - Se PKG_REVISION è impostata dall'utente, usa quella.
# - Altrimenti, se il control aveva già la stessa BASE_VER e una rev numerica → incrementa.
# - Altrimenti parti da 1.
if [[ -n "${PKG_REVISION:-}" ]]; then
  PKG_REV="$PKG_REVISION"
elif [[ -n "$ORIG_REV" && "$ORIG_BASE" == "$BASE_VER" && "$ORIG_REV" =~ ^[0-9]+$ ]]; then
  PKG_REV="$(( ORIG_REV + 1 ))"
else
  PKG_REV="1"
fi

DEB_VER="${BASE_VER}-${PKG_REV}"

# Scrivi la nuova Version nel control
sed -i -E "s/^Version: .*/Version: ${DEB_VER}/" "$CONTROL"

# ───────────────────────── campi control ─────────────────────────
PKG_NAME="$(sed -n 's/^Package: //p' "$CONTROL" | head -n1)"
ARCH="$(sed -n 's/^Architecture: //p' "$CONTROL" | head -n1)"
: "${PKG_NAME:?ERRORE: campo Package: mancante in control}"
: "${ARCH:=all}"

# ───────────────────────── sanity file installati ─────────────────────────
# wrapper e main presenti?
if [[ ! -x "$PKGDIR/usr/bin/hevc-video-converter" ]]; then
  # prova a sistemare permessi se esiste
  if [[ -f "$PKGDIR/usr/bin/hevc-video-converter" ]]; then
    chmod 0755 "$PKGDIR/usr/bin/hevc-video-converter"
  else
    echo "ERRORE: manca $PKGDIR/usr/bin/hevc-video-converter" >&2
    exit 1
  fi
fi

if [[ ! -f "$PKGDIR/usr/lib/hevc-video-converter/main.py" ]]; then
  echo "ERRORE: manca $PKGDIR/usr/lib/hevc-video-converter/main.py" >&2
  exit 1
fi

# ───────────────────────── sync sorgenti nello staging pkg ─────────────────────────
STAGE="$PKGDIR/usr/lib/hevc-video-converter"
mkdir -p "$STAGE"

# copia TUTTA la cartella hevc_gui (include gui/, crop dialog, ecc.)
rsync -a --delete "$ROOT/hevc_gui/" "$STAGE/hevc_gui/"

# copia la cartella scripts (serve string_audio_generator.py & co.)
if [[ -d "$ROOT/scripts" ]]; then
  rsync -a --delete "$ROOT/scripts/" "$STAGE/scripts/"
fi

# main.py (entrypoint usato dal wrapper /usr/bin/hevc-video-converter)
if [[ -f "$ROOT/main.py" ]]; then
  install -m 0644 "$ROOT/main.py" "$STAGE/main.py"
fi

# ───────────────────────── build ─────────────────────────
rm -rf "$DIST"
mkdir -p "$DIST"
OUT="$DIST/${PKG_NAME}_${DEB_VER}_${ARCH}.deb"

echo "== Hevc – Video Converter =="
echo "Upstream:   $BASE_VER"
echo "Debian rev: $PKG_REV  → Version: $DEB_VER"
echo "Pacchetto:  $PKG_NAME  Arch: $ARCH"
echo "Output:     $OUT"
echo

dpkg-deb --build --root-owner-group "$PKGDIR" "$OUT"

# ───────────────────────── riepilogo ─────────────────────────
dpkg-deb -f "$OUT" Package Version Architecture
echo "→ creato: $OUT"
echo
echo "Installa (upgrade):"
echo "  sudo apt install ./dist/$(basename "$OUT")"
echo
echo "Override manuale della Debian revision (se serve):"
echo "  PKG_REVISION=7 $0"

