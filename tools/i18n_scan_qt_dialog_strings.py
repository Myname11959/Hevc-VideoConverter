#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import ast
from pathlib import Path

ROOTS = [Path("hevc_gui"), Path("scripts")]
EXCLUDE = {".git", "__pycache__", "build", "dist", "tools", "backup"}

MSGBOX = {"information","warning","critical","question","about"}
INPUT  = {"getText","getInt","getDouble","getItem"}
FILED  = {"getOpenFileName","getOpenFileNames","getSaveFileName","getExistingDirectory"}

def skip(p: Path) -> bool:
    return any(x in p.parts for x in EXCLUDE)

def const_str(n):
    return n.value if isinstance(n, ast.Constant) and isinstance(n.value, str) else None

def dotted(n) -> str:
    if isinstance(n, ast.Name): return n.id
    if isinstance(n, ast.Attribute): return dotted(n.value) + "." + n.attr
    return ""

def scan(path: Path, out: set[str]) -> None:
    try:
        txt = path.read_text(encoding="utf-8")
        tree = ast.parse(txt, filename=str(path))
    except Exception:
        return

    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        name = dotted(n.func)

        # QMessageBox.*(parent, title, text, ...)
        if any(name.endswith(".QMessageBox."+a) or name.endswith("."+a) for a in MSGBOX):
            if len(n.args) >= 3:
                t1 = const_str(n.args[1]); t2 = const_str(n.args[2])
                if t1: out.add(t1)
                if t2: out.add(t2)
            continue

        # QInputDialog.getX(parent, title, label, ...)
        if any(name.endswith(".QInputDialog."+a) or name.endswith("."+a) for a in INPUT):
            if len(n.args) >= 3:
                t1 = const_str(n.args[1]); t2 = const_str(n.args[2])
                if t1: out.add(t1)
                if t2: out.add(t2)
            continue

        # QFileDialog.getX(parent, caption, dir, filter, ...)
        if any(name.endswith(".QFileDialog."+a) or name.endswith("."+a) for a in FILED):
            if len(n.args) >= 2:
                cap = const_str(n.args[1])
                if cap: out.add(cap)
            if len(n.args) >= 4:
                flt = const_str(n.args[3])
                if flt: out.add(flt)
            continue

def main() -> int:
    out: set[str] = set()
    for root in ROOTS:
        if not root.exists():
            continue
        for p in root.rglob("*.py"):
            if skip(p):
                continue
            scan(p, out)

    items = sorted(s for s in out if s.strip())
    dest = Path("hevc_gui/resources/i18n/_marks_dialogs_auto.py")
    dest.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# -*- coding: utf-8 -*-\n",
        "# AUTO-GENERATED. Do not edit.\n",
        "from PyQt5.QtCore import QCoreApplication\n",
        "_ = QCoreApplication.translate\n",
        "CTX = '@dialog'\n\n",
    ]
    for s in items:
        lines.append(f"_(CTX, {s!r})\n")

    dest.write_text("".join(lines), encoding="utf-8")
    print(f"[scan] {len(items)} dialog strings -> {dest}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
