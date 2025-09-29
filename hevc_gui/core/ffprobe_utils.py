# -*- coding: utf-8 -*-
from __future__ import annotations
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional, Union

# Usa FFPROBE_BIN se definito in constants.py, altrimenti 'ffprobe'
try:
    from . import constants as C

    _FFPROBE = getattr(C, "FFPROBE_BIN", "ffprobe")
except Exception:
    _FFPROBE = "ffprobe"


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def probe_audio_stream(
    src: Union[str, Path],
    *,
    stream_index: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Ritorna info basilari sulla traccia audio richiesta:
      { 'channels': int, 'channel_layout': str, 'codec_name': str, 'sample_rate': str }
    stream_index: se None → a:0
    """
    sel = f"a:{stream_index if stream_index is not None else 0}"
    cmd = [
        _FFPROBE,
        "-v",
        "error",
        "-select_streams",
        sel,
        "-show_entries",
        "stream=channels,channel_layout,codec_name,sample_rate",
        "-of",
        "json",
        str(src),
    ]
    cp = _run(cmd)
    if cp.returncode != 0:
        return {}
    try:
        data = json.loads(cp.stdout or "{}")
        streams = data.get("streams") or []
        return streams[0] if streams else {}
    except Exception:
        return {}


def probe_audio_channels(input_path: Union[str, Path], stream_idx: int) -> int:
    """
    Ritorna SOLO il numero canali (0 se non disponibile).
    Wrapper compatibile con il vecchio uso.
    """
    info = probe_audio_stream(input_path, stream_index=stream_idx)
    try:
        return int(info.get("channels") or 0)
    except Exception:
        return 0
