#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_PKGDIR="$ROOT/pkg"
DIST="$ROOT/dist"
SRC_CONTROL="$SRC_PKGDIR/DEBIAN/control"
VER_FILE="$ROOT/hevc_gui/VERSION"

die(){ echo "ERRORE: $*" >&2; exit 1; }
need(){ command -v "$1" >/dev/null 2>&1 || die "comando mancante: $1"; }

need rsync
need dpkg-deb
need python3
need pyrcc5

[[ -f "$VER_FILE" ]] || die "manca $VER_FILE"
[[ -f "$SRC_CONTROL" ]] || die "manca $SRC_CONTROL"

BASE_VER="${RELEASE_VERSION:-$(tr -d ' \r\n' < "$VER_FILE")}"

# workspace
WORK="$(mktemp -d -t hevc_deb_XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

PKGDIR="$WORK/pkg"
CONTROL="$PKGDIR/DEBIAN/control"

mkdir -p "$DIST"
rsync -a "$SRC_PKGDIR/" "$PKGDIR/"

# Version nel control SOLO nello staging
if [[ -n "${PKG_REVISION:-}" ]]; then
  DEB_VER="${BASE_VER}-${PKG_REVISION}"
else
  # auto-bump se non passi PKG_REVISION
  ORIG_CTRL_VER="$(sed -n 's/^Version: //p' "$SRC_CONTROL" | head -n1 || true)"
  ORIG_BASE="${ORIG_CTRL_VER%-*}"; ORIG_REV="${ORIG_CTRL_VER##*-}"
  if [[ "$ORIG_CTRL_VER" == "$ORIG_BASE" ]]; then ORIG_REV=""; fi
  if [[ -n "$ORIG_REV" && "$ORIG_BASE" == "$BASE_VER" && "$ORIG_REV" =~ ^[0-9]+$ ]]; then
    DEB_VER="${BASE_VER}-$((ORIG_REV+1))"
  else
    DEB_VER="${BASE_VER}-1"
  fi
fi
DEB_VER="$ORIG_CTRL_VER"
sed -i -E "s/^Version: .*/Version: ${DEB_VER}/" "$CONTROL"

PKG_NAME="$(sed -n 's/^Package: //p' "$CONTROL" | head -n1)"
ARCH="$(sed -n 's/^Architecture: //p' "$CONTROL" | head -n1)"
: "${PKG_NAME:?ERRORE: Package: mancante}"
: "${ARCH:=all}"

# layout staging
STAGE="$PKGDIR/usr/lib/hevc-video-converter"
mkdir -p "$STAGE"

# wrapper (assicurati exec)
[[ -f "$PKGDIR/usr/bin/hevc-video-converter" ]] || die "manca $PKGDIR/usr/bin/hevc-video-converter"
chmod 0755 "$PKGDIR/usr/bin/hevc-video-converter" || true

# copia sorgenti nello staging (questa è la payload del deb)
rsync -a --delete "$ROOT/hevc_gui/" "$STAGE/hevc_gui/"
if [[ -d "$ROOT/scripts" ]]; then
  rsync -a --delete "$ROOT/scripts/" "$STAGE/scripts/"
fi
[[ -f "$ROOT/main.py" ]] && install -m 0644 "$ROOT/main.py" "$STAGE/main.py"

# ─────────────── Qt resources: genera QRC + compila icons_rc.py nello staging ───────────────
RES_DIR="$STAGE/hevc_gui/resources"
ICONS_DIR="$RES_DIR/icons"
QRC="$RES_DIR/icons.qrc"
RC_PY="$RES_DIR/icons_rc.py"

[[ -d "$ICONS_DIR" ]] || die "manca cartella icone nello staging: $ICONS_DIR"

python3 - <<PY
from pathlib import Path
icons_dir = Path(r"$ICONS_DIR")
qrc_path  = Path(r"$QRC")

files = sorted([p for p in icons_dir.iterdir()
                if p.is_file() and p.suffix.lower() in (".png",".svg",".ico")])

if not files:
    raise SystemExit("Nessuna icona trovata in: " + str(icons_dir))

lines = ["<RCC>", '  <qresource prefix="/icons">']
for p in files:
    rel = f"icons/{p.name}"
    # path "reale" → :/icons/icons/<name>
    lines.append(f"    <file>{rel}</file>")
    # alias corto → :/icons/<name>
    lines.append(f'    <file alias="{p.name}">{rel}</file>')
    # alias senza ph_ (compat LDVD) → :/icons/<senza_ph_>
    if p.name.startswith("ph_"):
        lines.append(f'    <file alias="{p.name[3:]}">{rel}</file>')
lines += ["  </qresource>", "</RCC>"]
qrc_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"[QRC] scritto: {qrc_path} ({len(files)} file)")
PY

pyrcc5 "$QRC" -o "$RC_PY"

# check minimo: deve esistere almeno un'icona tipica
python3 - <<PY
import importlib.util
from PyQt5.QtCore import QFile

spec = importlib.util.spec_from_file_location("icons_rc", r"$RC_PY")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

ok = QFile.exists(":/icons/ph_open.png") or QFile.exists(":/icons/icons/ph_open.png")
assert ok, "QRC/RC non valido: non trovo ph_open.png nel resource system"
print("[QRC] OK")
PY

# opzionale: non installare il .qrc nel deb (lo usiamo solo per generare rc)
rm -f "$QRC" || true

# ─────────────── build ───────────────
OUT="$DIST/${PKG_NAME}_${DEB_VER}_${ARCH}.deb"
echo "== Build .deb =="
echo "Package: $PKG_NAME"
echo "Version: $DEB_VER"
echo "Arch:    $ARCH"
echo "Output:  $OUT"
echo

dpkg-deb --build --root-owner-group "$PKGDIR" "$OUT"
dpkg-deb -f "$OUT" Package Version Architecture
echo "→ creato: $OUT"
