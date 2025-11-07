#!/usr/bin/env bash
set -euo pipefail

F="hevc_gui/gui/main_window.py"
TS="$(date +%Y%m%d_%H%M%S)"
BK="${F}.bak_${TS}"

cp -a "$F" "$BK"
echo "Backup: $BK"

python3 - <<'PY'
import re, pathlib
p = pathlib.Path("hevc_gui/gui/main_window.py")
s = p.read_text(encoding="utf-8")
orig = s

# 1) Forza il path di log in /dev/shm/hevc_gui (niente sotto-dir extra)
s = re.sub(r'HEVC_LOG_DIR",\s*"/dev/shm/[^"]+"', 'HEVC_LOG_DIR", "/dev/shm/hevc_gui"', s)
s = s.replace('/dev/shm/hevc-video-converter/log', '/dev/shm/hevc_gui')
s = s.replace('/tmp/hevc-video-converter/log', '/tmp/hevc_gui')

# 2) Se nel blocco logger c'è un commento che crea "log/..." aggiungilo piatto
s = s.replace('base_dir / "log"', 'base_dir')  # nel dubbio, appiattisci

# 3) Assicura filename del log
s = re.sub(r'log_path\s*=\s*base_dir\s*/\s*Path?\(?["\'].*?["\']\)?',
           'log_path = base_dir / "gui_debug.log"', s)

# 4) Chiama refresh_icons() alla fine di _build_ui()
if '_build_ui(self):' in s and 'self.refresh_icons()' not in s:
    s = re.sub(
        r'(\n\s*layout\s*=\s*self\.centralWidget\(\)\.layout\(\)\s*\n\s*layout\.setContentsMargins\(.*\)\s*\n\s*layout\.setSpacing\(.*\)\s*\n)',
        r'\1\n        # Imposta le icone dell’app alla fine della build\n        try:\n            self.refresh_icons()\n        except Exception:\n            pass\n',
        s, count=1
    )

# 5) Piccola stampa di servizio in console con il path del log alla creazione del logger
if "root.debug(\"=== Avvio applicazione" in s and "logger_path" not in s:
    s = s.replace(
        'root.debug("=== Avvio applicazione — log file: %s ===", log_path)',
        'root.debug("=== Avvio applicazione — log file: %s ===", log_path); print("[LOG]", log_path)'
    )

if s != orig:
    p.write_text(s, encoding="utf-8")
PY

echo "Patch applicata a $F"

