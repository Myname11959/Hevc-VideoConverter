# -*- coding: utf-8 -*-
"""
Dialog 'Informazioni…' (About) con pulsante 'Dona (PayPal)'.
Integra l'About ESISTENTE: prova ad "agganciare" l'azione/icona About già in GUI.
Non crea nuove voci di menu.
"""

from __future__ import annotations

from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QAction,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QToolBar,
    QMenu,
)

# Parametri base (fallback sicuri se non presenti in constants)
try:
    from hevc_gui.core.constants import DONATE_URL  # type: ignore
except Exception:
    DONATE_URL = "https://paypal.me/loris1159"

try:
    from hevc_gui.core.constants import APP_NAME  # type: ignore
except Exception:
    APP_NAME = "HEVC – Video Converter"

try:
    from hevc_gui.core.constants import APP_VERSION  # type: ignore
except Exception:
    APP_VERSION = ""


def _open_url(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))


def make_about_dialog(parent) -> QDialog:
    dlg = QDialog(parent)
    dlg.setWindowTitle(f"Informazioni su {APP_NAME}")
    dlg.setModal(True)

    v = QVBoxLayout(dlg)
    v.setContentsMargins(16, 16, 16, 16)
    v.setSpacing(10)

    title = QLabel(f"<b>{APP_NAME}</b> {APP_VERSION}")
    title.setTextFormat(Qt.RichText)
    title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

    desc = QLabel(
        "App Qt per convertire video in <b>HEVC/x265</b> con controllo fine su video e audio.<br>"
        "Linux-first, genera comandi <code>ffmpeg</code> riproducibili."
    )
    desc.setTextFormat(Qt.RichText)
    desc.setWordWrap(True)
    desc.setOpenExternalLinks(True)

    donate_btn = QPushButton("Dona (PayPal)")
    donate_btn.setCursor(Qt.PointingHandCursor)
    donate_btn.setToolTip("Apri la pagina PayPal per una donazione")
    donate_btn.clicked.connect(lambda: _open_url(DONATE_URL))
    donate_btn.setStyleSheet(
        """
        QPushButton {
            background-color: #0070ba;
            color: white;
            border: none;
            border-radius: 6px;
            padding: 6px 10px;
            font-weight: 600;
        }
        QPushButton:hover { background-color: #0b7dda; }
        QPushButton:pressed { background-color: #005c97; }
        """
    )

    h_badge = QHBoxLayout()
    h_badge.addWidget(donate_btn, 0, Qt.AlignLeft)
    h_badge.addStretch(1)

    links = QLabel(
        'Sorgenti e licenza: vedi <code>README.md</code> e <code>LICENSE</code> nel repository.'
    )
    links.setTextFormat(Qt.RichText)
    links.setWordWrap(True)

    btn_box = QDialogButtonBox(QDialogButtonBox.Close, parent=dlg)
    btn_box.rejected.connect(dlg.reject)
    btn_box.accepted.connect(dlg.accept)

    v.addWidget(title)
    v.addWidget(desc)
    v.addLayout(h_badge)
    v.addWidget(links)
    v.addSpacing(6)
    v.addWidget(btn_box, 0, Qt.AlignRight)

    return dlg


def show_about_dialog(parent) -> None:
    dlg = make_about_dialog(parent)
    dlg.exec_()


def attach_to_existing_about(window) -> bool:
    """
    Reindirizza l'azione/icona About ESISTENTE alla nuova dialog.
    Non crea nuove voci. Ritorna True se ha agganciato qualcosa.
    """
    hooked = False
    keys = ("informazioni", "about", "info", "?")

    # 1) Se esiste un metodo _on_about → lo sovrascrivo in modo soft
    if hasattr(window, "_on_about"):
        def _open():  # noqa: N802
            show_about_dialog(window)
        try:
            window._on_about = _open  # type: ignore[attr-defined]
            hooked = True
        except Exception:
            pass

    # 2) Scansione menù e toolbar per azioni "About"
    #    - disconnetto eventuali handler e collego alla nuova dialog
    def matches_about(act: QAction) -> bool:
        t = (act.text() or "").strip().lower()
        tip = (act.toolTip() or "").strip().lower()
        name = (act.objectName() or "").strip().lower()
        return (
            any(k in t for k in keys)
            or any(k in tip for k in keys)
            or "about" in name
            or "informazioni" in name
        )

    # Menù
    menubar = None
    mb_attr = getattr(window, "menuBar", None)
    if callable(mb_attr):
        menubar = mb_attr()

    if menubar is not None:
        for menu in menubar.findChildren(QMenu):
            for act in menu.actions():
                if matches_about(act):
                    try:
                        act.triggered.disconnect()  # rimuove collegamenti precedenti
                    except Exception:
                        pass
                    act.triggered.connect(lambda _=False: show_about_dialog(window))
                    hooked = True

    # Toolbar
    for tb in window.findChildren(QToolBar):
        for act in tb.actions():
            if matches_about(act):
                try:
                    act.triggered.disconnect()
                except Exception:
                    pass
                act.triggered.connect(lambda _=False: show_about_dialog(window))
                hooked = True

    return hooked
