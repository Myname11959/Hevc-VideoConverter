#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


def _norm_lang(x: Optional[str]) -> str:
    s = (x or "").strip()
    return s if s else "und"


@dataclass
class TrackInfo:
    ordinal: int                 # 1..N (ordine tracce)
    tid: int                     # Track ID per mkvextract (da mkvmerge)
    type: str                    # video/audio/subtitles/buttons
    codec_id: str = ""
    codec: str = ""
    language: str = "und"
    name: str = ""

    flag_default: Optional[bool] = None
    flag_forced: Optional[bool] = None

    include: bool = True

    # override manuali (None = non toccato; "" = svuota)
    lang_user: Optional[str] = None
    name_user: Optional[str] = None
    default_user: Optional[bool] = None
    forced_user: Optional[bool] = None

    def eff_lang(self) -> str:
        if self.lang_user is None:
            return _norm_lang(self.language)
        return _norm_lang(self.lang_user)

    def eff_name(self) -> str:
        if self.name_user is None:
            return (self.name or "").strip()
        # "" vuol dire: svuota (voluto)
        return (self.name_user or "").strip()

    def eff_default(self) -> Optional[bool]:
        return self.flag_default if self.default_user is None else self.default_user

    def eff_forced(self) -> Optional[bool]:
        return self.flag_forced if self.forced_user is None else self.forced_user


@dataclass
class AttachmentInfo:
    aid: int
    file_name: str
    mime_type: str = ""


@dataclass
class MediaInfo:
    path: Path
    tracks: List[TrackInfo] = field(default_factory=list)
    attachments: List[AttachmentInfo] = field(default_factory=list)

    def merge_user_overrides_from(self, old: "MediaInfo") -> None:
        """
        Mantieni override manuali quando ricarichi/probi di nuovo.
        Matching: (type, tid)
        """
        idx: Dict[tuple[str, int], TrackInfo] = {(t.type, t.tid): t for t in old.tracks}
        for t in self.tracks:
            k = (t.type, t.tid)
            o = idx.get(k)
            if not o:
                continue
            t.lang_user = o.lang_user
            t.name_user = o.name_user
            t.default_user = o.default_user
            t.forced_user = o.forced_user
            t.include = o.include
