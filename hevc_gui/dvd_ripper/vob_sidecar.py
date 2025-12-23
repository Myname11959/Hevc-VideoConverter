#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

"""
vob_sidecar.py — genera sidecar accanto al .vob:

  • <basename>.ldvdmeta.json   → audio/sub “normalizzati”
  • <basename>.chapters_ogm.txt→ CHAPTERxx=… / CHAPTERxxNAME=…

Obiettivo importante per HEVC-GUI:
  - nel JSON l’attributo "index" per audio/sub DEVE essere 0..N-1
    (indice per-tipo usato con -map 0:a:<index> / -map 0:s:<index>)
  - l’indice globale ffprobe viene salvato come "stream_index".
"""

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import json
import os
import subprocess
import shutil

# srt_ocr è opzionale: se manca, l’OCR verrà semplicemente saltato.
try:
    from .srt_ocr import extract_srt_for_mkv  # type: ignore[attr-defined]
except Exception:
    try:
        from srt_ocr import extract_srt_for_mkv  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover
        extract_srt_for_mkv = None  # type: ignore[assignment]

StatusCb = Optional[Callable[[str], None]]

# ───────────────────────────── Lingue ─────────────────────────────

_LANG_MAP = {
    "eng": "en",
    "en": "en",
    "english": "en",
    "fra": "fr",
    "fre": "fr",
    "fr": "fr",
    "francais": "fr",
    "french": "fr",
    "ita": "it",
    "it": "it",
    "italiano": "it",
    "nld": "nl",
    "dut": "nl",
    "nl": "nl",
    "nederlands": "nl",
    "ell": "el",
    "el": "el",
    "greek": "el",
}


def _norm_lang(code: str) -> str:
    if not code:
        return "und"
    c = code.strip().lower()
    if c in _LANG_MAP:
        return _LANG_MAP[c]
    if len(c) >= 3 and c[:3] in _LANG_MAP:
        return _LANG_MAP[c[:3]]
    if len(c) >= 2 and c[:2] in _LANG_MAP:
        return _LANG_MAP[c[:2]]
    if len(c) >= 2:
        return c[:2]
    return c


def _norm_streamid(x: str) -> str:
    """
    Normalizza gli stream-id/codec_tag:

      "0x80" → "80"
      "80"   → "80"
      ""     → ""
    """
    s = str(x or "").strip().lower()
    if not s:
        return ""
    if s.startswith("0x"):
        s = s[2:]
    return s


# ───────────────────────────── Path helper ─────────────────────────────

def sidecar_path_for(vob_path: str | Path) -> Path:
    return Path(vob_path).with_suffix(".ldvdmeta.json")


def lsdvd_snapshot_path_for(vob_path: str | Path) -> Path:
    return Path(vob_path).with_suffix(".lsdvd.json")


def chapters_sidecar_path_for(vob_path: str | Path) -> Path:
    return Path(vob_path).with_suffix(".chapters_ogm.txt")


def chapters_ffmeta_path_for(vob_path: str | Path) -> Path:
    """
    File capitoli in formato ffmetadata per ffmpeg:
      -chapters <basename>.chapters_ffmeta.txt
    """
    return Path(vob_path).with_suffix(".chapters_ffmeta.txt")

# ───────────────────────────── Util ─────────────────────────────

def _status(cb: StatusCb, msg: str) -> None:
    if cb is None:
        return
    try:
        cb(msg)
    except Exception:
        pass


def _run_cmd(cmd: List[str]) -> str:
    """Esegue un comando e ritorna stdout come testo, oppure stringa vuota."""
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
        return out
    except Exception:
        return ""

def _time_to_ms(tc: str) -> int:
    """
    'HH:MM:SS.mmm' → millisecondi (int).
    """
    tc = (tc or "").strip()
    if not tc:
        return 0
    parts = tc.split(":")
    if len(parts) != 3:
        return 0
    try:
        h = int(parts[0])
        m = int(parts[1])
    except Exception:
        return 0
    sec_part = parts[2]
    if "." in sec_part:
        s_str, frac_str = sec_part.split(".", 1)
        try:
            s = int(s_str)
        except Exception:
            return 0
        frac_str = (frac_str + "000")[:3]
        try:
            ms = int(frac_str)
        except Exception:
            ms = 0
    else:
        try:
            s = int(sec_part)
        except Exception:
            return 0
        ms = 0
    total = ((h * 60 + m) * 60 + s) * 1000 + ms
    return max(0, total)


def _ogm_to_ffmetadata(ogm_text: str) -> str:
    """
    Converte un elenco capitoli OGM:

      CHAPTER01=00:00:00.000
      CHAPTER01NAME=Capitolo 1
      ...

    in un blocco ffmetadata per ffmpeg.
    """
    times = {}
    titles = {}

    for line in (ogm_text or "").splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        if key.startswith("CHAPTER") and key.endswith("NAME"):
            idx = key[len("CHAPTER") : -len("NAME")]
            try:
                i = int(idx)
            except Exception:
                continue
            titles[i] = val or f"Chapter {i:02d}"
        elif key.startswith("CHAPTER"):
            idx = key[len("CHAPTER") :]
            try:
                i = int(idx)
            except Exception:
                continue
            times[i] = _time_to_ms(val)

    if not times:
        return ";FFMETADATA1\n"

    indices = sorted(times.keys())
    starts = [times[i] for i in indices]

    # END = start del prossimo -1ms (per l’ultimo: start+1)
    ends = []
    for n, start in enumerate(starts):
        if n + 1 < len(starts):
            nxt = max(start + 1, starts[n + 1] - 1)
        else:
            nxt = start + 1
        ends.append(nxt)

    lines = [";FFMETADATA1", "", "; chapters generated from OGM", ""]
    for i, idx in enumerate(indices):
        start = max(0, int(starts[i]))
        end = max(start + 1, int(ends[i]))
        title = titles.get(idx) or f"Chapter {idx:02d}"
        title = title.replace("\n", " ").strip() or f"Chapter {idx:02d}"

        lines.append("[CHAPTER]")
        lines.append("TIMEBASE=1/1000")
        lines.append(f"START={start}")
        lines.append(f"END={end}")
        lines.append(f"title={title}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"

def _parse_ogm_chapters(text: str):
    """
    Parsea un file capitoli OGM (CHAPTERxx=..., CHAPTERxxNAME=...)
    e ritorna una lista [(start_ms, title), ...] ordinata per indice.
    """
    import re as _re

    times = {}
    titles = {}

    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        m = _re.match(r"CHAPTER(\d+)(NAME)?", key, flags=_re.IGNORECASE)
        if not m:
            continue
        idx = int(m.group(1))
        is_name = bool(m.group(2))
        if is_name:
            titles[idx] = val
        else:
            times[idx] = _time_to_ms(val)

    chapters = []
    for idx in sorted(times.keys()):
        start = times[idx]
        title = titles.get(idx) or f"Chapter {idx:02d}"
        chapters.append((start, title))
    return chapters


def _ogm_to_ffmetadata(text: str, movie_ms: int | None = None) -> str:
    """
    Converte il testo OGM in un blocco ffmetadata per ffmpeg.

    TIMEBASE fisso 1/1000, START/END in millisecondi.
    Se movie_ms non è noto, l'ultimo capitolo ha END = START+1.
    """
    chapters = _parse_ogm_chapters(text)
    if not chapters:
        return ""

    starts = [c[0] for c in chapters]
    ends: list[int] = []
    for i, start in enumerate(starts):
        if i + 1 < len(starts):
            nxt = max(start + 1, starts[i + 1] - 1)
        elif movie_ms and movie_ms > start:
            nxt = movie_ms - 1
        else:
            nxt = start + 1
        ends.append(nxt)

    lines: list[str] = []
    lines.append(";FFMETADATA1")
    lines.append("")
    lines.append("; chapters generated from OGM (.chapters_ogm.txt)")
    lines.append("")

    for i, (start, title) in enumerate(chapters):
        lines.append("[CHAPTER]")
        lines.append("TIMEBASE=1/1000")
        lines.append(f"START={max(0, int(start))}")
        lines.append(f"END={max(0, int(ends[i]))}")
        safe_title = (title or "").replace("\n", " ").strip() or f"Chapter {i + 1:02d}"
        lines.append(f"title={safe_title}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"

# ───────────────────────────── lsdvd ─────────────────────────────

def _load_lsdvd_snapshot(vob_path: Path) -> Dict[str, Any]:
    """
    Carica il JSON di lsdvd.

    Supporta sia:
      { "lsdvd": { ... } }
    sia:
      { "device": "...", "track": [...] }
    """
    snap_path = lsdvd_snapshot_path_for(vob_path)
    if not snap_path.is_file():
        return {}
    try:
        data = json.loads(snap_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    # Caso tipico: {"lsdvd": {...}}
    if isinstance(data, dict) and "lsdvd" in data and isinstance(data["lsdvd"], dict):
        return data["lsdvd"]

    # Caso “piatto”: già nel formato atteso
    if isinstance(data, dict):
        return data

    return {}


def _pick_main_track(lsdvd: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    tracks = lsdvd.get("track") or []
    if not tracks:
        return None
    longest = lsdvd.get("longest_track")
    if longest:
        for t in tracks:
            if t.get("ix") == longest:
                return t
    # Fallback: quello più lungo
    best = None
    best_len = -1.0
    for t in tracks:
        try:
            L = float(t.get("length") or 0.0)
        except Exception:
            L = 0.0
        if L > best_len:
            best_len = L
            best = t
    return best


# ───────────────────────────── ffprobe ─────────────────────────────

def _run_ffprobe(vob_path: Path, stream_spec: str) -> List[Dict[str, Any]]:
    """
    Ritorna i dizionari "stream" di ffprobe per audio ("a") o sub ("s").

    NOTA: l'index che arriva da ffprobe è l'indice GLOBALE.
          Noi lo salviamo in "stream_index" e poi riassegniamo "index" = 0..N-1
          solo nelle strutture lato sidecar.
    """
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", stream_spec,
        "-show_entries",
        (
            "stream=index,id,codec_name,codec_tag_string,channels,channel_layout,"
            "sample_rate,bit_rate,disposition:stream_tags=language,title"
        ),
        "-of", "json",
        str(vob_path),
    ]
    try:
        raw = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
    except Exception:
        return []

    try:
        data = json.loads(raw)
    except Exception:
        return []

    streams = data.get("streams") or []
    norm: List[Dict[str, Any]] = []

    for s in streams:
        # index globale in int
        try:
            idx = int(s.get("index") or 0)
        except Exception:
            idx = 0
        s["index"] = idx

        # normalizza id / codec_tag_string per il match con lsdvd (0x80 / 0x81 / 0x82…)
        sid = s.get("id")
        if isinstance(sid, str):
            s["id"] = sid.lower()
        else:
            try:
                s["id"] = f"0x{int(sid):x}".lower()
            except Exception:
                s["id"] = ""

        ctag = s.get("codec_tag_string") or ""
        s["codec_tag_string"] = str(ctag).lower()

        norm.append(s)

    # Manteniamo l'ordine di ffprobe per sicurezza
    norm.sort(key=lambda x: x.get("index", 0))
    return norm


# ───────────────────────────── Audio list ─────────────────────────────

def _build_audio_list(vob_path: Path, lsdvd: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Costruisce l'elenco audio:

      [
        {
          "index": 0,          # indice per-tipo (0..N-1) → -map 0:a:0 (ordine ffprobe)
          "stream_index": 2,   # indice globale ffprobe
          "stream_id": "0x82", # id DVD (se disponibile)
          "codec": "ac3",
          "channels": 6,
          "layout": "5.1(side)",
          "sample_rate": 48000,
          "bit_rate": 448000,
          "language": "it",
          "lang": "it",
          "name": "IT — AC3 5.1(SIDE)",
          "title": "...",
          "default": True/False,
        },
        ...
      ]

    REGOLA FONDAMENTALE:
      - l'ordine nel sidecar (index=0,1,2,...) segue SEMPRE ffprobe
        → quindi 0:a:0, 0:a:1, 0:a:2 corrispondono a quello che vedi in VLC.
      - lsdvd serve **solo** per etichette (lingua/canali), non per cambiare l'ordine.
    """
    ff_streams = _run_ffprobe(vob_path, "a")
    if not ff_streams:
        return []

    # Traccia principale da lsdvd
    main = _pick_main_track(lsdvd) if lsdvd else None
    lsdvd_audio = main.get("audio", []) if main else []

    # mappa streamid ("0x80" / "0x81" / "0x82") → entry lsdvd
    by_streamid: Dict[str, Dict[str, Any]] = {}
    for a in lsdvd_audio:
        sid = str(a.get("streamid") or "").lower()
        if sid:
            by_streamid[sid] = a

    used_lsdvd = set()
    items: List[Dict[str, Any]] = []

    for pos, s in enumerate(ff_streams):
        gl_idx = int(s.get("index") or 0)
        codec = (s.get("codec_name") or "").lower() or "unknown"
        codec_tag = (s.get("codec_tag_string") or "").lower()
        stream_id = (s.get("id") or "").lower()

        # proprietà base da ffprobe
        try:
            channels = int(s.get("channels") or 0)
        except Exception:
            channels = 0

        layout = (s.get("channel_layout") or "") or ""

        try:
            sr = int(s.get("sample_rate") or 0)
        except Exception:
            sr = 0

        try:
            br = int(s.get("bit_rate") or 0)
        except Exception:
            br = 0

        tags = s.get("tags") or {}
        lang_raw = (tags.get("language") or "").strip()
        lang = _norm_lang(lang_raw) if lang_raw else "und"
        title = tags.get("title") or ""

        # ------------------ Match con lsdvd ------------------
        lsd = None

        # 1) Match per stream_id (id) o codec_tag_string (es. "0x80", "0x81", "0x82")
        for cand in (stream_id, codec_tag):
            if not cand:
                continue
            key = str(cand).lower()
            if key in by_streamid:
                candidate = by_streamid[key]
                if id(candidate) not in used_lsdvd:
                    lsd = candidate
                    used_lsdvd.add(id(candidate))
                    break

        # 2) Se non trovato e abbiamo già una lingua da ffprobe, prova a matchare per lingua
        if lsd is None and lsdvd_audio and lang not in ("", "und"):
            for a in lsdvd_audio:
                if id(a) in used_lsdvd:
                    continue
                code = _norm_lang(a.get("langcode") or a.get("language") or "")
                if code == lang:
                    lsd = a
                    used_lsdvd.add(id(a))
                    break

        # 3) Ultimo fallback: posizione (pos) nella lista audio di lsdvd
        if lsd is None and lsdvd_audio and pos < len(lsdvd_audio):
            cand = lsdvd_audio[pos]
            if id(cand) not in used_lsdvd:
                lsd = cand
                used_lsdvd.add(id(cand))

        # Integra dati da lsdvd (ma NON cambiamo l'ordine ffprobe!)
        if lsd is not None:
            if channels <= 0:
                try:
                    channels = int(lsd.get("channels") or 0)
                except Exception:
                    pass
            if sr <= 0:
                try:
                    sr = int(lsd.get("frequency") or 0)
                except Exception:
                    pass
            if not lang or lang == "und":
                lang = _norm_lang(lsd.get("langcode") or lsd.get("language") or "")

        if not lang:
            lang = "und"

        # Etichetta codec + canali
        codec_label = codec.upper()
        if channels == 1:
            ch_desc = "MONO"
        elif channels == 2:
            ch_desc = "2.0"
        elif channels > 2:
            ch_desc = (layout or f"{channels}ch").upper()
        else:
            ch_desc = ""

        codec_desc = codec_label if not ch_desc else f"{codec_label} {ch_desc}"
        display_name = f"{lang.upper()} — {codec_desc}"

        items.append(
            {
                # ATTENZIONE: index = pos → 0,1,2… in ordine ffprobe
                "index": pos,                  # 0..N-1 → -map 0:a:<index>
                "stream_index": gl_idx,        # indice globale ffprobe
                "stream_id": stream_id or codec_tag,
                "codec": codec,
                "channels": channels,
                "layout": layout,
                "sample_rate": sr,
                "bit_rate": br,
                "language": lang,
                "lang": lang,
                "name": display_name,
                "title": title,
                "default": False,
            }
        )

    # ------------------ Scegliamo la traccia di default ------------------
    def _score(a: Dict[str, Any]) -> int:
        lang = a.get("language")
        ch = int(a.get("channels") or 0)
        score = 0
        if lang == "it":
            score += 100
        elif lang == "en":
            score += 80
        elif lang != "und":
            score += 60

        if ch > 2:
            score += 10
        elif ch == 2:
            score += 5

        return score

    if items:
        best = max(items, key=_score)
        for it in items:
            if it is best:
                it["default"] = True

    return items


# ──────────────────────── Sub list (con kind) ─────────────────────────

def _classify_sub_kind(lsd_entry: Optional[Dict[str, Any]], title: str) -> str:
    """
    Determina 'kind' del sottotitolo a partire da:

      - lsd_entry["content"]  (stringa da lsdvd: "Normal", "Hearing impaired", "Forced", …)
      - title                 (tag title di ffprobe, se presente)

    Ritorna uno tra: "normal", "forced", "sdh", "commentary", "karaoke".
    """
    chunks: List[str] = []
    if lsd_entry is not None:
        c = str(lsd_entry.get("content") or "").strip()
        if c:
            chunks.append(c)
    if title:
        chunks.append(str(title))

    s = " ".join(chunks).lower()
    if not s:
        return "normal"

    # Forced / only signs
    if "forced" in s or "only signs" in s or "signs only" in s:
        return "forced"

    # SDH / hearing impaired
    if "sdh" in s or "hearing" in s or "impaired" in s or "hoh" in s:
        return "sdh"

    # Commentari
    if "commentary" in s or "comment" in s:
        return "commentary"

    # Karaoke
    if "karaoke" in s:
        return "karaoke"

    return "normal"


def _build_subtitles_list(vob_path: Path, lsdvd: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Costruisce l'elenco sottotitoli:

      [
        {
          "index": 0,          # indice per-tipo (0..N-1) → -map 0:s:0
          "stream_index": 5,   # indice globale ffprobe
          "format": "vobsub",
          "language": "it",
          "lang": "it",
          "name": "IT — VobSub (SDH)",
          "kind": "sdh",
          "forced": False,
          "external_files": [],
          "title": "Hearing impaired",
          "stream_id": "0x20"
        },
        ...
      ]
    """
    ff_streams = _run_ffprobe(vob_path, "s")
    # Se ffprobe non vede nulla, proviamo comunque a usare solo lsdvd,
    # ma senza mappare stream_index in modo affidabile.
    main = _pick_main_track(lsdvd) if lsdvd else None
    lsd_subp = main.get("subp", []) if main else []

    if not ff_streams and not lsd_subp:
        return []

    # mappa streamid ("0x20", "0x21", ...) → entry lsdvd
    by_streamid: Dict[str, Dict[str, Any]] = {}
    for sp in lsd_subp:
        sid = str(sp.get("streamid") or "").lower()
        if sid:
            by_streamid[sid] = sp

    used_lsd = set()
    items: List[Dict[str, Any]] = []

    if ff_streams:
        # Caso "normale": abbiamo sia ffprobe che lsdvd → match completo
        for pos, s in enumerate(ff_streams):
            gl_idx = int(s.get("index") or 0)
            codec = (s.get("codec_name") or "").lower() or "vobsub"
            codec_tag = (s.get("codec_tag_string") or "").lower()
            stream_id = (s.get("id") or "").lower()

            tags = s.get("tags") or {}
            lang_raw = (tags.get("language") or "").strip()
            lang = _norm_lang(lang_raw) if lang_raw else "und"
            title = tags.get("title") or ""

            # -------- Match con lsdvd --------
            lsd = None

            # 1) stream_id / codec_tag_string (0x20 / 0x21 / ...)
            for cand in (stream_id, codec_tag):
                if not cand:
                    continue
                key = str(cand).lower()
                if key in by_streamid:
                    candidate = by_streamid[key]
                    if id(candidate) not in used_lsd:
                        lsd = candidate
                        used_lsd.add(id(candidate))
                        break

            # 2) match per lingua
            if lsd is None and lsd_subp and lang not in ("", "und"):
                for sp in lsd_subp:
                    if id(sp) in used_lsd:
                        continue
                    code = _norm_lang(sp.get("langcode") or sp.get("language") or "")
                    if code == lang:
                        lsd = sp
                        used_lsd.add(id(sp))
                        break

            # 3) fallback: posizione
            if lsd is None and lsd_subp and pos < len(lsd_subp):
                cand = lsd_subp[pos]
                if id(cand) not in used_lsd:
                    lsd = cand
                    used_lsd.add(id(cand))

            # integra lingua da lsdvd se ffprobe non l'ha messa
            if lsd is not None and (not lang or lang == "und"):
                lang = _norm_lang(lsd.get("langcode") or lsd.get("language") or "")

            if not lang:
                lang = "und"

            kind = _classify_sub_kind(lsd, title)
            forced = kind == "forced"

            base_name = f"{lang.upper()} — VobSub"
            if kind == "sdh":
                name = f"{base_name} (SDH)"
            elif kind == "forced":
                name = f"{base_name} (forced)"
            elif kind == "commentary":
                name = f"{base_name} (commentary)"
            else:
                name = base_name

            items.append(
                {
                    "index": pos,                 # 0..N-1 → -map 0:s:<index>
                    "stream_index": gl_idx,       # indice globale ffprobe
                    "format": codec or "vobsub",
                    "language": lang,
                    "lang": lang,
                    "name": name,
                    "kind": kind,
                    "forced": forced,
                    "external_files": [],
                    "title": title,
                    "stream_id": stream_id or codec_tag,
                }
            )
    else:
        # Caso estremo: ffprobe non vede i sub, ma lsdvd sì → sintetizziamo.
        for pos, sp in enumerate(lsd_subp):
            lang = _norm_lang(sp.get("langcode") or sp.get("language") or "")
            if not lang:
                lang = "und"
            content = sp.get("content") or ""
            # qui non abbiamo "title" da ffprobe → usiamo solo content
            kind = _classify_sub_kind(sp, "")
            forced = kind == "forced"

            base_name = f"{lang.upper()} — VobSub"
            if kind == "sdh":
                name = f"{base_name} (SDH)"
            elif kind == "forced":
                name = f"{base_name} (forced)"
            elif kind == "commentary":
                name = f"{base_name} (commentary)"
            else:
                name = base_name

            items.append(
                {
                    "index": pos,
                    "stream_index": pos,      # best-effort
                    "format": "vobsub",
                    "language": lang,
                    "lang": lang,
                    "name": name,
                    "kind": kind,
                    "forced": forced,
                    "external_files": [],
                    "title": str(content),
                    "stream_id": str(sp.get("streamid") or "").lower(),
                }
            )

    return items


# ───────────────────────────── Capitoli ─────────────────────────────

def write_chapters_sidecar(
    vob_path: str | Path,
    lsdvd: Dict[str, Any],
    status_cb: StatusCb = None,
) -> str:
    """
    Genera i capitoli e ritorna **il file ffmetadata** per ffmpeg.

    Passi:
      1) usa dvdxchap per ottenere il testo OGM (CHAPTERxx=…)
      2) lo salva in <base>.chapters_ogm.txt (solo temporaneo)
      3) converte in ffmetadata e salva <base>.chapters_ffmeta.txt
      4) elimina il file OGM
    """
    vob = Path(vob_path)
    ogm_path = chapters_sidecar_path_for(vob)
    ffm_path = chapters_ffmeta_path_for(vob)

    device = lsdvd.get("device") or os.environ.get("DVD_DEV") or "/dev/dvd"
    try:
        track = int(lsdvd.get("longest_track") or 1)
    except Exception:
        track = 1

    _status(status_cb, f"Capitoli: dvdxchap -t {track} {device}")
    cmd = ["dvdxchap", "-t", str(track), device]
    ogm_text = _run_cmd(cmd)
    if not ogm_text.strip():
        # Fallback minimo: 1 capitolo all'inizio
        ogm_text = "CHAPTER01=00:00:00.000\nCHAPTER01NAME=Chapter 1\n"

    # 1) scrivi comunque l'OGM (anche se poi lo elimineremo)
    try:
        ogm_path.write_text(ogm_text, encoding="utf-8")
    except Exception:
        pass

    # 2) genera ffmetadata
    ffm_text = _ogm_to_ffmetadata(ogm_text)
    try:
        ffm_path.write_text(ffm_text, encoding="utf-8")
        _status(status_cb, f"Capitoli: scritto ffmetadata ({ffm_path.name}).")
    except Exception:
        _status(status_cb, "Capitoli: impossibile scrivere ffmetadata.")
        # in caso di errore, teniamo almeno l'OGM e ritorniamo quello
        return str(ogm_path)

    # 3) elimina l'OGM: ormai ffmpeg lavora col ffmetadata
    try:
        ogm_path.unlink()
    except Exception:
        pass

    return str(ffm_path)

# ───────────────────────────── SRT hint ─────────────────────────────

def _build_srt_requests(
    subs: List[Dict[str, Any]],
    vob_path: Path,
    mode: str,
) -> List[Dict[str, Any]]:
    reqs: List[Dict[str, Any]] = []
    for s in subs:
        idx = int(s.get("index") or 0)
        lang = s.get("language") or "und"
        name = s.get("name") or lang.upper()
        target = str(vob_path.with_suffix(f".{lang}.srt"))
        reqs.append(
            {
                "index": idx,
                "language": lang,
                "name": name,
                "reason": mode,
                "target": target,
            }
        )
    return reqs


def _choose_srt_hint(
    subs: List[Dict[str, Any]],
    reqs: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not subs or not reqs:
        return None

    def _find_for(lang: str) -> Optional[Dict[str, Any]]:
        for r in reqs:
            if r.get("language") == lang:
                return r
        return None

    for pref in ("it", "en"):
        h = _find_for(pref)
        if h is not None:
            return h

    return reqs[0]

def _tmp_dir_for_ocr(vob: Path) -> Path:
    """
    Cartella tmp per l'OCR SRT.

    1) Prova …/dvdripper/.tmp/dvd_ripper (locale al progetto).
    2) Fallback: cartella del VOB.
    """
    try:
        pkg_dir = Path(__file__).resolve().parent
        proj_root = pkg_dir.parent
        tmp_dir = proj_root / ".tmp" / "dvd_ripper"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        return tmp_dir
    except Exception:
        return vob.parent


def _generate_srts_for_vob(
    vob: Path,
    subs: List[Dict[str, Any]],
    reqs: List[Dict[str, Any]],
    status_cb: StatusCb = None,
) -> List[str]:
    """
    Usa srt_ocr.extract_srt_for_mkv per creare i .srt richiesti accanto al VOB.

    Strategia:
      1) crea un MKV temporaneo solo-sottotitoli dal VOB;
      2) esegue l'OCR su quel MKV;
      3) ricopia/rinomina i .srt prodotti sui target indicati in reqs;
      4) ripulisce i temporanei.
    """
    def S(msg: str) -> None:
        _status(status_cb, msg)

    if not subs or not reqs:
        S("OCR SRT: nessun sottotitolo da convertire.")
        return []

    # Modulo OCR non disponibile → esci in silenzio “gentile”
    if extract_srt_for_mkv is None:
        S("OCR SRT non disponibile (manca modulo srt_ocr).")
        return []

    # mkvmerge è requisito minimo (mkvextract/vobsub2srt li verifica srt_ocr)
    if shutil.which("mkvmerge") is None:
        S('OCR SRT non disponibile (manca "mkvmerge" / mkvtoolnix).')
        return []

    tmp_dir = _tmp_dir_for_ocr(vob)
    base = vob.stem
    tmp_mkv = tmp_dir / f"{base}.ocrsubs.mkv"

    # Pulisci eventuale residuo
    try:
        tmp_mkv.unlink()
    except Exception:
        pass

    S(f"OCR SRT: preparo MKV temporaneo ({tmp_mkv.name})…")
    cmd = [
        "mkvmerge",
        "-o", str(tmp_mkv),
        "--no-audio",
        "--no-video",
        "--no-chapters",
        "--no-global-tags",
        "--no-track-tags",
        str(vob),
    ]
    try:
        r = subprocess.run(cmd, check=False)
        if r.returncode != 0 or (not tmp_mkv.is_file()):
            S("OCR SRT: mkvmerge fallito, salto l'OCR.")
            return []
    except FileNotFoundError:
        S('OCR SRT: mkvmerge non trovato. Installa "mkvtoolnix".')
        return []
    except Exception as e:
        S(f"OCR SRT: errore mkvmerge: {e}")
        return []

    # Esegui OCR tramite srt_ocr
    S("OCR SRT: avvio riconoscimento…")
    try:
        produced = extract_srt_for_mkv(  # type: ignore[misc]
            str(tmp_mkv),
            progress_cb=None,
            status_cb=lambda s: S(f"{s}"),
        ) or []
    except Exception as e:
        S(f"OCR SRT: errore durante l'OCR: {e}")
        produced = []

    # Mappa language → target desiderato (es. Film.it.srt)
    targets_by_lang: Dict[str, str] = {}
    for r in reqs:
        lang = _norm_lang(str(r.get("language") or "und"))
        target = r.get("target")
        if not target:
            continue
        if lang not in targets_by_lang:
            targets_by_lang[lang] = str(target)

    final_paths: List[str] = []
    used_targets = set()

    for spath in produced:
        p = Path(spath)
        if not p.is_file():
            continue

        # Nome tipico: "<base>.track<ID>.<lang>.srt"
        stem_no_ext = p.with_suffix("").name
        if "." in stem_no_ext:
            lang_tag = stem_no_ext.rsplit(".", 1)[-1]
        else:
            lang_tag = "und"
        lang_norm = _norm_lang(lang_tag)

        target = targets_by_lang.get(lang_norm)
        if not target or target in used_targets:
            continue

        try:
            tpath = Path(target)
            tpath.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            # se non riusciamo a creare la dir saltiamo
            continue

        try:
            data = p.read_bytes()
            tpath.write_bytes(data)
            final_paths.append(str(tpath))
            used_targets.add(target)
        except Exception:
            continue

    if final_paths:
        S(f"OCR SRT: creati {len(final_paths)} file SRT.")
    else:
        S("OCR SRT: nessun file SRT creato (vedi tool esterni / lingue).")

    # Pulizia: srt/idx/sub temporanei + MKV temporaneo
    try:
        for spath in produced:
            base_tmp = Path(spath).with_suffix("")
            for ext in (".srt", ".sub", ".idx"):
                try:
                    base_tmp.with_suffix(ext).unlink()
                except Exception:
                    pass
    except Exception:
        pass

    try:
        tmp_mkv.unlink()
    except Exception:
        pass

    return final_paths

# ───────────────────────────── API principali ─────────────────────────────

def postprocess_vob(
    vob_path: str | Path,
    status_cb: StatusCb = None,
    make_srt: bool = False,
    srt_mode: str = "all",
) -> Dict[str, Any]:
    """
    Analizza il VOB e genera:

      • <basename>.chapters_ogm.txt
      • <basename>.ldvdmeta.json

    Ritorna il dict del sidecar.

    Nota: NON esegue l'OCR. Qui prepariamo solo il "piano" SRT (srt_requests),
    che verrà poi usato da run_srt_ocr_for_vob().
    """
    vob = Path(vob_path)

    _status(status_cb, "Analisi DVD (lsdvd)…")
    lsdvd = _load_lsdvd_snapshot(vob)

    audio = _build_audio_list(vob, lsdvd)
    _status(status_cb, f"Tracce audio rilevate: {len(audio)}")

    subs = _build_subtitles_list(vob, lsdvd)
    _status(status_cb, f"Sottotitoli rilevati: {len(subs)}")

    chapters_file = write_chapters_sidecar(vob, lsdvd, status_cb=status_cb)

    # Se srt_mode != 'none' vogliamo comunque preparare il piano SRT
    want_srt = bool(make_srt) or (srt_mode not in ("none", "", None))

    meta: Dict[str, Any] = {
        "audio": audio,
        "subtitles": subs,
        "chapters_file": chapters_file,
        "srt_mode": srt_mode,
        "srt_requests": [],
        "want_srt": want_srt,
    }

    if want_srt and subs:
        reqs = _build_srt_requests(subs, vob, srt_mode)
        meta["srt_requests"] = reqs
        hint = _choose_srt_hint(subs, reqs)
        if hint is not None:
            meta["srt_hint"] = hint

    sc_path = sidecar_path_for(vob)
    try:
        sc_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

    _status(status_cb, f"Sidecar generato: {sc_path}")
    return meta

def load_sidecar(vob_path: str | Path) -> Dict[str, Any]:
    """
    Carica <basename>.ldvdmeta.json se esiste, altrimenti {}.
    """
    p = sidecar_path_for(vob_path)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def ffmpeg_args_from_sidecar(meta: Dict[str, Any]) -> Dict[str, Any]:
    """
    Helper generico (per remux futuri).

    Ritorna un dizionario con liste audio/sub che usano SEMPRE
    index 0..N-1 compatibili con -map 0:a:<idx> / -map 0:s:<idx>.
    """
    audio = meta.get("audio") or []
    subs = meta.get("subtitles") or []

    # Ordine audio consigliato: IT 5.1, IT 2.0, EN 5.1/2.0, altri
    def _prio(a: Dict[str, Any]) -> int:
        lang = a.get("language")
        ch = int(a.get("channels") or 0)
        if lang == "it" and ch > 2:
            return 0
        if lang == "it":
            return 1
        if lang == "en" and ch > 2:
            return 2
        if lang == "en":
            return 3
        return 4

    ordered_audio = sorted(audio, key=_prio)

    audio_maps = [
        {
            "map": f"0:a:{int(a.get('index') or 0)}",
            "lang": a.get("language") or "und",
            "name": a.get("name") or "",
            "default": bool(a.get("default")),
        }
        for a in ordered_audio
    ]

    sub_maps = [
        {
            "map": f"0:s:{int(s.get('index') or 0)}",
            "lang": s.get("language") or "und",
            "name": s.get("name") or "",
            "forced": bool(s.get("forced")),
        }
        for s in subs
    ]

    return {
        "audio": audio_maps,
        "subtitles": sub_maps,
        "chapters_file": meta.get("chapters_file"),
    }

# ───────────────────────────── OCR SRT a partire dal VOB ─────────────────────────────

def _project_tmp_dir() -> Path:
    """
    Directory temporanea locale al progetto, condivisa con i worker:

        …/dvd_ripper/.tmp/dvd_ripper
    """
    pkg_dir = Path(__file__).resolve().parent
    proj_root = pkg_dir.parent
    tmp_dir = proj_root / ".tmp" / "dvd_ripper"
    try:
        tmp_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return tmp_dir


def _build_ocr_mkv_for_vob(vob: Path, status_cb: StatusCb = None) -> Optional[Path]:
    """
    Crea un MKV temporaneo con SOLO i sottotitoli del VOB, da usare per l'OCR.
    Ritorna il path dell'MKV oppure None in caso di errore.
    """
    mkvmerge = shutil.which("mkvmerge")
    if not mkvmerge:
        _status(status_cb, 'OCR: "mkvmerge" non trovato; impossibile preparare l\'MKV temporaneo.')
        return None

    tmp_dir = _project_tmp_dir()
    out_mkv = tmp_dir / f"{vob.stem}.ocrsubs.mkv"

    cmd = [
        mkvmerge,
        "-o", str(out_mkv),
        "--no-audio",
        "--no-video",
        "--no-chapters",
        "--no-global-tags",
        "--no-track-tags",
        str(vob),
    ]

    _status(status_cb, "OCR: preparo MKV temporaneo dei sottotitoli…")
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    except Exception as e:
        _status(status_cb, f"OCR: errore eseguendo mkvmerge: {e}")
        return None

    if proc.returncode != 0 or (not out_mkv.is_file()):
        _status(status_cb, "OCR: mkvmerge ha restituito errore; nessun MKV temporaneo creato.")
        return None

    _status(status_cb, "OCR: MKV temporaneo pronto.")
    return out_mkv


def run_srt_ocr_for_vob(
    vob_path: str | Path,
    status_cb: StatusCb = None,
    srt_mode: Optional[str] = None,
) -> List[str]:
    """
    Esegue davvero l'OCR dei sottotitoli a partire da un VOB:

      1) Carica (o genera) il sidecar .ldvdmeta.json.
      2) Prepara la lista srt_requests (una per lingua) se mancante.
      3) Crea un MKV temporaneo con solo i sottotitoli.
      4) Usa srt_ocr.extract_srt_for_mkv() per produrre i .srt.
      5) Sposta e rinomina i .srt accanto al VOB secondo il piano srt_requests.
      6) Aggiorna il sidecar marcando le richieste soddisfatte con "generated": true.

    Ritorna la lista dei path .srt effettivamente presenti alla fine.
    """
    from pathlib import Path as _P

    vob = _P(vob_path).resolve()

    # 1) sidecar (se non c'è, lo creiamo al volo)
    meta = load_sidecar(vob)
    if not meta:
        _status(status_cb, "OCR: nessun sidecar trovato; lo genero al volo…")
        meta = postprocess_vob(vob, status_cb=status_cb, make_srt=False, srt_mode=srt_mode or "all")

    subs = meta.get("subtitles") or []
    if not subs:
        _status(status_cb, "OCR: nessun sottotitolo nel VOB; niente da fare.")
        return []

    mode = (srt_mode or meta.get("srt_mode") or "all") or "all"
    mode = str(mode).lower().strip()
    if mode == "none":
        _status(status_cb, "OCR: modalità SRT impostata su 'none'; salto.")
        return []

    # 2) piano SRT
    reqs: List[Dict[str, Any]] = meta.get("srt_requests") or _build_srt_requests(subs, vob, mode)
    meta["srt_requests"] = reqs
    hint = meta.get("srt_hint") or _choose_srt_hint(subs, reqs)
    if hint is not None:
        meta["srt_hint"] = hint
    meta["want_srt"] = True

    sc_path = sidecar_path_for(vob)
    try:
        sc_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

    # 3) controlla cosa esiste già
    pending: List[Dict[str, Any]] = []
    existing: List[str] = []
    for r in reqs:
        t = (r.get("target") or "").strip()
        if t and Path(t).is_file():
            existing.append(t)
            r["generated"] = True
        else:
            pending.append(r)
            r["generated"] = False

    if not pending:
        _status(status_cb, f"OCR: .srt già presenti ({len(existing)}); non rigenero.")
        try:
            sc_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
        seen: Dict[str, bool] = {}
        out_existing: List[str] = []
        for p in existing:
            if p not in seen:
                seen[p] = True
                out_existing.append(p)
        return out_existing

    _status(status_cb, f"OCR: preparo OCR per {len(pending)} tracce ({mode})…")

    # 4) MKV temporaneo
    mkv = _build_ocr_mkv_for_vob(vob, status_cb=status_cb)
    if not mkv:
        return []

    # 5) OCR vero e proprio
    try:
        try:
            from . import srt_ocr as _srt_ocr  # type: ignore[import]
        except Exception:
            import srt_ocr as _srt_ocr  # type: ignore[import]
    except Exception:
        _status(status_cb, "OCR: modulo srt_ocr non disponibile.")
        return []

    def _wrap_status(msg: str) -> None:
        _status(status_cb, msg)

    out_tmp = _srt_ocr.extract_srt_for_mkv(str(mkv), progress_cb=None, status_cb=_wrap_status)
    if not out_tmp:
        _status(status_cb, "OCR: nessun .srt ottenuto (controlla mkvextract/vobsub2srt).")
        return []

    # 6) sposta/rinomina i .srt in base al piano
    by_lang: Dict[str, List[Dict[str, Any]]] = {}
    for r in reqs:
        lang = (r.get("language") or "und")
        lang = _norm_lang(lang)
        by_lang.setdefault(lang, []).append(r)

    moved: List[str] = []
    base_no_ext = vob.with_suffix("")

    for src in out_tmp:
        src_path = Path(src)
        parts = src_path.name.split(".")
        if len(parts) >= 2:
            raw_lang = parts[-2].lower()
        else:
            raw_lang = "und"
        lang = _norm_lang(raw_lang)

        candidates = by_lang.get(lang) or []
        req = candidates[0] if candidates else None

        if req and (req.get("target") or "").strip():
            dest = Path(req["target"])  # type: ignore[path-type]
        else:
            dest = base_no_ext.with_suffix(f".{lang}.srt")

        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        try:
            if dest.exists():
                dest.unlink()
        except Exception:
            pass

        try:
            os.replace(str(src_path), str(dest))
            final_path = dest
        except Exception:
            # fallback: lascia il file dove sta
            final_path = src_path

        moved.append(str(final_path))
        if req is not None:
            req["target"] = str(final_path)
            req["generated"] = True

    # aggiorna il sidecar con i flag "generated"
    try:
        sc_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

    _status(status_cb, f"OCR: .srt generati: {len(moved)}")
    return moved
