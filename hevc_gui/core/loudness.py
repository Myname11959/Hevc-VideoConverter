# -*- coding: utf-8 -*-
from __future__ import annotations
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# Binario ffmpeg (se definito in constants)
try:
    from . import constants as C

    _FFMPEG = getattr(C, "FFMPEG_BIN", "ffmpeg")
except Exception:
    _FFMPEG = "ffmpeg"

# ── Modalità di normalizzazione esposte in GUI ─────────────────────────────────
NORM_NONE = "Nessuna"
NORM_DYNA = "Dynaudnorm (default)"
NORM_LOUDNORM1 = "Loudnorm (EBU, 1-pass)"
NORM_LOUDNORM2 = "Loudnorm (EBU, 2-pass)"  # usata sia per preview che per encode

ALL_NORMS = [NORM_NONE, NORM_DYNA, NORM_LOUDNORM1, NORM_LOUDNORM2]

# Target “domestici” (coerenti con i giri precedenti)
DEFAULT_I = -16.0
DEFAULT_TP = -1.0
DEFAULT_LRA = 11.0


def build_norm_filters(mode: str, *, anticlipping: bool) -> List[str]:
    """
    Ritorna i filtri -af per la normalizzazione.
    NOTA: per NORM_LOUDNORM2 qui non aggiungiamo nulla: il 2° pass
          viene costruito con i parametri misurati (vedi funzioni di misura).
    """
    if mode not in ALL_NORMS or mode == NORM_NONE:
        return []

    if mode == NORM_DYNA:
        flt = ["dynaudnorm=f=250:g=31:p=0.95:m=50"]
        if anticlipping:
            flt.append("alimiter=limit=1.0")
        return flt

    if mode == NORM_LOUDNORM1:
        flt = [f"loudnorm=I={DEFAULT_I}:TP={DEFAULT_TP}:LRA={DEFAULT_LRA}"]
        if anticlipping:
            flt.append("alimiter=limit=1.0")
        return flt

    # NORM_LOUDNORM2 → nessun filtro qui (si usa build_second_pass_filter_from_json)
    return []


# ── Misurazioni per Loudnorm 2-pass ───────────────────────────────────────────


def _extract_json_from_text(txt: str) -> Optional[Dict[str, Any]]:
    """
    Prende l'ultimo blocco JSON presente nel testo (stderr tipicamente) e lo parse-a.
    """
    if not txt:
        return None
    start = txt.rfind("{")
    end = txt.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(txt[start : end + 1])
    except Exception:
        return None


def measure_loudnorm_first_pass(
    input_args: List[str],
    *,
    dur_args: List[str],
    I: float = DEFAULT_I,
    TP: float = DEFAULT_TP,
    LRA: float = DEFAULT_LRA,
) -> Optional[Dict[str, Any]]:
    """
    1° pass “grezzo” generico: passi tu [-i file, (-map 0:a:x)] e [durata].
    Ritorna il JSON con i measured_* da usare nel 2° pass.
    """
    cmd = (
        [_FFMPEG, "-hide_banner", "-nostdin"]
        + dur_args
        + input_args
        + [
            "-af",
            f"loudnorm=I={I}:TP={TP}:LRA={LRA}:print_format=json",
            "-f",
            "null",
            "-",
        ]
    )
    cp = subprocess.run(cmd, capture_output=True, text=True, check=False)
    # ffmpeg stampa su stderr (a volte anche su stdout — uniamo)
    block = (cp.stderr or "") + "\n" + (cp.stdout or "")
    return _extract_json_from_text(block)


def measure_loudnorm_smart(
    input_file: Union[str, Path],
    a_stream_idx: int = 0,
    *,
    ss: Optional[float] = None,
    t: float = 120.0,
    I: float = DEFAULT_I,
    TP: float = DEFAULT_TP,
    LRA: float = DEFAULT_LRA,
) -> Optional[Dict[str, Any]]:
    """
    1° pass “smart”: misura una finestra (default 120 s).
    Se ss=None, parte dal centro del file (scelto da chi la chiama).
    """
    args: List[str] = []
    if ss is not None:
        args += ["-ss", str(ss)]
    args += ["-i", str(input_file), "-map", f"0:a:{a_stream_idx}"]
    dur = ["-t", str(int(t))] if t and t > 0 else []
    return measure_loudnorm_first_pass(args, dur_args=dur, I=I, TP=TP, LRA=LRA)


def measure_loudnorm_full(
    input_file: Union[str, Path],
    a_stream_idx: int = 0,
    *,
    I: float = DEFAULT_I,
    TP: float = DEFAULT_TP,
    LRA: float = DEFAULT_LRA,
) -> Optional[Dict[str, Any]]:
    """
    1° pass completo sull'intera traccia.
    """
    args = ["-i", str(input_file), "-map", f"0:a:{a_stream_idx}"]
    return measure_loudnorm_first_pass(args, dur_args=[], I=I, TP=TP, LRA=LRA)


def build_second_pass_filter_from_json(
    data: Dict[str, Any],
    *,
    anticlipping: bool = False,
    I: float = DEFAULT_I,
    TP: float = DEFAULT_TP,
    LRA: float = DEFAULT_LRA,
) -> List[str]:
    """
    Costruisce il filtro loudnorm di 2° pass a partire dal JSON misurato.
    Aggiunge 'linear=true' e 'print_format=summary'. Opzionalmente un limiter.
    """

    # accetta sia chiavi input_* che measured_*
    def pick(d: Dict[str, Any], *keys: str) -> Optional[float]:
        for k in keys:
            if k in d and d[k] is not None:
                try:
                    return float(d[k])
                except Exception:
                    return None
        return None

    mI = pick(data, "measured_I", "input_i", "measured_i")
    mTP = pick(data, "measured_TP", "input_tp", "measured_tp")
    mLRA = pick(data, "measured_LRA", "input_lra", "measured_lra")
    mThr = pick(data, "measured_thresh", "input_thresh")
    off = pick(data, "target_offset", "offset")

    parts = [f"I={I}", f"TP={TP}", f"LRA={LRA}"]
    if mI is not None:
        parts.append(f"measured_I={mI}")
    if mTP is not None:
        parts.append(f"measured_TP={mTP}")
    if mLRA is not None:
        parts.append(f"measured_LRA={mLRA}")
    if mThr is not None:
        parts.append(f"measured_thresh={mThr}")
    if off is not None:
        parts.append(f"offset={off}")
    parts += ["linear=true", "print_format=summary"]

    flt = ["loudnorm=" + ":".join(parts)]
    if anticlipping:
        flt.append("alimiter=limit=1.0")
    return flt
