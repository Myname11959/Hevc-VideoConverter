#!/usr/bin/env bash
set -euo pipefail

# Root del repo = cartella padre di questo script
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
cd "$ROOT"

echo "== HEVC-GUI quick sanity =="
echo "Repo: $ROOT"

FAIL=0

have() { command -v "$1" >/dev/null 2>&1; }

# 1) Tool di base
for c in python3 grep awk sed; do
  if ! have "$c"; then
    echo "FATAL: comando mancante: $c"
    FAIL=1
  fi
done

# 2) FFmpeg tools
for c in ffmpeg ffprobe; do
  if have "$c"; then
    "$c" -hide_banner -version | head -n1
  else
    echo "FATAL: manca $c"
    FAIL=1
  fi
done
# opzionali (solo warning)
for c in ffplay cpulimit taskset ionice nice; do
  if have "$c"; then
    echo "OK: $c presente"
  else
    echo "WARN: $c assente (ok se non usato)"
  fi
done

# 3) Verifica risorse principali
ICON="$ROOT/hevc_gui/resources/icons/logo.png"
if [[ -f "$ICON" ]]; then
  echo "OK: icon $ICON"
else
  echo "WARN: icona non trovata ($ICON)"
fi

# 4) Compilazione bytecode Python (catch syntax errors)
echo "== py_compile =="
python3 - <<'PY'
import compileall, sys
ok = compileall.compile_dir('.', force=False, quiet=1)
sys.exit(0 if ok else 1)
PY

# 5) Import smoke-test + check simboli attesi in MainWindow
echo "== import test =="
python3 - <<'PY'
import sys
from importlib import import_module

mods = [
  "hevc_gui.gui.main_window",
  "hevc_gui.core.constants",
  "hevc_gui.core.queue",
]
for m in mods:
    import_module(m)

from hevc_gui.gui.main_window import MainWindow
need = [
  "_wrap_with_cpu_limits",
  "toggle_pause",
  "_path_changed",
  "_wire_dblclick_for_all_combos",
  "_apply_elabora_enabled",
]
missing = [n for n in need if not hasattr(MainWindow, n)]
if missing:
    print("FATAL: simboli mancanti in MainWindow:", ", ".join(missing))
    sys.exit(2)

# info CPU limits da constants (se presenti)
try:
    import hevc_gui.core.constants as C
    cpulim = int(getattr(C, "CPU_CPULIMIT", 0) or 0)
    enable = bool(getattr(C, "CPU_LIMITS_ENABLE", True))
    print(f"INFO: CPU_LIMITS_ENABLE={enable} CPU_CPULIMIT={cpulim}")
except Exception:
    pass
print("OK: import + simboli MainWindow")
PY

# 6) Se constants chiede cpulimit>0 ma non c'è, solo warning
CPULIMIT_WANTED="$(python3 - <<'PY'
try:
    import hevc_gui.core.constants as C
    print(int(getattr(C,"CPU_CPULIMIT",0) or 0))
except Exception:
    print(0)
PY
)"
if [[ "${CPULIMIT_WANTED}" -gt 0 && ! $(command -v cpulimit) ]]; then
  echo "WARN: CPU_CPULIMIT=${CPULIMIT_WANTED} ma 'cpulimit' non è installato."
fi

# 7) Stampa esito
if [[ $FAIL -ne 0 ]]; then
  echo "== RISULTATO: ❌ problemi rilevati"
  exit 1
else
  echo "== RISULTATO: ✅ sanity OK"
fi

