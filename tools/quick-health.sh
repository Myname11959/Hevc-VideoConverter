#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"

OUT="health-report.$(date +%F-%H%M%S).txt"
echo "== HEVC-GUI • Quick Health Check • $(date) ==" | tee "$OUT"

# 0) Elenco file Python (escludo roba d'archivio)
echo -e "\n[files] Scansione Python..." | tee -a "$OUT"
mapfile -t PYFILES < <(find . -type f -name '*.py' \
  -not -path './.git/*' \
  -not -path './packaging/*' \
  -not -path './_backup/*' \
  -not -path './_export/*' \
  -not -path './.ruff_cache/*' \
  -not -path './__pycache__/*' | LC_ALL=C sort)
echo "Totale file: ${#PYFILES[@]}" | tee -a "$OUT"

# 1) Encoding e CRLF
echo -e "\n[encoding] UTF-16/CRLF check..." | tee -a "$OUT"
UTF16=0; CRLF=0
for f in "${PYFILES[@]}"; do
  t=$(file -bi "$f" | sed 's/.*charset=//')
  [[ "$t" =~ utf-16 ]] && { echo "  UTF-16: $f" | tee -a "$OUT"; UTF16=$((UTF16+1)); }
  if grep -U -q $'\r$' "$f"; then
    echo "  CRLF:   $f" | tee -a "$OUT"; CRLF=$((CRLF+1))
  fi
done
echo "Riepilogo: UTF-16=$UTF16, CRLF=$CRLF" | tee -a "$OUT"

# 2) Compilazione Python (syntax errors)
echo -e "\n[python] py_compile (syntax)..." | tee -a "$OUT"
PYERR=0
for f in "${PYFILES[@]}"; do
  python3 -m py_compile "$f" 2>>"$OUT" || PYERR=$((PYERR+1))
done
echo "File con errori di sintassi: $PYERR" | tee -a "$OUT"

# 3) Ruff "critico" SOLO report (no fix, no estetica)
echo -e "\n[ruff] Controlli critici (E9,F63,F7,F82,F821)..." | tee -a "$OUT"
if command -v ruff >/dev/null 2>&1; then
  ruff check \
    --select E9,F63,F7,F82,F821 \
    --ignore E402,E501 \
    --exclude packaging,_backup,_export,.ruff_cache,__pycache__,.git \
    . | tee -a "$OUT" || true
else
  echo "Ruff non trovato: salto questa sezione." | tee -a "$OUT"
fi

echo -e "\n== DONE ==" | tee -a "$OUT"
ln -sf "$OUT" health-report.txt
echo "Report scritto in: $OUT (symlink: health-report.txt)"
