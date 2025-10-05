#!/usr/bin/env bash
# Uso: bash tools/sanitize-log.sh file1 [file2 ...]
set -euo pipefail
for f in "$@"; do
  [ -f "$f" ] || { echo "Skip: $f non esiste"; continue; }
  out="${f%.txt}.ascii.txt"
  perl -0777 -pe 's/\e\[[0-9;?]*[ -/]*[@-~]//g; s/\e\][^\a]*\a//g; s/\e\([0-2]//g; s/\x0F//g' "$f" > "$out"
  echo "Pulito: $out"
done
