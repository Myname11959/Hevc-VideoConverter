# mkv_tools/mkv_suite/core/auto_sync.py
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Dict, Iterable

def suggest_track_sync_ms(
    mkvmerge_bin: str,
    mkv_path: str | Path,
    types: Iterable[str] = ("audio", "subtitles"),
    threshold_ms: int = 0,
) -> Dict[int, int]:
    """
    Ritorna {tid: ms} dove ms è il valore da passare a mkvmerge --sync tid:ms
    per allineare AUDIO+SUBS al VIDEO (delta 0 vs video).
    """
    p = Path(mkv_path)
    if not p.is_file():
        raise FileNotFoundError(str(p))

    cmd = [mkvmerge_bin, "-J", str(p)]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()
        raise RuntimeError(err or f"mkvmerge -J rc={r.returncode}")

    data = json.loads(r.stdout or "{}")
    tracks = data.get("tracks") or []

    types = {str(t).lower() for t in types}

    vmin_ms = None
    tmin_ms: Dict[int, int] = {}

    for tr in tracks:
        tid = tr.get("id", None)
        ttype = (tr.get("type") or "").lower()
        props = tr.get("properties") or {}
        mts = props.get("minimum_timestamp", None)  # ns
        if tid is None or mts is None:
            continue
        try:
            ms = int(round(float(mts) / 1_000_000.0))
        except Exception:
            continue

        if ttype == "video":
            vmin_ms = ms if (vmin_ms is None or ms < vmin_ms) else vmin_ms
        elif ttype in types:
            tmin_ms[int(tid)] = ms

    if vmin_ms is None:
        vmin_ms = 0

    out: Dict[int, int] = {}
    for tid, ms in tmin_ms.items():
        corr = int(vmin_ms - ms)  # valore per --sync
        if threshold_ms and abs(corr) < int(threshold_ms):
            corr = 0
        out[int(tid)] = corr
    return out
