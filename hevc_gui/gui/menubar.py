#!/usr/bin/env python3
import os
import sys
import logging
from typing import TYPE_CHECKING

from PyQt5.QtWidgets import QAction, QMenuBar, QProxyStyle, QStyle, QApplication, QToolBar, QMessageBox, QToolButton
from PyQt5.QtCore import QSize, Qt, QUrl, QProcess, QFile
from PyQt5.QtGui import QIcon, QDesktopServices

from .appearance_dialog import AppearanceDialog

if TYPE_CHECKING:
    from .main_window import MainWindow


# — Stile per forzare icone grandi nella menubar —
class LargeMenuStyle(QProxyStyle):
    def pixelMetric(self, metric, option=None, widget=None):
        if metric == QStyle.PM_SmallIconSize:
            return 32
        return super().pixelMetric(metric, option, widget)


def apply_large_menu_icons(app: QApplication):
    app.setStyle(LargeMenuStyle())


# — Mappa di alias per supportare temi con nomi diversi —
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
    "manual": ["help-contents", "help-browser", "help", "manual"],
    "info": ["help-about", "dialog-information", "info"],
    "trim": ["edit-cut", "media-seek-forward", "trim"],
    "crop": ["transform-crop", "crop"],
    "color": ["preferences-desktop-color", "color"],
    "dvdrip": ["media-optical", "drive-optical", "media-optical-dvd", "dvdrip"],
    "restart": ["view-refresh", "system-reboot", "restart"],

    # Donate
    "paypal": ["paypal", "help-donate", "emblem-favorite"],
}

# — Directory fallback per icone locali —
LOCAL_ICON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "resources", "icons"))


def _qrc_icon_try(name: str) -> QIcon:
    """
    Carica icone SOLO dal QRC ufficiale: :/icons/ph_<name>.png
    """
    if not name:
        return QIcon()

    # priorità: ph_<name>.png poi <name>.png (se per caso alcune non hanno prefix ph_)
    for base in (f"ph_{name}", name):
        p = f":/icons/{base}.png"
        if QFile.exists(p):
            return QIcon(p)

    return QIcon()

def _local_icon_try(name: str) -> QIcon:
    """
    Icona locale 'ph_<name>.png' nella cartella resources/icons.
    """
    if not name:
        return QIcon()
    p = os.path.join(LOCAL_ICON_DIR, f"ph_{name}.png")
    if os.path.exists(p):
        return QIcon(p)
    return QIcon()


def _themed_icon_with_aliases(name: str) -> QIcon:
    """
    Priorità (per avere pulsanti = PNG coerenti):
      1) QRC (se presente)
      2) file locale resources/icons/ph_<name>.png
      3) tema di sistema (fromTheme) con alias
    """
    # 1) QRC
    ic = _qrc_icon_try(name)
    if not ic.isNull():
        return ic

    # 2) Locale
    ic = _local_icon_try(name)
    if not ic.isNull():
        return ic

    # 3) Tema (fallback)
    aliases = ICON_ALIASES.get(name, [name])
    theme = QIcon.themeName()

    for alias in aliases:
        icon = QIcon.fromTheme(alias)
        if not icon.isNull():
            logging.debug(f"Icona per '{name}' trovata nel tema '{theme}' come: '{alias}'")
            return icon

    logging.debug(f"Icona per '{name}' non trovata (QRC/locale/tema).")
    return QIcon()


def _apply_hevc_toolbar_style(tb: QToolBar, icon_px: int = 32) -> None:
    """
    Stile LDVD-like:
      - icon-only
      - zero padding/margini
      - pulsante = icona (fixed size)
      - hover/pressed leggeri
    """
    tb.setIconSize(QSize(icon_px, icon_px))
    tb.setToolButtonStyle(Qt.ToolButtonIconOnly)
    tb.setMovable(False)
    tb.setFloatable(False)
    tb.setContextMenuPolicy(Qt.PreventContextMenu)
    tb.setContentsMargins(0, 0, 0, 0)

    tb.setStyleSheet(f"""
        QToolBar {{
            spacing: 0px;
            padding: 0px;
            margin: 0px;
            border: 0px;
            background: transparent;
        }}
        QToolButton {{
            padding: 0px;
            margin: 0px;
            border: 0px;
            background: transparent;
        }}
        QToolButton:hover {{
            background: rgba(255, 255, 255, 0.12);
        }}
        QToolButton:pressed {{
            background: rgba(0, 0, 0, 0.20);
        }}
        QToolButton:disabled {{
            background: transparent;
            opacity: 0.35;
        }}
    """)


def _finalize_toolbar_buttons(tb: QToolBar, icon_px: int = 32) -> None:
    """
    Step finale: i pulsanti diventano grandi esattamente come l’icona.
    Va chiamato DOPO tb.addActions(...).
    """
    for b in tb.findChildren(QToolButton):
        b.setAutoRaise(True)
        b.setToolButtonStyle(Qt.ToolButtonIconOnly)
        b.setIconSize(QSize(icon_px, icon_px))
        b.setFixedSize(icon_px, icon_px)     # ← pulsante = PNG
        b.setFocusPolicy(Qt.NoFocus)
        b.setCursor(Qt.PointingHandCursor)

def _restart_app(win) -> None:
    """
    Riavvia HEVC "da zero" rilanciando lo stesso comando (python + argv),
    poi chiude il processo corrente.
    """
    res = QMessageBox.question(
        win,
        "Riavvia…",
        "Vuoi riavviare HEVC?\n\nLo stato corrente (file/queue) verrà perso.",
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No,
    )
    if res != QMessageBox.Yes:
        return

    # Best-effort: se esiste qualche metodo di reset/stop, lo chiamiamo senza rompere nulla.
    for meth in (
        "stop_queue_processing",
        "abort_processing",
        "cancel_all_jobs",
        "reset_all",
        "clear_all",
        "new_session",
        "reset_gui",
    ):
        fn = getattr(win, meth, None)
        if callable(fn):
            try:
                fn()
            except Exception:
                pass

    program = sys.executable
    args = sys.argv[:]  # stesso comando con cui l'hai lanciato (es. main.py)
    QProcess.startDetached(program, args, os.getcwd())
    QApplication.quit()

def setup_menubar(win: "MainWindow") -> QMenuBar:
    menubar = QMenuBar(win)

    # — FILE —
    m_file = menubar.addMenu("&File")
    act_open = QAction(_themed_icon_with_aliases("open"), "Apri video…", win,
                       shortcut="Ctrl+O", triggered=win.open_file)
    act_open.setProperty("icon_name", "open")

    act_restart = QAction(_themed_icon_with_aliases("restart"), "Riavvia…", win,
                          shortcut="Ctrl+Shift+R",
                          triggered=lambda: _restart_app(win))
    act_restart.setProperty("icon_name", "restart")

    act_exit = QAction(_themed_icon_with_aliases("exit"), "Esci", win,
                       shortcut="Ctrl+Q", triggered=win.exit_app)
    act_exit.setProperty("icon_name", "exit")

    m_file.addAction(act_open)
    m_file.addAction(act_restart)
    m_file.addSeparator()
    m_file.addAction(act_exit)

    # — AZIONI —
    m_actions = menubar.addMenu("&Azioni")

    act_convert = QAction(_themed_icon_with_aliases("convert"), "Converti", win,
                          shortcut="Ctrl+Return", triggered=win.on_convert_clicked)
    act_convert.setProperty("icon_name", "convert")

    act_extract = QAction(_themed_icon_with_aliases("extract"), "Estrai audio", win,
                          triggered=win.extract_audio)
    act_extract.setProperty("icon_name", "extract")

    act_subs = QAction(_themed_icon_with_aliases("subs"), "Sottotitoli…", win,
                       triggered=win.on_subtitle_clicked)
    act_subs.setProperty("icon_name", "subs")

    act_chapters = QAction(_themed_icon_with_aliases("chapters"), "Capitoli…", win,
                           triggered=win.on_chapter_clicked)
    act_chapters.setProperty("icon_name", "chapters")

    act_queue_run = QAction(_themed_icon_with_aliases("queue_run"), "Elabora coda", win,
                            shortcut="F9", triggered=win.start_queue_processing)
    act_queue_run.setProperty("icon_name", "queue_run")

    act_save = QAction(_themed_icon_with_aliases("save"), "Salva coda", win,
                       shortcut="Ctrl+S", triggered=win.save_gui_queue_to_file)
    act_save.setProperty("icon_name", "save")

    act_edit_queue = QAction(_themed_icon_with_aliases("edit_queue"), "Gestisci coda", win,
                             triggered=win.open_queue_manager)
    act_edit_queue.setProperty("icon_name", "edit_queue")

    m_actions.addActions(
        [act_convert, act_extract, act_subs, act_chapters, act_queue_run, act_save, act_edit_queue]
    )

    # — STRUMENTI —
    m_tools = menubar.addMenu("&Strumenti")

    act_minfo = QAction(_themed_icon_with_aliases("minfo"), "MediaInfo", win,
                        triggered=win.show_mediainfo)
    act_minfo.setProperty("icon_name", "minfo")

    act_preview = QAction(_themed_icon_with_aliases("preview"), "Preview", win,
                          triggered=lambda: win.launch_preview(False))
    act_preview.setProperty("icon_name", "preview")

    act_preview_filtered = QAction(_themed_icon_with_aliases("preview_filtered"), "Preview filtrata", win,
                                   triggered=lambda: win.launch_preview(True))
    act_preview_filtered.setProperty("icon_name", "preview_filtered")

    act_crop = QAction(_themed_icon_with_aliases("crop"), "Imposta crop…", win,
                       triggered=win.open_crop_tool)
    act_crop.setStatusTip("Apri lo strumento di ritaglio video")
    act_crop.setProperty("icon_name", "crop")
    act_crop.setObjectName("act_crop")
    act_crop.setEnabled(False)

    act_color = QAction(_themed_icon_with_aliases("color"), "Regola colore…", win,
                        triggered=win.open_color_tool)
    act_color.setStatusTip("Apri lo strumento di correzione colore")
    act_color.setProperty("icon_name", "color")
    act_color.setObjectName("act_color")
    act_color.setEnabled(False)

    act_trim = QAction(_themed_icon_with_aliases("trim"), "Trim…", win,
                       triggered=win.open_trim_tool)
    act_trim.setStatusTip("Taglia un segmento interno (es. pubblicità) da video e audio")
    act_trim.setProperty("icon_name", "trim")
    act_trim.setObjectName("act_trim")
    act_trim.setEnabled(False)

    m_tools.addActions(
        [act_minfo, act_preview, act_preview_filtered, act_crop, act_color, act_trim]
    )

    act_dvd = QAction(_themed_icon_with_aliases("dvdrip"), "DVD Ripper…", win)
    act_dvd.setToolTip("Apri l'estrattore DVD (LDVD-Ripper)")
    act_dvd.setProperty("icon_name", "dvdrip")
    act_dvd.triggered.connect(win.open_dvd_ripper)
    m_tools.addAction(act_dvd)

    # — IMPOSTAZIONI —
    m_settings = menubar.addMenu("&Impostazioni")
    act_asp = QAction(_themed_icon_with_aliases("asp"), "Aspetto…", win)
    act_asp.setToolTip("Scegli stile Qt e font dell’interfaccia")
    act_asp.setProperty("icon_name", "asp")
    act_asp.triggered.connect(lambda: AppearanceDialog(win).exec_())
    m_settings.addAction(act_asp)

    # — HELP —
    m_help = menubar.addMenu("&Help")

    act_manual = QAction(_themed_icon_with_aliases("manual"), "Manuale utente", win)
    act_manual.setToolTip("Apri manuale istruzioni nel browser")
    act_manual.setProperty("icon_name", "manual")
    act_manual.triggered.connect(win.open_help)

    act_info = QAction(_themed_icon_with_aliases("info"), "Informazioni", win)
    act_info.setToolTip("About Hevc - Video Converter")
    act_info.setProperty("icon_name", "info")
    act_info.triggered.connect(win.show_info)

    # Donate (PayPal) — qui nasce l'azione, così esiste anche per la toolbar
    act_donate = QAction(_themed_icon_with_aliases("paypal"), "Dona (PayPal)", win)
    act_donate.setToolTip("Apri la pagina PayPal per una donazione")
    act_donate.setProperty("icon_name", "paypal")
    act_donate.setIconVisibleInMenu(True)
    act_donate.triggered.connect(lambda: QDesktopServices.openUrl(QUrl("https://paypal.me/loris1159")))

    m_help.addAction(act_manual)
    m_help.addAction(act_info)
    m_help.addSeparator()
    m_help.addAction(act_donate)

    # Espone i riferimenti direttamente sul MainWindow
    setattr(win, "act_minfo", act_minfo)
    setattr(win, "act_preview", act_preview)
    setattr(win, "act_preview_filtered", act_preview_filtered)
    setattr(win, "act_crop", act_crop)
    setattr(win, "act_color", act_color)
    setattr(win, "act_trim", act_trim)
    setattr(win, "act_dvd_ripper", act_dvd)

    # — Mappa per refresh icone (UNA sola) —
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
        "manual": act_manual,
        "info": act_info,
        "donate": act_donate,
    }

    # --- SCOPA: elimina qualsiasi toolbar già presente ---
    try:
        for tb in win.findChildren(QToolBar):
            win.removeToolBar(tb)
            tb.deleteLater()
    except Exception:
        pass

    # — Toolbar (LDVD-like) —
    icon_px = 48  # ← se vuoi più “bottonazzi”, metti 48
    toolbar = win.addToolBar("Azioni rapide")
    _apply_hevc_toolbar_style(toolbar, icon_px=icon_px)

    toolbar.addActions(
        [
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
        ]
    )
    toolbar.addSeparator()
    toolbar.addAction(act_donate)

    # importantissimo: dopo addActions
    _finalize_toolbar_buttons(toolbar, icon_px=icon_px)

    win._menu_toolbar = toolbar
    return menubar


def add_donate_to_help(main_window):
    """
    Compatibilità: main_window importa questa funzione.
    Ora l'azione Donate viene creata in setup_menubar(), quindi qui
    ci limitiamo a restituirla se già esiste.
    """
    try:
        if hasattr(main_window, "_menu_actions") and isinstance(main_window._menu_actions, dict):
            return main_window._menu_actions.get("donate")
    except Exception:
        pass
    return None


def refresh_icons(win):
    # qui lasciamo la tua logica, ma con una protezione: non mettere icone "vuote"
    for key, action in win._menu_actions.items():
        name = action.property("icon_name")
        if name:
            icon = _themed_icon_with_aliases(name)
            if not icon.isNull():
                action.setIcon(icon)
