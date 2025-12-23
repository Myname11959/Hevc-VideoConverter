#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, re
from typing import Iterable, List

_VOB_RX = re.compile(r"(?i)^VTS_(\d+)_([0-9]+)\.VOB$")

def natural_sort_vobs(paths: Iterable[str]) -> List[str]:
    def key(p: str):
        name = os.path.basename(p)
        m = _VOB_RX.match(name)
        if m:
            return (0, int(m.group(1)), int(m.group(2)))
        return (1, name.lower())
    return sorted(paths, key=key)

def total_bytes(paths: Iterable[str]) -> int:
    tot = 0
    for p in paths:
        try:
            tot += int(os.path.getsize(p))
        except Exception:
            pass
    return tot
