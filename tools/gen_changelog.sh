#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

OUT="${1:-CHANGELOG.md}"
DATE="$(date +%Y-%m-%d)"
VER="$(cat hevc_gui/VERSION 2>/dev/null || echo "Unreleased")"

# ultimo tag (se esiste)
LAST_TAG="$(git describe --tags --abbrev=0 2>/dev/null || true)"

{
  echo "# Changelog"
  echo
  echo "## [$VER] - $DATE"
  echo
  if [[ -n "$LAST_TAG" ]]; then
    echo "_Changes since ${LAST_TAG}_"
    echo
    git log --no-merges --pretty="* %s (%h)" "$LAST_TAG..HEAD"
  else
    echo "_No git tags found — latest commits:_"
    echo
    git log --no-merges -n 60 --pretty="* %s (%h)"
  fi
  echo
  echo "## Older releases"
  echo
  echo "See: https://github.com/Myname11959/Hevc-VideoConverter/releases"
  echo
} > "$OUT"

echo "[OK] Wrote $OUT"

