#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
P = ROOT / "hevc_gui" / "dvd_ripper" / "gui.py"

TARGET_LITERALS = [
    "&Azioni",
    "&Visualizza",
    "&Aiuto",
    "&File",
    "Genera SRT",
    "Titolo DVD:",
    "Titolo film:",
]

def ensure_import_L(src: str) -> str:
    if "from hevc_gui.i18n import L" in src:
        return src

    lines = src.splitlines(True)
    out = []
    i = 0

    # shebang/encoding
    while i < len(lines) and (lines[i].startswith("#!") or "coding:" in lines[i]):
        out.append(lines[i]); i += 1

    # docstring iniziale (se c'è)
    if i < len(lines) and lines[i].lstrip().startswith(('"""', "'''")):
        q = lines[i].lstrip()[:3]
        out.append(lines[i]); i += 1
        while i < len(lines):
            out.append(lines[i])
            if q in lines[i]:
                i += 1
                break
            i += 1

    # future imports
    while i < len(lines) and lines[i].startswith("from __future__ import"):
        out.append(lines[i]); i += 1

    out.append("from hevc_gui.i18n import L\n\n")
    out.extend(lines[i:])
    return "".join(out)

def wrap_calls(src: str) -> tuple[str, int]:
    """
    Wrappa SOLO argomenti stringa esatti (TARGET_LITERALS) in chiamate tipiche UI:
      addMenu("..."), setTitle("..."), QMenu("..."), setText("..."), QCheckBox("...")
    Non tocca f-string, non tocca altro.
    """
    count = 0

    # helper: sostituisce "literal" -> L("literal") se non già L(...)
    def repl_literal(m: re.Match) -> str:
        nonlocal count
        before = m.group(1)  # prefix fino a '(' incluso
        quote = m.group(2)
        text  = m.group(3)
        after = m.group(4)  # resto
        # già L("...")?
        if before.rstrip().endswith("L("):
            return m.group(0)
        count += 1
        return f"{before}L({quote}{text}{quote}){after}"

    # pattern per catturare: PREFIX ( "TEXT" )  dove PREFIX include la '('
    # Esempi:
    #   menubar.addMenu("&Azioni")
    #   QMenu("&File", self)
    #   lbl.setText("Titolo DVD:")
    #   cb = QCheckBox("Genera SRT")
    call_prefixes = [
        r"\.addMenu\(",
        r"\.setTitle\(",
        r"\.setText\(",
        r"\.setToolTip\(",
        r"\.setStatusTip\(",
        r"\.setWindowTitle\(",
        r"\bQMenu\(",
        r"\bQCheckBox\(",
        r"\bQAction\(",
    ]
    prefix_re = "(?:" + "|".join(call_prefixes) + ")"

    for lit in TARGET_LITERALS:
        # match: PREFIX ( "lit"  oppure PREFIX ( 'lit'
        pat = re.compile(rf"({prefix_re}\s*)(['\"])({re.escape(lit)})\2(\s*[,\)])")
        src = pat.sub(repl_literal, src)

    return src, count

def main() -> int:
    apply = "--apply" in sys.argv
    bdir = None
    if "--backup-dir" in sys.argv:
        i = sys.argv.index("--backup-dir")
        bdir = Path(sys.argv[i+1])
    backup_dir = bdir or Path("/tmp/i18n_ldvd_ui_patch_bak")

    src0 = P.read_text(encoding="utf-8", errors="replace")
    src = ensure_import_L(src0)
    src2, n = wrap_calls(src)

    if src2 == src0:
        print(f"[OK] nochange {P}")
        return 0

    if apply:
        backup_dir.mkdir(parents=True, exist_ok=True)
        (backup_dir / P.as_posix().replace("/", "__")).write_text(src0, encoding="utf-8")
        P.write_text(src2, encoding="utf-8")
        print(f"[CHANGED] {P} wrapped={n}")
        # compile check
        import py_compile
        py_compile.compile(str(P), doraise=True)
        print("[OK] py_compile gui.py")
    else:
        print(f"[WOULD_CHANGE] {P} wrapped={n}")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
