#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, sys


def _add_local_path():
    mod_dir = os.path.dirname(os.path.abspath(__file__))
    if mod_dir not in sys.path:
        sys.path.insert(0, mod_dir)


def _apply_theme_from_env(app):
    """
    Eredita il tema dalla GUI principale quando LDVD viene lanciato da HEVC via QProcess.

    Variabili (tutte opzionali):
      - HEVC_QT_STYLE
      - HEVC_QT_FONT_FAMILY
      - HEVC_QT_FONT_SIZE
      - HEVC_ICON_THEME
      - HEVC_QT_STYLESHEET_FILE
    """
    style_applied = False

    # Qt style
    try:
        style = (os.environ.get("HEVC_QT_STYLE", "") or "").strip()
        if style:
            app.setStyle(style)
            style_applied = True
    except Exception:
        pass

    # Palette: se lo style arriva da HEVC, usa la palette standard di quello style
    # (non richiede modifiche a HEVC)
    if style_applied:
        try:
            pal = app.style().standardPalette()
            app.setPalette(pal)
        except Exception:
            pass

    # Font
    try:
        fam = (os.environ.get("HEVC_QT_FONT_FAMILY", "") or "").strip()
        psz = (os.environ.get("HEVC_QT_FONT_SIZE", "") or "").strip()
        if fam or psz:
            f = app.font()
            if fam:
                f.setFamily(fam)
            if psz:
                try:
                    f.setPointSize(int(float(psz)))
                except Exception:
                    pass
            app.setFont(f)
    except Exception:
        pass

    # Icon theme
    try:
        from PyQt5.QtGui import QIcon
        icon_theme = (os.environ.get("HEVC_ICON_THEME", "") or "").strip()
        if icon_theme:
            QIcon.setThemeName(icon_theme)
    except Exception:
        pass

    # Stylesheet (QSS)
    try:
        qss_file = (os.environ.get("HEVC_QT_STYLESHEET_FILE", "") or "").strip()
        if qss_file and os.path.exists(qss_file):
            with open(qss_file, "r", encoding="utf-8", errors="ignore") as f:
                app.setStyleSheet(f.read())
    except Exception:
        pass

def _resolve_dvd_extractor_controller():
    """
    Risolve DVDExtractorController in modo robusto.
    Se fallisce, ritorna (None, dettagli_errore).
    """
    import traceback

    # 1) import relativo (quando è modulo del package)
    try:
        from .controller import DVDExtractorController  # type: ignore
        return DVDExtractorController, ""
    except Exception:
        tb1 = traceback.format_exc()

    # 2) fallback: import locale (debug/standalone)
    try:
        _add_local_path()
        from controller import DVDExtractorController  # type: ignore
        return DVDExtractorController, ""
    except Exception:
        tb2 = traceback.format_exc()

    msg = (
        "Impossibile importare DVDExtractorController.\n\n"
        "Tentativo 1 (.controller):\n" + tb1 + "\n"
        "Tentativo 2 (controller locale):\n" + tb2
    )
    return None, msg

def main():
    # ---- Qt imports/attribs (HiDPI) ----
    try:
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QApplication, QWidget, QMainWindow, QMessageBox
        try:
            QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
            QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        except Exception:
            pass
    except Exception as e:
        print("PyQt5 non disponibile:", e, file=sys.stderr)
        return 1

    app = QApplication(sys.argv)
    try:
        app.setApplicationName("LDVD Ripper")
        app.setOrganizationName("LDVD")
    except Exception:
        pass

    # ✅ applica tema ereditato PRIMA di creare finestre/widget
    _apply_theme_from_env(app)

    def _excepthook(exc_type, exc, tb):
        import traceback
        txt = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            QMessageBox.critical(None, "Errore non gestito", txt)
        except Exception:
            print(txt, file=sys.stderr)

    sys.excepthook = _excepthook

    # --- Controller (robusto, niente NameError) ---
    Ctl, err = _resolve_dvd_extractor_controller()
    if Ctl is None:
        try:
            QMessageBox.critical(None, "Errore", err)
        except Exception:
            print(err, file=sys.stderr)
        return 1

    ctl = Ctl()
    ctl.show()

    # --- Azioni lossless opzionali (se presenti) ---
    attach_lossless_action = None
    register_quit_cleanup = None
    try:
        from .actions_lossless import attach_lossless_action, register_quit_cleanup
    except Exception:
        _add_local_path()
        try:
            from actions_lossless import attach_lossless_action, register_quit_cleanup  # type: ignore
        except Exception:
            pass

    win: QWidget | None = (
        getattr(ctl, "view", None)
        or getattr(ctl, "main_window", None)
        or getattr(ctl, "window", None)
        or None
    )
    if win is None:
        for w in app.topLevelWidgets():
            if isinstance(w, QMainWindow):
                win = w
                break

    if attach_lossless_action and win is not None:
        try:
            attach_lossless_action(win)
        except Exception:
            pass
    if register_quit_cleanup:
        try:
            register_quit_cleanup(app, win)
        except Exception:
            pass

    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
