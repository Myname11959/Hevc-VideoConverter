#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

P = Path("hevc_gui/i18n.py")

MARK = "# --- i18n: apply QAction texts/tooltips (AUTO) ---"

CODE = r'''
# --- i18n: apply QAction texts/tooltips (AUTO) ---
def apply_actions_i18n(root_obj) -> None:
    """
    Traduce anche QAction (menù + toolbar) che Qt non traduce da solo.
    - action.text()
    - action.toolTip()
    - action.statusTip()
    - action.whatsThis()
    Ricorsivo dentro QMenu.
    """
    try:
        from PyQt5.QtWidgets import QMenu, QMenuBar, QToolBar
    except Exception:
        return

    # usa L() se disponibile (già nel tuo i18n), altrimenti no-op
    try:
        _L = L  # noqa: F821
    except Exception:
        def _L(s):  # type: ignore
            return s

    def _is_human(s: str) -> bool:
        if not s:
            return False
        t = s.strip()
        if not t or t in {"—", "…", "..."}:
            return False
        low = t.lower()
        if "ffmpeg" in low:
            return False
        # skip scorciatoie / tasti / risorse / path / estensioni
        if low.startswith(":/") or "/" in t:
            return False
        if any(x in t for x in ("Ctrl+", "Alt+", "Shift+")):
            return False
        if (len(t) <= 4 and t.upper().startswith("F") and t[1:].isdigit()):
            return False
        if t.startswith(".") and t[1:].isalnum():
            return False
        return any(ch.isalpha() for ch in t)

    def _tr_action(a) -> None:
        try:
            tx = a.text()
            if _is_human(tx):
                a.setText(_L(tx))
            tt = a.toolTip()
            if _is_human(tt):
                a.setToolTip(_L(tt))
            st = a.statusTip()
            if _is_human(st):
                a.setStatusTip(_L(st))
            wt = a.whatsThis()
            if _is_human(wt):
                a.setWhatsThis(_L(wt))
        except Exception:
            pass

    def _walk_menu(menu: QMenu) -> None:
        try:
            title = menu.title()
            if _is_human(title):
                menu.setTitle(_L(title))
        except Exception:
            pass

        for a in menu.actions():
            _tr_action(a)
            try:
                m = a.menu()
                if m is not None:
                    _walk_menu(m)
            except Exception:
                pass

    # menubar
    try:
        if hasattr(root_obj, "menuBar"):
            mb = root_obj.menuBar()
            if isinstance(mb, QMenuBar):
                for a in mb.actions():
                    _tr_action(a)
                    m = a.menu()
                    if m is not None:
                        _walk_menu(m)
    except Exception:
        pass

    # toolbars
    try:
        for tb in root_obj.findChildren(QToolBar):
            for a in tb.actions():
                _tr_action(a)
                m = a.menu()
                if m is not None:
                    _walk_menu(m)
    except Exception:
        pass

# patch non-invasiva: wrappo apply_i18n esistente senza toccare il suo corpo
try:
    _apply_i18n_orig = apply_i18n  # noqa: F821
    def apply_i18n(obj, *a, **kw):  # type: ignore
        r = _apply_i18n_orig(obj, *a, **kw)
        try:
            apply_actions_i18n(obj)
        except Exception:
            pass
        return r
except Exception:
    pass
'''

def main() -> int:
    if not P.exists():
        print(f"ERRORE: non trovo {P}")
        return 2

    src = P.read_text(encoding="utf-8", errors="replace")
    if MARK in src:
        print("[OK] i18n.py già patchato (QAction).")
        return 0

    # backup
    (Path("'"+""+"'") )
    return 0

if __name__ == "__main__":
    p = Path("hevc_gui/i18n.py")
    src = p.read_text(encoding="utf-8", errors="replace")
    if MARK in src:
        print("[OK] i18n.py già patchato (QAction).")
        raise SystemExit(0)
    bak = Path("/tmp") / f"i18n.py.bak_actions_{__import__('time').time_ns()}"
    bak.write_text(src, encoding="utf-8")
    print("Backup:", bak)

    p.write_text(src.rstrip() + "\n\n" + CODE.strip() + "\n", encoding="utf-8")
    print("[CHANGED] aggiunto supporto QAction in i18n.py")

