#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import ast
import subprocess
from pathlib import Path

UI_ATTRS = {
    "setText","setTitle","setWindowTitle","setToolTip","setStatusTip","setPlaceholderText",
    "showMessage","append","appendPlainText","insertPlainText",
    "addMenu","addAction","setTabText","setHeaderData","setItemText",
}
MSGBOX = {"information","warning","critical","question"}

def _is_wrapped(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"L","T"}

def _extract_str(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):  # f-string: solo parti costanti
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                parts.append(v.value)
        s = "".join(parts)
        return s if s else None
    return None

def _looks_user_text(s: str) -> bool:
    s = (s or "").strip()
    if not s:
        return False
    # evita roba tecnica
    if s.startswith(("scale=","ffmpeg","x265","hevc_gui.")):
        return False
    # segnali tipici di ITA
    if any(ch in s for ch in "àèéìòùÀÈÉÌÒÙ"):
        return True
    hot = ("Conferma","Sei sicuro","Avvio","Impossibile","Errore","Cassetto","Nessun","Pronto")
    return any(w in s for w in hot)

def main():
    out = subprocess.check_output(["git","ls-files","-z","*.py"])
    files = [f.decode("utf-8") for f in out.split(b"\0") if f]
    files = [f for f in files if not f.startswith("backup/")]

    hits = []
    for f in files:
        p = Path(f)
        try:
            src = p.read_text(encoding="utf-8")
            tree = ast.parse(src, filename=f)
        except Exception:
            continue

        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue

            func = n.func
            name = None
            if isinstance(func, ast.Attribute):
                name = func.attr
            elif isinstance(func, ast.Name):
                name = func.id
            if not name:
                continue

            # QMessageBox.xxx(self/view, "Title", "Text", ...)
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "QMessageBox" and name in MSGBOX:
                for idx in (1,2):
                    if len(n.args) > idx and not _is_wrapped(n.args[idx]):
                        s = _extract_str(n.args[idx])
                        if s and _looks_user_text(s):
                            hits.append((f, n.lineno, f"QMessageBox.{name}", s.strip()))
                continue

            # widget.setText("...") ecc
            if name in UI_ATTRS:
                for a in n.args[:2]:
                    if _is_wrapped(a):
                        continue
                    s = _extract_str(a)
                    if s and _looks_user_text(s):
                        hits.append((f, n.lineno, name, s.strip()))

    print("HITS =", len(hits))
    for f, ln, kind, s in hits:
        print(f"{f}:{ln}: {kind}: {s}")

if __name__ == "__main__":
    main()
