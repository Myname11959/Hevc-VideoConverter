# mkv_tools/mkv_suite/core/auto_sync_manager.py
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

# soglia fissa interna: 0 = applica qualunque valore != 0
THRESHOLD_MS: int = 0

@dataclass(frozen=True)
class ProbeResult:
    video_tid: int
    video_min_ts_ns: int
    min_ts_ns: Dict[int, int]          # tid -> ns
    suggested_ms: Dict[int, int]       # tid -> ms (per mkvmerge --sync)

def _to_int(x) -> Optional[int]:
    try:
        return int(x)
    except Exception:
        try:
            return int(float(x))
        except Exception:
            return None

def probe_suggested_ms(input_path: str | Path, mkvmerge_bin: str = "mkvmerge") -> ProbeResult:
    p = Path(input_path)
    if not p.is_file():
        raise FileNotFoundError(str(p))

    cmd = [mkvmerge_bin, "-J", str(p)]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "").strip())

    data = json.loads(r.stdout)
    tracks = data.get("tracks", []) or []

    min_ts: Dict[int, int] = {}
    vids = []
    for t in tracks:
        tid = _to_int(t.get("id"))
        typ = t.get("type")
        props = t.get("properties") or {}
        mt = _to_int(props.get("minimum_timestamp"))
        if tid is None or mt is None:
            continue
        min_ts[int(tid)] = int(mt)
        if typ == "video":
            vids.append((int(tid), int(mt)))

    if not vids:
        # fallback: niente video -> reference 0
        v_tid, v_mt = 0, 0
    else:
        v_tid, v_mt = sorted(vids, key=lambda x: x[0])[0]

    suggested: Dict[int, int] = {}
    for t in tracks:
        tid = _to_int(t.get("id"))
        typ = t.get("type")
        if tid is None or typ != "audio":
            continue
        mt = min_ts.get(int(tid), 0)
        ms = int(round((v_mt - mt) / 1e6))   # ns -> ms
        suggested[int(tid)] = ms

    return ProbeResult(
        video_tid=v_tid,
        video_min_ts_ns=v_mt,
        min_ts_ns=min_ts,
        suggested_ms=suggested,
    )

def should_apply(ms: int) -> bool:
    if ms == 0:
        return False
    return abs(ms) >= THRESHOLD_MS
