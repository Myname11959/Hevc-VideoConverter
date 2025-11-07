#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Stampa un JSON racchiuso tra marker:
  ### AUDIO_CMDS_JSON_BEGIN ###
  [ { "cmd": [...], "cmd_line": "..." } ]
  ### AUDIO_CMDS_JSON_END ###

Uso tipico dal test:
  python3 tools/inspect_audio_cmds.py --input /dev/shm/af_tests/in.wav --reverb "Intermedio"
Opzioni:
  --input PATH         file audio di ingresso (se manca, lo creo con un toni 440Hz/3s)
  --reverb LABEL       etichetta UI (es. "Nessuno", "Intermedio", "Forte", ecc.)
  --external-af EXPR   catena -af già pronta (rispettata “as is”, niente auto-SOXR/dynaudnorm)
  --run                esegue davvero ffmpeg sull'output /dev/shm/af_tests/out.*
"""

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

# ── Setup import progetto ──────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent  # .../Hevc_gui
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Proviamo a usare i tuoi helper/const; se non ci sono, fallback sicuri
try:
    from hevc_gui.core import constants as C
except Exception:
    class C:  # fallback minimo
        FFMPEG_BIN = "ffmpeg"
        FFPROBE_BIN = "ffprobe"

try:
    from hevc_gui.core.helpers import select_reverb_expr
except Exception:
    # fallback: mappa essenziale (puoi ampliare)
    def select_reverb_expr(lbl: str) -> str | None:
        MAP = {
            "Minimo": "aecho=0.97:0.97:70:0.15",
            "Leggerissimo": "aecho=0.95:0.95:80:0.20",
            "Molto Leggero": "aecho=0.92:0.97:80|160:0.22|0.14",
            "Leggero": "aecho=0.90:0.98:60|120:0.30|0.18",
            "Intermedio-": "aecho=0.87:0.99:60|120|180:0.45|0.32|0.22",
            "Intermedio": "aecho=0.85:0.99:60|120|180:0.50|0.35|0.25",
            "Intermedio+": "aecho=0.83:0.99:60|120|180|240:0.55|0.40|0.28|0.20",
            "Moderato-": "aecho=0.82:0.99:60|120|180|240:0.58|0.42|0.30|0.22",
            "Moderato": "aecho=0.80:0.99:60|120|180:0.60|0.40|0.30",
            "Moderato+": "aecho=0.78:0.99:60|120|180|240:0.62|0.45|0.33|0.24",
            "Pronunciato": "aecho=0.75:0.99:60|120|180|240:0.65|0.50|0.38|0.28",
            "Forte": "aecho=0.70:1.00:60|120|180|240|300:0.70|0.55|0.40|0.30|0.22",
        }
        return MAP.get(lbl.strip()) or None

# ── Argomenti ─────────────────────────────────────────────────────────────
ap = argparse.ArgumentParser(add_help=True)
ap.add_argument("--input", required=True, help="file di input (wav/aac/…)")
ap.add_argument("--reverb", default="Nessuno", help="etichetta reverb UI")
ap.add_argument("--external-af", default=None, help="catena -af esterna (rispettata)")
ap.add_argument("--run", action="store_true", help="esegui ffmpeg davvero")
args = ap.parse_args()

INP = Path(args.input)
TMP = Path("/dev/shm/af_tests")
TMP.mkdir(parents=True, exist_ok=True)

FFMPEG = getattr(C, "FFMPEG_BIN", "ffmpeg") or "ffmpeg"

# ── Se input non esiste, crealo (sine 440Hz 3s) ───────────────────────────
if not INP.exists():
    try:
        subprocess.run(
            [
                FFMPEG,
                "-v", "error",
                "-f", "lavfi",
                "-i", "sine=frequency=440:duration=3",
                "-ac", "1",
                "-ar", "44100",
                str(INP),
                "-y",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        # Non sporcare stdout; eventuale msg su stderr
        print(f"Impossibile creare input di test: {e}", file=sys.stderr)
        sys.exit(1)

# ── Costruzione comando audio “come in GUI” ───────────────────────────────
# Base comando
cmd: list[str] = [FFMPEG, "-y", "-nostdin", "-i", str(INP), "-vn"]

# Scelta -af:
#  • Se --external-af: usiamo ESATTAMENTE quello (nessun SOXR auto)
#  • Altrimenti:
#      - sempre aresample=soxr
#      - se reverb="Nessuno": aggiungi dynaudnorm (come default “copia”)
#      - se reverb!=Nessuno: aggiungi aecho dalla mappa e *non* dynaudnorm
af_chain = None
if args.external_af:
    af_chain = args.external_af.strip()
else:
    parts = ["aresample=resampler=soxr"]
    rev = (args.reverb or "").strip()
    if rev and rev.lower() != "nessuno":
        expr = select_reverb_expr(rev)
        if expr:
            parts.append(expr)
    else:
        parts.append("dynaudnorm=f=250:g=31:p=0.95:m=50")
    af_chain = ",".join(parts)

if af_chain:
    cmd += ["-af", af_chain]

# Codec/containere default (come le tue esterne AAC)
# Non è importante per i test (greppano solo -af), ma teniamo coerenza.
ext = ".m4a"
container = ["-f", "ipod"]
tail = ["-movflags", "+faststart"]
cmd += ["-c:a", "aac", *container, *tail, str(TMP / f"out{ext}")]

# Piccoli limiti CPU coerenti con GUI (non indispensabili)
if "-filter_threads" not in cmd:
    cmd += ["-filter_threads", "1"]
if "-threads" not in cmd:
    cmd += ["-threads", "1"]

# ── Stampa JSON tra marker, SENZA rumore su stdout ────────────────────────
payload = [{"cmd": cmd, "cmd_line": " ".join(shlex.quote(x) for x in cmd)}]
sys.stdout.write("### AUDIO_CMDS_JSON_BEGIN ###\n")
json.dump(payload, sys.stdout, ensure_ascii=False)
sys.stdout.write("\n### AUDIO_CMDS_JSON_END ###\n")
sys.stdout.flush()

# ── Esecuzione reale (opzionale) ──────────────────────────────────────────
if args.run:
    # Mandiamo il log su stdout ma prefissato con "### " (il test fa sed su quello)
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in p.stdout:
            print("### " + line.rstrip("\n"))
        p.wait()
    except Exception as e:
        print("### [RUN ERR] " + str(e))
