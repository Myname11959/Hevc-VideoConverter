#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
P = ROOT / "hevc_gui" / "dvd_ripper" / "gui.py"

SINK_NAMES = {
    "addMenu", "addAction",
    "QMenu", "QAction",
    "setText", "setTitle", "setWindowTitle",
    "setToolTip", "setStatusTip", "setWhatsThis",
    "setPlaceholderText",
    "QCheckBox", "QPushButton", "QLabel", "QGroupBox",
}

TECH_PATTERNS = [
    re.compile(r"^:/"),                  # Qt resource paths
    re.compile(r"/"),                    # path-like
    re.compile(r"^\.[A-Za-z0-9]{2,5}$"), # extensions
    re.compile(r"^(Ctrl|Alt|Shift)\+"),  # shortcuts
    re.compile(r"^F\d+$"),               # function keys
    re.compile(r"^Esc$", re.I),
    re.compile(r"^--"),                  # CLI flags
]

def should_translate(s: str) -> bool:
    t = (s or "").strip()
    if not t or t in {"—", "…", "..."}:
        return False
    for pat in TECH_PATTERNS:
        if pat.search(t):
            return False
    if "ffmpeg" in t.lower():
        return False
    return any(ch.isalpha() for ch in t)

def ensure_import_L(src: str) -> str:
    if "from hevc_gui.i18n import L" in src:
        return src
    lines = src.splitlines(True)
    out: List[str] = []
    i = 0
    while i < len(lines) and (lines[i].startswith("#!") or "coding:" in lines[i]):
        out.append(lines[i]); i += 1
    if i < len(lines) and lines[i].lstrip().startswith(('"""', "'''")):
        q = lines[i].lstrip()[:3]
        out.append(lines[i]); i += 1
        while i < len(lines):
            out.append(lines[i])
            if q in lines[i]:
                i += 1
                break
            i += 1
    while i < len(lines) and lines[i].startswith("from __future__ import"):
        out.append(lines[i]); i += 1
    out.append("from hevc_gui.i18n import L\n\n")
    out.extend(lines[i:])
    return "".join(out)

@dataclass
class Edit:
    start: int
    end: int
    repl: str

def _line_starts(src: str) -> List[int]:
    starts = [0]
    acc = 0
    for ln in src.splitlines(True):
        acc += len(ln)
        starts.append(acc)
    return starts

def _abspos(starts: List[int], lineno: int, col: int) -> int:
    return starts[lineno - 1] + col

def _is_L_call(n: ast.AST) -> bool:
    return isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "L"

def _call_name(node: ast.Call) -> str:
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return ""

def _next_non_ws(src: str, pos: int) -> str:
    i = pos
    n = len(src)
    while i < n:
        ch = src[i]
        if ch in " \t\r\n":
            i += 1
            continue
        return ch
    return ""

def main() -> int:
    apply = "--apply" in sys.argv
    bdir = None
    if "--backup-dir" in sys.argv:
        i = sys.argv.index("--backup-dir")
        bdir = Path(sys.argv[i+1])
    backup_dir = bdir or Path("/tmp/i18n_ldvd_gui_sinks_v2_bak")

    src0 = P.read_text(encoding="utf-8", errors="replace")
    src = ensure_import_L(src0)

    tree = ast.parse(src)
    starts = _line_starts(src)
    edits: List[Edit] = []

    class V(ast.NodeVisitor):
        def visit_Call(self, node: ast.Call):
            name = _call_name(node)
            if name in SINK_NAMES:
                for arg in node.args:
                    if _is_L_call(arg):
                        continue
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        if not should_translate(arg.value):
                            continue
                        seg = ast.get_source_segment(src, arg)
                        if not seg:
                            continue
                        s = _abspos(starts, arg.lineno, arg.col_offset)
                        e = _abspos(starts, arg.end_lineno, arg.end_col_offset)
                        # SAFETY: wrappa solo se dopo la stringa c'è un delimitatore valido
                        nxt = _next_non_ws(src, e)
                        if nxt not in {",", ")", "]", "}"}:
                            continue
                        edits.append(Edit(s, e, f"L({seg})"))

                for kw in node.keywords:
                    if kw.value is None or _is_L_call(kw.value):
                        continue
                    v = kw.value
                    if isinstance(v, ast.Constant) and isinstance(v.value, str):
                        if not should_translate(v.value):
                            continue
                        seg = ast.get_source_segment(src, v)
                        if not seg:
                            continue
                        s = _abspos(starts, v.lineno, v.col_offset)
                        e = _abspos(starts, v.end_lineno, v.end_col_offset)
                        nxt = _next_non_ws(src, e)
                        if nxt not in {",", ")", "]", "}"}:
                            continue
                        edits.append(Edit(s, e, f"L({seg})"))
            self.generic_visit(node)

    V().visit(tree)

    if not edits and src == src0:
        print(f"[OK] nochange {P}")
        return 0

    out = src
    for ed in sorted(edits, key=lambda x: (x.start, x.end), reverse=True):
        out = out[:ed.start] + ed.repl + out[ed.end:]

    if out == src0:
        print(f"[OK] nochange {P}")
        return 0

    if apply:
        backup_dir.mkdir(parents=True, exist_ok=True)
        (backup_dir / P.as_posix().replace("/", "__")).write_text(src0, encoding="utf-8")
        P.write_text(out, encoding="utf-8")
        print(f"[CHANGED] {P} edits={len(edits)}")
        import py_compile
        py_compile.compile(str(P), doraise=True)
        print("[OK] py_compile gui.py")
    else:
        print(f"[WOULD_CHANGE] {P} edits={len(edits)}")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
