# -*- coding: utf-8 -*-
# hevc_gui/gui/donate_menu.py
from __future__ import annotations

from pathlib import Path
from PyQt5.QtCore import QUrl
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QAction, QMenu, QMainWindow, QStyle, QToolBar
from PyQt5.QtGui import QDesktopServices


def _norm_title(s: str) -> str:
    return (s or "").replace("&", "").strip().lower()


def _find_menu(menubar, preferred_titles: tuple[str, ...]) -> QMenu | None:
    """Cerca un menu per titolo (case-insensitive, senza &)."""
    if not menubar:
        return None
    titles = tuple(t.lower() for t in preferred_titles)
    for act in menubar.actions():
        m = act.menu()
        if not m:
            continue
        if _norm_title(m.title()) in titles:
            return m
    return None


def _ensure_menu(menubar, title: str) -> QMenu | None:
    """Ritorna un QMenu con quel titolo, creandolo se serve (alla fine della menubar)."""
    m = _find_menu(menubar, (title,))
    if m:
        return m
    if menubar:
        m = QMenu(title, menubar)
        menubar.addMenu(m)
        return m
    return None


def install_donate_action(main: QMainWindow) -> None:
    """
    Aggiunge una voce 'Dona (PayPal)' **con icona ph_paypal.png**
    nel menu 'Aiuto' (o 'Help' / 'Info'). Se non esiste, crea un
    menu 'Aiuto'. Se c'è una toolbar, aggiunge anche lì l'azione.
    """
    menubar = main.menuBar() if hasattr(main, "menuBar") else None

    # Dove metterla? Preferenze: "Aiuto" → "Help" → "Info".
    target = _find_menu(menubar, ("aiuto", "help")) or _ensure_menu(menubar, "&Aiuto")

    # Icona (fallback safe se manca il file)
    icons_dir = Path(__file__).parent.parent / "resources" / "icons"
    pp_icon = icons_dir / "ph_paypal.png"
    icon = QIcon(str(pp_icon)) if pp_icon.exists() else main.style().standardIcon(QStyle.SP_DialogHelpButton)

    act = QAction(icon, "Dona (PayPal)", main)
    act.setToolTip("Apri la pagina PayPal per una donazione")
    act.setStatusTip("Apri la pagina PayPal per una donazione")
    act.setIconVisibleInMenu(True)
    act.triggered.connect(lambda: QDesktopServices.openUrl(QUrl("https://paypal.me/loris1159")))

    # Inserimento nel menu (sotto un separatore, vicino a Info/About se presente)
    if target:
        # prova a metterla dopo una voce tipo "Informazioni" / "About"
        placed = False
        about_aliases = ("informazioni", "info", "about")
        for a in target.actions():
            if _norm_title(a.text()) in about_aliases:
                target.insertAction(a, act)  # la mette PRIMA di "Informazioni"
                target.insertSeparator(a)
                placed = True
                break
        if not placed:
            if target.actions():
                target.addSeparator()
            target.addAction(act)
    else:
        # nessun menubar? niente paura: esponi l'azione in una toolbar se c'è
        pass

    # Aggiungi anche in toolbar, se esiste
    tb: QToolBar | None = getattr(main, "_menu_toolbar", None)
    if isinstance(tb, QToolBar):
        tb.addSeparator()
        tb.addAction(act)

    # Esponi per eventuale sync con _update_buttons_enabled()
    try:
        if hasattr(main, "_menu_actions") and isinstance(main._menu_actions, dict):
            main._menu_actions["donate"] = act
    except Exception:
        pass
