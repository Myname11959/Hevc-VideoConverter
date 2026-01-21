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

UI_STATIC_CLASSES = {"QMessageBox", "QFileDialog", "QInputDialog"}
QMSG_ATTRS = {"information", "warning", "critical", "question"}

# SOLO metodi davvero "sink UI" (niente append generico!)
UI_METHOD_SINKS = {
    "setText", "setToolTip", "setStatusTip", "setWindowTitle",
    "showMessage",
    "insertPlainText", "appendPlainText",
    # tuoi metodi “UI sotto il cofano”
    "set_status", "set_progress_stage", "set_dvd_title", "set_movie_title",
}

# widget tipo log/console quando usano .append(...)
TEXTEDIT_LIKE_NAMES = {
    "txt_info", "txt_log", "txt_console", "txt_output",
    "log", "log_view", "console", "textEdit", "plainTextEdit",
}

# ── esclusioni robuste ───────────────────────────────────────────────────────
EXCLUDE_TOPDIRS = {"backup", "tools", "build", "dist"}

# risorse/generatori: non toccare
EXCLUDE_PREFIXES = (
    "hevc_gui/resources/",
)

# esclusioni mirate (temporanee)
EXCLUDE_FILES = {
    Path("hevc_gui/gui/main_window.py"),          # ora fa parse fail (line 40)
    Path("scripts/string_audio_generator.py"),    # 46 edits: lo facciamo in un secondo giro
    Path("tools/i18n_one_shot_underhood.py"),     # non autocannibalizzarti
    Path("hevc_gui/dvd_ripper/controller.py"),
    Path("hevc_gui/dvd_ripper/gui.py"),
}

def _excluded(rel: Path) -> bool:
    if rel in EXCLUDE_FILES:
        return True
    if rel.parts and rel.parts[0] in EXCLUDE_TOPDIRS:
        return True
    s = rel.as_posix()
    return any(s.startswith(px) for px in EXCLUDE_PREFIXES)

# ── euristica “tecnico” ──────────────────────────────────────────────────────
TECH_LIT_RE = re.compile(r"^[A-Za-z0-9 _./:=+,\-\[\]\(\)']+$")

def looks_technical_literal(s: str) -> bool:
    t = s.strip()
    if not t:
        return True

    # snake_case / key tecniche / costanti senza spazi
    if " " not in t and re.fullmatch(r"[A-Za-z0-9_]+", t):
        return True

    # roba tipo parametri/filtri senza spazi (ffmpeg-ish, regex-ish)
    if " " not in t and TECH_LIT_RE.match(t) and any(ch in t for ch in ("=", ":", "/", "\\", "[", "]", "{", "}", "|")):
        return True

    # comandi cli evidenti
    low = t.lower()
    if low.startswith(("ffmpeg ", "ffprobe ", "x265 ", "mkvmerge ", "mono ")):
        return True
    if low.startswith("-") or " -vf" in low or " -af" in low or " -map" in low:
        return True

    return False

# ── util offset ──────────────────────────────────────────────────────────────
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

def _is_L_or_T_call(n: ast.AST) -> bool:
    return (
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id in {"L", "T"}
    )

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
                if isinstance(fs, ast.JoinedStr):
                    ss = []
                    for vv in fs.values:
                        if isinstance(vv, ast.Constant) and isinstance(vv.value, str):
                            ss.append(vv.value)
                        else:
                            return None
                    spec = ":" + "".join(ss)
                elif isinstance(fs, ast.Constant) and isinstance(fs.value, str):
                    spec = ":" + fs.value
                else:
                    return None

            parts.append("{" + str(idx) + conv + spec + "}")
            args.append(v.value)
            idx += 1
        else:
            return None

    return "".join(parts), args

def _wrap_expr(expr: ast.AST) -> ast.AST | None:
    if _is_L_or_T_call(expr):
        return None

    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        txt = expr.value
        if not txt.strip():
            return None
        if looks_technical_literal(txt):
            return None
        return ast.Call(func=ast.Name(id="L", ctx=ast.Load()),
                        args=[ast.Constant(value=txt)],
                        keywords=[])

    if isinstance(expr, ast.JoinedStr):
        conv = _fstring_to_L_format(expr)
        if not conv:
            return None
        templ, args = conv
        # se template sembra tecnico, skip
        scrub = templ.replace("{0}", "").replace("{1}", "").replace("{2}", "")
        if looks_technical_literal(scrub):
            return None
        base = ast.Call(func=ast.Name(id="L", ctx=ast.Load()),
                        args=[ast.Constant(value=templ)],
                        keywords=[])
        if args:
            return ast.Call(func=ast.Attribute(value=base, attr="format", ctx=ast.Load()),
                            args=args, keywords=[])
        return base

    if isinstance(expr, (ast.List, ast.Tuple)):
        changed = False
        new_elts = []
        for e in expr.elts:
            w = _wrap_expr(e)
            if w is not None:
                new_elts.append(w)
                changed = True
            else:
                new_elts.append(e)
        if changed:
            return ast.List(elts=new_elts, ctx=ast.Load()) if isinstance(expr, ast.List) else ast.Tuple(elts=new_elts, ctx=ast.Load())

    return None

def _is_textedit_like(obj: ast.AST) -> bool:
    # self.txt_info / self.log_view / variabili chiamate log/console/textEdit...
    if isinstance(obj, ast.Attribute):
        a = obj.attr
        al = a.lower()
        return a in TEXTEDIT_LIKE_NAMES or "log" in al or "console" in al or "textedit" in al
    if isinstance(obj, ast.Name):
        n = obj.id.lower()
        return n in {x.lower() for x in TEXTEDIT_LIKE_NAMES} or "log" in n or "console" in n or "textedit" in n
    return False

def _is_target_call(call: ast.Call) -> bool:
    f = call.func
    if not isinstance(f, ast.Attribute):
        return False

    # static: QMessageBox / QFileDialog / QInputDialog
    if isinstance(f.value, ast.Name) and f.value.id in UI_STATIC_CLASSES:
        return True
    # QtWidgets.QMessageBox.warning ecc
    if f.attr in QMSG_ATTRS and ("QMessageBox" in ast.unparse(f.value)):
        return True

    # sink method
    if f.attr in UI_METHOD_SINKS:
        return True

    # append SOLO su widget log/console
    if f.attr == "append" and _is_textedit_like(f.value):
        return True

    return False

def _ensure_import_L(src: str) -> str:
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
    out.extend(lines[i:])
    return "".join(out)

def process_file(p: Path, apply: bool, backup_dir: Path) -> Tuple[bool, str]:
    src0 = p.read_text(encoding="utf-8", errors="replace")
    src = src0

    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return False, f"[SKIP] parse fail {p}: {e}"

    starts = _line_starts(src)
    edits: List[Edit] = []

    class V(ast.NodeVisitor):
        def visit_Call(self, node: ast.Call):
            if _is_target_call(node):
                for arg in list(node.args):
                    w = _wrap_expr(arg)
                    if w is None:
                        continue
                    if not hasattr(arg, "lineno") or not hasattr(arg, "end_lineno"):
                        continue
                    s = _abspos(starts, arg.lineno, arg.col_offset)
                    e = _abspos(starts, arg.end_lineno, arg.end_col_offset)
                    edits.append(Edit(s, e, ast.unparse(w)))

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
                    edits.append(Edit(s, e, ast.unparse(w)))

            self.generic_visit(node)

    V().visit(tree)

    if not edits:
        return False, f"[OK] nochange {p}"

    # applica edits in reverse sullo stesso src usato per gli offset
    out = src
    for ed in sorted(edits, key=lambda x: (x.start, x.end), reverse=True):
        out = out[:ed.start] + ed.repl + out[ed.end:]

    # solo dopo aggiungi import L se serve
    if "L(" in out and "from hevc_gui.i18n import L" not in out:
        out = _ensure_import_L(out)

    if out == src0:
        return False, f"[OK] nochange {p}"

    if apply:
        backup_dir.mkdir(parents=True, exist_ok=True)
        bp = backup_dir / p.as_posix().replace("/", "__")
        bp.write_text(src0, encoding="utf-8")
        p.write_text(out, encoding="utf-8")
        return True, f"[CHANGED] {p} edits={len(edits)}"

    return True, f"[WOULD_CHANGE] {p} edits={len(edits)}"

def git_py_files() -> List[Path]:
    out = subprocess.check_output(["git", "ls-files", "-z", "*.py"], cwd=ROOT)
    files = [f.decode("utf-8") for f in out.split(b"\0") if f]
    keep: List[Path] = []
    for f in files:
        rel = Path(f)
        if _excluded(rel):
            continue
        keep.append(ROOT / rel)
    return keep

def main() -> int:
    apply = "--apply" in sys.argv
    bdir = None
    if "--backup-dir" in sys.argv:
        i = sys.argv.index("--backup-dir")
        bdir = Path(sys.argv[i + 1])
    backup_dir = bdir or Path("/tmp/i18n_underhood_safe_bak")

    changed: List[str] = []
    for p in git_py_files():
        ok, msg = process_file(p, apply=apply, backup_dir=backup_dir)
        print(msg)
        if msg.startswith("[CHANGED]") or msg.startswith("[WOULD_CHANGE]"):
            changed.append(str(p))

    if apply and changed:
        import py_compile
        for f in changed:
            py_compile.compile(f, doraise=True)

    if changed:
        Path("/tmp/i18n_underhood_safe_changed_files.txt").write_text("\n".join(changed) + "\n", encoding="utf-8")
        print("Changed list -> /tmp/i18n_underhood_safe_changed_files.txt")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
