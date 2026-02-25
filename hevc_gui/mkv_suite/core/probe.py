#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .model import MediaInfo, TrackInfo, AttachmentInfo
from .toolchain import Toolchain, ToolError, run_cmd


def probe_mkv(path: Path, tc: Toolchain) -> MediaInfo:
    if not tc.mkvmerge:
        raise ToolError("mkvmerge non trovato (installa mkvtoolnix).")

    cmd = [tc.mkvmerge, "-J", str(path)]
    rc, out, err = run_cmd(cmd)
    if rc != 0:
        raise ToolError((err or out or "").strip() or f"mkvmerge -J fallito (rc={rc})")

    data = json.loads(out)
    mi = MediaInfo(path=path)

    tracks = data.get("tracks") or []
    for i, tr in enumerate(tracks):
        props = tr.get("properties") or {}
        tid = int(tr.get("id", i))
        ttype = str(tr.get("type") or "")
        codec_id = str(props.get("codec_id") or "")
        codec = str(props.get("codec") or "")

        lang = props.get("language")
        if lang is None:
            lang = "und"
        name = props.get("track_name")
        if name is None:
            name = ""

        fd = props.get("default_track")
        ff = props.get("forced_track")

        ti = TrackInfo(
            ordinal=i + 1,
            tid=tid,
            type=ttype,
            codec_id=codec_id,
            codec=codec,
            language=str(lang),
            name=str(name),
            flag_default=(bool(fd) if fd is not None else None),
            flag_forced=(bool(ff) if ff is not None else None),
            include=True,
        )
        mi.tracks.append(ti)

    atts = data.get("attachments") or []
    for a in atts:
        props = a.get("properties") or {}
        aid = int(a.get("id", 0))
        fn = props.get("file_name") or a.get("file_name") or ""
        mt = props.get("content_type") or props.get("mime_type") or a.get("mime_type") or ""
        mi.attachments.append(AttachmentInfo(aid=aid, file_name=str(fn), mime_type=str(mt)))

    return mi
