#!/usr/bin/env python3
import os
import logging
from PyQt5.QtWidgets import QAction, QMenuBar, QProxyStyle, QStyle, QApplication
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .main_window import MainWindow
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import QSize, Qt
from .appearance_dialog import AppearanceDialog

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
    "open": ["document-open"],
    "save": ["document-save"],
    "convert": ["media-playback-start"],
    "extract": ["audio-x-generic"],
    "subs": ["text-subtitle", "insert-text", "edit", "text-x-generic"],
    "chapters": ["media-optical", "view-list", "go-next", "bookmark"],
    "queue_run": ["system-run"],
    "edit_queue": ["edit-paste"],
    "minfo": ["dialog-information", "help-about"],
    "preview": ["video-x-generic"],
    "preview_filtered": ["video-x-generic"],
    "exit": ["application-exit"],
    "asp": [],
    "manual": ["help-contents", "help-browser", "help"],  # <— più compatibilità
    "info": ["help-about", "dialog-information"],          # <— più compatibilità
}

# — Directory fallback per icone locali —
LOCAL_ICON_DIR = os.path.join(os.path.dirname(__file__), "..", "resources", "icons")

def _themed_icon_with_aliases(name: str) -> QIcon:
    aliases = ICON_ALIASES.get(name, [name])
    theme = QIcon.themeName()
    for alias in aliases:
        icon = QIcon.fromTheme(alias)
        if not icon.isNull():
            logging.debug(f"Icona per '{name}' trovata nel tema '{theme}' come: '{alias}'")
            return icon
    fallback_path = os.path.join(LOCAL_ICON_DIR, f"ph_{name}.png")
    if os.path.exists(fallback_path):
        logging.debug(f"Icona per '{name}' non trovata nel tema: uso fallback locale '{fallback_path}'")
        return QIcon(fallback_path)
    logging.debug(f"Icona per '{name}' non trovata. Nessun fallback disponibile.")
    return QIcon()

def setup_menubar(win: "MainWindow") -> QMenuBar:
    menubar = QMenuBar(win)

    # — FILE —
    m_file = menubar.addMenu("&File")
    act_open = QAction(_themed_icon_with_aliases("open"), "Apri video…", win,
                       shortcut="Ctrl+O", triggered=win.open_file)
    act_open.setProperty("icon_name", "open")
    act_exit = QAction(_themed_icon_with_aliases("exit"), "Esci", win,
                       shortcut="Ctrl+Q", triggered=win.exit_app)
    act_exit.setProperty("icon_name", "exit")
    m_file.addAction(act_open)
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

    m_tools.addActions([act_minfo, act_preview, act_preview_filtered])

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

    m_help.addAction(act_manual)
    m_help.addAction(act_info)

    # — Mappatura per aggiornamento icone —
    win._menu_actions = {
        "open": act_open,
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
        "asp": act_asp,
        "help": act_manual,
        "info": act_info,
    }

    # --- SCOPA: elimina qualsiasi toolbar già presente ---
    try:
        for tb in win.findChildren(QToolBar):
            win.removeToolBar(tb)
            tb.deleteLater()
    except Exception:
        pass
    
    # — Toolbar (storica) — crea qui la toolbar una volta sola
    toolbar = win.addToolBar("Azioni rapide")
    toolbar.setIconSize(QSize(48, 48))
    toolbar.setToolButtonStyle(Qt.ToolButtonIconOnly)
    toolbar.setStyleSheet("""
        QToolButton { padding: 1px 1px; min-width: 10px; margin: 0px; }
        QToolButton:hover { background-color: #d0d0d0; }
    """)
    toolbar.addActions(
        [
            act_open,
            act_preview,
            act_preview_filtered,
            act_extract,
            act_subs,
            act_chapters,
            act_save,
            act_edit_queue,
            act_queue_run,
            act_convert,
        ]
    )
    win._menu_toolbar = toolbar

    return menubar

# ────────────────────────────────────────────────────────────────────────────
# Dona (PayPal) nel menu Aiuto/Help (icona: ph_paypal.png)
# ────────────────────────────────────────────────────────────────────────────
def add_donate_to_help(main_window):
    from pathlib import Path
    from PyQt5.QtCore import QUrl
    from PyQt5.QtGui import QIcon
    from PyQt5.QtWidgets import QAction, QStyle
    from PyQt5.QtGui import QDesktopServices

    def _norm(s: str) -> str:
        return (s or "").replace("&", "").strip().lower()

    menubar = main_window.menuBar() if hasattr(main_window, "menuBar") else None
    if not menubar:
        return

    target = None
    for act in menubar.actions():
        m = act.menu()
        if m and _norm(m.title()) in ("aiuto", "help", "info"):
            target = m
            break
    if target is None:
        target = menubar.addMenu("&Aiuto")

    icons_dir = Path(__file__).parent.parent / "resources" / "icons"
    pp_icon = icons_dir / "ph_paypal.png"
    icon = QIcon(str(pp_icon)) if pp_icon.exists() else main_window.style().standardIcon(QStyle.SP_DialogHelpButton)

    act = QAction(icon, "Dona (PayPal)", main_window)
    act.setIconVisibleInMenu(True)
    act.setToolTip("Apri la pagina PayPal per una donazione")
    act.triggered.connect(lambda: QDesktopServices.openUrl(QUrl("https://paypal.me/loris1159")))

    placed = False
    for a in target.actions():
        if _norm(a.text()) in ("informazioni", "info", "about"):
            target.insertSeparator(a)
            target.insertAction(a, act)
            placed = True
            break
    if not placed:
        if target.actions():
            target.addSeparator()
        target.addAction(act)

    try:
        if hasattr(main_window, "_menu_actions") and isinstance(main_window._menu_actions, dict):
            main_window._menu_actions["donate"] = act
    except Exception:
        pass

def refresh_icons(win):
    for key, action in win._menu_actions.items():
        name = action.property("icon_name")
        if name:
            action.setIcon(_themed_icon_with_aliases(name))
