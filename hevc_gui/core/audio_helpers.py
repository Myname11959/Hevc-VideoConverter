# hevc_gui/core/audio_helpers.py

import subprocess
import json
from typing import List, Tuple


def audio_tracks_with_title(file_path: str) -> List[Tuple[int, str]]:
    """
    Ritorna una lista di (index, title_tag) per ogni traccia audio.
    Se manca il tag 'title', usa '' come tag vuoto.
    Se ffprobe fallisce o l'output non è JSON valido, restituisce lista vuota.
    """
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a",
        "-show_entries",
        "stream=index:stream_tags=title",
        "-of",
        "json",
        file_path,
    ]

    try:
        out = subprocess.check_output(cmd, text=True)
    except subprocess.CalledProcessError as e:
        # ffprobe ha restituito un errore (file corrotto o senza tracce audio)
        print(f"[WARN] ffprobe error: {e}")
        return []

    try:
        info = json.loads(out)
    except json.JSONDecodeError as e:
        # Output non JSON valido
        print(f"[WARN] JSON decode error: {e}")
        return []

    tracks: List[Tuple[int, str]] = []
    for s in info.get("streams", []):
        idx = s.get("index", 0)
        title = s.get("tags", {}).get("title", "")
        tracks.append((idx, title))

    return tracks
