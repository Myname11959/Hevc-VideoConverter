#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [
    ROOT / "hevc_gui" / "dvd_ripper" / "controller.py",
    ROOT / "hevc_gui" / "dvd_ripper" / "gui.py",
]

# ── utilities ────────────────────────────────────────────────────────────────
def ensure_import_L_after_future(src: str) -> str:
    lines = src.splitlines(True)
    # remove existing import L
    lines = [ln for ln in lines if ln.strip() != "from hevc_gui.i18n import L"]

    # find insertion point: after last __future__ import
    fut = [i for i, ln in enumerate(lines) if ln.startswith("from __future__ import")]
    if fut:
        ins = fut[-1] + 1
    else:
        ins = 0
        # shebang/encoding
        while ins < len(lines) and (lines[ins].startswith("#!") or "coding:" in lines[ins]):
            ins += 1
        # docstring
        if ins < len(lines) and lines[ins].lstrip().startswith(('"""', "'''")):
            q = lines[ins].lstrip()[:3]
            ins += 1
            while ins < len(lines):
                if q in lines[ins]:
                    ins += 1
                    break
                ins += 1

    lines.insert(ins, "from hevc_gui.i18n import L\n")
    if ins + 1 < len(lines) and lines[ins + 1].strip() != "":
        lines.insert(ins + 1, "\n")
    return "".join(lines)

_str_lit = re.compile(r"""^(?P<prefix>[rubRUBfF]*) (?P<q>['"])(?P<body>(?:\\.|(?!\2).)*)\2$""", re.X | re.S)

def is_plain_string_literal(s: str) -> bool:
    s = s.strip()
    m = _str_lit.match(s)
    if not m:
        return False
    # escludi f-string qui (le lasciamo stare per non rischiare)
    return "f" not in (m.group("prefix") or "").lower()

def wrap_lit(s: str) -> str:
    s = s.strip()
    if s.startswith("L("):
        return s
    return f"L({s})"

# ── patch QMessageBox calls (balanced-parens) ────────────────────────────────
QMB_PREFIX_RE = re.compile(r"QMessageBox\.(information|warning|critical|question)\s*\(")

def _find_call_end(src: str, open_paren: int) -> int | None:
    depth = 1
    i = open_paren + 1
    in_str = False
    q = ""
    esc = False
    while i < len(src):
        ch = src[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == q:
                in_str = False
        else:
            if ch in ("'", '"'):
                in_str = True
                q = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return None

def _split_args(argstr: str) -> List[str]:
    args = []
    cur = []
    depth = 0
    in_str = False
    q = ""
    esc = False
    for ch in argstr:
        if in_str:
            cur.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == q:
                in_str = False
            continue
        if ch in ("'", '"'):
            in_str = True
            q = ch
            cur.append(ch)
            continue
        if ch in "([{":
            depth += 1
            cur.append(ch)
            continue
        if ch in ")]}":
            depth -= 1
            cur.append(ch)
            continue
        if ch == "," and depth == 0:
            args.append("".join(cur).strip())
            cur = []
            continue
        cur.append(ch)
    if cur:
        args.append("".join(cur).strip())
    return args

def patch_qmessagebox(src: str) -> str:
    out = []
    i = 0
    while True:
        m = QMB_PREFIX_RE.search(src, i)
        if not m:
            out.append(src[i:])
            break
        start = m.start()
        out.append(src[i:start])
        open_paren = src.find("(", m.end() - 1)
        if open_paren == -1:
            out.append(src[start:m.end()])
            i = m.end()
            continue
        end_paren = _find_call_end(src, open_paren)
        if end_paren is None:
            out.append(src[start:m.end()])
            i = m.end()
            continue

        call = src[start:end_paren + 1]
        inside = call[call.find("(") + 1 : -1]
        args = _split_args(inside)

        # QMessageBox.*(parent, title, text, ...)
        if len(args) >= 3:
            if is_plain_string_literal(args[1]):
                args[1] = wrap_lit(args[1])
            if is_plain_string_literal(args[2]):
                args[2] = wrap_lit(args[2])
        new_inside = ", ".join(args)
        new_call = call[:call.find("(") + 1] + new_inside + ")"
        out.append(new_call)
        i = end_paren + 1
    return "".join(out)

# ── patch common UI sinks: setText/toolTip/windowTitle/status/progress ───────
SINK_METHODS = (
    "setText", "setToolTip", "setStatusTip", "setWindowTitle",
    "set_status", "set_progress_stage", "set_dvd_title", "set_movie_title",
)

# match .method( "literal" ) single arg
_re_sink_1 = re.compile(
    r"(\.\s*(?:%s)\s*\(\s*)([^)\n]+?)(\s*\))" % "|".join(map(re.escape, SINK_METHODS))
)

def patch_sink_methods(src: str) -> str:
    def repl(m: re.Match) -> str:
        head, arg, tail = m.group(1), m.group(2), m.group(3)
        a = arg.strip()
        if a.startswith("L("):
            return m.group(0)
        if is_plain_string_literal(a):
            return head + wrap_lit(a) + tail
        return m.group(0)
    return _re_sink_1.sub(repl, src)

# ── patch widget constructors with first arg literal: QLabel(".."), QPushButton(".."), QAction(".."), QMenu("..")
CTOR = ("QLabel", "QPushButton", "QAction", "QMenu", "QGroupBox")
_re_ctor = re.compile(r"\b(?:%s)\s*\(\s*([^,\n)]+)" % "|".join(CTOR))

def patch_ctors(src: str) -> str:
    def repl(m: re.Match) -> str:
        a = m.group(1).strip()
        if a.startswith("L("):
            return m.group(0)
        if is_plain_string_literal(a):
            return m.group(0).replace(a, wrap_lit(a), 1)
        return m.group(0)
    return _re_ctor.sub(repl, src)

def process_file(p: Path, apply: bool, backup_dir: Path) -> str:
    src0 = p.read_text(encoding="utf-8", errors="replace")
    src = src0

    src = patch_qmessagebox(src)
    src = patch_sink_methods(src)
    src = patch_ctors(src)

    if "L(" in src:
        src = ensure_import_L_after_future(src)

    if src == src0:
        return f"[OK] nochange {p}"

    if apply:
        backup_dir.mkdir(parents=True, exist_ok=True)
        (backup_dir / p.as_posix().replace("/", "__")).write_text(src0, encoding="utf-8")
        p.write_text(src, encoding="utf-8")
        return f"[CHANGED] {p}"
    return f"[WOULD_CHANGE] {p}"

def main() -> int:
    apply = "--apply" in sys.argv
    bdir = Path("/tmp/i18n_ldvd_ui_bak")
    if "--backup-dir" in sys.argv:
        i = sys.argv.index("--backup-dir")
        bdir = Path(sys.argv[i + 1])

    msgs = []
    for p in TARGETS:
        msgs.append(process_file(p, apply=apply, backup_dir=bdir))
    print("\n".join(msgs))

    if apply:
        import py_compile
        for p in TARGETS:
            py_compile.compile(str(p), doraise=True)
        print("[OK] py_compile targets OK")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
