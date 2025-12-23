#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

_HEVC_DVD_DEBUG = os.getenv("HEVC_DVD_DEBUG", "0") not in ("", "0", "false", "no", "False", "No")


def _dprint(*a, **k) -> None:
    if not _HEVC_DVD_DEBUG:
        return
    try:
        print("[LDVD-SIDECAR]", *a, **k, flush=True)
    except Exception:
        pass


# ────────────────────────────── Data class ──────────────────────────────

@dataclass
class LdvdAudioTrack:
    index: int
    codec: str = ""
    channels: int = 0
    layout: str = ""
    sample_rate: int = 0
    language: str = ""
    name: str = ""
    default: bool = False


@dataclass
class LdvdSubtitleTrack:
    index: int
    format: str = ""
    language: str = ""
    name: str = ""
    kind: str = ""  # es. "normal", "sdh", "forced", ecc.
    forced: bool = False
    external_files: List[str] = field(default_factory=list)
    stream_index: int = 0      # indice globale ffprobe (0,1,2… → "0:<idx>")
    stream_id: str = ""        # es. "0x20", "0x21" (opzionale, ma utile per debug)


@dataclass
class LdvdSrtRequest:
    index: int
    language: str
    name: str
    reason: str
    target: str
    exists: bool = False  # true se il file .srt esiste già sul disco


@dataclass
class LdvdSidecar:
    base_vob: Path
    meta_path: Path
    chapters_file: Optional[Path]
    audio: List[LdvdAudioTrack] = field(default_factory=list)
    subtitles: List[LdvdSubtitleTrack] = field(default_factory=list)
    srt_mode: str = "none"
    srt_requests: List[LdvdSrtRequest] = field(default_factory=list)
    want_srt: bool = False

    @property
    def has_chapters(self) -> bool:
        return bool(self.chapters_file and self.chapters_file.is_file())

    @property
    def has_subtitles(self) -> bool:
        return bool(self.subtitles)

    @property
    def has_srt_plan(self) -> bool:
        return bool(self.want_srt and self.srt_requests)

    def scan_srt_files(self) -> None:
        """Aggiorna il flag .exists per ogni richiesta SRT."""
        for req in self.srt_requests:
            try:
                req.exists = os.path.isfile(req.target)
            except Exception:
                req.exists = False

    def summary_for_log(self) -> str:
        parts: List[str] = []
        parts.append(f"audio={len(self.audio)}")
        parts.append(f"subs={len(self.subtitles)}")
        parts.append("chapters=YES" if self.has_chapters else "chapters=NO")
        if self.has_srt_plan:
            done = sum(1 for r in self.srt_requests if r.exists)
            parts.append(f"srt_plan={len(self.srt_requests)} (presenti {done})")
        else:
            parts.append("srt_plan=NO")
        return ", ".join(parts)


# ────────────────────── helper per path sidecar ────────────────────────

def sidecar_paths_for(vob_path: str | Path) -> tuple[Path, Path]:
    """
    Dato il VOB di LDVD-Ripper, ritorna:
      (<basename>.ldvdmeta.json, <basename>.chapters_ogm.txt)
    SENZA controllare se esistono.
    """
    base = Path(vob_path)
    return (
        base.with_suffix(".ldvdmeta.json"),
        base.with_suffix(".chapters_ogm.txt"),
    )


# ───────────────────────────── loader ──────────────────────────────────

def _safe_int(val: Any, default: int = 0) -> int:
    try:
        return int(val)
    except Exception:
        return default


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        txt = path.read_text(encoding="utf-8")
        return json.loads(txt)
    except Exception as e:
        _dprint(f"Errore nel leggere/parsing JSON {path}: {e}")
        return None


def load_sidecar_for(vob_path: str | Path) -> Optional[LdvdSidecar]:
    """
    Carica il sidecar LDVD per un dato .vob.

    Ritorna un LdvdSidecar oppure None se il sidecar non c'è
    o è illeggibile.
    """
    base_vob = Path(vob_path)
    meta_path, guessed_chapters = sidecar_paths_for(base_vob)

    if not meta_path.is_file():
        _dprint(f"Nessun .ldvdmeta.json accanto a {base_vob}")
        return None

    data = _load_json(meta_path)
    if not data:
        return None

    audio_list: List[LdvdAudioTrack] = []
    for a in data.get("audio", []):
        try:
            audio_list.append(
                LdvdAudioTrack(
                    index=_safe_int(a.get("index", 0)),
                    codec=str(a.get("codec") or ""),
                    channels=_safe_int(a.get("channels", 0)),
                    layout=str(a.get("layout") or ""),
                    sample_rate=_safe_int(a.get("sample_rate", 0)),
                    language=str(a.get("language") or ""),
                    name=str(a.get("name") or ""),
                    default=bool(a.get("default", False)),
                )
            )
        except Exception as e:
            _dprint("Audio track non parsabile:", a, "err:", e)

    subs_list: List[LdvdSubtitleTrack] = []
    for s in data.get("subtitles", []):
        try:
            ext = s.get("external_files") or []
            if not isinstance(ext, list):
                ext = []
            subs_list.append(
                LdvdSubtitleTrack(
                    index=_safe_int(s.get("index", 0)),
                    format=str(s.get("format") or ""),
                    language=str(s.get("language") or ""),
                    name=str(s.get("name") or ""),
                    kind=str(s.get("kind") or ""),
                    forced=bool(s.get("forced", False)),
                    external_files=[str(p) for p in ext],
                    stream_index=_safe_int(s.get("stream_index", s.get("sub_index", 0))),
                    stream_id=str(s.get("stream_id") or ""),
                )
            )
        except Exception as e:
            _dprint("Subtitle track non parsabile:", s, "err:", e)

    srt_mode = str(data.get("srt_mode") or "none")
    want_srt = bool(data.get("want_srt", False))

    srt_reqs: List[LdvdSrtRequest] = []
    for r in data.get("srt_requests", []):
        try:
            srt_reqs.append(
                LdvdSrtRequest(
                    index=_safe_int(r.get("index", 0)),
                    language=str(r.get("language") or ""),
                    name=str(r.get("name") or ""),
                    reason=str(r.get("reason") or ""),
                    target=str(r.get("target") or ""),
                )
            )
        except Exception as e:
            _dprint("SRT request non parsabile:", r, "err:", e)

    chapters_file: Optional[Path] = None
    ch = data.get("chapters_file") or ""
    if ch:
        try:
            p = Path(ch)
            chapters_file = p
        except Exception:
            chapters_file = None
    if not (chapters_file and chapters_file.is_file()) and guessed_chapters.is_file():
        chapters_file = guessed_chapters

    sidecar = LdvdSidecar(
        base_vob=base_vob,
        meta_path=meta_path,
        chapters_file=chapters_file,
        audio=audio_list,
        subtitles=subs_list,
        srt_mode=srt_mode,
        srt_requests=srt_reqs,
        want_srt=want_srt,
    )
    sidecar.scan_srt_files()

    _dprint(f"Sidecar caricato da {meta_path}: {sidecar.summary_for_log()}")
    return sidecar
