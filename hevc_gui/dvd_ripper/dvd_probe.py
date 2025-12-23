#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import os
import re
import subprocess
from pathlib import Path
from typing import Optional


def _run(cmd: list[str]) -> tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except Exception as e:
        return 127, "", str(e)


def get_dvd_device() -> str:
    # preferisci /dev/sr0, altrimenti /dev/cdrom, fallback /dev/sr0
    for d in ("/dev/sr0", "/dev/cdrom", "/dev/dvd"):
        try:
            if os.path.exists(d):
                return d
        except Exception:
            pass
    return "/dev/sr0"


def get_cdrom_mount_point() -> Optional[str]:
    dev = get_dvd_device()

    # 1) findmnt
    rc, out, _ = _run(["findmnt", "-n", "-S", dev, "-o", "TARGET"])
    if rc == 0 and out:
        return out

    # 2) /proc/mounts
    try:
        with open("/proc/mounts", "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                parts = line.split()
                if parts and parts[0] == dev and len(parts) >= 2:
                    return parts[1]
    except Exception:
        pass

    # 3) euristica su /media e /run/media
    user = os.environ.get("USER") or os.environ.get("USERNAME") or ""
    bases = []
    if user:
        bases += [f"/media/{user}", f"/run/media/{user}"]
    bases += ["/media", "/run/media"]
    for base in bases:
        p = Path(base)
        if not p.is_dir():
            continue
        for e in p.iterdir():
            if e.is_dir():
                # preferisci cartella che contenga VIDEO_TS
                try:
                    if (e / "VIDEO_TS").is_dir():
                        return str(e)
                    for ch in e.iterdir():
                        if ch.is_dir() and ch.name.upper().startswith("VIDEO_TS"):
                            return str(e)
                except Exception:
                    pass

    return None


def get_dvd_title() -> Optional[str]:
    """
    Ritorna la label del disco (se disponibile):
    - lsblk -no LABEL /dev/sr0
    - blkid -o value -s LABEL /dev/sr0
    - nome cartella del mount
    """
    dev = get_dvd_device()
    for cmd in (["lsblk", "-no", "LABEL", dev], ["blkid", "-o", "value", "-s", "LABEL", dev]):
        rc, out, _ = _run(cmd)
        if rc == 0 and out:
            return out.strip()

    mp = get_cdrom_mount_point()
    if mp:
        try:
            return Path(mp).name
        except Exception:
            pass
    return None


def suggest_movie_title(lang: str = "it") -> Optional[str]:
    t = get_dvd_title() or ""
    t = t.replace("_", " ")
    # capitalizzazione leggera (il controller applica comunque title_case)
    t = re.sub(r"\s+", " ", t).strip(" \t\r\n.-_")
    return t or None


def open_tray() -> bool:
    rc, _, _ = _run(["eject", get_dvd_device()])
    return rc == 0


def close_tray() -> bool:
    rc, _, _ = _run(["eject", "-t", get_dvd_device()])
    return rc == 0
