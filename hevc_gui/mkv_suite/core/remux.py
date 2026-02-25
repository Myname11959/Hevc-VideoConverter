#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

from .model import MediaInfo, TrackInfo
from .toolchain import Toolchain, ToolError, run_cmd


def remux_mkv(mi: MediaInfo, tc: Toolchain, tracks: List[TrackInfo], out_file: Path) -> Tuple[int, str, str]:
    """
    Crea un nuovo MKV mantenendo il contenitore (MKV) e includendo SOLO le tracce passate.
    Track selection tramite mkvmerge (--video-tracks/--audio-tracks/--subtitle-tracks).
    """
    if not tc.mkvmerge:
        raise ToolError("mkvmerge non trovato (installa mkvtoolnix).")

    out_file.parent.mkdir(parents=True, exist_ok=True)

    vids = [str(t.tid) for t in tracks if (t.type or "").lower() == "video"]
    auds = [str(t.tid) for t in tracks if (t.type or "").lower() == "audio"]
    subs = [str(t.tid) for t in tracks if (t.type or "").lower() == "subtitles"]
    buts = [str(t.tid) for t in tracks if (t.type or "").lower() == "buttons"]

    cmd: List[str] = [tc.mkvmerge, "-o", str(out_file)]

    # se non selezioni un tipo, lo escludiamo esplicitamente
    if vids: cmd += ["--video-tracks", ",".join(vids)]
    else:    cmd += ["--no-video"]

    if auds: cmd += ["--audio-tracks", ",".join(auds)]
    else:    cmd += ["--no-audio"]

    if subs: cmd += ["--subtitle-tracks", ",".join(subs)]
    else:    cmd += ["--no-subtitles"]

    if buts: cmd += ["--button-tracks", ",".join(buts)]
    else:    cmd += ["--no-buttons"]

    # capitoli/attachments li lasciamo di default (mkvmerge li copia se presenti)
    cmd += [str(mi.path)]

    rc, out, err = run_cmd(cmd)
    if rc != 0:
        raise ToolError((err or out or "").strip() or f"mkvmerge fallito (rc={rc})")
    return rc, out, err
def remux_video_only(mi: MediaInfo, tc: Toolchain, video_tracks: List[TrackInfo], out_file: Path, title: str = "") -> Tuple[int, str, str]:
    """
    Crea un MKV con SOLO video (container MKV), senza ricodifiche.
    Output tipico: video.mkv
    """
    if not tc.mkvmerge:
        raise ToolError("mkvmerge non trovato (installa mkvtoolnix).")

    out_file.parent.mkdir(parents=True, exist_ok=True)

    vids = [str(t.tid) for t in video_tracks if (t.type or "").lower() == "video"]
    cmd: List[str] = [tc.mkvmerge, "-o", str(out_file)]

    if title.strip():
        cmd += ["--title", title.strip()]

    if vids:
        cmd += ["--video-tracks", ",".join(vids)]
    else:
        cmd += ["--no-video"]

    cmd += ["--no-audio", "--no-subtitles", "--no-buttons"]
    cmd += [str(mi.path)]

    rc, out, err = run_cmd(cmd)
    if rc != 0:
        raise ToolError((err or out or "").strip() or f"mkvmerge fallito (rc={rc})")
    return rc, out, err
