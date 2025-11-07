#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APPNAME="HEVC Video Converter"
BUNDLE="HEVC-Video-Converter"
ICON_PNG="$ROOT/hevc_gui/resources/icons/logo.png"
ICON_ICNS="$ROOT/hevc_gui/resources/icons/logo.icns"
DIST="$ROOT/dist"

cd "$ROOT"

# 0) Requisiti
python3 -m pip install --upgrade pip
python3 -m pip install pyinstaller

# 1) Icona .icns (se manca, la genero da logo.png)
if [[ ! -f "$ICON_ICNS" ]]; then
  echo "== Creo .icns da logo.png =="
  ICONSET="$ROOT/tools/_tmp.iconset"
  rm -rf "$ICONSET"; mkdir -p "$ICONSET"
  # richiede 'sips' (c'è su macOS) e 'iconutil'
  for S in 16 32 64 128 256 512; do
    sips -z $S $S "$ICON_PNG" --out "$ICONSET/icon_${S}x${S}.png" >/dev/null
    sips -z $((S*2)) $((S*2)) "$ICON_PNG" --out "$ICONSET/icon_${S}x${S}@2x.png" >/dev/null
  done
  iconutil -c icns "$ICONSET" -o "$ICON_ICNS" || true
  rm -rf "$ICONSET"
fi

# 2) PyInstaller (bundle .app, risorse incluse)
rm -rf build "$DIST"
python3 -m PyInstaller \
  --name "$BUNDLE" \
  --windowed \
  --icon "$ICON_ICNS" \
  --add-data "hevc_gui/resources:hevc_gui/resources" \
  --add-data "hevc_gui/resources/doc:hevc_gui/resources/doc" \
  main.py

# 3) Rinomina in "HEVC Video Converter.app"
mkdir -p "$DIST"
APP_PATH="dist/$BUNDLE.app"
FINAL_APP="$DIST/$APPNAME.app"
rm -rf "$FINAL_APP"
mv "$APP_PATH" "$FINAL_APP"

# 4) Crea DMG (usa 'create-dmg' se presente, altrimenti hdiutil)
DMG="$DIST/$BUNDLE.dmg"
rm -f "$DMG"
if command -v create-dmg >/dev/null 2>&1; then
  create-dmg --overwrite --volname "$APPNAME" --window-size 600 400 \
    --icon "$APPNAME.app" 160 160 --app-drop-link 440 160 \
    "$DMG" "$DIST"
else
  # Fallback semplice con hdiutil
  TMP_D="$DIST/_dmg"
  rm -rf "$TMP_D"; mkdir -p "$TMP_D"
  cp -R "$FINAL_APP" "$TMP_D/"
  hdiutil create -volname "$APPNAME" -srcfolder "$TMP_D" -ov -format UDZO "$DMG"
  rm -rf "$TMP_D"
fi

echo "✔ App: $FINAL_APP"
echo "✔ DMG: $DMG"


