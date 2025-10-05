#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import argparse
import logging
from pathlib import Path

# --- Qt: attributi PRIMA di creare QApplication ---
from PyQt5.QtCore import (
    QCoreApplication,
    Qt,
    QEvent,
    QObject,
    qInstallMessageHandler,
    QtMsgType,
)
from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtGui import QIcon

# ===== Env “sicuri” =====
# usa qt5ct (se presente) e silenzia il warning del plugin
os.environ.setdefault("QT_QPA_PLATFORMTHEME", "qt5ct")
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.plugin=false")

# evita i dialoghi nativi (alcuni WM fanno i capricci)
QCoreApplication.setAttribute(Qt.AA_DontUseNativeDialogs, True)

# ======= Import progetto =======
# (stessa struttura del tuo file originale)
from hevc_gui.gui.main_window import MainWindow
from hevc_gui.gui.settings import load_window_size
from hevc_gui.gui.appearance_settings import apply_appearance
from hevc_gui.gui.menubar import apply_large_menu_icons
# ↑ questi moduli restano invariati


# ===========================
#  Qt → Python logging bridge
# ===========================
def _qt_message_handler(msg_type, context, message):
    """
    Porta i messaggi Qt nel logger Python (utile con --debug).
    """
    message = str(message)
    if msg_type in (QtMsgType.QtDebugMsg,):
        logging.debug("[Qt] %s", message)
    elif msg_type in (QtMsgType.QtInfoMsg,):
        logging.info("[Qt] %s", message)
    elif msg_type in (QtMsgType.QtWarningMsg,):
        logging.warning("[Qt] %s", message)
    elif msg_type in (QtMsgType.QtCriticalMsg,):
        logging.error("[Qt] %s", message)
    elif msg_type in (QtMsgType.QtFatalMsg,):
        logging.critical("[Qt] %s", message)
    else:
        logging.info("[Qt] %s", message)


# ====================
#  Font / Palette hook
# ====================
class FontEnforcer(QObject):
    """
    Come il tuo: applica font e palette dell’app ad ogni QWidget mostrato.
    """

    def __init__(self, font, palette):
        super().__init__()
        self.font = font
        self.palette = palette

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Show and isinstance(obj, QWidget):
            try:
                obj.setFont(self.font)
                obj.setPalette(self.palette)
            except Exception:
                pass
        return super().eventFilter(obj, event)


# ===============
#  Arg e logging
# ===============
def _parse_args(argv):
    p = argparse.ArgumentParser(description="HEVC-GUI launcher")
    p.add_argument("--debug", action="store_true", help="Log in DEBUG e Qt logs")
    p.add_argument("--log-file", default="", help="Percorso file log (opzionale)")
    return p.parse_args(argv)


def _setup_logging(debug: bool, log_file: str):
    lvl = logging.DEBUG if debug else logging.INFO
    fmt = "%(asctime)s %(levelname)-7s %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handlers = [logging.StreamHandler(sys.stdout)]
    if log_file:
        try:
            from logging.handlers import RotatingFileHandler

            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            handlers.append(RotatingFileHandler(str(log_path), maxBytes=2_000_000, backupCount=2))
        except Exception:
            # se non riesce a creare il file, va bene la console
            pass

    logging.basicConfig(level=lvl, format=fmt, datefmt=datefmt, handlers=handlers)

    # pulizia schermo come facevi tu
    logging.debug("=== Avvio applicazione: log ripulito ===")

    # hook dei messaggi Qt → logging
    qInstallMessageHandler(_qt_message_handler)

    # uncaught exceptions → logging
    def _excepthook(exc_type, exc, tb):
        logging.exception("Uncaught exception", exc_info=(exc_type, exc, tb))
        # termina con codice d’errore
        try:
            QApplication.quit()
        finally:
            os._exit(1)

    sys.excepthook = _excepthook


# =========
#  main()
# =========
def main():
    args = _parse_args(sys.argv[1:])
    _setup_logging(args.debug, args.log_file)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)

    # icona applicazione (se disponibile)
    icon_candidates = [
        "/usr/share/icons/hicolor/128x128/apps/hevc-gui.png",
        "/usr/share/pixmaps/hevc-gui.png",
    ]
    for icon_path in icon_candidates:
        if os.path.exists(icon_path):
            app.setWindowIcon(QIcon(icon_path))
            break

    # tema/aspetto
    apply_appearance(app)

    # font/palette coerenti ovunque
    enforcer = FontEnforcer(app.font(), app.palette())
    app.installEventFilter(enforcer)

    # finestra principale
    win = MainWindow()
    try:
        w, h = load_window_size()
        win.resize(w, h)
    except Exception:
        pass
    win.show()

    # piccoli tocchi post-show
    QApplication.processEvents()
    try:
        apply_large_menu_icons(app)
        apply_appearance(app)  # re-apply (come nel tuo file) per coerenza
    except Exception:
        pass

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
