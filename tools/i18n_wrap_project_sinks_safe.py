#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import ast
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parents[1]

# ───────────────────────────── esclusioni ─────────────────────────────
EXCLUDE_TOPDIRS = {"backup", "build", "dist"}
EXCLUDE_PREFIXES = (
    "hevc_gui/resources/i18n/",  # auto marks / generatori
    "hevc_gui/resources/icons/",
    "tools/",                    # toolchain: non tradurre i tool stessi
)
EXCLUDE_FILES = {
    Path("tools/update_ts_en.py"),  # wrapper/legacy: non serve
}

# ───────────────────────────── sink umani ─────────────────────────────
QMSG_ATTRS = {"information", "warning", "critical", "question"}
UI_STATIC_CLASSES = {"QMessageBox", "QFileDialog", "QInputDialog"}

# metodi tipicamente UI
UI_METHOD_SINKS = {
    "setText", "setTitle", "setWindowTitle",
    "setToolTip", "setStatusTip", "setWhatsThis",
    "setPlaceholderText",
    "showMessage",
    # tuoi metodi “underhood”
    "set_status", "set_progress_stage", "set_dvd_title", "set_movie_title",
}

# QTextEdit/QPlainTextEdit: SOLO metodi univoci, NON append() generico!
TEXT_SINKS = {"appendPlainText", "insertPlainText"}

# QAction/QMenu (menu + toolbar)
ACTION_SINKS = {"QAction", "QMenu", "addAction", "addMenu"}

# ───────────────────────────── filtri “tecnico” ─────────────────────────────
TECH_RES_PAT = re.compile(r"^:/")
TECH_PATH_PAT = re.compile(r"[/\\]")
TECH_FLAG_PAT = re.compile(r"^--?[\w-]+$")
TECH_EXT_PAT  = re.compile(r"^\.[A-Za-z0-9]{2,5}$")
TECH_SHORTCUT = re.compile(r"^(Ctrl|Alt|Shift)\+")
TECH_FKEY     = re.compile(r"^F\d+$")
TECH_REGEXY   = re.compile(r"(\\d|\\s|\(\?|\[\^|\^\w|\$\s*$)")

def _is_human(s: str) -> bool:
    t = (s or "").strip()
    if not t or t in {"—", "…", "..."}:
        return False
    low = t.lower()
    if "ffmpeg" in low or "x265" in low:
        return False
    if TECH_RES_PAT.match(t):
        return False
    if TECH_FLAG_PAT.match(t):
        return False
    if TECH_EXT_PAT.match(t):
        return False
    if TECH_SHORTCUT.match(t):
        return False
    if TECH_FKEY.match(t):
        return False
    if TECH_REGEXY.search(t):
        return False
    # path-like
    if TECH_PATH_PAT.search(t) and (":" in t or "." in t or "_" in t):
        return False
    # se non ha lettere, lascia stare
    return any(ch.isalpha() for ch in t)

def _is_already_i18n(expr: ast.AST) -> bool:
    # L(".."), T(".."), self.tr(".."), QCoreApplication.translate(...)
    if isinstance(expr, ast.Call):
        f = expr.func
        if isinstance(f, ast.Name) and f.id in {"L", "T"}:
            return True
        if isinstance(f, ast.Attribute) and f.attr == "tr":
            return True
        if isinstance(f, ast.Attribute) and f.attr == "translate":
            # QtCore.QCoreApplication.translate(...)
            return True
    return False

def _escape_braces(s: str) -> str:
    return s.replace("{", "{{").replace("}", "}}")

def _fstring_to_L_format(n: ast.JoinedStr) -> Tuple[str, List[ast.AST]] | None:
    parts: List[str] = []
    args: List[ast.AST] = []
    idx = 0
    for v in n.values:
        if isinstance(v, ast.Constant) and isinstance(v.value, str):
            parts.append(_escape_braces(v.value))
        elif isinstance(v, ast.FormattedValue):
            conv = ""
            if v.conversion != -1:
                conv = {ord("r"): "!r", ord("s"): "!s", ord("a"): "!a"}.get(v.conversion, "")
            spec = ""
            if v.format_spec is not None:
                fs = v.format_spec
                if isinstance(fs, ast.Constant) and isinstance(fs.value, str):
                    spec = ":" + fs.value
                elif isinstance(fs, ast.JoinedStr):
                    ss = []
                    for vv in fs.values:
                        if isinstance(vv, ast.Constant) and isinstance(vv.value, str):
                            ss.append(vv.value)
                        else:
                            return None
                    spec = ":" + "".join(ss)
                else:
                    return None
            parts.append("{" + str(idx) + conv + spec + "}")
            args.append(v.value)
            idx += 1
        else:
            return None
    return "".join(parts), args

def _wrap_expr(expr: ast.AST) -> ast.AST | None:
    if _is_already_i18n(expr):
        return None
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        if not _is_human(expr.value):
            return None
        return ast.Call(func=ast.Name(id="L", ctx=ast.Load()),
                        args=[ast.Constant(value=expr.value)], keywords=[])
    if isinstance(expr, ast.JoinedStr):
        conv = _fstring_to_L_format(expr)
        if not conv:
            return None
        templ, args = conv
        if not _is_human(templ):
            return None
        base = ast.Call(func=ast.Name(id="L", ctx=ast.Load()),
                        args=[ast.Constant(value=templ)], keywords=[])
        if args:
            return ast.Call(func=ast.Attribute(value=base, attr="format", ctx=ast.Load()),
                            args=args, keywords=[])
        return base
    return None

def _attr_chain_last_name(n: ast.AST) -> str:
    if isinstance(n, ast.Name):
        return n.id
    if isinstance(n, ast.Attribute):
        return _attr_chain_last_name(n.value) or n.attr
    return ""

def _is_qmessagebox_static(call: ast.Call) -> bool:
    f = call.func
    if isinstance(f, ast.Attribute) and f.attr in QMSG_ATTRS:
        try:
            txt = ast.unparse(f.value)
        except Exception:
            txt = ""
        return "QMessageBox" in txt
    return False

def _is_target_call(call: ast.Call) -> bool:
    f = call.func
    if isinstance(f, ast.Attribute):
        base_last = _attr_chain_last_name(f.value)
        if base_last in UI_STATIC_CLASSES:
            return True
        if _is_qmessagebox_static(call):
            return True
        if f.attr in UI_METHOD_SINKS:
            return True
        if f.attr in TEXT_SINKS:
            return True
        if f.attr in ACTION_SINKS:
            return True
    elif isinstance(f, ast.Name):
        # costruttori usati senza prefisso (QAction, QMenu)
        if f.id in ACTION_SINKS:
            return True
    return False


def _trim_end_comma(src_text: str, s: int, e: int) -> tuple[int, int]:
    """Evita di inglobare la virgola finale nel range che sostituiamo.
    Se l'end offset punta dopo una ',' (o dopo spazi + ','), arretra.
    """
    ee = e
    # tolgo spazi finali
    while ee > s and src_text[ee - 1].isspace():
        ee -= 1
    # se c'è una virgola finale, NON sostituirla
    if ee > s and src_text[ee - 1] == ",":
        ee -= 1
    return s, ee
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

def _ensure_import_L_after(src: str) -> str:
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
    out.append("from hevc_gui.i18n import L\n")
    out.append("\n")
    out.extend(lines[i:])
    return "".join(out)

def _excluded(rel: str) -> bool:
    if rel.split("/", 1)[0] in EXCLUDE_TOPDIRS:
        return True
    if any(rel.startswith(p) for p in EXCLUDE_PREFIXES):
        return True
    if Path(rel) in EXCLUDE_FILES:
        return True
    return False

def git_py_files() -> List[Tuple[Path, str]]:
    out = subprocess.check_output(["git", "ls-files", "-z", "*.py"], cwd=ROOT)
    files = [f.decode("utf-8") for f in out.split(b"\0") if f]
    res = []
    for rel in files:
        if _excluded(rel):
            continue
        res.append((ROOT / rel, rel))
    return res

def process_file(p: Path, rel: str, apply: bool, backup_dir: Path) -> Tuple[bool, str]:
    src0 = p.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(src0)
    except SyntaxError as e:
        return False, f"[SKIP] parse fail {rel}: {e}"

    starts = _line_starts(src0)
    edits: List[Edit] = []

    class V(ast.NodeVisitor):
        def visit_Call(self, node: ast.Call):
            if _is_target_call(node):
                # wrap args
                for arg in node.args:
                    w = _wrap_expr(arg)
                    if w is None:
                        continue
                    if not hasattr(arg, "lineno") or not hasattr(arg, "end_lineno"):
                        continue
                    s = _abspos(starts, arg.lineno, arg.col_offset)
                    e = _abspos(starts, arg.end_lineno, arg.end_col_offset)
                    s, e = _trim_end_comma(src, s, e)
                    edits.append(Edit(s, e, ast.unparse(w)))

                # wrap keyword values
                for kw in node.keywords:
                    if kw.value is None:
                        continue
                    w = _wrap_expr(kw.value)
                    if w is None:
                        continue
                    v = kw.value
                    if not hasattr(v, "lineno") or not hasattr(v, "end_lineno"):
                        continue
                    s = _abspos(starts, v.lineno, v.col_offset)
                    e = _abspos(starts, v.end_lineno, v.end_col_offset)
                    s, e = _trim_end_comma(src, s, e)
                    edits.append(Edit(s, e, ast.unparse(w)))
            self.generic_visit(node)

    V().visit(tree)

    if not edits:
        return False, f"[OK] nochange {rel}"

    out = src0
    for ed in sorted(edits, key=lambda x: (x.start, x.end), reverse=True):
        out = out[:ed.start] + ed.repl + out[ed.end:]

    # importa L *dopo* (non prima), così non sballa gli offset
    if "L(" in out and "from hevc_gui.i18n import L" not in out:
        out = _ensure_import_L_after(out)

    if out == src0:
        return False, f"[OK] nochange {rel}"

    if apply:
        backup_dir.mkdir(parents=True, exist_ok=True)
        (backup_dir / rel.replace("/", "__")).write_text(src0, encoding="utf-8")
        p.write_text(out, encoding="utf-8")
        # compile subito: se fail, rollback
        import py_compile
        try:
            py_compile.compile(str(p), doraise=True)
        except Exception as e:
            p.write_text(src0, encoding="utf-8")
            return False, f"[ROLLBACK] {rel} -> {e}"
        return True, f"[CHANGED] {rel} edits={len(edits)}"
    else:
        return True, f"[WOULD_CHANGE] {rel} edits={len(edits)}"

def main() -> int:
    apply = "--apply" in sys.argv
    bdir = None
    if "--backup-dir" in sys.argv:
        i = sys.argv.index("--backup-dir")
        bdir = Path(sys.argv[i+1])
    backup_dir = bdir or Path("/tmp/i18n_wrap_project_bak")

    changed = 0
    rolled = 0
    skipped = 0

    for p, rel in git_py_files():
        ok, msg = process_file(p, rel, apply=apply, backup_dir=backup_dir)
        print(msg)
        if msg.startswith("[CHANGED]"):
            changed += 1
        elif msg.startswith("[ROLLBACK]"):
            rolled += 1
        elif msg.startswith("[SKIP]"):
            skipped += 1

    print(f"\n[SUMMARY] changed={changed} rollback={rolled} skipped={skipped} apply={apply}")
    return 0 if rolled == 0 else 3

if __name__ == "__main__":
    raise SystemExit(main())
