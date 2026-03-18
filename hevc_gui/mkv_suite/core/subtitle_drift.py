from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable, List, Tuple


@dataclass(frozen=True)
class DriftPoint:
    time_ms: int
    offset_ms: int


def _clamp_non_negative(v: int) -> int:
    return max(0, int(v))


def _interp_offset(points: List[DriftPoint], x_ms: int) -> int:
    pts = sorted(points, key=lambda p: int(p.time_ms))
    if len(pts) < 2:
        raise ValueError("At least 2 drift points are required")
    if len(pts) > 3:
        pts = pts[:3]

    x = int(x_ms)

    if x <= pts[0].time_ms:
        return int(pts[0].offset_ms)

    if len(pts) == 2:
        a, b = pts
        if x >= b.time_ms:
            return int(b.offset_ms)
        return _lerp(a, b, x)

    a, b, c = pts
    if x <= b.time_ms:
        return _lerp(a, b, x)
    if x <= c.time_ms:
        return _lerp(b, c, x)
    return int(c.offset_ms)


def _lerp(a: DriftPoint, b: DriftPoint, x_ms: int) -> int:
    x = int(x_ms)
    x1 = int(a.time_ms)
    y1 = int(a.offset_ms)
    x2 = int(b.time_ms)
    y2 = int(b.offset_ms)

    if x2 == x1:
        return int(y2)
    t = (x - x1) / float(x2 - x1)
    return int(round(y1 + (y2 - y1) * t))


# ----------------------------------------------------------------------
# SRT
# ----------------------------------------------------------------------
_RX_SRT = re.compile(
    r'(?P<a>\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(?P<b>\d{2}:\d{2}:\d{2},\d{3})'
)

def _parse_srt_time(s: str) -> int:
    hh, mm, rest = s.split(":")
    ss, ms = rest.split(",")
    return (((int(hh) * 60 + int(mm)) * 60 + int(ss)) * 1000) + int(ms)

def _fmt_srt_time(ms: int) -> str:
    ms = _clamp_non_negative(ms)
    hh = ms // 3600000
    ms %= 3600000
    mm = ms // 60000
    ms %= 60000
    ss = ms // 1000
    ms %= 1000
    return f"{hh:02d}:{mm:02d}:{ss:02d},{ms:03d}"

def retime_srt_text(text: str, points: List[DriftPoint]) -> str:
    def repl(m):
        a0 = _parse_srt_time(m.group("a"))
        b0 = _parse_srt_time(m.group("b"))
        mid = int(round((a0 + b0) / 2.0))
        off = _interp_offset(points, mid)
        a1 = a0 + off
        b1 = b0 + off
        if b1 < a1:
            b1 = a1
        return f"{_fmt_srt_time(a1)} --> {_fmt_srt_time(b1)}"
    return _RX_SRT.sub(repl, text)


# ----------------------------------------------------------------------
# ASS / SSA
# ----------------------------------------------------------------------
_RX_ASS = re.compile(
    r'^(?P<head>\s*Dialogue:\s*[^,]*,)(?P<a>\d+:\d{2}:\d{2}\.\d{2}),(?P<b>\d+:\d{2}:\d{2}\.\d{2})(?P<tail>,.*)$',
    re.M
)

def _parse_ass_time(s: str) -> int:
    h, mm, rest = s.split(":")
    ss, cs = rest.split(".")
    return (((int(h) * 60 + int(mm)) * 60 + int(ss)) * 1000) + int(cs) * 10

def _fmt_ass_time(ms: int) -> str:
    ms = _clamp_non_negative(ms)
    h = ms // 3600000
    ms %= 3600000
    m = ms // 60000
    ms %= 60000
    s = ms // 1000
    ms %= 1000
    cs = int(round(ms / 10.0))
    if cs >= 100:
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

def retime_ass_text(text: str, points: List[DriftPoint]) -> str:
    def repl(m):
        a0 = _parse_ass_time(m.group("a"))
        b0 = _parse_ass_time(m.group("b"))
        mid = int(round((a0 + b0) / 2.0))
        off = _interp_offset(points, mid)
        a1 = a0 + off
        b1 = b0 + off
        if b1 < a1:
            b1 = a1
        return f"{m.group('head')}{_fmt_ass_time(a1)},{_fmt_ass_time(b1)}{m.group('tail')}"
    return _RX_ASS.sub(repl, text)


# ----------------------------------------------------------------------
# VTT
# ----------------------------------------------------------------------
_RX_VTT = re.compile(
    r'(?P<a>(?:\d{2}:)?\d{2}:\d{2}\.\d{3})\s*-->\s*(?P<b>(?:\d{2}:)?\d{2}:\d{2}\.\d{3})'
)

def _parse_vtt_time(s: str) -> int:
    parts = s.split(":")
    if len(parts) == 2:
        hh = 0
        mm, rest = parts
    else:
        hh, mm, rest = parts
    ss, ms = rest.split(".")
    return (((int(hh) * 60 + int(mm)) * 60 + int(ss)) * 1000) + int(ms)

def _fmt_vtt_time(ms: int) -> str:
    ms = _clamp_non_negative(ms)
    hh = ms // 3600000
    ms %= 3600000
    mm = ms // 60000
    ms %= 60000
    ss = ms // 1000
    ms %= 1000
    return f"{hh:02d}:{mm:02d}:{ss:02d}.{ms:03d}"

def retime_vtt_text(text: str, points: List[DriftPoint]) -> str:
    def repl(m):
        a0 = _parse_vtt_time(m.group("a"))
        b0 = _parse_vtt_time(m.group("b"))
        mid = int(round((a0 + b0) / 2.0))
        off = _interp_offset(points, mid)
        a1 = a0 + off
        b1 = b0 + off
        if b1 < a1:
            b1 = a1
        return f"{_fmt_vtt_time(a1)} --> {_fmt_vtt_time(b1)}"
    return _RX_VTT.sub(repl, text)


# ----------------------------------------------------------------------
# Generic file helpers
# ----------------------------------------------------------------------
def retime_subtitle_text(text: str, suffix: str, points: List[DriftPoint]) -> str:
    sfx = (suffix or "").lower()
    if sfx == ".srt":
        return retime_srt_text(text, points)
    if sfx in (".ass", ".ssa"):
        return retime_ass_text(text, points)
    if sfx == ".vtt":
        return retime_vtt_text(text, points)
    raise ValueError(f"Unsupported subtitle text format: {suffix}")


def retime_subtitle_file(src: Path, dst: Path, points: List[DriftPoint]) -> Path:
    suffix = src.suffix.lower()
    if suffix not in (".srt", ".ass", ".ssa", ".vtt"):
        raise ValueError(f"Unsupported subtitle text format: {suffix}")

    text = src.read_text(encoding="utf-8", errors="replace")
    out = retime_subtitle_text(text, suffix, points)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(out, encoding="utf-8")
    return dst
