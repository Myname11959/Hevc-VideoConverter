from __future__ import annotations

import os
import sys
from typing import Callable, Optional

from PyQt5.QtCore import QSettings
from PyQt5.QtWidgets import QAction, QMessageBox, QStyle

LANG_KEY = "ui/lang"
LANG_IT = "it"
LANG_EN = "en"


def _embedded_lang_override() -> Optional[str]:
    env = (os.environ.get("HEVC_MKV_EMBEDDED", "") or "").strip().lower()
    if env not in ("1", "true", "yes", "on"):
        return None
    v = (os.environ.get("HEVC_LANG", "") or "").strip().lower()
    if v.startswith("en"):
        return LANG_EN
    if v.startswith("it"):
        return LANG_IT
    return None


def get_lang(settings: Optional[QSettings] = None) -> str:
    ov = _embedded_lang_override()
    if ov:
        return ov
    st = settings or QSettings()
    v = str(st.value(LANG_KEY, LANG_IT))
    return v if v in (LANG_IT, LANG_EN) else LANG_IT


def lang_label(lang: str, tr: Callable[[str], str]) -> str:
    return tr("Italiano") if lang == LANG_IT else tr("Inglese")


def restart_process() -> None:
    # ri-esegue lo stesso comando con cui è partita l'app (python3 main.py, launcher, ecc.)
    os.execv(sys.executable, [sys.executable] + sys.argv)


def restart_with_info(parent, title: str, text: str) -> None:
    QMessageBox.information(parent, title, text)
    restart_process()


def build_restart_action(parent, style, tr: Callable[[str], str], log: Optional[Callable[[str], None]] = None) -> QAction:
    lang = get_lang()
    act = QAction(style.standardIcon(QStyle.SP_BrowserReload), f"{tr('Riavvia')} ({lang_label(lang, tr)})", parent)
    if _embedded_lang_override() is not None:
        act.setVisible(False)
        act.setEnabled(False)

    def refresh_label() -> None:
        l = get_lang()
        act.setText(f"{tr('Riavvia')} ({lang_label(l, tr)})")

    def _do_restart() -> None:
        l = get_lang()
        msg = f"{tr('Riavvio dell’app in')} {lang_label(l, tr)}."
        if log:
            log(f"[UI] {msg}")
        restart_with_info(parent, tr("Riavvio"), msg)

    act.triggered.connect(_do_restart)
    # attach helper (comodo se in futuro vuoi aggiornare live)
    act._refresh_label = refresh_label  # type: ignore[attr-defined]
    return act
