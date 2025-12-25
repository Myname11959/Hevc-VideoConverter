#!/usr/bin/env bash
set -euo pipefail

# ───────────────────────── repo paths ─────────────────────────
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PKGDIR="$ROOT/pkg"
DIST="$ROOT/dist"
CONTROL="$PKGDIR/DEBIAN/control"
VER_FILE="$ROOT/hevc_gui/VERSION"

# ───────────────────────── helpers ─────────────────────────
die() { echo "ERRORE: $*" >&2; exit 1; }

need_cmd() { command -v "$1" >/dev/null 2>&1 || die "manca comando '$1'"; }

# Compila un .qrc in un .py (pyrcc5 o fallback)
compile_qrc() {
  local qrc="$1"
  local out_py="$2"

  [[ -f "$qrc" ]] || die "manca QRC: $qrc"

  if command -v pyrcc5 >/dev/null 2>&1; then
    pyrcc5 "$qrc" -o "$out_py"
  else
    python3 -m PyQt5.pyrcc_main "$qrc" -o "$out_py"
  fi

  [[ -s "$out_py" ]] || die "generazione fallita: $out_py"
}

# Genera un QRC MINIMALE (senza duplicazioni) a partire dalla cartella icons/
# - prefisso /icons
# - alias = nome file (ph_open.png ecc.) così le risorse sono :/icons/ph_open.png
gen_icons_qrc_temp() {
  local icons_dir="$1"   # .../hevc_gui/resources/icons
  local tmp_qrc="$2"

  [[ -d "$icons_dir" ]] || die "manca cartella icone: $icons_dir"

  {
    echo '<RCC>'
    echo '  <qresource prefix="/icons">'

    # logo (se presente)
    if [[ -f "$icons_dir/logo.png" ]]; then
      echo "    <file alias=\"logo.png\">$icons_dir/logo.png</file>"
    fi

    # tutte le icone ph_*.png / ph_*.svg (ordinate)
    # (find -printf è GNU; su Debian/Ubuntu ok)
    local listed=0
    while IFS= read -r f; do
      [[ -n "$f" ]] || continue
      echo "    <file alias=\"$f\">$icons_dir/$f</file>"
      listed=1
    done < <(find "$icons_dir" -maxdepth 1 -type f \( -name 'ph_*.png' -o -name 'ph_*.svg' \) -printf '%f\n' | LC_ALL=C sort)

    if [[ "$listed" -eq 0 ]]; then
      die "nessuna icona trovata in $icons_dir (attese ph_*.png o ph_*.svg)"
    fi

    echo '  </qresource>'
    echo '</RCC>'
  } > "$tmp_qrc"
}

# ───────────────────────── sanity ─────────────────────────
[[ -f "$VER_FILE" ]] || die "manca $VER_FILE"
[[ -f "$CONTROL"  ]] || die "manca $CONTROL"
[[ -d "$PKGDIR/usr" ]] || die "manca struttura pkg/usr (staging deb)"

# wrapper presente?
if [[ ! -x "$PKGDIR/usr/bin/hevc-video-converter" ]]; then
  if [[ -f "$PKGDIR/usr/bin/hevc-video-converter" ]]; then
    chmod 0755 "$PKGDIR/usr/bin/hevc-video-converter"
  else
    die "manca $PKGDIR/usr/bin/hevc-video-converter"
  fi
fi

# entrypoint sorgente (da installare nello staging)
[[ -f "$ROOT/main.py" ]] || die "manca $ROOT/main.py"

need_cmd dpkg-deb
need_cmd rsync
need_cmd python3

# ───────────────────────── versioni ─────────────────────────
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

# ───────────────────────── sync sorgenti nello staging pkg ─────────────────────────
STAGE="$PKGDIR/usr/lib/hevc-video-converter"
mkdir -p "$STAGE"

# copia TUTTA la cartella hevc_gui
rsync -a --delete "$ROOT/hevc_gui/" "$STAGE/hevc_gui/"

# copia la cartella scripts
if [[ -d "$ROOT/scripts" ]]; then
  rsync -a --delete "$ROOT/scripts/" "$STAGE/scripts/"
fi

# install main.py (entrypoint usato dal wrapper /usr/bin/hevc-video-converter)
install -m 0644 "$ROOT/main.py" "$STAGE/main.py"

# ───────────────────────── autogenera QRC e compila icons_rc.py nello staging ─────────────────────────
ICONS_DIR="$STAGE/hevc_gui/resources/icons"
OUT_RC_STAGE="$STAGE/hevc_gui/resources/icons_rc.py"

TMP_QRC="$(mktemp -p "${TMPDIR:-/tmp}" hevc-icons-XXXXXX.qrc)"
cleanup() { rm -f "$TMP_QRC"; }
trap cleanup EXIT

gen_icons_qrc_temp "$ICONS_DIR" "$TMP_QRC"
compile_qrc "$TMP_QRC" "$OUT_RC_STAGE"

echo "[INFO] icons_rc.py generato: $(du -h "$OUT_RC_STAGE" | awk '{print $1}')  → $OUT_RC_STAGE"

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

# ───────────────────────── ripulisci file generato nello staging ─────────────────────────
# Così non ti resta 'icons_rc.py' modificato dentro pkg/ e non rischi commit accidentali.
rm -f "$OUT_RC_STAGE"

# ───────────────────────── riepilogo ─────────────────────────
dpkg-deb -f "$OUT" Package Version Architecture
echo "→ creato: $OUT"
echo
echo "Installa (upgrade):"
echo "  sudo apt install ./dist/$(basename "$OUT")"
echo
echo "Override manuale della Debian revision (se serve):"
echo "  PKG_REVISION=7 $0"
