#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]

TARGETS = [
    ROOT / "hevc_gui" / "dvd_ripper" / "controller.py",
    ROOT / "hevc_gui" / "dvd_ripper" / "gui.py",
]

SINK_METHODS = ("set_status", "set_progress_stage", "set_dvd_title", "set_movie_title")

# ──────────────────────────────────────────────────────────────────────────────
# helpers: import L
def ensure_import_L(src: str) -> str:
    if "from hevc_gui.i18n import L" in src:
        return src

    lines = src.splitlines(True)
    out: List[str] = []
    i = 0

    # shebang/encoding
    while i < len(lines) and (lines[i].startswith("#!") or "coding:" in lines[i]):
        out.append(lines[i]); i += 1

    # module docstring
    if i < len(lines) and lines[i].lstrip().startswith(('"""', "'''")):
        q = lines[i].lstrip()[:3]
        out.append(lines[i]); i += 1
        while i < len(lines):
            out.append(lines[i])
            if q in lines[i]:
                i += 1
                break
            i += 1

    # __future__
    while i < len(lines) and lines[i].startswith("from __future__ import"):
        out.append(lines[i]); i += 1

    out.append("from hevc_gui.i18n import L\n")
    out.extend(lines[i:])
    return "".join(out)

# ──────────────────────────────────────────────────────────────────────────────
# string literal detection
_str_lit = re.compile(r"""^(?P<prefix>[rubRUB]*) (?P<q>['"])(?P<body>(?:\\.|(?!\2).)*)\2$""", re.X | re.S)

def is_string_literal(s: str) -> bool:
    return bool(_str_lit.match(s.strip()))

def wrap_string_literal(lit: str) -> str:
    lit = lit.strip()
    if lit.startswith("L("):
        return lit
    return f"L({lit})"

def _escape_for_double_quotes(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')

def fstring_to_L_format(flit: str) -> str | None:
    """
    Converte f"ciao {x} ok" -> L("ciao {0} ok").format(x)
    Supporta anche format spec semplice: {expr:02d} -> {0:02d}
    """
    s = flit.strip()
    if not (s.startswith('f"') or s.startswith("f'")):
        return None
    q = s[1]
    if not s.endswith(q):
        return None
    body = s[2:-1]  # contenuto fra quote

    parts: List[str] = []
    exprs: List[str] = []
    i = 0
    idx = 0

    while i < len(body):
        ch = body[i]

        # brace escape
        if ch == "{" and i + 1 < len(body) and body[i + 1] == "{":
            parts.append("{"); i += 2; continue
        if ch == "}" and i + 1 < len(body) and body[i + 1] == "}":
            parts.append("}"); i += 2; continue

        if ch == "{":
            # trova brace chiusa (no nested braces qui)
            j = i + 1
            level = 1
            while j < len(body) and level:
                if body[j] == "{" and not (j + 1 < len(body) and body[j + 1] == "{"):
                    level += 1
                elif body[j] == "}" and not (j + 1 < len(body) and body[j + 1] == "}"):
                    level -= 1
                    if level == 0:
                        break
                j += 1
            if level != 0:
                return None

            inside = body[i + 1 : j].strip()

            # split expr / :spec (molto semplice ma funziona per i tuoi casi)
            expr = inside
            spec = ""
            # se c'è ":" e non sembra parte di dict/ternary, prendo il primo ":" top-level (approssimazione prudente)
            if ":" in inside:
                # split al primo ":" (nei tuoi casi: int(vts_num):02d)
                expr, spec = inside.split(":", 1)
                expr = expr.strip()
                spec = spec.strip()

            exprs.append(expr)
            if spec:
                parts.append("{" + str(idx) + ":" + spec + "}")
            else:
                parts.append("{" + str(idx) + "}")
            idx += 1
            i = j + 1
            continue

        # normale
        parts.append(ch)
        i += 1

    templ = "".join(parts)
    templ = templ.replace("{", "{{").replace("}", "}}")  # escape per .format
    # riporta placeholders
    for n in range(idx):
        templ = templ.replace("{{" + str(n) + "}}", "{" + str(n) + "}")

    templ = _escape_for_double_quotes(templ)
    if idx == 0:
        return f'L("{templ}")'
    args = ", ".join(exprs)
    return f'L("{templ}").format({args})'

# ──────────────────────────────────────────────────────────────────────────────
# patch: set_status / set_progress_stage / set_dvd_title / set_movie_title
_re_setter = re.compile(
    r"""
    (?P<head>\.\s*(?:set_status|set_progress_stage|set_dvd_title|set_movie_title)\s*\(\s*)
    (?P<arg>
        L\([^)]*\) |
        f(?P<fq>['"])(?:\\.|(?!\3).)*\3 |
        (?P<sq>['"])(?:\\.|(?!\4).)*\4
    )
    (?P<tail>\s*\))
    """,
    re.X | re.S,
)

def patch_setters(src: str) -> str:
    def repl(m: re.Match) -> str:
        head = m.group("head")
        arg = m.group("arg").strip()
        tail = m.group("tail")

        if arg.startswith("L("):
            return m.group(0)

        if arg.startswith("f'") or arg.startswith('f"'):
            conv = fstring_to_L_format(arg)
            if conv:
                return head + conv + tail
            return m.group(0)

        if is_string_literal(arg):
            return head + wrap_string_literal(arg) + tail

        return m.group(0)

    return _re_setter.sub(repl, src)

# ──────────────────────────────────────────────────────────────────────────────
# parse a QMessageBox.<kind>( ... ) call and patch args[1]=title args[2]=text
QMB_KINDS = ("information", "warning", "critical", "question")
QMB_PREFIX_RE = re.compile(r"QMessageBox\.(%s)\s*\(" % "|".join(QMB_KINDS))

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

def _patch_arg_text(a: str) -> str:
    a = a.strip()
    if a.startswith("L("):
        return a
    if a.startswith("f'") or a.startswith('f"'):
        conv = fstring_to_L_format(a)
        return conv if conv else a
    if is_string_literal(a):
        return wrap_string_literal(a)

    # pattern: msg or "fallback"
    m = re.match(r"^(?P<lhs>.+?)\s+or\s+(?P<rhs>f?['\"].*['\"])$", a, re.S)
    if m:
        lhs = m.group("lhs").strip()
        rhs = m.group("rhs").strip()
        if rhs.startswith("f'") or rhs.startswith('f"'):
            conv = fstring_to_L_format(rhs)
            rhs2 = conv if conv else rhs
        elif is_string_literal(rhs):
            rhs2 = wrap_string_literal(rhs)
        else:
            rhs2 = rhs
        return f"{lhs} or {rhs2}"

    return a

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

        # trova '('
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
        if len(args) >= 3:
            # args[1]=title args[2]=text
            args[1] = _patch_arg_text(args[1])
            args[2] = _patch_arg_text(args[2])
            new_inside = ", ".join(args)
            call = call[:call.find("(") + 1] + new_inside + ")"

        out.append(call)
        i = end_paren + 1

    return "".join(out)

# ──────────────────────────────────────────────────────────────────────────────
def process_file(p: Path, apply: bool, backup_dir: Path) -> tuple[bool, str]:
    src0 = p.read_text(encoding="utf-8", errors="replace")
    src = src0

    src = patch_qmessagebox(src)
    src = patch_setters(src)

    # import L se serve
    if "L(" in src:
        src = ensure_import_L(src)

    if src == src0:
        return False, f"[OK] nochange {p}"

    if apply:
        backup_dir.mkdir(parents=True, exist_ok=True)
        bp = backup_dir / p.as_posix().replace("/", "__")
        bp.write_text(src0, encoding="utf-8")
        p.write_text(src, encoding="utf-8")
        return True, f"[CHANGED] {p}"
    else:
        return True, f"[WOULD_CHANGE] {p}"

def main() -> int:
    apply = "--apply" in sys.argv
    bdir = Path("/tmp/i18n_ldvd_ripper_sinks_bak")
    if "--backup-dir" in sys.argv:
        i = sys.argv.index("--backup-dir")
        bdir = Path(sys.argv[i + 1])

    changed = []
    for p in TARGETS:
        ok, msg = process_file(p, apply=apply, backup_dir=bdir)
        print(msg)
        if msg.startswith("[CHANGED]") or msg.startswith("[WOULD_CHANGE]"):
            changed.append(p)

    if apply and changed:
        import py_compile
        for p in changed:
            py_compile.compile(str(p), doraise=True)
        print("[OK] py_compile targets OK")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
