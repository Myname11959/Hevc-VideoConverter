#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Wrap/convert string literals for Qt i18n.

Modes:
1) Default: wrap plain string literals passed to common Qt setters into tr(CTX, "...").
   - Skips anything already containing tr()/translate()/self.tr()
   - Skips anything containing t( or ftr(
   - Skips f-strings and bytes

2) With --convert-t: convert simple t("...") -> tr(CTX, "...")
   - Only exact single-literal calls: t("...") or t('...')
   - Skips f-strings, bytes, t(tr(...)), t(foo), t("a"+ "b") etc.
   - Skips attribute calls like self.t("...") / obj.t("...")

Backups unless --no-backup.
"""

from __future__ import annotations
import argparse
import difflib
import io
import re
import sys
import tokenize
from pathlib import Path
from typing import Iterable, Optional, Tuple, List


METHODS = [
    "addItem",
    "setItemText",
    "setText",
    "setToolTip",
    "setStatusTip",
    "setWhatsThis",
    "setWindowTitle",
    "setPlaceholderText",
]

SKIP_IF_ARGS_CONTAINS = (
    "tr(",
    "self.tr(",
    "QCoreApplication.translate(",
    ".translate(",
    "translate(",
    "t(",
    "ftr(",
)

# Detect any f-string prefix near a quote (f"...", rf'...', fr"...", etc.)
FSTRING_RE = re.compile(r"""(^|[\s,(])(?:[rRuU]{0,2})[fF](?:[rRuU]{0,2})["']""")

# Python string literal with optional prefixes (we keep r/u prefixes, skip b/f)
LIT_RE = re.compile(
    r"""(?P<pfx>(?:[rRuUbB]{0,2}))(?P<q>["'])(?P<s>(?:\\.|(?!\2).)*)\2""",
    re.DOTALL,
)

CALL_START_RE = re.compile(r"""\.\s*(?P<meth>{})\s*\(""".format("|".join(map(re.escape, METHODS))))


def iter_files(paths: Iterable[str]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        pp = Path(p)
        if pp.is_dir():
            out.extend([x for x in pp.rglob("*.py") if x.is_file()])
        elif pp.is_file() and pp.suffix == ".py":
            out.append(pp)
    # de-dup
    seen = set()
    uniq: list[Path] = []
    for f in out:
        rf = f.resolve()
        if rf not in seen:
            uniq.append(f)
            seen.add(rf)
    return uniq


def find_matching_paren(s: str, open_pos: int) -> Optional[int]:
    """Return index of matching ')' for s[open_pos]=='(' accounting for strings."""
    assert s[open_pos] == "("
    i = open_pos + 1
    depth = 1
    in_str = False
    quote = ""
    triple = False
    esc = False

    while i < len(s):
        ch = s[i]

        if in_str:
            if triple:
                if s.startswith(quote * 3, i):
                    in_str = False
                    i += 3
                    continue
                i += 1
                continue
            else:
                if esc:
                    esc = False
                    i += 1
                    continue
                if ch == "\\":
                    esc = True
                    i += 1
                    continue
                if ch == quote:
                    in_str = False
                    i += 1
                    continue
                i += 1
                continue

        # not in string
        if ch in ("'", '"'):
            # triple?
            if s.startswith(ch * 3, i):
                in_str = True
                quote = ch
                triple = True
                i += 3
                continue
            in_str = True
            quote = ch
            triple = False
            i += 1
            continue

        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1

    return None


def wrap_args(args: str, ctx: str) -> Tuple[str, bool]:
    a = args
    if any(h in a for h in SKIP_IF_ARGS_CONTAINS):
        return args, False
    if FSTRING_RE.search(a):
        return args, False

    changed = False

    def repl(m: re.Match) -> str:
        nonlocal changed
        pfx = m.group("pfx") or ""
        q = m.group("q")
        s = m.group("s")

        lp = pfx.lower()
        if "b" in lp:   # bytes
            return m.group(0)
        if "f" in lp:   # f-string (extra safety)
            return m.group(0)

        changed = True
        return f"tr({ctx}, {pfx}{q}{s}{q})"

    new_args = LIT_RE.sub(repl, a)
    return new_args, (changed and new_args != args)


def process_text_setters(text: str, ctx: str) -> Tuple[str, int]:
    s = text
    out = []
    last = 0
    changes = 0

    for m in CALL_START_RE.finditer(s):
        open_pos = s.find("(", m.end() - 1)
        if open_pos < 0:
            continue
        close_pos = find_matching_paren(s, open_pos)
        if close_pos is None:
            continue

        args = s[open_pos + 1 : close_pos]
        new_args, ch = wrap_args(args, ctx)
        if not ch:
            continue

        out.append(s[last : open_pos + 1])
        out.append(new_args)
        out.append(")")
        last = close_pos + 1
        changes += 1

    if changes == 0:
        return text, 0

    out.append(s[last:])
    return "".join(out), changes


def _prefix_of_string_token(tok: str) -> str:
    # tok is like: r"abc" or "abc" or f"abc" etc.
    # Return lowercase prefix before first quote.
    i = 0
    while i < len(tok) and tok[i] not in ("'", '"'):
        i += 1
    return tok[:i].lower()


def convert_simple_t_calls(text: str, ctx: str) -> Tuple[str, int]:
    """
    Convert simple occurrences of: t("...") -> tr(CTX, "...")
    using tokenize, then apply replacements by absolute offsets.
    """
    lines = text.splitlines(True)
    line_off = [0]
    for ln in lines:
        line_off.append(line_off[-1] + len(ln))

    def abspos(line: int, col: int) -> int:
        # tokenize lines are 1-based
        return line_off[line - 1] + col

    toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    repls: List[Tuple[int, int, str]] = []
    i = 0
    n = 0

    while i + 3 < len(toks):
        t0, t1, t2, t3 = toks[i], toks[i + 1], toks[i + 2], toks[i + 3]

        # pattern: NAME 't'  OP '('  STRING  OP ')'
        if t0.type == tokenize.NAME and t0.string == "t" and t1.string == "(" and t2.type == tokenize.STRING and t3.string == ")":
            # skip attribute calls: ". t ("
            j = i - 1
            while j >= 0 and toks[j].type in (tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT):
                j -= 1
            if j >= 0 and toks[j].string == ".":
                i += 1
                continue

            pref = _prefix_of_string_token(t2.string)
            if "f" in pref or "b" in pref:
                i += 1
                continue

            start = abspos(t0.start[0], t0.start[1])
            end = abspos(t3.end[0], t3.end[1])
            new = f"tr({ctx}, {t2.string})"
            repls.append((start, end, new))
            n += 1
            i += 4
            continue

        i += 1

    if not repls:
        return text, 0

    # apply from end
    s = text
    for start, end, new in sorted(repls, key=lambda x: x[0], reverse=True):
        s = s[:start] + new + s[end:]
    return s, n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ctx", default="CTX")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--convert-t", action="store_true", help='Convert simple t("...") to tr(CTX, "...")')
    ap.add_argument("--backup-suffix", default=".bak_i18n")
    ap.add_argument("--no-backup", action="store_true")
    ap.add_argument("paths", nargs="+")
    args = ap.parse_args()

    files = iter_files(args.paths)
    if not files:
        print("No .py files found.", file=sys.stderr)
        return 2

    total = 0
    for f in files:
        old = f.read_text(encoding="utf-8")
        new = old
        c1 = c2 = 0

        # 1) optional: convert t("...") -> tr(...)
        if args.convert_t:
            new, c1 = convert_simple_t_calls(new, args.ctx)

        # 2) wrap plain literals in setters
        new, c2 = process_text_setters(new, args.ctx)

        n = c1 + c2
        if n <= 0 or new == old:
            continue

        total += n
        if args.dry_run:
            diff = difflib.unified_diff(
                old.splitlines(True),
                new.splitlines(True),
                fromfile=str(f),
                tofile=str(f) + " (wrapped)",
            )
            sys.stdout.writelines(diff)
        else:
            if not args.no_backup:
                bak = f.with_name(f.name + args.backup_suffix)
                bak.write_text(old, encoding="utf-8")
            f.write_text(new, encoding="utf-8")
            print(f"[OK] {f}: changed {n} (convert_t={c1}, setters={c2})")

    if args.dry_run:
        print(f"\n[dry-run] Total changed: {total}")
    else:
        print(f"\nTotal changed: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
