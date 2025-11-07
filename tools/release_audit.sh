#!/usr/bin/env bash
set -euo pipefail

# ── Config ──────────────────────────────────────────────────────────────
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"

OK()    { printf "\033[1;32m[OK]\033[0m    %s\n"    "$*"; }
MISS()  { printf "\033[1;31m[MISSING]\033[0m %s\n"  "$*"; }
SUGG()  { printf "\033[1;33m[SUGGEST]\033[0m %s\n"  "$*"; }
INFO()  { printf "\033[1;36m[INFO]\033[0m  %s\n"    "$*"; }
HEAD()  { printf "\n\033[1;34m== %s ==\033[0m\n"    "$*"; }

must_files=(
  "README.md"
  "LICENSE"
  "main.py"
  "pyproject.toml"
  ".gitignore"
  ".editorconfig"
  "hevc_gui/__init__.py"
  "hevc_gui/gui/main_window.py"
  "hevc_gui/resources/icons.qrc"
  "hevc_gui/resources/icons_rc.py"
  "tools/scan_deps.py"
)
must_dirs=(
  "hevc_gui"
  "hevc_gui/core"
  "hevc_gui/gui"
  "hevc_gui/resources/icons"
  ".github/workflows"
  "tools"
  "tests/assets"
)

opt_files=(
  "tools/make_deb.sh"           # script di build .deb (se non c’è: suggerito)
  "debian/control.template"     # template opzionale per pacchetto
)

# ── Check base tree ─────────────────────────────────────────────────────
HEAD "Verifica struttura progetto"
miss=0
for f in "${must_files[@]}"; do
  if [[ -f "$f" ]]; then OK "$f"; else MISS "$f"; ((miss++)); fi
done
for d in "${must_dirs[@]}"; do
  if [[ -d "$d" ]]; then OK "$d/"; else MISS "$d/"; ((miss++)); fi
done
for f in "${opt_files[@]}"; do
  if [[ -e "$f" ]]; then OK "$f"; else SUGG "$f (opzionale, utile per packaging)"; fi
done

# ── Icone minime ────────────────────────────────────────────────────────
HEAD "Verifica icone"
icons_needed=( "logo.png" "ph_info.png" "ph_paypal.png" "ph_help.png" )
for ic in "${icons_needed[@]}"; do
  if [[ -f "hevc_gui/resources/icons/$ic" ]]; then OK "icons/$ic"; else MISS "icons/$ic"; ((miss++)); fi
done

# ── README/LICENCE minimi ───────────────────────────────────────────────
HEAD "Verifica README/LICENCE"
if grep -qiE "README — EN|README – EN|README EN" README.md && grep -qiE "README — IT|README – IT|README IT" README.md; then
  OK "README.md (sezioni IT/EN trovate)"
else
  SUGG "README.md senza doppia sezione IT/EN? (controlla i titoli)"
fi
if [[ $(wc -c < LICENSE) -gt 100 ]]; then
  OK "LICENSE presente (dimensione >100 byte)"
else
  SUGG "LICENSE sembra troppo corta: verifica contenuto"
fi

# ── Compilazione Python e import minimi ─────────────────────────────────
HEAD "Verifica sintassi Python"
if git ls-files "*.py" >/dev/null; then
  python3 - <<'PY'
import sys, compileall
ok = compileall.compile_dir(".", force=False, quiet=1, maxlevels=10)
sys.exit(0 if ok else 1)
PY
  OK "Compilazione bytecode OK"
else
  SUGG "Nessun .py tracciato? (controlla git)"
fi

HEAD "Import minimi (PyQt5 / ffmpeg presence nel PATH non verificata qui)"
python3 - <<'PY'
import importlib, sys
mods = ["PyQt5","pyqtgraph","numpy","psutil","chardet"]
missing=[]
for m in mods:
    try:
        importlib.import_module(m)
    except Exception as e:
        missing.append((m,str(e)))
if missing:
    print("MISSING Python modules:")
    for m,e in missing: print(" -", m, "→", e)
    sys.exit(0)  # non fallire: è audit progetto, non runtime CI
else:
    print("All core Python imports OK")
PY

# ── Dipendenze (tools/scan_deps.py) ─────────────────────────────────────
HEAD "Analisi dipendenze (tools/scan_deps.py)"
if [[ -f tools/scan_deps.py ]]; then
  python3 tools/scan_deps.py || true
  OK "scan_deps eseguito"
else
  SUGG "Manca tools/scan_deps.py (consigliato per controllare Depends/Recommends)"
fi

# ── Workflow CI (badge) ─────────────────────────────────────────────────
HEAD "Workflow CI essenziali"
ci_files=( ".github/workflows/ui-smoketest.yml" ".github/workflows/ruff.yml" )
for wf in "${ci_files[@]}"; do
  if [[ -f "$wf" ]]; then OK "$wf"; else SUGG "$wf (utile ma non obbligatorio)"; fi
done

# ── Riepilogo ───────────────────────────────────────────────────────────
HEAD "Riepilogo"
if (( miss == 0 )); then
  OK "Tutti i file/dir obbligatori presenti"
else
  MISS "Mancano $miss elementi obbligatori (vedi sopra)"
fi

INFO "Consigliato: git status; poi commit & push se tutto ok."

