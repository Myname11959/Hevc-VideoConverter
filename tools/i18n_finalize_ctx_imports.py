#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/i18n_finalize_ctx_imports.py

Finalizza i file dopo i wrap tipo: tr(CTX, "...") / ftr(CTX, "...").

Cosa fa per ogni .py:
- calcola automaticamente il contesto CTX dalla path (es. hevc_gui/gui/main_window.py -> "hevc_gui.gui.main_window")
- se nel file trova tr(CTX, ...) e CTX manca, inserisce:
    CTX = "..."
- se trova chiamate a tr(...) (non QtCore.QCoreApplication.translate) e manca tr callable a livello modulo,
  inserisce:
    from PyQt5.QtCore import QCoreApplication
    tr = QCoreApplication.translate
- se trova ftr(...) e manca, inserisce:
    def ftr(ctx, s, **kw): return tr(ctx, s).format(**kw)

Ha anche --dry-run con diff.
"""

from __future__ import annotations

import argparse
import difflib
import os
import re
from pathlib import Path
from typing import Iterable, Tuple


RX_CALL_TR = re.compile(r"(?<!\.)\btr\s*\(")     # tr( ... ) non preceduto da "."
RX_CALL_FTR = re.compile(r"(?<!\.)\bftr\s*\(")
RX_CALL_TR_CTX = re.compile(r"(?<!\.)\btr\s*\(\s*CTX\s*,")
RX_CALL_FTR_CTX = re.compile(r"(?<!\.)\bftr\s*\(\s*CTX\s*,")

RX_HAS_CTX = re.compile(r"(?m)^\s*CTX\s*=\s*['\"]")
RX_HAS_TR_TOP = re.compile(r"(?m)^\s*tr\s*=")          # potrebbe essere anche indentato
RX_HAS_TR_TOPLEVEL = re.compile(r"(?m)^tr\s*=")        # SOLO livello modulo
RX_HAS_FTR_DEF = re.compile(r"(?m)^\s*def\s+ftr\s*\(")

RX_IMPORT_QCORE = re.compile(r"(?m)^\s*from\s+PyQt5\.QtCore\s+import\s+.*\bQCoreApplication\b")
RX_IMPORT_PYQT5_QTCORE = re.compile(r"(?m)^\s*from\s+PyQt5\s+import\s+QtCore\b")
RX_QCOREAPP_USED = re.compile(r"\bQCoreApplication\b")

SKIP_SUFFIXES = (
    ".bak",
    ".orig",
    ".bak_i18n",
)

def iter_py_files(paths: Iterable[Path]) -> Iterable[Path]:
    for p in paths:
        if p.is_dir():
            for f in p.rglob("*.py"):
                yield f
        elif p.is_file() and p.suffix == ".py":
            yield p


def rel_module_ctx(repo_root: Path, file_path: Path) -> str | None:
    """
    Ritorna il module context stile python, partendo dalla path relativa al repo.
    Esempi:
      hevc_gui/gui/main_window.py -> hevc_gui.gui.main_window
      hevc_gui/gui/__init__.py -> hevc_gui.gui
    """
    try:
        rel = file_path.resolve().relative_to(repo_root.resolve())
    except Exception:
        return None

    parts = list(rel.parts)
    if not parts:
        return None

    # vogliamo solo roba sotto hevc_gui/
    if parts[0] != "hevc_gui":
        return None

    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1].removesuffix(".py")

    return ".".join(parts)


def find_insertion_index(lines: list[str]) -> int:
    """
    Punto di inserimento sicuro:
      - dopo shebang/encoding
      - dopo eventuale docstring di modulo
      - DOPO eventuali "from __future__ import ..." (anche se preceduti da commenti/blank)

    Importante: non deve MAI inserire codice prima dei future import,
    altrimenti Python solleva:
      SyntaxError: from __future__ imports must occur at the beginning of the file
    """
    i = 0
    n = len(lines)

    # shebang
    if i < n and lines[i].startswith("#!"):
        i += 1

    # encoding comment (prima/seconda riga tipicamente)
    if i < n and re.search(r"coding[:=]\s*utf-8", lines[i]):
        i += 1
    elif i + 1 < n and re.search(r"coding[:=]\s*utf-8", lines[i + 1]):
        i += 2

    # salta righe vuote (ma NON commenti: li vogliamo preservare dove sono)
    while i < n and lines[i].strip() == "":
        i += 1

    # docstring ("""...""" oppure '''...''') immediato
    if i < n and (lines[i].lstrip().startswith('"""') or lines[i].lstrip().startswith("'''")):
        quote = '"""' if '"""' in lines[i] else "'''"
        if lines[i].count(quote) >= 2:
            i += 1
        else:
            i += 1
            while i < n:
                if quote in lines[i]:
                    i += 1
                    break
                i += 1

    # Cerca future import nella "testa" del file, ignorando commenti/blank.
    j = i
    last_future_end = None
    while j < n:
        s = lines[j].strip()
        if s == "" or s.startswith("#"):
            j += 1
            continue
        if re.match(r"^\s*from\s+__future__\s+import\s+", lines[j]):
            last_future_end = j + 1
            j += 1
            continue
        break

    return last_future_end if last_future_end is not None else i

def ensure_block(text: str, ctx: str) -> Tuple[str, int]:
    """
    Ritorna (new_text, changed_count).
    """
    # quick filters
    if any(text.endswith(suf) for suf in SKIP_SUFFIXES):
        return text, 0

    needs_ctx = bool(RX_CALL_TR_CTX.search(text) or RX_CALL_FTR_CTX.search(text))
    needs_tr = bool(RX_CALL_TR.search(text))
    needs_ftr = bool(RX_CALL_FTR.search(text))

    if not (needs_ctx or needs_tr or needs_ftr):
        return text, 0

    changed = 0
    lines = text.splitlines(keepends=True)

    insert_lines: list[str] = []

    # 1) CTX
    if needs_ctx and not RX_HAS_CTX.search(text):
        insert_lines.append(f'CTX = "{ctx}"\n')
        changed += 1

    # 2) tr alias
    # Se c'è già un tr a livello modulo (es. tr = QTranslator()), NON tocchiamo.
    # Se c'è solo tr indentato (dentro funzioni), noi aggiungiamo comunque un tr globale (utile).
    has_tr_toplevel = bool(RX_HAS_TR_TOPLEVEL.search(text))
    if needs_tr and not has_tr_toplevel:
        # import QCoreApplication se manca
        if not RX_IMPORT_QCORE.search(text):
            insert_lines.append("from PyQt5.QtCore import QCoreApplication\n")
            changed += 1
        # alias tr se non esiste già (anche indentato) — ma se c'è indentato, va bene uguale, aggiungiamo globale.
        insert_lines.append("tr = QCoreApplication.translate\n")
        changed += 1

    # 3) ftr helper
    if needs_ftr and not RX_HAS_FTR_DEF.search(text):
        # garantisci che tr ci sia (se non lo abbiamo aggiunto, ma magari c'è già toplevel tr=...)
        if not has_tr_toplevel and "tr = QCoreApplication.translate\n" not in insert_lines:
            if not RX_IMPORT_QCORE.search(text):
                insert_lines.append("from PyQt5.QtCore import QCoreApplication\n")
                changed += 1
            insert_lines.append("tr = QCoreApplication.translate\n")
            changed += 1

        insert_lines.append(
            "\n"
            "def ftr(ctx: str, s: str, **kw) -> str:\n"
            '    """Translate + format (kwargs)."""\n'
            "    return tr(ctx, s).format(**kw)\n"
        )
        changed += 1

    if not insert_lines:
        return text, 0

    # Inserisci blocco con separatori (idempotente: se CTX c'è già, non reinserisce)
    idx = find_insertion_index(lines)
    block = []
    block.append("\n" if (idx > 0 and (not lines[idx - 1].endswith("\n") or lines[idx - 1].strip() != "")) else "")
    block.append("# --- i18n (auto) ---------------------------------------------------------\n")
    block.extend(insert_lines)
    block.append("# ------------------------------------------------------------------------\n\n")

    new_lines = lines[:idx] + block + lines[idx:]
    new_text = "".join(new_lines)
    return new_text, changed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Mostra diff, non scrive")
    ap.add_argument("--repo-root", default=".", help="Root repo (default: .)")
    ap.add_argument("paths", nargs="+", help="File o directory da processare")
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    paths = [Path(p) for p in args.paths]

    total_files = 0
    total_changed = 0

    for f in iter_py_files(paths):
        # skip backup-like
        if any(str(f).endswith(suf) for suf in SKIP_SUFFIXES):
            continue
        if "__pycache__" in f.parts:
            continue

        ctx = rel_module_ctx(repo_root, f)
        if not ctx:
            continue

        try:
            old = f.read_text(encoding="utf-8")
        except Exception:
            continue

        new, changed = ensure_block(old, ctx)
        if changed <= 0 or new == old:
            continue

        total_files += 1
        total_changed += changed

        if args.dry_run:
            diff = difflib.unified_diff(
                old.splitlines(),
                new.splitlines(),
                fromfile=str(f),
                tofile=str(f) + " (i18n+)",
                lineterm="",
            )
            print("\n".join(diff))
        else:
            f.write_text(new, encoding="utf-8")
            print(f"[OK] {f}: inserted {changed} block item(s)")

    if args.dry_run:
        print(f"\n[dry-run] Files changed: {total_files} | Total insert items: {total_changed}")
    else:
        print(f"\nFiles changed: {total_files} | Total insert items: {total_changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
