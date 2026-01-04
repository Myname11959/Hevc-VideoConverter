#!/usr/bin/env bash
set -euo pipefail

# ───────────────────────────────────────────────────────────────
# i18n rebuild "one shot" (EN) — sicuro e ripetibile
#
# Uso tipico:
#   tools/i18n_rebuild_en_onfly.sh
#
# Opzioni:
#   --lang=en|it          (default: en)
#   --wrap-underhood      (OPZIONALE: lancia il codemod "underhood" se vuoi wrappare sinks)
#   --no-scan             (salta scanner)
#   --no-compile          (salta py_compile)
# ───────────────────────────────────────────────────────────────

LANG_CODE="en"
DO_WRAP=0
DO_SCAN=1
DO_COMPILE=1

for a in "$@"; do
  case "$a" in
    --lang=*) LANG_CODE="${a#--lang=}" ;;
    --wrap-underhood) DO_WRAP=1 ;;
    --no-scan) DO_SCAN=0 ;;
    --no-compile) DO_COMPILE=0 ;;
    *) echo "Argomento sconosciuto: $a" >&2; exit 2 ;;
  esac
done

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${ROOT}" ]]; then
  echo "ERRORE: non sembra un repo git (o non sei nella root)." >&2
  exit 2
fi
cd "$ROOT"

STAMP="$(date +%Y%m%d_%H%M%S)"
WORK="/tmp/i18n_rebuild_${STAMP}"
mkdir -p "$WORK"
echo "[i18n] workdir: $WORK"
echo "[i18n] lang: $LANG_CODE"

TS="hevc_gui/resources/i18n/hevc_en.ts"
QM="hevc_gui/resources/i18n/hevc_en.qm"

command -v pylupdate5 >/dev/null || { echo "ERRORE: pylupdate5 non trovato" >&2; exit 3; }
command -v lrelease  >/dev/null || { echo "ERRORE: lrelease non trovato" >&2; exit 3; }

# 0) snapshot diff (così non perdi niente se qualcosa va storto)
git diff > "$WORK/git_diff_before.patch" || true

# 1) sanity compile (tutto il repo tracciato)
if [[ "$DO_COMPILE" -eq 1 ]]; then
  echo "[i18n] py_compile: tutti i .py tracciati..."
  python3 - <<'PY'
import subprocess, py_compile, sys
files = subprocess.check_output(["git","ls-files","*.py"]).decode().splitlines()
bad=[]
for f in files:
    try:
        py_compile.compile(f, doraise=True)
    except Exception as e:
        bad.append((f,str(e)))
if bad:
    print(f"[FAIL] py_compile: {len(bad)} errori")
    for f,e in bad[:50]:
        print(f"\n--- {f} ---\n{e}")
    sys.exit(1)
print("[OK] py_compile: tutto ok")
PY
fi

# 2) scanner (solo report: non modifica nulla)
if [[ "$DO_SCAN" -eq 1 ]]; then
  if [[ -f tools/i18n_scan_naked_strings.py ]]; then
    echo "[i18n] scan naked strings..."
    python3 tools/i18n_scan_naked_strings.py | tee "$WORK/naked_report.txt" >/dev/null || true
    echo "[i18n] naked report -> $WORK/naked_report.txt"
  fi
  if [[ -f tools/i18n_scan_pyqt_strings.py ]]; then
    echo "[i18n] scan pyqt strings..."
    python3 tools/i18n_scan_pyqt_strings.py | tee "$WORK/pyqt_report.txt" >/dev/null || true
    echo "[i18n] pyqt report  -> $WORK/pyqt_report.txt"
  fi
fi

# 3) (OPZIONALE) codemod underhood (solo se glielo chiedi esplicitamente)
if [[ "$DO_WRAP" -eq 1 ]]; then
  if [[ ! -f tools/i18n_one_shot_underhood.py ]]; then
    echo "ERRORE: tools/i18n_one_shot_underhood.py non trovato" >&2
    exit 4
  fi
  BAK="$WORK/underhood_bak"
  mkdir -p "$BAK"
  echo "[i18n] underhood wrap: APPLY (backup: $BAK)"
  python3 tools/i18n_one_shot_underhood.py --apply --backup-dir "$BAK"
fi

# 4) aggiorna TS (estrazione+merge safe)
echo "[i18n] update TS (safe)..."
python3 tools/update_ts_en_safe.py | tee "$WORK/update_ts.log" >/dev/null

# 5) override mirati (es. menubar LDVD) — IMPORTANTI per non tornare in italiano
#    (se esistono, li eseguiamo in ordine)
echo "[i18n] apply overrides (se presenti)..."
for f in \
  tools/override_ldvd_menu_en.py \
  tools/apply_overrides_ldvd_en.py \
  tools/apply_overrides_ldvd_ui_en.py
do
  if [[ -f "$f" ]]; then
    echo "  - $f"
    python3 "$f" | tee -a "$WORK/overrides.log" >/dev/null
  fi
done

# 6) fill optional (se hai lo script di fill safe)
if [[ -f tools/ts_fill_untranslated_en.py ]]; then
  echo "[i18n] fill untranslated (safe heuristic)..."
  python3 tools/ts_fill_untranslated_en.py "$TS" | tee "$WORK/ts_fill.log" >/dev/null
fi

# 7) rebuild QM
echo "[i18n] lrelease -> qm..."
lrelease "$TS" -qm "$QM" | tee "$WORK/lrelease.log" >/dev/null

# 8) smoke check runtime (DEVE tradurre sia L() che QCoreApplication.translate)
echo "[i18n] smoke check runtime..."
HEVC_LANG="$LANG_CODE" python3 - <<'PY'
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QCoreApplication
from hevc_gui.i18n import init_qt_i18n, set_lang, L

app = QApplication([])
set_lang("en")
init_qt_i18n(app)

# L() check
a = L("Pronto")
b = L("Apri .srt")

# Qt translate check (LDVD menubar)
ctx = "hevc_gui.dvd_ripper.gui"
m = QCoreApplication.translate(ctx, "&Azioni")

print("L('Pronto') ->", a)
print("L('Apri .srt') ->", b)
print("translate('&Azioni') ->", m)

# condizioni minime (se falliscono, la rebuild non è affidabile)
assert a in ("Ready","Ready."), "L('Pronto') non traduce in EN"
assert b.startswith("Open"), "L('Apri .srt') non traduce in EN"
assert m in ("&Actions","Actions","&Action"), "Menù LDVD '&Azioni' non tradotto"
print("[OK] smoke check passed")
PY

echo
echo "[OK] i18n rebuild completata."
echo "  TS : $TS"
echo "  QM : $QM"
echo "  Log: $WORK"
echo
echo "Prova:"
echo "  HEVC_LANG=$LANG_CODE python3 main.py"
