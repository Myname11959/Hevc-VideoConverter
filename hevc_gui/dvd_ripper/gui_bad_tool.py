#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GUI pura (solo View) per LDVD Ripper — stile file manager.

- Menubar + toolbar.
- Corpo con splitter:
  * Sinistra: albero directory (solo cartelle di default, opzionale mostra file).
  * Destra: tabella file/cartelle della dir selezionata.
  * Sotto: coda .vob selezionati.
- Footer fisso: QStatusBar
  * Sinistra: Stato + “Titolo DVD” + Fase (Vobcopy / postprocess, ecc.)
  * Centro: “Titolo film” (allineato verticalmente alla riga di "Titolo DVD")
  * Destra: pulsanti (Estrai/Passa a HEVC/Annulla/Esci)

Nessuna logica di dominio qui dentro.
"""

from __future__ import annotations
from typing import List
import os

from PyQt5.QtCore import (
    Qt,
    pyqtSignal,
    QItemSelectionModel,
    QModelIndex,
    QSize,
    QDir,
    QDirIterator,
    QUrl,
    QTimer,
    QMimeData,
)

from PyQt5.QtGui import QIcon, QKeySequence

from PyQt5.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QMessageBox,
    QTreeView,
    QTableView,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QToolBar,
    QAction,
    QMenu,
    QMenuBar,
    QLabel,
    #QProgressBar,
    QStatusBar,
    QPushButton,
    QStyle,
    QFileSystemModel,
    QAbstractItemView,
    QCheckBox,
    QApplication,
    QHeaderView,
    QToolButton,
    QSizePolicy,
)

# ── Assicura caricamento risorse QRC (ph_*.png, logo.png) ─────────────
try:
    import hevc_gui.resources.icons_rc  # noqa: F401
except Exception:
    pass

# ===== Modello per l'albero: solo cartelle (opzione mostra file) + freccia solo se ci sono figli =====
class DirTreeModel(QFileSystemModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._show_files = False

    def setShowFiles(self, enabled: bool):
        self._show_files = bool(enabled)

    def hasChildren(self, parent: QModelIndex) -> bool:
        try:
            if not parent.isValid():
                return True
            path = self.filePath(parent)
            if not path or not os.path.isdir(path):
                return False

            it_dirs = QDirIterator(path, QDir.Dirs | QDir.NoDotAndDotDot)
            if it_dirs.hasNext():
                return True

            if self._show_files:
                it_files = QDirIterator(path, QDir.Files | QDir.NoDotAndDotDot)
                return it_files.hasNext()

            return False
        except Exception:
            return super().hasChildren(parent)


class QueueListWidget(QListWidget):
    """
    QListWidget per la coda che accetta drag&drop di file .vob
    (sia dal pannello destro, sia da file manager esterno).
    """

    paths_dropped = pyqtSignal(list)  # list[str]

    def __init__(self, parent=None):
        super().__init__(parent)
        # accetta solo drop (niente drag interno per spostare le righe)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DropOnly)

    def _extract_vob_paths(self, mime: QMimeData) -> list[str]:
        """
        Estrae percorsi .vob/.ifo validi da un QMimeData (drag&drop).
        """
        paths: list[str] = []

        # 1) da URL (drag&drop da file manager)
        for url in mime.urls() or []:
            try:
                p = url.toLocalFile()
            except Exception:
                p = ""
            if not p:
                continue
            if p.lower().endswith((".vob", ".ifo")) and os.path.isfile(p):
                ap = os.path.abspath(p)
                if ap not in paths:
                    paths.append(ap)

        # 2) da testo (alcuni file manager passano percorsi in chiaro)
        text = mime.text() or ""
        if text:
            for line in text.splitlines():
                p = line.strip()
                if not p:
                    continue
                if p.lower().endswith((".vob", ".ifo")) and os.path.isfile(p):
                    ap = os.path.abspath(p)
                    if ap not in paths:
                        paths.append(ap)

        return paths

    def dragEnterEvent(self, event):
        mime = event.mimeData()
        if mime and mime.hasUrls() and self._extract_vob_paths(mime):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        mime = event.mimeData()
        if mime and mime.hasUrls() and self._extract_vob_paths(mime):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        mime = event.mimeData()
        if mime and mime.hasUrls():
            paths = self._extract_vob_paths(mime)
            if paths:
                self.paths_dropped.emit(paths)
                event.acceptProposedAction()
                return
        super().dropEvent(event)


class _ForwardStatusBar(QStatusBar):
    """
    In questa GUI la QStatusBar è usata come contenitore di widget custom (con righe multiple).
    Quindi la message-area “nativa” della QStatusBar spesso non è quella che vuoi.

    Regola GIUSTA:
      - showMessage()/clearMessage() devono andare sulla riga "Stato" (lblStatus),
        NON sulla riga della progressione (lblStage), altrimenti sovrascrivono barra/%/ETA.
    """

    def __init__(self, owner):
        super().__init__(owner)
        self._owner = owner
        self._prev_status_text = ""
        self._restore_timer = QTimer(self)
        self._restore_timer.setSingleShot(True)
        self._restore_timer.timeout.connect(self._restore_prev_status)

    def _restore_prev_status(self):
        try:
            if self._owner and hasattr(self._owner, "set_status"):
                self._owner.set_status(self._prev_status_text or "")
        except Exception:
            pass
        finally:
            self._prev_status_text = ""

    def showMessage(self, text: str, timeout: int = 0) -> None:
        # Salva il precedente SOLO se è un messaggio temporaneo
        if timeout and self._owner is not None:
            try:
                if hasattr(self._owner, "lblStatus") and self._owner.lblStatus is not None:
                    self._prev_status_text = self._owner.lblStatus.text()
                else:
                    self._prev_status_text = ""
            except Exception:
                self._prev_status_text = ""

        # Inoltra sulla riga "Stato"
        try:
            if self._owner and hasattr(self._owner, "set_status"):
                self._owner.set_status(text or "")
        except Exception:
            pass

        # Ripristina dopo timeout (ms), emulando QStatusBar
        try:
            if timeout:
                self._restore_timer.stop()
                self._restore_timer.start(int(timeout))
        except Exception:
            pass

        # Manteniamo anche il comportamento base (non dà fastidio)
        try:
            super().showMessage(text, timeout)
        except Exception:
            pass

    def clearMessage(self) -> None:
        try:
            if self._restore_timer.isActive():
                self._restore_timer.stop()
            # Se avevamo un prev, ripristina. Altrimenti pulisci.
            if self._prev_status_text:
                self._restore_prev_status()
            else:
                if self._owner and hasattr(self._owner, "set_status"):
                    self._owner.set_status("")
        except Exception:
            pass

        try:
            super().clearMessage()
        except Exception:
            pass

class DVDExtractorView(QMainWindow):
    
    # ---- segnali verso il Controller ----
    request_refresh_dvd = pyqtSignal()
    request_eject = pyqtSignal()
    request_close_tray = pyqtSignal()
    request_extract = pyqtSignal()
    request_handoff_to_hevc = pyqtSignal()        # ➜ Passa a HEVC
    request_cancel = pyqtSignal()
    request_exit = pyqtSignal()
    request_set_title_lang = pyqtSignal(str)
    request_open_folder = pyqtSignal()
    request_add_files = pyqtSignal()
    # nuovo: flag globale “Genera SRT”
    request_set_ocr_srt = pyqtSignal(bool)

    request_add_selection = pyqtSignal(list)  # list[str]
    request_remove_selected_from_queue = pyqtSignal(list)  # list[int]
    request_move_up = pyqtSignal(list)                    # list[int]
    request_move_down = pyqtSignal(list)                  # list[int]
    request_clear_queue = pyqtSignal()

    dir_activated = pyqtSignal(str)
    file_activated = pyqtSignal(str)
    open_containing_requested = pyqtSignal(str)
    # ➜ NUOVO: richiesta “Apri in VLC”
    request_open_in_vlc = pyqtSignal()
    # ➜ NUOVO: Apri .srt collegati
    request_open_srt = pyqtSignal()
    # ➜ NUOVO: richiesta “Apri Subtitle Edit”
    request_open_subtitle_edit = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("LDVD Ripper — File Manager View")
        self.setMinimumSize(900, 600)

        self._build_actions()
        self._build_menubar()
        self._build_toolbar()
        self._build_central()
        self._build_footer()
        self.set_splitter_handle_width(12)

        # Stato iniziale / pulizia completa
        self.reset_ui()

        # file manager UX: click nel tree sinistro = aggiorna pannello destro
        self.ensure_file_manager_behavior()
        # ✅ Applica subito (all'avvio) il filtro: mostra file nell'albero
        try:
            self._toggle_tree_show_files(True)
        except Exception:
            pass

    def _qrc_ph_icon(self, name: str) -> QIcon:
        """
        Carica un'icona dal QRC provando PRIMA gli alias "puliti" (<name>.png),
        poi i prefissi ph_/ps_, e cerca sia in :/icons/ che in :/icons/icons/.
        """
        n = (name or "").strip()
        if not n:
            return QIcon()

        candidates = []

        # Se già .png, prova esattamente quello
        if n.lower().endswith(".png"):
            candidates.append(n)
        else:
            # ✅ PRIORITÀ: alias senza prefisso (es: "folder-open" -> "folder-open.png")
            candidates.append(f"{n}.png")

            # poi prefissi
            if n.startswith(("ph_", "ps_")):
                # es: "ph_open" -> prova anche "open.png"
                candidates.append(f"{n}.png")
                candidates.append(f"{n[3:]}.png")
            else:
                candidates.append(f"ph_{n}.png")
                candidates.append(f"ps_{n}.png")

        for base in candidates:
            for p in (f":/icons/{base}", f":/icons/icons/{base}"):
                ic = QIcon(p)
                if not ic.isNull():
                    return ic

        return QIcon()

    def _icon(self, ph_name=None, theme_names=None, standard=None) -> QIcon:
        # 1) priorità: QRC (alias/ph/ps/raw)
        if ph_name:
            ic = self._qrc_ph_icon(str(ph_name))
            if not ic.isNull():
                return ic

        # 2) se mi dai theme_names, prima provo QRC usando quei nomi (alias inclusi)
        if theme_names:
            if isinstance(theme_names, str):
                theme_names = [theme_names]
            for t in theme_names:
                ic = self._qrc_ph_icon(str(t))
                if not ic.isNull():
                    return ic

            # 3) fallback: tema di sistema
            for t in theme_names:
                ic = QIcon.fromTheme(t)
                if not ic.isNull():
                    return ic

        # 4) fallback: icona standard Qt
        if standard is not None:
            try:
                return self.style().standardIcon(standard)
            except Exception:
                pass

        return QIcon()

    # == Costruzione UI ==

    def _build_actions(self) -> None:
        # ✅ icona finestra LDVD (questa è quella che vedi su finestra/pannello se lanci da terminale)
        try:
            self.setWindowIcon(QIcon(":/icons/ldvd-logo.png"))
        except Exception:
            pass

        # === Azioni base ===
        self.actOpenFolder = QAction(
            self._icon("folder-open"),
            "Apri cartella…",
            self,
        )
        try:
            self.actOpenFolder.setShortcut(QKeySequence("Ctrl+O"))
        except Exception:
            self.actOpenFolder.setShortcut("Ctrl+O")
        self.actOpenFolder.triggered.connect(self.request_open_folder.emit)

        self.actAddFiles = QAction(
            self._icon("list-add"),
            "Aggiungi file…",
            self,
        )
        try:
            self.actAddFiles.setShortcut(QKeySequence("Ctrl+I"))
        except Exception:
            self.actAddFiles.setShortcut("Ctrl+I")
        self.actAddFiles.triggered.connect(self.request_add_files.emit)

        # “Apri/Refresh DVD”
        self.actRefresh = QAction(
            self._icon("view-refresh"),
            "Apri/Refresh DVD",
            self,
        )
        try:
            self.actRefresh.setShortcut(QKeySequence("F5"))
        except Exception:
            self.actRefresh.setShortcut("F5")
        self.actRefresh.triggered.connect(self.request_refresh_dvd.emit)

        # Coda
        self.actAddToQueue = QAction(
            self._icon("go-next"),
            "Aggiungi a coda",
            self,
        )
        self.actAddToQueue.triggered.connect(self._emit_add_selection)

        self.actRemoveFromQueue = QAction(
            self._icon("list-remove"),
            "Rimuovi selezionati",
            self,
        )
        self.actRemoveFromQueue.triggered.connect(
            lambda: self.request_remove_selected_from_queue.emit(self.selected_queue_rows())
        )

        self.actMoveUp = QAction(
            self._icon("go-up"),
            "Sposta su",
            self,
        )
        self.actMoveUp.triggered.connect(lambda: self.request_move_up.emit(self.selected_queue_rows()))

        self.actMoveDown = QAction(
            self._icon("go-down"),
            "Sposta giù",
            self,
        )
        self.actMoveDown.triggered.connect(lambda: self.request_move_down.emit(self.selected_queue_rows()))

        self.actClearQueue = QAction(
            self._icon("edit-clear"),
            "Svuota coda",
            self,
        )
        self.actClearQueue.triggered.connect(self.request_clear_queue.emit)

        # ✅ Genera .srt OCR: NESSUNA icona (come richiesto)
        self.actOcrSrt = QAction(
            QIcon(),
            "Genera SRT (.srt via OCR)",
            self,
        )
        self.actOcrSrt.setCheckable(True)
        self.actOcrSrt.setChecked(False)
        self.actOcrSrt.toggled.connect(self._on_act_ocr_srt_toggled)

        # Operazioni
        self.actExtract = QAction(
            self._icon("media-record"),
            "Estrai",
            self,
        )
        try:
            self.actExtract.setShortcut(QKeySequence("Ctrl+E"))
        except Exception:
            self.actExtract.setShortcut("Ctrl+E")
        self.actExtract.triggered.connect(self.request_extract.emit)

        # ✅ Passa a HEVC: NESSUNA icona (come richiesto)
        self.actHandoffHevc = QAction(
            QIcon(),
            "Passa a HEVC",
            self,
        )
        try:
            self.actHandoffHevc.setShortcut(QKeySequence("Ctrl+H"))
        except Exception:
            self.actHandoffHevc.setShortcut("Ctrl+H")
        self.actHandoffHevc.setToolTip("Invia l'ultimo VOB estratto a HEVC-VC (stdout: HEVC_HANDOFF:<path>)")
        self.actHandoffHevc.triggered.connect(self.request_handoff_to_hevc.emit)
        self.actHandoffHevc.setEnabled(False)

        self.actCancel = QAction(
            self._icon("process-stop"),
            "Annulla",
            self,
        )
        try:
            self.actCancel.setShortcut(QKeySequence("Esc"))
        except Exception:
            self.actCancel.setShortcut("Esc")
        self.actCancel.triggered.connect(self.request_cancel.emit)

        # Lettore (cassetto)
        self.actEject = QAction(
            self._icon("media-eject"),
            "Eject (apri cassetto)",
            self,
        )
        self.actEject.triggered.connect(self.request_eject.emit)

        self.actCloseTray = QAction(
            self._icon("media-playback-stop"),
            "Chiudi cassetto",
            self,
        )
        self.actCloseTray.triggered.connect(self.request_close_tray.emit)

        # Apri DVD in VLC
        self.actOpenInVlc = QAction(
            self._icon("media-playback-start"),
            "Apri in VLC",
            self,
        )
        self.actOpenInVlc.setStatusTip("Riproduci il DVD attuale con VLC")
        self.actOpenInVlc.setToolTip("Apri il DVD attuale in VLC")
        self.actOpenInVlc.triggered.connect(self.request_open_in_vlc.emit)

        # Apri .srt
        self.actOpenSrt = QAction(
            self._icon("document-open"),
            "Apri sottotitoli .srt",
            self,
        )
        self.actOpenSrt.setStatusTip("Apri i .srt generati/collegati all'ultimo titolo estratto")
        self.actOpenSrt.setToolTip("Apri sottotitoli .srt")
        self.actOpenSrt.triggered.connect(self.request_open_srt.emit)

        # Apri Subtitle Edit
        self.actOpenSubtitleEdit = QAction(
            self._icon("text-subtitle"),
            "Apri Subtitle Edit…",
            self,
        )
        self.actOpenSubtitleEdit.setStatusTip("Avvia Subtitle Edit per lavorare sui sottotitoli del DVD")
        self.actOpenSubtitleEdit.setToolTip("Apri Subtitle Edit")
        self.actOpenSubtitleEdit.triggered.connect(self.request_open_subtitle_edit.emit)

        # Alias compat
        self.actOpenSubEdit = self.actOpenSubtitleEdit

        # Lingua (menù)
        self.actLangIt = QAction("Italiano (it)", self)
        self.actLangIt.setCheckable(True)
        self.actLangEn = QAction("English (en)", self)
        self.actLangEn.setCheckable(True)
        self.actLangGroup = [self.actLangIt, self.actLangEn]
        self.actLangIt.setChecked(True)
        self.actLangEn.setChecked(False)
        self.actLangIt.triggered.connect(lambda: self.request_set_title_lang.emit("it"))
        self.actLangEn.triggered.connect(lambda: self.request_set_title_lang.emit("en"))

        # Help/About (qui puoi lasciare HEVC-style con ph_)
        self.actAbout = QAction(
            self._icon("ph_info", ["help-about", "dialog-information"], QStyle.SP_MessageBoxInformation),
            "Informazioni…",
            self,
        )
        self.actAbout.triggered.connect(self._show_about)

        # Uscita (usa la tua ph_exit)
        self.actExit = QAction(
            self._icon("exit", ["application-exit"], QStyle.SP_DialogCloseButton),
            "Esci",
            self,
        )

    def _build_menubar(self) -> None:
        mb: QMenuBar = self.menuBar()

        # --- File ---
        m_file: QMenu = mb.addMenu("&File")
        m_file.addAction(self.actOpenFolder)
        m_file.addAction(self.actAddFiles)
        m_file.addAction(self.actRefresh)
        m_file.addSeparator()
        m_file.addAction(self.actEject)
        m_file.addAction(self.actCloseTray)
        # voce “Apri in VLC”
        m_file.addSeparator()
        m_file.addAction(self.actOpenInVlc)
        m_file.addSeparator()
        m_file.addAction(self.actExit)

        # --- Azioni ---
        m_actions: QMenu = mb.addMenu("&Azioni")
        m_actions.addAction(self.actExtract)
        # flag OCR SRT nel menu Azioni
        m_actions.addAction(self.actOcrSrt)
        # nuovo: Apri sottotitoli .srt collegati
        m_actions.addAction(self.actOpenSrt)
        # nuova voce: Apri Subtitle Edit
        m_actions.addAction(self.actOpenSubtitleEdit)
        m_actions.addAction(self.actHandoffHevc)          # Passa a HEVC
        m_actions.addAction(self.actCancel)
        m_actions.addSeparator()
        m_actions.addAction(self.actAddToQueue)
        m_actions.addAction(self.actRemoveFromQueue)
        m_actions.addAction(self.actMoveUp)
        m_actions.addAction(self.actMoveDown)
        m_actions.addAction(self.actClearQueue)


        # --- Visualizza ---
        m_view: QMenu = mb.addMenu("&Visualizza")
        m_lang = m_view.addMenu("Lingua titoli")
        m_lang.addAction(self.actLangIt)
        m_lang.addAction(self.actLangEn)

        self.actTreeShowFiles = QAction("Mostra file nell'albero", self)
        self.actTreeShowFiles.setCheckable(True)
        self.actTreeShowFiles.setChecked(True)
        self.actTreeShowFiles.toggled.connect(self._toggle_tree_show_files)
        m_view.addAction(self.actTreeShowFiles)

        # --- Aiuto ---
        m_help: QMenu = mb.addMenu("&Aiuto")
        m_help.addAction(self.actAbout)

    def _build_toolbar(self) -> None:
        tb: QToolBar = QToolBar("Strumenti", self)

        # 📌 Scegli qui la dimensione reale delle tue PNG (consiglio: 28 o 32)
        # Se sono 32x32 metti 32, così non vengono scalate.
        icon_px = 32

        tb.setIconSize(QSize(icon_px, icon_px))
        tb.setToolButtonStyle(Qt.ToolButtonIconOnly)
        tb.setMovable(False)

        # ✅ Toolbar “compatta” + toolbutton = icona (niente padding enorme)
        tb.setStyleSheet(f"""
            QToolBar {{
                padding: 2px;
                spacing: 4px;
            }}
            QToolButton {{
                padding: 0px;
                margin: 0px;
                border: 0px;
                background: transparent;
            }}
            QToolButton:hover {{
                background: rgba(255,255,255,0.06);
                border-radius: 4px;
            }}
            QToolButton:pressed {{
                background: rgba(0,0,0,0.12);
                border-radius: 4px;
            }}
            QToolButton:disabled {{
                opacity: 0.40;
            }}
        """)

        # altezza coerente
        tb.setMinimumHeight(icon_px + 6)

        self.addToolBar(Qt.TopToolBarArea, tb)

        # --- Gruppi azioni ---
        tb.addAction(self.actOpenFolder)
        tb.addAction(self.actAddFiles)
        tb.addSeparator()

        tb.addAction(self.actRefresh)
        tb.addSeparator()

        tb.addAction(self.actAddToQueue)
        tb.addAction(self.actRemoveFromQueue)
        tb.addAction(self.actMoveUp)
        tb.addAction(self.actMoveDown)
        tb.addAction(self.actClearQueue)
        tb.addSeparator()

        tb.addAction(self.actExtract)

        # ❌ tolto dalla toolbar: Passa a HEVC (resta nel menu + bottone footer)
        # tb.addAction(self.actHandoffHevc)

        tb.addSeparator()
        tb.addAction(self.actOpenSrt)
        tb.addAction(self.actOpenSubtitleEdit)
        tb.addSeparator()

        tb.addAction(self.actCancel)
        tb.addSeparator()

        tb.addAction(self.actEject)
        tb.addAction(self.actCloseTray)
        tb.addSeparator()

        tb.addAction(self.actOpenInVlc)

        self.toolbar = tb

        # --- Azione CLEAR (rimane in fondo) ---
        ico_clear = self._icon("edit-clear", None, QStyle.SP_DialogResetButton)
        self.actClear = QAction(ico_clear, "Clear", self)
        self.actClear.setToolTip("Pulisci la GUI e ripristina i default")
        self.actClear.setStatusTip("Pulisce viste, coda, campi e progress")
        tb.addAction(self.actClear)

        # Checkbox per SRT
        self.chkOcrSrt = QCheckBox("Genera SRT", tb)
        self.chkOcrSrt.setChecked(False)
        self.chkOcrSrt.toggled.connect(self._on_chk_ocr_srt_toggled)
        tb.addWidget(self.chkOcrSrt)

        # ✅ Step finale: forza tutti i QToolButton ad essere grandi ESATTAMENTE come l'icona
        # (così la tua PNG “è” il pulsante)
        for b in tb.findChildren(QToolButton):
            b.setAutoRaise(True)  # flat
            b.setFixedSize(QSize(icon_px, icon_px))
            b.setIconSize(QSize(icon_px, icon_px))

    def _build_central(self) -> None:
        # Modello FS per ALBERO (sinistra)
        self.fsModelDirs = DirTreeModel(self)
        self.fsModelDirs.setRootPath("/")
        self.fsModelDirs.setReadOnly(True)
        self.fsModelDirs.setFilter(QDir.AllDirs | QDir.NoDotAndDotDot | QDir.Drives)

        # Modello FILE+DIR (destra)
        self.fsModelFiles = QFileSystemModel(self)
        self.fsModelFiles.setRootPath("/")
        self.fsModelFiles.setReadOnly(True)
        self.fsModelFiles.setFilter(QDir.AllEntries | QDir.NoDotAndDotDot)

        # Tree (sinistra)
        self.treeDirs = QTreeView(self)
        self.treeDirs.setObjectName("treeDirs")
        self.treeDirs.setModel(self.fsModelDirs)
        self.treeDirs.setHeaderHidden(False)
        self.treeDirs.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.treeDirs.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.treeDirs.setUniformRowHeights(True)
        self.treeDirs.setAnimated(True)
        self.treeDirs.header().setSectionResizeMode(QHeaderView.Interactive)
        self.treeDirs.header().setStretchLastSection(True)
        self.treeDirs.doubleClicked.connect(self._on_tree_activated)

        # Files (destra)
        self.viewFiles = QTableView(self)
        self.viewFiles.setObjectName("viewFiles")
        self.viewFiles.setModel(self.fsModelFiles)
        self.viewFiles.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.viewFiles.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.viewFiles.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.viewFiles.doubleClicked.connect(self._on_files_activated)
        self.viewFiles.setSortingEnabled(True)
        self.viewFiles.sortByColumn(0, Qt.AscendingOrder)
        self.viewFiles.setAlternatingRowColors(True)
        self.viewFiles.setContextMenuPolicy(Qt.CustomContextMenu)
        self.viewFiles.customContextMenuRequested.connect(self._on_files_context_menu)
        self.viewFiles.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.viewFiles.horizontalHeader().setStretchLastSection(True)
        # sorgente di drag per i .vob
        self.viewFiles.setDragEnabled(True)
        self.viewFiles.setDragDropMode(QAbstractItemView.DragOnly)

        # Splitter orizzontale
        split_top = QSplitter(Qt.Horizontal, self)
        split_top.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        split_top.addWidget(self.treeDirs)
        split_top.addWidget(self.viewFiles)
        split_top.setStretchFactor(0, 1)
        split_top.setStretchFactor(1, 2)
        split_top.setHandleWidth(12)

        # Coda (sotto) — con drag&drop
        self.listQueue = QueueListWidget(self)
        self.listQueue.setObjectName("listQueue")
        self.listQueue.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.listQueue.setContextMenuPolicy(Qt.CustomContextMenu)
        self.listQueue.customContextMenuRequested.connect(self._on_queue_context_menu)
        self.listQueue.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # Drag&drop: quando cadono dei percorsi, li rimandiamo al Controller
        self.listQueue.paths_dropped.connect(self._on_queue_paths_dropped)

        # Splitter verticale
        split_main = QSplitter(Qt.Vertical, self)
        split_main.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        split_main.addWidget(split_top)
        split_main.addWidget(self.listQueue)
        split_main.setStretchFactor(0, 3)
        split_main.setStretchFactor(1, 1)
        split_main.setHandleWidth(12)

        # Central widget
        cw = QWidget(self)
        cw.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        lay = QVBoxLayout(cw)
        lay.setContentsMargins(6, 6, 0, 0)
        lay.addWidget(split_main)
        self.setCentralWidget(cw)

        # Larghezze iniziali
        for c, w in [(0, 320), (1, 120), (2, 160), (3, 180)]:
            self.viewFiles.setColumnWidth(c, w)
        self.treeDirs.setColumnWidth(0, 300)

    def _build_footer(self) -> None:
        # Status bar fissa a fondo finestra
        sb = self.statusBar()
        if not isinstance(sb, _ForwardStatusBar):
            sb = _ForwardStatusBar(self)
            self.setStatusBar(sb)
        sb.setSizeGripEnabled(True)

        from PyQt5.QtWidgets import QGridLayout

        # Root: ora è a DUE RIGHE
        #  - Riga 1: contenuti (sinistra + stretch + bottoni destra)
        #  - Riga 2: riga vuota per "aria"
        root = QWidget(self)
        root_v = QVBoxLayout(root)
        root_v.setContentsMargins(6, 0, 6, 0)
        root_v.setSpacing(0)

        # --- Riga 1: contenuti ---
        row = QWidget(root)
        row_lay = QHBoxLayout(row)
        row_lay.setContentsMargins(0, 0, 0, 0)
        row_lay.setSpacing(12)

        # --- SINISTRA: Stato + Titolo DVD + Titolo film + Vobcopy stage ---
        left = QWidget(row)
        vl = QVBoxLayout(left)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(2)

        self.lblStatus = QLabel("Pronto", left)
        self.lblDvdTitle = QLabel("Titolo DVD: —", left)

        # ✅ Spostata qui: tra Titolo DVD e Vobcopy
        self.lblMovieTitle = QLabel("Titolo film: —", left)

        # Label usata per Vobcopy / ETA / percentuale
        self.lblStage = QLabel("", left)
        self.lblStage.setObjectName("lblStage")
        self.lblStage.setStyleSheet("color:#666666; font-size: 11px;")
        self.lblStage.setTextFormat(Qt.RichText)
        self.lblStage.setWordWrap(False)
        self.lblStage.setTextInteractionFlags(Qt.TextSelectableByMouse)

        vl.addWidget(self.lblStatus)
        vl.addWidget(self.lblDvdTitle)
        vl.addWidget(self.lblMovieTitle)   # ✅ qui in mezzo
        vl.addWidget(self.lblStage)

        row_lay.addWidget(left)

        # Stretch centrale per spingere i bottoni a destra
        row_lay.addStretch(1)

        # --- DESTRA: 2x2 pulsanti ancorati a destra ---
        right = QWidget(row)
        grid = QGridLayout(right)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)

        self.btnExtract = QPushButton("Estrai", right)
        self.btnHevc    = QPushButton("Passa a HEVC", right)
        self.btnCancel  = QPushButton("Annulla", right)
        self.btnExit    = QPushButton("Esci", right)

        for b in (self.btnExtract, self.btnHevc, self.btnCancel, self.btnExit):
            b.setFixedHeight(26)

        # Connessioni bottoni → segnali verso il Controller
        self.btnExtract.clicked.connect(self.request_extract.emit)
        self.btnHevc.clicked.connect(self.request_handoff_to_hevc.emit)
        self.btnCancel.clicked.connect(self.request_cancel.emit)
        self.btnExit.clicked.connect(self.request_exit.emit)

        # Griglia 2x2
        grid.addWidget(self.btnExtract, 0, 0)
        grid.addWidget(self.btnHevc,    0, 1)
        grid.addWidget(self.btnCancel,  1, 0)
        grid.addWidget(self.btnExit,    1, 1)

        row_lay.addWidget(right, 0, Qt.AlignRight)

        # --- Riga 2: riga vuota (aria) ---
        air = QWidget(root)
        air.setFixedHeight(8)  # puoi alzare a 10/12 se la vuoi più “morbida”

        # Inserisci righe nel root
        root_v.addWidget(row)
        root_v.addWidget(air)

        # Unico widget dentro la statusbar
        sb.addPermanentWidget(root, 1)

    # == Helpers UI interni ==

    def _show_about(self):
        QMessageBox.about(
            self,
            "DVD Ripper — Informazioni",
            "<b>DVD Ripper</b><br>"
            "GUI split (albero / file / coda) con estrazione VOB nativa e sidecar, "
            "più handoff a HEVC.<br><br>"
            "© Loris — Tool di backup personale.<br>"
            "<small>Può integrare un remux DVD (lossless) opzionale se disponibile.</small>",
        )

    # --- Lingua titoli (solo da menù, niente combo toolbar) ---

    def set_titlecase_lang(self, code: str) -> None:
        code = (code or "it").lower()
        self.actLangIt.setChecked(code == "it")
        self.actLangEn.setChecked(code == "en")

    # --- Toggle "Mostra file nell'albero" ---

    def _toggle_tree_show_files(self, checked: bool) -> None:
        try:
            self.fsModelDirs.setShowFiles(checked)
            filt = QDir.AllDirs | QDir.NoDotAndDotDot | QDir.Drives
            if checked:
                filt |= QDir.Files
            self.fsModelDirs.setFilter(filt)

            idx = self.treeDirs.rootIndex()
            cur_path = self.fsModelDirs.filePath(idx) if idx.isValid() else "/"
            self.fsModelDirs.setRootPath(cur_path)
            self.treeDirs.setRootIndex(self.fsModelDirs.index(cur_path))

            self._rebind_tree_selection()
        except Exception:
            pass

    # --- OCR / SRT: wiring interno ---

    def _on_act_ocr_srt_toggled(self, checked: bool) -> None:
        """
        Azione di menù/toolbar 'Genera SRT' cambiata.
        Tiene in sync la checkbox e notifica il Controller.
        """
        try:
            cb = getattr(self, "chkOcrSrt", None)
            if cb is not None:
                cb.blockSignals(True)
                cb.setChecked(bool(checked))
                cb.blockSignals(False)
        except Exception:
            pass
        # notifica il Controller
        self.request_set_ocr_srt.emit(bool(checked))

    def _on_chk_ocr_srt_toggled(self, checked: bool) -> None:
        """
        Checkbox in toolbar per 'Genera SRT' cambiata.
        Rimanda lo stato all'azione, che gestisce il segnale verso il Controller.
        """
        try:
            self.actOcrSrt.setChecked(bool(checked))
        except Exception:
            # se per qualche motivo l'azione manca, almeno emettiamo il segnale
            self.request_set_ocr_srt.emit(bool(checked))

    # --- FS helpers ---

    def set_file_panel_path(self, path: str) -> None:
        if not path:
            return
        try:
            base = os.path.abspath(path)
            self.fsModelFiles.setRootPath(base)
            idx = self.fsModelFiles.index(base)
            if idx.isValid():
                self.viewFiles.setRootIndex(idx)
                for c, w in ((0, 320), (1, 120), (2, 160), (3, 180)):
                    try:
                        self.viewFiles.setColumnWidth(c, w)
                    except Exception:
                        pass
                try:
                    first = self.fsModelFiles.index(0, 0, idx)
                    if first.isValid():
                        self.viewFiles.setCurrentIndex(first)
                        self.viewFiles.scrollTo(first)
                except Exception:
                    pass
        except Exception:
            pass

    def select_in_tree(self, path: str) -> None:
        if not path:
            return
        try:
            p = os.path.abspath(path)
            idx = self.fsModelDirs.index(p)
            if idx.isValid():
                self.treeDirs.setCurrentIndex(idx)
                self.treeDirs.expand(idx)
                self.treeDirs.scrollTo(idx)
        except Exception:
            pass

    def ensure_file_manager_behavior(self) -> None:
        self._rebind_tree_selection()

    def _rebind_tree_selection(self) -> None:
        try:
            sel = self.treeDirs.selectionModel()
            if sel is None:
                return
            try:
                sel.currentChanged.disconnect(self._on_tree_current_changed)
            except Exception:
                pass
            sel.currentChanged.connect(self._on_tree_current_changed)
        except Exception:
            pass

    def _on_tree_current_changed(self, current, _previous):
        try:
            path = self.fsModelDirs.filePath(current)
            if path:
                self.dir_activated.emit(path)
        except Exception:
            pass

    def _on_tree_activated(self, idx):
        try:
            path = self.fsModelDirs.filePath(idx)
            if not path:
                return
            if os.path.isdir(path):
                self.dir_activated.emit(path)
            else:
                self.file_activated.emit(path)
        except Exception:
            pass

    def _on_files_activated(self, idx):
        try:
            path = self.fsModelFiles.filePath(idx)
            if path:
                self.file_activated.emit(path)
        except Exception:
            pass

    def _on_files_context_menu(self, pos) -> None:
        menu = QMenu(self.viewFiles)
        add = menu.addAction("Aggiungi a coda")
        open_folder = menu.addAction("Apri cartella contenente")
        act = menu.exec_(self.viewFiles.viewport().mapToGlobal(pos))
        if act == add:
            self._emit_add_selection()
        elif act == open_folder:
            sel = self.viewFiles.selectionModel()
            if sel and sel.selectedRows():
                p = self.fsModelFiles.filePath(sel.selectedRows(0)[0])
                if p:
                    self.open_containing_requested.emit(p)

    def _on_queue_context_menu(self, pos) -> None:
        menu = QMenu(self.listQueue)
        a_open = menu.addAction("Apri cartella contenente")
        a_rem = menu.addAction("Rimuovi")
        a_up = menu.addAction("Sposta su")
        a_down = menu.addAction("Sposta giù")
        a_clear = menu.addAction("Svuota coda")
        act = menu.exec_(self.listQueue.viewport().mapToGlobal(pos))
        if act == a_open:
            rows = self.selected_queue_rows()
            if rows:
                item = self.listQueue.item(rows[0])
                if item:
                    self.open_containing_requested.emit(item.text())
        elif act == a_rem:
            self._emit_remove_selected_from_queue()
        elif act == a_up:
            self._emit_move_up()
        elif act == a_down:
            self._emit_move_down()
        elif act == a_clear:
            self.request_clear_queue.emit()

    def _emit_add_selection(self) -> None:
        """
        Invia al Controller i percorsi selezionati nel pannello destro,
        ma filtra qui almeno a .vob/.ifo per non mandare cartelle o roba varia.
        """
        paths = []
        for p in self.selected_right_paths():
            low = (p or "").lower()
            if low.endswith(".vob") or low.endswith(".ifo"):
                paths.append(p)
        if paths:
            self.request_add_selection.emit(paths)

    def _on_queue_paths_dropped(self, paths: List[str]) -> None:
        """
        Riceve i percorsi .vob droppati nella coda e li inoltra al Controller.
        """
        if not paths:
            return
        self.request_add_selection.emit(paths)

    def _emit_remove_selected_from_queue(self) -> None:
        self.request_remove_selected_from_queue.emit(self.selected_queue_rows())

    def _emit_move_up(self) -> None:
        self.request_move_up.emit(self.selected_queue_rows())

    def _emit_move_down(self) -> None:
        self.request_move_down.emit(self.selected_queue_rows())

    # == API View esposte al Controller ==
    def set_root_path(self, path: str) -> None:
        if not path:
            return
        base = os.path.abspath(path)

        def _find_video_ts(p: str) -> str:
            try:
                vt = os.path.join(p, "VIDEO_TS")
                if os.path.isdir(vt):
                    return vt
                for n in os.listdir(p):
                    q = os.path.join(p, n)
                    if os.path.isdir(q) and n.upper().startswith("VIDEO_TS"):
                        return q
            except Exception:
                pass
            return p

        try:
            idx_root = self.fsModelDirs.setRootPath(base)
            if idx_root.isValid():
                self.treeDirs.setRootIndex(idx_root)
                self.treeDirs.setCurrentIndex(idx_root)
                self.treeDirs.expand(idx_root)
                vt_dir = _find_video_ts(base)
                if vt_dir != base:
                    idx_vt = self.fsModelDirs.index(vt_dir)
                    if idx_vt.isValid():
                        self.treeDirs.setCurrentIndex(idx_vt)
                        self.treeDirs.scrollTo(idx_vt)
        except Exception:
            pass

        files_root = _find_video_ts(base)
        try:
            self.fsModelFiles.setRootPath(files_root)
            idx_files = self.fsModelFiles.index(files_root)
            if idx_files.isValid():
                self.viewFiles.setRootIndex(idx_files)
                for c, w in ((0, 320), (1, 120), (2, 160), (3, 180)):
                    try:
                        self.viewFiles.setColumnWidth(c, w)
                    except Exception:
                        pass
                try:
                    first = self.fsModelFiles.index(0, 0, idx_files)
                    if first.isValid():
                        self.viewFiles.setCurrentIndex(first)
                        self.viewFiles.scrollTo(first)
                except Exception:
                    pass
        except Exception:
            pass

        self._rebind_tree_selection()

    def set_dvd_title(self, title: str) -> None:
        self.lblDvdTitle.setText(f"Titolo DVD: <b>{title or '—'}</b>")

    def set_movie_title(self, title: str) -> None:
        # Stesso stile di set_dvd_title(): label + valore in grassetto
        self.lblMovieTitle.setText(f"Titolo film: <b>{title or '—'}</b>")

    def set_status(self, text: str) -> None:
        self.lblStatus.setText(text or "")

    def set_progress_stage(self, s: str) -> None:
        """
        Aggiorna la label 'Fase' (lblStage).
        Supporta stringhe tipo:
          - "Vobcopy [=====>     ] 42% ETA 01:23"
          - qualunque altra stringa (mostrata in grigio)
        """
        if not hasattr(self, "lblStage") or self.lblStage is None:
            return

        s = (s or "").strip()
        if not s:
            self.lblStage.setText("")
            return

        def _shrink_bar(bar: str, factor: float = 0.5) -> str:
            """
            Prende una barra tipo "[====>   ]" e la rende più corta,
            mantenendo la percentuale (circa) e la freccia '>'.
            """
            if not (bar.startswith("[") and bar.endswith("]")):
                return bar
            inner = bar[1:-1]
            L = len(inner)
            if L <= 2:
                return bar

            # conta gli '=' iniziali
            eq_len = 0
            for ch in inner:
                if ch == "=":
                    eq_len += 1
                else:
                    break

            has_arrow = ">" in inner
            new_total = max(3, int(L * factor))

            if new_total >= L:
                return bar

            ratio = eq_len / float(L) if L else 0.0

            if has_arrow:
                eq_new = max(1, min(new_total - 1, int(round(ratio * new_total))))
                spaces_new = max(0, new_total - eq_new - 1)
                new_inner = "=" * eq_new + ">" + " " * spaces_new
            else:
                eq_new = max(1, min(new_total, int(round(ratio * new_total))))
                spaces_new = max(0, new_total - eq_new)
                new_inner = "=" * eq_new + " " * spaces_new

            return "[" + new_inner + "]"

        lower = s.lower()
        if lower.startswith("vobcopy"):
            # Tolgo "Vobcopy" e l'eventuale ":"
            rest = s[len("Vobcopy"):].lstrip()
            if rest.startswith(":"):
                rest = rest[1:].lstrip()

            import re
            tokens = rest.split()
            bar = ""

            # Se il primo token è una barra [===...] lo tratto come tale
            if tokens and tokens[0].startswith("["):
                bar = tokens[0]
                tokens = tokens[1:]

            # Barra ridotta (così non diventa “due metri”)
            if bar:
                bar = _shrink_bar(bar, factor=0.5)

            # Cerca percentuale e tempo (mm:ss)
            perc = ""
            eta_time = ""
            for t in tokens:
                if "%" in t:
                    perc = t
                    break
            for t in reversed(tokens):
                if re.match(r"^\d{1,2}:\d{2}$", t):
                    eta_time = t
                    break

            # HTML (come volevi tu)
            html = "<span style='font-weight:bold; color:#cc0000;'>Vobcopy</span>"
            if bar:
                html += f" <span style='font-weight:bold; color:#000000;'>{bar}</span>"
            if perc:
                html += f" <span style='font-weight:bold; color:#0044aa;'>{perc}</span>"
            if eta_time:
                html += (
                    " <span style='font-weight:bold; color:#008800;'>ETA</span>"
                    f" <span style='font-weight:bold; color:#008800;'>{eta_time}</span>"
                )

            self.lblStage.setText(html)
        else:
            safe = s.replace("<", "&lt;").replace(">", "&gt;")
            self.lblStage.setText(f"<span style='color:#666666;'>{safe}</span>")

    def set_progress(self, value: int) -> None:
        """
        Compat: il Controller usa ancora set_progress(p) per la percentuale,
        ma la riga lblStage è riservata a: barra + % + ETA (renderizzata dal Controller).
        Qui NON tocchiamo lblStage.
        """
        try:
            self._last_progress = max(0, min(100, int(value)))
        except Exception:
            self._last_progress = 0

    def set_progress_indeterminate(self, enabled: bool):
        """
        Compat: alcuni pezzi di Controller potrebbero accendere/spegnere “indeterminate”.
        Qui lo traduciamo in una riga stage minimale.
        """
        if bool(enabled):
            self.set_progress_stage("Vobcopy …")
        else:
            # non svuotare se magari vuoi lasciare l'ultimo stato visibile:
            # se preferisci pulire davvero, lascia così.
            self.set_progress_stage("")

    # Compat (tenuta per non rompere vecchio codice)
    def install_stage_label(self):
        return

    def reset_ui(self):
        # Pulisce selezioni e contenuti base (coda, ecc.)
        for name in (
            "treeDirs",
            "viewFiles",
            "listFiles",
            "listChosen",
            "lstQueue",
            "tableQueue",
            "queueView",
            "listQueue",
        ):
            w = getattr(self, name, None)
            if not w:
                continue
            try:
                w.clearSelection()
            except Exception:
                pass
            try:
                w.clear()
            except Exception:
                pass
            try:
                m = w.model()
                if m and hasattr(m, "removeRows"):
                    try:
                        m.removeRows(0, m.rowCount())
                    except Exception:
                        pass
            except Exception:
                pass

        for name in ("leTitle", "lineTitle", "leOutput", "leDest", "leFolder"):
            w = getattr(self, name, None)
            if w:
                try:
                    w.clear()
                except Exception:
                    pass

        for name in ("chkChapters", "chkSubsLang", "chkOcrSrt", "chkUseRam", "chkStrictSafe"):
            cb = getattr(self, name, None)
            if cb:
                try:
                    cb.setChecked(False)
                except Exception:
                    pass

        try:
            self.set_status("Pronto")
        except Exception:
            pass
        try:
            self.set_dvd_title("—")
        except Exception:
            pass
        try:
            self.set_movie_title("—")
        except Exception:
            pass
        try:
            self.set_progress_stage("Pronto")
        except Exception:
            pass

        try:
            if hasattr(self, "actLangIt") and hasattr(self, "actLangEn"):
                self.actLangIt.setChecked(True)
                self.actLangEn.setChecked(False)
        except Exception:
            pass

        # disabilita il bottone/azione HEVC finché non c'è un VOB fresco
        self.set_handoff_enabled(False)

        # reset SRT toggle
        try:
            self.set_ocr_srt_enabled(False)
        except Exception:
            pass

    def set_busy(self, busy: bool) -> None:
        en = not busy
        for act in (
            getattr(self, "actRefresh", None),
            getattr(self, "actEject", None),
            getattr(self, "actCloseTray", None),
            getattr(self, "actExtract", None),
            getattr(self, "actOpenSrt", None),
            getattr(self, "actOpenSubEdit", None),
            getattr(self, "actHandoffHevc", None),
            getattr(self, "actAddToQueue", None),
            getattr(self, "actRemoveFromQueue", None),
            getattr(self, "actMoveUp", None),
            getattr(self, "actMoveDown", None),
            getattr(self, "actClearQueue", None),
            getattr(self, "actOpenFolder", None),
            getattr(self, "actAddFiles", None),
            getattr(self, "actOcrSrt", None),
        ):
            if act:
                act.setEnabled(en)

        # Pulsanti
        mapping = (
            ("btnExtract", en),
            ("btnHevc", en),
            ("btnCancel", True),
            ("btnExit", True),
        )
        for btn_name, on in mapping:
            btn = getattr(self, btn_name, None)
            if btn:
                btn.setEnabled(on)

        for wname in ("treeDirs", "viewFiles", "listQueue"):
            w = getattr(self, wname, None)
            if w:
                w.setEnabled(en)

        # checkbox SRT segue lo stato globale
        cb = getattr(self, "chkOcrSrt", None)
        if cb is not None:
            cb.setEnabled(en)

        for a in getattr(self, "actLangGroup", []):
            try:
                a.setEnabled(en)
            except Exception:
                pass

    def set_ocr_srt_enabled(self, enabled: bool) -> None:
        """Aggiorna lo stato check di Genera SRT (azione + checkbox) dal Controller."""
        val = bool(enabled)
        try:
            self.actOcrSrt.blockSignals(True)
            self.actOcrSrt.setChecked(val)
            self.actOcrSrt.blockSignals(False)
        except Exception:
            pass
        try:
            cb = getattr(self, "chkOcrSrt", None)
            if cb is not None:
                cb.blockSignals(True)
                cb.setChecked(val)
                cb.blockSignals(False)
        except Exception:
            pass

    def set_queue_items(self, items: List[str]) -> None:
        self.listQueue.clear()
        for p in items or []:
            it = QListWidgetItem(p)
            it.setToolTip(p)
            self.listQueue.addItem(it)

    def selected_right_paths(self) -> List[str]:
        sel: QItemSelectionModel = self.viewFiles.selectionModel()
        if not sel:
            return []
        paths: List[str] = []
        for idx in sel.selectedRows(0):
            if not idx.isValid():
                continue
            paths.append(self.fsModelFiles.filePath(idx))
        return paths

    def selected_queue_rows(self) -> List[int]:
        return sorted({i.row() for i in self.listQueue.selectedIndexes()})

    def set_splitter_handle_width(self, px: int = 12) -> None:
        for sp in self.findChildren(QSplitter):
            sp.setHandleWidth(int(px))

    # ➜ API usata dal Controller per abilitare/disabilitare “Passa a HEVC”
    def set_handoff_enabled(self, enabled: bool) -> None:
        if hasattr(self, "actHandoffHevc") and self.actHandoffHevc:
            self.actHandoffHevc.setEnabled(bool(enabled))
        if hasattr(self, "btnHevc") and self.btnHevc:
            self.btnHevc.setEnabled(bool(enabled))

    # Mantieni l’allineamento di “Titolo film” anche dopo resize/cambio font
    def resizeEvent(self, ev):
        try:
            if hasattr(self, "_align_movie_title_row"):
                self._align_movie_title_row()
        except Exception:
            pass
        super().resizeEvent(ev)


# Avvio locale (debug)
if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    w = DVDExtractorView()
    w.set_root_path(os.path.expanduser("~"))
    w.show()
    sys.exit(app.exec_())
