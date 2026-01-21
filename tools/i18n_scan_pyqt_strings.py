#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


# Metodi Qt “tipici” che ricevono testo UI
TARGET_ATTRS = {
    "setText",
    "setWindowTitle",
    "setTitle",
    "setToolTip",
    "setStatusTip",
    "setWhatsThis",
    "setPlaceholderText",
    "setAccessibleName",
    "setAccessibleDescription",
    "setHeaderLabels",
    "setHorizontalHeaderLabels",
    "setVerticalHeaderLabels",
    "addAction",
    "addMenu",
    "addTab",
    "insertTab",
    "setTabText",
    "setItemText",
    "setTextFormat",
    "setInformativeText",
    "setDetailedText",
    "setTextInteractionFlags",
    "setLabelText",
    "setButtonText",
    "setShortcut",
    "setIconText",
    "setDescription",
}

# Un po’ di filtri “soft” per ridurre rumore
def looks_like_noise(s: str) -> bool:
    st = s.strip()
    if not st:
        return True
    # roba troppo corta spesso è rumore (ma lascio passare "&File", "OK", ecc.)
    if len(st) == 1:
        return True
    # percorsi/file spesso non sono UI
    if "/" in st or "\\\\" in st:
        return True
    # roba che sembra chiave interna
    if st.startswith(("http://", "https://")):
        return True
    return False


@dataclass
class Hit:
    path: Path
    lineno: int
    col: int
    func: str
    text: str


def _get_func_name(call: ast.Call) -> Optional[str]:
    f = call.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return None


def _extract_str_consts(node: ast.AST) -> List[str]:
    """Ritorna tutte le stringhe costanti immediate dentro un nodo (args, tuple, concat semplice...)."""
    out: List[str] = []

    def rec(n: ast.AST) -> None:
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            out.append(n.value)
            return
        # f-string: possiamo prendere solo i pezzi statici (JoinedStr con Constant str)
        if isinstance(n, ast.JoinedStr):
            for v in n.values:
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    out.append(v.value)
            return
        # concatenazioni tipo "a" + "b"
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
            rec(n.left)
            rec(n.right)
            return
        # tuple/list
        if isinstance(n, (ast.Tuple, ast.List)):
            for e in n.elts:
                rec(e)
            return

    rec(node)
    return out


class Visitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.hits: List[Hit] = []

    def visit_Call(self, node: ast.Call) -> None:
        fn = _get_func_name(node)
        if fn in TARGET_ATTRS:
            # prendiamo stringhe costanti in tutti gli args (addAction spesso ha icon + testo)
            for arg in node.args:
                # se arg è già una call (es. self.tr("x") o translate(...)), non è una stringa nuda => ok
                if isinstance(arg, ast.Call):
                    continue
                for s in _extract_str_consts(arg):
                    if looks_like_noise(s):
                        continue
                    self.hits.append(
                        Hit(
                            path=self.path,
                            lineno=getattr(arg, "lineno", getattr(node, "lineno", 0)),
                            col=getattr(arg, "col_offset", getattr(node, "col_offset", 0)),
                            func=fn or "?",
                            text=s.strip(),
                        )
                    )

        self.generic_visit(node)


def iter_py_files(roots: Iterable[str]) -> Iterable[Path]:
    for r in roots:
        base = Path(r)
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            if p.is_file():
                yield p


def parse_file(path: Path) -> Tuple[List[Hit], Optional[str]]:
    try:
        src = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        src = path.read_text(encoding="utf-8", errors="ignore")

    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as e:
        return [], f"SyntaxError: {e}"

    v = Visitor(path)
    v.visit(tree)
    return v.hits, None


def main() -> int:
    ap = argparse.ArgumentParser(description="Scan PyQt .py for UI strings not wrapped in tr()/translate().")
    ap.add_argument("--roots", nargs="*", default=["hevc_gui", "scripts", "tools"], help="Root dirs to scan")
    ap.add_argument("--max-per-file", type=int, default=80, help="Max hits to show per file")
    ap.add_argument("--out", default="", help="Write full report to file (txt)")
    args = ap.parse_args()

    all_hits: List[Hit] = []
    errors: List[str] = []

    for p in iter_py_files(args.roots):
        hits, err = parse_file(p)
        if err:
            errors.append(f"{p}: {err}")
        all_hits.extend(hits)

    # raggruppa per file
    by_file: dict[Path, List[Hit]] = {}
    for h in all_hits:
        by_file.setdefault(h.path, []).append(h)

    lines: List[str] = []
    lines.append(f"Files scanned: {sum(1 for _ in iter_py_files(args.roots))}")
    lines.append(f"Total candidate UI strings (nude): {len(all_hits)}")
    if errors:
        lines.append("")
        lines.append("Parse errors:")
        lines.extend([f"  - {e}" for e in errors])

    # stampa per file (più hits prima)
    lines.append("")
    lines.append("=== Candidates by file (most first) ===")
    for f, hits in sorted(by_file.items(), key=lambda kv: len(kv[1]), reverse=True):
        lines.append("")
        lines.append(f"[{len(hits):4d}] {f}")
        shown = 0
        for h in hits:
            shown += 1
            if shown > args.max_per_file:
                lines.append(f"  ... (+{len(hits)-args.max_per_file} more)")
                break
            lines.append(f"  L{h.lineno:4d}:{h.col:<3d}  {h.func:<24s}  {h.text!r}")

    report = "\n".join(lines)
    print(report)

    if args.out:
        Path(args.out).write_text(report + "\n", encoding="utf-8")
        print(f"\n[OK] Written: {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
