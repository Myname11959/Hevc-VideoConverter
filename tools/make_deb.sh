#!/usr/bin/env bash
set -euo pipefail

# repo root
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PKGDIR="$ROOT/pkg"
DIST="$ROOT/dist"
CONTROL="$PKGDIR/DEBIAN/control"
VER_FILE="$ROOT/hevc_gui/VERSION"

# versione base dal file (o override con RELEASE_VERSION)
if [[ ! -f "$VER_FILE" ]]; then
  echo "ERRORE: mancante $VER_FILE" >&2
  exit 1
fi
BASE_VER="${RELEASE_VERSION:-$(tr -d ' \r\n' < "$VER_FILE")}"
PKG_REV="${PKG_REVISION:-1}"                         # override con PKG_REVISION=2 se serve
DEB_VER="${BASE_VER}-${PKG_REV}"

# aggiorna Version: nel control
if [[ ! -f "$CONTROL" ]]; then
  echo "ERRORE: mancante $CONTROL" >&2
  exit 1
fi
sed -i -E "s/^Version: .*/Version: ${DEB_VER}/" "$CONTROL"

# leggi name/arch dal control
PKG_NAME="$(sed -n 's/^Package: //p' "$CONTROL" | head -n1)"
ARCH="$(sed -n 's/^Architecture: //p' "$CONTROL" | head -n1)"
: "${PKG_NAME:?ERRORE: campo Package: mancante in control}"
: "${ARCH:=all}"

# sanity: wrapper eseguibile e main presente
chmod 0755 "$PKGDIR/usr/bin/hevc-video-converter"
if [[ ! -f "$PKGDIR/usr/lib/hevc-video-converter/main.py" ]]; then
  echo "ERRORE: manca pkg/usr/lib/hevc-video-converter/main.py" >&2
  exit 1
fi

# build
rm -rf "$DIST"
mkdir -p "$DIST"
OUT="$DIST/${PKG_NAME}_${DEB_VER}_${ARCH}.deb"
dpkg-deb --build --root-owner-group "$PKGDIR" "$OUT"

# riepilogo e verifica
dpkg-deb -f "$OUT" Package Version Architecture
echo "→ creato: $OUT"

