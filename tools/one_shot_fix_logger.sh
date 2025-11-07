#!/usr/bin/env bash
set -euo pipefail

F="hevc_gui/gui/main_window.py"
TS="$(date +%Y%m%d_%H%M%S)"
BK="${F}.bak_${TS}"

# 1) Backup
cp -a "$F" "$BK"
echo "Backup creato: $BK"

# 2) Patch via Python (regex difensive, idempotenti)
python3 - <<'PY'
import re, sys, pathlib

F = pathlib.Path("hevc_gui/gui/main_window.py")
src = F.read_text(encoding="utf-8")

orig = src

# A) rimuovi "import builtins" (se presente)
src = re.sub(r'(?m)^\s*import\s+builtins\s*\n', '', src)

# B) rimuovi la funzione custom print(...) e l’assegnazione builtins.print = print
#    (cerchiamo blocchi robusti per evitare falsi positivi)
#    1) _original_print = builtins.print  → rimuovi questa riga
src = re.sub(r'(?m)^\s*_original_print\s*=\s*builtins\.print\s*\n', '', src)

#    2) def print(...): ... (blocchi con indentazione fino alla riga vuota successiva o fino a 'class ' / 'def ' / decorator)
src = re.sub(
    r'(?s)\n\s*def\s+print\s*\(\*args,\s*\*\*kwargs\)\s*:\s*.*?\n(?=\s*(?:@|def\s|class\s|builtins\.print\s*=|#|from\s|import\s|$))',
    '\n',
    src
)

#    3) builtins.print = print
src = re.sub(r'(?m)^\s*builtins\.print\s*=\s*print\s*\n', '', src)

# C) sostituisci l’intero blocco "Logger" con il nuovo blocco /dev/shm
#    Identifichiamo l’inizio poco dopo la riga con "FFMPEG_BIN"
start_anchor = r'(?m)^\s*#\s*—+.*\n\s*#\s*Logger.*\n'
#    Fine blocco vecchio: fino alla prima riga successiva che introduce una sezione importante (es. "Widget helper" o classe)
end_anchor   = r'(?m)^\s*#\s*—+.*Widget helper.*\n'
m_start = re.search(start_anchor, src)
m_end   = re.search(end_anchor, src)

NEW = r"""
# —————————————————————————————————————————————————————————————
# Logger → file in /dev/shm/ (in RAM). Nessun unlink, nessun override di print.
# —————————————————————————————————————————————————————————————
import os
import sys
import logging
from pathlib import Path

logging.raiseExceptions = False  # non far esplodere l'app se il logger fallisce

def _setup_logging() -> logging.Logger:
    # Path di default in RAM; puoi sovrascrivere con HEVC_LOG_DIR se vuoi.
    base_dir = Path(os.environ.get("HEVC_LOG_DIR", "/dev/shm/hevc-video-converter/log"))
    try:
        base_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        # fallback di sicurezza se /dev/shm/ non è disponibile
        base_dir = Path("/tmp/hevc-video-converter/log")
        base_dir.mkdir(parents=True, exist_ok=True)

    log_path = base_dir / "gui_debug.log"

    root = logging.getLogger()
    if not root.handlers:
        root.setLevel(logging.DEBUG)
        fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(message)s")

        fh = logging.FileHandler(str(log_path), mode="w", encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        root.addHandler(fh)

        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.INFO)  # a console teniamo INFO+
        ch.setFormatter(fmt)
        root.addHandler(ch)

        root.debug("=== Avvio applicazione — log file: %s ===", log_path)

    return logging.getLogger(__name__)

logger = _setup_logging()

def excepthook(exc_type, exc_value, exc_tb):
    logging.getLogger(__name__).error("Uncaught exception", exc_info=(exc_type, exc_value, exc_tb))
    sys.__excepthook__(exc_type, exc_value, exc_tb)

sys.excepthook = excepthook

# ────────────────────────────────────────────────────────────────────────
# Widget helper per drag&drop di file video
# ────────────────────────────────────────────────────────────────────────
""".lstrip('\n')

if m_start and m_end and m_start.start() < m_end.start():
    # sostituisco il blocco vecchio (Logger → fino al titolo successivo) col nuovo
    src = src[:m_start.start()] + NEW + src[m_end.start():]
else:
    # fallback: prova a cercare il vecchio "log_path" + "builtins.print = print" e sostituisci quel range
    beg = src.find('log_path = log_dir / "gui_debug.log"')
    end = src.find('Widget helper per drag&drop di file video')
    if beg != -1 and end != -1 and beg < end:
        # risali all'inizio della sezione (qualche riga sopra)
        up = src.rfind('\n#', 0, beg)
        if up != -1:
            src = src[:up+1] + NEW + src[end - 1:]
    else:
        # Se non troviamo le ancore, inserisci comunque il nuovo blocco subito dopo FFMPEG_BIN
        pos = src.find('FFMPEG_BIN')
        if pos != -1:
            line_end = src.find('\n', pos)
            if line_end != -1:
                src = src[:line_end+1] + '\n' + NEW + src[line_end+1:]

if src != orig:
    F.write_text(src, encoding="utf-8")
else:
    # nessuna modifica (probabilmente già patchato)
    pass
PY

echo "Patch completata su $F"
echo "Se qualcosa non ti piace:  cp -a $BK $F  (ripristina)"

