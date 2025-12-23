# -*- coding: utf-8 -*-
"""
hevc_gui/video/crop_tools.py

Helper per:
- probing risoluzione sorgente (ffprobe)
- persistenza impostazioni crop (QSettings)
- iniezione filtro crop nella -vf chain
- adattamento "no-stretch" con pad al primo scale numerico
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Tuple, List
import subprocess
import json
import re

from PyQt5.QtCore import QSettings

# Provo a leggere costanti (SAR PAL ecc.); se non ci sono, uso fallback
try:
    from hevc_gui.core import constants as C
    FFPROBE_BIN = getattr(C, "FFPROBE_BIN", "ffprobe")
    PAL_SAR_4_3  = getattr(C, "PAL_SAR_4_3",  "16/15")
    PAL_SAR_16_9 = getattr(C, "PAL_SAR_16_9", "64/45")
except Exception:
    FFPROBE_BIN = "ffprobe"
    PAL_SAR_4_3  = "16/15"
    PAL_SAR_16_9 = "64/45"


# ──────────────────────────────────────────────────────────────────────────────
# Dataclass & settings
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class CropSpec:
    w: int
    h: int
    x: int
    y: int

def _settings() -> QSettings:
    # namespace semplice e stabile
    return QSettings("hevc_gui", "video")

def save_crop_settings(w: int, h: int, x: int, y: int,
                       *, enabled: bool = True,
                       force_169: bool = False,
                       force_scope: bool = False) -> None:
    s = _settings()
    s.setValue("crop/enabled", int(bool(enabled)))
    s.setValue("crop/w", int(w))
    s.setValue("crop/h", int(h))
    s.setValue("crop/x", int(x))
    s.setValue("crop/y", int(y))
    s.setValue("crop/force_169",  int(bool(force_169)))
    s.setValue("crop/force_scope", int(bool(force_scope)))
    s.sync()

def load_crop_settings() -> tuple[Optional[CropSpec], bool, bool, bool]:
    """
    Ritorna: (CropSpec|None, enabled, force_169, force_scope)
    """
    s = _settings()
    enabled = bool(int(s.value("crop/enabled", 0)))
    try:
        w = int(s.value("crop/w", 0))
        h = int(s.value("crop/h", 0))
        x = int(s.value("crop/x", 0))
        y = int(s.value("crop/y", 0))
    except Exception:
        w = h = x = y = 0
    spec = CropSpec(w, h, x, y) if (w > 0 and h > 0) else None
    force_169  = bool(int(s.value("crop/force_169", 0)))
    force_scope = bool(int(s.value("crop/force_scope", 0)))
    return spec, enabled, force_169, force_scope

# Spegne il crop (e opz. pulisce tutto)
def clear_crop_settings(disable_only: bool = True) -> None:
    s = _settings()
    if disable_only:
        # come “riavvio”: crop disabilitato ma rettangolo ricordato
        s.setValue("crop/enabled", 0)
        s.setValue("crop/force_169", 0)
        s.setValue("crop/force_scope", 0)
    else:
        # wipe completo delle chiavi crop
        for k in (
            "crop/enabled", "crop/w", "crop/h", "crop/x", "crop/y",
            "crop/force_169", "crop/force_scope"
        ):
            s.remove(k)
    s.sync()

# ──────────────────────────────────────────────────────────────────────────────
# Probe
# ──────────────────────────────────────────────────────────────────────────────

def probe_resolution(path: str) -> Optional[Tuple[int, int]]:
    """
    Ritorna (width, height) del primo stream video oppure None.
    """
    try:
        out = subprocess.check_output(
            [
                FFPROBE_BIN, "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "json", str(path),
            ],
            text=True
        )
        st = json.loads(out)["streams"][0]
        w = int(st.get("width") or 0)
        h = int(st.get("height") or 0)
        return (w, h) if (w and h) else None
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Filtro crop nella chain
# ──────────────────────────────────────────────────────────────────────────────

def inject_crop(vf_parts: List[str], spec: CropSpec) -> None:
    """
    Inserisce/aggiorna 'crop=W:H:X:Y' prima del primo 'scale=' numerico.
    Se un 'crop=' esiste (in una voce singola o dentro una voce con più filtri), lo sostituisce.
    NOTE: si assume che W,H,X,Y siano già pari (li hai già normalizzati a monte).
    """
    crop_str = f"crop={int(spec.w)}:{int(spec.h)}:{int(spec.x)}:{int(spec.y)}"

    # 1) Prova a sostituire un crop già presente
    replaced = False
    for i, f in enumerate(vf_parts):
        s = f.strip()

        # caso semplice: la voce è proprio "crop=..."
        if s.startswith("crop="):
            vf_parts[i] = crop_str
            replaced = True
            break

        # caso composito: dentro la stessa voce ci sono più filtri separati da virgole
        if "crop=" in s:
            # rimpiazza solo il segmento crop=...
            new_s = re.sub(r'(?:(?<=,)|^)\s*crop=[^,]+', crop_str, s)
            if new_s != s:
                vf_parts[i] = new_s
                replaced = True
                break

    if replaced:
        return

    # 2) Inserisci prima del primo "scale=WxH" numerico; altrimenti append in coda
    insert_at = -1
    for i, f in enumerate(vf_parts):
        # rimuovi spazi per semplificare il match
        compact = f.replace(" ", "")
        # matcha solo scale con numeri (es. scale=720:576[:...])
        if re.search(r'(^|,)scale=\d+\s*:\s*\d+', compact):
            insert_at = i
            break

    if insert_at >= 0:
        vf_parts.insert(insert_at, crop_str)
    else:
        vf_parts.append(crop_str)


# ──────────────────────────────────────────────────────────────────────────────
# Fit senza stirare + eventuale SAR/DAR per SD
# ──────────────────────────────────────────────────────────────────────────────

def _find_numeric_scale(vf_parts: List[str]) -> tuple[int, Optional[int], Optional[int]]:
    """
    Trova il primo 'scale=W:H' con W,H numerici.
    Ritorna (index, W, H) oppure (-1, None, None)
    """
    for i, f in enumerate(vf_parts):
        m = re.search(r"scale\s*=\s*(\d+)\s*:\s*(\d+)", f.replace(" ", ""))
        if m:
            return i, int(m.group(1)), int(m.group(2))
    return -1, None, None


def auto_fit_no_stretch(vf_parts: List[str],
                        spec: CropSpec,
                        *,
                        force_pal_auto: bool = True,
                        force_169: bool = False,
                        force_scope: bool = False) -> None:
    """
    Se esiste uno scale numerico 'scale=W:H[...]':
      - aggiunge 'force_original_aspect_ratio=decrease' se mancante;
      - aggiunge 'pad=W:H:(W-iw)/2:(H-ih)/2' subito dopo per “riempire”,
        così non c'è nessuno stretch;
      - se H è 576/480/486 e force_169==True → imposta SAR/DAR per 16:9;
        (se vuoi estenderlo per 4:3 aggiungi un flag analogo).
    """
    idx, W, H = _find_numeric_scale(vf_parts)
    if idx < 0 or not W or not H:
        return  # niente da fare senza uno scale numerico

    # 1) forza aspect ratio decrease sullo scale
    sc = vf_parts[idx]
    if "force_original_aspect_ratio=" not in sc:
        sc = sc.rstrip()
        if not sc.endswith(":"):
            sc += ":"
        sc += "force_original_aspect_ratio=decrease"
    vf_parts[idx] = sc

    # 2) aggiungi pad per centrare nel canvas target
    pad = f"pad={W}:{H}:({W}-iw)/2:({H}-ih)/2"
    # inseriscilo SUBITO dopo quello scale
    vf_parts.insert(idx + 1, pad)

    # 3) per SD → SAR/DAR coerenti se richiesto
    if force_pal_auto and H in (576, 480, 486):
        if force_169:
            # es. PAL 16:9 flag
            vf_parts.append(f"setsar={PAL_SAR_16_9}")
            vf_parts.append("setdar=16/9")
        # se un domani volessi forzare 4:3, potresti usare:
        # else:
        #     vf_parts.append(f"setsar={PAL_SAR_4_3}")
        #     vf_parts.append("setdar=4/3")

    # 4) opzionale: “Forza 2.35:1” a livello di container (no stretch)
    #    Anche qui: manteniamo lo scale W:H e usiamo pad per arrivare a ~2.35
    if force_scope:
        target_ar = 2.35
        # aggiungi un secondo pad (dopo il primo) per rifinitura al 2.35
        # calcolo width/height finali mantenendo uno dei due (qui manteniamo H)
        # e allarghiamo con pad laterale.
        pad2 = f"pad=ceil({target_ar}*ih/2)*2:ih:(ow-iw)/2:0"
        vf_parts.insert(idx + 2, pad2)
