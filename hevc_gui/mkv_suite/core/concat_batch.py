#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple, Optional, Dict


# Riconoscimento stagione/episodio (S01E02, 1x02, Ep 02)
_RX_SEASON_EP = re.compile(
    r"(?i)\bS?(\d{1,2})[ ._\-]*E(\d{1,3})\b|\b(\d{1,2})x(\d{1,3})\b"
)
_RX_EP_ONLY = re.compile(r"(?i)\b(?:ep|episodio|episode)[ ._\-]*(\d{1,3})\b")

def natural_key(s: str):
    s = (s or "").strip().lower()
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", s)]

def detect_season_episode(text: str) -> Tuple[Optional[int], Optional[int]]:
    s = (text or "").strip()
    if not s:
        return None, None

    m = _RX_SEASON_EP.search(s)
    if m:
        g = m.groups()
        # pattern SxxEyy
        if g[0] and g[1]:
            try:
                return int(g[0]), int(g[1])
            except Exception:
                return None, None
        # pattern xxXyy
        if g[2] and g[3]:
            try:
                return int(g[2]), int(g[3])
            except Exception:
                return None, None

    m2 = _RX_EP_ONLY.search(s)
    if m2:
        try:
            return None, int(m2.group(1))
        except Exception:
            return None, None

    # fallback morbido: ultimo numero breve -> episodio
    nums = re.findall(r"\d{1,3}", s)
    if nums:
        try:
            v = int(nums[-1])
            if 0 < v < 1000:
                return None, v
        except Exception:
            pass

    return None, None

def detect_episode_index(text: str) -> Optional[int]:
    _, e = detect_season_episode(text)
    return e

@dataclass
class ConcatItem:
    path: Path
    file_name: str
    embedded_title: str = ""
    detected_season: Optional[int] = None
    detected_order: Optional[int] = None   # episodio
    duration_sec: Optional[float] = None
    signature: Tuple[Tuple[str, str], ...] = ()
    warning: str = ""
    manual_group: Optional[int] = None

    def sort_key(self):
        # stagione, episodio, poi filename naturale
        s = self.detected_season if self.detected_season is not None else 10**9
        e = self.detected_order if self.detected_order is not None else 10**9
        return (s, e, natural_key(self.file_name))

@dataclass
class ConcatGroup:
    index: int
    items: List[ConcatItem] = field(default_factory=list)
    out_name: str = ""
    status: str = ""
    manual_id: Optional[int] = None
    source_mode: str = "auto"  # auto | manual

    @property
    def count(self) -> int:
        return len(self.items)

    @property
    def seasons(self) -> List[int]:
        vals = [x.detected_season for x in self.items if x.detected_season is not None]
        return sorted(set(vals))

    @property
    def first_season(self) -> Optional[int]:
        ss = self.seasons
        return ss[0] if ss else None

    @property
    def single_season(self) -> bool:
        return len(self.seasons) == 1

    @property
    def first_order(self) -> Optional[int]:
        vals = [x.detected_order for x in self.items if x.detected_order is not None]
        return min(vals) if vals else None

    @property
    def last_order(self) -> Optional[int]:
        vals = [x.detected_order for x in self.items if x.detected_order is not None]
        return max(vals) if vals else None


def _safe_slug(s: str, maxlen: int = 220) -> str:
    s = (s or "").strip()
    # Solo caratteri vietati/fastidiosi per filename
    s = s.replace("/", "_").replace("\\", "_").replace(":", " - ")
    s = s.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    s = re.sub(r"\s+", " ", s).strip()
    # conserva [] perché li vuoi nel naming
    s = re.sub(r'[<>\"|?*]+', "", s)
    s = s.strip(" .")
    if not s:
        s = "concat"
    if len(s) > maxlen:
        s = s[:maxlen].rstrip(" .")
    return s


def _json_probe(mkvmerge_bin: str, path: Path) -> dict:
    cp = subprocess.run(
        [mkvmerge_bin, "-J", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if cp.returncode != 0:
        raise RuntimeError((cp.stderr or cp.stdout or "").strip() or f"mkvmerge -J rc={cp.returncode}")
    try:
        return json.loads(cp.stdout)
    except Exception as e:
        raise RuntimeError(f"JSON probe non valido per {path.name}: {e}")


def _norm_duration(v) -> Optional[float]:
    if v is None:
        return None
    try:
        x = float(v)
    except Exception:
        return None
    # mkvmerge spesso usa nanosecondi
    if x > 1_000_000:
        x = x / 1_000_000_000.0
    if x <= 0:
        return None
    return x


def _extract_title_and_sig(j: dict) -> tuple[str, Optional[float], Tuple[Tuple[str, str], ...]]:
    title = ""
    dur = None
    sig: List[Tuple[str, str]] = []

    try:
        c = (j.get("container") or {})
        p = (c.get("properties") or {})
        title = str(p.get("title") or "").strip()
        dur = _norm_duration(p.get("duration"))
    except Exception:
        pass

    try:
        for t in (j.get("tracks") or []):
            ttype = str(t.get("type") or "").strip().lower()
            props = t.get("properties") or {}
            codec = str(props.get("codec_id") or t.get("codec") or "").strip().upper()
            if not codec:
                codec = str(t.get("codec") or "").strip().upper()
            sig.append((ttype, codec))
            if dur is None:
                dur = _norm_duration(props.get("default_duration")) or dur
    except Exception:
        pass

    return title, dur, tuple(sig)


def probe_concat_item(path: Path, mkvmerge_bin: str) -> ConcatItem:
    path = Path(path).expanduser().resolve()
    if path.suffix.lower() != ".mkv":
        raise RuntimeError(f"Non è un MKV: {path.name}")

    j = _json_probe(mkvmerge_bin, path)
    title, dur, sig = _extract_title_and_sig(j)

    s, e = (None, None)
    if title:
        s, e = detect_season_episode(title)
    if e is None:
        s2, e2 = detect_season_episode(path.stem)
        if s is None:
            s = s2
        if e is None:
            e = e2

    return ConcatItem(
        path=path,
        file_name=path.name,
        embedded_title=title,
        detected_season=s,
        detected_order=e,
        duration_sec=dur,
        signature=sig,
        warning="",
        manual_group=None,
    )


def sort_items(items: List[ConcatItem]) -> List[ConcatItem]:
    return sorted(items, key=lambda x: x.sort_key())


def mark_compat(items: List[ConcatItem]) -> List[ConcatItem]:
    if not items:
        return items
    ref = items[0].signature
    out: List[ConcatItem] = []
    for i, it in enumerate(items):
        if i == 0:
            it.warning = ""
        else:
            it.warning = "" if it.signature == ref else "layout tracce diverso"
        out.append(it)
    return out


def auto_group_diagnostics(items: List[ConcatItem]) -> Dict[str, object]:
    """
    Diagnostica 'umana' per capire se l'automatico è affidabile.
    Non blocca per forza; serve per avvisi/consigli.
    """
    src = sort_items(list(items))
    episodes = [x.detected_order for x in src]
    seasons = [x.detected_season for x in src]

    missing_ep = [i+1 for i, v in enumerate(episodes) if v is None]
    present_ep = [v for v in episodes if v is not None]
    duplicates = sorted({v for v in present_ep if present_ep.count(v) > 1})

    # stagione: se alcune presenti e altre no -> incoerente "morbido"
    season_present = [s for s in seasons if s is not None]
    mixed_season_presence = (len(season_present) > 0 and len(season_present) != len(seasons))

    # continuità episodio (solo se tutti presenti)
    gaps = []
    if len(present_ep) == len(src) and present_ep:
        ordered = sorted(present_ep)
        for a, b in zip(ordered, ordered[1:]):
            if b != a + 1:
                gaps.append((a, b))

    ok = (len(missing_ep) == 0 and len(duplicates) == 0)

    messages: List[str] = []
    if missing_ep:
        messages.append("episodi mancanti/non letti")
    if duplicates:
        messages.append("episodi duplicati")
    if mixed_season_presence:
        messages.append("stagione presente solo su alcuni file")
    if gaps:
        messages.append("sequenza episodi non continua")

    return {
        "ok": ok,
        "missing_ep_rows": missing_ep,
        "duplicates": duplicates,
        "mixed_season_presence": mixed_season_presence,
        "gaps": gaps,
        "messages": messages,
    }


def format_group_output_name(prefix: str, g: ConcatGroup) -> str:
    prefix = _safe_slug(prefix or "serie")
    ep_a = g.first_order
    ep_b = g.last_order
    s = g.first_season if g.single_season else None

    if ep_a is not None and ep_b is not None:
        if ep_a == ep_b:
            ep_part = f"E{ep_a:02d}"
        else:
            ep_part = f"E{ep_a:02d}-{ep_b:02d}"

        if s is not None:
            return _safe_slug(f"{prefix} - S{s:02d} [{ep_part}].mkv")
        return _safe_slug(f"{prefix} - [{ep_part}].mkv")

    # fallback: se gruppo manuale esplicito usa [gruppo X]
    gid = g.manual_id if g.manual_id is not None else g.index
    return _safe_slug(f"{prefix} - [gruppo {gid}].mkv")


def _finalize_groups(groups: List[ConcatGroup], prefix: str) -> List[ConcatGroup]:
    for g in groups:
        g.out_name = format_group_output_name(prefix, g)
    return groups


def build_groups_auto(items: List[ConcatItem], group_size: int, prefix: str = "serie") -> List[ConcatGroup]:
    group_size = max(1, int(group_size))
    src = sort_items(list(items))
    src = mark_compat(src)

    groups: List[ConcatGroup] = []
    idx = 1
    for i in range(0, len(src), group_size):
        chunk = src[i:i+group_size]
        g = ConcatGroup(index=idx, items=chunk, source_mode="auto")
        groups.append(g)
        idx += 1
    return _finalize_groups(groups, prefix)


def build_groups_manual(items: List[ConcatItem], prefix: str = "serie") -> List[ConcatGroup]:
    """
    Crea gruppi in base a item.manual_group.
    Nessun automatismo di chunking.
    L'ordine dentro ai gruppi è l'ordine corrente della lista 'items'.
    """
    # preserva ordine lista corrente
    ordered = mark_compat(list(items))
    buckets: Dict[int, List[ConcatItem]] = {}
    group_order: List[int] = []

    for it in ordered:
        gid = it.manual_group
        if gid is None:
            continue
        try:
            gid = int(gid)
        except Exception:
            continue
        if gid <= 0:
            continue
        if gid not in buckets:
            buckets[gid] = []
            group_order.append(gid)
        buckets[gid].append(it)

    groups: List[ConcatGroup] = []
    for idx, gid in enumerate(group_order, start=1):
        groups.append(
            ConcatGroup(
                index=idx,
                items=buckets.get(gid, []),
                manual_id=gid,
                source_mode="manual",
            )
        )
    return _finalize_groups(groups, prefix)


# backward-compat (vecchio nome = automatico)
def build_groups(items: List[ConcatItem], group_size: int, prefix: str = "serie") -> List[ConcatGroup]:
    return build_groups_auto(items, group_size=group_size, prefix=prefix)


def build_append_cmd(mkvmerge_bin: str, out_path: Path, inputs: List[Path]) -> List[str]:
    if len(inputs) < 2:
        raise ValueError("Servono almeno 2 file per unire")
    cmd = [mkvmerge_bin, "-o", str(out_path)]
    first = True
    for p in inputs:
        p = Path(p)
        if first:
            cmd.append(str(p))
            first = False
        else:
            cmd.extend(["+", str(p)])
    return cmd


def fmt_duration(sec: Optional[float]) -> str:
    if sec is None:
        return ""
    try:
        s = int(round(float(sec)))
    except Exception:
        return ""
    h = s // 3600
    m = (s % 3600) // 60
    ss = s % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{ss:02d}"
    return f"{m:02d}:{ss:02d}"
