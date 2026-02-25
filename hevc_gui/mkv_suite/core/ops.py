#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Tuple

from .model import MediaInfo, TrackInfo, AttachmentInfo
from .toolchain import Toolchain, ToolError, run_cmd


def _safe_slug(s: str, maxlen: int = 80) -> str:
    s = (s or "").strip()
    s = s.replace("/", "_").replace("\\", "_")
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"[^0-9A-Za-z._ -]+", "", s)
    s = s.strip(" ._-")
    return (s[:maxlen] if len(s) > maxlen else s) or "track"


def _ext_for_codec_id(codec_id: str, ttype: str) -> str:
    cid = (codec_id or "").upper().strip()
    ttype = (ttype or "").lower().strip()

    # Audio
    if cid.startswith("A_AAC"):
        return "aac"
    if cid in ("A_AC3",):
        return "ac3"
    if cid in ("A_EAC3",):
        return "eac3"
    if cid in ("A_DTS",):
        return "dts"
    if cid in ("A_FLAC",):
        return "flac"
    if cid in ("A_OPUS",):
        return "opus"
    if cid.startswith("A_MPEG/L3"):
        return "mp3"
    if cid.startswith("A_MPEG/L2"):
        return "mp2"
    if cid.startswith("A_VORBIS"):
        return "ogg"
    if cid.startswith("A_TRUEHD") or cid.startswith("A_MLP"):
        return "truehd"

    # Subs
    if cid.startswith("S_TEXT/UTF8"):
        return "srt"
    if cid.startswith("S_TEXT/ASS"):
        return "ass"
    if cid.startswith("S_TEXT/SSA"):
        return "ssa"
    if cid.startswith("S_TEXT/WEBVTT"):
        return "vtt"
    if cid.startswith("S_HDMV/PGS"):
        return "sup"
    if cid.startswith("S_VOBSUB"):
        return "idx"

    # Video
    if cid.startswith("V_MPEG4/ISO/AVC"):
        return "h264"
    if cid.startswith("V_MPEGH/ISO/HEVC"):
        return "hevc"
    if cid.startswith("V_AV1") or cid.startswith("V_VP9") or cid.startswith("V_VP8"):
        return "ivf"

    # fallback
    if ttype == "audio":
        return "audio"
    if ttype == "subtitles":
        return "sub"
    if ttype == "video":
        return "video"
    return "bin"


def apply_tags_in_place(mi: MediaInfo, tc: Toolchain, title: str) -> Tuple[int, str, str]:
    if not tc.mkvpropedit:
        raise ToolError("mkvpropedit non trovato (installa mkvtoolnix).")

    cmd: List[str] = [tc.mkvpropedit, str(mi.path)]

    # titolo segmento
    cmd += ["--edit", "info", "--set", f"title={title}"]

    # tracks (usiamo selector track:n, n=ordinal)
    for t in mi.tracks:
        sel = f"track:{t.ordinal}"
        cmd += ["--edit", sel]

        # language
        if t.lang_user is not None:
            lang = (t.eff_lang() or "und")
            cmd += ["--set", f"language={lang}"]

        # name ("" = svuota)
        if t.name_user is not None:
            cmd += ["--set", f"name={t.eff_name()}"]

        # flags
        if t.default_user is not None:
            cmd += ["--set", f"flag-default={1 if t.default_user else 0}"]
        if t.forced_user is not None:
            cmd += ["--set", f"flag-forced={1 if t.forced_user else 0}"]

    rc, out, err = run_cmd(cmd)
    if rc != 0:
        raise ToolError((err or out or "").strip() or f"mkvpropedit fallito (rc={rc})")
    return rc, out, err


def extract_tracks(mi: MediaInfo, tc: Toolchain, tracks: List[TrackInfo], out_dir: Path, base: str):
    """
    Estrae tracce con mkvextract.
    Ritorna: (rc, stdout, stderr, output_paths)
    """
    if not tc.mkvextract:
        raise ToolError("mkvextract non trovato (installa mkvtoolnix).")

    out_dir.mkdir(parents=True, exist_ok=True)

    specs: List[str] = []
    outs: List[Path] = []

    for t in tracks:
        lang = t.eff_lang()
        name = _safe_slug(t.eff_name())
        ext = _ext_for_codec_id(t.codec_id, t.type)
        fn = f"{_safe_slug(base)}_T{t.tid}_{t.type}_{lang}_{name}_e.{ext}"
        out_path = out_dir / fn
        outs.append(out_path)
        specs.append(f"{t.tid}:{str(out_path)}")

    if not specs:
        return 0, "", "", []

    cmd = [tc.mkvextract, str(mi.path), "tracks"] + specs
    rc, out, err = run_cmd(cmd)
    if rc != 0:
        raise ToolError((err or out or "").strip() or f"mkvextract tracks fallito (rc={rc})")
    return rc, out, err, outs

def extract_attachments(mi: MediaInfo, tc: Toolchain, atts: List[AttachmentInfo], out_dir: Path) -> Tuple[int, str, str]:
    if not tc.mkvextract:
        raise ToolError("mkvextract non trovato (installa mkvtoolnix).")
    out_dir.mkdir(parents=True, exist_ok=True)

    specs: List[str] = []
    for a in atts:
        name = a.file_name or f"att_{a.aid}"
        name = _safe_slug(name, 120)
        specs.append(f"{a.aid}:{str(out_dir / name)}")

    if not specs:
        return 0, "", ""

    cmd = [tc.mkvextract, str(mi.path), "attachments"] + specs
    rc, out, err = run_cmd(cmd)
    if rc != 0:
        raise ToolError((err or out or "").strip() or f"mkvextract attachments fallito (rc={rc})")
    return rc, out, err


def extract_chapters(mi: MediaInfo, tc: Toolchain, out_file: Path) -> Tuple[int, str, str]:
    if not tc.mkvextract:
        raise ToolError("mkvextract non trovato (installa mkvtoolnix).")
    out_file.parent.mkdir(parents=True, exist_ok=True)

    cmd = [tc.mkvextract, str(mi.path), "chapters", str(out_file)]
    rc, out, err = run_cmd(cmd)
    # se non ci sono capitoli, mkvextract può non creare il file; non è un errore “grave”
    if rc != 0:
        raise ToolError((err or out or "").strip() or f"mkvextract chapters fallito (rc={rc})")
    return rc, out, err
