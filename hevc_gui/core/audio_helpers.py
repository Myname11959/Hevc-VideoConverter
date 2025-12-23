#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audio_helpers.py — utility per tracce audio

Funzione principale:
- audio_tracks_with_title(file_path) → List[(index, label)]
  • usa ffprobe per trovare le tracce audio;
  • se disponibile, prova a usare il sidecar LDVD (<basename>.ldvdmeta.json)
    per avere lingua/nome/codec/canali/bitrate più “reali”;
  • restituisce comunque solo (index, stringa_label) per compatibilità
    con il resto della GUI (es. String Audio Generator).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import List, Tuple, Any


def _ldvd_sidecar_path_for(path: Path | str) -> Path:
    """
    /percorso/FILE.ext → /percorso/FILE.ldvdmeta.json
    """
    base = Path(path)
    return base.with_suffix(".ldvdmeta.json")


def _load_ldvd_sidecar(path: Path | str) -> dict | None:
    """
    Prova a caricare il sidecar LDVD (<basename>.ldvdmeta.json).
    Restituisce il dict oppure None se assente/non valido.
    """
    side = _ldvd_sidecar_path_for(path)
    try:
        if side.is_file():
            txt = side.read_text(encoding="utf-8")
            data = json.loads(txt)
            print(f"[AUDIO] Sidecar LDVD rilevato: {side}", flush=True)
            return data
    except Exception as e:
        print(f"[AUDIO] Errore lettura sidecar {side}: {e}", flush=True)
    return None


def _get(obj: Any, key: str, default=None):
    """
    Accesso robusto sia a dict che a oggetti con attributi.
    """
    try:
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key)
    except Exception:
        return default


def _norm_lang(lang: str | None) -> str:
    """
    Normalizza un codice lingua in qualcosa di “sensato”:
    - tutto lowercase
    - se vuoto → 'und'
    - mapping base per ita/eng/fra/deu/spa
    """
    if not lang:
        return "und"
    s = str(lang).strip().lower()
    if not s:
        return "und"

    if len(s) == 3:
        return s

    if s in {"it", "ita", "italian", "italiano"}:
        return "ita"
    if s in {"en", "eng", "english"}:
        return "eng"
    if s in {"fr", "fra", "fre", "french", "francais", "français"}:
        return "fra"
    if s in {"de", "ger", "deu", "german", "deutsch"}:
        return "deu"
    if s in {"es", "spa", "spanish", "español"}:
        return "spa"

    # se è tipo 'ita (Italiano)' → prendi la prima parola
    if " " in s or "(" in s:
        s = s.replace("(", " ").split()[0].strip()

    if len(s) == 2:
        if s == "it":
            return "ita"
        if s == "en":
            return "eng"
        if s == "fr":
            return "fra"
        if s == "de":
            return "deu"
        if s == "es":
            return "spa"

    return s or "und"


def _match_sidecar_audio(sidecar: dict | None) -> dict[int, dict]:
    """
    Costruisce una mappa index → meta_audio dal sidecar, se presente.
    Accetta campi tipo:
      audio: [
        {
          "index": 0,
          "stream_index": 0,
          "language": "ita",
          "name": "Italiano 5.1 (AC3 448)",
          "codec": "ac3",
          "channels": 6,
          "layout": "5.1(side)",
          "bitrate": 448000,
          "default": true
        }, ...
      ]
    """
    if not isinstance(sidecar, dict):
        return {}

    audio_list = _get(sidecar, "audio", []) or []
    by_idx: dict[int, dict] = {}

    for entry in audio_list:
        idx = _get(entry, "index", None)
        if idx is None:
            idx = _get(entry, "stream_index", None)
        try:
            idx = int(idx)
        except Exception:
            continue
        by_idx[idx] = entry

    return by_idx


def audio_tracks_with_title(file_path: str) -> List[Tuple[int, str]]:
    """
    Ritorna una lista di (index, label) per ogni traccia audio.

    - Se ffprobe fallisce → lista vuota.
    - Se esiste sidecar LDVD → i label cercano di riflettere lingua/codec/canali/bitrate
      presi dal sidecar; altrimenti usano i tag di ffprobe.
    """
    src = str(file_path)

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a",
        "-show_entries",
        "stream=index,codec_name,channels,channel_layout,bit_rate:stream_tags=language,title",
        "-of",
        "json",
        src,
    ]

    try:
        out = subprocess.check_output(cmd, text=True)
    except subprocess.CalledProcessError as e:
        # ffprobe ha restituito un errore (file corrotto o senza tracce audio)
        print(f"[AUDIO] ffprobe error: {e}", flush=True)
        return []

    try:
        info = json.loads(out)
    except json.JSONDecodeError as e:
        # Output non JSON valido
        print(f"[AUDIO] JSON decode error: {e}", flush=True)
        return []

    streams = info.get("streams", []) or []

    # Prova a caricare il sidecar LDVD per metadata più affidabili
    sidecar = _load_ldvd_sidecar(src)
    side_audio_map = _match_sidecar_audio(sidecar)

    tracks: List[Tuple[int, str]] = []

    for s in streams:
        idx = s.get("index", 0)
        try:
            idx_int = int(idx)
        except Exception:
            idx_int = 0

        tags = s.get("tags", {}) or {}
        ff_lang = tags.get("language", "") or ""
        ff_title = tags.get("title", "") or ""

        codec = s.get("codec_name") or ""
        channels = s.get("channels") or None
        layout = s.get("channel_layout") or ""
        bitrate_raw = s.get("bit_rate") or ""

        # Default da ffprobe
        lang = _norm_lang(ff_lang)
        name = ff_title
        br_kbps = None
        try:
            if bitrate_raw:
                br_kbps = int(bitrate_raw) // 1000
        except Exception:
            br_kbps = None

        # Se il sidecar conosce questa traccia, sovrascrivi con i suoi dati
        side_entry = side_audio_map.get(idx_int)
        if side_entry:
            sl = _norm_lang(_get(side_entry, "language", "") or lang)
            if sl:
                lang = sl

            s_name = _get(side_entry, "name", "") or ""
            if s_name:
                name = s_name

            scodec = _get(side_entry, "codec", "") or _get(side_entry, "codec_name", "") or ""
            if scodec:
                codec = scodec

            sch = _get(side_entry, "channels", None)
            try:
                if sch is not None:
                    channels = int(sch)
            except Exception:
                pass

            slayout = _get(side_entry, "layout", "") or _get(side_entry, "channel_layout", "") or ""
            if slayout:
                layout = slayout

            sbitrate = _get(side_entry, "bitrate", None)
            try:
                if sbitrate:
                    br_kbps = int(sbitrate) // 1000
            except Exception:
                pass

        # Costruzione etichetta
        pieces: list[str] = []

        # prefisso "#0 [ita] ..."
        pieces.append(f"#{idx_int}")
        if lang and lang != "und":
            pieces.append(f"[{lang}]")

        # codec / canali
        codec_part = ""
        if codec:
            codec_part = codec.upper()
        if channels:
            if layout:
                codec_part = f"{codec_part} {layout}" if codec_part else layout
            else:
                codec_part = f"{codec_part} {channels}ch" if codec_part else f"{channels}ch"
        if codec_part:
            pieces.append(codec_part.strip())

        # bitrate
        if br_kbps:
            pieces.append(f"{br_kbps} kb/s")

        # nome “umano”
        if name:
            # separatore “—” per leggibilità
            pieces.append(f"— {name}")

        label = " ".join(str(p) for p in pieces if str(p).strip())

        # fallback nel caso fosse finito tutto vuoto
        if not label:
            label = f"#{idx_int}"

        tracks.append((idx_int, label))

    return tracks
