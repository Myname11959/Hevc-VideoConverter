#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hevc_gui/video/crop_tools.py

Crop tool:
- Salva/legge crop (w,h,x,y) + flags (enabled, force_169, force_scope)
- inject_crop(): inserisce crop=... prima del primo scale=... (se presente)

NB: Il “consume” vero lo facciamo in main_window (fine encode + cambio file).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple
import subprocess

from PyQt5.QtCore import QSettings

# ✅ FIX: constants sta in hevc_gui/core/
from hevc_gui.core import constants as C


SETTINGS_ORG = "hevc_gui"
SETTINGS_APP = "video"
GROUP = "crop"

KEY_ENABLED = "enabled"
KEY_W = "w"
KEY_H = "h"
KEY_X = "x"
KEY_Y = "y"
KEY_FORCE_169 = "force_169"
KEY_FORCE_SCOPE = "force_scope"


@dataclass
class CropSpec:
    w: int
    h: int
    x: int
    y: int


def _s() -> QSettings:
    return QSettings(SETTINGS_ORG, SETTINGS_APP)


def save_crop_settings(
    w: int,
    h: int,
    x: int,
    y: int,
    *,
    enabled: bool = True,
    force_169: bool = False,
    force_scope: bool = False,
) -> None:
    s = _s()
    s.beginGroup(GROUP)
    s.setValue(KEY_ENABLED, 1 if enabled else 0)
    s.setValue(KEY_W, int(w))
    s.setValue(KEY_H, int(h))
    s.setValue(KEY_X, int(x))
    s.setValue(KEY_Y, int(y))
    s.setValue(KEY_FORCE_169, 1 if force_169 else 0)
    s.setValue(KEY_FORCE_SCOPE, 1 if force_scope else 0)
    s.endGroup()


def load_crop_settings() -> Tuple[Optional[CropSpec], bool, bool, bool]:
    s = _s()
    s.beginGroup(GROUP)
    try:
        enabled = str(s.value(KEY_ENABLED, "0")).strip() in ("1", "true", "True", "yes", "on")
        w = int(s.value(KEY_W, 0) or 0)
        h = int(s.value(KEY_H, 0) or 0)
        x = int(s.value(KEY_X, 0) or 0)
        y = int(s.value(KEY_Y, 0) or 0)
        force_169 = str(s.value(KEY_FORCE_169, "0")).strip() in ("1", "true", "True", "yes", "on")
        force_scope = str(s.value(KEY_FORCE_SCOPE, "0")).strip() in ("1", "true", "True", "yes", "on")
    except Exception:
        enabled, w, h, x, y, force_169, force_scope = False, 0, 0, 0, 0, False, False
    finally:
        s.endGroup()

    spec = CropSpec(w=w, h=h, x=x, y=y) if (w > 0 and h > 0) else None
    return spec, bool(enabled), bool(force_169), bool(force_scope)


def clear_crop_settings(*, disable_only: bool = True) -> None:
    """
    disable_only=True  -> spegne crop ma conserva w/h/x/y (utile se vuoi solo “toggle off”)
    disable_only=False -> cancella tutto il gruppo crop
    """
    s = _s()
    s.beginGroup(GROUP)
    try:
        if disable_only:
            s.setValue(KEY_ENABLED, 0)
            s.setValue(KEY_FORCE_169, 0)
            s.setValue(KEY_FORCE_SCOPE, 0)
        else:
            s.remove("")
    finally:
        s.endGroup()


def probe_resolution(input_path: str) -> tuple[int, int]:
    """
    Ritorna (w,h) del primo stream video via ffprobe.
    """
    try:
        out = subprocess.check_output(
            [
                C.FFPROBE_BIN,
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=p=0:s=x",
                str(input_path),
            ],
            text=True,
        ).strip()
        if "x" in out:
            w_s, h_s = out.split("x", 1)
            return int(w_s), int(h_s)
    except Exception:
        pass
    return 0, 0


def inject_crop(vf_parts: list[str], spec: CropSpec) -> None:
    """
    Inserisce crop=... prima del primo scale=... (così croppi prima di ridimensionare).
    Se non c'è scale, lo mette in testa.
    """
    crop = f"crop={spec.w}:{spec.h}:{spec.x}:{spec.y}"

    # evita doppioni
    if any(f.strip().startswith("crop=") for f in vf_parts):
        # rimpiazza il primo crop trovato
        for i, f in enumerate(vf_parts):
            if f.strip().startswith("crop="):
                vf_parts[i] = crop
                return
        vf_parts.insert(0, crop)
        return

    scale_idx = -1
    for i, f in enumerate(vf_parts):
        if f.strip().startswith("scale="):
            scale_idx = i
            break

    if scale_idx >= 0:
        vf_parts.insert(scale_idx, crop)
    else:
        vf_parts.insert(0, crop)
