#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hevc_gui/video/trim_tools.py

Gestione globale del TRIM (taglio di un segmento interno):

- TrimSpec.start_sec / end_sec → intervallo (in secondi) da ELIMINARE
- TrimSpec.enabled             → bool: se False il trim è ignorato

Idea:
    Film originale:  [------ A ------][ XXX ][------ B ------]
    start_sec = IN, end_sec = OUT → elimino il blocco XXX
    Risultato:      [------ A -------------- B ------]

Lato ffmpeg:
    - VIDEO: split/trim/concat + catena filtri video
    - AUDIO: asplit/atrim/concat + catena filtri audio

Nota importante (fix “velocità doppia / sync”):
    Per l’audio usiamo asetpts=N/SR/TB (non PTS-STARTPTS), così la timeline
    viene ricostruita in modo deterministico sui campioni.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PyQt5.QtCore import QSettings


@dataclass
class TrimSpec:
    start_sec: float = 0.0
    end_sec: float = 0.0
    enabled: bool = False


_GROUP = "trim"


def _settings() -> QSettings:
    return QSettings()


def load_trim_settings() -> TrimSpec:
    """Legge IN/OUT/enabled dai settings (gruppo 'trim')."""
    s = _settings()
    s.beginGroup(_GROUP)
    try:
        start_sec = float(s.value("start_sec", 0.0))
    except Exception:
        start_sec = 0.0
    try:
        end_sec = float(s.value("end_sec", 0.0))
    except Exception:
        end_sec = 0.0
    enabled = bool(s.value("enabled", False, type=bool))
    s.endGroup()
    return TrimSpec(start_sec=start_sec, end_sec=end_sec, enabled=enabled)


def save_trim_settings(spec: Optional[TrimSpec] = None, **kwargs) -> None:
    """
    Salva IN/OUT/enabled nei settings.

    Compatibile con:
        save_trim_settings(TrimSpec(...))
    oppure:
        save_trim_settings(start_sec=..., end_sec=..., enabled=...)
    """
    if spec is None:
        spec = TrimSpec(
            start_sec=float(kwargs.get("start_sec", 0.0)),
            end_sec=float(kwargs.get("end_sec", 0.0)),
            enabled=bool(kwargs.get("enabled", False)),
        )

    s = _settings()
    s.beginGroup(_GROUP)
    s.setValue("start_sec", float(spec.start_sec))
    s.setValue("end_sec", float(spec.end_sec))
    s.setValue("enabled", bool(spec.enabled))
    s.endGroup()


def clear_trim_settings(disable_only: bool = True) -> None:
    """
    Se disable_only=True:
        - metti enabled=False ma tieni IN/OUT (per “ricordare” il trim).
    Se disable_only=False:
        - cancella completamente il gruppo (come se non fosse mai esistito).
    """
    s = _settings()
    s.beginGroup(_GROUP)
    if disable_only:
        s.setValue("enabled", False)
    else:
        s.remove("")
    s.endGroup()


def has_active_trim() -> bool:
    """True se c'è un trim attivo e sensato (IN<OUT)."""
    spec = load_trim_settings()
    return bool(
        spec.enabled
        and (spec.end_sec - spec.start_sec) > 1e-3
        and spec.start_sec >= 0.0
        and spec.end_sec > 0.0
    )


def build_video_trim_chain(base_chain: str, start_sec: float, end_sec: float) -> str:
    """
    Ritorna una filtergraph per -vf che TAGLIA via l'intervallo [start_sec, end_sec].
    Se il trim non è valido (IN>=OUT), ritorna base_chain così com'è.
    """
    if end_sec <= start_sec + 1e-3 or start_sec < 0.0:
        return base_chain

    prefix = (
        "split[vpre][vpost];"
        f"[vpre]trim=0:{start_sec:.3f},setpts=PTS-STARTPTS[vpre_t];"
        f"[vpost]trim={end_sec:.3f},setpts=PTS-STARTPTS[vpost_t];"
        "[vpre_t][vpost_t]concat=n=2:v=1:a=0"
    )
    return (prefix + "," + base_chain) if base_chain else prefix


def build_audio_trim_chain(base_chain: str, start_sec: float, end_sec: float) -> str:
    """
    Analogo di build_video_trim_chain, ma per -af (audio).
    Se il trim non è valido (IN>=OUT), ritorna base_chain così com'è.
    """
    if end_sec <= start_sec + 1e-3 or start_sec < 0.0:
        return base_chain

    # FIX: ricostruzione timeline robusta sui campioni
    prefix = (
        "asplit[apre][apost];"
        f"[apre]atrim=0:{start_sec:.3f},asetpts=N/SR/TB[apre_t];"
        f"[apost]atrim={end_sec:.3f},asetpts=N/SR/TB[apost_t];"
        "[apre_t][apost_t]concat=n=2:v=0:a=1"
    )
    return (prefix + "," + base_chain) if base_chain else prefix
