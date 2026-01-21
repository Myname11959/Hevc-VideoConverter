#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
from pathlib import Path
import subprocess
import shutil
import sys
import os

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "hevc_gui" / "resources"
I18N = RES / "i18n"

def _run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if p.stdout:
        print(p.stdout, end="" if p.stdout.endswith("\n") else "\n")
    if p.returncode != 0:
        raise SystemExit(f"ERRORE: comando fallito ({p.returncode})")

def _which(names: list[str]) -> str | None:
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None

def rebuild_qrc() -> None:
    qrc_files = sorted(RES.rglob("*.qrc")) if RES.exists() else []
    if not qrc_files:
        print("Nessun .qrc trovato sotto:", RES)
        return

    pyrcc = _which(["pyrcc5"])
    use_module = False
    if not pyrcc:
        # fallback: python -m PyQt5.pyrcc_main
        use_module = True
        pyrcc = sys.executable

    for qrc in qrc_files:
        out_py = qrc.with_name(qrc.stem + "_rc.py")
        if use_module:
            _run([pyrcc, "-m", "PyQt5.pyrcc_main", str(qrc), "-o", str(out_py)])
        else:
            _run([pyrcc, str(qrc), "-o", str(out_py)])

def rebuild_qm() -> None:
    lrelease = _which(["lrelease-qt5", "lrelease"])
    if not lrelease:
        raise SystemExit("Manca lrelease. Su Mint/Ubuntu: sudo apt install qttools5-dev-tools")

    for lang in ("it", "en"):
        ts = I18N / f"hevc_{lang}.ts"
        if not ts.exists():
            continue
        qm = I18N / f"hevc_{lang}.qm"
        _run([lrelease, str(ts), "-qm", str(qm)])

def main() -> None:
    os.chdir(ROOT)
    rebuild_qrc()
    rebuild_qm()
    print("\nOK: rigenerazione completata.")

if __name__ == "__main__":
    main()
