#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hevc_gui/gui/menubar.py

- Menubar + toolbar (icone QRC/tema)
- Tutte le stringhe passano da L() -> traducibili.
- Menu Lingua unico, azioni esclusive, avviso + restart.
- FIX: forza icone visibili nei menu (GNOME spesso le nasconde).
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import TYPE_CHECKING

from PyQt5.QtCore import QSize, Qt, QUrl, QProcess, QFile
from PyQt5.QtGui import QIcon, QDesktopServices
from PyQt5.QtWidgets import (
    QAction, QActionGroup, QApplication, QMenuBar, QMessageBox, QProxyStyle,
    QStyle, QToolBar, QToolButton
)

from hevc_gui.i18n import L, get_lang, set_lang, restart_app


# QRC icons: assicurati che le risorse Qt siano registrate anche in dev-run
try:
    import hevc_gui.resources.icons_rc  # noqa: F401
except Exception:
    pass

if TYPE_CHECKING:
    from .main_window import MainWindow


# ───────────────────────────────────────────────────────────────
# Stile: forza icone nei menu (e dimensione icone)
# ───────────────────────────────────────────────────────────────
class LargeMenuStyle(QProxyStyle):
    def __init__(self, base=None):
        super().__init__(base)

    def styleHint(self, hint, option=None, widget=None, returnData=None):
        # GNOME/Adwaita spesso ritorna True qui → niente icone nei menu
        if hint == getattr(QStyle, 'SH_DontShowIconsInMenus', -1):
            return 0
        return super().styleHint(hint, option, widget, returnData)

    def pixelMetric(self, metric, option=None, widget=None):
        if metric == QStyle.PM_SmallIconSize:
            return 32
        return super().pixelMetric(metric, option, widget)


def apply_large_menu_icons(app: QApplication | None):
    app = app or QApplication.instance()
    if not app:
        return
    try:
        app.setAttribute(Qt.AA_DontShowIconsInMenus, False)
    except Exception:
        pass
    try:
        app.setStyle(LargeMenuStyle(app.style()))
    except Exception:
        app.setStyle(LargeMenuStyle())


# ───────────────────────────────────────────────────────────────
# Icone
# ───────────────────────────────────────────────────────────────
ICON_ALIASES = {
    "open": ["document-open", "open"],
    "save": ["document-save", "save"],
    "convert": ["media-playback-start", "run", "convert"],
    "extract": ["audio-x-generic", "extract"],
    "subs": ["text-subtitle", "insert-text", "edit", "text-x-generic", "subs"],
    "chapters": ["media-optical", "view-list", "go-next", "bookmark", "chapters"],
    "queue_run": ["system-run", "run"],
    "edit_queue": ["edit-paste", "edit"],
    "minfo": ["dialog-information", "help-about", "info"],
    "preview": ["video-x-generic", "preview"],
    "preview_filtered": ["video-x-generic", "preview"],
    "exit": ["application-exit", "exit"],
    "asp": ["preferences-system", "preferences-desktop", "asp"],
    "user_manual": ["help-contents", "help-browser", "help", "manual"],
    "info": ["help-about", "dialog-information", "info"],
    "trim": ["edit-cut", "media-seek-forward", "trim"],
    "crop": ["transform-crop", "crop"],
    "color": ["preferences-desktop-color", "color"],
    "dvdrip": ["media-optical", "drive-optical", "media-optical-dvd", "dvdrip"],
    "restart": ["view-refresh", "system-reboot", "restart"],
    "paypal": ["paypal", "help-donate", "emblem-favorite"],
    "send": ["document-send", "mail-send", "send"],
}

LOCAL_ICON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "resources", "icons"))


def _qrc_icon_try(name: str) -> QIcon:
    """Carica icone SOLO dal QRC ufficiale: :/icons/ph_<name>.png oppure :/icons/<name>.png"""
    if not name:
        return QIcon()
    for base in (f"ph_{name}", name):
        p = f":/icons/{base}.png"
        if QFile.exists(p):
            return QIcon(p)
    return QIcon()


def _local_icon_try(name: str) -> QIcon:
    if not name:
        return QIcon()
    for base in (f"ph_{name}.png", f"{name}.png"):
        p = os.path.join(LOCAL_ICON_DIR, base)
        if os.path.exists(p):
            return QIcon(p)
    return QIcon()


def _themed_icon_with_aliases(key: str) -> QIcon:
    if not key:
        return QIcon()
    # 1) Tema (solo se NON stai usando il pack interno HEVC)
    use_theme = (os.environ.get("HEVC_ICON_PACK", "theme") != "qrc")
    if use_theme:
        for nm in ICON_ALIASES.get(key, [key]):
            ic = QIcon.fromTheme(nm)
            if not ic.isNull():
                return ic
    # 2) QRC
    ic = _qrc_icon_try(key)
    if not ic.isNull():
        return ic
    for nm in ICON_ALIASES.get(key, []):
        ic = _qrc_icon_try(nm)
        if not ic.isNull():
            return ic

    # 3) PNG locali (fallback)
    ic = _local_icon_try(key)
    if not ic.isNull():
        return ic
    for nm in ICON_ALIASES.get(key, []):
        ic = _local_icon_try(nm)
        if not ic.isNull():
            return ic

    return QIcon()


def _finalize_toolbar_buttons(tb: QToolBar, icon_px: int = 32) -> None:
    for b in tb.findChildren(QToolButton):
        b.setAutoRaise(True)
        b.setToolButtonStyle(Qt.ToolButtonIconOnly)
        b.setIconSize(QSize(icon_px, icon_px))
        b.setFixedSize(icon_px, icon_px)
        b.setFocusPolicy(Qt.NoFocus)
        b.setCursor(Qt.PointingHandCursor)


def _restart_app_prompt(win: "MainWindow") -> None:
    res = QMessageBox.question(
        win,
        L("Riavvia…"),
        L("Vuoi riavviare HEVC?\n\nLo stato corrente (file/queue) verrà perso."),
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No,
    )
    if res == QMessageBox.Yes:
        restart_app()


def _open_appearance_dialog(win: "MainWindow") -> None:
    try:
        from .appearance_dialog import AppearanceDialog  # lazy import (anti-cicli)
        dlg = AppearanceDialog(parent=win)
        dlg.exec_()
    except Exception as e:
        QMessageBox.warning(win, L("Errore"), L("Impossibile aprire Aspetto…:\n{0}").format(e))


def _safe_call(win, name: str, *a, **k):
    fn = getattr(win, name, None)
    if callable(fn):
        return fn(*a, **k)
    QMessageBox.warning(win, L("Errore"), L("Azione non disponibile: {0}").format(name))
    return None


def setup_menubar(win: "MainWindow") -> QMenuBar:
    apply_large_menu_icons(QApplication.instance())

    menubar = QMenuBar(win)

    # — FILE —
    m_file = menubar.addMenu(L("&File"))

    act_open = QAction(_themed_icon_with_aliases("open"), L("Apri video…"), win,
                       shortcut="Ctrl+O", triggered=lambda: _safe_call(win, "open_file"))
    act_open.setProperty("icon_name", "open")

    act_restart = QAction(_themed_icon_with_aliases("restart"), L("Riavvia…"), win,
                          shortcut="Ctrl+Shift+R", triggered=lambda: _restart_app_prompt(win))
    act_restart.setProperty("icon_name", "restart")

    act_exit = QAction(_themed_icon_with_aliases("exit"), L("Esci"), win,
                       shortcut="Ctrl+Q", triggered=lambda: _safe_call(win, "exit_app"))
    act_exit.setProperty("icon_name", "exit")

    m_file.addAction(act_open)
    m_file.addAction(act_restart)
    m_file.addSeparator()
    m_file.addAction(act_exit)

    # — AZIONI —
    m_actions = menubar.addMenu(L("&Azioni"))

    act_convert = QAction(_themed_icon_with_aliases("convert"), L("Converti"), win,
                          shortcut="Ctrl+Return", triggered=lambda: _safe_call(win, "on_convert_clicked"))
    act_convert.setProperty("icon_name", "convert")

    act_extract = QAction(_themed_icon_with_aliases("extract"), L("Estrai audio"), win,
                          triggered=lambda: _safe_call(win, "extract_audio"))
    act_extract.setProperty("icon_name", "extract")

    act_subs = QAction(_themed_icon_with_aliases("subs"), L("Sottotitoli…"), win,
                       triggered=lambda: _safe_call(win, "on_subtitle_clicked"))
    act_subs.setProperty("icon_name", "subs")

    act_chapters = QAction(_themed_icon_with_aliases("chapters"), L("Capitoli…"), win,
                           triggered=lambda: _safe_call(win, "on_chapter_clicked"))
    act_chapters.setProperty("icon_name", "chapters")

    act_queue_run = QAction(_themed_icon_with_aliases("queue_run"), L("Elabora coda"), win,
                            shortcut="F9", triggered=lambda: _safe_call(win, "start_queue_processing"))
    act_queue_run.setProperty("icon_name", "queue_run")

    act_save = QAction(_themed_icon_with_aliases("save"), L("Salva coda"), win,
                       shortcut="Ctrl+S", triggered=lambda: _safe_call(win, "save_gui_queue_to_file"))
    act_save.setProperty("icon_name", "save")

    act_edit_queue = QAction(_themed_icon_with_aliases("edit_queue"), L("Gestisci coda"), win,
                             triggered=lambda: _safe_call(win, "open_queue_manager"))
    act_edit_queue.setProperty("icon_name", "edit_queue")

    m_actions.addActions([act_convert, act_extract, act_subs, act_chapters, act_queue_run, act_save, act_edit_queue])

    # — STRUMENTI —
    m_tools = menubar.addMenu(L("&Strumenti"))

    act_minfo = QAction(_themed_icon_with_aliases("minfo"), L("MediaInfo"), win,
                        triggered=lambda: _safe_call(win, "show_mediainfo"))
    act_minfo.setProperty("icon_name", "minfo")

    act_preview = QAction(_themed_icon_with_aliases("preview"), L("Preview"), win,
                          triggered=lambda: _safe_call(win, "launch_preview", False))
    act_preview.setProperty("icon_name", "preview")

    act_preview_filtered = QAction(_themed_icon_with_aliases("preview_filtered"), L("Preview filtrata"), win,
                                   triggered=lambda: _safe_call(win, "launch_preview", True))
    act_preview_filtered.setProperty("icon_name", "preview_filtered")

    act_crop = QAction(_themed_icon_with_aliases("crop"), L("Imposta crop…"), win,
                       triggered=lambda: _safe_call(win, "open_crop_tool"))
    act_crop.setProperty("icon_name", "crop")
    act_crop.setEnabled(False)

    act_color = QAction(_themed_icon_with_aliases("color"), L("Color…"), win,
                        triggered=lambda: _safe_call(win, "open_color_tool"))
    act_color.setProperty("icon_name", "color")
    act_color.setEnabled(False)

    act_trim = QAction(_themed_icon_with_aliases("trim"), L("Trim…"), win,
                       triggered=lambda: _safe_call(win, "open_trim_tool"))
    act_trim.setProperty("icon_name", "trim")
    act_trim.setEnabled(False)

    act_dvd = QAction(_themed_icon_with_aliases("dvdrip"), L("DVD Ripper…"), win,
                      triggered=lambda: _safe_call(win, "open_dvd_ripper"))
    act_dvd.setProperty("icon_name", "dvdrip")

    m_tools.addActions([act_minfo, act_preview, act_preview_filtered])
    m_tools.addSeparator()
    m_tools.addActions([act_crop, act_color, act_trim])
    m_tools.addSeparator()
    m_tools.addAction(act_dvd)

    # --- MKV Suite (embedded-only) ---
    def _open_mkv_suite():
        try:
            cmd = [sys.executable, "-m", "hevc_gui.mkv_suite.shells.embedded_app", "--embedded"]
            env = os.environ.copy()
            # Ensure hevc_gui is importable in subprocess (installed .deb uses local sys.path)
            try:
                from pathlib import Path as _P
                _pkg = _P(__file__).resolve().parents[2]  # .../hevc_gui
                _root = str(_pkg)  # /usr/lib/hevc-video-converter (serve per import hevc_gui nel subprocess)                 # parent dir to add on PYTHONPATH
                _pp = env.get('PYTHONPATH', '')
                env['PYTHONPATH'] = _root + (os.pathsep + _pp if _pp else '')
            except Exception:
                pass
            try:
                from hevc_gui.i18n import child_env
                for _k, _v in child_env().items():
                    env[str(_k)] = str(_v)
            except Exception:
                pass
            env["HEVC_MKV_EMBEDDED"] = "1"
            subprocess.Popen(cmd, env=env)
        except Exception as e:
            QMessageBox.warning(
                win,
                L("Errore"),
                L("Impossibile avviare Strumenti MKV:") + "\\n" + str(e),
            )

    _mkv_text = L("Strumenti MKV")
    try:
        from hevc_gui.i18n import get_lang as _hevc_get_lang
        _mkv_lang = (_hevc_get_lang() or "").lower()
    except Exception:
        _mkv_lang = (os.environ.get("HEVC_LANG", "") or "").lower()
    if _mkv_lang.startswith("en") and (_mkv_text.strip() in ("", "Strumenti MKV")):
        _mkv_text = "MKV Tools"

    act_mkv_suite = QAction(_mkv_text, win)
    try:
        _ic = QIcon(":/icons/ph_mkv.png")
        if _ic.isNull():
            _ic = QIcon(":/icons/ph_tools.png")
        if _ic.isNull():
            _ic = QIcon(":/icons/ph_video_file.png")
        if _ic.isNull() and "act_dvd" in locals():
            _ic = act_dvd.icon()
        if _ic and (not _ic.isNull()):
            act_mkv_suite.setIcon(_ic)
    except Exception:
        pass
    act_mkv_suite.triggered.connect(_open_mkv_suite)
    m_tools.addAction(act_mkv_suite)

    # — SETTINGS —
    m_settings = menubar.addMenu(L("&Settings"))
    act_asp = QAction(_themed_icon_with_aliases("asp"), L("Aspetto…"), win,
                      triggered=lambda: _open_appearance_dialog(win))
    act_asp.setProperty("icon_name", "asp")
    m_settings.addAction(act_asp)

    # — HELP —
    m_help = menubar.addMenu(L("&Help"))

    act_manual = QAction(_themed_icon_with_aliases("user_manual"), L("Manuale utente"), win)

    # QRC hard (garantito) — ma SOLO se esiste davvero (e NON è null)
    # Nota: QIcon(":/...") non lancia eccezioni se manca: restituisce solo un'icona vuota.
    p_qrc = ":/icons/ph_user_manual.png"
    if QFile.exists(p_qrc):
        ico = QIcon(p_qrc)
        if not ico.isNull():
            act_manual.setIcon(ico)

    # forza comunque "icone nei menu" per questa action (se supportato)
    try:
        act_manual.setIconVisibleInMenu(True)
    except Exception:
        pass

    act_manual.setProperty("icon_name", "user_manual")
    act_manual.triggered.connect(lambda: _safe_call(win, "open_help"))

    act_info = QAction(_themed_icon_with_aliases("info"), L("Informazioni"), win)
    act_info.setProperty("icon_name", "info")
    act_info.triggered.connect(lambda: _safe_call(win, "show_info"))

    act_donate = QAction(_themed_icon_with_aliases("paypal"), L("Dona (PayPal)"), win)
    act_donate.setProperty("icon_name", "paypal")
    try:
        act_donate.setIconVisibleInMenu(True)
    except Exception:
        pass
    act_donate.triggered.connect(lambda: QDesktopServices.openUrl(QUrl("https://paypal.me/loris1159")))

    m_help.addAction(act_manual)
    m_help.addAction(act_info)
    m_help.addSeparator()
    m_help.addAction(act_donate)

    # esponi riferimenti utili
    setattr(win, "act_minfo", act_minfo)
    setattr(win, "act_preview", act_preview)
    setattr(win, "act_preview_filtered", act_preview_filtered)
    setattr(win, "act_crop", act_crop)
    setattr(win, "act_color", act_color)
    setattr(win, "act_trim", act_trim)
    setattr(win, "act_dvd_ripper", act_dvd)

    win._menu_actions = {
        "open": act_open,
        "restart": act_restart,
        "save": act_save,
        "convert": act_convert,
        "extract": act_extract,
        "subs": act_subs,
        "chapters": act_chapters,
        "queue_run": act_queue_run,
        "edit_queue": act_edit_queue,
        "minfo": act_minfo,
        "preview": act_preview,
        "preview_filtered": act_preview_filtered,
        "crop": act_crop,
        "color": act_color,
        "trim": act_trim,
        "dvdrip": act_dvd,
        "asp": act_asp,
        "user_manual": act_manual,
        "info": act_info,
        "donate": act_donate,
        "exit": act_exit,
    }

    # — Toolbar —
    try:
        for tb in win.findChildren(QToolBar):
            win.removeToolBar(tb)
            tb.deleteLater()
    except Exception:
        pass

    icon_px = 40
    toolbar = win.addToolBar(L("Azioni rapide"))
    toolbar.setIconSize(QSize(icon_px, icon_px))

    toolbar.addActions([
        act_open,
        act_preview,
        act_preview_filtered,
        act_color,
        act_crop,
        act_trim,
        act_extract,
        act_subs,
        act_chapters,
        act_save,
        act_edit_queue,
        act_queue_run,
        act_convert,
        act_dvd,
    ])
    toolbar.addSeparator()
    toolbar.addAction(act_donate)

    _finalize_toolbar_buttons(toolbar, icon_px=icon_px)
    win._menu_toolbar = toolbar

    # — LINGUA (menu unico + restart obbligatorio) —
    m_lang = menubar.addMenu(L("Lingua"))
    m_lang.setObjectName("menuLanguage")

    grp = QActionGroup(m_lang)
    grp.setExclusive(True)

    act_it = QAction(L("Italiano"), m_lang)
    act_en = QAction(L("English"), m_lang)
    for a, code in ((act_it, "it"), (act_en, "en")):
        a.setCheckable(True)
        a.setData(code)
        grp.addAction(a)
        m_lang.addAction(a)

    cur = (get_lang() or "it").lower()
    act_it.setChecked(cur.startswith("it"))
    act_en.setChecked(cur.startswith("en"))

    def _apply_lang(code: str) -> None:
        code = (code or "it").lower()
        cur2 = (get_lang() or "it").lower()
        if cur2.startswith(code):
            return
        set_lang(code)
        QMessageBox.information(
            win,
            L("Riavvio necessario"),
            L("La lingua verrà applicata dopo il riavvio dell'app.")
        )
        restart_app()

    act_it.triggered.connect(lambda: _apply_lang("it"))
    act_en.triggered.connect(lambda: _apply_lang("en"))

    return menubar


def add_donate_to_help(main_window):
    try:
        if hasattr(main_window, "_menu_actions") and isinstance(main_window._menu_actions, dict):
            return main_window._menu_actions.get("donate")
    except Exception:
        pass
    return None


def refresh_icons(win):
    """Aggiorna icone (solo se non nulle) + prova a renderle visibili nei menu."""
    try:
        apply_large_menu_icons(QApplication.instance())
    except Exception:
        pass
    try:
        items = getattr(win, "_menu_actions", {})
        for _key, action in items.items():
            name = action.property("icon_name")
            if name:
                icon = _themed_icon_with_aliases(str(name))
                if not icon.isNull():
                    action.setIcon(icon)
                    try:
                        action.setIconVisibleInMenu(True)
                    except Exception:
                        pass
    except Exception:
        pass
