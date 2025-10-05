#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"

OUT="verify-report.txt"
: > "$OUT"

say(){ printf '\n== %s ==\n' "$*" | tee -a "$OUT"; }

say "HEVC-GUI • Verifica non-distruttiva ($(date))"

# 1) Raccogli i .py: se git è vuoto o non repo → fallback find
PYFILES=()
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  mapfile -t PYFILES < <(git ls-files '*.py' 2>/dev/null || true)
fi
if [ ${#PYFILES[@]} -eq 0 ]; then
  mapfile -t PYFILES < <(find . -type f -name '*.py' \
    -not -path './.git/*' \
    -not -path './packaging/*' \
    -not -path './_backup/*' \
    -not -path './_export/*' \
    -not -path './.ruff_cache/*' \
    -not -path './__pycache__/*' \
    | LC_ALL=C sort)
fi

say "1) Elenco file Python"
echo "Totale: ${#PYFILES[@]}" | tee -a "$OUT"
for f in "${PYFILES[@]}"; do echo "  $f" >> "$OUT"; done

# 2) Encoding/CRLF
say "2) Controllo encoding/CRLF"
UTF16=0; CRLF=0
for f in "${PYFILES[@]}"; do
  enc="$(file -bi "$f" | sed 's/.*charset=//')"
  [[ "$enc" =~ utf-16 ]] && { echo "UTF-16: $f" | tee -a "$OUT"; UTF16=$((UTF16+1)); }
  if grep -U -q $'\r$' "$f"; then
    echo "CRLF:   $f" | tee -a "$OUT"; CRLF=$((CRLF+1))
  fi
done
echo "Riepilogo: UTF-16=$UTF16, CRLF=$CRLF" | tee -a "$OUT"

# 3) Syntax (py_compile) — senza here-doc annidati
say "3) Syntax check (py_compile)"
TMPLIST="$(mktemp)"
trap 'rm -f "$TMPLIST"' EXIT
printf '%s\n' "${PYFILES[@]}" > "$TMPLIST"

PYERR=0
python3 - "$OUT" "$TMPLIST" <<'PY' || PYERR=1
import sys, py_compile, pathlib
out, list_path = sys.argv[1], sys.argv[2]
files = pathlib.Path(list_path).read_text().splitlines()
bad=[]
for f in files:
    try:
        py_compile.compile(f, doraise=True)
    except Exception as e:
        bad.append((f, str(e)))
if bad:
    with open(out, "a", encoding="utf-8") as fh:
        for f,err in bad:
            fh.write(f"  SYNTAX: %s\n    %s\n" % (f, err))
    sys.exit(1)
print("OK: nessun errore di sintassi")
PY

if [ "$PYERR" -ne 0 ]; then
  echo "Esito: ERRORI di sintassi (vedi sopra)" | tee -a "$OUT"
else
  echo "Esito: OK" | tee -a "$OUT"
fi

# 4) Ruff (solo errori DAVVERO seri) — report ONLY
say "4) Ruff (solo errori critici) — report ONLY"
if command -v ruff >/dev/null 2>&1 && [ ${#PYFILES[@]} -gt 0 ]; then
  ruff check \
    --select E9,F63,F7,F82,F821 \
    --ignore E402,E501 \
    --exclude packaging,_backup,_export,.ruff_cache,__pycache__,.git \
    "${PYFILES[@]}" 2>&1 | tee -a "$OUT" || true
else
  echo "Ruff non trovato o nessun file: salto." | tee -a "$OUT"
fi

say "FINE — report salvato in $OUT"
