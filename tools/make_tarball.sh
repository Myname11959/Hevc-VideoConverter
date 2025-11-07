#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"
VER="$(git -C "$ROOT_DIR" describe --tags --abbrev=0 2>/dev/null || date +%Y.%m.%d)"
NAME="hevc-video-converter-$VER"

rm -rf "$DIST_DIR/$NAME"
mkdir -p "$DIST_DIR/$NAME"
rsync -a --exclude '.git' --exclude 'dist' --exclude '.ruff_cache' --exclude '__pycache__' \
      "$ROOT_DIR/" "$DIST_DIR/$NAME/"

# launcher comodo
cat > "$DIST_DIR/$NAME/run.sh" <<'EOF'
#!/usr/bin/env bash
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$HERE/main.py" "$@"
EOF
chmod +x "$DIST_DIR/$NAME/run.sh"

tar -C "$DIST_DIR" -czf "$DIST_DIR/$NAME.tar.gz" "$NAME"
echo "✔ Creato: dist/$NAME.tar.gz"

