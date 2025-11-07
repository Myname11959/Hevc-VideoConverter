#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

# Crea l’archivio sorgente: dist/hevc-video-converter-<ver>.tar.gz
# Usa git archive se disponibile; altrimenti tar su copia “pulita”.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=release.env
. "${SCRIPT_DIR}/release.env"

VERSION="$(get_version)"
TARBALL="${DIST_DIR}/${APP_ID}-${VERSION}.tar.gz"

mkdir -p "${DIST_DIR}"

echo "==> Sorgente: ${ROOT}"
echo "==> Versione: ${VERSION}"
echo "==> Tarball : ${TARBALL}"

if git -C "${ROOT}" rev-parse --git-dir >/dev/null 2>&1; then
  echo "-- git archive..."
  (cd "${ROOT}" && git archive --format=tar --prefix="${APP_ID}-${VERSION}/" HEAD) | gzip -9 > "${TARBALL}"
else
  echo "-- tar (repo non git)..."
  TMPDIR="$(mktemp -d)"
  trap 'rm -rf "${TMPDIR}"' EXIT

  CLEAN="${TMPDIR}/${APP_ID}-${VERSION}"
  rsync -a --exclude '.git' --exclude 'build' --exclude 'dist' --exclude '__pycache__' \
        --exclude '*.pyc' --exclude '*.pyo' --exclude '*.egg-info' \
        --exclude '.ruff_cache' --exclude '.mypy_cache' \
        "${ROOT}/" "${CLEAN}/"

  (cd "${TMPDIR}" && tar -czf "${TARBALL}" "${APP_ID}-${VERSION}")
fi

echo "✅ Fatto: ${TARBALL}"

