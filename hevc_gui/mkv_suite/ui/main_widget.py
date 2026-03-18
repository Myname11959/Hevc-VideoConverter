#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
import mimetypes
import os
import subprocess
from typing import Optional, Dict, List, Tuple

from PyQt5.QtCore import Qt, QTimer, QUrl, QProcess
from PyQt5.QtGui import QDesktopServices
from PyQt5 import QtWidgets, QtCore, QtGui
from gi.repository import Gio, GLib
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem, QMenu,
    QTabWidget, QTableWidget, QTableWidgetItem,
    QLabel, QLineEdit, QPushButton, QToolButton, QProgressBar,
    QFileDialog, QTextEdit, QGroupBox, QFormLayout, QSplitter,
    QMessageBox,
    QCheckBox,
    QSpinBox,


)
from hevc_gui.mkv_suite.ui.input_drop_frame import InputDropFrame
from hevc_gui.mkv_suite.ui.insert_clips_dialog import InsertClipsDialog
from PyQt5.QtWidgets import QAction  # type: ignore

from hevc_gui.mkv_suite.i18n import L
try:
    from hevc_gui.mkv_suite.i18n import L
except Exception:
    def L(s: str) -> str:
        return s

from hevc_gui.mkv_suite.core.toolchain import detect_toolchain, run_cmd
from hevc_gui.mkv_suite.core.probe import probe_mkv
from hevc_gui.mkv_suite.core.ops import apply_tags_in_place


from hevc_gui.mkv_suite.core.gnome_subtitles_editor import GnomeSubtitlesEditor
from hevc_gui.mkv_suite.ui.concat_batch_tab import ConcatBatchTab

AUDIO_EXT = {".aac", ".ac3", ".eac3", ".dts", ".flac", ".mp3", ".m4a", ".wav", ".ogg", ".opus", ".truehd", ".mka"}
SUB_EXT = {".srt", ".ass", ".ssa", ".vtt", ".sup", ".idx", ".sub"}  # idx/sub vobsub
VIDEO_EXT = {".mkv", ".mp4", ".m4v", ".mov", ".avi", ".ts", ".m2ts"}


@dataclass


class EditableName:
    name_user: str = ""
    name_auto: str = ""

    @property
    def effective(self) -> str:
        s = (self.name_user or "").strip()
        return s if s else (self.name_auto or "").strip()


@dataclass
class RemuxEntry:
    src: Path
    src_label: str
    kind: str          # video/audio/subtitles/other
    tid: int           # mkv track id, or 0 for external single-file
    is_mkv: bool
    include: bool = True
    lang: str = "und"
    name: str = ""
    default: bool = False
    forced: bool = False
    codec_id: str = ""


class MainWidget(QWidget):
    COL_INC = 0
    COL_SRC = 1
    COL_KIND = 2
    COL_ID = 3
    COL_LANG = 4
    COL_NAME = 5
    COL_DEF = 6
    COL_FOR = 7

    _RX_PROGRESS = re.compile(r"(?:Progresso|Progress)\s*:\s*(\d+)\s*%")

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._tc = detect_toolchain()
        self._busy = False
        self._ui_lock = False
        self._actions: Dict[str, QAction] = {}

        self._entries: List[RemuxEntry] = []
        self._sources: List[Path] = []
        self._chapters_override: Optional[Path] = None

        self._title = EditableName()
        self._year = EditableName()
        self._out_base = EditableName()
        self._out_dir = None  # output non impostata
        self._job_dir: Optional[Path] = None

        self._dlg_guard = False

        self._preview_open_path = None  # preview mkv da aprire a fine job
        self._tracks_last_clicked_row = -1
        self._subtitle_sync_manual_ms = {}
        self._subtitle_drift_points = {}

        self._preview_open_path = None  # preview mkv da aprire a fine job

        self._last_in_dir = None  # ultima cartella input (runtime)

        # QProcess queue
        self._proc: Optional[QProcess] = None
        self._proc_buf: str = ""
        self._queue: List[Tuple[List[str], str, bool]] = []   # (cmd, label, allow_fail)
        self._queue_done_msg: str = ""
        self._cur_allow_fail: bool = False
        self._autosync_anim_timer: Optional[QTimer] = None
        self._autosync_anim_value: int = 0

        self._analyze_proc: Optional[QProcess] = None
        self._analyze_queue: List[Path] = []
        self._analyze_current_src: Optional[Path] = None

        self._build_ui()

        self._bind_doubleclick_player()
        self._wire_signals()
        self._bind_temp_cleanup_buttons()

        self._log_tools()
        self._update_previews()
        self._update_enabled()

    # ---------- binding actions ----------
    def bind_actions(self, actions: Dict[str, QAction]) -> None:
        self._actions = dict(actions or {})

        def hook(key: str, fn):
            a = self._actions.get(key)
            if isinstance(a, QAction):
                try:
                    a.triggered.connect(fn, type=Qt.UniqueConnection)
                except Exception:
                    try:
                        a.triggered.connect(fn)
                    except Exception:
                        pass

        hook("add", self.on_add_files)
        hook("remove", self.on_remove_selected)
        hook("outdir", self.on_choose_outdir)
        hook("open_outdir", self.open_output_folder)
        hook("tag", self.apply_tags)
        hook("extract", self.extract_selected)
        hook("cut", self.open_cut_tool)
        hook("insert_clip", self.open_insert_clips_tool)
        hook("remux", self.remux_selected)
        hook("stop", self.stop_jobs)
        hook("reset", self.reset_all)
        hook("exit", self.exit_app)

        self._update_enabled()

    def _sync_bound_action_states(self) -> None:
        try:
            actions = getattr(self, "_actions", {}) or {}
            pairs = {
                "add": self.btn_add_files,
                "remove": self.btn_remove_files,
                "outdir": self.btn_choose_outdir,
                "open_outdir": self.btn_open_outdir,
                "tag": self.btn_apply_tags,
                "extract": self.btn_extract,
                "cut": self.btn_cut,
                "insert_clip": self.btn_insert_clip,
                "remux": self.btn_remux,
                "stop": self.btn_stop,
                "reset": self.btn_reset,
                "exit": self.btn_exit,
            }
            for key, btn in pairs.items():
                act = actions.get(key)
                if isinstance(act, QAction):
                    act.setEnabled(bool(btn.isEnabled()))
        except Exception:
            pass

    # ---------- UI ----------
    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        splitter = QSplitter(Qt.Horizontal, self)

        # LEFT
        left = QWidget()
        lyt_left = QVBoxLayout(left)
        lyt_left.setContentsMargins(0, 0, 0, 0)
        lyt_left.setSpacing(6)

        lyt_left.addWidget(QLabel(L("Sorgenti (Crea MKV) / File (Estrai)")))

        self.input_drop = InputDropFrame()
        lyt_drop = QVBoxLayout(self.input_drop)
        lyt_drop.setContentsMargins(0, 0, 0, 0)
        lyt_drop.setSpacing(0)

        self.list_files = QListWidget()
        self.list_files.setSelectionMode(QListWidget.ExtendedSelection)
        self.list_files.setContextMenuPolicy(Qt.CustomContextMenu)
        lyt_drop.addWidget(self.list_files)

        lyt_left.addWidget(self.input_drop, 1)

        self.btn_add_files = QPushButton(L("Aggiungi file…"))
        self.btn_remove_files = QPushButton(L("Rimuovi selezionati"))
        lyt_left.addWidget(self.btn_add_files)
        lyt_left.addWidget(self.btn_remove_files)

        # CENTER
        center = QWidget()
        lyt_center = QVBoxLayout(center)
        lyt_center.setContentsMargins(0, 0, 0, 0)
        lyt_center.setSpacing(8)

        self.tabs = QTabWidget()

        self.tbl_tracks = QTableWidget(0, 8)
        self.tbl_tracks.setHorizontalHeaderLabels([
            L("Includi"), L("Sorgente"), L("Tipo"), L("ID"),
            L("Lingua"), L("Nome traccia"), L("Default"), L("Forced")
        ])
        self.tbl_tracks.horizontalHeader().setStretchLastSection(True)
        self.tbl_tracks.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.tbl_tracks.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        # --- Tracks page wrapper: tab Tracce = tabella + riga Delay ---
        self.page_tracks = QtWidgets.QWidget()
        lay_tracks = QtWidgets.QVBoxLayout(self.page_tracks)
        lay_tracks.setContentsMargins(0, 0, 0, 0)
        lay_tracks.addWidget(self.tbl_tracks)
        
        self.w_autosync = QtWidgets.QWidget()
        lay_as = QtWidgets.QHBoxLayout(self.w_autosync)
        lay_as.setContentsMargins(0, 0, 0, 0)
        self.chk_autosync = QtWidgets.QCheckBox(L('Auto-sync audio'))
        self.lbl_delay = QtWidgets.QLabel(L('Delay:'))
        self.spn_delay = QtWidgets.QSpinBox()
        self.spn_delay.setRange(-5000, 5000)
        self.spn_delay.setSingleStep(1)
        self.spn_delay.setValue(0)
        self.spn_delay.setSuffix(' ms')
        self.btn_delay_info = QtWidgets.QToolButton()
        self.btn_delay_info.setText('')
        self.btn_delay_info.setAutoRaise(False)
        self.btn_delay_info.setToolTip(L('Informazioni sul delay manuale'))
        self.btn_delay_info.setFixedSize(24, 24)
        try:
            self.btn_delay_info.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_MessageBoxInformation))
            self.btn_delay_info.setIconSize(QtCore.QSize(16, 16))
        except Exception:
            self.btn_delay_info.setText('i')
        self.btn_delay_info.setStyleSheet('QToolButton { border: 1px solid #7f7f7f; border-radius: 4px; padding: 0px; } QToolButton:hover { background: rgba(127,127,127,0.12); }')

        self.btn_autosync_run = QtWidgets.QPushButton(L('Analizza'))
        self.btn_autosync_run.setToolTip(L('Ricalcola i delay automatici per le tracce audio incluse'))
        self.btn_autosync_run.setMaximumWidth(90)
        self.btn_preview = QtWidgets.QPushButton(L('Preview'))
        self.btn_preview.setToolTip(L('Crea un MKV temporaneo (video + audio selezionata) e lo apre in VLC'))
        self.btn_preview.setMaximumWidth(90)
        self.btn_sub_drift = QtWidgets.QPushButton(L('Drift…'))
        self.btn_sub_drift.setToolTip(L('Imposta 3 punti di drift per il subtitle selezionato'))
        self.btn_sub_drift.setMaximumWidth(90)
        self.chk_autosync.setToolTip(L('Auto-sync ON: mostra i delay calcolati per traccia.\nAuto-sync OFF: inserisci tu il delay per la traccia selezionata.'))
        self.spn_delay.setToolTip(L('Delay della traccia audio selezionata.\nNegativo = anticipa audio, positivo = ritarda audio.\n0 = nessuno shift.'))
        self.w_delay_nudge = QtWidgets.QWidget()
        lay_dn = QtWidgets.QHBoxLayout(self.w_delay_nudge)
        lay_dn.setContentsMargins(0, 0, 0, 0)
        lay_dn.setSpacing(4)
        self._delay_nudge_buttons = []

        for _delta in (-1000, -500, -250, -100, -50, 50, 100, 250, 500, 1000):
            _b = QtWidgets.QToolButton()
            _b.setText(f"{_delta:+d}")
            _b.setProperty("delay_delta", int(_delta))
            _b.setToolTip(L("Applica {ms} ms alla traccia audio selezionata").format(ms=f"{_delta:+d}"))
            _b.setMinimumWidth(46)
            lay_dn.addWidget(_b)
            self._delay_nudge_buttons.append(_b)

        self.btn_delay_reset = QtWidgets.QToolButton()
        self.btn_delay_reset.setText(L("Reset"))
        self.btn_delay_reset.setToolTip(L("Reimposta a 0 ms il delay della traccia audio selezionata"))
        self.btn_delay_reset.setMinimumWidth(58)
        lay_dn.addWidget(self.btn_delay_reset)
        lay_dn.addStretch(1)
        lay_as.addWidget(self.chk_autosync)
        lay_as.addSpacing(12)
        lay_as.addWidget(self.lbl_delay)
        lay_as.addWidget(self.spn_delay)
        lay_as.addWidget(self.btn_delay_info)
        lay_as.addSpacing(8)
        lay_as.addWidget(self.btn_autosync_run)
        lay_as.addSpacing(6)
        lay_as.addWidget(self.btn_preview)
        lay_as.addSpacing(6)
        lay_as.addWidget(self.btn_sub_drift)
        lay_as.addStretch(1)
        lay_tracks.addWidget(self.w_autosync)
        lay_tracks.addWidget(self.w_delay_nudge)
        # --- end wrapper ---
        

        self.tabs.addTab(self.page_tracks, L("Tracce"))

        # Sync audio per-traccia: base stabile (manuale sempre disponibile)
        self._audio_sync_manual_ms = {}
        self._audio_sync_auto_ms = {}
        self._audio_sync_auto_done_sources = set()
        self._autosync_running = False
        self._table_entries = []
        self._delay_ui_guard = False
        self._auto_sync_backend_warned = False

        self.chk_autosync.setChecked(False)
        self.tbl_tracks.itemSelectionChanged.connect(self._on_tracks_selection_changed)
        self.chk_autosync.toggled.connect(self._on_autosync_toggled)
        self.spn_delay.valueChanged.connect(self._on_delay_value_changed)
        self.btn_delay_info.clicked.connect(self._show_delay_info)
        for _b in getattr(self, '_delay_nudge_buttons', []):
            _b.clicked.connect(self._on_delay_nudge_clicked)
        self.btn_delay_reset.clicked.connect(self._on_delay_reset_clicked)
        self.btn_autosync_run.clicked.connect(self._run_autosync_now)
        self.btn_preview.clicked.connect(self._run_preview_now)
        self.btn_sub_drift.clicked.connect(self._on_subtitle_drift_clicked)
        if self.chk_autosync.isChecked():
            self._ensure_auto_sync_for_included_sources()
        self._refresh_delay_ui()

        # CHAPTERS tab: riga lunga
        tab_ch = QWidget()
        ch_lyt = QVBoxLayout(tab_ch)
        ch_lyt.setContentsMargins(6, 6, 6, 6)
        ch_lyt.setSpacing(6)
        self.lbl_chapters_status = QLabel(L("Capitoli nel video: nessun MKV selezionato."))
        self.lbl_chapters_status.setWordWrap(True)
        self.lbl_chapters_status.setStyleSheet(
            "padding: 6px 8px; border: 1px solid #bfc7d5; border-radius: 6px; "
            "background: rgba(127,127,127,0.08);"
        )
        ch_lyt.addWidget(self.lbl_chapters_status)

        self.lbl_chapters_file = QLabel(L("File capitoli esterno (opzionale: .xml / .txt)"))
        self.lbl_chapters_file.setStyleSheet("font-weight: 600;")
        ch_lyt.addWidget(self.lbl_chapters_file)

        row = QWidget()
        row_lyt = QHBoxLayout(row)
        row_lyt.setContentsMargins(0, 0, 0, 0)
        row_lyt.setSpacing(6)

        self.ed_chapters = QLineEdit()
        self.ed_chapters.setReadOnly(True)
        self.ed_chapters.setPlaceholderText(L("Nessun file capitoli esterno selezionato"))

        btn_pick = QToolButton()
        btn_pick.setText(L("…"))
        btn_pick.clicked.connect(self.pick_chapters_file)

        btn_gen_chapters = QToolButton()
        btn_gen_chapters.setText(L("Genera"))
        btn_gen_chapters.clicked.connect(self.generate_chapters)


        row_lyt.addWidget(self.ed_chapters, 1)
        row_lyt.addWidget(btn_pick)
        row_lyt.addWidget(btn_gen_chapters)
        ch_lyt.addWidget(row)

        self.tabs.addTab(tab_ch, L("Capitoli"))

        # CONCAT / batch-append tab (episodi in sequenza, senza ricodifica)
        try:
            self.tab_concat_batch = ConcatBatchTab(host=self, parent=self)
            self.tabs.addTab(self.tab_concat_batch, L("Unisci episodi"))
        except Exception as _e:
            try:
                self._log(f"[WARN] Tab Unisci episodi non disponibile: {_e}")
            except Exception:
                pass

        lyt_center.addWidget(self.tabs, 1)

        # Titolo e output (sotto)
        gb_meta = QGroupBox(L("Titolo e output"))
        form = QFormLayout(gb_meta)

        self.ed_title = QLineEdit()
        self.ed_year = QLineEdit()
        self.ed_year.setMaximumWidth(90)

        self.ed_title.textChanged.connect(self._on_title_changed)
        self.ed_year.textChanged.connect(self._on_year_changed)

        row_title = QWidget()
        row_title_lyt = QHBoxLayout(row_title)
        row_title_lyt.setContentsMargins(0, 0, 0, 0)
        row_title_lyt.setSpacing(6)
        row_title_lyt.addWidget(self.ed_title, 1)
        row_title_lyt.addWidget(QLabel(L("Anno")))
        row_title_lyt.addWidget(self.ed_year)
        form.addRow(L("Titolo"), row_title)

        self.lbl_preview_file = QLabel("-")
        self.lbl_preview_media = QLabel("-")
        self.lbl_preview_file.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_preview_media.setTextInteractionFlags(Qt.TextSelectableByMouse)

        form.addRow(L("Nome file"), self.lbl_preview_file)
        form.addRow(L("Titolo media"), self.lbl_preview_media)

        row_out = QWidget()
        row_out_lyt = QHBoxLayout(row_out)
        row_out_lyt.setContentsMargins(0, 0, 0, 0)
        row_out_lyt.setSpacing(6)

        self.ed_outdir = QLineEdit("")
        self.ed_outdir.setReadOnly(True)

        self.btn_choose_outdir = QToolButton()
        self.btn_choose_outdir.setText(L("…"))
        self.btn_choose_outdir.clicked.connect(self.on_choose_outdir)

        self.btn_open_outdir = QToolButton()
        self.btn_open_outdir.setText(L("Apri"))
        self.btn_open_outdir.clicked.connect(self.open_output_folder)

        row_out_lyt.addWidget(self.ed_outdir, 1)
        row_out_lyt.addWidget(self.btn_choose_outdir)
        row_out_lyt.addWidget(self.btn_open_outdir)
        form.addRow(L("Cartella output"), row_out)

        lyt_center.addWidget(gb_meta, 0)

        # RIGHT
        right = QWidget()
        lyt_right = QVBoxLayout(right)
        lyt_right.setContentsMargins(0, 0, 0, 0)
        lyt_right.setSpacing(8)

        gb_ops = QGroupBox(L("Operazioni"))
        ops = QVBoxLayout(gb_ops)

        self.btn_apply_tags = QPushButton(L("Applica Tag"))
        self.btn_extract = QPushButton(L("Estrai"))
        self.btn_cut = QPushButton(L("Taglio…"))
        self.btn_cut.setToolTip(L("Taglio"))
        try:
            self.btn_cut.setStatusTip(L("Taglio"))
        except Exception:
            pass
        self.btn_insert_clip = QPushButton(L("Inserisci clip…"))
        self.btn_insert_clip.setToolTip(L("Inserisci una o più clip nel file selezionato."))
        try:
            self.btn_insert_clip.setStatusTip(L("Inserisci una o più clip nel file selezionato."))
        except Exception:
            pass
        self.btn_remux = QPushButton(L("Crea MKV"))
        self.btn_stop = QPushButton(L("Stop"))
        self.btn_reset = QPushButton(L("Annulla"))
        self.btn_exit = QPushButton(L("Esci"))

        self.btn_apply_tags.clicked.connect(self.apply_tags)
        self.btn_extract.clicked.connect(self.extract_selected)
        self.btn_cut.clicked.connect(self.open_cut_tool)
        self.btn_insert_clip.clicked.connect(self.open_insert_clips_tool)
        self.btn_remux.clicked.connect(self.remux_selected)
        self.btn_stop.clicked.connect(self.stop_jobs)
        self.btn_reset.clicked.connect(self.reset_all)
        self.btn_exit.clicked.connect(self.exit_app)

        ops.addWidget(self.btn_apply_tags)
        ops.addWidget(self.btn_extract)
        ops.addWidget(self.btn_remux)
        ops.addWidget(self.btn_stop)
        ops.addWidget(self.btn_reset)
        ops.addWidget(self.btn_exit)

        lyt_right.addWidget(gb_ops)

        # Progressbar reale, sempre visibile, 18px, % al centro
        self.progress = QProgressBar()
        # PROGRESSBAR_ZERO_CHUNK_INIT
        self.progress.setProperty('zero', True)
        self.progress.setStyleSheet(
            "QProgressBar { text-align: center; }\n"
            "QProgressBar::chunk { background-color: palette(highlight); }\n"
            "QProgressBar[zero=\"true\"]::chunk { background-color: transparent; width: 0px; }\n"
        )
        self.progress.setFixedHeight(18)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        # PROGRESSBAR_ZERO_CHUNK_SET
        try:
            self.progress.setProperty('zero', (self.progress.value() <= 0))
            self.progress.style().unpolish(self.progress)
            self.progress.style().polish(self.progress)
            self.progress.update()
        except Exception:
            pass
        self.progress.setTextVisible(True)
        self.progress.setAlignment(Qt.AlignCenter)
        self.progress.setFormat("%p%")
        lyt_right.addWidget(self.progress)

        gb_log = QGroupBox(L("Log"))
        lyt_log = QVBoxLayout(gb_log)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        lyt_log.addWidget(self.log, 1)
        lyt_right.addWidget(gb_log, 1)

        splitter.addWidget(left)
        splitter.addWidget(center)
        splitter.addWidget(right)
        splitter.setSizes([320, 860, 360])
        root.addWidget(splitter, 1)

    def _bind_doubleclick_player(self) -> None:
        try:
            self.list_files.itemDoubleClicked.disconnect(self._open_selected_in_vlc)
        except Exception:
            pass
        try:
            self.list_files.itemDoubleClicked.connect(self._open_selected_in_vlc)
        except Exception:
            pass

    def _open_selected_in_vlc(self, item=None) -> None:
        try:
            it = item if item is not None else self.list_files.currentItem()
            if it is None:
                return

            p = Path(it.text())
            if not p.exists():
                try:
                    self._log(f"[WARN] File non trovato: {p}")
                except Exception:
                    pass
                return

            import shutil as _shutil
            vlc = _shutil.which("vlc")
            if vlc:
                try:
                    if QProcess.startDetached(vlc, [str(p)]):
                        return
                except Exception:
                    pass

            try:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))
            except Exception as e:
                try:
                    self._log(f"[WARN] Apri file: {e}")
                except Exception:
                    pass
        except Exception as e:
            try:
                self._log(f"[WARN] Apri in VLC: {e}")
            except Exception:
                pass


    def _wire_signals(self) -> None:
        self.btn_add_files.clicked.connect(self.on_add_files)
        self.input_drop.filesDropped.connect(self._add_files_to_list)
        self.list_files.customContextMenuRequested.connect(self._show_input_context_menu)
        self.btn_remove_files.clicked.connect(self.on_remove_selected)
        self.list_files.itemSelectionChanged.connect(self._update_enabled)
        self.tbl_tracks.cellClicked.connect(self._on_tracks_cell_clicked_toggle)
        self.tbl_tracks.itemChanged.connect(self._on_track_item_changed)
        self.tbl_tracks.cellDoubleClicked.connect(self._mkv_suite_on_tracks_cell_double_clicked)


        try:
            self._apply_all_tooltips()
        except Exception:
            pass
    # ---------- basic helpers ----------
    def _log(self, msg: str) -> None:
        self.log.append(msg)

    def _set_busy(self, v: bool) -> None:
        self._busy = bool(v)
        self._update_enabled()

    def _log_tools(self) -> None:
        miss = self._tc.missing()
        if miss:
            self._log(f"[WARN] Tool mancanti: {', '.join(miss)}")
        else:
            self._log("[OK] Toolchain MKVToolNix trovata (mkvmerge/mkvextract/mkvpropedit)")

    def _update_enabled(self) -> None:
        try:
            self._chap_refresh_embedded_info()
        except Exception:
            pass

        has_any = self.list_files.count() > 0
        has_sel = len(self.list_files.selectedIndexes()) > 0

        try:
            _out = getattr(self, "_out_dir", None)
            has_outdir = bool(_out) and Path(_out).expanduser().exists()
        except Exception:
            has_outdir = bool(getattr(self, "_out_dir", None))

        self.btn_add_files.setEnabled(not self._busy)
        self.btn_remove_files.setEnabled(has_any and has_sel and (not self._busy))

        # configurazione sessione
        self.btn_choose_outdir.setEnabled(not self._busy)
        self.btn_open_outdir.setEnabled(has_outdir)

        # azioni sui file: richiedono almeno un input
        self.btn_apply_tags.setEnabled(has_any and (not self._busy))
        self.btn_extract.setEnabled(has_any and (not self._busy))
        self.btn_cut.setEnabled(not self._busy)
        self.btn_insert_clip.setEnabled(not self._busy)
        self.btn_remux.setEnabled(has_any and (not self._busy))

        self.btn_stop.setEnabled(self._busy)
        self.btn_reset.setEnabled(not self._busy)
        self.btn_exit.setEnabled(True)

        self._sync_bound_action_states()

    def _effective_title(self) -> str:
        title = (self._title.effective or "").strip()
        year = (self._year.effective or "").strip()
        if title and year:
            return f"{title} ({year})"
        return title or ""

    # ---------- naming helpers ----------

    # ---------- Job folder helpers ----------
    def _safe_job_name(self, s: str) -> str:
        s = (s or "").strip()
        s = s.replace("/", "_").replace("\\", "_").replace(":", "_")
        s = re.sub(r"\s+", " ", s).strip()
        # tienilo leggibile ma sicuro
        s = re.sub(r"[^0-9A-Za-zÀ-ÿ ._\-\(\)]+", "", s).strip()
        s = s.strip(" ._-")
        return s or "job"

    def _job_hint(self) -> str:
        # 1) titolo/anno se disponibili
        try:
            t = (self._effective_title() or "").strip()
        except Exception:
            t = ""
        if t:
            return t

        # 2) mkv selezionato o primo mkv in lista
        try:
            it = self.list_files.currentItem()
            if it:
                p = Path(it.text())
                if p.exists():
                    return p.stem
        except Exception:
            pass
        try:
            for i in range(self.list_files.count()):
                p = Path(self.list_files.item(i).text())
                if p.exists():
                    return p.stem
        except Exception:
            pass

        return "job"

    def _norm_lang(self, s: str) -> str:
        x = (s or "").strip().lower()
        if x in ("it", "ita", "italian", "italiano"): return "ita"
        if x in ("en", "eng", "english", "inglese"): return "eng"
        if x in ("de", "deu", "ger", "german", "tedesco"): return "deu"
        if x in ("fr", "fra", "fre", "french", "francese"): return "fra"
        if x in ("es", "spa", "spanish", "spagnolo"): return "spa"
        if not x: return "und"
        return x

    def _lang_label(self, code: str) -> str:
        c = self._norm_lang(code)
        return {
            "ita": "Italiano", "eng": "Inglese", "deu": "Tedesco",
            "fra": "Francese", "spa": "Spagnolo", "und": "Sconosciuta"
        }.get(c, c)


    # ---------- VLC track naming (compatto) ----------
    def _vlc_track_name(self, tid: int, entry, src: "Path") -> str:
        """
        Nome corto per VLC:
          Audio:  T{N} <Lingua> Audio
          Subs :  T{N} <Lingua> Sub (forced|normal)
        Se l'utente ha scritto un nome "manuale" (pulito), ha priorità.
        """
        # manuale ha priorità se sembra davvero manuale (non filename tecnico)
        manual = (getattr(entry, "name", "") or "").strip()
        if manual and ("_T" not in manual) and (not manual.endswith("_e")) and ("." not in manual):
            return manual

        # numero traccia: prova a leggerlo dal filename (per esterni), altrimenti tid
        tnum = 0
        try:
            m = re.search(r"_T(\d+)_", src.stem)
            if m:
                tnum = int(m.group(1))
            else:
                tnum = int(tid)
        except Exception:
            try:
                tnum = int(tid)
            except Exception:
                tnum = 0

        # lingua “umana”
        try:
            langlab = self._lang_label(getattr(entry, "lang", "und"))
        except Exception:
            langlab = (getattr(entry, "lang", "und") or "und")

        kind = (getattr(entry, "kind", "") or "").lower()
        forced = bool(getattr(entry, "forced", False))

        if kind == "audio":
            return f"T{tnum} {langlab} Audio"
        if kind == "subtitles":
            return f"T{tnum} {langlab} Sub ({'forced' if forced else 'normal'})"

        # fallback: se non è audio/sub, lascia il manuale se c'è
        return manual

    def _guess_lang_from_path(self, path: Path) -> str:
        tokens = re.split(r"[^a-zA-Z0-9]+", path.stem.lower())
        for t in tokens:
            if t in ("ita", "it", "italiano", "italian"): return "ita"
            if t in ("eng", "en", "inglese", "english"): return "eng"
            if t in ("deu", "de", "ger", "tedesco", "german"): return "deu"
            if t in ("fra", "fr", "fre", "francese", "french"): return "fra"
            if t in ("spa", "es", "spagnolo", "spanish"): return "spa"
        return "und"

    def _guess_forced(self, path: Path) -> bool:
        s = path.stem.lower()
        return ("forced" in s) or ("forz" in s)

    def _safe_slug(self, s: str, maxlen: int = 90) -> str:
        s = (s or "").strip().replace("/", "_").replace("\\", "_")
        s = re.sub(r"\s+", " ", s).strip()
        s = re.sub(r"[^0-9A-Za-z._ -]+", "", s).strip(" ._-")
        if not s:
            s = "track"
        return s[:maxlen]

    def _ext_for(self, codec_id: str, kind: str) -> str:
        cid = (codec_id or "").upper().strip()
        k = (kind or "").lower().strip()
        # audio
        if cid.startswith("A_AAC"): return "aac"
        if cid == "A_AC3": return "ac3"
        if cid == "A_EAC3": return "eac3"
        if cid == "A_DTS": return "dts"
        if cid == "A_FLAC": return "flac"
        if cid == "A_OPUS": return "opus"
        if cid.startswith("A_MPEG/L3"): return "mp3"
        if cid.startswith("A_MPEG/L2"): return "mp2"
        if cid.startswith("A_VORBIS"): return "ogg"
        if cid.startswith("A_TRUEHD") or cid.startswith("A_MLP"): return "truehd"
        # subs
        if cid.startswith("S_TEXT/UTF8"): return "srt"
        if cid.startswith("S_TEXT/ASS"): return "ass"
        if cid.startswith("S_TEXT/SSA"): return "ssa"
        if cid.startswith("S_TEXT/WEBVTT"): return "vtt"
        if cid.startswith("S_HDMV/PGS"): return "sup"
        if cid.startswith("S_VOBSUB"): return "idx"
        # fallback
        if k == "audio": return "audio"
        if k == "subtitles": return "sub"
        return "bin"

    def _default_track_name(self, src: Path, kind: str, lang: str, forced: bool, original_name: str) -> str:
        # Audio: default = nome originale se c'è, altrimenti nome file
        if (kind or "").lower() == "audio":
            if (original_name or "").strip():
                return original_name.strip()
            base = src.stem.replace("_", " ")
            return re.sub(r"\s+", " ", base).strip()

        # Subs: include forced/normal
        if (kind or "").lower() == "subtitles":
            if (original_name or "").strip():
                n = original_name.strip()
            else:
                n = re.sub(r"\s+", " ", src.stem.replace("_", " ")).strip()
            tag = "forced" if forced else "normal"
            if tag not in n.lower():
                n = f"{n} ({tag})"
            return n

        # video/other
        return (original_name or src.stem).strip()

    # ---------- title/year hint from selected video track ----------
    def _on_title_changed(self, s: str) -> None:
        if self._ui_lock:
            return
        self._title.name_user = s
        self._update_previews()

    def _on_year_changed(self, s: str) -> None:
        if self._ui_lock:
            return
        self._year.name_user = s
        self._update_previews()

    def _update_previews(self) -> None:
        base = self._effective_title().strip()
        self._out_base.name_auto = base
        out_base = self._out_base.effective or "-"
        self.lbl_preview_media.setText(out_base)
        self.lbl_preview_file.setText(out_base + ".mkv")

    def _auto_title_from_video(self) -> None:
        v = next((e for e in self._entries if e.include and (e.kind or "").lower() == "video"), None)
        if not v:
            return
        guess = (v.name or "").strip() or v.src.stem
        year = ""
        m = re.search(r"(19\d{2}|20\d{2})", guess)
        if m:
            year = m.group(1)

        title = guess.replace("_", " ").replace(".", " ")
        title = re.sub(r"\s+", " ", title).strip()
        if year:
            title = re.sub(r"[\(\[\{]?\s*" + re.escape(year) + r"\s*[\)\]\}]?", "", title).strip()
            title = re.sub(r"\s+", " ", title).strip()

        self._ui_lock = True
        try:
            if not (self._title.name_user or "").strip():
                self._title.name_auto = title
                self.ed_title.setText(title)
            if year and not (self._year.name_user or "").strip():
                self._year.name_auto = year
                self.ed_year.setText(year)
        finally:
            self._ui_lock = False
        self._update_previews()

    # ---------- chapters ----------
    def pick_chapters_file(self) -> None:
        start_dir = self._get_last_input_dir()
        filt = L("Tutti i file (*.*);;Capitoli (*.xml *.txt)")
        fn, _ = QFileDialog.getOpenFileName(self, L("Seleziona capitoli"), start_dir, filt)
        if not fn:
            return

        # ricorda cartella input (runtime)
        self._remember_last_input_dir(fn)

        self._chapters_override = Path(fn)
        self.ed_chapters.setText(str(self._chapters_override))

    def _chap_pick_video(self) -> Path | None:
        # MKV corrente se possibile, altrimenti primo MKV in lista
        try:
            it = self.list_files.currentItem()
            if it:
                fp = Path(it.text())
                if fp.exists() and fp.suffix.lower() == ".mkv":
                    return fp
        except Exception:
            pass
        try:
            for i in range(self.list_files.count()):
                fp = Path(self.list_files.item(i).text())
                if fp.exists() and fp.suffix.lower() == ".mkv":
                    return fp
        except Exception:
            pass
        return None

    def _chap_ffprobe_duration(self, video: Path) -> float:
        import subprocess
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
            text=True
        ).strip()
        return float(out or "0")

    def _chap_embedded_count(self, video: Path) -> int:
        import subprocess
        try:
            out = subprocess.check_output(
                ["ffprobe", "-v", "error", "-show_chapters", str(video)],
                text=True
            )
            # ffprobe stampa sezioni [CHAPTER]...[/CHAPTER]
            return out.count("[CHAPTER]")
        except Exception:
            return 0

    def _chap_has_embedded(self, video: Path) -> bool:
        return self._chap_embedded_count(video) > 0

    def _chap_refresh_embedded_info(self) -> None:
        lbl = getattr(self, "lbl_chapters_status", None)
        if lbl is None:
            # fallback compatibilità con versioni vecchie (senza label stato separata)
            lbl = getattr(self, "lbl_chapters_file", None)
        if lbl is None:
            return

        style_neutral = (
            "padding: 6px 8px; border: 1px solid #bfc7d5; border-radius: 6px; "
            "background: rgba(127,127,127,0.08);"
        )
        style_ok = (
            "padding: 6px 8px; border: 1px solid #9fd3a8; border-radius: 6px; "
            "background: rgba(70,160,90,0.12);"
        )
        style_warn = (
            "padding: 6px 8px; border: 1px solid #e2c28a; border-radius: 6px; "
            "background: rgba(220,170,60,0.14);"
        )

        try:
            video = self._chap_pick_video()
        except Exception:
            video = None

        if not video:
            lbl.setText(L("Capitoli nel video: nessun MKV selezionato."))
            try:
                lbl.setStyleSheet(style_neutral)
            except Exception:
                pass
            return

        try:
            n = int(self._chap_embedded_count(video) or 0)
        except Exception:
            n = 0

        if n <= 0:
            lbl.setText(
                L("Capitoli nel video: assenti. Puoi usare un file capitoli esterno (.xml/.txt) oppure generarli.")
            )
            try:
                lbl.setStyleSheet(style_warn)
            except Exception:
                pass
            return

        if n == 1:
            lbl.setText(L("Capitoli nel video: presenti (1 capitolo)."))
        else:
            lbl.setText(L("Capitoli nel video: presenti ({n} capitoli).").format(n=n))

        try:
            lbl.setStyleSheet(style_ok)
        except Exception:
            pass

    def _chap_fmt_ts(self, sec: float) -> str:
        if sec < 0:
            sec = 0.0
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = sec % 60
        return f"{h:02d}:{m:02d}:{s:06.3f}"

    def _chap_write_ogm(self, timestamps: list[float], out_path: Path, prefix: str = "Chapter") -> None:
        # Simple/OGM chapter format (compatibile mkvmerge --chapters)
        ts = sorted(set(float(x) for x in timestamps if x >= 0))
        if not ts or ts[0] != 0.0:
            ts = [0.0] + ts
        n = len(ts)
        width = max(2, len(str(n)))
        lines = []
        for i, t in enumerate(ts, 1):
            idx = str(i).zfill(width)
            lines.append(f"CHAPTER{idx}={self._chap_fmt_ts(t)}")
            lines.append(f"CHAPTER{idx}NAME={prefix} {i:02d}")
        out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _chap_filter(self, ts: list[float], min_dur: int = 180, max_dur: int = 300) -> list[float]:
        # stessa logica “umana” di HEVC: evita capitoli troppo ravvicinati, inserisce intermedi se troppo lunghi
        if not ts:
            return [0.0]
        ts = sorted(set(float(x) for x in ts if x >= 0))
        out = [0.0]
        for x in ts:
            if x - out[-1] < min_dur:
                continue
            if x - out[-1] <= max_dur:
                out.append(x)
            else:
                t = out[-1] + max_dur
                while t < x:
                    out.append(t)
                    t += max_dur
        return out

    def generate_chapters(self) -> None:
        from PyQt5.QtWidgets import QInputDialog, QMessageBox
        if getattr(self, "_busy", False):
            return

        video = self._chap_pick_video()
        if not video:
            QMessageBox.information(self, L("Info"), L("Aggiungi o seleziona un MKV per generare i capitoli."))
            return

        # solo se non ci sono capitoli, altrimenti chiedi
        if self._chap_has_embedded(video):
            q = QMessageBox.question(
                self, L("Capitoli"),
                L("Il file contiene già capitoli.\nVuoi generarli comunque?"),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if q != QMessageBox.Yes:
                return

        # scegli dove salvare (così poi Rimuxa li usa subito)
        try:
            chooser = getattr(self, "on_choose_outdir", None)
            if callable(chooser):
                if not chooser():
                    self._log("[INFO] Genera capitoli annullato: cartella output non scelta.")
                    return
        except Exception:
            pass

        mode, ok = QInputDialog.getItem(
            self, L("Genera capitoli"),
            L("Metodo:"),
            [L("Scene (auto)"), L("Intervallo fisso (minuti)")],
            0, False
        )
        if not ok:
            return

        base = (getattr(self, "_effective_title", lambda: "")() or "").strip() or video.stem
        job = self._job_dir or self._out_dir
        chap_dir = job / "chapters"
        chap_dir.mkdir(parents=True, exist_ok=True)
        out_path = chap_dir / f"{base}.chapters_ogm.txt"

        # reset progress
        try:
            self.progress.setValue(0)
            # PROGRESSBAR_ZERO_CHUNK_SET
            try:
                self.progress.setProperty('zero', (self.progress.value() <= 0))
                self.progress.style().unpolish(self.progress)
                self.progress.style().polish(self.progress)
                self.progress.update()
            except Exception:
                pass
        except Exception:
            pass

        if mode.startswith("Intervallo"):
            minutes, ok = QInputDialog.getInt(self, L("Intervallo fisso"), L("Ogni quanti minuti?"), 5, 1, 180, 1)
            if not ok:
                return
            dur = 0.0
            try:
                dur = self._chap_ffprobe_duration(video)
            except Exception:
                dur = 0.0
            step = float(minutes) * 60.0
            ts = [0.0]
            t = step
            # aggiorna progress "umana" durante loop
            while dur > 0 and t < dur:
                ts.append(t)
                t += step
                try:
                    self.progress.setValue(min(99, int((t / dur) * 100)))
                    # PROGRESSBAR_ZERO_CHUNK_SET
                    try:
                        self.progress.setProperty('zero', (self.progress.value() <= 0))
                        self.progress.style().unpolish(self.progress)
                        self.progress.style().polish(self.progress)
                        self.progress.update()
                    except Exception:
                        pass
                except Exception:
                    pass
            self._chap_write_ogm(ts, out_path)
            try:
                self.ed_chapters.setText(str(out_path))
                self._chapters_override = out_path
            except Exception:
                pass
            try:
                self.progress.setValue(100)
                # PROGRESSBAR_ZERO_CHUNK_SET
                try:
                    self.progress.setProperty('zero', (self.progress.value() <= 0))
                    self.progress.style().unpolish(self.progress)
                    self.progress.style().polish(self.progress)
                    self.progress.update()
                except Exception:
                    pass
            except Exception:
                pass
            self._log(f"[OK] Capitoli generati (intervallo): {out_path}")
            return

        # --- Scene detect con ffmpeg + progress reale ---
        thr, ok = QInputDialog.getDouble(self, L("Scene threshold"), L("Soglia (0.0–1.0):"), 0.4, 0.0, 1.0, 2)
        if not ok:
            return

        dur = 0.0
        try:
            dur = self._chap_ffprobe_duration(video)
        except Exception:
            dur = 0.0

        self._set_busy(True)
        self._chap_ts: list[float] = []
        self._chap_buf: str = ""
        self._chap_proc = QProcess(self)
        proc = self._chap_proc
        proc.setProcessChannelMode(QProcess.MergedChannels)

        rx_pts = re.compile(r"pts_time:([0-9.]+)")
        rx_out_ms = re.compile(r"out_time_ms=(\d+)")

        def _read():
            data = bytes(proc.readAllStandardOutput()).decode("utf-8", "replace")
            if not data:
                return
            data = data.replace("\r", "\n")
            self._chap_buf += data
            while "\n" in self._chap_buf:
                line, self._chap_buf = self._chap_buf.split("\n", 1)
                line = line.strip()
                if not line:
                    continue

                m = rx_pts.search(line)
                if m:
                    try:
                        self._chap_ts.append(float(m.group(1)))
                    except Exception:
                        pass

                m = rx_out_ms.search(line)
                if m and dur > 0:
                    try:
                        tsec = int(m.group(1)) / 1_000_000.0
                        pct = int(max(0.0, min(1.0, tsec / dur)) * 100)
                        self.progress.setValue(pct)
                        # PROGRESSBAR_ZERO_CHUNK_SET
                        try:
                            self.progress.setProperty('zero', (self.progress.value() <= 0))
                            self.progress.style().unpolish(self.progress)
                            self.progress.style().polish(self.progress)
                            self.progress.update()
                        except Exception:
                            pass
                    except Exception:
                        pass

        def _done(code, _status):
            try:
                _read()
            except Exception:
                pass

            if code != 0:
                self._log(f"[ERR] Generazione capitoli fallita (rc={code}).")
                try:
                    self.progress.setValue(0)
                    # PROGRESSBAR_ZERO_CHUNK_SET
                    try:
                        self.progress.setProperty('zero', (self.progress.value() <= 0))
                        self.progress.style().unpolish(self.progress)
                        self.progress.style().polish(self.progress)
                        self.progress.update()
                    except Exception:
                        pass
                except Exception:
                    pass
                self._set_busy(False)
                return

            ts = self._chap_filter(self._chap_ts, 180, 300)
            try:
                self._chap_write_ogm(ts, out_path)
                self.ed_chapters.setText(str(out_path))
                self._chapters_override = out_path
                self.progress.setValue(100)
                # PROGRESSBAR_ZERO_CHUNK_SET
                try:
                    self.progress.setProperty('zero', (self.progress.value() <= 0))
                    self.progress.style().unpolish(self.progress)
                    self.progress.style().polish(self.progress)
                    self.progress.update()
                except Exception:
                    pass
                self._log(f"[OK] Capitoli generati (scene): {out_path}")
            except Exception as e:
                self._log(f"[ERR] Scrittura capitoli: {e}")
                try:
                    self.progress.setValue(0)
                    # PROGRESSBAR_ZERO_CHUNK_SET
                    try:
                        self.progress.setProperty('zero', (self.progress.value() <= 0))
                        self.progress.style().unpolish(self.progress)
                        self.progress.style().polish(self.progress)
                        self.progress.update()
                    except Exception:
                        pass
                except Exception:
                    pass
            finally:
                self._set_busy(False)

        proc.readyReadStandardOutput.connect(_read)
        proc.finished.connect(_done)

        vf = f"select='gt(scene,{thr})',showinfo"
        args = [
            "-y", "-hide_banner", "-nostdin",
            "-i", str(video),
            "-vf", vf,
            "-an", "-sn", "-f", "null", "-",
            "-progress", "pipe:1",
            "-nostats"
        ]
        self._log(f"[RUN] ffmpeg scene-detect (thr={thr})")
        proc.start("ffmpeg", args)
    def open_output_folder(self) -> None:
        # Se non è ancora impostata una cartella output, chiedila ora
        if getattr(self, "_out_dir", None) is None:
            if not self.on_choose_outdir():
                return
        try:
            d = getattr(self, "_job_dir", None) or self._out_dir
            Path(d).mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))
        except Exception as e:
            QMessageBox.warning(self, L("Errore"), L("Impossibile aprire la cartella output:") + "\n" + str(e))

    def on_choose_outdir(self) -> bool:
        d = QFileDialog.getExistingDirectory(self, L("Scegli cartella output"), str(self._out_dir) if self._out_dir else str(Path.home()))
        if not d:
            return False

        self._out_dir = Path(d)
        self._job_dir = self._out_dir  # ✅ job = output scelto (UNA sola directory)

        try:
            self.ed_outdir.setText(str(self._out_dir) if self._out_dir else "")
        except Exception:
            pass

        self._log(f"[UI] Output: {self._out_dir}")
        self._log(f"[OUT] Job dir: {self._job_dir}")
        return True


    # ---------- last input dir (runtime) ----------
    def _get_last_input_dir(self) -> str:
        try:
            d = getattr(self, "_last_in_dir", None)
            if d:
                pp = Path(d)
                if pp.is_dir():
                    return str(pp)
        except Exception:
            pass

        # fallback: cartella del file selezionato in lista
        try:
            it = self.list_files.currentItem()
            if it:
                pp = Path(it.text()).expanduser().resolve().parent
                if pp.is_dir():
                    return str(pp)
        except Exception:
            pass

        return str(Path.home())

    def _remember_last_input_dir(self, file_path: str) -> None:
        try:
            self._last_in_dir = Path(file_path).expanduser().resolve().parent
        except Exception:
            pass

    def _add_files_to_list(self, files) -> None:
        if not files:
            return

        # ricorda cartella input (runtime)
        self._remember_last_input_dir(files[0])

        # ⚠️ A prova di cretino: capitoli NON sono sorgenti (usa la scheda 'Capitoli')
        bad = []
        keep = []
        for fn in files:
            pp = Path(fn)
            suf = pp.suffix.lower()
            nm = pp.name.lower()
            is_ch = False

            # euristica nome+estensione
            if suf in (".xml", ".txt") and ("chap" in nm or "chapter" in nm or "chapters" in nm or "ogm" in nm):
                is_ch = True

            # euristica contenuto (OGM simple chapters / FFMETADATA)
            if (not is_ch) and suf in (".xml", ".txt"):
                try:
                    head = pp.read_text(encoding="utf-8", errors="ignore")[:4096].lower()
                    if "chapter01=" in head or "[chapter]" in head or "ffmetadata" in head:
                        is_ch = True
                except Exception:
                    pass

            if is_ch:
                bad.append(str(pp))
            else:
                keep.append(fn)

        if bad:
            QMessageBox.information(
                self,
                L("Capitoli"),
                L("Hai selezionato un file capitoli.\nSelezionalo dalla scheda 'Capitoli'.\n\nFile ignorati:")
                + "\n" + "\n".join(bad)
            )
            try:
                self._log("[INFO] Capitoli ignorati come sorgenti: " + "; ".join(Path(x).name for x in bad))
            except Exception:
                pass

        files = keep
        if not files:
            return

        existing = {self.list_files.item(i).text() for i in range(self.list_files.count())}
        added = 0
        for fn in files:
            ap = str(Path(fn).expanduser().resolve())
            if ap in existing:
                continue
            self.list_files.addItem(QListWidgetItem(ap))
            existing.add(ap)
            added += 1

        if added:
            self._log(f"[UI] Aggiunti {added} file (tot={self.list_files.count()})")

        self._rebuild_entries_from_sources()

    def on_add_files(self) -> None:
        if getattr(self, "_dlg_guard", False):
            return
        self._dlg_guard = True
        try:
            start_dir = self._get_last_input_dir()
            filt = L("Tutti i file (*.*);;Video (*.mkv *.mp4 *.m4v *.mov *.avi *.ts *.m2ts);;Audio (*.aac *.ac3 *.eac3 *.dts *.flac *.mp3 *.m4a *.wav *.ogg *.opus *.truehd *.mka);;Sottotitoli (*.srt *.ass *.ssa *.vtt *.sup *.idx *.sub);;Capitoli (*.xml *.txt)")
            files, _ = QFileDialog.getOpenFileNames(self, L("Aggiungi file"), start_dir, filt)
            if not files:
                return
            self._add_files_to_list(files)
        finally:
            QTimer.singleShot(0, lambda: setattr(self, "_dlg_guard", False))

    def _open_input_with_dialog(self, path_str: str) -> None:
        try:
            pp = Path(path_str).expanduser().resolve()
        except Exception as e:
            self._log(f"[WARN] Apri con fallito (path): {e}")
            return

        mime = ""
        try:
            mime = mimetypes.guess_type(str(pp), strict=False)[0] or ""
        except Exception:
            mime = ""

        if not mime:
            try:
                cp = subprocess.run(
                    ["xdg-mime", "query", "filetype", str(pp)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                mime = (cp.stdout or "").strip()
            except Exception as e:
                self._log(f"[WARN] Apri con fallito (xdg-mime): {e}")

        if not mime:
            QtWidgets.QMessageBox.warning(
                self,
                L("Apri con…"),
                L("Impossibile rilevare il tipo del file.")
            )
            return

        try:
            out = subprocess.check_output(
                ["gio", "mime", mime],
                stderr=subprocess.STDOUT,
                text=True,
            )
        except Exception as e:
            self._log(f"[WARN] Apri con fallito (gio mime): {e}")
            QtWidgets.QMessageBox.warning(
                self,
                L("Apri con…"),
                L("Impossibile leggere le applicazioni disponibili.")
            )
            return

        apps = []
        seen = set()
        for raw in out.splitlines():
            line = raw.strip()
            if not line or ".desktop" not in line:
                continue
            line = line.replace(",", " ")
            if ":" in line:
                line = line.split(":", 1)[1].strip()
            for tok in line.split():
                tok = tok.strip()
                if tok.endswith(".desktop") and tok not in seen:
                    seen.add(tok)
                    apps.append(tok)

        if not apps:
            QtWidgets.QMessageBox.information(
                self,
                L("Apri con…"),
                L("Nessuna applicazione disponibile trovata per questo file.")
            )
            return

        choice, ok = QtWidgets.QInputDialog.getItem(
            self,
            L("Apri con…"),
            L("Applicazione:"),
            apps,
            0,
            False,
        )
        if not ok or not choice:
            return

        try:
            subprocess.Popen(["gio", "launch", choice, str(pp)])
            self._log(f"[UI] Apri con: {choice} -> {pp}")
        except Exception as e:
            self._log(f"[WARN] Apri con fallito (gio launch): {e}")
            QtWidgets.QMessageBox.warning(
                self,
                L("Apri con…"),
                L("Avvio applicazione fallito.")
            )


    def _portal_open_with_dialog(self, path_str: str) -> None:
        try:
            target = Path(path_str).expanduser().resolve()
            if not target.exists():
                QtWidgets.QMessageBox.warning(
                    self,
                    L("Apri con…"),
                    L("File non trovato.")
                )
                return

            fd = os.open(str(target), os.O_RDONLY)
            try:
                conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
                fds = Gio.UnixFDList.new()
                idx = fds.append(fd)

                params = GLib.Variant(
                    "(sha{sv})",
                    (
                        "",
                        idx,
                        {
                            "ask": GLib.Variant("b", True),
                        },
                    ),
                )

                conn.call_with_unix_fd_list_sync(
                    "org.freedesktop.portal.Desktop",
                    "/org/freedesktop/portal/desktop",
                    "org.freedesktop.portal.OpenURI",
                    "OpenFile",
                    params,
                    GLib.VariantType.new("(o)"),
                    Gio.DBusCallFlags.NONE,
                    -1,
                    fds,
                    None,
                )
                self._log(f"[UI] Apri con portal: {target}")
            finally:
                os.close(fd)

        except Exception as e:
            self._log(f"[WARN] Apri con portal fallito: {e}")
            QtWidgets.QMessageBox.warning(
                self,
                L("Apri con…"),
                L("Impossibile aprire il selettore applicazione.")
            )

    def _show_input_context_menu(self, pos) -> None:
        item = self.list_files.itemAt(pos)
        if item is None:
            return

        menu = QMenu(self)

        act_open = menu.addAction(L("Apri"))
        act_open_with = menu.addAction(L("Apri con…"))
        act_open_dir = menu.addAction(L("Apri cartella di origine"))
        menu.addSeparator()
        act_remove = menu.addAction(L("Rimuovi dalla lista"))

        chosen = menu.exec_(self.list_files.mapToGlobal(pos))
        if chosen is act_open:
            try:
                pp = Path(item.text()).expanduser().resolve()
                QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(pp)))
                self._log(f"[UI] Apri: {pp}")
            except Exception as e:
                self._log(f"[WARN] Apri fallito: {e}")
        elif chosen is act_open_with:
            self._portal_open_with_dialog(item.text())
        elif chosen is act_open_dir:
            try:
                pp = Path(item.text()).expanduser().resolve()
                folder = pp if pp.is_dir() else pp.parent
                QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(folder)))
                self._log(f"[UI] Apri cartella origine: {folder}")
            except Exception as e:
                self._log(f"[WARN] Apri cartella origine fallito: {e}")
        elif chosen is act_remove:
            row = self.list_files.row(item)
            if row >= 0:
                self.list_files.takeItem(row)
                self._log("[UI] Rimosso 1 file dal menu contestuale")
                self._rebuild_entries_from_sources()

    def on_remove_selected(self) -> None:
        rows = sorted({i.row() for i in self.list_files.selectedIndexes()}, reverse=True)
        for r in rows:
            self.list_files.takeItem(r)
        self._log(f"[UI] Rimossi {len(rows)} file")
        self._rebuild_entries_from_sources()

    # ---------- entries ----------
    def _rebuild_entries_from_sources(self) -> None:
        self._set_busy(True)
        try:
            self._sources = [Path(self.list_files.item(i).text()) for i in range(self.list_files.count())]
            entries: List[RemuxEntry] = []
            chapters_candidate: Optional[Path] = None

            for src in self._sources:
                if not src.exists():
                    continue
                suf = src.suffix.lower()

                if suf == ".xml" and "chap" in src.name.lower():
                    chapters_candidate = src
                    continue

                if suf == ".mkv":
                    try:
                        mi = probe_mkv(src, self._tc)
                        for t in mi.tracks:
                            lang = self._norm_lang(t.language or "und")
                            forced = bool(t.flag_forced) if t.flag_forced is not None else False
                            original_name = (t.name or "").strip()
                            # audio default: nome originale; subs default: include forced/normal
                            name = self._default_track_name(src, t.type, lang, forced, original_name)
                            entries.append(RemuxEntry(
                                src=src,
                                src_label=src.name,
                                kind=t.type,
                                tid=t.tid,
                                is_mkv=True,
                                include=True,
                                lang=lang,
                                name=name,
                                default=bool(t.flag_default) if t.flag_default is not None else False,
                                forced=forced,
                                codec_id=t.codec_id or "",
                            ))
                    except Exception as e:
                        self._log(f"[WARN] Probe MKV fallito su {src.name}: {e}")
                    continue

                # external single file
                kind = "other"
                if suf in AUDIO_EXT: kind = "audio"
                elif suf in SUB_EXT: kind = "subtitles"
                elif suf in VIDEO_EXT: kind = "video"

                lang = self._guess_lang_from_path(src) if kind in ("audio", "subtitles") else "und"
                forced = self._guess_forced(src) if kind == "subtitles" else False
                name = self._default_track_name(src, kind, lang, forced, src.stem)

                entries.append(RemuxEntry(
                    src=src,
                    src_label=src.name,
                    kind=kind,
                    tid=0,
                    is_mkv=False,
                    include=True,
                    lang=lang,
                    name=name,
                    default=False,
                    forced=forced,
                    codec_id="",
                ))

            # chapters display: override > auto candidate
            ch = self._chapters_override if (self._chapters_override and self._chapters_override.is_file()) else chapters_candidate
            self.ed_chapters.setText(str(ch) if ch and ch.is_file() else "")

            # order: video -> audio -> subs -> other
            def pri(k: str) -> int:
                kk = (k or "").lower()
                if kk == "video": return 0
                if kk == "audio": return 1
                if kk == "subtitles": return 2
                return 3
            entries.sort(key=lambda e: (pri(e.kind), e.src_label.lower(), e.tid))

            self._entries = entries
            self._fill_tracks_table(entries)
            self._auto_title_from_video()
        finally:
            self._set_busy(False)

    def _fill_tracks_table(self, entries: List[RemuxEntry]) -> None:
        self._table_entries = list(entries or [])
        self._ui_lock = True
        try:
            self.tbl_tracks.setRowCount(0)
            self.tbl_tracks.setRowCount(len(entries))
            for r, e in enumerate(entries):
                it_inc = QTableWidgetItem("")
                it_inc.setFlags(it_inc.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                it_inc.setCheckState(Qt.Checked if e.include else Qt.Unchecked)
                self.tbl_tracks.setItem(r, self.COL_INC, it_inc)

                self.tbl_tracks.setItem(r, self.COL_SRC, self._item(e.src_label, editable=False))
                self.tbl_tracks.setItem(r, self.COL_KIND, self._item(e.kind, editable=False))
                self.tbl_tracks.setItem(r, self.COL_ID, self._item(str(e.tid), editable=False))
                self.tbl_tracks.setItem(r, self.COL_LANG, self._item(e.lang, editable=True))
                self.tbl_tracks.setItem(r, self.COL_NAME, self._item(e.name, editable=True))

                it_def = QTableWidgetItem("")
                it_def.setFlags(it_def.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                it_def.setCheckState(Qt.Checked if e.default else Qt.Unchecked)
                self.tbl_tracks.setItem(r, self.COL_DEF, it_def)

                it_for = QTableWidgetItem("")
                it_for.setFlags(it_for.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                it_for.setCheckState(Qt.Checked if e.forced else Qt.Unchecked)
                self.tbl_tracks.setItem(r, self.COL_FOR, it_for)
        finally:
            self._ui_lock = False


    def _table_has_audio_rows(self) -> bool:
        for row in range(self.tbl_tracks.rowCount()):
            try:
                if self._row_is_audio(row):
                    return True
            except Exception:
                pass
        return False

    def _autosync_pulse_step(self) -> None:
        try:
            v = int(getattr(self, "_autosync_anim_value", 0))
            v += 7
            if v > 100:
                v = 7
            self._autosync_anim_value = v
            self.progress.setRange(0, 100)
            self.progress.setValue(v)
        except Exception:
            pass


    def _autosync_busy_begin(self) -> None:
        try:
            self._autosync_prev_progress_range = (self.progress.minimum(), self.progress.maximum())
        except Exception:
            self._autosync_prev_progress_range = None
        try:
            self._autosync_prev_progress_value = self.progress.value()
        except Exception:
            self._autosync_prev_progress_value = 0
        try:
            self._autosync_prev_progress_format = self.progress.format()
        except Exception:
            self._autosync_prev_progress_format = "%p%"
        try:
            self._autosync_prev_progress_text_visible = self.progress.isTextVisible()
        except Exception:
            self._autosync_prev_progress_text_visible = True

        try:
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.progress.setFormat(L("Analisi contenuto in corso… %p%"))
            self.progress.setTextVisible(True)
        except Exception:
            pass

        self._autosync_anim_value = 0
        try:
            if self._autosync_anim_timer is None:
                self._autosync_anim_timer = QTimer(self)
                self._autosync_anim_timer.timeout.connect(self._autosync_pulse_step)
            if self._autosync_anim_timer.isActive():
                self._autosync_anim_timer.stop()
            self._autosync_anim_timer.start(120)
        except Exception:
            pass

        try:
            self._set_busy(True)
        except Exception:
            pass


    def _autosync_busy_end(self) -> None:
        try:
            if self._autosync_anim_timer is not None and self._autosync_anim_timer.isActive():
                self._autosync_anim_timer.stop()
        except Exception:
            pass

        try:
            rng = getattr(self, "_autosync_prev_progress_range", None)
            if rng and isinstance(rng, tuple) and len(rng) == 2:
                self.progress.setRange(int(rng[0]), int(rng[1]))
            else:
                self.progress.setRange(0, 100)
        except Exception:
            pass

        try:
            self.progress.setValue(int(getattr(self, "_autosync_prev_progress_value", 0) or 0))
        except Exception:
            pass

        try:
            self.progress.setFormat(str(getattr(self, "_autosync_prev_progress_format", "%p%")))
        except Exception:
            try:
                self.progress.setFormat("%p%")
            except Exception:
                pass

        try:
            self.progress.setTextVisible(bool(getattr(self, "_autosync_prev_progress_text_visible", True)))
        except Exception:
            pass

        try:
            self._set_busy(False)
        except Exception:
            pass


    def _autosync_ui_pulse(self) -> None:
        try:
            self._autosync_pulse_step()
        except Exception:
            pass


    def _show_delay_info(self) -> None:
        dlg = QtWidgets.QDialog(self)
        try:
            dlg.setWindowTitle(self.btn_delay_info.toolTip() or L("Guida sync"))
        except Exception:
            dlg.setWindowTitle(L("Guida sync"))
        dlg.setModal(True)
        dlg.resize(820, 620)

        lay = QtWidgets.QVBoxLayout(dlg)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        view = QtWidgets.QTextBrowser(dlg)
        view.setOpenExternalLinks(True)
        view.setReadOnly(True)
        view.setHtml(
            "<h2>" + L("Guida rapida sync audio e sottotitoli") + "</h2>"

            "<p>" + L("Questa finestra serve per capire come lavorare sul sync senza fare confusione tra riga selezionata, checkbox, preview e remux.") + "</p>"

            "<h3>" + L("Regola fondamentale") + "</h3>"
            "<ul>"
            "<li><b>" + L("Riga selezionata") + "</b>: " + L("comanda il valore del delay, i piccoli aggiustamenti con i pulsanti - / + e la Preview.") + "</li>"
            "<li><b>" + L("Checkbox") + "</b>: " + L("serve solo a decidere se quella traccia sarà inclusa nel remux finale.") + "</li>"
            "</ul>"

            "<h3>" + L("Sync audio manuale") + "</h3>"
            "<ul>"
            "<li>" + L("Lavora sempre sulla traccia audio selezionata.") + "</li>"
            "<li>" + L("Valore negativo = anticipa l'audio.") + "</li>"
            "<li>" + L("Valore positivo = ritarda l'audio.") + "</li>"
            "<li>" + L("0 ms = nessuna correzione.") + "</li>"
            "<li>" + L("Se hai già trovato il valore corretto con VLC o con altre prove, inseriscilo qui mantenendo lo stesso segno.") + "</li>"
            "</ul>"

            "<h3>" + L("Pulsanti - / +") + "</h3>"
            "<p>" + L("I pulsanti piccoli servono solo per fare ritocchi rapidi di pochi millisecondi, senza riscrivere il numero a mano. In pratica: piccoli passi avanti o indietro finché il sync ti sembra giusto.") + "</p>"

            "<h3>" + L("Auto-sync audio") + "</h3>"
            "<p>" + L("Auto-sync prova a stimare il delay delle tracce audio interne del file MKV. È utile come punto di partenza, ma non è magia: se il risultato non ti convince, controlla sempre con la Preview e rifinisci a mano.") + "</p>"

            "<h3>" + L("Preview") + "</h3>"
            "<p>" + L("La Preview serve per controllare a orecchio se audio e video sono allineati. Il flusso giusto è: seleziona la riga, prova il valore, ascolta la Preview, poi ritocca ancora finché sei a posto.") + "</p>"

            "<h3>" + L("Sync sottotitoli") + "</h3>"
            "<ul>"
            "<li>" + L("Per i sottotitoli puoi applicare un offset fisso, cioè spostarli tutti avanti o indietro dello stesso valore.") + "</li>"
            "<li>" + L("Se il problema è uguale dall'inizio alla fine, basta un offset fisso.") + "</li>"
            "<li>" + L("Se all'inizio sembrano giusti ma poi si sfasano sempre di più, allora non basta un offset: lì serve il drift.") + "</li>"
            "</ul>"

            "<h3>" + L("Drift sottotitoli") + "</h3>"
            "<ul>"
            "<li>" + L("Prima cosa: non guardare un solo punto del film. Per capire bene il problema devi controllare almeno 3 punti diversi: inizio, metà e fine.") + "</li>"
            "<li>" + L("Esempio pratico: scegli una battuta chiara o un momento in cui si capisce bene quando il sottotitolo dovrebbe comparire, e confrontalo in questi 3 punti.") + "</li>"
            "<li>" + L("Se all'inizio, a metà e alla fine il sottotitolo è sempre in ritardo o in anticipo più o meno dello stesso valore, allora NON è drift: basta uno spostamento fisso avanti o indietro.") + "</li>"
            "<li>" + L("Se invece all'inizio sembra quasi giusto, a metà è più sfasato e alla fine ancora di più, allora c'è drift.") + "</li>"
            "<li>" + L("Detto semplice: il drift è quando l'errore non resta uguale, ma cambia man mano che il video va avanti.") + "</li>"
            "<li>" + L("In quel caso non devi solo spostare tutto, ma correggere il tempo dei sottotitoli in modo progressivo.") + "</li>"
            "<li>" + L("Per i sottotitoli testo/SRT questa correzione si può fare, e poi conviene sempre controllare il risultato con la Preview prima del remux finale.") + "</li>"
            "<li>" + L("Per i sottotitoli bitmap, invece, questa correzione di solito non è davvero gestibile bene: nella maggior parte dei casi puoi solo spostarli tutti avanti o indietro con un offset fisso.") + "</li>"
            "</ul>"

            "<h3>" + L("Metodo consigliato, senza incasinarsi") + "</h3>"
            "<ol>"
            "<li>" + L("Seleziona la riga giusta.") + "</li>"
            "<li>" + L("Per l'audio: prova Auto-sync oppure inserisci un valore manuale.") + "</li>"
            "<li>" + L("Controlla con la Preview.") + "</li>"
            "<li>" + L("Rifinisci con il numero manuale o con i piccoli pulsanti - / +.") + "</li>"
            "<li>" + L("Per i sottotitoli: prima capisci se basta un offset fisso oppure se c'è drift.") + "</li>"
            "<li>" + L("Solo alla fine decidi cosa includere davvero nel remux tramite le checkbox.") + "</li>"
            "</ol>"

            "<p><b>" + L("Regola pratica") + "</b>: " + L("se non sei sicuro, non fare troppe mosse insieme. Una prova, una Preview, un ritocco. Così capisci subito cosa ha cambiato davvero il sync.") + "</p>"
        )
        lay.addWidget(view, 1)

        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        btn_close = QtWidgets.QPushButton(L("Chiudi"), dlg)
        btn_close.clicked.connect(dlg.accept)
        row.addWidget(btn_close)
        lay.addLayout(row)

        dlg.exec_()

    def _sync_source_token(self, text: str) -> str:
        txt = (text or "").strip()
        if not txt:
            return ""
        try:
            return str(Path(txt).expanduser().resolve())
        except Exception:
            return txt

    def _row_type_text(self, row: int) -> str:
        it = self.tbl_tracks.item(row, 2)
        return (it.text().strip().lower() if it and it.text() else "")

    def _row_entry(self, row: int):
        try:
            entries = getattr(self, "_table_entries", []) or []
            if 0 <= int(row) < len(entries):
                return entries[int(row)]
        except Exception:
            pass
        return None

    def _row_source_text(self, row: int) -> str:
        e = self._row_entry(row)
        if e is not None:
            try:
                return str(Path(e.src))
            except Exception:
                try:
                    return str(e.src)
                except Exception:
                    pass
        it = self.tbl_tracks.item(row, 1)
        return (it.text().strip() if it and it.text() else "")

    def _row_track_id_text(self, row: int) -> str:
        e = self._row_entry(row)
        if e is not None:
            try:
                return str(int(e.tid))
            except Exception:
                try:
                    return str(e.tid)
                except Exception:
                    pass
        it = self.tbl_tracks.item(row, 3)
        return (it.text().strip() if it and it.text() else "")

    def _row_include_checked(self, row: int) -> bool:
        it = self.tbl_tracks.item(row, 0)
        return bool(it and it.checkState() == Qt.Checked)

    def _row_is_audio(self, row: int) -> bool:
        e = self._row_entry(row)
        if e is not None:
            kind = (getattr(e, "kind", "") or "").strip().lower()
            return ("audio" in kind) or (kind in ("a", "sound", "sonoro"))
        t = self._row_type_text(row)
        return ("audio" in t) or (t in ("a", "sound", "sonoro"))

    def _row_sync_key(self, row: int):
        if not self._row_is_audio(row):
            return None
        src = self._row_source_text(row)
        tid = self._row_track_id_text(row)
        if not src or not tid:
            return None
        return (self._sync_source_token(src), tid)

    def _current_audio_row(self) -> int:
        rows = []
        for idx in self.tbl_tracks.selectedIndexes():
            if idx.row() not in rows:
                rows.append(idx.row())
        for row in rows:
            if self._row_is_audio(row):
                return row
        return -1

    def _current_audio_sync_key(self):
        row = self._current_audio_row()
        if row < 0:
            return None
        return self._row_sync_key(row)

    def _safe_suggest_content_sync_ms(self, src_path: Path, mkvmerge_bin: str, ffmpeg_bin: str):
        try:
            import json as _json
            import os as _os
            import subprocess as _subprocess
            import sys as _sys

            repo_root = Path(__file__).resolve().parents[3]
            code = (
                "import json, sys\n"
                "from pathlib import Path\n"
                "sys.path.insert(0, sys.argv[1])\n"
                "from hevc_gui.mkv_suite.core.auto_sync_content import suggest_content_sync_ms\n"
                "res = suggest_content_sync_ms(\n"
                "    mkvmerge_bin=sys.argv[2],\n"
                "    ffmpeg_bin=sys.argv[3],\n"
                "    src_path=sys.argv[4],\n"
                "    analyze_seconds=600,\n"
                "    noise_db=-35.0,\n"
                "    silence_d=0.20,\n"
                "    black_d=0.20,\n"
                "    black_pic_th=0.98,\n"
                "    max_abs_ms=5000,\n"
                ")\n"
                "print(json.dumps(res))\n"
            )

            env = _os.environ.copy()
            old_pp = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = str(repo_root) + (_os.pathsep + old_pp if old_pp else "")

            r = _subprocess.run(
                [_sys.executable, "-c", code, str(repo_root), str(mkvmerge_bin), str(ffmpeg_bin), str(src_path)],
                stdout=_subprocess.PIPE,
                stderr=_subprocess.PIPE,
                text=True,
                env=env,
                timeout=900,
            )

            if r.returncode != 0:
                msg = (r.stderr or r.stdout or "").strip()
                raise RuntimeError(msg or f"autosync child failed rc={r.returncode}")

            txt = (r.stdout or "").strip()
            if not txt:
                return {}

            data = _json.loads(txt)
            out = {}
            for k, v in (data or {}).items():
                out[int(k)] = int(v)
            return out

        except Exception as e:
            raise RuntimeError(str(e))


    def _detect_ffmpeg_bin(self) -> str:
        for name in ("ffmpeg", "ffmpeg_bin", "ffmpeg_path"):
            try:
                val = getattr(self._tc, name, None)
            except Exception:
                val = None
            if val:
                return str(val)
        try:
            import shutil as _shutil
            return _shutil.which("ffmpeg") or ""
        except Exception:
            return ""

    def _autosync_candidate_sources(self):
        out = []
        seen = set()

        for row in range(self.tbl_tracks.rowCount()):
            try:
                if not self._row_include_checked(row):
                    continue
                if not self._row_is_audio(row):
                    continue

                src_text = self._row_source_text(row)
                if not src_text:
                    continue

                src = Path(src_text)
                if src.suffix.lower() != ".mkv":
                    continue
                if not src.is_file():
                    continue

                tok = self._sync_source_token(str(src))
                if tok in seen:
                    continue
                seen.add(tok)
                out.append(src)
            except Exception:
                continue

        if not out:
            try:
                mkv = self._pick_target_mkv()
            except Exception:
                mkv = None
            if mkv and mkv.is_file():
                out.append(mkv)

        return out
    def _ensure_auto_sync_for_included_sources(self, force: bool = False) -> None:
        if getattr(self, "_autosync_running", False):
            return

        if not bool(self.chk_autosync.isChecked()) and not force:
            return

        self._autosync_running = True
        try:
            try:
                mkvmerge_bin = str(getattr(self._tc, "mkvmerge", "") or "")
            except Exception:
                mkvmerge_bin = ""

            if not mkvmerge_bin:
                try:
                    self._log("[WARN] Auto-sync non disponibile: mkvmerge mancante.")
                except Exception:
                    pass
                return

            try:
                from hevc_gui.mkv_suite.core.auto_sync import suggest_track_sync_ms
            except Exception:
                try:
                    from ..core.auto_sync import suggest_track_sync_ms
                except Exception as e:
                    try:
                        self._log(f"[WARN] Auto-sync backend non importabile: {e}")
                    except Exception:
                        pass
                    return

            sources = self._autosync_candidate_sources()
            if not sources:
                return

            self._autosync_busy_begin()
            try:
                for src_path in sources:
                    tok = self._sync_source_token(str(src_path))
                    if (not force) and (tok in self._audio_sync_auto_done_sources):
                        continue

                    try:
                        res = suggest_track_sync_ms(
                            mkvmerge_bin=mkvmerge_bin,
                            mkv_path=src_path,
                            types=("audio",),
                            threshold_ms=0,
                        )

                        old_keys = [k for k in list(self._audio_sync_auto_ms.keys()) if k[0] == tok]
                        for k in old_keys:
                            self._audio_sync_auto_ms.pop(k, None)

                        for tid, delay in sorted((res or {}).items()):
                            self._audio_sync_auto_ms[(tok, str(int(tid)))] = int(delay)

                        self._audio_sync_auto_done_sources.add(tok)

                        try:
                            if res:
                                pretty = ", ".join(f"{tid}:{delay}ms" for tid, delay in sorted(res.items()))
                                self._log(f"[AUTO] {Path(src_path).name}: {pretty}")
                            else:
                                self._log(f"[AUTO] {Path(src_path).name}: nessun delay container rilevato.")
                        except Exception:
                            pass

                    except Exception as e:
                        try:
                            self._log(f"[WARN] Auto-sync fallito su {Path(src_path).name}: {e}")
                        except Exception:
                            pass
            finally:
                self._autosync_busy_end()
        finally:
            self._autosync_running = False



    def _get_delay_for_key(self, key) -> int:
        if not key:
            return 0

        try:
            tok, tid, kind = key
        except Exception:
            try:
                tok, tid = key
                kind = "audio"
            except Exception:
                return 0

        kind = (kind or "audio").strip().lower()

        if kind == "subtitles":
            return int(self._subtitle_sync_manual_ms.get((tok, tid, "subtitles"), 0) or 0)

        if self.chk_autosync.isChecked():
            try:
                return int(self._audio_sync_auto_ms.get((tok, tid), 0) or 0)
            except Exception:
                return 0

        v = self._audio_sync_manual_ms.get((tok, tid, "audio"), None)
        if v is None:
            v = self._audio_sync_manual_ms.get((tok, tid), 0)
        return int(v or 0)



    def _refresh_delay_ui(self) -> None:
        if getattr(self, "_delay_ui_guard", False):
            return

        self._delay_ui_guard = True
        try:
            key = self._current_sync_key()
            selected_kind = key[2] if key and len(key) >= 3 else ""
            auto = bool(self.chk_autosync.isChecked())
            auto_for_ui = auto and selected_kind == "audio"

            has_any_audio = any((getattr(e, "kind", "") or "").strip().lower() == "audio" for e in getattr(self, "_entries", []))
            has_delay_target = selected_kind in ("audio", "subtitles")

            current_entry = self._current_selected_entry()
            can_drift_sub = bool(self._subtitle_entry_supports_drift(current_entry))

            try:
                self.chk_autosync.setEnabled(bool(has_any_audio and selected_kind != "subtitles"))
            except Exception:
                pass

            try:
                self.btn_autosync_run.setEnabled(bool(has_any_audio and selected_kind != "subtitles"))
            except Exception:
                pass

            self.lbl_delay.setEnabled(has_delay_target)
            self.spn_delay.setEnabled(has_delay_target and not auto_for_ui)

            try:
                self.btn_delay_info.setEnabled(True)
            except Exception:
                pass

            try:
                self._set_delay_nudge_enabled(has_delay_target and not auto_for_ui)
            except Exception:
                pass

            try:
                self.btn_preview.setEnabled(bool(has_delay_target and self._pick_target_mkv() is not None))
            except Exception:
                pass

            try:
                self.btn_sub_drift.setEnabled(bool(can_drift_sub))
            except Exception:
                pass

            value = self._get_delay_for_key(key) if has_delay_target else 0
            self.spn_delay.blockSignals(True)
            self.spn_delay.setValue(int(value))
            self.spn_delay.blockSignals(False)
        finally:
            self._delay_ui_guard = False

    def _clear_tracks_selection(self) -> None:
        try:
            self.tbl_tracks.clearSelection()
        except Exception:
            pass
        try:
            self.tbl_tracks.setCurrentCell(-1, -1)
        except Exception:
            pass
        try:
            sm = self.tbl_tracks.selectionModel()
            if sm is not None:
                sm.clearCurrentIndex()
        except Exception:
            pass
        self._tracks_last_clicked_row = -1
        try:
            self._refresh_delay_ui()
        except Exception:
            pass


    def _on_tracks_cell_clicked_toggle(self, row: int, col: int) -> None:
        row = int(row)
        last = int(getattr(self, "_tracks_last_clicked_row", -1))

        if last == row:
            try:
                QtCore.QTimer.singleShot(0, self._clear_tracks_selection)
            except Exception:
                self._clear_tracks_selection()
            return

        self._tracks_last_clicked_row = row
        try:
            self.tbl_tracks.selectRow(row)
        except Exception:
            pass
        try:
            self._refresh_delay_ui()
        except Exception:
            pass

    def _on_tracks_selection_changed(self) -> None:
        self._refresh_delay_ui()


    def _on_autosync_toggled(self, checked: bool) -> None:
        if checked:
            self._ensure_auto_sync_for_included_sources(force=False)
        self._refresh_delay_ui()


    def _entry_sync_key(self, e):
        try:
            kind = (getattr(e, "kind", "") or "").strip().lower()
        except Exception:
            kind = ""
        if kind not in ("audio", "subtitles"):
            return None
        try:
            tok = self._sync_source_token(str(getattr(e, "src", "")))
        except Exception:
            return None
        try:
            tid = str(int(getattr(e, "tid", 0)))
        except Exception:
            return None
        return (tok, tid, kind)

    def _current_sync_key(self):
        row = self.tbl_tracks.currentRow()
        if row < 0:
            return None

        e = None
        try:
            if 0 <= row < len(self._entries):
                e = self._entries[row]
        except Exception:
            e = None

        if e is not None:
            return self._entry_sync_key(e)

        try:
            kind = (self.tbl_tracks.item(row, self.COL_KIND).text() or "").strip().lower()
            tid = int((self.tbl_tracks.item(row, self.COL_ID).text() or "").strip())
            src_label = (self.tbl_tracks.item(row, self.COL_SRC).text() or "").strip()
        except Exception:
            return None

        if kind not in ("audio", "subtitles"):
            return None

        try:
            tok = self._sync_source_token(src_label)
        except Exception:
            return None

        return (tok, str(tid), kind)

    def _current_audio_sync_key(self):
        key = self._current_sync_key()
        if key and len(key) >= 3 and key[2] == "audio":
            return key
        return None

    def _current_subtitle_sync_key(self):
        key = self._current_sync_key()
        if key and len(key) >= 3 and key[2] == "subtitles":
            return key
        return None

    def _first_included_entry(self, kind: str, src: Path | None = None):
        kind = (kind or "").strip().lower()
        for e in getattr(self, "_entries", []):
            try:
                if not bool(getattr(e, "include", False)):
                    continue
                if (getattr(e, "kind", "") or "").strip().lower() != kind:
                    continue
                if src is not None and Path(getattr(e, "src")) != Path(src):
                    continue
                return e
            except Exception:
                continue
        return None

    def _set_delay_nudge_enabled(self, enabled: bool) -> None:
        for _b in getattr(self, "_delay_nudge_buttons", []):
            try:
                _b.setEnabled(bool(enabled))
            except Exception:
                pass
        try:
            self.btn_delay_reset.setEnabled(bool(enabled))
        except Exception:
            pass


    def _on_delay_nudge_clicked(self) -> None:
        key = self._current_sync_key()
        if not key:
            return

        kind = key[2] if len(key) >= 3 else "audio"
        if kind == "audio" and self.chk_autosync.isChecked():
            return

        btn = self.sender()
        if btn is None:
            return

        try:
            delta = int(btn.property("delay_delta"))
        except Exception:
            return

        try:
            self.spn_delay.setValue(int(self.spn_delay.value()) + int(delta))
        except Exception:
            pass


    def _on_delay_reset_clicked(self) -> None:
        key = self._current_sync_key()
        if not key:
            return

        kind = key[2] if len(key) >= 3 else "audio"
        if kind == "audio" and self.chk_autosync.isChecked():
            return

        try:
            self.spn_delay.setValue(0)
        except Exception:
            pass

    def _current_selected_entry(self):
        row = self.tbl_tracks.currentRow()
        if row < 0:
            return None
        try:
            if 0 <= row < len(self._entries):
                return self._entries[row]
        except Exception:
            pass
        return None


    def _subtitle_entry_supports_drift(self, e) -> bool:
        if e is None:
            return False
        try:
            kind = (getattr(e, "kind", "") or "").strip().lower()
            is_mkv = bool(getattr(e, "is_mkv", False))
            p = Path(getattr(e, "src"))
            codec_id = (getattr(e, "codec_id", "") or "").strip().upper()
        except Exception:
            return False

        if kind != "subtitles":
            return False

        if not is_mkv:
            return p.suffix.lower() in (".srt", ".ass", ".ssa", ".vtt")

        # interni testuali supportati
        if codec_id in ("S_TEXT/UTF8", "S_TEXT/ASCII"):
            return True
        if codec_id in ("S_TEXT/ASS", "S_ASS"):
            return True
        if codec_id in ("S_TEXT/SSA", "S_SSA"):
            return True
        if codec_id in ("S_TEXT/WEBVTT",):
            return True
        return False

    def _subtitle_internal_text_suffix(self, e):
        if e is None:
            return None
        try:
            codec_id = (getattr(e, "codec_id", "") or "").strip().upper()
        except Exception:
            return None

        if codec_id in ("S_TEXT/UTF8", "S_TEXT/ASCII"):
            return ".srt"
        if codec_id in ("S_TEXT/ASS", "S_ASS"):
            return ".ass"
        if codec_id in ("S_TEXT/SSA", "S_SSA"):
            return ".ssa"
        if codec_id in ("S_TEXT/WEBVTT",):
            return ".vtt"
        return None

    def _extract_internal_text_subtitle_for_drift(self, e, out_dir: Path) -> Path | None:
        if e is None:
            return None
        if not bool(getattr(e, "is_mkv", False)):
            return None

        suffix = self._subtitle_internal_text_suffix(e)
        if not suffix:
            return None

        try:
            mkvextract = getattr(self._tc, "mkvextract", None)
            if not mkvextract:
                raise RuntimeError("mkvextract non trovato")
            src_path = Path(getattr(e, "src"))
            tid = int(getattr(e, "tid", 0))
        except Exception as ex:
            raise RuntimeError(f"dati subtitle interno non validi: {ex}")

        out_dir.mkdir(parents=True, exist_ok=True)
        dst = out_dir / f"{src_path.stem}_t{tid}{suffix}"

        _subprocess = __import__("subprocess")
        cmd = [str(mkvextract), "tracks", str(src_path), f"{tid}:{dst}"]
        r = _subprocess.run(cmd, stdout=_subprocess.PIPE, stderr=_subprocess.PIPE, text=True)
        if r.returncode != 0 or not dst.is_file():
            msg = (r.stderr or r.stdout or "").strip() or "mkvextract failed"
            raise RuntimeError(msg)

        return dst

    def _subtitle_drift_key(self, e):
        return self._entry_sync_key(e)

    def _subtitle_drift_points_for_entry(self, e):
        k = self._subtitle_drift_key(e)
        if not k:
            return []
        pts = self._subtitle_drift_points.get(k, [])
        out = []
        for item in pts:
            try:
                t, off = item
                out.append((int(t), int(off)))
            except Exception:
                pass
        out.sort(key=lambda x: x[0])
        return out[:3]

    def _parse_timecode_ms_ui(self, s: str) -> int:
        s = str(s or "").strip()
        if not s:
            raise ValueError("Tempo vuoto")
        if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
            return int(s)

        parts = s.split(":")
        if len(parts) == 2:
            hh = 0
            mm, rest = parts
        elif len(parts) == 3:
            hh, mm, rest = parts
        else:
            raise ValueError(f"Formato tempo non valido: {s}")

        if "." in rest:
            ss, ms = rest.split(".", 1)
            ms = (ms + "000")[:3]
        elif "," in rest:
            ss, ms = rest.split(",", 1)
            ms = (ms + "000")[:3]
        else:
            ss, ms = rest, "000"

        return (((int(hh) * 60 + int(mm)) * 60 + int(ss)) * 1000) + int(ms)

    def _fmt_timecode_ms_ui(self, ms: int) -> str:
        ms = int(ms)
        neg = ms < 0
        ms = abs(ms)
        hh = ms // 3600000
        ms %= 3600000
        mm = ms // 60000
        ms %= 60000
        ss = ms // 1000
        ms %= 1000
        out = f"{hh:02d}:{mm:02d}:{ss:02d}.{ms:03d}"
        return "-" + out if neg else out


    def _render_drifted_subtitle_for_entry(self, e, out_dir: Path) -> Path | None:
        if not self._subtitle_entry_supports_drift(e):
            return None

        pts = self._subtitle_drift_points_for_entry(e)
        if len(pts) < 2:
            return None

        try:
            from hevc_gui.mkv_suite.core.subtitle_drift import DriftPoint, retime_subtitle_file
        except Exception:
            from ..core.subtitle_drift import DriftPoint, retime_subtitle_file  # type: ignore

        out_dir.mkdir(parents=True, exist_ok=True)

        if bool(getattr(e, "is_mkv", False)):
            src_dir = out_dir / "_src"
            src_dir.mkdir(parents=True, exist_ok=True)
            src_path = self._extract_internal_text_subtitle_for_drift(e, src_dir)
            if src_path is None:
                return None
        else:
            src_path = Path(getattr(e, "src"))

        dst = out_dir / f"{src_path.stem}_drifted{src_path.suffix.lower()}"

        retime_subtitle_file(
            src_path,
            dst,
            [DriftPoint(time_ms=int(t), offset_ms=int(off)) for t, off in pts],
        )
        return dst

    def _on_subtitle_drift_clicked(self) -> None:
        e = self._current_selected_entry()
        if not self._subtitle_entry_supports_drift(e):
            QMessageBox.information(
                self,
                L("Info"),
                L("Drift disponibile solo per subtitle esterni testuali (.srt / .ass / .ssa / .vtt)."),
            )
            return

        current = self._subtitle_drift_points_for_entry(e)
        defaults = current if len(current) == 3 else [
            (5 * 60 * 1000, 0),
            (50 * 60 * 1000, 0),
            (100 * 60 * 1000, 0),
        ]

        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(L("Drift subtitle (3 punti)"))
        dlg.setModal(True)

        root = QtWidgets.QVBoxLayout(dlg)
        lbl = QtWidgets.QLabel(L("Inserisci 3 punti tempo/offset. L'offset è in millisecondi."))
        root.addWidget(lbl)

        grid = QtWidgets.QGridLayout()
        edits_t = []
        edits_o = []

        for i in range(3):
            grid.addWidget(QtWidgets.QLabel(L("Punto {n} tempo").format(n=i+1)), i, 0)
            ed_t = QtWidgets.QLineEdit(self._fmt_timecode_ms_ui(defaults[i][0]))
            ed_t.setPlaceholderText("00:05:00.000")
            grid.addWidget(ed_t, i, 1)

            grid.addWidget(QtWidgets.QLabel(L("Offset ms")), i, 2)
            sp_o = QtWidgets.QSpinBox()
            sp_o.setRange(-3600000, 3600000)
            sp_o.setValue(int(defaults[i][1]))
            grid.addWidget(sp_o, i, 3)

            edits_t.append(ed_t)
            edits_o.append(sp_o)

        root.addLayout(grid)

        btns = QtWidgets.QDialogButtonBox()
        btn_ok = btns.addButton(QtWidgets.QDialogButtonBox.Ok)
        btn_cancel = btns.addButton(QtWidgets.QDialogButtonBox.Cancel)
        btn_clear = btns.addButton(L("Clear"), QtWidgets.QDialogButtonBox.ResetRole)
        root.addWidget(btns)

        btn_ok.clicked.connect(dlg.accept)
        btn_cancel.clicked.connect(dlg.reject)

        def _clear():
            k = self._subtitle_drift_key(e)
            if k in self._subtitle_drift_points:
                self._subtitle_drift_points.pop(k, None)
            dlg.done(2)

        btn_clear.clicked.connect(_clear)

        rc = dlg.exec_() if hasattr(dlg, "exec_") else dlg.exec()
        if rc == 2:
            try:
                self._log("[DRIFT] Drift subtitle rimosso.")
            except Exception:
                pass
            self._refresh_delay_ui()
            return

        if rc != QtWidgets.QDialog.Accepted:
            return

        pts = []
        try:
            for i in range(3):
                t = self._parse_timecode_ms_ui(edits_t[i].text())
                off = int(edits_o[i].value())
                pts.append((t, off))
            pts.sort(key=lambda x: x[0])
        except Exception as ex:
            QMessageBox.warning(self, L("Errore"), L("Punti drift non validi: {ex}").format(ex=ex))
            return

        self._subtitle_drift_points[self._subtitle_drift_key(e)] = pts
        try:
            pretty = ", ".join(f"{self._fmt_timecode_ms_ui(t)}->{off:+d}ms" for t, off in pts)
            self._log(f"[DRIFT] Salvato: {pretty}")
        except Exception:
            pass
        self._refresh_delay_ui()

    def _tmp_cleanup_dirs(self):
        try:
            root = self._project_tmp_root()
        except Exception:
            root = Path(__file__).resolve().parents[3] / "tmp"
        return [
            root / "preview",
            root / "subtitle_drift_remux",
        ]


    def _cleanup_temp_artifacts(self) -> None:
        try:
            import shutil as _shutil

            removed = False
            for p in self._tmp_cleanup_dirs():
                try:
                    p = Path(p)
                    if p.is_symlink() or p.is_file():
                        p.unlink(missing_ok=True)
                        removed = True
                    elif p.is_dir():
                        # svuota la directory ma lascia la root tmp intatta
                        for child in p.iterdir():
                            try:
                                if child.is_symlink() or child.is_file():
                                    child.unlink(missing_ok=True)
                                elif child.is_dir():
                                    _shutil.rmtree(child, ignore_errors=True)
                            except Exception:
                                pass
                        removed = True
                        try:
                            p.mkdir(parents=True, exist_ok=True)
                        except Exception:
                            pass
                except Exception:
                    pass

            # lascia sempre esistere tmp
            try:
                root = Path(__file__).resolve().parents[3] / "tmp"
                root.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

            if removed:
                try:
                    self._log("[TMP] Pulizia contenuto temporaneo completata.")
                except Exception:
                    pass
        except Exception:
            pass

    def _bind_temp_cleanup_buttons(self) -> None:
        try:
            for b in self.findChildren(QtWidgets.QAbstractButton):
                try:
                    txt = (b.text() or "").strip().lower().replace("&", "")
                except Exception:
                    txt = ""
                if txt in ("annulla", "cancel", "stop"):
                    try:
                        b.clicked.connect(self._cleanup_temp_artifacts)
                    except Exception:
                        pass
        except Exception:
            pass

    def closeEvent(self, event) -> None:
        try:
            self._cleanup_temp_artifacts()
        except Exception:
            pass
        try:
            super().closeEvent(event)
        except Exception:
            try:
                event.accept()
            except Exception:
                pass

    def _open_path_in_vlc(self, p: Path) -> None:
        try:
            import shutil as _shutil
            vlc = _shutil.which("vlc")
            if vlc:
                try:
                    if QProcess.startDetached(vlc, [str(p)]):
                        return
                except Exception:
                    pass
            try:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))
            except Exception as e:
                try:
                    self._log(f"[WARN] Apri preview: {e}")
                except Exception:
                    pass
        except Exception:
            pass



    def _run_preview_now(self) -> None:
        mkv = self._pick_target_mkv()
        if not mkv:
            QMessageBox.information(self, L("Info"), L("Seleziona un file MKV nella lista a sinistra per il Preview."))
            return

        if not getattr(self._tc, "mkvmerge", None):
            QMessageBox.information(self, L("Info"), L("mkvmerge non trovato (installa mkvtoolnix)."))
            return

        row = self.tbl_tracks.currentRow()
        if row < 0:
            QMessageBox.information(self, L("Info"), L("Seleziona una traccia AUDIO o SUBTITLE nella tab Tracce per il Preview."))
            return

        current = self._current_selected_entry()
        if current is None:
            QMessageBox.information(self, L("Info"), L("Riga selezionata non valida per il Preview."))
            return

        kind = (getattr(current, "kind", "") or "").strip().lower()
        if kind not in ("audio", "subtitles"):
            QMessageBox.information(self, L("Info"), L("Per il Preview devi selezionare una traccia AUDIO o SUBTITLE."))
            return

        try:
            mi = probe_mkv(mkv, self._tc)
            v_tid = 0
            for t in (mi.tracks or []):
                if (getattr(t, "type", "") or "").lower() == "video":
                    v_tid = int(getattr(t, "tid", 0) or 0)
                    break
        except Exception:
            v_tid = 0

        sel_audio = None
        sel_sub = None

        if kind == "audio":
            sel_audio = current
        else:
            sel_sub = current
            try:
                sel_audio = self._first_included_entry("audio", src=mkv)
            except Exception:
                sel_audio = None

        if sel_audio is None and sel_sub is None:
            QMessageBox.information(self, L("Info"), L("Nessuna traccia adatta per il Preview."))
            return

        try:
            from hevc_gui.mkv_suite.core.preview_builder import project_preview_dir, default_preview_output, build_preview_cmd
        except Exception:
            from ..core.preview_builder import project_preview_dir, default_preview_output, build_preview_cmd  # type: ignore

        project_root = Path(__file__).resolve().parents[3]
        preview_dir = project_preview_dir(project_root)

        a_tid = int(getattr(sel_audio, "tid", 0)) if sel_audio is not None else None
        a_delay = self._get_delay_for_key(self._entry_sync_key(sel_audio)) if sel_audio is not None else 0

        external_sub = None
        s_tid = None
        s_delay = 0

        if sel_sub is not None:
            s_delay = self._get_delay_for_key(self._entry_sync_key(sel_sub))

            if bool(getattr(sel_sub, "is_mkv", False)):
                # subtitle interno
                if self._subtitle_entry_supports_drift(sel_sub) and len(self._subtitle_drift_points_for_entry(sel_sub)) >= 2:
                    try:
                        drift_dir = preview_dir / "subtitle_drift"
                        external_sub = self._render_drifted_subtitle_for_entry(sel_sub, drift_dir)
                    except Exception as ex:
                        QMessageBox.warning(self, L("Errore"), L("Drift subtitle non applicabile: {ex}").format(ex=ex))
                        return
                    if external_sub is None:
                        QMessageBox.warning(self, L("Errore"), L("Impossibile creare il subtitle driftato per il Preview."))
                        return
                else:
                    # nessun drift applicato: usa la traccia interna normale
                    s_tid = int(getattr(sel_sub, "tid", 0))
            else:
                # subtitle esterno
                if self._subtitle_entry_supports_drift(sel_sub) and len(self._subtitle_drift_points_for_entry(sel_sub)) >= 2:
                    try:
                        drift_dir = preview_dir / "subtitle_drift"
                        external_sub = self._render_drifted_subtitle_for_entry(sel_sub, drift_dir)
                    except Exception as ex:
                        QMessageBox.warning(self, L("Errore"), L("Drift subtitle non applicabile: {ex}").format(ex=ex))
                        return
                    if external_sub is None:
                        external_sub = Path(getattr(sel_sub, "src"))
                else:
                    external_sub = Path(getattr(sel_sub, "src"))

        out_file = default_preview_output(
            preview_dir=preview_dir,
            src=mkv,
            audio_tid=a_tid,
            subtitle_tid=s_tid if external_sub is None else None,
            audio_delay_ms=int(a_delay),
            subtitle_delay_ms=int(s_delay),
        )

        cmd = build_preview_cmd(
            mkvmerge_bin=str(self._tc.mkvmerge),
            src=mkv,
            out_file=out_file,
            video_tid=v_tid,
            audio_tid=a_tid,
            subtitle_tid=s_tid,
            audio_delay_ms=int(a_delay),
            subtitle_delay_ms=int(s_delay),
            external_subtitle_file=external_sub,
        )

        self._preview_open_path = str(out_file)
        self._log(f"[PREVIEW] Creazione: {out_file}")
        self._queue_start([(cmd, "preview", False)], done_msg=L("[OK] Preview creato: {out_file}").format(out_file=out_file))

    def _run_autosync_now(self) -> None:
        if getattr(self, "_analyze_proc", None) is not None:
            try:
                self._log("[INFO] Analisi già in corso.")
            except Exception:
                pass
            return

        if getattr(self, "_autosync_running", False):
            try:
                self._log("[INFO] Auto-sync già in corso.")
            except Exception:
                pass
            return

        sources = self._autosync_candidate_sources()
        if not sources:
            try:
                self._log("[WARN] Nessun file MKV adatto per Analizza.")
            except Exception:
                pass
            return

        try:
            self.chk_autosync.blockSignals(True)
            self.chk_autosync.setChecked(True)
        finally:
            try:
                self.chk_autosync.blockSignals(False)
            except Exception:
                pass

        try:
            self._refresh_delay_ui()
        except Exception:
            pass

        self._analyze_queue = list(sources)

        try:
            self._log("[INFO] Avvio analisi contenuto…")
        except Exception:
            pass

        QTimer.singleShot(0, self._start_next_content_analysis)


    def _start_next_content_analysis(self) -> None:
        if not getattr(self, "_analyze_queue", None):
            self._analyze_proc = None
            self._analyze_current_src = None
            try:
                self._autosync_busy_end()
            except Exception:
                pass
            try:
                self._refresh_delay_ui()
            except Exception:
                pass
            try:
                self._log("[OK] Analisi contenuto completata.")
            except Exception:
                pass
            return

        src_path = self._analyze_queue.pop(0)
        self._analyze_current_src = src_path

        try:
            mkvmerge_bin = str(getattr(self._tc, "mkvmerge", "") or "")
        except Exception:
            mkvmerge_bin = ""
        ffmpeg_bin = self._detect_ffmpeg_bin()

        if not mkvmerge_bin or not ffmpeg_bin:
            try:
                self._log("[WARN] Analizza non disponibile: mkvmerge o ffmpeg mancanti.")
            except Exception:
                pass
            self._start_next_content_analysis()
            return

        repo_root = Path(__file__).resolve().parents[3]

        code = (
            "import json, sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "from hevc_gui.mkv_suite.core.auto_sync_content import suggest_content_sync_ms\n"
            "res = suggest_content_sync_ms(\n"
            "    mkvmerge_bin=sys.argv[2],\n"
            "    ffmpeg_bin=sys.argv[3],\n"
            "    src_path=sys.argv[4],\n"
            "    analyze_seconds=600,\n"
            "    noise_db=-35.0,\n"
            "    silence_d=0.20,\n"
            "    black_d=0.20,\n"
            "    black_pic_th=0.98,\n"
            "    max_abs_ms=5000,\n"
            ")\n"
            "print(json.dumps(res))\n"
        )

        proc = QProcess(self)
        proc.setProgram("python3")
        proc.setArguments(["-c", code, str(repo_root), str(mkvmerge_bin), str(ffmpeg_bin), str(src_path)])
        proc.setWorkingDirectory(str(repo_root))

        try:
            self._autosync_busy_begin()
            self.progress.setFormat(L("Analisi contenuto in corso… %p%"))
        except Exception:
            pass

        try:
            self._log(f"[INFO] Analisi contenuto: {Path(src_path).name}")
        except Exception:
            pass

        proc.finished.connect(self._on_content_analysis_finished)
        proc.readyReadStandardError.connect(self._on_content_analysis_stderr)
        self._analyze_proc = proc
        proc.start()

    def _on_content_analysis_stderr(self) -> None:
        proc = getattr(self, "_analyze_proc", None)
        if not proc:
            return
        try:
            data = bytes(proc.readAllStandardError()).decode("utf-8", errors="replace").strip()
        except Exception:
            data = ""
        if not data:
            return
        for line in data.splitlines():
            line = line.strip()
            if line:
                try:
                    self._log(f"[ANALYZE] {line}")
                except Exception:
                    pass

    def _on_content_analysis_finished(self, exitCode: int, exitStatus) -> None:
        proc = getattr(self, "_analyze_proc", None)
        src_path = getattr(self, "_analyze_current_src", None)

        out_txt = ""
        err_txt = ""
        if proc is not None:
            try:
                out_txt = bytes(proc.readAllStandardOutput()).decode("utf-8", errors="replace").strip()
            except Exception:
                out_txt = ""
            try:
                err_txt = bytes(proc.readAllStandardError()).decode("utf-8", errors="replace").strip()
            except Exception:
                err_txt = ""

        if src_path is not None:
            tok = self._sync_source_token(str(src_path))
            try:
                import json
                if int(exitCode) == 0 and out_txt:
                    res = json.loads(out_txt)
                    old_keys = [k for k in list(self._audio_sync_auto_ms.keys()) if k[0] == tok]
                    for k in old_keys:
                        self._audio_sync_auto_ms.pop(k, None)

                    parsed = {}
                    for tid, delay in (res or {}).items():
                        tid_i = int(tid)
                        delay_i = int(delay)
                        self._audio_sync_auto_ms[(tok, str(tid_i))] = delay_i
                        parsed[tid_i] = delay_i

                    self._audio_sync_auto_done_sources.add(tok)

                    if parsed:
                        pretty = ", ".join(f"{tid}:{delay}ms" for tid, delay in sorted(parsed.items()))
                        self._log(f"[ANALYZE] {Path(src_path).name}: {pretty}")
                    else:
                        self._log(f"[ANALYZE] {Path(src_path).name}: nessun sync contenuto affidabile rilevato.")
                else:
                    msg = err_txt or out_txt or f"rc={exitCode}"
                    self._log(f"[WARN] Analisi contenuto fallita su {Path(src_path).name}: {msg}")
            except Exception as e:
                try:
                    self._log(f"[WARN] Risultato analisi non valido su {Path(src_path).name}: {e}")
                except Exception:
                    pass

        try:
            if proc is not None:
                proc.deleteLater()
        except Exception:
            pass

        self._analyze_proc = None
        self._analyze_current_src = None
        self._start_next_content_analysis()



    def _on_delay_value_changed(self, value: int) -> None:
        if getattr(self, "_delay_ui_guard", False):
            return

        key = self._current_sync_key()
        if not key:
            return

        tok, tid, kind = key
        kind = (kind or "").strip().lower()
        value = int(value)

        if kind == "audio":
            if self.chk_autosync.isChecked():
                return

            if value == 0:
                self._audio_sync_manual_ms.pop((tok, tid), None)
                self._audio_sync_manual_ms.pop((tok, tid, "audio"), None)
            else:
                self._audio_sync_manual_ms[(tok, tid)] = value
                self._audio_sync_manual_ms[(tok, tid, "audio")] = value

        elif kind == "subtitles":
            if value == 0:
                self._subtitle_sync_manual_ms.pop((tok, tid, "subtitles"), None)
            else:
                self._subtitle_sync_manual_ms[(tok, tid, "subtitles")] = value

        self._refresh_delay_ui()

    def _active_audio_sync_rows(self):
        out = {}
        for row in range(self.tbl_tracks.rowCount()):
            if not self._row_is_audio(row):
                continue
            if not self._row_include_checked(row):
                continue

            key = self._row_sync_key(row)
            if not key:
                continue

            delay = self._get_delay_for_key(key)
            if not delay:
                continue

            src_text = self._row_source_text(row)
            src_norm = self._sync_source_token(src_text)
            tid = key[1]

            names = set()
            if src_norm:
                names.add(src_norm)
            if src_text:
                try:
                    names.add(Path(src_text).name)
                except Exception:
                    pass

            for name in names:
                if not name:
                    continue
                out.setdefault(name, []).append((str(tid), int(delay)))

        return out

    def _apply_audio_sync_to_mkvmerge_cmd(self, cmd: List[str]) -> List[str]:
        try:
            sync_map = self._active_audio_sync_rows()
            if not sync_map:
                return cmd

            out = []
            matched = set()

            for tok in cmd:
                tok_norm = self._sync_source_token(tok)
                try:
                    tok_base = Path(tok).name
                except Exception:
                    tok_base = tok

                pairs = sync_map.get(tok_norm) or sync_map.get(tok_base)
                if pairs:
                    for tid, delay in pairs:
                        out.extend(["--sync", f"{tid}:{delay}"])
                        try:
                            self._log(f"[SYNC] traccia {tid} -> {delay} ms su {tok_base}")
                        except Exception:
                            pass
                    matched.add(tok_norm or tok_base)

                out.append(tok)

            return out

        except Exception as e:
            try:
                self._log(f"[WARN] Sync audio non applicato: {e}")
            except Exception:
                pass
            return cmd

    def _item(self, text: str, editable: bool) -> QTableWidgetItem:
        it = QTableWidgetItem(text)
        if not editable:
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
        return it

    def _on_track_item_changed(self, it: QTableWidgetItem) -> None:
        if self._ui_lock:
            return
        r = it.row()
        c = it.column()
        if r < 0 or r >= len(self._entries):
            return
        e = self._entries[r]
        if c == self.COL_INC:
            e.include = (it.checkState() == Qt.Checked)
        elif c == self.COL_LANG:
            e.lang = self._norm_lang(it.text())
        elif c == self.COL_NAME:
            e.name = (it.text() or "").strip()
        elif c == self.COL_DEF:
            e.default = (it.checkState() == Qt.Checked)
        elif c == self.COL_FOR:
            e.forced = (it.checkState() == Qt.Checked)



    def _mkv_suite_sub_editor_sync_job_dir(self, editor) -> None:
        try:
            job = getattr(editor, "last_job_dir", None)
            if not job:
                return
            from pathlib import Path as _P
            p = _P(job)
            self._job_dir = p
            self._out_dir = p
            try:
                self.ed_outdir.setText(str(p))
            except Exception:
                pass
        except Exception:
            pass

    def _mkv_suite_apply_sub_edit_override(self, row: int, new_path) -> None:
        try:
            r = int(row)
        except Exception:
            return
        if r < 0 or r >= len(getattr(self, "_entries", [])):
            return

        e = self._entries[r]
        kind = (getattr(e, "kind", "") or "").strip().lower()
        if kind != "subtitles":
            return

        from pathlib import Path as _P
        p = _P(new_path).expanduser()

        # Regola Loris: mai sovrascrivere l'estratto originale; la riga diventa il *_edit.*
        e.src = p
        e.src_label = p.name
        e.is_mkv = False
        e.tid = 0

        old_lock = getattr(self, "_ui_lock", False)
        self._ui_lock = True
        try:
            it_src = self.tbl_tracks.item(r, self.COL_SRC)
            if it_src is not None:
                it_src.setText(p.name)
            it_id = self.tbl_tracks.item(r, self.COL_ID)
            if it_id is not None:
                it_id.setText(L("0"))
        finally:
            self._ui_lock = old_lock

        try:
            self._log(f"[SUB] Riga subtitle ora usa file edit: {p.name}")
        except Exception:
            pass

    def _mkv_suite_on_tracks_cell_double_clicked(self, row: int, _col: int) -> None:
        # Doppio click su qualsiasi cella della riga subtitles -> gnome-subtitles
        if getattr(self, "_ui_lock", False):
            return
        if getattr(self, "_busy", False):
            return
        try:
            r = int(row)
        except Exception:
            return
        if r < 0 or r >= len(getattr(self, "_entries", [])):
            return

        e = self._entries[r]
        kind = (getattr(e, "kind", "") or "").strip().lower()
        if kind != "subtitles":
            return

        # Regola non distruttiva: SEMPRE overwrite=False -> si lavora su *_edit.*
        overwrite = False

        editor = getattr(self, "_mkv_suite_sub_editor", None)
        if editor is None:
            mkvextract_bin = "mkvextract"
            try:
                mkvextract_bin = getattr(self._tc, "mkvextract", None) or "mkvextract"
            except Exception:
                pass
            editor = GnomeSubtitlesEditor(self, mkvextract_bin=mkvextract_bin)
            self._mkv_suite_sub_editor = editor

        try:
            jobp = getattr(self, "_job_dir", None) or getattr(self, "_out_dir", None)
            job_hint = str(jobp) if jobp else ""
        except Exception:
            job_hint = ""

        try:
            from pathlib import Path as _P

            if bool(getattr(e, "is_mkv", False)):
                src_name = _P(e.src).name
                tid0 = int(getattr(e, "tid", 0))
                editor.edit_internal_track(
                    source_path=str(e.src),
                    track_id=tid0,
                    codec_id=str(getattr(e, "codec_id", "") or ""),
                    job_dir_hint=job_hint,
                    overwrite=overwrite,
                )
                self._mkv_suite_sub_editor_sync_job_dir(editor)
                tgt = getattr(editor, "last_opened_target", None)
                if tgt:
                    self._mkv_suite_apply_sub_edit_override(r, tgt)
                self._log(f"[SUB] Editor subs interno: {src_name} T{tid0}")
            else:
                src_name = _P(e.src).name
                editor.edit_external_file(
                    subtitle_path=str(e.src),
                    job_dir_hint=job_hint,
                    overwrite=overwrite,
                )
                self._mkv_suite_sub_editor_sync_job_dir(editor)
                tgt = getattr(editor, "last_opened_target", None)
                if tgt:
                    self._mkv_suite_apply_sub_edit_override(r, tgt)
                self._log(f"[SUB] Editor subs esterno: {src_name}")

        except Exception as ex:
            try:
                self._log(f"[ERR] Apertura editor sottotitoli: {ex}")
            except Exception:
                pass
            try:
                QMessageBox.warning(self, L("Errore"), L("Impossibile aprire l'editor sottotitoli:") + "\n" + str(ex))
            except Exception:
                pass



    def open_cut_tool(self) -> None:
        try:
            it = self.list_files.currentItem()
            src = None

            if it is not None and (it.text() or "").strip():
                src = Path(it.text()).expanduser()
            elif self.list_files.count() > 0:
                txt = (self.list_files.item(0).text() or "").strip()
                if txt:
                    src = Path(txt).expanduser()

            if src is not None and not src.exists():
                QtWidgets.QMessageBox.warning(
                    self,
                    L("Errore"),
                    L("File sorgente non trovato.") + "\n" + str(src),
                )
                return

            try:
                from hevc_gui.mkv_suite.ui.cut_dialog import CutDialog
            except Exception as e:
                QtWidgets.QMessageBox.critical(
                    self,
                    L("Errore"),
                    L("Modulo Taglio non disponibile:") + "\n" + str(e),
                )
                return

            dlg = CutDialog(src, self)
            dlg.exec_()

        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                L("Errore"),
                L("Impossibile aprire lo strumento di taglio:") + "\n" + str(e),
            )
    def _tooltip_applica_tag(self) -> str:
        return L(
            "Scrive subito nel file MKV originale i metadati (titolo, nomi tracce, lingue, default/forced). "
            "Non fa remux e non crea un nuovo file."
        )

    def _apply_all_tooltips(self) -> None:
        # Tooltip espliciti (traducibili) per i controlli principali
        explicit = {
            "btn_apply_tags": self._tooltip_applica_tag(),
            "btn_remux": L("Premi 'Applica Tag' per scrivere nel file originale, oppure 'Crea MKV' per creare un nuovo file."),
            "btn_extract": L("Estrae le tracce selezionate nella cartella extract/."),
            "btn_cut": L("Apre lo strumento di taglio video sul file selezionato."),
            "btn_stop": L("Interrompe l'operazione in corso."),
            "btn_add": L("Aggiunge file sorgenti alla lista."),
            "btn_remove": L("Rimuove il file selezionato dalla lista (non dal disco)."),
            "btn_open_outdir": L("Apre la cartella output della sessione."),
            "btn_apply_tag": self._tooltip_applica_tag(),  # fallback nome alternativo
        }
        for attr, tip in explicit.items():
            w = getattr(self, attr, None)
            if w is not None:
                try:
                    w.setToolTip(tip)
                except Exception:
                    pass

        # Tooltip base a tutti i widget senza tooltip (fallback automatico)
        try:
            from PyQt5.QtWidgets import QWidget, QAbstractButton, QLineEdit, QComboBox, QAbstractSpinBox, QTableWidget
        except Exception:
            return

        for w in self.findChildren(QWidget):
            try:
                if w.toolTip():
                    continue
            except Exception:
                continue

            # Pulsanti / checkbox / radio: usa il testo visibile (già traducibile dalla UI)
            if isinstance(w, QAbstractButton):
                try:
                    t = (w.text() or "").strip()
                    if t:
                        w.setToolTip(t)
                        continue
                except Exception:
                    pass

            # Input testo
            if isinstance(w, QLineEdit):
                try:
                    ph = (w.placeholderText() or "").strip()
                    if ph:
                        w.setToolTip(ph)
                    else:
                        w.setToolTip(L("Campo di testo."))
                    continue
                except Exception:
                    pass

            # Combo
            if isinstance(w, QComboBox):
                try:
                    w.setToolTip(L("Seleziona un valore dall'elenco."))
                    continue
                except Exception:
                    pass

            # Spin
            if isinstance(w, QAbstractSpinBox):
                try:
                    w.setToolTip(L("Imposta un valore."))
                    continue
                except Exception:
                    pass

            # Tabelle
            if isinstance(w, QTableWidget):
                try:
                    w.setToolTip(L("Tabella dati. Doppio click per modifiche dove supportato."))
                    continue
                except Exception:
                    pass

            # Fallback leggero: objectName se utile
            try:
                name = (w.objectName() or "").strip()
                if name:
                    w.setToolTip(name)
            except Exception:
                pass

    # ---------- QProcess queue runner ----------
    def _queue_start(self, queue: List[Tuple[List[str], str, bool]], done_msg: str) -> None:
        if self._busy:
            return
        self._queue = list(queue)
        self._queue_done_msg = done_msg
        self.progress.setValue(0)
        # PROGRESSBAR_ZERO_CHUNK_SET
        try:
            self.progress.setProperty('zero', (self.progress.value() <= 0))
            self.progress.style().unpolish(self.progress)
            self.progress.style().polish(self.progress)
            self.progress.update()
        except Exception:
            pass
        self._set_busy(True)
        self._queue_next()

    def _queue_next(self) -> None:
        if not self._queue:
            self.progress.setValue(0)
            # PROGRESSBAR_ZERO_CHUNK_SET
            try:
                self.progress.setProperty('zero', (self.progress.value() <= 0))
                self.progress.style().unpolish(self.progress)
                self.progress.style().polish(self.progress)
                self.progress.update()
            except Exception:
                pass
            self._set_busy(False)
            if self._queue_done_msg:
                self._log(self._queue_done_msg)
            try:
                _p = getattr(self, '_preview_open_path', None)
                if _p:
                    self._preview_open_path = None
                    self._open_path_in_vlc(Path(_p))
            except Exception:
                try:
                    self._preview_open_path = None
                except Exception:
                    pass
            return

        cmd, label, allow_fail = self._queue.pop(0)
        self._cur_allow_fail = bool(allow_fail)
        self._start_process(cmd, label)

    def _start_process(self, cmd: List[str], label: str) -> None:
        # reset progress for this step
        self.progress.setValue(0)
        # PROGRESSBAR_ZERO_CHUNK_SET
        try:
            self.progress.setProperty('zero', (self.progress.value() <= 0))
            self.progress.style().unpolish(self.progress)
            self.progress.style().polish(self.progress)
            self.progress.update()
        except Exception:
            pass
        self.progress.setToolTip(label)

        if self._proc is not None:
            try:
                self._proc.kill()
            except Exception:
                pass
            self._proc = None

        self._proc_buf = ""
        p = QProcess(self)
        self._proc = p
        p.setProcessChannelMode(QProcess.MergedChannels)

        p.readyReadStandardOutput.connect(self._proc_read)
        p.finished.connect(self._proc_finished)

        self._log("[RUN] " + " ".join(cmd))

        program = cmd[0]
        args = cmd[1:]
        p.start(program, args)

    def _proc_read(self) -> None:
        if not self._proc:
            return
        data = bytes(self._proc.readAllStandardOutput()).decode("utf-8", "replace")
        data = data.replace("\r", "\n")
        if not data:
            return
        self._proc_buf += data
        while "\n" in self._proc_buf:
            line, self._proc_buf = self._proc_buf.split("\n", 1)
            line = line.rstrip("\r")
            if line:
                self._log(line)
                m = self._RX_PROGRESS.search(line)
                if m:
                    try:
                        v = int(m.group(1))
                        v = max(0, min(100, v))
                        self.progress.setValue(v)
                        # PROGRESSBAR_ZERO_CHUNK_SET
                        try:
                            self.progress.setProperty('zero', (self.progress.value() <= 0))
                            self.progress.style().unpolish(self.progress)
                            self.progress.style().polish(self.progress)
                            self.progress.update()
                        except Exception:
                            pass
                    except Exception:
                        pass

    def _proc_finished(self, exitCode: int, _exitStatus) -> None:
        # flush last buffered line
        if self._proc_buf.strip():
            line = self._proc_buf.strip()
            line = line.replace('\r', '\n')
            self._log(line)
            m = self._RX_PROGRESS.search(line)
            if m:
                try:
                    v = int(m.group(1))
                    v = max(0, min(100, v))
                    self.progress.setValue(v)
                    # PROGRESSBAR_ZERO_CHUNK_SET
                    try:
                        self.progress.setProperty('zero', (self.progress.value() <= 0))
                        self.progress.style().unpolish(self.progress)
                        self.progress.style().polish(self.progress)
                        self.progress.update()
                    except Exception:
                        pass
                except Exception:
                    pass
        self._proc_buf = ""

        rc = int(exitCode)
        if rc != 0 and not self._cur_allow_fail:
            self._log(f"[ERR] Comando fallito (rc={rc}).")
            self.progress.setValue(0)
            # PROGRESSBAR_ZERO_CHUNK_SET
            try:
                self.progress.setProperty('zero', (self.progress.value() <= 0))
                self.progress.style().unpolish(self.progress)
                self.progress.style().polish(self.progress)
                self.progress.update()
            except Exception:
                pass
            self._set_busy(False)
            try:
                self._preview_open_path = None
            except Exception:
                pass
            try:
                self._preview_open_path = None
            except Exception:
                pass
            self._queue.clear()
            return

        # next
        self._queue_next()

    # ---------- operations ----------
    def _pick_target_mkv(self) -> Optional[Path]:
        it = self.list_files.currentItem()
        if it:
            p = Path(it.text())
            if p.suffix.lower() == ".mkv" and p.exists():
                return p
        for i in range(self.list_files.count()):
            p = Path(self.list_files.item(i).text())
            if p.suffix.lower() == ".mkv" and p.exists():
                return p
        return None

    def apply_tags(self) -> None:
        mkv = self._pick_target_mkv()
        if not mkv:
            QMessageBox.information(self, L("Info"), L("Seleziona (o aggiungi) almeno un file MKV per Applica Tag."))
            return
        title = self._effective_title().strip()
        if not title:
            QMessageBox.information(self, L("Info"), L("Inserisci almeno un Titolo (e opzionalmente l’Anno)."))
            return
        self._set_busy(True)
        try:
            mi = probe_mkv(mkv, self._tc)
            apply_tags_in_place(mi, self._tc, title=title)
            self._log("[OK] Tag applicati (in-place).")
        except Exception as e:
            self._log(f"[ERR] Applica Tag: {e}")
        finally:
            self._set_busy(False)

    def extract_selected(self) -> None:
        # SEMPRE chiedi cartella output
        if getattr(self, '_out_dir', None) is None and not self.on_choose_outdir():
            self._log("[INFO] Estrai annullato: cartella output non scelta.")
            return

        mkv = self._pick_target_mkv()
        if not mkv:
            QMessageBox.information(self, L("Info"), L("Seleziona (o aggiungi) un file MKV per Estrai."))
            return

        title = self._effective_title().strip()
        base = (title or mkv.stem).strip() or mkv.stem

        def safe_folder(s: str) -> str:
            s = (s or "").strip().replace("/", "_").replace("\\", "_").replace(":", "_")
            s = re.sub(r"\s+", " ", s).strip()
            return s or "extract"

        job = self._job_dir
        if not job:
            job = self._out_dir
            self._job_dir = job
        out_root = job / "extract"
        audio_dir = out_root / "audio"
        subs_dir = out_root / "subs"
        out_root.mkdir(parents=True, exist_ok=True)
        audio_dir.mkdir(parents=True, exist_ok=True)
        subs_dir.mkdir(parents=True, exist_ok=True)

        # track selection (from entries)
        mkv_entries = [e for e in self._entries if e.is_mkv and e.src == mkv and e.include]
        if not mkv_entries:
            # fallback: everything from probe
            mi_tmp = probe_mkv(mkv, self._tc)
            mkv_entries = []
            for t in mi_tmp.tracks:
                mkv_entries.append(RemuxEntry(
                    src=mkv, src_label=mkv.name, kind=t.type, tid=t.tid, is_mkv=True, include=True,
                    lang=self._norm_lang(t.language or "und"),
                    name=(t.name or "").strip(),
                    default=bool(t.flag_default) if t.flag_default is not None else False,
                    forced=bool(t.flag_forced) if t.flag_forced is not None else False,
                    codec_id=t.codec_id or ""
                ))

        v_ids = sorted({e.tid for e in mkv_entries if (e.kind or "").lower() == "video"})
        a_tracks = [e for e in mkv_entries if (e.kind or "").lower() == "audio"]
        s_tracks = [e for e in mkv_entries if (e.kind or "").lower() == "subtitles"]

        queue: List[Tuple[List[str], str, bool]] = []

        # 1) video => <input>_e.mkv (mkvmerge)
        if v_ids and self._tc.mkvmerge:
            v_base = self._safe_job_name(base) or mkv.stem
            v_out = out_root / f"{v_base}_e.mkv"
            cmd = [self._tc.mkvmerge, "-o", str(v_out), "--no-audio", "--no-subtitles", "--no-buttons",
                   "--video-tracks", ",".join(str(x) for x in v_ids), str(mkv)]
            if title:
                cmd.insert(3, "--title")
                cmd.insert(4, title)
            queue.append((cmd, "video", False))

        # 2) mkvextract tracks (audio+subs) => formato naturale + _e
        if self._tc.mkvextract:
            mi = probe_mkv(mkv, self._tc)
            tid_map = {t.tid: t for t in mi.tracks}

            specs: List[str] = []
            # audio
            for e in a_tracks:
                t = tid_map.get(e.tid)
                if not t:
                    continue
                ext = self._ext_for(t.codec_id or "", "audio")
                nm = self._safe_slug(e.name or self._lang_label(e.lang))
                fn = f"{self._safe_slug(base)}_T{e.tid}_audio_{self._norm_lang(e.lang)}_{nm}_e.{ext}"
                specs.append(f"{e.tid}:{str(audio_dir / fn)}")

            # subs
            for e in s_tracks:
                t = tid_map.get(e.tid)
                if not t:
                    continue
                ext = self._ext_for(t.codec_id or "", "subtitles")
                nm = self._safe_slug(e.name or f"{self._lang_label(e.lang)} ({'forced' if e.forced else 'normal'})")
                fn = f"{self._safe_slug(base)}_T{e.tid}_sub_{self._norm_lang(e.lang)}_{nm}_e.{ext}"
                specs.append(f"{e.tid}:{str(subs_dir / fn)}")

            if specs:
                cmd = [self._tc.mkvextract, str(mkv), "tracks"] + specs
                queue.append((cmd, "tracks", False))

        # 3) chapters => chapters_e.xml (best effort)
        ch_xml = (self.ed_chapters.text() or "").strip()
        # prefer: if user selected chapters file, we already have it; for extract we take from MKV itself:
        if self._tc.mkvextract:
            chap_out = out_root / "chapters_e.xml"
            cmd = [self._tc.mkvextract, str(mkv), "chapters", str(chap_out)]
            # allow_fail=True (mkv without chapters)
            queue.append((cmd, "chapters", True))

        if not queue:
            self._log("[INFO] Nulla da estrarre.")
            return

        self._queue_start(queue, done_msg=L("[OK] Estrazione completata."))


    def _normalize_mkvmerge_cmd(self, cmd, out_file=None):
        try:
            cmd = list(cmd or [])
            if len(cmd) < 4:
                return cmd
            if str(cmd[0]).endswith("mkvmerge") is False and "mkvmerge" not in str(cmd[0]):
                return cmd
            if cmd[1] != "-o":
                return cmd

            # caso sano: subito dopo -o c'è l'output
            if len(cmd) >= 3 and not str(cmd[2]).startswith("-"):
                return cmd

            # caso rotto: -o --sync X:Y OUTPUT ...
            fixed = [cmd[0], "-o", str(out_file)] if out_file is not None else [cmd[0], "-o"]

            i = 2
            early_sync = []
            while i + 1 < len(cmd) and cmd[i] == "--sync":
                early_sync.extend([cmd[i], cmd[i + 1]])
                i += 2

            rest = cmd[i:]

            # se il primo token del resto è proprio l'out_file, non duplicarlo
            if out_file is not None and rest and str(rest[0]) == str(out_file):
                rest = rest[1:]

            # prova a lasciare l'input come ultimo argomento
            if rest:
                src_tok = rest[-1]
                fixed.extend(rest[:-1])
                fixed.extend(early_sync)
                fixed.append(src_tok)
            else:
                fixed.extend(early_sync)

            try:
                self._log("[FIX] Normalizzato ordine argomenti mkvmerge per --sync.")
            except Exception:
                pass
            return fixed
        except Exception:
            return cmd


    def _project_tmp_root(self) -> Path:
        p = Path(__file__).resolve().parents[3] / "tmp"
        p.mkdir(parents=True, exist_ok=True)
        return p


    def _build_external_subtitle_adjustment_map(self):
        out = {"external": {}, "internal_drift": []}
        try:
            drift_dir = self._project_tmp_root() / "subtitle_drift_remux"
            drift_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            drift_dir = None

        for e in getattr(self, "_entries", []):
            try:
                if not bool(getattr(e, "include", False)):
                    continue
                if (getattr(e, "kind", "") or "").strip().lower() != "subtitles":
                    continue

                try:
                    delay = int(self._get_delay_for_key(self._entry_sync_key(e)) or 0)
                except Exception:
                    delay = 0

                # subtitle esterni
                if not bool(getattr(e, "is_mkv", False)):
                    src_path = Path(getattr(e, "src"))
                    use_path = src_path

                    try:
                        pts = self._subtitle_drift_points_for_entry(e)
                    except Exception:
                        pts = []

                    if drift_dir is not None and self._subtitle_entry_supports_drift(e) and len(pts) >= 2:
                        try:
                            rendered = self._render_drifted_subtitle_for_entry(e, drift_dir)
                            if rendered is not None:
                                use_path = Path(rendered)
                                try:
                                    self._log(f"[DRIFT] Uso subtitle retimato per remux: {use_path}")
                                except Exception:
                                    pass
                        except Exception as ex:
                            try:
                                self._log(f"[WARN] Drift subtitle non applicato nel remux: {ex}")
                            except Exception:
                                pass

                    out["external"][str(src_path)] = {
                        "path": str(use_path),
                        "delay": int(delay),
                    }
                    continue

                # subtitle interni testuali con drift
                try:
                    pts = self._subtitle_drift_points_for_entry(e)
                except Exception:
                    pts = []

                if drift_dir is not None and self._subtitle_entry_supports_drift(e) and len(pts) >= 2:
                    try:
                        rendered = self._render_drifted_subtitle_for_entry(e, drift_dir)
                        if rendered is not None:
                            try:
                                self._log(f"[DRIFT] Uso subtitle interno retimato per remux: {rendered}")
                            except Exception:
                                pass
                            out["internal_drift"].append({
                                "src": str(Path(getattr(e, "src"))),
                                "tid": int(getattr(e, "tid", 0)),
                                "path": str(rendered),
                                "delay": int(delay),
                                "lang": str(getattr(e, "lang", "") or "und"),
                                "name": str(getattr(e, "name", "") or ""),
                                "default": bool(getattr(e, "default", False)),
                                "forced": bool(getattr(e, "forced", False)),
                            })
                    except Exception as ex:
                        try:
                            self._log(f"[WARN] Drift subtitle interno non applicato nel remux: {ex}")
                        except Exception:
                            pass

            except Exception:
                continue

        return out


    def _apply_subtitle_adjustments_to_remux_cmd(self, cmd):
        try:
            cmd = list(cmd or [])
            plan = self._build_external_subtitle_adjustment_map()
            external_map = dict(plan.get("external", {}) or {})
            internal_drift = list(plan.get("internal_drift", []) or [])

            # A) sostituisci subtitle esterni originali con eventuali file retimati
            out = []
            for tok in cmd:
                info = external_map.get(str(tok))
                if info is None:
                    out.append(tok)
                    continue

                delay = int(info.get("delay", 0) or 0)
                new_path = str(info.get("path", tok))

                # per subtitle esterni, track id interno è 0
                if delay != 0:
                    if not (len(out) >= 2 and out[-2] == "--sync" and out[-1] == f"0:{delay}"):
                        out.extend(["--sync", f"0:{delay}"])

                out.append(new_path)

            cmd = out

            # B) sostituisci subtitle interni driftati con file esterni temporanei
            if not internal_drift:
                return cmd

            def _remove_tid_from_subtitle_tracks(tokens, src_path_str, tid_to_remove):
                tokens = list(tokens)
                try:
                    src_index = tokens.index(src_path_str)
                except ValueError:
                    return tokens

                sub_idx = -1
                i = 0
                while i < src_index:
                    if tokens[i] == "--subtitle-tracks" and i + 1 < src_index:
                        sub_idx = i
                        i += 2
                        continue
                    i += 1

                if sub_idx < 0:
                    return tokens

                ids = [x for x in str(tokens[sub_idx + 1]).split(",") if x != ""]
                ids = [x for x in ids if x != str(int(tid_to_remove))]

                if ids:
                    tokens[sub_idx + 1] = ",".join(ids)
                else:
                    tokens[sub_idx:sub_idx + 2] = ["--no-subtitles"]

                return tokens

            def _append_external_sub(tokens, item):
                lang = str(item.get("lang", "und") or "und")
                name = str(item.get("name", "") or "")
                default = "yes" if bool(item.get("default", False)) else "no"
                forced = "yes" if bool(item.get("forced", False)) else "no"
                delay = int(item.get("delay", 0) or 0)
                path = str(item.get("path"))

                tokens.extend([
                    "--subtitle-tracks", "0",
                    "--no-video", "--no-audio", "--no-buttons",
                    "--language", f"0:{lang}",
                    "--track-name", f"0:{name}",
                    "--default-track", f"0:{default}",
                    "--forced-track", f"0:{forced}",
                ])
                if delay != 0:
                    tokens.extend(["--sync", f"0:{delay}"])
                tokens.append(path)
                return tokens

            for item in internal_drift:
                src_path_str = str(item.get("src"))
                tid = int(item.get("tid", 0))
                cmd = _remove_tid_from_subtitle_tracks(cmd, src_path_str, tid)
                cmd = _append_external_sub(cmd, item)

            return cmd
        except Exception:
            return cmd

    def remux_selected(self) -> None:
        # SEMPRE chiedi cartella output
        if getattr(self, '_out_dir', None) is None and not self.on_choose_outdir():
            self._log("[INFO] Crea MKV annullato: cartella output non scelta.")
            return

        if not self._tc.mkvmerge:
            self._log("[ERR] mkvmerge non trovato (installa mkvtoolnix).")
            return

        if not self._entries:
            self._log("[INFO] Crea MKV: aggiungi almeno una sorgente.")
            return

        title = self._effective_title().strip()
        base = (title or "output").strip() or "output"
        job = self._job_dir
        if not job:
            job = self._out_dir
            self._job_dir = job
        remux_dir = job / "remux"
        remux_dir.mkdir(parents=True, exist_ok=True)
        out_file = remux_dir / f"{base}.mkv"


        if out_file.exists():
            k = 1
            while True:
                cand = self._out_dir / f"{base} ({k}).mkv"
                if not cand.exists():
                    out_file = cand
                    break
                k += 1

        chapters_path = None
        if self._chapters_override and self._chapters_override.is_file():
            chapters_path = self._chapters_override
        else:
            t = (self.ed_chapters.text() or "").strip()
            if t:
                cp = Path(t)
                if cp.is_file():
                    chapters_path = cp

        # group by src
        by_src: Dict[Path, List[RemuxEntry]] = {}
        for e in self._entries:
            if e.include:
                by_src.setdefault(e.src, []).append(e)

        if not by_src:
            self._log("[INFO] Crea MKV: nessuna traccia spuntata.")
            return

        cmd: List[str] = [self._tc.mkvmerge, "-o", str(out_file)]
        if title:
            cmd += ["--title", title]
        if chapters_path:
            cmd += ["--chapters", str(chapters_path)]

        def src_pri(src: Path) -> int:
            ents = by_src[src]
            if any((x.kind or "").lower() == "video" for x in ents): return 0
            if any((x.kind or "").lower() == "audio" for x in ents): return 1
            if any((x.kind or "").lower() == "subtitles" for x in ents): return 2
            return 3

        for src in sorted(by_src.keys(), key=lambda s: (src_pri(s), s.name.lower())):
            ents = by_src[src]
            suf = src.suffix.lower()

            if suf == ".mkv":
                vids = sorted({x.tid for x in ents if (x.kind or "").lower() == "video"})
                auds = sorted({x.tid for x in ents if (x.kind or "").lower() == "audio"})
                subs = sorted({x.tid for x in ents if (x.kind or "").lower() == "subtitles"})

                cmd += (["--video-tracks", ",".join(str(x) for x in vids)] if vids else ["--no-video"])
                cmd += (["--audio-tracks", ",".join(str(x) for x in auds)] if auds else ["--no-audio"])
                cmd += (["--subtitle-tracks", ",".join(str(x) for x in subs)] if subs else ["--no-subtitles"])
                cmd += ["--no-buttons"]

                for x in ents:
                    tid = x.tid
                    if x.lang:
                        cmd += ["--language", f"{tid}:{self._norm_lang(x.lang)}"]
                    tname = self._vlc_track_name(tid, x, src)
                    if tname:
                        cmd += ["--track-name", f"{tid}:{tname}"]
                    cmd += ["--default-track", f"{tid}:{'yes' if x.default else 'no'}"]
                    cmd += ["--forced-track", f"{tid}:{'yes' if x.forced else 'no'}"]

                if chapters_path:
                    cmd += ["--no-chapters"]
                cmd += [str(src)]
            else:
                # external single file: explicit track selection by type (no bleed)
                x = ents[0]
                tid = 0
                k = (x.kind or "").lower()

                if k == "audio":
                    cmd += ["--audio-tracks", "0", "--no-video", "--no-subtitles", "--no-buttons"]
                elif k == "subtitles":
                    cmd += ["--subtitle-tracks", "0", "--no-video", "--no-audio", "--no-buttons"]
                elif k == "video":
                    cmd += ["--video-tracks", "0", "--no-audio", "--no-subtitles", "--no-buttons"]
                else:
                    # unknown: include all tracks
                    pass

                if x.lang:
                    cmd += ["--language", f"{tid}:{self._norm_lang(x.lang)}"]
                tname = self._vlc_track_name(tid, x, src)
                if tname:
                    cmd += ["--track-name", f"{tid}:{tname}"]
                cmd += ["--default-track", f"{tid}:{'yes' if x.default else 'no'}"]
                cmd += ["--forced-track", f"{tid}:{'yes' if x.forced else 'no'}"]

                cmd += [str(src)]

        cmd = self._apply_audio_sync_to_mkvmerge_cmd(cmd)
        cmd = self._apply_subtitle_adjustments_to_remux_cmd(cmd)
        cmd = self._normalize_mkvmerge_cmd(cmd, out_file=out_file)
        self._queue_start([(cmd, "mkvmerge", False)], done_msg=L("[OK] Rimux creato: {out_file}").format(out_file=out_file))

    def stop_jobs(self) -> None:
        # stop QProcess + clear queue
        try:
            self._preview_open_path = None
        except Exception:
            pass
        try:
            self._preview_open_path = None
        except Exception:
            pass
        self._queue.clear()
        if self._proc and self._proc.state() != QProcess.NotRunning:
            try:
                self._proc.terminate()
            except Exception:
                pass
            QTimer.singleShot(800, lambda: (self._proc.kill() if self._proc and self._proc.state() != QProcess.NotRunning else None))
        self.progress.setValue(0)
        # PROGRESSBAR_ZERO_CHUNK_SET
        try:
            self.progress.setProperty('zero', (self.progress.value() <= 0))
            self.progress.style().unpolish(self.progress)
            self.progress.style().polish(self.progress)
            self.progress.update()
        except Exception:
            pass
        self._set_busy(False)
        self._log("[UI] Stop richiesto.")

    def reset_all(self) -> None:
        if self._busy:
            QMessageBox.information(self, L("Info"), L("Operazione in corso. Premi Stop o attendi."))
            return
        q = QMessageBox.question(
            self, L("Conferma"),
            L("Vuoi annullare e pulire tutto?\n(I dati non salvati andranno persi)"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if q != QMessageBox.Yes:
            return

        self._ui_lock = True
        try:
            self._entries = []
            self._sources = []
            self._chapters_override = None
            self.list_files.clear()
            self.tbl_tracks.setRowCount(0)
            self.ed_chapters.clear()

            self._title.name_user = self._title.name_auto = ""
            self._year.name_user = self._year.name_auto = ""
            self._out_base.name_user = self._out_base.name_auto = ""
            self.ed_title.clear()
            self.ed_year.clear()

            self.log.clear()
            self.progress.setValue(0)
            # PROGRESSBAR_ZERO_CHUNK_SET
            try:
                self.progress.setProperty('zero', (self.progress.value() <= 0))
                self.progress.style().unpolish(self.progress)
                self.progress.style().polish(self.progress)
                self.progress.update()
            except Exception:
                pass
        finally:
            self._ui_lock = False

        self._update_previews()
        self._update_enabled()
        self._log("[UI] Reset completato.")

    def exit_app(self) -> None:
        msg = L("Vuoi davvero uscire da Strumenti MKV?")
        if self._busy:
            msg = L("C'è un'operazione in corso.\nVuoi uscire comunque?")
        q = QMessageBox.question(self, L("Esci"), msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if q != QMessageBox.Yes:
            return
        try:
            self.window().close()
        except Exception:
            self.close()





    def open_insert_clips_tool(self) -> None:
        try:
            it = self.list_files.currentItem()
            src = None

            if it is not None and (it.text() or "").strip():
                src = Path(it.text()).expanduser()
            elif self.list_files.count() > 0:
                txt = (self.list_files.item(0).text() or "").strip()
                if txt:
                    src = Path(txt).expanduser()

            if src is not None and not src.exists():
                QtWidgets.QMessageBox.warning(
                    self,
                    L("Errore"),
                    L("File sorgente non trovato.") + "\n" + str(src),
                )
                return

            try:
                from hevc_gui.mkv_suite.ui.insert_clips_dialog import InsertClipsDialog
            except Exception as e:
                QtWidgets.QMessageBox.critical(
                    self,
                    L("Errore"),
                    L("Modulo Inserisci clip non disponibile:") + "\n" + str(e),
                )
                return

            dlg = InsertClipsDialog(src, self)
            dlg.exec_()

        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                L("Errore"),
                L("Impossibile aprire lo strumento Inserisci clip:") + "\n" + str(e),
            )
    def _tooltip_applica_tag(self) -> str:
        return L(
            "Scrive subito nel file MKV originale i metadati (titolo, nomi tracce, lingue, default/forced). "
            "Non fa remux e non crea un nuovo file."
        )

    def _apply_all_tooltips(self) -> None:
        # Tooltip espliciti (traducibili) per i controlli principali
        explicit = {
            "btn_apply_tags": self._tooltip_applica_tag(),
            "btn_remux": L("Premi 'Applica Tag' per scrivere nel file originale, oppure 'Crea MKV' per creare un nuovo file."),
            "btn_extract": L("Estrae le tracce selezionate nella cartella extract/."),
            "btn_cut": L("Apre lo strumento di taglio video sul file selezionato."),
            "btn_stop": L("Interrompe l'operazione in corso."),
            "btn_add": L("Aggiunge file sorgenti alla lista."),
            "btn_remove": L("Rimuove il file selezionato dalla lista (non dal disco)."),
            "btn_open_outdir": L("Apre la cartella output della sessione."),
            "btn_apply_tag": self._tooltip_applica_tag(),  # fallback nome alternativo
        }
        for attr, tip in explicit.items():
            w = getattr(self, attr, None)
            if w is not None:
                try:
                    w.setToolTip(tip)
                except Exception:
                    pass

        # Tooltip base a tutti i widget senza tooltip (fallback automatico)
        try:
            from PyQt5.QtWidgets import QWidget, QAbstractButton, QLineEdit, QComboBox, QAbstractSpinBox, QTableWidget
        except Exception:
            return

        for w in self.findChildren(QWidget):
            try:
                if w.toolTip():
                    continue
            except Exception:
                continue

            # Pulsanti / checkbox / radio: usa il testo visibile (già traducibile dalla UI)
            if isinstance(w, QAbstractButton):
                try:
                    t = (w.text() or "").strip()
                    if t:
                        w.setToolTip(t)
                        continue
                except Exception:
                    pass

            # Input testo
            if isinstance(w, QLineEdit):
                try:
                    ph = (w.placeholderText() or "").strip()
                    if ph:
                        w.setToolTip(ph)
                    else:
                        w.setToolTip(L("Campo di testo."))
                    continue
                except Exception:
                    pass

            # Combo
            if isinstance(w, QComboBox):
                try:
                    w.setToolTip(L("Seleziona un valore dall'elenco."))
                    continue
                except Exception:
                    pass

            # Spin
            if isinstance(w, QAbstractSpinBox):
                try:
                    w.setToolTip(L("Imposta un valore."))
                    continue
                except Exception:
                    pass

            # Tabelle
            if isinstance(w, QTableWidget):
                try:
                    w.setToolTip(L("Tabella dati. Doppio click per modifiche dove supportato."))
                    continue
                except Exception:
                    pass

            # Fallback leggero: objectName se utile
            try:
                name = (w.objectName() or "").strip()
                if name:
                    w.setToolTip(name)
            except Exception:
                pass

    # ---------- QProcess queue runner ----------
    def _queue_start(self, queue: List[Tuple[List[str], str, bool]], done_msg: str) -> None:
        if self._busy:
            return
        self._queue = list(queue)
        self._queue_done_msg = done_msg
        self.progress.setValue(0)
        # PROGRESSBAR_ZERO_CHUNK_SET
        try:
            self.progress.setProperty('zero', (self.progress.value() <= 0))
            self.progress.style().unpolish(self.progress)
            self.progress.style().polish(self.progress)
            self.progress.update()
        except Exception:
            pass
        self._set_busy(True)
        self._queue_next()

    def _queue_next(self) -> None:
        if not self._queue:
            self.progress.setValue(0)
            # PROGRESSBAR_ZERO_CHUNK_SET
            try:
                self.progress.setProperty('zero', (self.progress.value() <= 0))
                self.progress.style().unpolish(self.progress)
                self.progress.style().polish(self.progress)
                self.progress.update()
            except Exception:
                pass
            self._set_busy(False)
            if self._queue_done_msg:
                self._log(self._queue_done_msg)
            try:
                _p = getattr(self, '_preview_open_path', None)
                if _p:
                    self._preview_open_path = None
                    self._open_path_in_vlc(Path(_p))
            except Exception:
                try:
                    self._preview_open_path = None
                except Exception:
                    pass
            return

        cmd, label, allow_fail = self._queue.pop(0)
        self._cur_allow_fail = bool(allow_fail)
        self._start_process(cmd, label)

    def _start_process(self, cmd: List[str], label: str) -> None:
        # reset progress for this step
        self.progress.setValue(0)
        # PROGRESSBAR_ZERO_CHUNK_SET
        try:
            self.progress.setProperty('zero', (self.progress.value() <= 0))
            self.progress.style().unpolish(self.progress)
            self.progress.style().polish(self.progress)
            self.progress.update()
        except Exception:
            pass
        self.progress.setToolTip(label)

        if self._proc is not None:
            try:
                self._proc.kill()
            except Exception:
                pass
            self._proc = None

        self._proc_buf = ""
        p = QProcess(self)
        self._proc = p
        p.setProcessChannelMode(QProcess.MergedChannels)

        p.readyReadStandardOutput.connect(self._proc_read)
        p.finished.connect(self._proc_finished)

        self._log("[RUN] " + " ".join(cmd))

        program = cmd[0]
        args = cmd[1:]
        p.start(program, args)

    def _proc_read(self) -> None:
        if not self._proc:
            return
        data = bytes(self._proc.readAllStandardOutput()).decode("utf-8", "replace")
        data = data.replace("\r", "\n")
        if not data:
            return
        self._proc_buf += data
        while "\n" in self._proc_buf:
            line, self._proc_buf = self._proc_buf.split("\n", 1)
            line = line.rstrip("\r")
            if line:
                self._log(line)
                m = self._RX_PROGRESS.search(line)
                if m:
                    try:
                        v = int(m.group(1))
                        v = max(0, min(100, v))
                        self.progress.setValue(v)
                        # PROGRESSBAR_ZERO_CHUNK_SET
                        try:
                            self.progress.setProperty('zero', (self.progress.value() <= 0))
                            self.progress.style().unpolish(self.progress)
                            self.progress.style().polish(self.progress)
                            self.progress.update()
                        except Exception:
                            pass
                    except Exception:
                        pass

    def _proc_finished(self, exitCode: int, _exitStatus) -> None:
        # flush last buffered line
        if self._proc_buf.strip():
            line = self._proc_buf.strip()
            line = line.replace('\r', '\n')
            self._log(line)
            m = self._RX_PROGRESS.search(line)
            if m:
                try:
                    v = int(m.group(1))
                    v = max(0, min(100, v))
                    self.progress.setValue(v)
                    # PROGRESSBAR_ZERO_CHUNK_SET
                    try:
                        self.progress.setProperty('zero', (self.progress.value() <= 0))
                        self.progress.style().unpolish(self.progress)
                        self.progress.style().polish(self.progress)
                        self.progress.update()
                    except Exception:
                        pass
                except Exception:
                    pass
        self._proc_buf = ""

        rc = int(exitCode)
        if rc != 0 and not self._cur_allow_fail:
            self._log(f"[ERR] Comando fallito (rc={rc}).")
            self.progress.setValue(0)
            # PROGRESSBAR_ZERO_CHUNK_SET
            try:
                self.progress.setProperty('zero', (self.progress.value() <= 0))
                self.progress.style().unpolish(self.progress)
                self.progress.style().polish(self.progress)
                self.progress.update()
            except Exception:
                pass
            self._set_busy(False)
            try:
                self._preview_open_path = None
            except Exception:
                pass
            try:
                self._preview_open_path = None
            except Exception:
                pass
            self._queue.clear()
            return

        # next
        self._queue_next()

    # ---------- operations ----------
    def _pick_target_mkv(self) -> Optional[Path]:
        it = self.list_files.currentItem()
        if it:
            p = Path(it.text())
            if p.suffix.lower() == ".mkv" and p.exists():
                return p
        for i in range(self.list_files.count()):
            p = Path(self.list_files.item(i).text())
            if p.suffix.lower() == ".mkv" and p.exists():
                return p
        return None

    def apply_tags(self) -> None:
        mkv = self._pick_target_mkv()
        if not mkv:
            QMessageBox.information(self, L("Info"), L("Seleziona (o aggiungi) almeno un file MKV per Applica Tag."))
            return
        title = self._effective_title().strip()
        if not title:
            QMessageBox.information(self, L("Info"), L("Inserisci almeno un Titolo (e opzionalmente l’Anno)."))
            return
        self._set_busy(True)
        try:
            mi = probe_mkv(mkv, self._tc)
            apply_tags_in_place(mi, self._tc, title=title)
            self._log("[OK] Tag applicati (in-place).")
        except Exception as e:
            self._log(f"[ERR] Applica Tag: {e}")
        finally:
            self._set_busy(False)

    def extract_selected(self) -> None:
        # SEMPRE chiedi cartella output
        if getattr(self, '_out_dir', None) is None and not self.on_choose_outdir():
            self._log("[INFO] Estrai annullato: cartella output non scelta.")
            return

        mkv = self._pick_target_mkv()
        if not mkv:
            QMessageBox.information(self, L("Info"), L("Seleziona (o aggiungi) un file MKV per Estrai."))
            return

        title = self._effective_title().strip()
        base = (title or mkv.stem).strip() or mkv.stem

        def safe_folder(s: str) -> str:
            s = (s or "").strip().replace("/", "_").replace("\\", "_").replace(":", "_")
            s = re.sub(r"\s+", " ", s).strip()
            return s or "extract"

        job = self._job_dir
        if not job:
            job = self._out_dir
            self._job_dir = job
        out_root = job / "extract"
        audio_dir = out_root / "audio"
        subs_dir = out_root / "subs"
        out_root.mkdir(parents=True, exist_ok=True)
        audio_dir.mkdir(parents=True, exist_ok=True)
        subs_dir.mkdir(parents=True, exist_ok=True)

        # track selection (from entries)
        mkv_entries = [e for e in self._entries if e.is_mkv and e.src == mkv and e.include]
        if not mkv_entries:
            # fallback: everything from probe
            mi_tmp = probe_mkv(mkv, self._tc)
            mkv_entries = []
            for t in mi_tmp.tracks:
                mkv_entries.append(RemuxEntry(
                    src=mkv, src_label=mkv.name, kind=t.type, tid=t.tid, is_mkv=True, include=True,
                    lang=self._norm_lang(t.language or "und"),
                    name=(t.name or "").strip(),
                    default=bool(t.flag_default) if t.flag_default is not None else False,
                    forced=bool(t.flag_forced) if t.flag_forced is not None else False,
                    codec_id=t.codec_id or ""
                ))

        v_ids = sorted({e.tid for e in mkv_entries if (e.kind or "").lower() == "video"})
        a_tracks = [e for e in mkv_entries if (e.kind or "").lower() == "audio"]
        s_tracks = [e for e in mkv_entries if (e.kind or "").lower() == "subtitles"]

        queue: List[Tuple[List[str], str, bool]] = []

        # 1) video => <input>_e.mkv (mkvmerge)
        if v_ids and self._tc.mkvmerge:
            v_base = self._safe_job_name(base) or mkv.stem
            v_out = out_root / f"{v_base}_e.mkv"
            cmd = [self._tc.mkvmerge, "-o", str(v_out), "--no-audio", "--no-subtitles", "--no-buttons",
                   "--video-tracks", ",".join(str(x) for x in v_ids), str(mkv)]
            if title:
                cmd.insert(3, "--title")
                cmd.insert(4, title)
            queue.append((cmd, "video", False))

        # 2) mkvextract tracks (audio+subs) => formato naturale + _e
        if self._tc.mkvextract:
            mi = probe_mkv(mkv, self._tc)
            tid_map = {t.tid: t for t in mi.tracks}

            specs: List[str] = []
            # audio
            for e in a_tracks:
                t = tid_map.get(e.tid)
                if not t:
                    continue
                ext = self._ext_for(t.codec_id or "", "audio")
                nm = self._safe_slug(e.name or self._lang_label(e.lang))
                fn = f"{self._safe_slug(base)}_T{e.tid}_audio_{self._norm_lang(e.lang)}_{nm}_e.{ext}"
                specs.append(f"{e.tid}:{str(audio_dir / fn)}")

            # subs
            for e in s_tracks:
                t = tid_map.get(e.tid)
                if not t:
                    continue
                ext = self._ext_for(t.codec_id or "", "subtitles")
                nm = self._safe_slug(e.name or f"{self._lang_label(e.lang)} ({'forced' if e.forced else 'normal'})")
                fn = f"{self._safe_slug(base)}_T{e.tid}_sub_{self._norm_lang(e.lang)}_{nm}_e.{ext}"
                specs.append(f"{e.tid}:{str(subs_dir / fn)}")

            if specs:
                cmd = [self._tc.mkvextract, str(mkv), "tracks"] + specs
                queue.append((cmd, "tracks", False))

        # 3) chapters => chapters_e.xml (best effort)
        ch_xml = (self.ed_chapters.text() or "").strip()
        # prefer: if user selected chapters file, we already have it; for extract we take from MKV itself:
        if self._tc.mkvextract:
            chap_out = out_root / "chapters_e.xml"
            cmd = [self._tc.mkvextract, str(mkv), "chapters", str(chap_out)]
            # allow_fail=True (mkv without chapters)
            queue.append((cmd, "chapters", True))

        if not queue:
            self._log("[INFO] Nulla da estrarre.")
            return

        self._queue_start(queue, done_msg=L("[OK] Estrazione completata."))


    def _normalize_mkvmerge_cmd(self, cmd, out_file=None):
        try:
            cmd = list(cmd or [])
            if len(cmd) < 4:
                return cmd
            if str(cmd[0]).endswith("mkvmerge") is False and "mkvmerge" not in str(cmd[0]):
                return cmd
            if cmd[1] != "-o":
                return cmd

            # caso sano: subito dopo -o c'è l'output
            if len(cmd) >= 3 and not str(cmd[2]).startswith("-"):
                return cmd

            # caso rotto: -o --sync X:Y OUTPUT ...
            fixed = [cmd[0], "-o", str(out_file)] if out_file is not None else [cmd[0], "-o"]

            i = 2
            early_sync = []
            while i + 1 < len(cmd) and cmd[i] == "--sync":
                early_sync.extend([cmd[i], cmd[i + 1]])
                i += 2

            rest = cmd[i:]

            # se il primo token del resto è proprio l'out_file, non duplicarlo
            if out_file is not None and rest and str(rest[0]) == str(out_file):
                rest = rest[1:]

            # prova a lasciare l'input come ultimo argomento
            if rest:
                src_tok = rest[-1]
                fixed.extend(rest[:-1])
                fixed.extend(early_sync)
                fixed.append(src_tok)
            else:
                fixed.extend(early_sync)

            try:
                self._log("[FIX] Normalizzato ordine argomenti mkvmerge per --sync.")
            except Exception:
                pass
            return fixed
        except Exception:
            return cmd


    def _project_tmp_root(self) -> Path:
        p = Path(__file__).resolve().parents[3] / "tmp"
        p.mkdir(parents=True, exist_ok=True)
        return p


    def _build_external_subtitle_adjustment_map(self):
        out = {"external": {}, "internal_drift": []}
        try:
            drift_dir = self._project_tmp_root() / "subtitle_drift_remux"
            drift_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            drift_dir = None

        for e in getattr(self, "_entries", []):
            try:
                if not bool(getattr(e, "include", False)):
                    continue
                if (getattr(e, "kind", "") or "").strip().lower() != "subtitles":
                    continue

                try:
                    delay = int(self._get_delay_for_key(self._entry_sync_key(e)) or 0)
                except Exception:
                    delay = 0

                # subtitle esterni
                if not bool(getattr(e, "is_mkv", False)):
                    src_path = Path(getattr(e, "src"))
                    use_path = src_path

                    try:
                        pts = self._subtitle_drift_points_for_entry(e)
                    except Exception:
                        pts = []

                    if drift_dir is not None and self._subtitle_entry_supports_drift(e) and len(pts) >= 2:
                        try:
                            rendered = self._render_drifted_subtitle_for_entry(e, drift_dir)
                            if rendered is not None:
                                use_path = Path(rendered)
                                try:
                                    self._log(f"[DRIFT] Uso subtitle retimato per remux: {use_path}")
                                except Exception:
                                    pass
                        except Exception as ex:
                            try:
                                self._log(f"[WARN] Drift subtitle non applicato nel remux: {ex}")
                            except Exception:
                                pass

                    out["external"][str(src_path)] = {
                        "path": str(use_path),
                        "delay": int(delay),
                    }
                    continue

                # subtitle interni testuali con drift
                try:
                    pts = self._subtitle_drift_points_for_entry(e)
                except Exception:
                    pts = []

                if drift_dir is not None and self._subtitle_entry_supports_drift(e) and len(pts) >= 2:
                    try:
                        rendered = self._render_drifted_subtitle_for_entry(e, drift_dir)
                        if rendered is not None:
                            try:
                                self._log(f"[DRIFT] Uso subtitle interno retimato per remux: {rendered}")
                            except Exception:
                                pass
                            out["internal_drift"].append({
                                "src": str(Path(getattr(e, "src"))),
                                "tid": int(getattr(e, "tid", 0)),
                                "path": str(rendered),
                                "delay": int(delay),
                                "lang": str(getattr(e, "lang", "") or "und"),
                                "name": str(getattr(e, "name", "") or ""),
                                "default": bool(getattr(e, "default", False)),
                                "forced": bool(getattr(e, "forced", False)),
                            })
                    except Exception as ex:
                        try:
                            self._log(f"[WARN] Drift subtitle interno non applicato nel remux: {ex}")
                        except Exception:
                            pass

            except Exception:
                continue

        return out


    def _apply_subtitle_adjustments_to_remux_cmd(self, cmd):
        try:
            cmd = list(cmd or [])
            plan = self._build_external_subtitle_adjustment_map()
            external_map = dict(plan.get("external", {}) or {})
            internal_drift = list(plan.get("internal_drift", []) or [])

            # A) sostituisci subtitle esterni originali con eventuali file retimati
            out = []
            for tok in cmd:
                info = external_map.get(str(tok))
                if info is None:
                    out.append(tok)
                    continue

                delay = int(info.get("delay", 0) or 0)
                new_path = str(info.get("path", tok))

                # per subtitle esterni, track id interno è 0
                if delay != 0:
                    if not (len(out) >= 2 and out[-2] == "--sync" and out[-1] == f"0:{delay}"):
                        out.extend(["--sync", f"0:{delay}"])

                out.append(new_path)

            cmd = out

            # B) sostituisci subtitle interni driftati con file esterni temporanei
            if not internal_drift:
                return cmd

            def _remove_tid_from_subtitle_tracks(tokens, src_path_str, tid_to_remove):
                tokens = list(tokens)
                try:
                    src_index = tokens.index(src_path_str)
                except ValueError:
                    return tokens

                sub_idx = -1
                i = 0
                while i < src_index:
                    if tokens[i] == "--subtitle-tracks" and i + 1 < src_index:
                        sub_idx = i
                        i += 2
                        continue
                    i += 1

                if sub_idx < 0:
                    return tokens

                ids = [x for x in str(tokens[sub_idx + 1]).split(",") if x != ""]
                ids = [x for x in ids if x != str(int(tid_to_remove))]

                if ids:
                    tokens[sub_idx + 1] = ",".join(ids)
                else:
                    tokens[sub_idx:sub_idx + 2] = ["--no-subtitles"]

                return tokens

            def _append_external_sub(tokens, item):
                lang = str(item.get("lang", "und") or "und")
                name = str(item.get("name", "") or "")
                default = "yes" if bool(item.get("default", False)) else "no"
                forced = "yes" if bool(item.get("forced", False)) else "no"
                delay = int(item.get("delay", 0) or 0)
                path = str(item.get("path"))

                tokens.extend([
                    "--subtitle-tracks", "0",
                    "--no-video", "--no-audio", "--no-buttons",
                    "--language", f"0:{lang}",
                    "--track-name", f"0:{name}",
                    "--default-track", f"0:{default}",
                    "--forced-track", f"0:{forced}",
                ])
                if delay != 0:
                    tokens.extend(["--sync", f"0:{delay}"])
                tokens.append(path)
                return tokens

            for item in internal_drift:
                src_path_str = str(item.get("src"))
                tid = int(item.get("tid", 0))
                cmd = _remove_tid_from_subtitle_tracks(cmd, src_path_str, tid)
                cmd = _append_external_sub(cmd, item)

            return cmd
        except Exception:
            return cmd

    def remux_selected(self) -> None:
        # SEMPRE chiedi cartella output
        if getattr(self, '_out_dir', None) is None and not self.on_choose_outdir():
            self._log("[INFO] Crea MKV annullato: cartella output non scelta.")
            return

        if not self._tc.mkvmerge:
            self._log("[ERR] mkvmerge non trovato (installa mkvtoolnix).")
            return

        if not self._entries:
            self._log("[INFO] Crea MKV: aggiungi almeno una sorgente.")
            return

        title = self._effective_title().strip()
        base = (title or "output").strip() or "output"
        job = self._job_dir
        if not job:
            job = self._out_dir
            self._job_dir = job
        remux_dir = job / "remux"
        remux_dir.mkdir(parents=True, exist_ok=True)
        out_file = remux_dir / f"{base}.mkv"


        if out_file.exists():
            k = 1
            while True:
                cand = self._out_dir / f"{base} ({k}).mkv"
                if not cand.exists():
                    out_file = cand
                    break
                k += 1

        chapters_path = None
        if self._chapters_override and self._chapters_override.is_file():
            chapters_path = self._chapters_override
        else:
            t = (self.ed_chapters.text() or "").strip()
            if t:
                cp = Path(t)
                if cp.is_file():
                    chapters_path = cp

        # group by src
        by_src: Dict[Path, List[RemuxEntry]] = {}
        for e in self._entries:
            if e.include:
                by_src.setdefault(e.src, []).append(e)

        if not by_src:
            self._log("[INFO] Crea MKV: nessuna traccia spuntata.")
            return

        cmd: List[str] = [self._tc.mkvmerge, "-o", str(out_file)]
        if title:
            cmd += ["--title", title]
        if chapters_path:
            cmd += ["--chapters", str(chapters_path)]

        def src_pri(src: Path) -> int:
            ents = by_src[src]
            if any((x.kind or "").lower() == "video" for x in ents): return 0
            if any((x.kind or "").lower() == "audio" for x in ents): return 1
            if any((x.kind or "").lower() == "subtitles" for x in ents): return 2
            return 3

        for src in sorted(by_src.keys(), key=lambda s: (src_pri(s), s.name.lower())):
            ents = by_src[src]
            suf = src.suffix.lower()

            if suf == ".mkv":
                vids = sorted({x.tid for x in ents if (x.kind or "").lower() == "video"})
                auds = sorted({x.tid for x in ents if (x.kind or "").lower() == "audio"})
                subs = sorted({x.tid for x in ents if (x.kind or "").lower() == "subtitles"})

                cmd += (["--video-tracks", ",".join(str(x) for x in vids)] if vids else ["--no-video"])
                cmd += (["--audio-tracks", ",".join(str(x) for x in auds)] if auds else ["--no-audio"])
                cmd += (["--subtitle-tracks", ",".join(str(x) for x in subs)] if subs else ["--no-subtitles"])
                cmd += ["--no-buttons"]

                for x in ents:
                    tid = x.tid
                    if x.lang:
                        cmd += ["--language", f"{tid}:{self._norm_lang(x.lang)}"]
                    tname = self._vlc_track_name(tid, x, src)
                    if tname:
                        cmd += ["--track-name", f"{tid}:{tname}"]
                    cmd += ["--default-track", f"{tid}:{'yes' if x.default else 'no'}"]
                    cmd += ["--forced-track", f"{tid}:{'yes' if x.forced else 'no'}"]

                if chapters_path:
                    cmd += ["--no-chapters"]
                cmd += [str(src)]
            else:
                # external single file: explicit track selection by type (no bleed)
                x = ents[0]
                tid = 0
                k = (x.kind or "").lower()

                if k == "audio":
                    cmd += ["--audio-tracks", "0", "--no-video", "--no-subtitles", "--no-buttons"]
                elif k == "subtitles":
                    cmd += ["--subtitle-tracks", "0", "--no-video", "--no-audio", "--no-buttons"]
                elif k == "video":
                    cmd += ["--video-tracks", "0", "--no-audio", "--no-subtitles", "--no-buttons"]
                else:
                    # unknown: include all tracks
                    pass

                if x.lang:
                    cmd += ["--language", f"{tid}:{self._norm_lang(x.lang)}"]
                tname = self._vlc_track_name(tid, x, src)
                if tname:
                    cmd += ["--track-name", f"{tid}:{tname}"]
                cmd += ["--default-track", f"{tid}:{'yes' if x.default else 'no'}"]
                cmd += ["--forced-track", f"{tid}:{'yes' if x.forced else 'no'}"]

                cmd += [str(src)]

        cmd = self._apply_audio_sync_to_mkvmerge_cmd(cmd)
        cmd = self._apply_subtitle_adjustments_to_remux_cmd(cmd)
        cmd = self._normalize_mkvmerge_cmd(cmd, out_file=out_file)
        self._queue_start([(cmd, "mkvmerge", False)], done_msg=L("[OK] Rimux creato: {out_file}").format(out_file=out_file))

    def stop_jobs(self) -> None:
        # stop QProcess + clear queue
        try:
            self._preview_open_path = None
        except Exception:
            pass
        try:
            self._preview_open_path = None
        except Exception:
            pass
        self._queue.clear()
        if self._proc and self._proc.state() != QProcess.NotRunning:
            try:
                self._proc.terminate()
            except Exception:
                pass
            QTimer.singleShot(800, lambda: (self._proc.kill() if self._proc and self._proc.state() != QProcess.NotRunning else None))
        self.progress.setValue(0)
        # PROGRESSBAR_ZERO_CHUNK_SET
        try:
            self.progress.setProperty('zero', (self.progress.value() <= 0))
            self.progress.style().unpolish(self.progress)
            self.progress.style().polish(self.progress)
            self.progress.update()
        except Exception:
            pass
        self._set_busy(False)
        self._log("[UI] Stop richiesto.")

    def reset_all(self) -> None:
        if self._busy:
            QMessageBox.information(self, L("Info"), L("Operazione in corso. Premi Stop o attendi."))
            return
        q = QMessageBox.question(
            self, L("Conferma"),
            L("Vuoi annullare e pulire tutto?\n(I dati non salvati andranno persi)"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if q != QMessageBox.Yes:
            return

        self._ui_lock = True
        try:
            self._entries = []
            self._sources = []
            self._chapters_override = None
            self.list_files.clear()
            self.tbl_tracks.setRowCount(0)
            self.ed_chapters.clear()

            self._title.name_user = self._title.name_auto = ""
            self._year.name_user = self._year.name_auto = ""
            self._out_base.name_user = self._out_base.name_auto = ""
            self.ed_title.clear()
            self.ed_year.clear()

            self.log.clear()
            self.progress.setValue(0)
            # PROGRESSBAR_ZERO_CHUNK_SET
            try:
                self.progress.setProperty('zero', (self.progress.value() <= 0))
                self.progress.style().unpolish(self.progress)
                self.progress.style().polish(self.progress)
                self.progress.update()
            except Exception:
                pass
        finally:
            self._ui_lock = False

        self._update_previews()
        self._update_enabled()
        self._log("[UI] Reset completato.")

    def exit_app(self) -> None:
        msg = L("Vuoi davvero uscire da Strumenti MKV?")
        if self._busy:
            msg = L("C'è un'operazione in corso.\nVuoi uscire comunque?")
        q = QMessageBox.question(self, L("Esci"), msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if q != QMessageBox.Yes:
            return
        try:
            self.window().close()
        except Exception:
            self.close()
