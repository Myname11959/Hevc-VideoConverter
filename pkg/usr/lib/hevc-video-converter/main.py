#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import argparse
import logging
from pathlib import Path

# Qt: attributi PRIMA di creare QApplication
from PyQt5.QtCore import QCoreApplication, Qt, QEvent, QObject, qInstallMessageHandler, QtMsgType
from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtGui import QIcon, QGuiApplication

# Import progetto
from hevc_gui.gui.main_window import MainWindow
from hevc_gui.gui.settings import load_window_size
from hevc_gui.gui.appearance_settings import apply_appearance
from hevc_gui.gui.menubar import apply_large_menu_icons
import hevc_gui.resources.icons_rc  # QRC icone

APP_SLUG = "hevc-video-converter"          # slug tecnico ovunque
APP_DISPLAY_NAME = "HEVC – Video Converter"

# ========== Qt → Python logging ==========
def _qt_message_handler(msg_type, context, message):
    m = str(message)
    if msg_type == QtMsgType.QtDebugMsg:
        logging.debug("[Qt] %s", m)
    elif msg_type == QtMsgType.QtInfoMsg:
        logging.info("[Qt] %s", m)
    elif msg_type == QtMsgType.QtWarningMsg:
        logging.warning("[Qt] %s", m)
    elif msg_type == QtMsgType.QtCriticalMsg:
        logging.error("[Qt] %s", m)
    elif msg_type == QtMsgType.QtFatalMsg:
        logging.critical("[Qt] %s", m)
    else:
        logging.info("[Qt] %s", m)

class FontEnforcer(QObject):
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

def _parse_args(argv):
    p = argparse.ArgumentParser(description=f"{APP_DISPLAY_NAME} launcher")
    p.add_argument("--debug", action="store_true", help="Log in DEBUG e Qt logs")
    p.add_argument("--log-file", default="", help="Percorso file log (opzionale)")
    return p.parse_args(argv)

def _setup_logging(debug: bool, log_file: str):
    lvl = logging.DEBUG if debug else logging.INFO
    fmt = "%(asctime)s %(levelname)-7s %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    for h in logging.root.handlers[:]:
        logging.root.removeHandler(h)
    handlers = [logging.StreamHandler(sys.stdout)]
    if log_file:
        try:
            from logging.handlers import RotatingFileHandler
            log_path = Path(log_file); log_path.parent.mkdir(parents=True, exist_ok=True)
            handlers.append(RotatingFileHandler(str(log_path), maxBytes=2_000_000, backupCount=2))
        except Exception:
            pass
    logging.basicConfig(level=lvl, format=fmt, datefmt=datefmt, handlers=handlers)
    logging.debug("=== Avvio applicazione: log ripulito ===")
    qInstallMessageHandler(_qt_message_handler)
    def _excepthook(exc_type, exc, tb):
        logging.exception("Uncaught exception", exc_info=(exc_type, exc, tb))
        try:
            QApplication.quit()
        finally:
            os._exit(1)
    sys.excepthook = _excepthook

def main():
    args = _parse_args(sys.argv[1:])
    _setup_logging(args.debug, args.log_file)

    # Allineamento WM_CLASS ↔ .desktop ↔ pannello Cinnamon
    QCoreApplication.setApplicationName(APP_SLUG)
    QGuiApplication.setDesktopFileName(f"{APP_SLUG}.desktop")

    app = QApplication(sys.argv)

    # Icona finestra SEMPRE da QRC (stabile, niente CRC)
    app.setWindowIcon(QIcon(":/icons/logo.png"))
    app.setQuitOnLastWindowClosed(True)

    # Tema/aspetto
    apply_appearance(app)

    # font/palette coerenti ovunque
    enforcer = FontEnforcer(app.font(), app.palette())
    app.installEventFilter(enforcer)

    # Finestra principale
    win = MainWindow()
    try:
        w, h = load_window_size()
        win.resize(w, h)
    except Exception:
        pass
    win.setWindowTitle(APP_DISPLAY_NAME)  # barra del titolo coerente
    win.setWindowIcon(QIcon(":/icons/logo.png"))  # tasklist/pannello sicuro
    win.show()

    # Post-show
    QApplication.processEvents()
    try:
        apply_large_menu_icons(app)
        apply_appearance(app)
    except Exception:
        pass

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
