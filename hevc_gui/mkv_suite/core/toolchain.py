#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
from typing import List, Optional, Tuple


@dataclass
class Toolchain:
    mkvmerge: Optional[str]
    mkvextract: Optional[str]
    mkvpropedit: Optional[str]

    def missing(self) -> list[str]:
        out = []
        if not self.mkvmerge: out.append("mkvmerge")
        if not self.mkvextract: out.append("mkvextract")
        if not self.mkvpropedit: out.append("mkvpropedit")
        return out


class ToolError(RuntimeError):
    pass


def detect_toolchain() -> Toolchain:
    return Toolchain(
        mkvmerge=shutil.which("mkvmerge"),
        mkvextract=shutil.which("mkvextract"),
        mkvpropedit=shutil.which("mkvpropedit"),
    )


def run_cmd(cmd: List[str], timeout: int = 0) -> Tuple[int, str, str]:
    """
    Esegue un comando e ritorna (rc, stdout, stderr).
    timeout=0 => nessun timeout.
    """
    try:
        p = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            timeout=(timeout if timeout and timeout > 0 else None),
        )
        return p.returncode, (p.stdout or ""), (p.stderr or "")
    except Exception as e:
        raise ToolError(str(e))
