# -*- coding: utf-8 -*-
"""
Profili audio per soundbar/TV + piano di encode.

- build_soundbar_filters(): restituisce i filtri audio da applicare (stereo/downmix).
- plan_encode_for_profile(): decide codec/layout/SR/bitrate in base al profilo.
- apply_export_overrides_from_plan(): applica il piano al comando ffmpeg (export).

Comportamenti chiave:
- Stereo (PROFILE_NONE): fallback bitrate 128k se la combo bitrate è vuota.
- Samsung Stereo (PROFILE_SAMSUNG_HW_R450): stereo 2.0 con crossfeed leggero, SR→48k SOLO se in GUI SR=Originale/Auto,
  fallback bitrate 192k se la combo bitrate è vuota; NON cambia il codec.
- Samsung 5.1 (PROFILE_SAMSUNG_COMPLETO): forzato AC-3 5.1 @48k (bitrate predef. 640k; cambiare a 448k se preferito).
"""

from __future__ import annotations
from typing import List, Dict, Any, Optional

# ---- Profili esposti in GUI ----
PROFILE_NONE = "Nessuno (default)"
PROFILE_SOUNDBAR_STD = "Soundbar standard"
PROFILE_SAMSUNG_HW_R450 = "Samsung TV J + HW-R450"      # Stereo ottimizzato (PCM 2.0)
PROFILE_SAMSUNG_COMPLETO = "Samsung (completo)"         # 5.1 AC-3

ALL_PROFILES = [
    PROFILE_NONE,
    PROFILE_SOUNDBAR_STD,
    PROFILE_SAMSUNG_HW_R450,
    PROFILE_SAMSUNG_COMPLETO,
]


# ----------------------------------------------------------------------
# Filtri 'soft' orientati a stereo (no pan se output multicanale)
# ----------------------------------------------------------------------
def build_soundbar_filters(
    profile_name: str,
    *,
    input_channels_hint: int,
    output_channels: int,
) -> List[str]:
    """
    Filtri 'prudenziali' per soundbar.

    Regole:
      - Se output è stereo (2 ch) e input è 5.1 (>=6 ch), applichiamo un downmix "dialog-friendly".
      - Se output è stereo (2 ch) e input è stereo (2 ch), per il profilo Samsung mettiamo un crossfeed leggero.
      - Se output è multicanale (>=5 ch), NON forziamo pan/downmix qui.
      - EQ/HPF leggeri per i profili soundbar.
      - Limiter soft in coda.
    """
    if profile_name not in ALL_PROFILES or profile_name == PROFILE_NONE:
        return []

    filters: List[str] = []

    # High-pass leggero (taglia rumble)
    filters.append("highpass=f=30")

    if output_channels == 2:
        if input_channels_hint >= 6:
            # Downmix 5.1 -> stereo con enfasi dialoghi
            filters.append(
                "pan=stereo|"
                "FL=0.92*FL+0.70*FC+0.12*SL+0.08*LFE|"
                "FR=0.92*FR+0.70*FC+0.12*SR+0.08*LFE"
            )
        elif input_channels_hint == 2 and profile_name == PROFILE_SAMSUNG_HW_R450:
            # Crossfeed leggero L↔R (Samsung stereo)
            filters.append("pan=stereo|c0=0.85*c0+0.15*c1|c1=0.15*c0+0.85*c1")

    # Correzioni leggere per i profili
    if profile_name == PROFILE_SOUNDBAR_STD:
        filters += [
            "equalizer=f=2000:t=q:w=1.0:g=1.5",
            "equalizer=f=8000:t=q:w=1.0:g=0.8",
        ]
    elif profile_name in (PROFILE_SAMSUNG_HW_R450, PROFILE_SAMSUNG_COMPLETO):
        filters += [
            "equalizer=f=1800:t=q:w=1.0:g=2.0",
            "equalizer=f=80:t=q:w=1.0:g=-1.0",
        ]

    # Limiter soft a valle (anti-clipping, parametri morbidi)
    filters.append("alimiter=limit=0.965:attack=12:release=300")
    return filters


# ----------------------------------------------------------------------
# Pianificazione encode reale (codec/layout/bitrate)
# ----------------------------------------------------------------------
def plan_encode_for_profile(
    *,
    profile_name: str,
    detected_input_channels: int,
    multichannel_enabled: bool,
) -> Dict[str, Any]:
    """
    Piano d'encode per profilo:

      - PROFILE_NONE:
          stereo (2.0); 'keep_codec'=True; 'bitrate_fallback'="128k".
      - PROFILE_SAMSUNG_HW_R450 (Stereo ottimizzato):
          stereo (2.0); 'keep_codec'=True; SR→48k SOLO se in GUI SR=Originale/Auto;
          'bitrate_fallback'="192k".
      - PROFILE_SAMSUNG_COMPLETO (5.1):
          se multicanale e input >=6ch → AC-3 5.1 @48k, bitrate "640k" (cambiare a "448k" se preferito).
          altrimenti come PROFILE_NONE.

    Campi speciali nel plan:
      - codec: None → NON toccare -c:a (mantieni quello impostato altrove).
      - ac, ar, bitrate: valori da imporre se presenti (altrimenti None = lascia GUI).
      - bitrate_fallback: usalo se la combo bitrate è vuota.
      - force_ar_if_gui_original: se la SR GUI è Originale/Auto, imposta questo AR.
      - keep_codec: True = NON cambiare -c:a (utile per Stereo).
    """
    # Base: stereo, non forzare codec/SR/bitrate (si occupa la GUI)
    plan: Dict[str, Any] = {
        "codec": None,
        "ac": 2,
        "ar": None,
        "bitrate": None,
        "bitrate_fallback": "128k",        # default fallback per Stereo neutro
        "force_ar_if_gui_original": None,  # per Samsung stereo -> 48000
        "keep_codec": True,
    }

    if profile_name == PROFILE_SAMSUNG_HW_R450:
        plan["bitrate_fallback"] = "192k"
        plan["force_ar_if_gui_original"] = 48000
        return plan

    if profile_name == PROFILE_SAMSUNG_COMPLETO and multichannel_enabled and detected_input_channels >= 6:
        return {
            "codec": "ac3",
            "ac": 6,
            "ar": 48000,
            "bitrate": "640k",             # cambia a "448k" se preferisci
            "bitrate_fallback": None,
            "force_ar_if_gui_original": None,
            "keep_codec": False,
        }

    # Soundbar standard o altri casi → piano base
    return plan


# ----------------------------------------------------------------------
# Applicazione del piano al comando ffmpeg (export)
# ----------------------------------------------------------------------
def apply_export_overrides_from_plan(
    cmd: List[str],
    plan: Dict[str, Any],
    *,
    gui_bitrate: Optional[str],  # "160k"/"192k"/"256k" oppure None se combo vuota
    gui_sr_hz: Optional[int],    # 44100/48000, oppure None se SR=Originale/Auto
) -> List[str]:
    """
    Applica il piano al cmd:

      - 5.1 AC-3 (keep_codec=False e codec=ac3):
          sostituisce -c:a/-ac/-ar/-b:a coi valori del plan.

      - Stereo (keep_codec=True):
          NON cambia -c:a;
          garantisce -ac 2;
          -ar: se gui_sr_hz è None e plan['force_ar_if_gui_original'] è impostato;
          -b:a: se assente, usa gui_bitrate o plan['bitrate'] o plan['bitrate_fallback'].
    """
    def _has_opt(lst: List[str], key: str) -> bool:
        try:
            lst.index(key)
            return True
        except ValueError:
            return False

    def _strip(lst: List[str], keys: tuple[str, ...]) -> List[str]:
        out: List[str] = []
        i = 0
        n = len(lst)
        while i < n:
            if lst[i] in keys and i + 1 < n:
                i += 2  # rimuove chiave + valore
            else:
                out.append(lst[i])
                i += 1
        return out

    # Caso 5.1 AC-3
    if not plan.get("keep_codec", True) and plan.get("codec") == "ac3":
        base = _strip(cmd, ("-c:a", "-ac", "-ar", "-b:a"))
        out = base + [
            "-c:a", "ac3",
            "-ac", str(plan.get("ac", 6)),
            "-ar", str(plan.get("ar", 48000)),
        ]
        br = plan.get("bitrate")
        if br:
            out += ["-b:a", br]
        return out

    # Stereo: NON toccare -c:a
    out = cmd[:]

    # -ac 2 garantito
    if not _has_opt(out, "-ac"):
        out += ["-ac", "2"]

    # -ar 48k SOLO se la GUI è su "Originale/Auto" e il plan lo richiede
    ar_if_orig = plan.get("force_ar_if_gui_original")
    if gui_sr_hz is None and ar_if_orig and not _has_opt(out, "-ar"):
        out += ["-ar", str(int(ar_if_orig))]

    # -b:a: se manca, usa GUI → altrimenti plan['bitrate'] → altrimenti plan['bitrate_fallback']
    if not _has_opt(out, "-b:a"):
        br = gui_bitrate or plan.get("bitrate") or plan.get("bitrate_fallback")
        if br:
            out += ["-b:a", br]

    return out
