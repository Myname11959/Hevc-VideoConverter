from __future__ import annotations

import os
from typing import Callable, Optional, Tuple

from PyQt5.QtCore import QSettings
from PyQt5.QtWidgets import QAction, QActionGroup, QMenu

from hevc_gui.mkv_suite.ui.restart_action import LANG_EN, LANG_IT, LANG_KEY, lang_label, restart_with_info


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


def set_lang(lang: str, settings: Optional[QSettings] = None) -> None:
    if _embedded_lang_override() is not None:
        return
    st = settings or QSettings()
    st.setValue(LANG_KEY, lang)


def _msg_for(lang: str) -> tuple[str, str]:
    """Titolo+messaggio dell’avviso nella lingua *target* (inversa rispetto alla UI corrente)."""
    if lang == LANG_EN:
        return (
            "Language",
            "Language set to: English.\nThe app will restart to apply it.",
        )
    return (
        "Lingua",
        "Lingua impostata: Italiano.\nL’app verrà riavviata per applicarla.",
    )


def install_language_menu(
    window,
    menubar,
    before_action,
    tr: Callable[[str], str] = lambda s: s,
    log: Optional[Callable[[str], None]] = None,
) -> Tuple[QMenu, QActionGroup]:
    """
    Menu 'Lingua' con Italiano/Inglese.
    Cambio lingua -> avviso (nella lingua selezionata) -> riavvio automatico.
    Persistenza in QSettings: ui/lang = it|en
    """
    # Nota: i testi del menu restano nella lingua corrente fino al riavvio (come HEVC).
    menu = QMenu(tr("Lingua"), window)

    grp = QActionGroup(menu)
    grp.setExclusive(True)

    act_it = QAction(tr("Italiano"), menu)
    act_it.setCheckable(True)
    act_it.setData(LANG_IT)

    act_en = QAction(tr("Inglese"), menu)
    act_en.setCheckable(True)
    act_en.setData(LANG_EN)

    grp.addAction(act_it)
    grp.addAction(act_en)
    menu.addAction(act_it)
    menu.addAction(act_en)

    cur = get_lang()
    (act_en if cur == LANG_EN else act_it).setChecked(True)

    def _apply(act: QAction) -> None:
        target = str(act.data() or "").strip()
        if target not in (LANG_IT, LANG_EN):
            return

        # salva scelta (persistente)
        set_lang(target)

        # avviso nella lingua target (cioè inversa rispetto a quella corrente)
        title, msg = _msg_for(target)

        if log:
            # log semplice (senza mischiare L())
            log(f"[UI] lingua -> {target} | {title}: {msg.replace(chr(10), ' ')}")

        restart_with_info(window, title, msg)

    grp.triggered.connect(_apply)

    if before_action is not None:
        menubar.insertMenu(before_action, menu)
    else:
        menubar.addMenu(menu)

    return menu, grp
