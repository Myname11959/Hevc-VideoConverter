#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
# STANDALONE_SAFETY_DEFAULTS
from hevc_gui.mkv_suite.i18n import L, LT
if '_APPLY_APPEARANCE' not in globals():
    _APPLY_APPEARANCE = None
if '_LOAD_APPEARANCE' not in globals():
    _LOAD_APPEARANCE = None

from pathlib import Path

import os
import sys


def _is_hevc_embedded(argv=None) -> bool:
    env = (os.environ.get("HEVC_MKV_EMBEDDED", "") or "").strip().lower()
    if env in ("1", "true", "yes", "on"):
        return True
    try:
        args = list(argv) if argv is not None else list(sys.argv[1:])
    except Exception:
        args = []
    return "--embedded" in args


def _embedded_lang_env() -> str:
    v = (os.environ.get("HEVC_LANG", "") or "").strip().lower()
    if v.startswith("en"):
        return "en"
    if v.startswith("it"):
        return "it"
    return ""
try:
    from mkv_tools.version import get_version  # standalone
except Exception:
    def get_version():
        try:
            vf = Path(__file__).resolve().parents[2] / "VERSION"
            if vf.is_file():
                return vf.read_text(encoding="utf-8").strip() or "1.0.0.0"
        except Exception:
            pass
        return "1.0.0.0"

from hevc_gui.mkv_suite.i18n_apply import install_auto_translator, apply_to_widget_tree
from hevc_gui.mkv_suite import i18n as _i18n
# STANDALONE_I18N_RELOAD
import importlib as _importlib
_i18n = _importlib.reload(_i18n)
L = _i18n.L
# STANDALONE_I18N_FORCE_L
_orig_L = _i18n.L
L = _i18n.L
from hevc_gui.mkv_suite.ui.restart_action import build_restart_action
from hevc_gui.mkv_suite.ui.lang_menu import install_language_menu

from PyQt5.QtCore import Qt, QSize, QSettings, QTimer
from PyQt5.QtGui import QPixmap, QIcon
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QAction, QToolBar, QStyle, QMessageBox,
    QTabWidget, QSplitter, QDialog, QLabel, QHBoxLayout, QVBoxLayout, QDialogButtonBox
)

try:
    import hevc_gui.resources.icons_rc  # noqa: F401
except Exception:
    pass

try:
    from hevc_gui.mkv_suite.i18n import L, get_lang
except Exception:
    def L(s: str) -> str:
        return s
    def get_lang(self) -> None:
        """Finestra Informazioni (standalone)."""
        from pathlib import Path
        # import runtime (PyQt5 / PyQt5)
        try:
            from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QDialogButtonBox
            from PyQt5.QtGui import QPixmap, QIcon
            from PyQt5.QtCore import Qt
        except Exception:
            from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QDialogButtonBox
            from PyQt5.QtGui import QPixmap, QIcon
            from PyQt5.QtCore import Qt
    
        # versione da file (fallback)
        ver = '1.0.0.0'
        try:
            vf = Path(__file__).resolve().parents[2] / 'VERSION'  # mkv_tools/VERSION
            if vf.is_file():
                ver = (vf.read_text(encoding='utf-8').strip() or ver)
        except Exception:
            pass
    
        dlg = QDialog(self)
        dlg.setWindowTitle(L('Informazioni'))
        dlg.setModal(True)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(26, 18, 26, 18)
        lay.setSpacing(10)
    
        # icona sopra (centrata)
        try:
            icon_path = Path(__file__).resolve().parent.parent / 'assets' / 'icons' / 'ph_mkv.png'
            if icon_path.is_file():
                pm = QPixmap(str(icon_path)).scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                lab_icon = QLabel(dlg)
                lab_icon.setPixmap(pm)
                lab_icon.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
                lay.addWidget(lab_icon)
                try:
                    dlg.setWindowIcon(QIcon(str(icon_path)))
                except Exception:
                    pass
        except Exception:
            pass
    
        title = L('Strumenti MKV')
        desc  = L('Suite standalone per estrazione, remux, capitoli e strumenti MKV.')
        html = (
            "<div align='center'>"
            + "<b>" + title + "</b><br>"
            + L('Versione') + " " + ver + "<br><br>"
            + desc + "<br><br>"
            + "LorisPaganiniHomeStudio - 2026<br>"
            + "<a href='mailto:loris.paganini@gmail.com'>mailto: loris.paganini@gmail.com</a>"
            + "</div>"
        )
        lab = QLabel(html, dlg)
        lab.setTextFormat(Qt.RichText)
        try:
            lab.setOpenExternalLinks(True)
        except Exception:
            pass
        lab.setAlignment(Qt.AlignCenter)
        lay.addWidget(lab)
    
        bb = QDialogButtonBox(QDialogButtonBox.Ok, parent=dlg)
        bb.accepted.connect(dlg.accept)
        lay.addWidget(bb, alignment=Qt.AlignHCenter)
    
        try:
            dlg.exec()
        except Exception:
            dlg.exec_()
    def _L_mkv_fallback(s, *args, **kwargs):
        return s
    try:
# _i18n.L = _L_mkv_fallback
        globals()["L"] = _L_mkv_fallback
        _i18n._MKV_EN_FALLBACKS_PATCHED = True
    except Exception:
        pass

# SAFE_INSTALL_MKV_EN_FALLBACKS (disabled in standalone)
# legacy fallback removed to avoid recursion
# --- end MKV Suite EN fallback ---

from hevc_gui.mkv_suite.ui.main_widget import MainWidget


def _require_embedded_flag(argv: list[str]) -> None:
    if "--embedded" not in argv:
        # (removed noisy message)
        raise SystemExit(2)


class EmbeddedWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(L("Strumenti MKV"))
        # --- window icon (standalone) ---
        _icon_path = Path(__file__).resolve().parent.parent / 'assets' / 'icons' / 'mkv-tools.png'
        if _icon_path.is_file():
            self.setWindowIcon(QIcon(str(_icon_path)))
        self.setMinimumSize(1100, 650)

        self.w = MainWidget(self)
        self.setCentralWidget(self.w)

        self._build_actions()
        # collega controlli interni del widget alle QAction (menu/toolbar)
        self.w.bind_actions({
            "add": self.actAdd,
            "remove": self.actRemove,
            "outdir": self.actOutDir,
            "open_outdir": self.actOpenOutDir,
            "tag": self.actTag,
            "extract": self.actExtract,
            "cut": self.actCut,
            "insert_clip": self.actInsertClip,
            "remux": self.actRemux,
            "stop": self.actStop,
        })
        self._build_menus()
        self._build_toolbar()
        self._unlock_resize_limits()

        try:
            _btn_extract = getattr(self.w, "btn_extract", None)
            _tt_extract = (_btn_extract.toolTip() if _btn_extract is not None else "") or L("Estrae le tracce selezionate nella cartella extract/.")
            self.actExtract.setToolTip(_tt_extract)
            self.actExtract.setStatusTip(_tt_extract)
            self.actExtract.setWhatsThis(_tt_extract)
        except Exception:
            pass
        try:
            _tt_cut = L("Taglio")
            self.actCut.setToolTip(_tt_cut)
            self.actCut.setStatusTip(_tt_cut)
            self.actCut.setWhatsThis(_tt_cut)
        except Exception:
            pass
        try:
            _tt_ins = L("Inserisci una o più clip nel file selezionato.")
            self.actInsertClip.setToolTip(_tt_ins)
            self.actInsertClip.setStatusTip(_tt_ins)
            self.actInsertClip.setWhatsThis(_tt_ins)
        except Exception:
            pass
        try:
            self._sync_view_menu_state()
        except Exception:
            pass

    # --- geometry persistence (auto patch) ---
        # --- ENSURE USER MANUAL ACTION (standalone) ---
        try:
            _icons = Path(__file__).resolve().parent.parent / 'assets' / 'icons'
            _p = _icons / 'ph_help.png'
            _ic = QIcon(str(_p)) if _p.is_file() else self.style().standardIcon(QStyle.SP_DialogHelpButton)
            if hasattr(self, 'actUserManual') and self.actUserManual:
                if not _ic.isNull():
                    self.actUserManual.setIcon(_ic)
                self.actUserManual.setVisible(True)
                self.actUserManual.setEnabled(True)
                # menu Aiuto/Help
                mb = self.menuBar()
                help_menu = None
                for a in mb.actions():
                    t = (a.text() or '').replace('&','').strip().lower()
                    if t in ('aiuto','help'):
                        help_menu = a.menu()
                        break
                if help_menu and self.actUserManual not in help_menu.actions():
                    help_menu.addSeparator()
                    help_menu.addAction(self.actUserManual)
                # toolbar (prima trovata)
                tbs = self.findChildren(QToolBar)
                if tbs:
                    tb = tbs[0]
                    if self.actUserManual not in tb.actions():
                        tb.addSeparator()
                        tb.addAction(self.actUserManual)
        except Exception:
            pass
    def _restore_window_geometry_prefs(self) -> None:
        try:
            st = QSettings("MKV-Tools", "MKVTools")
            geo = st.value("main/geometry")
            if geo:
                self.restoreGeometry(geo)
            win_state = st.value("main/windowState")
            if win_state:
                self.restoreState(win_state)
        except Exception:
            pass

    def _save_window_geometry_prefs(self) -> None:
        try:
            st = QSettings("MKV-Tools", "MKVTools")
            st.setValue("main/geometry", self.saveGeometry())
            st.setValue("main/windowState", self.saveState())
        except Exception:
            pass

    # --- resize unlock (auto patch) ---
    def _unlock_resize_limits(self) -> None:
        """Sblocca eventuali vincoli residui su larghezza/altezza."""
        try:
            self.setMinimumSize(640, 420)
            self.setMaximumSize(16777215, 16777215)
        except Exception:
            pass
        try:
            cw = self.centralWidget()
            if cw is not None:
                cw.setMinimumSize(1, 1)
                cw.setMaximumSize(16777215, 16777215)
        except Exception:
            pass

    def _build_actions(self) -> None:
        s = self.style()

        self.actAdd = QAction(s.standardIcon(QStyle.SP_DialogOpenButton), L("Aggiungi file…"), self)

        self.actRemove = QAction(s.standardIcon(QStyle.SP_TrashIcon), L("Rimuovi selezionati"), self)

        self.actOutDir = QAction(s.standardIcon(QStyle.SP_DirOpenIcon), L("Cartella output…"), self)


        self.actOpenOutDir = QAction(


            s.standardIcon(QStyle.SP_ComputerIcon),


            L("Apri cartella output"),


            self


        )


        self.actTag = QAction(s.standardIcon(QStyle.SP_FileDialogDetailedView), L("Applica Tag"), self)

        self.actExtract = QAction(s.standardIcon(QStyle.SP_ArrowDown), L("Estrai tracce…"), self)

        self.actCut = QAction(s.standardIcon(QStyle.SP_FileDialogContentsView), L(L("Taglio…")), self)
        self.actInsertClip = QAction(s.standardIcon(QStyle.SP_FileDialogNewFolder), L("Inserisci clip…"), self)
        try:
            _ic_cut = QIcon(":/icons/ph_trim.png")
            if _ic_cut.isNull():
                _p_cut = (Path(__file__).resolve().parent.parent / "assets" / "icons" / "ph_trim.png")
                if _p_cut.is_file():
                    _ic_cut = QIcon(str(_p_cut))
            if not _ic_cut.isNull():
                self.actCut.setIcon(_ic_cut)
        except Exception:
            pass
        try:
            _ic_ins = QIcon(":/icons/ph_insert_clip.png")
            if _ic_ins.isNull():
                _p_ins = (Path(__file__).resolve().parent.parent / "assets" / "icons" / "ph_insert_clip.png")
                if _p_ins.is_file():
                    _ic_ins = QIcon(str(_p_ins))
            if not _ic_ins.isNull():
                self.actInsertClip.setIcon(_ic_ins)
        except Exception:
            pass

        self.actRemux = QAction(s.standardIcon(QStyle.SP_BrowserReload), L("Crea MKV"), self)

        self.actStop = QAction(s.standardIcon(QStyle.SP_BrowserStop), L("Stop"), self)

        self.actExit = QAction(L("Esci"), self)
        # --- RESTART ACTION (standalone) ---
        try:
            _tr = L if 'L' in globals() else (lambda x: x)
            self.actRestart = build_restart_action(self, s, tr=_tr, log=getattr(self, '_log', None))
        except Exception:
            self.actRestart = QAction(s.standardIcon(QStyle.SP_BrowserReload), L('Riavvia'), self)
        if _is_hevc_embedded():
            try:
                self.actRestart.setVisible(False)
                self.actRestart.setEnabled(False)
            except Exception:
                pass
        self.actExit.triggered.connect(self.close)

        self.actAbout = QAction(L("Informazioni…"), self)
        self.actAbout.triggered.connect(self._about)

        # Aiuto
        self.actUserManual = QAction(L("User manual"), self)
        # --- force actUserManual (standalone) ---
        try:
            self.actUserManual.setVisible(True)
            self.actUserManual.setEnabled(True)
            _icons = Path(__file__).resolve().parent.parent / 'assets' / 'icons'
            _p = _icons / 'ph_help.png'
            _ic = QIcon(str(_p)) if _p.is_file() else self.style().standardIcon(QStyle.SP_DialogHelpButton)
            if not _ic.isNull():
                self.actUserManual.setIcon(_ic)
        except Exception:
            pass
        # --- force user manual icon to ph_help ---
        try:
            _icons = Path(__file__).resolve().parent.parent / 'assets' / 'icons'
            _p = _icons / 'ph_help.png'
            _ic = QIcon(str(_p)) if _p.is_file() else self.style().standardIcon(QStyle.SP_DialogHelpButton)
            if not _ic.isNull():
                self.actUserManual.setIcon(_ic)
        except Exception:
            pass
        self.actUserManual.triggered.connect(self._user_manual)

        try:
            _ic_manual = QIcon(":/icons/ph_help.png")
            if _ic_manual.isNull():
                _ic_manual = QIcon(":/icons/ph_help.png")
            self.actUserManual.setIcon(_ic_manual)
        except Exception:
            pass
        try:
            _um = QIcon(":/icons/ph_help.png")
            if _um.isNull():
                _p = (Path(__file__).resolve().parent.parent / "assets" / "icons" / "ph_help.png")
                if _p.is_file():
                    _um = QIcon(str(_p))
            if not _um.isNull():
                self.actUserManual.setIcon(_um)
        except Exception:
            pass

        # Visualizza
        self.actViewToolbar = QAction(L("Barra strumenti"), self)
        self.actViewToolbar.setCheckable(True)
        self.actViewToolbar.setChecked(True)
        self.actViewToolbar.triggered.connect(self._toggle_toolbar_visible)

        self.actViewResetLayout = QAction(L("Ripristina layout"), self)
        self.actViewResetLayout.triggered.connect(self._restore_default_view_layout)

        self.actViewLog = QAction(L("Log"), self)
        self.actViewLog.setCheckable(True)
        self.actViewLog.setChecked(True)
        self.actViewLog.triggered.connect(self._toggle_log_visible)

        self.actViewGoTracks = QAction(L("Vai a Tracce"), self)
        self.actViewGoTracks.triggered.connect(
            lambda: self._goto_tab_by_names(["tracce", "tracks"])
        )

        self.actViewGoChapters = QAction(L("Vai a Capitoli"), self)
        self.actViewGoChapters.triggered.connect(
            lambda: self._goto_tab_by_names(["capitoli", "chapters"])
        )

        self.actViewGoConcat = QAction(L("Vai a Unisci episodi"), self)
        # --- icon override (standalone assets) ---
        try:
            from pathlib import Path
            _icons = Path(__file__).resolve().parent.parent / 'assets' / 'icons'
            def _ic(name: str):
                p = _icons / name
                return QIcon(str(p)) if p.is_file() else None
            for _act, _name in (
                (self.actOutDir, 'ph_out_folder.png'),
                (self.actOpenOutDir, 'ph_out_folder.png'),
                (self.actExtract, 'ph_extract.png'),
                (self.actCut, 'ph_trim.png'),
                (self.actInsertClip, 'ph_insert_clip.png'),
                (self.actRemux, 'ph_mkv.png'),
                (self.actTag, 'ph_tag.png'),
                (self.actStop, 'ph_stop.png'),
                (self.actViewGoChapters, 'ph_chapters.png'),
                (self.actViewGoConcat, 'ph_concat.png'),
            ):
                ic = _ic(_name)
                if ic:
                    _act.setIcon(ic)
        except Exception:
            pass
        self.actViewGoConcat.triggered.connect(
            lambda: self._goto_tab_by_names([
                "unisci episodi", "merge episodes", "merge", "concat", "batch", "episodi"
            ])
        )

        # --- icone QAction (menu + toolbar) ---
        # (standalone) prova prima assets/icons, poi (se esiste) qrc :/icons
        _icons = Path(__file__).resolve().parent.parent / 'assets' / 'icons'
        def _set_icon(action, res_path: str) -> None:
            try:
                if action is None:
                    return
                rp = (res_path or '').strip()
                name = rp.split('/')[-1] if rp.startswith(':/icons/') else ''
                ic = None
                if name:
                    p = _icons / name
                    if p.is_file():
                        ic = QIcon(str(p))
                if ic is None:
                    ic = QIcon(rp)
                if not ic.isNull():
                    action.setIcon(ic)
            except Exception:
                pass
        # File
        _set_icon(self.actAdd, ":/icons/ph_list-add.png")
        _set_icon(self.actRemove, ":/icons/ph_list-remove.png")
        _set_icon(self.actOpenOutDir, ":/icons/ph_out_folder.png")
        _set_icon(self.actOutDir, ":/icons/ph_folder-open.png")
        _set_icon(self.actExit, ":/icons/ph_exit.png")

        # Operazioni
        _set_icon(self.actTag, ":/icons/ph_edit_queue.png")
        _set_icon(self.actExtract, ":/icons/ph_send.png")
        _set_icon(self.actCut, ":/icons/ph_trim.png")
        _set_icon(self.actRemux, ":/icons/ph_view-refresh.png")
        _set_icon(self.actStop, ":/icons/ph_process-stop.png")

        # Visualizza
        _set_icon(self.actViewToolbar, ":/icons/ph_open.png")
        _set_icon(self.actViewLog, ":/icons/ph_minfo.png")
        self.actViewToolbar.setIconVisibleInMenu(False)
        self.actViewLog.setIconVisibleInMenu(False)
        _set_icon(self.actViewResetLayout, ":/icons/ph_view-refresh.png")
        _set_icon(self.actViewGoTracks, ":/icons/ph_go-next.png")
        _set_icon(self.actViewGoChapters, ":/icons/ph_chapters.png")
        _set_icon(self.actViewGoConcat, ":/icons/ph_mkv.png")

        # Aiuto
        _set_icon(self.actUserManual, ":/icons/ph_help.png")
        _set_icon(self.actAbout, ":/icons/ph_info.png")

    def _build_menus(self) -> None:
        mb = self.menuBar()

        m_file = mb.addMenu(L("File"))
        m_file.addAction(self.actAdd)
        m_file.addAction(self.actRemove)
        m_file.addSeparator()
        m_file.addAction(self.actOutDir)
        m_file.addAction(self.actOpenOutDir)
        m_file.addSeparator()
        if not _is_hevc_embedded():
            m_file.addAction(self.actRestart)
        m_file.addAction(self.actExit)

        m_ops = mb.addMenu(L("Operazioni"))
        m_ops.addAction(self.actTag)
        m_ops.addAction(self.actExtract)
        m_ops.addAction(self.actCut)
        m_ops.addAction(self.actInsertClip)
        m_ops.addAction(self.actRemux)
        m_ops.addSeparator()
        m_ops.addAction(self.actStop)

        m_view = mb.addMenu(L("Visualizza"))
        m_view.addAction(self.actViewToolbar)
        m_view.addAction(self.actViewLog)
        m_view.addAction(self.actViewResetLayout)
        m_view.addSeparator()
        m_view_tabs = m_view.addMenu(L("Vai alla scheda"))
        m_view_tabs.addAction(self.actViewGoTracks)
        m_view_tabs.addAction(self.actViewGoChapters)
        m_view_tabs.addAction(self.actViewGoConcat)

        m_help = mb.addMenu(L("Aiuto"))
        # --- LANGUAGE MENU (standalone only) ---
        if not _is_hevc_embedded():
            try:
                _tr = L if 'L' in globals() else (lambda x: x)
                _log = getattr(self, '_log', None)
                install_language_menu(self, mb, m_help.menuAction(), tr=_tr, log=_log)
            except Exception:
                pass
        m_help.addAction(self.actUserManual)
        try:
            _um_icon = QIcon(":/icons/ph_help.png")
            if _um_icon.isNull():
                _um_icon = QIcon(":/icons/ph_help.png")
            self.actUserManual.setIcon(_um_icon)
            self.actUserManual.setIconVisibleInMenu(True)
        except Exception:
            pass
        m_help.addSeparator()
        m_help.addAction(self.actAbout)

    def _build_toolbar(self) -> None:
        tb = QToolBar(L("Azioni rapide"), self)
        # --- force toolbar icons ---
        tb.setToolButtonStyle(Qt.ToolButtonIconOnly)
        try:
            tb.setIconSize(QSize(32, 32))
        except Exception:
            pass
        # --- force toolbar style (standalone) ---
        tb.setToolButtonStyle(Qt.ToolButtonIconOnly)
        try:
            tb.setIconSize(QSize(32, 32))
        except Exception:
            pass
        # --- toolbar icons visible ---
        tb.setToolButtonStyle(Qt.ToolButtonIconOnly)
        tb.setIconSize(QSize(32, 32))
        tb.setObjectName("toolbar_azioni_rapide")
        tb.setMovable(False)
        tb.setIconSize(QSize(32, 32))
        self.addToolBar(Qt.TopToolBarArea, tb)

        tb.addAction(self.actAdd)
        tb.addAction(self.actRemove)
        tb.addAction(self.actOutDir)
        tb.addAction(self.actOpenOutDir)
        tb.addSeparator()
        tb.addAction(self.actTag)
        tb.addAction(self.actExtract)
        tb.addAction(self.actCut)
        tb.addAction(self.actInsertClip)
        tb.addAction(self.actRemux)
        tb.addSeparator()
        tb.addAction(self.actStop)
        tb.addSeparator()
        tb.addAction(self.actUserManual)
        # --- force toolbar icons (late) ---
        try:
            QTimer.singleShot(0, lambda tb=tb: (
                tb.setToolButtonStyle(Qt.ToolButtonIconOnly),
                tb.setIconSize(QSize(32, 32)),
            ))
        except Exception:
            pass


    def _sync_view_menu_state(self) -> None:
        # Nota: all'avvio, prima dello show(), isVisible() può risultare False anche se
        # la toolbar è destinata a essere visibile. Usiamo isHidden() per uno stato più affidabile.
        try:
            tbs = self.findChildren(QToolBar)
            vis = any(not tb.isHidden() for tb in tbs) if tbs else True
        except Exception:
            vis = True
        try:
            self.actViewToolbar.setChecked(bool(vis))
        except Exception:
            pass

        try:
            if hasattr(self, "actViewLog"):
                self.actViewLog.setChecked(bool(self._is_log_visible()))
        except Exception:
            pass

    def _toggle_toolbar_visible(self, checked: bool) -> None:
        v = bool(checked)
        for tb in self.findChildren(QToolBar):
            try:
                tb.setVisible(v)
            except Exception:
                pass
        self._sync_view_menu_state()

    def _find_log_widget(self):
        try:
            w = getattr(self, "w", None)
            if w is None:
                return None
            # MainWidget ha self.log (QTextEdit)
            lw = getattr(w, "log", None)
            if lw is not None:
                return lw
        except Exception:
            pass
        return None

    def _find_log_container(self):
        lw = self._find_log_widget()
        if lw is None:
            return None
        try:
            p = lw.parentWidget()  # tipicamente QGroupBox "Log"
            if p is not None:
                return p
        except Exception:
            pass
        return lw

    def _is_log_visible(self) -> bool:
        box = self._find_log_container()
        if box is None:
            return False
        try:
            return not box.isHidden()
        except Exception:
            try:
                return box.isVisible()
            except Exception:
                return False

    def _toggle_log_visible(self, checked: bool) -> None:
        box = self._find_log_container()
        if box is None:
            QMessageBox.information(self, L("Visualizza"), L("Pannello log non trovato in questa schermata."))
            try:
                self._sync_view_menu_state()
            except Exception:
                pass
            return
        try:
            box.setVisible(bool(checked))
        except Exception:
            pass
        try:
            self._sync_view_menu_state()
        except Exception:
            pass
        try:
            self._log_view_info(L("Log ") + (L("mostrato") if checked else L("nascosto")))
        except Exception:
            pass

    def _restore_default_view_layout(self) -> None:
        # Ripristina SOLO l'aspetto della GUI (non tocca dati/file/tab corrente)
        restored = 0

        # 0) Riporta visibili toolbar e log (aspetto di avvio)
        try:
            self._toggle_toolbar_visible(True)
        except Exception:
            pass

        try:
            if hasattr(self, "actViewLog"):
                self._toggle_log_visible(True)
        except Exception:
            pass

        try:
            rootw = getattr(self, "w", None)
        except Exception:
            rootw = None

        # 1) Splitter dentro il widget centrale principale
        try:
            splitters = rootw.findChildren(QSplitter) if rootw is not None else []
        except Exception:
            splitters = []

        # 2) Fallback: cerca su tutta la finestra
        if not splitters:
            try:
                splitters = self.findChildren(QSplitter)
            except Exception:
                splitters = []

        # Prima quelli principali
        try:
            splitters = sorted(splitters, key=lambda sp: int(sp.count()), reverse=True)
        except Exception:
            pass

        for sp in splitters:
            try:
                count = int(sp.count())
            except Exception:
                continue

            try:
                if count == 3:
                    # Layout principale MainWidget (lista sorgenti / area centrale / pannello dx)
                    sp.setSizes([320, 860, 360])
                    restored += 1
                elif count == 2:
                    # Splitter secondari (anteprime/tabelle/log ecc.)
                    sp.setSizes([520, 380])
                    restored += 1
            except Exception:
                pass

        # 3) Ritocco visivo tabelle (solo estetica)
        try:
            from PyQt5.QtWidgets import QTableWidget
            tables = rootw.findChildren(QTableWidget) if rootw is not None else []
            for t in tables:
                try:
                    t.resizeColumnsToContents()
                except Exception:
                    pass
        except Exception:
            pass

        # 4) Refresh grafico
        try:
            if rootw is not None:
                rootw.updateGeometry()
                rootw.update()
                rootw.repaint()
        except Exception:
            pass

        # 5) Sincronizza i check del menu Visualizza
        try:
            self._sync_view_menu_state()
        except Exception:
            pass

        try:
            if restored > 0:
                self._log_view_info(L("Layout ripristinato (solo aspetto)."))
            else:
                self._log_view_info(L("Layout ripristinato (toolbar/log)."))
        except Exception:
            pass

    def _log_view_info(self, msg: str) -> None:
        try:
            if hasattr(self, "w") and hasattr(self.w, "_log") and callable(self.w._log):
                self.w._log("[UI] " + msg)
        except Exception:
            pass

    def _find_main_tabwidget(self):
        try:
            tabs = self.w.findChildren(QTabWidget)
        except Exception:
            tabs = []
        if not tabs:
            return None
        # prende quello più "ricco" (quasi sempre il tab centrale principale)
        try:
            tabs = sorted(tabs, key=lambda t: getattr(t, "count", lambda: 0)(), reverse=True)
        except Exception:
            pass
        return tabs[0]

    def _goto_tab_by_names(self, names) -> None:
        tw = self._find_main_tabwidget()
        if tw is None:
            QMessageBox.information(self, L("Visualizza"), L("Schede non trovate in questa schermata."))
            return

        wanted = [str(x).strip().lower() for x in (names or []) if str(x).strip()]
        for i in range(tw.count()):
            try:
                label = (tw.tabText(i) or "").strip().lower()
            except Exception:
                label = ""
            if any(k in label for k in wanted):
                tw.setCurrentIndex(i)
                try:
                    self._log_view_info(L("Scheda attivata: ") + tw.tabText(i))
                except Exception:
                    pass
                return

        QMessageBox.information(
            self,
            L("Visualizza"),
            L("Scheda non disponibile in questa schermata.")
        )

    def _user_manual(self) -> None:
        try:
            from hevc_gui.mkv_suite.ui.user_manual_dialog import UserManualDialog
        except Exception as e:
            QMessageBox.warning(
                self,
                L("User manual"),
                L("Impossibile caricare il manuale interno: {e}").format(e=str(e))
            )
            return

        dlg = getattr(self, "_user_manual_dlg", None)
        if dlg is None:
            try:
                dlg = UserManualDialog(self)
            except Exception as e:
                QMessageBox.warning(
                    self,
                    L("User manual"),
                    L("Impossibile aprire il manuale interno: {e}").format(e=str(e))
                )
                return
            self._user_manual_dlg = dlg
            try:
                dlg.destroyed.connect(self._on_user_manual_destroyed)
            except Exception:
                pass

        try:
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
        except Exception:
            pass

    def _on_user_manual_destroyed(self, *_args) -> None:
        self._user_manual_dlg = None

    def showEvent(self, e):
        try:
            super().showEvent(e)
        except Exception:
            try:
                QMainWindow.showEvent(self, e)
            except Exception:
                pass
        try:
            self._sync_view_menu_state()
        except Exception:
            pass

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if getattr(self, "_geom_restored_once", False):
            return
        self._geom_restored_once = True
        try:
            QTimer.singleShot(0, self._restore_window_geometry_prefs)
        except Exception:
            pass

    def closeEvent(self, event) -> None:
        try:
            self._save_window_geometry_prefs()
        except Exception:
            pass
        super().closeEvent(event)

    def _about(self) -> None:
        """Finestra Informazioni (standalone)."""
        from PyQt5.QtWidgets import QTextBrowser

        ver = '1.0.0.0'
        try:
            vf = Path(__file__).resolve().parents[2] / 'VERSION'  # mkv_tools/VERSION
            if vf.is_file():
                ver = (vf.read_text(encoding='utf-8').strip() or ver)
        except Exception:
            pass

        is_en = False
        try:
            from hevc_gui.mkv_suite.i18n import get_lang, LANG_EN
            is_en = (get_lang() == LANG_EN)
        except Exception:
            pass

        if is_en:
            app_title = "MKV Tools Suite"
            version_label = "Version"
            desc = "Standalone suite for MKV workflows based on MKVToolNix and FFmpeg."
            tools_title = "Included tools"
            tools = [
                "Remux / Create MKV",
                "Track extraction",
                "Chapter handling",
                "Apply Tags",
                "Merge Episodes",
                "Trim",
                "Insert Clip",
            ]
            notes_title = "Current notes"
            notes = [
                "Trim and Insert Clip are available from toolbar and menubar.",
                "Trim and Insert Clip can open even when the main file list is empty.",
                "Both tools can choose the source file directly from their own dialog.",
            ]
            footer = "Personal standalone build and local development workspace."
        else:
            app_title = "Strumenti MKV"
            version_label = "Versione"
            desc = "Suite standalone per flussi MKV basata su MKVToolNix e FFmpeg."
            tools_title = "Tool inclusi"
            tools = [
                "Crea MKV",
                "Estrai tracce",
                "Gestione capitoli",
                "Applica Tag",
                "Unisci episodi",
                "Trim",
                "Insert Clip",
            ]
            notes_title = "Note attuali"
            notes = [
                "Trim e Insert Clip sono disponibili da toolbar e menubar.",
                "Trim e Insert Clip si aprono anche con lista file principale vuota.",
                "Entrambi i tool permettono di scegliere il file sorgente direttamente dal proprio dialog.",
            ]
            footer = "Build standalone personale e workspace locale di sviluppo."

        tools_html = "".join(f"<li>{t}</li>" for t in tools)
        notes_html = "".join(f"<li>{n}</li>" for n in notes)

        dlg = QDialog(self)
        dlg.setWindowTitle(L('Informazioni'))
        dlg.setModal(True)
        try:
            dlg.resize(640, 560)
            dlg.setMinimumSize(580, 500)
        except Exception:
            pass

        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(10)

        try:
            icon_path = Path(__file__).resolve().parent.parent / 'assets' / 'icons' / 'ph_mkv.png'
            if icon_path.is_file():
                pm = QPixmap(str(icon_path)).scaled(96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                li = QLabel(dlg)
                li.setAlignment(Qt.AlignCenter)
                li.setPixmap(pm)
                lay.addWidget(li, 0, Qt.AlignHCenter)
                try:
                    dlg.setWindowIcon(QIcon(str(icon_path)))
                except Exception:
                    pass
        except Exception:
            pass

        html = (
            "<div style='font-family: sans-serif; font-size: 10.5pt;'>"
            "<div align='center'>"
            f"<div style='font-size: 15pt; font-weight: 700;'>{app_title}</div>"
            f"<div style='margin-top: 4px;'><b>{version_label}</b> {ver}</div>"
            f"<div style='margin-top: 10px;'>{desc}</div>"
            "</div>"
            "<hr>"
            f"<div style='margin-top: 8px;'><b>{tools_title}</b></div>"
            f"<ul>{tools_html}</ul>"
            f"<div style='margin-top: 10px;'><b>{notes_title}</b></div>"
            f"<ul>{notes_html}</ul>"
            "<hr>"
            "<div align='center' style='margin-top: 8px;'>"
            "LorisPaganiniHomeStudio - 2026<br>"
            "<a href='mailto:loris.paganini@gmail.com'>loris.paganini@gmail.com</a><br>"
            f"<span style='color: #666;'>{footer}</span>"
            "</div>"
            "</div>"
        )

        view = QTextBrowser(dlg)
        view.setOpenExternalLinks(True)
        view.setReadOnly(True)
        view.setHtml(html)
        try:
            view.setStyleSheet("QTextBrowser { border: 0; background: transparent; }")
        except Exception:
            pass
        lay.addWidget(view, 1)

        bb = QDialogButtonBox(QDialogButtonBox.Ok, parent=dlg)
        bb.accepted.connect(dlg.accept)
        lay.addWidget(bb, 0, Qt.AlignHCenter)

        try:
            dlg.exec()
        except Exception:
            dlg.exec_()


# --- I18N OVERRIDE (standalone) ---
L = _i18n.L
# --- STANDALONE MAIN ENTRYPOINT (restored) ---
def main(argv=None):
    """Entry point per mkv-tools (standalone)."""
    import sys
    argv = list(argv) if argv is not None else sys.argv[1:]

    # Qt binding (PyQt5 / PyQt5)
    try:
        from PyQt5.QtWidgets import QApplication
    except Exception:
        from PyQt5.QtWidgets import QApplication

    embedded = _is_hevc_embedded(argv)
    if embedded:
        _lang = _embedded_lang_env()
        if _lang:
            os.environ["MKV_LANG"] = _lang

    app = QApplication([sys.argv[0]] + argv)
    install_auto_translator(app)

    if embedded:
        try:
            from hevc_gui.gui.appearance_settings import apply_appearance
            apply_appearance(app)
        except Exception:
            pass
        try:
            from PyQt5.QtGui import QIcon
            _theme_name = (os.environ.get("HEVC_QT_ICON_THEME_NAME", "") or "").strip()
            _theme_paths = [x for x in (os.environ.get("HEVC_QT_ICON_THEME_SEARCH_PATHS", "") or "").split(os.pathsep) if x]
            if _theme_paths:
                QIcon.setThemeSearchPaths(_theme_paths)
            if _theme_name:
                QIcon.setThemeName(_theme_name)
        except Exception:
            pass

    # opzionale: applica appearance se esiste
    try:
        if (not embedded) and '_APPLY_APPEARANCE' in globals() and callable(_APPLY_APPEARANCE):
            _APPLY_APPEARANCE(app)
    except Exception:
        pass

    w = EmbeddedWindow()
    apply_to_widget_tree(w)
    w.show()

    try:
        return int(app.exec())
    except Exception:
        return int(app.exec_())

if __name__ == "__main__":
    raise SystemExit(main())
