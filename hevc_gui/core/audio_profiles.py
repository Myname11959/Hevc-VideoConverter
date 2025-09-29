# hevc_gui/core/audio_profiles.py
# -*- coding: utf-8 -*-
"""
Profili audio per soundbar/TV + planner encode.
- Filtri 'soft' per stereo o downmix,
- Pianificazione codec/parametri quando si abilita davvero il 5.1.
"""

from __future__ import annotations
from typing import List, Dict, Any

# ---- Profili esposti in GUI ----
PROFILE_NONE = "Nessuno (default)"
PROFILE_SOUNDBAR_STD = "Soundbar standard"
PROFILE_SAMSUNG_HW_R450 = "Samsung TV J + HW-R450"
PROFILE_SAMSUNG_COMPLETO = "Samsung (completo)"

ALL_PROFILES = [
    PROFILE_NONE,
    PROFILE_SOUNDBAR_STD,
    PROFILE_SAMSUNG_HW_R450,
    PROFILE_SAMSUNG_COMPLETO,
]


# ---- Filtri 'soft' orientati a stereo (no pan se output multicanale) ----
def build_soundbar_filters(
    profile_name: str,
    *,
    input_channels_hint: int,
    output_channels: int,
) -> List[str]:
    """
    Filtri 'prudenziali' per soundbar.
    - Se output è stereo (output_channels==2) e input è 5.1 (input_channels_hint>=6),
      possiamo inserire un pan 5.1->stereo 'dialog-friendly'.
    - Se output è multicanale, NIENTE pan/downmix.
    """
    if profile_name not in ALL_PROFILES or profile_name == PROFILE_NONE:
        return []

    filters: List[str] = ["highpass=f=30"]  # taglia rumble leggero

    if output_channels == 2 and input_channels_hint >= 6:
        # downmix dolce verso stereo (dialoghi un filo centrali)
        filters.append("pan=stereo|FL=0.92*FL+0.70*FC+0.12*SL+0.08*LFE|FR=0.92*FR+0.70*FC+0.12*SR+0.08*LFE")

    # correzioni leggere per i profili
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

    # limiter soft a valle
    filters.append("alimiter=limit=1.0")
    return filters


# ---- Pianificazione encode reale (codec/layout/bitrate) ----
def plan_encode_for_profile(
    *,
    profile_name: str,
    detected_input_channels: int,
    multichannel_enabled: bool,
) -> Dict[str, Any]:
    """
    Decide codec/parametri di output.
    - Se multicanale non abilitato: resta stereo AAC (come oggi).
    - Se abilitato e traccia è >=6 canali e profilo è 'Samsung (completo)': AC-3 5.1.
    - Tutto il resto: resta stereo AAC.
    """
    # default: stereo AAC (invariato)
    plan = {
        "codec": "aac",
        "ext": ".m4a",
        "ar": None,  # None = lascia UI
        "ac": 2,
        "bitrate": None,  # lascia UI
        "extra_flags": [
            "-movflags",
            "+faststart",
            "-f",
            "ipod",
        ],  # come da comportamento attuale
    }

    if not multichannel_enabled:
        return plan

    if profile_name == PROFILE_SAMSUNG_COMPLETO and detected_input_channels >= 6:
        # Pianifica 5.1 reale per catena Samsung TV J + HW-R450 (alta compatibilità: AC-3)
        plan = {
            "codec": "ac3",
            "ext": ".ac3",
            "ar": 48000,
            "ac": 6,
            "bitrate": "640k",  # 448k/640k sono classici AC-3 5.1
            "extra_flags": [],  # niente -f ipod
        }
        return plan

    return plan
