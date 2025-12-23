#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# hevc_gui/gui/main_window.py (inizio del file)

from __future__ import annotations

import os
import signal
import json
import shlex
import subprocess
import sys
import logging

import mimetypes
import webbrowser
import re
import time
import shutil
import hevc_gui.resources.icons_rc
from typing import Optional, List, Union
from pathlib import Path

# Assicuriamoci che Python trovi lo script in scripts/
scripts_dir = Path(__file__).parent.parent.parent / "scripts"
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

# Ora possiamo importare AudioConverter direttamente
from string_audio_generator import AudioConverter

from PyQt5.QtCore import Qt, QProcess, pyqtSlot, QUrl, QTimer, QTime, QEventLoop
from PyQt5.QtGui import (
    QDragEnterEvent,
    QFont,
    QDropEvent,
    QDesktopServices,
    QIcon,
    QPixmap,
)
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QFileDialog,
    QMessageBox,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QTextEdit,
    QRadioButton,
    QButtonGroup,
    QLineEdit,
    QDialog,
    QPlainTextEdit,
    QCheckBox,
    QInputDialog,
)

from ..core import constants as C
from ..core import queue as qman
from ..core.media_info_dialog import MediaInfoDialog
from ..core.subtitle_helper import select_subtitles
from ..core.chapter import ChapterManager
from ..core.chapter_worker import ChapterWorker
from ..core.progressbar_nozero import ProgressBarNoZeroChunk
from ..core.constants import SCRIPTS_DIR
from ..core.helpers import select_reverb_expr, join_filters, add_filter_arg
# Crop: lettura dai Settings + iniezione nella vf chain
from hevc_gui.video.crop_tools import load_crop_settings, inject_crop, clear_crop_settings, save_crop_settings

from .menubar import setup_menubar, refresh_icons, add_donate_to_help
from .appearance_settings import CONFIG_PATH, load_appearance
from subprocess import check_output

# Path del binario ffmpeg
FFMPEG_BIN = "ffmpeg"

# —————————————————————————————————————————————————————————————
# Logger → /dev/shm/hevc_gui/gui_debug.log (RAM)
# —————————————————————————————————————————————————————————————

logging.raiseExceptions = False

def _setup_logging() -> logging.Logger:
    base_dir = Path(os.environ.get("HEVC_LOG_DIR", "/dev/shm/hevc_gui"))
    try:
        base_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        base_dir = Path("/tmp/hevc_gui")
        base_dir.mkdir(parents=True, exist_ok=True)

    log_path = base_dir / "gui_debug.log"

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers[:] = []  # evita duplicati

    fmt_file = logging.Formatter("%(asctime)s %(levelname)-8s %(message)s")

    fh = logging.FileHandler(str(log_path), mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt_file)
    root.addHandler(fh)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(ch)

    root.debug("=== Avvio applicazione — log file: %s ===", log_path)
    return logging.getLogger(__name__)

logger = _setup_logging()


def excepthook(exc_type, exc_value, exc_tb):
    logging.getLogger(__name__).error("Uncaught exception", exc_info=(exc_type, exc_value, exc_tb))
    sys.__excepthook__(exc_type, exc_value, exc_tb)

sys.excepthook = excepthook

def _bootstrap_project_icons_on_first_run(win):
    """
    Al PRIMO avvio (niente file di config) forzo l'uso dei PNG locali del progetto.
    Se poi l’utente cambia tema icone da 'Aspetto…', al riavvio si usa la scelta salvata.
    """
    try:
        if not os.path.exists(CONFIG_PATH):
            QIcon.setThemeName("fallback-only")  # costringe i fallback PNG del progetto
            logging.debug("Primo avvio: forzo fallback alle icone del progetto (PNG locali).")
            if hasattr(win, "refresh_icons"):
                win.refresh_icons()
    except Exception as e:
        logging.debug(f"Bootstrap icone — skip: {e}")

# ────────────────────────────────────────────────────────────────────────
# Widget helper per drag&drop di file video
# ────────────────────────────────────────────────────────────────────────


class PathLineEdit(QLineEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setPlaceholderText("Trascina qui un file video oppure premi «Apri…»")
        self.setAcceptDrops(True)
        self.setDragEnabled(False)

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            url = e.mimeData().urls()[0]
            if url.isLocalFile() and self._is_video(url.toLocalFile()):
                e.acceptProposedAction()
                return
        e.ignore()

    def dropEvent(self, e: QDropEvent):
        url = e.mimeData().urls()[0]
        if url.isLocalFile():
            self.setText(url.toLocalFile())
        e.acceptProposedAction()

    @staticmethod
    def _is_video(p: str) -> bool:
        m, _ = mimetypes.guess_type(p)
        return bool(m and m.startswith("video/"))


class QueueDialog(QDialog):
    def __init__(self, command_queue, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gestione Coda")
        self.setFixedSize(600, 400)
        self.command_queue = command_queue.copy()
        layout = QVBoxLayout(self)

        self.text_edit = QPlainTextEdit(self)
        self.text_edit.setPlainText(self._queue_to_text(self.command_queue))
        self.text_edit.setToolTip("Modifica i comandi, uno per riga.")
        layout.addWidget(self.text_edit, 1)

        btns = QHBoxLayout()
        self.save_btn = QPushButton("Salva", self)
        self.save_btn.clicked.connect(self.accept)
        self.cancel_btn = QPushButton("Annulla", self)
        self.cancel_btn.clicked.connect(self.reject)
        btns.addStretch()
        btns.addWidget(self.save_btn)
        btns.addWidget(self.cancel_btn)
        layout.addLayout(btns)

    def _queue_to_text(self, queue):
        return "\n".join(" ".join(shlex.quote(a) for a in cmd) for cmd in queue)

    def get_updated_queue(self):
        updated = []
        for line in self.text_edit.toPlainText().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                updated.append(shlex.split(line))
            except ValueError:
                pass
        return updated


class CustomMessageBox(QMessageBox):
    def __init__(self, icon_path=None, parent=None):
        super().__init__(parent)
        if icon_path and Path(icon_path).exists():
            self.setWindowIcon(QIcon(icon_path))

    def show_info_message(self, title, text, icon_path=None, icon_size=(64, 64)):
        self.setWindowTitle(title)
        self.setText(text)
        if icon_path and Path(icon_path).exists():
            icon_label = QLabel()
            pixmap = QPixmap(icon_path).scaled(*icon_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            icon_label.setPixmap(pixmap)
            self.layout().addWidget(icon_label, 0, 0, Qt.AlignCenter)
        self.setStandardButtons(QMessageBox.Ok)
        self.exec_()
##=============================================================================

class MainWindow(QMainWindow):
    # === TMP su RAM (/dev/shm) con fallback automatico su DISCO ==========
    def _prepare_session_dirs(self) -> None:
        """
        Crea le cartelle di sessione preferendo la RAM (/dev/shm) se la macchina
        ha abbastanza memoria; in caso contrario usa il disco.
        Variabili d'ambiente supportate:
          - HEVC_FORCE_TMP=ram|disk
          - HEVC_RAM_TMP (default: /dev/shm/hevc_gui)
          - HEVC_DISK_TMP (default: C.TMP_DIR o /var/tmp/hevc_gui)
          - HEVC_TMP_EST_FACTOR (default: 1.2)
        Espone: self.tmp_storage_mode in {"ram","disk"} per debug/UI.
        """
        import os
        from pathlib import Path
        import hevc_gui.core.constants as C
        from ..core import queue as qman

        def _get_ram_bytes() -> tuple[int, int]:
            try:
                import psutil  # type: ignore
                vm = psutil.virtual_memory()
                return int(vm.total), int(vm.available)
            except Exception:
                try:
                    info = {}
                    with open("/proc/meminfo", "r") as f:
                        for line in f:
                            k, v = line.split(":", 1)
                            info[k.strip()] = v.strip()
                    def _kib(s): return int(s.split()[0]) * 1024
                    total = _kib(info.get("MemTotal", "0 kB"))
                    avail = _kib(info.get("MemAvailable", "0 kB"))
                    return total, avail
                except Exception:
                    return 0, 0

        def _estimate_needed_bytes() -> int:
            try:
                in_size = int(self._current_file.stat().st_size) if getattr(self, "_current_file", None) else 0
            except Exception:
                in_size = 0
            factor = float(os.environ.get("HEVC_TMP_EST_FACTOR", "1.2"))
            margin = 512 * 1024 * 1024
            est = int(in_size * factor) + margin
            return max(est, 1 * 1024 * 1024 * 1024)

        def _fs_free_bytes(p: Path) -> int:
            try:
                st = os.statvfs(str(p))
                return int(st.f_bavail) * int(st.f_frsize)
            except Exception:
                return 0

        def _fmt(b: int) -> str:
            for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
                if b < 1024 or unit == "TiB":
                    return f"{b:.0f} {unit}"
                b /= 1024

        force = os.environ.get("HEVC_FORCE_TMP", "").strip().lower()
        ram_root = Path(os.environ.get("HEVC_RAM_TMP", "/dev/shm/hevc_gui"))
        disk_root = Path(os.environ.get("HEVC_DISK_TMP", str(getattr(C, "TMP_DIR", "/var/tmp/hevc_gui"))))

        need = _estimate_needed_bytes()
        ram_total, ram_avail = _get_ram_bytes()
        shm_free = _fs_free_bytes(ram_root.parent if ram_root.name else Path("/dev/shm"))

        RAM_MIN_TOTAL = 16 * 1024**3
        use_ram = False
        reason = ""

        if force in ("ram", "disk"):
            use_ram = force == "ram"
            reason = f"forced via HEVC_FORCE_TMP={force}"
        else:
            if ram_total >= RAM_MIN_TOTAL and ram_avail >= need and shm_free >= need:
                use_ram = True
                reason = f"OK: RAM total={_fmt(ram_total)}, avail={_fmt(ram_avail)}, /dev/shm free={_fmt(shm_free)}, need≈{_fmt(need)}"
            else:
                use_ram = False
                reason = f"NO RAM: total={_fmt(ram_total)}, avail={_fmt(ram_avail)}, /dev/shm free={_fmt(shm_free)}, need≈{_fmt(need)}"

        base_root = ram_root if use_ram else disk_root
        self.tmp_storage_mode = "ram" if use_ram else "disk"

        base_sessions = base_root / "sessions"
        base_sessions.mkdir(parents=True, exist_ok=True)
        logging.debug("[TMP] mode=%s • root=%s • reason: %s", self.tmp_storage_mode, str(base_root), reason)

        try:
            for old in base_sessions.iterdir():
                if old.is_dir():
                    shutil.rmtree(old, ignore_errors=True)
        except Exception:
            pass

        ts = str(int(time.time()))
        sess = base_sessions / ts
        sess.mkdir(parents=True, exist_ok=True)

        self.tmp_dir = sess
        self.audio_dir = sess / "audio_tracks"
        self.chapters_dir = sess / "hevc_gui_chapters"
        self.video_dir = sess / "video_temp"
        self.queue_dir = sess / "queue"
        for d in (self.audio_dir, self.chapters_dir, self.video_dir, self.queue_dir):
            d.mkdir(parents=True, exist_ok=True)

        C.TMP_DIR = self.tmp_dir
        self.queue_tmp_file = self.queue_dir / "queue.tmp"
        qman.QUEUE_FILE = self.queue_dir / "queue.json"
        qman.TMP_QUEUE_FILE = self.queue_tmp_file
        if not qman.QUEUE_FILE.exists():
            qman.save([])
        self.queue_tmp_file.touch(exist_ok=True)

        try:
            self.statusBar().showMessage(f"Temp: {self.tmp_storage_mode.upper()} @ {base_root} (need≈{_fmt(need)})", 5000)
        except Exception:
            pass
    # aggiungi questo metodo in MainWindow (per esempio vicino ad altri helper)
    def _log(self, msg: str) -> None:
        """Logga su txt_info se presente, altrimenti stdout."""
        try:
            # se hai una QTextEdit/QPlainTextEdit per i log
            self.txt_info.append(msg)
        except Exception:
            try:
                print(msg)
            except Exception:
                pass

    def __init__(self):
        super().__init__()
        # logger istanza
        self.logger = logger
        self.setWindowIcon(QIcon(":/icons/logo.png"))

        logging.debug("--> ENV QT_QPA_PLATFORMTHEME = %s", os.environ.get("QT_QPA_PLATFORMTHEME"))
        logging.debug("--> ENV GTK_THEME           = %s", os.environ.get("GTK_THEME"))
        logging.debug("--> QApp.style() name       = %s", QApplication.instance().style().objectName())

        self.setWindowTitle("HEVC - Video Converter")

        # Stato interno e directory temporanee
        self._start_time = time.time()
        self._current_file: Path | None = None
        self._filters: list[str] = []
        self._audio_opts: list[list[str]] = []
        self._subtitle_opts: list[str] = []
        self._chapter_opts: list[str] = []
        self._chapters_handled: bool = False
        self._progress_frac = 0.0  # frazione 0..1 del progresso corrente (per ETA)

        # TMP su RAM
        self._prepare_session_dirs()

        # coda (ora vive nella sessione in RAM)
        self.command_queue = qman.load()
        self.is_queue_saved = bool(self.command_queue)

        # Contatori e processi
        self._audio_idx = self._chap_idx = self._video_idx = self._video_idx_queue = 0
        self._subs_integrated_count = 0
        self._audio_specs: list[dict] = []
        self._draft_mux_cmd: list[str] | None = None
        self._subtitle_inputs: list[Path] = []
        self._subtitle_langs: list[str] = []
        self._subtitle_types: list[str] = []
        self._subtitle_out_opts: list[str] = []
        self._elapsed_secs = self._eta_secs = 0
        self._tick_timer = None
        self._audio_procs: list[QProcess] = []
        self._current_audio_idx = 0
        self.ffmpeg_proc: QProcess | None = None
        self._total_duration = 0.0
        self._last_output: Path | None = None
        self.preview_proc: QProcess | None = None

        self._marquee_timer = QTimer(self)
        self._marquee_timer.timeout.connect(self._advance_marquee)
        self.block_width = 30
        self._marquee_value = 0
        self._marquee_direction = 1

        self._last_ffmpeg_log = ""
        self._is_paused = False
        self._last_queue_run: list[list[str]] | None = None

        # Costruzione UI e collegamenti
        self._build_ui()                       # ← dentro _build_ui esiste già: self.edit_path.textChanged.connect(self._path_changed)
        self._wire_dblclick_for_all_combos()

        # stato iniziale bottoni
        self._update_buttons_enabled()

        # NIENTE doppione: NON ricollegare qui edit_path e NON fare disconnect/connect su btn_convert
        self.adjustSize()

        self._allow_silent = False

    def _build_ui(self):
        try:
            if not os.path.exists(CONFIG_PATH):
                QIcon.setThemeName("fallback-only")
                logging.debug("Primo avvio: tema icone impostato a 'fallback-only' (icone progetto).")
        except Exception as e:
            logging.debug(f"Bootstrap icone (primo avvio) ignorato: {e}")

        self.setMenuBar(setup_menubar(self))
        add_donate_to_help(self)

        self.refresh_icons = lambda: refresh_icons(self)
        central = QWidget()
        self.setCentralWidget(central)
        vbox = QVBoxLayout(central)

        # Logo + Open
        logo_path = Path(__file__).parent.parent / "resources" / "icons" / "logo.png"
        logo_label = QLabel()
        if logo_path.exists():
            pix = QPixmap(str(logo_path)).scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            logo_label.setPixmap(pix)
        h1 = QHBoxLayout()
        h1.addWidget(logo_label)
        self.btn_open = QPushButton("Apri video…")
        self.btn_open.setToolTip("Seleziona un file video da convertire")
        self.btn_open.clicked.connect(self.open_file)
        h1.addWidget(self.btn_open)
        self.edit_path = PathLineEdit()
        self.edit_path.setToolTip("Percorso del file video da convertire")
        self.edit_path.textChanged.connect(self._path_changed)
        h1.addWidget(self.edit_path, 1)
        vbox.addLayout(h1)

        # Bitrate / CRF / Preset
        hrate = QHBoxLayout()
        self.rd_br = QRadioButton("Bit-rate")
        self.rd_crf = QRadioButton("CRF")
        self.rd_crf.setChecked(True)
        self.cmb_br = QComboBox()
        self.cmb_br.addItems(C.BITRATE_OPTIONS)
        self.cmb_br.setEnabled(False)
        self.cmb_crf = QComboBox()
        self.cmb_crf.addItems(C.CRF_OPTIONS)
        self.rd_br.toggled.connect(lambda val: (self.cmb_br.setEnabled(val), self.cmb_crf.setEnabled(not val)))
        hrate.addWidget(self.rd_br)
        hrate.addWidget(self.cmb_br)
        hrate.addSpacing(20)
        hrate.addWidget(self.rd_crf)
        hrate.addWidget(self.cmb_crf)
        hrate.addSpacing(20)
        hrate.addWidget(QLabel("Preset:"))
        self.cmb_preset = QComboBox()
        self.cmb_preset.addItems(C.PRESET_OPTIONS)
        hrate.addWidget(self.cmb_preset)
        vbox.addLayout(hrate)

        # Filtri video
        hfilters = QHBoxLayout()
        lbl = QLabel("Sharpness:")
        self.cmb_sharp = QComboBox()
        self.cmb_sharp.addItems(C.SHARPNESS_LEVELS)
        self.cmb_sharp.currentTextChanged.connect(self.update_filters)
        hfilters.addWidget(lbl)
        hfilters.addWidget(self.cmb_sharp)
        hfilters.addSpacing(20)
        lbl = QLabel("Smoothness:")
        self.cmb_smth = QComboBox()
        self.cmb_smth.addItems(C.SMOOTHNESS_LEVELS)
        self.cmb_smth.currentTextChanged.connect(self.update_filters)
        hfilters.addWidget(lbl)
        hfilters.addWidget(self.cmb_smth)
        hfilters.addSpacing(20)
        lbl = QLabel("Resize:")
        self.cmb_resize = QComboBox()
        self.cmb_resize.addItems(C.RESOLUTIONS)
        self.cmb_resize.currentTextChanged.connect(self.update_filters)
        hfilters.addWidget(lbl)
        hfilters.addWidget(self.cmb_resize)
        hfilters.addStretch()
        vbox.addLayout(hfilters)

        # Frame-rate, B&W, deinterlacciamento
        hfr = QHBoxLayout()
        hfr.addWidget(QLabel("Frame-rate:"))

        self.cmb_frmode = QComboBox()
        self.cmb_frmode.addItems(C.FR_MODE)
        self.cmb_frval = QComboBox()
        self.cmb_frval.addItems(C.FR_CONST_VALUES)
        self.cmb_frval.setEnabled(False)

        self.cmb_frmode.currentTextChanged.connect(lambda t: self.cmb_frval.setEnabled(t == "Costante"))

        for _label in ("Originale", "Nessuno"):
            if _label in C.FR_MODE:
                self.cmb_frmode.setCurrentText(_label)
                break
        else:
            self.cmb_frmode.setCurrentIndex(0)
        self.cmb_frval.setEnabled(self.cmb_frmode.currentText() == "Costante")

        hfr.addWidget(self.cmb_frmode)
        hfr.addSpacing(15)
        hfr.addWidget(QLabel("Valore:"))
        hfr.addWidget(self.cmb_frval)
        hfr.addSpacing(40)

        self.rd_color = QRadioButton("Color")
        self.rd_bw = QRadioButton("B&W")
        self.rd_color.setChecked(True)
        grp_col = QButtonGroup(self)
        grp_col.addButton(self.rd_color)
        grp_col.addButton(self.rd_bw)
        hfr.addWidget(self.rd_color)
        hfr.addWidget(self.rd_bw)

        hfr.addSpacing(40)
        self.chk_deint = QCheckBox("Deinterlacciamento")
        self.chk_deint.toggled.connect(self.update_filters)
        hfr.addWidget(self.chk_deint)
        hfr.addStretch()
        vbox.addLayout(hfr)
        # Pulsanti Estrai audio, Sottotitoli, Capitoli, Preview
        haudio_prev = QHBoxLayout()
        self.btn_audio = QPushButton("Estrai audio")
        self.btn_audio.clicked.connect(self.extract_audio)
        self.btn_subtitle = QPushButton("Sottotitoli")
        self.btn_subtitle.clicked.connect(self.on_subtitle_clicked)
        self.btn_subtitle.setEnabled(False)
        self.btn_chapter = QPushButton("Capitoli")
        self.btn_chapter.clicked.connect(self.on_chapter_clicked)
        self.btn_chapter.setEnabled(False)
        self.btn_preview = QPushButton("Preview")
        self.btn_preview.clicked.connect(lambda: self.launch_preview(False))
        self.btn_preview_filtered = QPushButton("Preview filtrata")
        self.btn_preview_filtered.clicked.connect(lambda: self.launch_preview(True))
        for w in (
            self.btn_audio,
            self.btn_subtitle,
            self.btn_chapter,
            self.btn_preview,
            self.btn_preview_filtered,
        ):
            haudio_prev.addWidget(w)
        haudio_prev.insertStretch(3)
        vbox.addLayout(haudio_prev)

        # Pulsanti MediaInfo, Salva/Elabora Coda, Converti, Help
        hmid = QHBoxLayout()
        self.btn_minfo = QPushButton("MediaInfo")
        self.btn_minfo.clicked.connect(self.show_mediainfo)
        self.btn_salva = QPushButton("Salva Coda")
        self.btn_salva.clicked.connect(self.save_gui_queue_to_file)
        self.btn_gestisci = QPushButton("Gestisci Coda")
        self.btn_gestisci.clicked.connect(self.open_queue_manager)
        self.btn_elabora = QPushButton("Elabora Coda")
        self.btn_elabora.clicked.connect(self.start_queue_processing)
        self.btn_convert = QPushButton("Converti")
        self.btn_convert.clicked.connect(self.on_convert_clicked)
        btn_help = QPushButton("Help")
        btn_help.clicked.connect(self.open_help)

        for w in (
            self.btn_minfo,
            None,
            self.btn_salva,
            self.btn_gestisci,
            self.btn_elabora,
            self.btn_convert,
            None,
            btn_help,
        ):
            if w is None:
                hmid.addStretch()
            else:
                hmid.addWidget(w)
        vbox.addLayout(hmid)

        # Log output
        self.txt_info = QTextEdit()
        self.txt_info.setReadOnly(True)
        vbox.addWidget(self.txt_info, 1)

        # Pulsanti inferiori
        hbot = QHBoxLayout()
        self.btn_dir_output = QPushButton("Directory Output")
        self.btn_dir_output.clicked.connect(self.open_output_directory)
        self.btn_copy_log = QPushButton("Copia Log FFmpeg")
        self.btn_copy_log.clicked.connect(self.copy_ffmpeg_log_to_clipboard)
        self.btn_copy_log.setEnabled(False)
        self.btn_pause = QPushButton("Pausa")
        self.btn_pause.clicked.connect(self.toggle_pause)
        self.btn_pause.setEnabled(False)
        self.btn_cancel = QPushButton("Interrompi")
        self.btn_cancel.clicked.connect(self.cancel_job)
        self.btn_reset_gui = QPushButton("Reset GUI")
        self.btn_reset_gui.clicked.connect(self.reset_gui_only)
        self.btn_exit = QPushButton("Esci")
        self.btn_exit.clicked.connect(self.exit_app)
        self.btn_info = QPushButton("Info")
        self.btn_info.clicked.connect(self.show_info)
        for w in (
            self.btn_dir_output,
            self.btn_copy_log,
            self.btn_pause,
            self.btn_cancel,
            self.btn_reset_gui,
            self.btn_exit,
            self.btn_info,
        ):
            hbot.addWidget(w)
        vbox.addLayout(hbot)

        # Stato e barra di avanzamento
        hstatus = QHBoxLayout()
        self.lbl_status = QLabel("Wait for conversion…")
        self.lbl_elapsed = QLabel("Elapsed: 00:00")
        self.lbl_remaining = QLabel("Remaining: --:--")
        for lbl in (self.lbl_elapsed, self.lbl_remaining):
            lbl.setStyleSheet("color: gray; font-size: 9pt;")
        hstatus.addWidget(self.lbl_status)
        hstatus.addStretch()
        hstatus.addWidget(self.lbl_elapsed)
        hstatus.addSpacing(10)
        hstatus.addWidget(self.lbl_remaining)
        vbox.addLayout(hstatus)

        self.progress = ProgressBarNoZeroChunk()
        self.progress.setFixedHeight(15)
        self.progress.setFormat("%p%")
        self.progress.setValue(0)
        vbox.addWidget(self.progress)

        layout = self.centralWidget().layout()
        layout.setContentsMargins(20, 30, 20, 30)
        layout.setSpacing(4)

    def _wire_dblclick_for_all_combos(self):
        from hevc_gui.core.dblclick import enable_doubleclick_on_children
        overrides = {}
        enable_doubleclick_on_children(self, overrides)

    # ─ update buttons + menù/toolbar ─────────────────────────────────────────
    def _update_buttons_enabled(self):
        running = bool(self.ffmpeg_proc and self.ffmpeg_proc.state() == QProcess.Running)
        has_file = bool(self._current_file)

        # --- Pulsanti visibili nella finestra --------------------------------
        for btn in (
            self.btn_convert,
            self.btn_audio,
            self.btn_subtitle,
            self.btn_chapter,
            self.btn_preview,
            self.btn_preview_filtered,
            self.btn_minfo,
            # self.btn_elabora,
        ):
            btn.setEnabled(has_file and not running)

        # 'Elabora Coda' segue lo stato reale della coda
        self._apply_elabora_enabled(running)

        self.btn_cancel.setEnabled(running)
        self.btn_reset_gui.setEnabled(not running)
        self.btn_pause.setEnabled(running)

        # --- Menù: sincronizza se la mappa esiste, ma NON ci affidiamo solo a quella
        if hasattr(self, "_menu_actions") and isinstance(self._menu_actions, dict):
            btn_map = {
                "open": getattr(self, "btn_open", None),
                "save": getattr(self, "btn_salva", None),
                "convert": self.btn_convert,
                "extract": self.btn_audio,
                "subs": self.btn_subtitle,
                "chapters": self.btn_chapter,
                "queue_run": self.btn_elabora,
                "preview": self.btn_preview,
                "preview_filtered": self.btn_preview_filtered,
                "mediainfo": self.btn_minfo,
            }
            for key, action in self._menu_actions.items():
                btn = btn_map.get(key)
                if btn is not None and action is not None:
                    action.setEnabled(btn.isEnabled())

        # Abilita/Disabilita "Imposta crop…" via riferimento diretto (affidabile)
        if hasattr(self, "act_crop") and self.act_crop is not None:
            try:
                self.act_crop.setEnabled(has_file and not running)
            except Exception:
                pass

        # (facoltativo) blocca/abilita l’intera toolbar in un colpo
        if hasattr(self, "_menu_toolbar"):
            self._menu_toolbar.setEnabled(not running)

    def _queue_has_jobs(self) -> bool:
        """True se esistono comandi in coda (in memoria, su JSON o in queue.tmp)."""
        try:
            if getattr(self, "command_queue", None):
                return len(self.command_queue) > 0
        except Exception:
            pass
        try:
            # queue.json (tramite queue manager)
            q = qman.load()
            if q:
                return True
        except Exception:
            pass
        try:
            # queue.tmp della sessione corrente
            if hasattr(self, "queue_tmp_file") and self.queue_tmp_file.is_file():
                txt = self.queue_tmp_file.read_text(errors="ignore")
                for ln in txt.splitlines():
                    s = ln.strip()
                    if s and not s.startswith("#"):
                        return True
        except Exception:
            pass
        return False

    def _apply_elabora_enabled(self, running: bool):
        """Abilita/Disabilita *solo* 'Elabora Coda' (finestra + toolbar/menù) in base alla coda."""
        on = (not running) and self._queue_has_jobs()
        # pulsante nella finestra
        if hasattr(self, "btn_elabora") and self.btn_elabora:
            self.btn_elabora.setEnabled(on)
        # azione di menù/toolbar
        if hasattr(self, "_menu_actions") and isinstance(self._menu_actions, dict):
            act = self._menu_actions.get("queue_run")
            if act:
                act.setEnabled(on)

    def _wrap_with_cpu_limits(self, cmd: list[str]) -> list[str]:
        """
        Opt-in via HEVC_USE_CPULIMIT=1: wrappa con cpulimit/ionice/nice.
        """
        import shutil
        use_cap = os.getenv("HEVC_USE_CPULIMIT", "0") == "1"
        if not use_cap:
            return cmd

        cpulimit_bin = shutil.which("cpulimit")
        ionice_bin = shutil.which("ionice")
        nice_bin = shutil.which("nice")
        if not cpulimit_bin or not ionice_bin or not nice_bin:
            return cmd

        cpu_limit = os.getenv("HEVC_CPU_LIMIT", "85")
        ionice_c = os.getenv("HEVC_IONICE_CLASS", "2")
        ionice_n = os.getenv("HEVC_IONICE_NICE", "5")
        nice_n = os.getenv("HEVC_NICE_N", "10")

        wrapped = [cpulimit_bin, "-l", cpu_limit, "--", ionice_bin, "-c", ionice_c, "-n", ionice_n, nice_bin, "-n", nice_n, *cmd]
        try:
            self.txt_info.append("[CPU] GUI wrapper: " + " ".join(wrapped))
        except Exception:
            pass
        return wrapped

    @pyqtSlot()
    def restart_app(self):
        python = sys.executable
        args = sys.argv[:]
        QProcess.startDetached(python, args)
        sys.exit(0)

    @pyqtSlot()
    def reload_font(self):
        app = QApplication.instance()
        new_font = app.font()
        app.setFont(QFont(new_font.family(), new_font.pointSize()))
        for w in app.allWidgets():
            w.update()

    @pyqtSlot(str)    # accetta segnali che passano la stringa
    @pyqtSlot()       # accetta anche segnali senza argomenti
    def _path_changed(self, text: str | None = None):
        """
        Handler robusto: funziona sia con textChanged(str) sia con editingFinished().
        Mantiene la logica: set _current_file, suggerisce FPS, aggiorna bottoni.
        """
        try:
            # 1) Ricava testo se non arrivato dal segnale
            if text is None:
                line = getattr(self, "edit_path", None)
                text = line.text().strip() if line else ""
            else:
                text = str(text).strip()

            # 2) Valida path file
            p = Path(text).expanduser()
            self._current_file = p if p.is_file() else None

            # 3) Abilita Converti “di base”
            try:
                self.btn_convert.setEnabled(self._current_file is not None)
            except Exception:
                pass

            # 4) Auto-suggerimento frame-rate quando c’è un file valido
            if self._current_file:
                fps = None
                try:
                    fps = self._probe_src_fps(self._current_file)
                except Exception as e:
                    if hasattr(self, "logger"):
                        self.logger.exception(f"_probe_src_fps() error: {e}")

                if fps:
                    try:
                        self._apply_detected_fps(fps)
                    except Exception as e:
                        if hasattr(self, "logger"):
                            self.logger.exception(f"_apply_detected_fps() error: {e}")
                else:
                    try:
                        self.txt_info.append("! Impossibile rilevare il frame-rate sorgente (ffprobe).")
                    except Exception:
                        pass

            # 5) Log di servizio
            if hasattr(self, "logger"):
                ok = self._current_file is not None
                self.logger.debug(f"_path_changed(): text='{text}' • file_ok={ok}")

        except Exception as e:
            if hasattr(self, "logger"):
                self.logger.exception(f"_path_changed() fatal: {e}")
        finally:
            # 6) Aggiorna l’abilitazione di pulsanti / menù / toolbar
            try:
                self._update_buttons_enabled()
            except Exception:
                pass

    def _probe_src_fps(self, f: Path) -> float | None:
        try:
            out = subprocess.check_output(
                [
                    C.FFPROBE_BIN,
                    "-v","error",
                    "-select_streams","v:0",
                    "-show_entries","stream=avg_frame_rate",
                    "-of","default=nokey=1:noprint_wrappers=1",
                    str(f),
                ],
                text=True,
            ).strip()
            if not out:
                return None
            if "/" in out:
                n, d = out.split("/", 1)
                n = float(n)
                d = float(d) if float(d) != 0 else 1.0
                return n / d
            return float(out)
        except Exception:
            return None

    def _apply_detected_fps(self, fps: float) -> None:
        def _to_float(s: str) -> float | None:
            try:
                return float(s)
            except Exception:
                return None

        candidates = [x for x in C.FR_CONST_VALUES if x != "Nessuno"]
        cand_vals = [(_to_float(x), x) for x in candidates]
        cand_vals = [(v, s) for (v, s) in cand_vals if v is not None]
        best = min(cand_vals, key=lambda p: abs((p[0] or 0.0) - fps))[1] if cand_vals else "Nessuno"

        self.cmb_frval.setCurrentText(best)
        try:
            self.txt_info.append(f"> Frame-rate sorgente: {fps:.3f} fps → suggerito '{best}' (se in modalità Costante).")
        except Exception:
            pass

    @pyqtSlot()
    def open_output_directory(self):
        if not self._last_output:
            QMessageBox.warning(self, "Nessuna directory", "Nessun file convertito finora.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._last_output.parent)))

    @pyqtSlot()
    def open_file(self):
        f, _ = QFileDialog.getOpenFileName(
            self,
            "Seleziona file video",
            str(Path.home()),
            "Video (*.mp4 *.mkv *.mov *.avi *.m4v *.ts);;Tutti i file (*)",
        )
        if f:
            self.edit_path.setText(f)

    def ask_output_path(self, suggested: Path) -> Path | None:
        p, _ = QFileDialog.getSaveFileName(
            self,
            "Scegli file di uscita",
            str(suggested),
            "MKV (*.mkv);;MP4 (*.mp4);;Tutti i file (*)",
        )
        return Path(p) if p else None
    
    @pyqtSlot()
    def reset_gui_only(self):
        # 🔴 Crop: spegni e DIMENTICA anche il rettangolo (come dopo un riavvio)
        try:
            from hevc_gui.video.crop_tools import clear_crop_settings
            clear_crop_settings(disable_only=False)
            if hasattr(self, "txt_info"):
                self.txt_info.append("[DBG] Crop azzerato (rettangolo incluso).")
        except Exception:
            pass

        # Ripristina solo la GUI (campi, log, progress bar),
        # senza cancellare tmp/ né il file queue.json.

        # 1) Percorso e stato file
        self.edit_path.clear()
        self._current_file = None
        self._last_output = None

        # 2) Filtri e opzioni
        self.cmb_br.setCurrentIndex(0)
        self.cmb_crf.setCurrentIndex(0)
        self.cmb_preset.setCurrentIndex(0)
        self.cmb_sharp.setCurrentIndex(0)
        self.cmb_smth.setCurrentIndex(0)
        self.cmb_resize.setCurrentIndex(0)
        self.rd_color.setChecked(True)
        self.rd_bw.setChecked(False)
        self.chk_deint.setChecked(False)
        self._filters.clear()

        # 3) Audio / subs / capitoli
        self._audio_opts.clear()
        self._subtitle_inputs.clear()
        self._subtitle_langs.clear()
        self._subtitle_types.clear()
        self._chapter_opts.clear()
        self._chapters_handled = False
        self._subs_integrated_count = 0

        # 4) Log e progress
        self.txt_info.clear()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.lbl_status.setText("Wait for conversion…")
        self.lbl_elapsed.setText("Elapsed: 00:00")
        self.lbl_remaining.setText("Remaining: --:--")
        self._audio_progress = {}

        self._last_queue_cmds = []
        self._last_ffmpeg_log = ""
        self.btn_copy_log.setEnabled(False)

        # 5) Frame-rate: default come all’avvio → "Originale"/"Nessuno"
        for _label in ("Originale", "Nessuno"):
            if _label in C.FR_MODE:
                self.cmb_frmode.setCurrentText(_label)
                break
        else:
            self.cmb_frmode.setCurrentIndex(0)

        # La combo valore resta disabilitata finché non scegli "Costante"
        self.cmb_frval.setEnabled(self.cmb_frmode.currentText() == "Costante")

        # 6) Bottoni allo stato iniziale
        self._update_buttons_enabled()

    @pyqtSlot()
    def extract_audio(self):
        if not self._current_file:
            return
        dlg = AudioConverter(str(self._current_file), parent=self)
        if dlg.exec_() != QDialog.Accepted:
            return

        raw_opts = dlg.batch.items
        self._audio_opts = raw_opts

        self.txt_info.append(f"> Tracce audio selezionate: {len(raw_opts)}")
        import shlex

        for cmd in raw_opts:
            toks = [str(t).lower() for t in cmd]
            is_51 = (
                "ac3" in toks
                or "eac3" in toks
                or any(t == "-ac" and (i + 1 < len(toks) and toks[i + 1] == "6") for i, t in enumerate(toks))
                or any(("channel_layout=5.1" in t) or ("pan=5.1" in t) or ("join=inputs=6" in t) for t in toks)
            )
            line = "  " + " ".join(shlex.quote(a) for a in cmd)
            if is_51:
                line += "   [🔊 5.1]"
            self.txt_info.append(line)

        self.btn_subtitle.setEnabled(True)
        self.btn_chapter.setEnabled(True)
        self.btn_convert.setEnabled(True)

    @pyqtSlot()
    def _audio_extract_finished(self, p: QProcess):
        raw = bytes(p.readAllStandardOutput()).decode().strip()
        err = bytes(p.readAllStandardError()).decode().strip()
        if err:
            self.txt_info.append(f"[stderr helper]\n{err}\n")
        self.txt_info.append(f"[DEBUG] raw audio extraction output: {raw!r}")

        if not raw:
            self._audio_opts = []
            self.txt_info.append("! Nessuna traccia audio aggiunta.")
            return

        try:
            raw_opts = json.loads(raw)
            self._audio_opts = raw_opts
            self.txt_info.append(f"[DEBUG] _audio_opts = {self._audio_opts}")
            self.txt_info.append(f"> Opzioni audio ricevute: {len(raw_opts)} tracce")
        except Exception as e:
            self._audio_opts = []
            self.txt_info.append(f"! Errore estrazione audio: {e}")

    def show_mediainfo(self):
        if not self._current_file:
            QMessageBox.information(self, "MediaInfo", "Nessun file selezionato.")
            return
        MediaInfoDialog(self._current_file, self).exec_()

    def open_crop_tool(self):
        if not self._current_file:
            QMessageBox.information(self, "Crop", "Seleziona prima un file video.")
            return
        try:
            from hevc_gui.gui.crop_dialog import CropDialog
        except Exception as e:
            QMessageBox.critical(self, "Errore", f"Modulo crop non disponibile:\n{e}")
            return

        dlg = CropDialog(str(self._current_file), parent=self)  # ← passa il path
        if dlg.exec_() == dlg.Accepted:
            # aggiorna la Preview filtrata se esiste
            for name in ("on_preview_filtered_clicked","_on_preview_filtered","preview_filtered","start_preview_filtered"):
                fn = getattr(self, name, None)
                if callable(fn):
                    try: fn()
                    except Exception: pass
                    break

    def _bw_filter(self) -> str:
        return "hue=s=0,format=yuv420p" if self.rd_bw.isChecked() else ""

    def update_filters(self):
        self._filters.clear()
        if self.chk_deint.isChecked():
            self._filters.append("yadif=1:-1:0")
        for cmb, src in (
            (self.cmb_sharp, C.SHARPNESS_LEVELS),
            (self.cmb_smth, C.SMOOTHNESS_LEVELS),
            (self.cmb_resize, C.RESOLUTIONS),
        ):
            val = src[cmb.currentText()]
            if val and val not in self._filters:
                self._filters.append(val)

    @pyqtSlot()
    def launch_preview(self, filtered=False):
        import re  # serve per trovare scale numerico
        if self.preview_proc and self.preview_proc.state() == QProcess.Running:
            return
        if not self._current_file:
            return

        ffplay = getattr(C, "FFPLAY_BIN", "ffplay")
        args = [
            ffplay, "-autoexit",
            "-window_title", "HEVC-Video Converter - Preview",
            "-x", "800", "-y", "600",
        ]

        if filtered:
            # 1) filtri di base accumulati dalla GUI
            vf_parts = list(getattr(self, "_filters", []))

            # 2) B/N come nel builder
            def _bw_filter_local():
                if getattr(self, "rd_bw", None) and self.rd_bw.isChecked():
                    return "hue=s=0"
                return ""
            bw = _bw_filter_local()
            if bw and not any(("hue=" in f and "s=0" in f) or ("format=gray" in f) for f in vf_parts):
                vf_parts.append(bw)

            # 3) Crop + flag dal dialog (retrocompatibile)
            try:
                ret = load_crop_settings()
                if len(ret) >= 2:
                    spec, enabled = ret[0], ret[1]
                    force_169 = bool(ret[2]) if len(ret) >= 3 else False
                    force_scope = bool(ret[3]) if len(ret) >= 4 else False
                else:
                    spec, enabled = (None, False)
                    force_169 = force_scope = False
            except Exception:
                spec, enabled = (None, False)
                force_169 = force_scope = False

            if enabled and spec:
                inject_crop(vf_parts, spec)
                self._log(f"[DBG] Preview: crop {spec.w}x{spec.h}+{spec.x}+{spec.y}")
            else:
                self._log("[DBG] Preview: crop non attivo")

            # 4) FOAR=decrease e PAD dopo lo scale numerico (come nel builder)
            scale_idx = -1
            target_w = target_h = None
            for i, f in enumerate(vf_parts):
                m = re.search(r"scale\s*=\s*(\d+)\s*:\s*(\d+)", f.replace(" ", ""))
                if m:
                    scale_idx = i
                    target_w = int(m.group(1))
                    target_h = int(m.group(2))
                    break

            if scale_idx >= 0 and target_w and target_h:
                orig = vf_parts[scale_idx].strip()
                if "force_original_aspect_ratio=" not in orig.replace(" ", ""):
                    sep = ":" if ":" in orig else ":"
                    vf_parts[scale_idx] = orig + sep + "force_original_aspect_ratio=decrease"

                # pad target per evitare stretch in preview
                pad_str = f"pad={target_w}:{target_h}:( {target_w}-iw )/2:( {target_h}-ih )/2".replace(" ", "")
                # inserisci subito dopo lo scale, se non presente già un pad identico
                if not any(s.startswith(f"pad={target_w}:{target_h}:") for s in vf_parts):
                    vf_parts.insert(scale_idx + 1, pad_str)

            # 5) setdar forzato (no stretch)
            if not any(s.strip().startswith("setdar=") for s in vf_parts):
                if force_169:
                    vf_parts.append("setdar=16/9")
                elif force_scope:
                    vf_parts.append("setdar=2.35/1")

            chain = ",".join(vf_parts)
            if chain:
                args += ["-vf", chain]

        # Sorgente
        args.append(str(self._current_file))

        # Avvia ffplay
        p = QProcess(self)
        self.preview_proc = p
        p.setProcessChannelMode(QProcess.MergedChannels)
        p.finished.connect(self._on_preview_finished)
        p.start(args[0], args[1:])

    @pyqtSlot()
    def _on_preview_finished(self):
        self.preview_proc = None

    def _probe_duration(self, f: Path) -> float:
        try:
            out = subprocess.check_output(
                [
                    C.FFPROBE_BIN, "-v","error",
                    "-show_entries","format=duration",
                    "-of","default=noprint_wrappers=1:nokey=1",
                    str(f),
                ],
                text=True,
            )
            return float(out.strip()) or 1.0
        except Exception as e:
            self.txt_info.append(f"Errore lettura durata: {e}")
            QMessageBox.warning(
                self,
                "Errore FFprobe",
                f"Non posso misurare la durata del file video:\n{e}\n\nControlla che ffprobe sia installato e accessibile.",
            )
            return 1.0

    def build_ffmpeg_video_cmd(self, video_tmp: Path) -> list[str]:
        """
        Ricodifica video secondo i parametri GUI.
        Fix inclusi:
          - scale numerico → force_original_aspect_ratio=decrease + pad=W:H:(W-iw)/2:(H-ih)/2
          - sposta -threads e -x265-params PRIMA dell'output
        Mantiene: crop, auto-colorimetria, B/N, FR, ecc.
        """
        import os, re, json, subprocess  # safe import locali
        # C è importato a livello modulo: from ..core import constants as C

        cmd = [C.FFMPEG_BIN, "-y", "-nostdin", "-i", str(self._current_file)]

        # --- Costruzione catena -vf ------------------------------------------------
        vf_parts: list[str] = []

        # Deinterlace
        if getattr(self, "chk_deint", None) and self.chk_deint.isChecked():
            vf_parts.append("yadif=1:-1:0")

        # Filtri base da GUI
        for cmb, levels in (
            (getattr(self, "cmb_sharp",  None), C.SHARPNESS_LEVELS),
            (getattr(self, "cmb_smth",   None), C.SMOOTHNESS_LEVELS),
            (getattr(self, "cmb_resize", None), C.RESOLUTIONS),
        ):
            if cmb is None:
                continue
            val = levels.get(cmb.currentText(), "")
            if val:
                vf_parts.append(val)

        # B/N coerente (evita doppioni)
        def _bw_filter_local():
            if getattr(self, "rd_bw", None) and self.rd_bw.isChecked():
                return "hue=s=0"
            return ""
        bw = _bw_filter_local()
        if bw and not any(("hue=" in f and "s=0" in f) or ("format=gray" in f) for f in vf_parts):
            vf_parts.append(bw)

        # --- Crop dai Settings: prima dello scale ----------------------------------
        # retrocompat: load_crop_settings può restituire (spec, enabled) o (spec, enabled, extra...)
        try:
            ret = load_crop_settings()
            # unpack flessibile
            if len(ret) >= 2:
                spec, enabled = ret[0], ret[1]
                force_169 = bool(ret[2]) if len(ret) >= 3 else False
                force_scope = bool(ret[3]) if len(ret) >= 4 else False
            else:
                spec, enabled = (None, False)
                force_169 = force_scope = False
        except Exception:
            spec, enabled = (None, False)
            force_169 = force_scope = False

        if enabled and spec:
            inject_crop(vf_parts, spec)
            try:
                self.txt_info.append(f"[DBG] Crop attivo: {spec.w}x{spec.h}+{spec.x}+{spec.y}")
            except Exception:
                pass
        else:
            try:
                self.txt_info.append("[DBG] Crop disattivato o assente.")
            except Exception:
                pass

        # --- Autofix SAR/DAR per target SD (opzionale) ----------------------------
        try:
            if getattr(C, "ASPECT_AUTOFIX", False):
                has_scale_720_576 = any(f.replace(" ", "") == "scale=720:576" for f in vf_parts)
                has_aspect_set = any(("setsar=" in f) or ("setdar=" in f) for f in vf_parts)
                if has_scale_720_576 and not has_aspect_set:
                    probe_cmd = [
                        C.FFPROBE_BIN, "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height,sample_aspect_ratio,display_aspect_ratio",
                        "-of", "json", str(self._current_file),
                    ]
                    out = subprocess.run(probe_cmd, capture_output=True, text=True, check=True).stdout
                    st = json.loads(out)["streams"][0]
                    w = float(st.get("width", 0) or 0); h = float(st.get("height", 0) or 0)

                    def _ratio(s):
                        try:
                            s = s or "1:1"
                            if ":" in s:
                                n, d = s.split(":")
                                return float(n) / float(d)
                            return float(s)
                        except Exception:
                            return None

                    sar = _ratio(st.get("sample_aspect_ratio"))
                    dar = _ratio(st.get("display_aspect_ratio"))
                    if dar is None and w > 0 and h > 0:
                        dar = (w / h) * (sar if sar else 1.0)

                    def _is_close(x, target, tol=0.02):
                        try: return abs(x - target) <= tol
                        except Exception: return False

                    if dar is not None:
                        if _is_close(dar, 16/9):
                            vf_parts.append(f"setsar={C.PAL_SAR_16_9},setdar=16/9")
                        elif _is_close(dar, 4/3):
                            vf_parts.append(f"setsar={C.PAL_SAR_4_3},setdar=4/3")
        except Exception:
            pass

        # --- AUTO-COLORIMETRIA + FOAR=decrease & PAD ------------------------------
        scale_idx = -1
        target_w = target_h = None
        for i, f in enumerate(vf_parts):
            m = re.search(r"scale\s*=\s*(\d+)\s*:\s*(\d+)", f.replace(" ", ""))
            if m:
                scale_idx = i
                target_w = int(m.group(1))
                target_h = int(m.group(2))
                break

        forcing_matrix = None  # "bt470bg" / "bt709"
        try:
            if scale_idx >= 0 and target_h:
                # Matrice di ARRIVO in base al target
                if (target_w, target_h) in ((720, 576), (720, 480), (720, 486)):
                    forcing_matrix = "bt470bg"
                elif target_w >= 1280 or target_h >= 720:
                    forcing_matrix = "bt709"

                if forcing_matrix:
                    # Matrice d'INGRESSO
                    try:
                        meta = subprocess.check_output(
                            [
                                C.FFPROBE_BIN, "-v", "error", "-select_streams", "v:0",
                                "-show_entries", "stream=width,height,color_space",
                                "-of", "json", str(self._current_file),
                            ],
                            text=True,
                        )
                        js = json.loads(meta)["streams"][0]
                        in_matrix = js.get("color_space") or js.get("matrix_coefficients")
                        if not in_matrix:
                            sw = int(js.get("width", 0) or 0)
                            sh = int(js.get("height", 0) or 0)
                            in_matrix = "bt709" if (sw >= 1280 or sh >= 720) else "bt470bg"
                    except Exception:
                        in_matrix = "bt709"

                    # Riscrivi lo scale con in/out matrix + flags + FOAR
                    orig = vf_parts[scale_idx].strip()
                    compact = orig.replace(" ", "")
                    has_in   = "in_color_matrix="  in compact
                    has_out  = "out_color_matrix=" in compact
                    has_flag = "flags=" in compact
                    has_foar = "force_original_aspect_ratio=" in compact

                    prefix = re.sub(r"(scale\s*=\s*\d+\s*:\s*\d+).*", r"\1", compact)
                    extras = []
                    if not has_in:
                        extras.append(f"in_color_matrix={in_matrix}")
                    if not has_out:
                        extras.append(f"out_color_matrix={forcing_matrix}")
                    if not has_flag:
                        extras.append("flags=lanczos")
                    if not has_foar:
                        extras.append("force_original_aspect_ratio=decrease")

                    vf_parts[scale_idx] = prefix + (":" + ":".join(extras) if extras else "")

                    # Tag contenitore coerente (solo colorspace)
                    cmd += ["-colorspace", forcing_matrix]

                    try:
                        self.txt_info.append(
                            f"[DBG] Auto colorimetria: {in_matrix} → {forcing_matrix} (scale {target_w}x{target_h})"
                        )
                    except Exception:
                        pass
            elif scale_idx >= 0:
                # Nessuna decisione sulla matrice, ma aggiungi comunque FOAR=decrease
                orig = vf_parts[scale_idx].strip()
                if "force_original_aspect_ratio=" not in orig.replace(" ", ""):
                    sep = ":" if ":" in orig else ":"
                    vf_parts[scale_idx] = orig + sep + "force_original_aspect_ratio=decrease"
        except Exception as e:
            try:
                self.txt_info.append(f"[WARN] Auto colorimetria/FOAR non applicata: {e}")
            except Exception:
                pass

        # PAD dopo lo scale (se presente) per evitare deformazioni
        if scale_idx >= 0 and (target_w and target_h):
            pad_regex = re.compile(r"pad\s*=\s*(\d+)\s*:\s*(\d+)", re.I)
            already_same_pad = False
            for f in vf_parts:
                m = pad_regex.search(f.replace(" ", ""))
                if m and int(m.group(1)) == target_w and int(m.group(2)) == target_h:
                    already_same_pad = True
                    break
            if not already_same_pad:
                pad_str = f"pad={target_w}:{target_h}:( {target_w}-iw )/2:( {target_h}-ih )/2"
                vf_parts.insert(scale_idx + 1, pad_str.replace(" ", ""))

        # Eventuale setdar forzato (da dialog crop)
        if not any(s.strip().startswith("setdar=") for s in vf_parts):
            if force_169:
                vf_parts.append("setdar=16/9")
            elif force_scope:
                vf_parts.append("setdar=2.35/1")

        # Debug filtri
        try:
            sharp_lbl = getattr(self, "cmb_sharp", None).currentText() if getattr(self, "cmb_sharp", None) else ""
            sharp_val = C.SHARPNESS_LEVELS.get(sharp_lbl, "")
            self.txt_info.append(f"[DBG] Sharpness: '{sharp_lbl}' → {sharp_val or '(nessuno)'}")
            self.txt_info.append(f"[DBG] -vf = {','.join(vf_parts)}")
        except Exception:
            pass

        if vf_parts:
            cmd += ["-vf", ",".join(vf_parts)]

        # --- Codec e parametri base ------------------------------------------------
        cmd += ["-map", "0:v:0", "-c:v", "libx265"]
        preset = getattr(self, "cmb_preset", None).currentText() if getattr(self, "cmb_preset", None) else "faster"
        if preset and preset != "Nessuno":
            cmd += ["-preset", preset]

        # bitrate vs CRF
        if getattr(self, "cmb_br", None) and self.cmb_br.isEnabled():
            br = self.cmb_br.currentText()
            if br and br != "Nessuno":
                cmd += ["-b:v", br, "-maxrate", "1500k", "-bufsize", "2000k"]
        else:
            crf = getattr(self, "cmb_crf", None).currentText() if getattr(self, "cmb_crf", None) else "24"
            if crf and crf != "Nessuno":
                cmd += ["-crf", crf]

        # Frame-rate
        fr_mode = getattr(self, "cmb_frmode", None).currentText().strip() if getattr(self, "cmb_frmode", None) else ""
        fr_val  = getattr(self, "cmb_frval",  None).currentText().strip() if getattr(self, "cmb_frval",  None) else ""
        try:
            self.txt_info.append(f"[DBG] FR: mode='{fr_mode}' value='{fr_val}'")
        except Exception:
            pass
        if fr_mode == "Costante" and fr_val and fr_val != "Nessuno":
            try:
                fr = str(float(fr_val)).rstrip("0").rstrip(".")
            except Exception:
                fr = fr_val
            cmd += ["-r", fr, "-vsync", "cfr"]
        elif fr_mode == "Variabile":
            cmd += ["-vsync", "vfr"]
        else:
            cmd += ["-vsync", "0"]

        # Formato e level
        cmd += ["-pix_fmt", "yuv420p", "-profile:v", "main", "-level", "4.0"]

        # --- Thread e x265-params: PRIMA dell'output ------------------------------
        pools = os.getenv("HEVC_X265_POOLS", "2")
        ft    = os.getenv("HEVC_X265_FRAME_THREADS", "1")

        if "-threads" not in cmd:
            cmd += ["-threads", os.getenv("HEVC_V_THREADS", "2")]

        x265_params_val = f"pools={pools}:frame-threads={ft}"
        if 'forcing_matrix' in locals() and forcing_matrix:
            x265_params_val += f":colormatrix={forcing_matrix}"

        try:
            xidx = cmd.index("-x265-params")
            if xidx + 1 < len(cmd):
                val = cmd[xidx + 1]
                if "pools=" not in val:
                    val = f"{x265_params_val}" + (":" + val if val else "")
                elif 'forcing_matrix' in locals() and forcing_matrix and "colormatrix=" not in val:
                    val += f":colormatrix={forcing_matrix}"
                cmd[xidx + 1] = val
        except ValueError:
            cmd += ["-x265-params", x265_params_val]

        # --- Output ---------------------------------------------------------------
        cmd += [str(video_tmp)]
        return cmd

    def build_ffmpeg_external_audio_cmd(
        self,
        audio_file: str,
        idx: int,
        audio_dir: Path,
        video_id: Optional[int] = None,
        for_queue: bool = False,
    ) -> tuple[Path, list[str]]:
        import shlex

        spec = list(self._audio_opts[idx]) if 0 <= idx < len(self._audio_opts) else []
        spec = self._clean_opts(spec)

        def _get_flag(seq, keys, default=None):
            for k in keys:
                if k in seq:
                    p = seq.index(k)
                    if p + 1 < len(seq):
                        return seq[p + 1]
            return default

        codec = (_get_flag(spec, ["-c:a", "-c:a:0"], "aac") or "aac").lower()
        if codec == "aac":
            ext = ".m4a"
            container = ["-f", "ipod"]
            tail = ["-movflags", "+faststart"]
        elif codec in ("ac3", "eac3"):
            ext = "." + codec
            container = ["-f", codec]
            tail = []
        else:
            ext = ".mka"
            container = ["-f", "matroska"]
            tail = []

        fname = (
            f"track_{'QUEUE_' if for_queue else ''}{video_id}_{idx}{ext}"
            if video_id is not None
            else f"track_ext{idx}{ext}"
        )
        out = audio_dir / fname

        cmd = [C.FFMPEG_BIN, "-y", "-nostdin"]

        if "-i" not in spec:
            spec = ["-i", audio_file] + spec
        else:
            i = spec.index("-i")
            if i + 1 < len(spec):
                spec[i + 1] = audio_file
        if "-vn" not in spec:
            spec += ["-vn"]

        if "-af" not in spec:
            try:
                gui_filters = self._ac_collect_audio_filters_from_ui()
            except Exception:
                gui_filters = []

            if gui_filters:
                af_chain = "aresample=resampler=soxr," + join_filters(gui_filters)
            else:
                af_chain = "aresample=resampler=soxr,dynaudnorm=f=250:g=31:p=0.95:m=50"

            spec += ["-af", af_chain]
            try:
                self.txt_info.append(f"[DBG] external -af = {af_chain}")
            except Exception:
                pass

        cmd += spec + container + tail

        if "-filter_threads" not in cmd:
            cmd += ["-filter_threads", "1"]
        if "-threads" not in cmd:
            cmd += ["-threads", "1"]

        cmd += [str(out)]

        try:
            self.txt_info.append("[DEBUG] external audio cmd: " + shlex.join(cmd))
        except Exception:
            pass

        return out, cmd

    def build_ffmpeg_audio_cmds(
        self, audio_dir: Path, video_id: Optional[int] = None, for_queue: bool = False
    ) -> list[tuple[Path, list[str]]]:
        import re
        import shlex
        from hevc_gui.core.constants import AUDIO_EXTS

        steps: list[tuple[Path, list[str]]] = []
        if not getattr(self, "_audio_opts", None):
            return steps

        br_map: dict[int, str] = {}
        for idx, spec in enumerate(self._audio_opts):
            for j, tok in enumerate(spec):
                if tok.startswith("-b:a") and j + 1 < len(spec):
                    br_map[idx] = spec[j + 1]
                    break

        in_video = str(self._current_file) if self._current_file else None

        for i, spec in enumerate(self._audio_opts):
            if not isinstance(spec, (list, tuple)) or not spec:
                continue

            if len(spec) >= 2 and spec[0] == "-i" and Path(spec[1]).suffix.lower() in AUDIO_EXTS:
                out, cmd = self.build_ffmpeg_external_audio_cmd(
                    audio_file=spec[1],
                    idx=i,
                    audio_dir=audio_dir,
                    video_id=video_id,
                    for_queue=for_queue,
                )
                steps.append((out, cmd))
                continue

            def _norm_flag(t: str) -> str:
                m = re.match(r"^-(c:a|ac|b:a|ar|af)(?::\d+)?$", t)
                return f"-{m.group(1)}" if m else t

            toks = [_norm_flag(t) for t in list(spec)]

            def _get_flag(seq, keys, default=None):
                for k in keys:
                    if k in seq:
                        p = seq.index(k)
                        if p + 1 < len(seq):
                            return seq[p + 1]
                return default

            codec = (_get_flag(toks, ["-c:a"], "aac") or "aac").lower()
            if codec == "aac":
                ext = ".m4a"
                container = ["-f", "ipod"]
                tail = ["-movflags", "+faststart"]
            elif codec in ("ac3", "eac3"):
                ext = f".{codec}"
                container = ["-f", codec]
                tail = []
            else:
                ext = ".mka"
                container = ["-f", "matroska"]
                tail = []

            base = f"track_{'QUEUE_' if for_queue else ''}{video_id}_{i}" if video_id is not None else f"track{i}"
            out = audio_dir / (base + ext)

            cmd = [C.FFMPEG_BIN, "-y", "-nostdin"]
            if in_video:
                cmd += ["-i", in_video]
            cmd += ["-vn", "-async", "1"]

            it = iter(toks)
            while True:
                try:
                    tok = next(it)
                except StopIteration:
                    break

                if tok == "-map":
                    idx_map = next(it, "")
                    m = re.match(r"^0:a:(\d+)$", idx_map)
                    if m:
                        new_idx = max(int(m.group(1)) - 1, 0)
                        idx_map = f"0:a:{new_idx}"
                    cmd += ["-map", idx_map]

                elif re.match(r"^-metadata(?::s:a(?::\d+)?)?$", tok):
                    val = next(it, "")
                    cmd += [tok, val]

                elif re.match(r"^-(?:c:a|ac|b:a|ar|af)$", tok):
                    val = next(it, "")
                    cmd += [tok, val]

                else:
                    pass

            if i in br_map and "-b:a" not in cmd:
                try:
                    pos = cmd.index("-c:a") + 2
                except ValueError:
                    pos = len(cmd)
                cmd[pos:pos] = ["-b:a", br_map[i]]

            if "-af" not in cmd:
                try:
                    gui_filters = self._ac_collect_audio_filters_from_ui()
                except Exception:
                    gui_filters = []

                if gui_filters:
                    af_chain = "aresample=resampler=soxr," + join_filters(gui_filters)
                else:
                    af_chain = "aresample=resampler=soxr,dynaudnorm=f=250:g=31:p=0.95:m=50"

                try:
                    insert_at = cmd.index("-vn") + 1
                except ValueError:
                    insert_at = len(cmd)
                cmd[insert_at:insert_at] = ["-af", af_chain]

                try:
                    self.txt_info.append(f"[DBG] internal -af = {af_chain}")
                except Exception:
                    pass

            cmd += container + tail + [str(out)]

            if "-filter_threads" not in cmd:
                cmd += ["-filter_threads", "1"]
            if "-threads" not in cmd:
                cmd += ["-threads", "1"]

            self.txt_info.append("[DEBUG] audio cmd: " + shlex.join(cmd))
            steps.append((out, cmd))

        return steps

    @staticmethod
    def get_base_name(p: Union[str, Path]) -> str:
        return Path(p).stem

    @staticmethod
    def extract_audio_titles(raw_audio_opts: List[List[str]]) -> List[str]:
        titles: List[str] = []
        for opts in raw_audio_opts:
            for tok in opts:
                if tok.startswith("title="):
                    titles.append(tok.split("=", 1)[1])
                    break
        return titles

    @pyqtSlot(int, QProcess.ExitStatus)
    def _on_video_finished(self, exit_code: int, exit_status: QProcess.ExitStatus):
        if getattr(self, "_tick_timer", None):
            self._tick_timer.stop()
            self._tick_timer.deleteLater()
            self._tick_timer = None

        self.progress.setValue(100)

        if exit_code != 0:
            QMessageBox.critical(self, "Errore video", f"Ricodifica video fallita (code {exit_code})")
            self._full_reset()
            return

        if not Path(self.video_tmp).is_file():
            self.txt_info.append(f"[ERROR] Output video non trovato: {self.video_tmp}")
            QMessageBox.critical(self, "Errore", f"Output video non trovato:\n{self.video_tmp}")
            self._full_reset()
            return

        self.txt_info.append(f"[DEBUG] Video pronto: {self.video_tmp}")
        self._run_audio()

    @pyqtSlot()
    def _run_audio(self):
        """Step 2 — Ricodifica tracce audio in sequenza."""
        self.txt_info.append("[DEBUG] ▶️ _run_audio start")

        dur = float(getattr(self, "_total_duration", 1.0) or 1.0)
        self._start_timer(dur)

        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.lbl_status.setText("🎵 Ricodifica tracce audio…")

        video_id = getattr(self, "_current_video_id", None)
        if video_id is None:
            QMessageBox.critical(self, "Errore", "ID video non trovato per audio.")
            return

        audio_steps = self.build_ffmpeg_audio_cmds(audio_dir=self.audio_dir, video_id=video_id, for_queue=False)

        if not audio_steps:
            if not self._allow_silent and not getattr(self, "audio_externo", False):
                QMessageBox.information(self, "Audio", "Nessuna traccia audio da codificare.")
            self._allow_silent = False
            self._run_mux()
            return

        self._audio_cmds_serial = []
        for out, cmd in audio_steps:
            self._audio_cmds_serial.append((Path(out), list(cmd)))

        self._audio_progress = {i: 0 for i in range(len(self._audio_cmds_serial))}
        self._audio_procs = []
        self._current_audio_idx = 0
        self._audio_queue_active = 0

        try:
            self.audio_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.txt_info.append(f"[ERROR] impossibile creare audio_dir: {e}")
            QMessageBox.critical(self, "Errore", f"Non posso creare {self.audio_dir}")
            return

        self._start_next_audio_serial()

    def _start_next_audio_serial(self):
        if not hasattr(self, "_audio_cmds_serial"):
            self._audio_cmds_serial = []

        while getattr(self, "_audio_queue_active", 0) < getattr(C, "MAX_AUDIO_JOBS", 1) and getattr(self, "_current_audio_idx", 0) < len(
            self._audio_cmds_serial
        ):
            idx = self._current_audio_idx
            out, cmd = self._audio_cmds_serial[idx]

            try:
                cmd_str = " ".join(shlex.quote(a) for a in cmd)
            except Exception:
                cmd_str = " ".join(cmd)
            self.txt_info.append(f"[DEBUG] Avvio audio seriale #{idx}: {cmd_str}")

            p = QProcess(self)
            p.audio_index = idx
            p.audio_out = Path(out)
            self._audio_procs.append(p)
            self.ffmpeg_proc = p

            p.setWorkingDirectory(str(self.audio_dir))
            p.setProcessChannelMode(QProcess.MergedChannels)
            p.readyReadStandardOutput.connect(self._progress_update)
            p.readyReadStandardError.connect(self._progress_update)
            p.finished.connect(self._on_audio_finished_serial)

            cmd = self._wrap_with_cpu_limits(cmd)
            p.start(cmd[0], cmd[1:])

            self._audio_queue_active = getattr(self, "_audio_queue_active", 0) + 1
            self._current_audio_idx += 1

    @pyqtSlot(int, QProcess.ExitStatus)
    def _on_audio_finished_serial(self, exit_code, exit_status):
        p = self.sender()
        idx = getattr(p, "audio_index", -1)
        out = getattr(p, "audio_out", None)

        if hasattr(self, "_audio_progress") and idx in self._audio_progress:
            self._audio_progress[idx] = 100
            overall = sum(self._audio_progress.values()) / max(1, len(self._audio_progress))
            self.progress.setValue(int(overall))
            self._progress_frac = max(0.0, min(0.99, overall / 100.0))

        if exit_code != 0:
            QMessageBox.critical(self, "Errore audio", f"Traccia {idx} fallita (code {exit_code})")
        else:
            if out and not Path(out).is_file():
                self.txt_info.append(f"[ERROR] Output audio mancante (traccia {idx}): {out}")
                QMessageBox.critical(self, "Errore audio", f"Output mancante:\n{out}")
                self._stop_timer()
                self.btn_pause.setEnabled(False)
                self.btn_cancel.setEnabled(False)
                return

        self._audio_queue_active = max(0, self._audio_queue_active - 1)
        if self._current_audio_idx < len(self._audio_cmds_serial):
            self._start_next_audio_serial()
            return

        if self._audio_queue_active == 0:
            self.txt_info.append("[DEBUG] Tutte tracce audio pronte, lancio mux…")
            self.lbl_status.setText("🔗 Muxing…")
            self._start_timer(self._total_duration)
            self._run_mux()

    @pyqtSlot(int, QProcess.ExitStatus)
    def _audio_finished(self, exit_code, exit_status):
        proc = self.sender()
        idx = getattr(proc, "audio_index", -1)

        if hasattr(self, "_audio_progress") and idx in self._audio_progress:
            self._audio_progress[idx] = 100
            overall = sum(self._audio_progress.values()) / len(self._audio_progress)
            self.progress.setValue(int(overall))

        if exit_code != 0:
            QMessageBox.critical(self, "Errore audio", f"Traccia {idx} fallita (code {exit_code})")
            return

        if all(p.state() != QProcess.Running for p in self._audio_procs):
            self.txt_info.append("[DEBUG] Tutte tracce audio pronte, lancio mux…")
            self.lbl_status.setText("🔗 Muxing…")
            self._start_timer(self._total_duration)
            self._run_mux()

    def _clean_opts(self, opts: list[str]) -> list[str]:
        import re
        cleaned: list[str] = []
        i = 0
        while i < len(opts):
            key = opts[i]
            if re.match(r"^-b:(?:a|v)(?::\d+)?$", key):
                if i + 1 < len(opts):
                    val = opts[i + 1]
                    if re.match(r"^\d+(?:[kKmM])?$", val):
                        cleaned += [key, val]
                    i += 2
                    continue
            cleaned.append(key)
            i += 1
        return cleaned

    def build_ffmpeg_mux_cmd(
        self,
        *,
        input_mkv: Union[str, Path],
        video_temp: Union[str, Path],
        audio_files: List[Union[str, Path]],
        raw_audio_opts: List[List[str]],
        chapters_file: Union[str, Path],
        output_mkv: Union[str, Path],
    ) -> List[str]:
        from pathlib import Path

        clean_name = Path(output_mkv).stem
        cmd = [
            C.FFMPEG_BIN,
            "-fflags","+genpts+discardcorrupt",
            "-avoid_negative_ts","make_zero",
            "-y","-nostdin",
            "-i", str(input_mkv),
            "-i", str(video_temp),
        ]

        for a in audio_files:
            cmd += ["-i", str(a)]
        for sub in self._subtitle_inputs:
            cmd += ["-i", str(sub)]

        chap_path = Path(chapters_file)
        if chap_path.is_file():
            cmd += ["-i", str(chap_path)]
            chap_idx = 2 + len(audio_files) + len(self._subtitle_inputs)
            cmd += ["-map_chapters", str(chap_idx)]

        cmd += ["-map", "1:v", "-c:v", "copy", "-metadata:s:v:0", f"title={clean_name}"]

        audio_titles = self.extract_audio_titles(raw_audio_opts)
        for i, title in enumerate(audio_titles):
            inp = 2 + i
            cmd += ["-map", f"{inp}:a", "-c:a", "copy", f"-metadata:s:a:{i}", f"title={title}"]

        track_idx = 0
        internal_count = len(self._subtitle_langs) - len(self._subtitle_inputs)
        for idx in range(internal_count):
            lang = self._subtitle_langs[idx]
            kind = self._subtitle_types[idx]
            cmd += [
                "-map", f"0:s:{idx}",
                "-c:s","copy",
                f"-metadata:s:s:{track_idx}", f"language={lang}",
                f"-metadata:s:s:{track_idx}", f"title=Subs {track_idx + 1} – {lang} [{kind}]",
            ]
            if kind in ("forced", "default", "sdh"):
                cmd += [f"-disposition:s:{track_idx}", kind]
            track_idx += 1

        base = 2 + len(audio_files)
        for j, (p, lang, kind) in enumerate(
            zip(
                self._subtitle_inputs,
                self._subtitle_langs[-len(self._subtitle_inputs) :],
                self._subtitle_types[-len(self._subtitle_inputs) :],
            )
        ):
            inp = base + j
            cmd += [
                "-map", f"{inp}:s:0",
                "-c:s","copy",
                f"-metadata:s:s:{track_idx}", f"language={lang}",
                f"-metadata:s:s:{track_idx}", f"title=Subs {track_idx + 1} – {lang} [{kind}]",
            ]
            if kind in ("forced", "default", "sdh"):
                cmd += [f"-disposition:s:{track_idx}", kind]
            track_idx += 1

        cmd += [
            "-metadata", f"title={clean_name}",
            "-cluster_time_limit", "20",
            "-cluster_size_limit", "32768",
            "-f", "matroska",
            str(output_mkv),
        ]
        return cmd

    def _build_apply_reverb_and_af(self, cmd: list[str], filters: list[str], *, for_shell: bool = False) -> None:
        try:
            reverb_label = self.ui.cmb_reverb.currentText()
        except Exception:
            try:
                reverb_label = self.cmb_reverb.currentText()
            except Exception:
                reverb_label = ""

        rev_expr = select_reverb_expr(reverb_label)
        if rev_expr:
            filters.append(rev_expr)

        af_chain = join_filters(filters)
        if af_chain:
            add_filter_arg(cmd, "-af", af_chain, for_shell=for_shell)

        try:
            self.txt_info.append(f"[DBG] Reverb: '{reverb_label}' → {rev_expr or '(nessuno)'}")
            self.txt_info.append(f"[DBG] -af = {af_chain or '(vuoto)'}")
        except Exception:
            pass

    def _ac_collect_audio_filters_from_ui(self) -> list[str]:
        filters: list[str] = []

        eq_expr = ""
        try:
            pass
        except Exception:
            pass
        if eq_expr:
            filters.append(eq_expr)

        try:
            if getattr(self, "chk_dialog_boost", None) and self.chk_dialog_boost.isChecked():
                filters.append(C.AUD_DIALOG_BOOST_EQ)
        except Exception:
            pass

        reverb_label = ""
        try:
            reverb_label = self.ui.cmb_reverb.currentText()
        except Exception:
            try:
                reverb_label = self.cmb_reverb.currentText()
            except Exception:
                reverb_label = ""

        rev_expr = select_reverb_expr(reverb_label)
        if rev_expr:
            filters.append(rev_expr)

        return filters

    def _ac_apply_audio_filters_to_cmd(self, cmd: list[str], filters: list[str], *, for_shell: bool = False) -> None:
        af_chain = join_filters(filters)
        if af_chain:
            add_filter_arg(cmd, "-af", af_chain, for_shell=for_shell)

    def _ac_debug_dump_audio_filters(self, filters: list[str]) -> None:
        try:
            self.txt_info.append(f"[DBG] Reverb/EQ chain: {', '.join(filters) or '(vuoto)'}")
            from ..core.helpers import join_filters as _jf
            self.txt_info.append(f"[DBG] -af = {_jf(filters) or '(vuoto)'}")
        except Exception:
            pass

    @pyqtSlot()
    def _run_mux(self):
        self.txt_info.append("[DEBUG] ▶️ _run_mux start")

        self.progress.setFormat("")
        self.progress.setRange(0, 100)
        self._marquee_value = 0
        self._marquee_direction = 1
        QApplication.processEvents()
        self._marquee_timer.start(100)
        self._progress_frac = 0.0

        if not self._draft_mux_cmd:
            QMessageBox.critical(self, "Mux", "Comando di muxing non generato.")
            self._marquee_timer.stop()
            self._stop_marquee()
            return

        cmd = list(self._draft_mux_cmd)
        self.txt_info.append(f"[DEBUG] mux cmd: {shlex.join(cmd)}")

        missing = []
        for idx, tok in enumerate(cmd):
            if tok == "-i" and idx + 1 < len(cmd):
                if not Path(cmd[idx + 1]).exists():
                    missing.append(cmd[idx + 1])
        if missing:
            self.txt_info.append(f"[ERROR] File mancante pre-mux: {missing}")
            QMessageBox.critical(self, "Mux", f"File non trovato: {missing[0]}")
            self._marquee_timer.stop()
            self._stop_marquee()
            return

        p = QProcess(self)
        self.ffmpeg_proc = p
        p.readyReadStandardError.connect(self._on_mux_stderr)
        p.readyReadStandardOutput.connect(self._on_mux_stdout)
        p.finished.connect(self._on_mux_finished)

        cmd = self._wrap_with_cpu_limits(cmd)
        p.start(cmd[0], cmd[1:])

    @pyqtSlot()
    def _on_mux_stdout(self):
        p = self.sender()
        out = bytes(p.readAllStandardOutput()).decode(errors="ignore")
        for line in out.splitlines():
            self.txt_info.append(f"[FFmpeg mux stdout] {line.strip()}")

    @pyqtSlot()
    def _on_mux_stderr(self):
        p = self.sender()
        if not isinstance(p, QProcess):
            return
        err = bytes(p.readAllStandardError()).decode(errors="ignore")
        for line in err.splitlines():
            self.txt_info.append(f"[FFmpeg mux stderr] {line.strip()}")

    @pyqtSlot(int, QProcess.ExitStatus)
    def _on_mux_finished(self, exit_code: int, exit_status: QProcess.ExitStatus):
        self._stop_timer()
        self._marquee_timer.stop()
        self.progress.setFormat("%p%")
        self.progress.setRange(0, 100)

        if exit_code != 0:
            self.txt_info.append(f"[DEBUG] ❌ Mux fallito (exit code {exit_code}).")
            QMessageBox.critical(self, "Mux", f"Mux fallito (codice {exit_code}).")
        else:
            self.progress.setValue(100)
            self.txt_info.append("[DEBUG] ✅ Mux completato con successo.")
            QMessageBox.information(self, "Mux", "✅ Mux completato!")

        self.btn_pause.setEnabled(False)

        def sanitize_audio_opts(opts: List[str]) -> List[str]:
            import re
            sanitized = []
            it = iter(opts)
            for key in it:
                if key == "-b:a" or re.match(r"-b:a:\d+", key):
                    val = next(it)
                    if re.match(r"^\d+k$", val):
                        sanitized.extend([key, val])
                    else:
                        continue
                else:
                    sanitized.append(key)
            return sanitized

    @pyqtSlot()
    def on_convert_clicked(self):
        if not self._current_file:
            return

        if not self._audio_opts and not getattr(self, "audio_externo", False):
            reply = QMessageBox.question(
                self,
                "Attenzione: video senza audio",
                "Non hai estratto alcuna traccia audio.\nIl video risultante sarà muto.\nVuoi comunque procedere?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
            self._allow_silent = True

        if not getattr(self, "_last_output", None):
            out = self.ask_output_path(self._current_file.with_suffix(".mkv"))
            if not out:
                return
            out.parent.mkdir(parents=True, exist_ok=True)
            out.touch(exist_ok=True)
            self._last_output = out

        self.video_dir.mkdir(parents=True, exist_ok=True)
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        vid = 0
        while (self.video_dir / f"video_temp_{vid}.mkv").exists():
            vid += 1
        self._current_video_id = vid
        self.video_tmp = self.video_dir / f"video_temp_{vid}.mkv"
        self._total_duration = self._probe_duration(self._current_file)

        video_cmd = self.build_ffmpeg_video_cmd(self.video_tmp)
        audio_steps = self.build_ffmpeg_audio_cmds(audio_dir=self.audio_dir, video_id=vid, for_queue=False)
        audio_cmds = [cmd for (_o, cmd) in audio_steps]
        self._audio_progress = {i: 0 for i in range(len(audio_cmds))}

        chap_file = Path(self._chapter_opts[1]) if len(self._chapter_opts) >= 2 else Path()

        mux_cmd = self.build_ffmpeg_mux_cmd(
            input_mkv=self._current_file,
            video_temp=self.video_tmp,
            audio_files=[out for (out, _c) in audio_steps],
            raw_audio_opts=self._audio_opts,
            chapters_file=chap_file,
            output_mkv=self._last_output,
        )

        existing = qman.load()
        if existing:
            choice = QMessageBox.question(
                self,
                "Converti / Coda",
                (
                    f"Ci sono {len(existing)} comandi in coda.\n"
                    "Sì → salva ed esegui tutta la coda\n"
                    "No  → esegui solo questo job\n"
                    "Annulla → niente"
                ),
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                QMessageBox.Yes,
            )
            if choice == QMessageBox.Cancel:
                return
            if choice == QMessageBox.Yes:
                for cmd in (video_cmd, *audio_cmds, mux_cmd):
                    qman.add(cmd)
                    with self.queue_tmp_file.open("a", encoding="utf-8") as f:
                        f.write(shlex.join(cmd) + "\n")
                self.command_queue = qman.load()
                self.is_queue_saved = True

                self._draft_mux_cmd = mux_cmd
                self._start_timer(self._total_duration)
                self.btn_pause.setEnabled(True)
                self.btn_cancel.setEnabled(True)
                self.run_queue_in_gui()
                return

        self._draft_mux_cmd = mux_cmd
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.lbl_status.setText("🔨 Ricodifica video…")
        self._start_timer(self._total_duration)
        self.btn_pause.setEnabled(True)
        self.btn_cancel.setEnabled(True)
        self._run_video()

    def _run_single_mux(self, cmd: list[str]) -> QProcess:
        p = QProcess(self)
        p.readyReadStandardError.connect(self._on_mux_stderr)
        p.readyReadStandardOutput.connect(self._on_mux_stdout)
        p.finished.connect(self._on_mux_finished)
        cmd = self._wrap_with_cpu_limits(cmd)
        p.start(cmd[0], cmd[1:])
        self.ffmpeg_proc = p
        self.btn_pause.setEnabled(True)
        self.btn_cancel.setEnabled(True)
        return p

    @pyqtSlot()
    def run_queue_in_gui(self):
        cmds = list(self.command_queue)
        if not cmds:
            QMessageBox.information(self, "Coda vuota", "Non ci sono comandi in coda.")
            return

        batches, batch = [], []
        for cmd in cmds:
            batch.append(cmd)
            if "-fflags" in cmd:
                batches.append(batch)
                batch = []
        if batch:
            QMessageBox.warning(self, "Coda corrotta", "Comandi residui non riconosciuti come mux.")
            return

        for b in (self.btn_convert, self.btn_elabora, self.btn_salva):
            b.setEnabled(False)
        self.btn_pause.setEnabled(True)
        self.btn_cancel.setEnabled(True)

        fail_marks = []

        for idx, bcmds in enumerate(batches, start=1):
            video_cmd, *audio_cmds, mux_cmd = bcmds

            dur = self._probe_duration(self._current_file)
            self._start_timer(dur)

            self.txt_info.append(f"> Batch {idx}: ricodifica video…")
            self.lbl_status.setText("🔨 Ricodifica video…")
            self.progress.setRange(0, 100)

            proc_v = QProcess(self)
            self.ffmpeg_proc = proc_v
            proc_v.setProcessChannelMode(QProcess.MergedChannels)
            proc_v.readyReadStandardOutput.connect(self._progress_update)
            proc_v.readyReadStandardError.connect(self._progress_update)

            loop_v = QEventLoop()
            proc_v.finished.connect(loop_v.quit)
            video_cmd = self._wrap_with_cpu_limits(video_cmd)
            proc_v.start(video_cmd[0], video_cmd[1:])
            loop_v.exec_()

            if proc_v.exitCode() != 0:
                self.txt_info.append(f"❌ Video batch {idx} fallito.")
                fail_marks.append(f"{idx}.VID")
                continue

            self._audio_progress = {i: 0 for i in range(len(audio_cmds))}
            self.txt_info.append(f"> Batch {idx}: ricodifica audio…")
            self.lbl_status.setText("🎵 Ricodifica audio…")
            self.progress.setRange(0, 100)
            self._start_timer(dur)

            for i, cmd in enumerate(audio_cmds):
                p = QProcess(self)
                p.audio_index = i
                self.ffmpeg_proc = p
                p.setProcessChannelMode(QProcess.MergedChannels)
                p.readyReadStandardOutput.connect(self._progress_update)
                p.readyReadStandardError.connect(self._progress_update)

                loop_a = QEventLoop()
                p.finished.connect(loop_a.quit)

                cmd = self._wrap_with_cpu_limits(cmd)
                p.start(cmd[0], cmd[1:])
                loop_a.exec_()

                self._audio_progress[i] = 100
                overall = sum(self._audio_progress.values()) / max(1, len(self._audio_progress))
                self.progress.setValue(int(overall))

                if p.exitCode() != 0:
                    self.txt_info.append(f"⚠️ Audio traccia {i} fallita (batch {idx}).")
                    fail_marks.append(f"{idx}.A{i}")

            self.txt_info.append(f"> Batch {idx}: muxing…")
            self.lbl_status.setText("🔗 Muxing…")
            self.progress.setRange(0, 0)
            self._stop_timer()

            p_m = QProcess(self)
            self.ffmpeg_proc = p_m
            p_m.setProcessChannelMode(QProcess.MergedChannels)
            p_m.readyReadStandardError.connect(self._on_mux_stderr)
            p_m.readyReadStandardOutput.connect(self._on_mux_stdout)

            loop_m = QEventLoop()
            p_m.finished.connect(loop_m.quit)

            mux_cmd = self._wrap_with_cpu_limits(mux_cmd)
            p_m.start(mux_cmd[0], mux_cmd[1:])
            loop_m.exec_()

            self.progress.setRange(0, 100)

            if p_m.exitCode() != 0:
                self.txt_info.append(f"❌ Mux batch {idx} fallito.")
                fail_marks.append(f"{idx}.MUX")
            else:
                self.progress.setValue(100)
                self.txt_info.append(f"✅ Batch {idx} completato!")

        self._stop_timer()
        for b in (self.btn_convert, self.btn_elabora, self.btn_salva):
            b.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self.lbl_status.setText("Wait for conversion…")

        if not fail_marks:
            QMessageBox.information(self, "Coda", "✅ Tutti i lavori in coda sono completati!")
        else:
            seen, ordered = set(), []
            for m in fail_marks:
                if m not in seen:
                    seen.add(m)
                    ordered.append(m)
            QMessageBox.warning(self, "Coda completata con errori", "⚠️ Fallimenti: " + ", ".join(ordered))

    @pyqtSlot()
    def _run_video(self):
        if not self._current_file:
            return
        for d in (self.tmp_dir, self.video_dir, self.audio_dir, self.chapters_dir):
            d.mkdir(parents=True, exist_ok=True)

        cmd = self.build_ffmpeg_video_cmd(self.video_tmp)
        try:
            self.txt_info.append("[DEBUG] video cmd: " + " ".join(shlex.quote(x) for x in cmd))
        except Exception:
            pass

        p = QProcess(self)
        self.ffmpeg_proc = p
        p.setProcessChannelMode(QProcess.MergedChannels)
        p.readyReadStandardOutput.connect(self._progress_update)
        p.readyReadStandardError.connect(self._progress_update)
        p.finished.connect(self._on_video_finished)

        cmd = self._wrap_with_cpu_limits(cmd)
        p.start(cmd[0], cmd[1:])

    def _hms_to_sec(self, hms):
        h, m, s = hms.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)

    @pyqtSlot()
    def _progress_update(self):
        proc = self.sender()
        if not isinstance(proc, QProcess):
            return

        raw_out = bytes(proc.readAllStandardOutput()).decode(errors="ignore")
        raw_err = bytes(proc.readAllStandardError()).decode(errors="ignore")
        raw = raw_out + raw_err
        if raw.strip():
            self.txt_info.append(raw.strip())

        last_time = None
        for line in map(str.strip, raw.splitlines()):
            if line.startswith("out_time_ms="):
                try:
                    last_time = int(line.split("=", 1)[1]) / 1_000_000.0
                except Exception:
                    pass
            elif line.startswith("out_time="):
                try:
                    last_time = self._hms_to_sec(line.split("=", 1)[1])
                except Exception:
                    pass
            else:
                m = re.search(r"time=(\d+:\d+:\d+\.\d+)", line)
                if m:
                    try:
                        last_time = self._hms_to_sec(m.group(1))
                    except Exception:
                        pass

        if last_time is None or self._total_duration <= 0:
            return

        if hasattr(proc, "audio_index"):
            pct_single = min(int(last_time / self._total_duration * 100), 99)
            if not hasattr(self, "_audio_progress") or proc.audio_index not in self._audio_progress:
                self._audio_progress = getattr(self, "_audio_progress", {})
                self._audio_progress[proc.audio_index] = 0
            self._audio_progress[proc.audio_index] = pct_single

            overall = sum(self._audio_progress.values()) / max(1, len(self._audio_progress))
            self.progress.setValue(int(overall))
            self._progress_frac = max(0.0, min(0.99, overall / 100.0))
        else:
            pct = min(int(last_time / self._total_duration * 100), 99)
            self.progress.setValue(pct)
            self._progress_frac = max(0.0, min(0.99, pct / 100.0))

    def _on_tick(self):
        self._elapsed_secs = int(getattr(self, "_elapsed_secs", 0)) + 1
        elapsed_t = QTime(0, 0).addSecs(self._elapsed_secs).toString("hh:mm:ss")

        p = float(getattr(self, "_progress_frac", 0.0) or 0.0)
        if 0.001 <= p < 0.999:
            eta = int(self._elapsed_secs * (1.0 - p) / max(p, 1e-6))
            remaining_t = QTime(0, 0).addSecs(max(0, eta)).toString("hh:mm:ss")
        else:
            remaining_t = "--:--"

        self.lbl_elapsed.setText(f"Elapsed:   {elapsed_t}")
        self.lbl_remaining.setText(f"Remaining: {remaining_t}")

    def _ffmpeg_done(self):
        code = self.ffmpeg_proc.exitCode()
        self.progress.setValue(100)
        if code == 0:
            QMessageBox.information(self, "FFmpeg", "✅ Conversione completata con successo.")
        else:
            QMessageBox.critical(self, "FFmpeg", f"❌ Conversione fallita (codice {code}).")
        self.lbl_status.setText("Wait for conversion...")
        self.reset_state(True)
        self.btn_pause.setEnabled(False)

    def run_queue(self):
        return self.start_queue_processing()

    @pyqtSlot()
    def save_gui_queue_to_file(self):
        if not self._current_file:
            QMessageBox.warning(self, "Errore", "Seleziona prima un file video.")
            return

        if not self._audio_opts and not getattr(self, "audio_externo", False):
            reply = QMessageBox.question(
                self,
                "Attenzione: video senza audio",
                "Non hai estratto alcuna traccia audio.\nIl file in coda sarà privo di audio.\nVuoi comunque salvare la coda?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
            self._allow_silent = True

        out = self.ask_output_path(self._current_file.with_suffix(".mkv"))
        if not out:
            return
        out.parent.mkdir(parents=True, exist_ok=True)
        out.touch(exist_ok=True)
        self._last_output = out

        qid = self._video_idx_queue
        video_tmp = self.video_dir / f"video_temp_QUEUE_{qid}.mkv"
        video_cmd = self.build_ffmpeg_video_cmd(video_tmp)

        raw_audio = self.build_ffmpeg_audio_cmds(audio_dir=self.audio_dir, video_id=None, for_queue=True)
        audio_steps = []
        for i, (_old, cmd) in enumerate(raw_audio):
            old = Path(_old)
            new_out = self.audio_dir / f"track_QUEUE_{qid}_{i}{old.suffix}"
            cmd = [str(new_out) if str(arg) == str(old) else arg for arg in cmd]
            audio_steps.append((new_out, cmd))
        audio_cmds = [cmd for (_o, cmd) in audio_steps]

        chap_file = Path(self._chapter_opts[1]) if len(self._chapter_opts) >= 2 else Path()
        mux_cmd = self.build_ffmpeg_mux_cmd(
            input_mkv=self._current_file,
            video_temp=video_tmp,
            audio_files=[o for (o, _c) in audio_steps],
            raw_audio_opts=self._audio_opts,
            chapters_file=chap_file,
            output_mkv=out,
        )

        all_cmds = [video_cmd] + audio_cmds + [mux_cmd]
        log = ["\n" + "═" * 53, "📦 COMANDI SALVATI IN CODA", "═" * 53]
        for i, cmd in enumerate(all_cmds, 1):
            log.append(f"[{i}/{len(all_cmds)}] {shlex.join(cmd)}")
        log.append("═" * 53 + "\n")
        self._last_ffmpeg_log = "\n".join(log)
        self._last_queue_cmds = [c.copy() for c in all_cmds]
        self.txt_info.setTextColor(Qt.blue)
        self.txt_info.append(self._last_ffmpeg_log)
        self.txt_info.setTextColor(Qt.black)
        self.btn_copy_log.setEnabled(True)

        for cmd in all_cmds:
            added = qman.add(cmd)
            with qman.TMP_QUEUE_FILE.open("a", encoding="utf-8") as f:
                f.write(shlex.join(cmd) + "\n")
            prefix = "✅" if added else "❌"
            self.txt_info.append(f"{prefix} {'Aggiunto' if added else 'Presente'}:\n  {shlex.join(cmd)}")

        self.command_queue = qman.load()
        self.is_queue_saved = True
        self._update_buttons_enabled()
        self._video_idx_queue += 1

    def open_queue_manager(self):
        dlg = QueueDialog(self.command_queue, self)
        if dlg.exec_() == QDialog.Accepted:
            newq = dlg.get_updated_queue()
            if newq != self.command_queue:
                qman.save(newq)
                self._last_queue_run = None
                self.command_queue = newq
                self.txt_info.append("Coda aggiornata e salvata.")
            else:
                self.txt_info.append("Nessuna modifica alla coda.")
        else:
            self.txt_info.append("Gestione coda annullata.")

    def _inject_cpu_limits_for_queue(self, cmd: list[str]) -> list[str]:
        import os
        c = list(cmd)
        if not c:
            return c
        exe = os.path.basename(str(c[0]))
        if exe not in ("ffmpeg", "avconv"):
            return c
        if "-fflags" in c:
            return c

        V_THREADS = os.getenv("HEVC_V_THREADS", "2")
        X265_POOLS = os.getenv("HEVC_X265_POOLS", "2")
        X265_FT = os.getenv("HEVC_X265_FRAME_THREADS", "1")
        A_FTHR = os.getenv("HEVC_A_FILTER_THREADS", "1")
        A_THR = os.getenv("HEVC_A_THREADS", "1")

        is_audio = ("-vn" in c) and any(t == "-c:a" or t.startswith("-c:a") for t in c)
        is_video = any(t == "-c:v" for t in c)

        if is_audio:
            try:
                insert_at = c.index("-nostdin") + 1
            except ValueError:
                insert_at = 1
            to_inject = []
            if "-filter_threads" not in c:
                to_inject += ["-filter_threads", A_FTHR]
            if "-threads" not in c:
                to_inject += ["-threads", A_THR]
            if to_inject:
                c[insert_at:insert_at] = to_inject
            return c

        if is_video:
            codec = ""
            try:
                idx = c.index("-c:v")
                if idx + 1 < len(c):
                    codec = c[idx + 1]
            except ValueError:
                pass

            extras = []
            if "-threads" not in c:
                extras += ["-threads", V_THREADS]
            if codec == "libx265" and "-x265-params" not in c:
                extras += ["-x265-params", f"pools={X265_POOLS}:frame-threads={X265_FT}"]

            if extras:
                if len(c) >= 2:
                    out = c[-1]
                    c = c[:-1] + extras + [out]
                else:
                    c += extras
            return c

        return c

    @pyqtSlot()
    def start_queue_processing(self):
        import shlex
        import subprocess
        from pathlib import Path

        queue = qman.load()

        if self._last_queue_run is not None and queue == self._last_queue_run:
            reply = QMessageBox.question(
                self,
                "Coda già avviata",
                "Hai già avviato questa stessa coda di comandi.\nSei sicuro di volerla lanciare di nuovo?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        if not queue:
            QMessageBox.warning(self, "Attenzione", "La coda è vuota.")
            return

        queue_file = Path(qman.QUEUE_FILE)
        script = queue_file.parent / "execute_queue.sh"

        try:
            queue_file.parent.mkdir(parents=True, exist_ok=True)
            with script.open("w", encoding="utf-8") as sh:
                sh.write("#!/bin/bash\n")
                sh.write("set -e\n\n")
                for raw_cmd in queue:
                    cmd = self._inject_cpu_limits_for_queue(raw_cmd)
                    line = " ".join(shlex.quote(arg) for arg in cmd)
                    sh.write(line + "\n")
            script.chmod(0o755)

            subprocess.Popen(["gnome-terminal", "--", "bash", "-c", f'"{script}" && exec bash'])

            self.txt_info.append("Coda avviata in GNOME Terminal (con limiti CPU applicati allo script).")
            QMessageBox.information(self, "Coda", "Elaborazione avviata.")
            self._last_queue_run = [cmd.copy() for cmd in queue]

        except Exception as e:
            QMessageBox.warning(self, "Errore", f"Impossibile eseguire la coda: {e}")

    def delete_queue_file(self):
        from pathlib import Path
        qfile = Path(qman.QUEUE_FILE)
        if qfile.exists():
            qfile.unlink()

    def _ask_stop(self) -> bool:
        if self.ffmpeg_proc and self.ffmpeg_proc.state() == QProcess.Running:
            ans = QMessageBox.question(
                self,
                "Conversione in corso",
                "È in corso una conversione.\nInterromperla subito?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if ans == QMessageBox.Yes:
                self.ffmpeg_proc.kill()
                return True
            return False
        return True

    def _ask_keep_queue(self) -> Optional[bool]:
        n = len(qman.load())
        if n == 0:
            return True

        ans = QMessageBox.question(
            self,
            "Coda",
            f"Ci sono {n} comandi salvati in coda.\nVuoi mantenerli?",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            QMessageBox.Yes,
        )

        if ans == QMessageBox.Yes:
            return True
        elif ans == QMessageBox.No:
            qman.clear()
            return False
        else:
            return None

    def _full_reset(self):
        self.edit_path.clear()
        self._current_file = None
        self._last_output = None

        self.update_filters()
        for cmb in (
            self.cmb_br,
            self.cmb_crf,
            self.cmb_preset,
            self.cmb_sharp,
            self.cmb_smth,
            self.cmb_resize,
        ):
            cmb.setCurrentIndex(0)
        self.cmb_frmode.setCurrentIndex(0)
        self.cmb_frval.setCurrentIndex(0)
        self.rd_color.setChecked(True)
        self._filters.clear()

        self._audio_opts.clear()
        self._audio_progress = {}
        self._chapter_opts.clear()
        self._chapters_handled = False
        self._subs_integrated_count = 0

        self.progress.setValue(0)
        self.txt_info.clear()
        self.btn_convert.setEnabled(False)
        self._last_queue_cmds = []
        self._last_ffmpeg_log = ""
        self.btn_copy_log.setEnabled(False)

    def cancel_job(self):
        if not (self.ffmpeg_proc and self.ffmpeg_proc.state() == QProcess.Running):
            return

        reply = QMessageBox.question(
            self,
            "Interrompi Conversione",
            "Vuoi davvero interrompere e cancellare i temporanei e la coda?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self.ffmpeg_proc.kill()
        for p in getattr(self, "_audio_procs", []):
            if p.state() == QProcess.Running:
                p.kill()

        qman.clear()
        self.reset_gui_only()

    @pyqtSlot()
    def exit_app(self):
        self.close()

    def reset_state(self, keep_log: bool):
        self._filters.clear()
        self._audio_opts.clear()
        if not keep_log:
            self.progress.setValue(0)
            self.txt_info.clear()
        self.btn_convert.setEnabled(bool(self._current_file))

    def closeEvent(self, event):
        from hevc_gui.gui.settings import save_window_size

        size = self.size()
        save_window_size(size.width(), size.height())

        proc = getattr(self, "ffmpeg_proc", None)
        running = bool(proc and proc.state() == QProcess.Running)
        if running:
            ans = QMessageBox.question(
                self,
                "Conversione in corso",
                "È in corso una conversione.\nInterromperla ed uscire?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if ans != QMessageBox.Yes:
                event.ignore()
                return
            proc.kill()
        else:
            ans = QMessageBox.question(
                self,
                "Conferma uscita",
                "Sei sicuro di voler uscire?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if ans != QMessageBox.Yes:
                event.ignore()
                return

        keep = self._ask_keep_queue()
        if keep is None:
            event.ignore()
            return
        elif not keep:
            qman.clear()

        event.accept()
        QApplication.quit()

    @pyqtSlot()
    def open_help(self):
        help_file = Path(__file__).parent.parent / "resources" / "doc" / "video_converter_user_manual.html"
        alt = Path("/usr/share/doc/video_converter_user_manual.html")
        if not help_file.exists() and alt.exists():
            help_file = alt
        if help_file.exists():
            webbrowser.open(help_file.as_uri())
        else:
            QMessageBox.warning(self, "Attenzione", "Manuale utente non trovato.")

    @pyqtSlot()
    def show_info(self):
        pp_w, pp_h = 120, 120
        logo_w, logo_h = 160, 160
        from PyQt5.QtCore import QSize

        dlg = QDialog(self)
        dlg.setWindowTitle("Info")
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(16, 16, 16, 14)
        layout.setSpacing(10)

        icon_file = Path(__file__).parent.parent / "resources" / "icons" / "logo.png"
        if icon_file.exists():
            pix = QPixmap(str(icon_file)).scaled(logo_w, logo_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            lbl_icon = QLabel()
            lbl_icon.setPixmap(pix)
            lbl_icon.setAlignment(Qt.AlignHCenter)
            layout.addWidget(lbl_icon)

        lbl_text = QLabel(
            "<div style='text-align:center;'>"
            "<b style='font-size:14pt;'>HEVC - Video Converter</b><br>"
            "Ver. 2.0.0<br><br>"
            "<b>LorisPaganiniHomeStudio – 2025</b><br><br>"
            "info: <a href='mailto:loris.paganini@gmail.com'>loris.paganini@gmail.com</a><br><br>"
            "</div>"
        )
        lbl_text.setTextFormat(Qt.RichText)
        lbl_text.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        lbl_text.setAlignment(Qt.AlignHCenter)
        layout.addWidget(lbl_text)

        pp_icon_path = None
        for name in ("paypal.png", "ph_paypal.png"):
            p = Path(__file__).parent.parent / "resources" / "icons" / name
            if p.exists():
                pp_icon_path = p
                break

        if pp_icon_path:
            donate_btn = QPushButton("")
            pm = QPixmap(str(pp_icon_path)).scaled(pp_w, pp_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            donate_btn.setIcon(QIcon(pm))
            donate_btn.setIconSize(QSize(pp_w, pp_h))
            donate_btn.setFixedSize(pp_w, pp_h)
            donate_btn.setToolTip("Dona su PayPal")
            donate_btn.setAccessibleName("Dona su PayPal")
            donate_btn.setCursor(Qt.PointingHandCursor)
            donate_btn.setFlat(True)
            donate_btn.setStyleSheet(
                "QPushButton { border: none; padding: 0; background: transparent; }"
                "QPushButton:pressed { transform: translateY(1px); }"
            )
            donate_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://paypal.me/loris1159")))
            layout.addWidget(donate_btn, alignment=Qt.AlignHCenter)
        else:
            donate_btn = QPushButton("Dona (PayPal)")
            donate_btn.setCursor(Qt.PointingHandCursor)
            donate_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://paypal.me/loris1159")))
            layout.addWidget(donate_btn, alignment=Qt.AlignHCenter)

        dlg.exec_()

    @pyqtSlot()
    def on_subtitle_clicked(self):
        if not self._current_file:
            return
        try:
            out = check_output(
                [
                    C.FFPROBE_BIN,
                    "-v","error",
                    "-select_streams","s",
                    "-show_entries","stream=index",
                    "-of","csv=p=0",
                    str(self._current_file),
                ],
                text=True,
            ).strip()
            self._subs_integrated_count = len(out.splitlines()) if out else 0
        except Exception:
            self._subs_integrated_count = 0

        select_subtitles(self)

    @pyqtSlot()
    def on_chapter_clicked(self):
        if not self._current_file:
            return

        self.chapters_dir.mkdir(parents=True, exist_ok=True)
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.video_dir.mkdir(parents=True, exist_ok=True)

        embedded = ChapterManager.get_embedded_chapters(self._current_file)
        self.txt_info.append(f"> Capitoli incorporati trovati: {len(embedded)}")

        if embedded:
            use = (
                QMessageBox.question(
                    self,
                    "Chapters",
                    f"Trovati {len(embedded)} capitoli incorporati. Vuoi usarli?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                == QMessageBox.Yes
            )

            if use:
                self.lbl_status.setText("Verifica capitoli incorporati…")
                self._start_marquee()
                QApplication.processEvents()
                try:
                    meta = ChapterManager.get_or_convert_chapters(self._current_file)
                except Exception as exc:
                    self._stop_marquee()
                    QMessageBox.critical(self, "Capitoli", str(exc))
                else:
                    self._stop_marquee()
                    self.lbl_status.setText("Wait for conversion…")
                    self._chapter_opts = ["-i", meta]
                    self.txt_info.append("> Capitoli incorporati compatibili e selezionati.")
                return

        thr, ok = QInputDialog.getDouble(self, "Threshold Scene Change", "Inserisci soglia (0.0–1.0):", 0.40, 0.0, 1.0, 2)
        if not ok:
            self.txt_info.append("! Capitoli: soglia non confermata.")
            return

        self.lbl_status.setText("Generating chapters, wait…")
        self.lbl_status.setStyleSheet("color:red;font-weight:bold;")
        self.progress.setFormat("")
        self.progress.setRange(0, 100)
        self._marquee_value = 0
        self._marquee_direction = 1
        QApplication.processEvents()
        self._marquee_timer.start(100)

        self._chapter_worker = ChapterWorker(self._current_file, thr)
        self._chapter_worker.finished.connect(self._on_chapter_generated)
        self._chapter_worker.error.connect(self._on_chapter_error)
        self._chapter_worker.start()

    @pyqtSlot(str, int)
    def _on_chapter_generated(self, metadata_path: str, count: int):
        self._marquee_timer.stop()
        self.progress.setFormat("%p%")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.lbl_status.setText("Wait for conversion…")
        self.lbl_status.setStyleSheet("")

        self._chapters_handled = True

        if (
            QMessageBox.question(
                self,
                "Chapters",
                f"Generati {count} capitoli. Vuoi usarli?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            == QMessageBox.Yes
        ):
            self._chapter_opts = ["-i", metadata_path]
            self.txt_info.append(f"> Usati {count} capitoli generati in {metadata_path}")
        else:
            self.txt_info.append("! Uso capitoli generati annullato.")

    @pyqtSlot(str)
    def _on_chapter_error(self, msg: str):
        self._marquee_timer.stop()
        self.progress.setFormat("%p%")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.lbl_status.setText("Wait for conversion...")
        self.lbl_status.setStyleSheet("")

        self.txt_info.append(f"! Errore generazione capitoli: {msg}")
        QMessageBox.critical(self, "Chapters", f"Errore generazione capitoli:\n{msg}")

    def _start_marquee(self):
        self.progress.setFormat("")
        self.progress.setRange(0, 0)
        self.progress.setValue(0)

    def _stop_marquee(self):
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("%p%")

    def _advance_marquee(self):
        v = self._marquee_value + 5 * self._marquee_direction
        if v >= 100 or v <= 0:
            self._marquee_direction *= -1
        self._marquee_value = max(0, min(100, v))
        self.progress.setValue(self._marquee_value)

    @pyqtSlot()
    def toggle_pause(self):
        if not self.ffmpeg_proc:
            return

        root_pid = int(self.ffmpeg_proc.processId() or 0)
        if root_pid <= 0:
            return

        if sys.platform == "win32":
            QMessageBox.information(self, "Pausa non disponibile", "La sospensione del processo non è supportata su Windows.")
            return

        def _children_of(pid: int) -> list[int]:
            try:
                with open(f"/proc/{pid}/task/{pid}/children", "r") as f:
                    txt = f.read().strip()
                return [int(x) for x in txt.split()] if txt else []
            except Exception:
                pass
            try:
                out = subprocess.check_output(["pgrep", "-P", str(pid)], text=True).strip()
                return [int(x) for x in out.splitlines() if x.strip()]
            except Exception:
                return []

        def _comm_of(pid: int) -> str:
            try:
                with open(f"/proc/{pid}/comm", "r") as f:
                    return f.read().strip()
            except Exception:
                pass
            try:
                with open(f"/proc/{pid}/cmdline", "rb") as f:
                    raw = f.read().decode(errors="ignore").replace("\x00", " ").strip()
                    return raw
            except Exception:
                return ""

        def _find_ffmpeg_descendant(pid: int, max_depth: int = 6) -> int:
            from collections import deque
            q = deque([(pid, 0)])
            seen = {pid}
            while q:
                cur, d = q.popleft()
                name = _comm_of(cur).lower()
                if "ffmpeg" in name or "avconv" in name:
                    return cur
                if d >= max_depth:
                    continue
                for ch in _children_of(cur):
                    if ch not in seen:
                        seen.add(ch)
                        q.append((ch, d + 1))
            return 0

        target_pid = root_pid
        try:
            pid2 = _find_ffmpeg_descendant(root_pid, max_depth=6)
            if pid2 > 0:
                target_pid = pid2
                try:
                    self.txt_info.append(f"[CPU] toggle_pause: targeting ffmpeg PID {target_pid} (wrapper PID {root_pid})")
                except Exception:
                    pass
            else:
                try:
                    self.txt_info.append(f"[CPU] toggle_pause: nessun discendente ffmpeg trovato, uso PID {root_pid}")
                except Exception:
                    pass
        except Exception:
            pass

        try:
            if not getattr(self, "_is_paused", False):
                os.kill(target_pid, signal.SIGSTOP)
                if getattr(self, "_tick_timer", None):
                    self._tick_timer.stop()
                self._is_paused = True
                self.btn_pause.setText("Continue")
            else:
                os.kill(target_pid, signal.SIGCONT)
                if getattr(self, "_tick_timer", None):
                    self._tick_timer.start(1000)
                self._is_paused = False
                self.btn_pause.setText("Pause")
        except ProcessLookupError:
            try:
                self.txt_info.append("[WARN] Processo non trovato per pausa/riprendi.")
            except Exception:
                pass
        except PermissionError as e:
            try:
                self.txt_info.append(f"[WARN] Permesso negato nel segnalare il processo: {e}")
            except Exception:
                pass

    def _child_pids_of(self, pid: int) -> list[int]:
        try:
            with open(f"/proc/{pid}/task/{pid}/children", "r") as f:
                data = f.read().strip()
            return [int(x) for x in data.split()] if data else []
        except Exception:
            return []

    def _start_timer(self, total_sec: float):
        self._total_duration = total_sec or 1.0
        if getattr(self, "_tick_timer", None):
            self._tick_timer.stop()
            self._tick_timer.deleteLater()
        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._on_tick)
        self._tick_timer.start(1000)

        self._elapsed_secs = 0
        self._eta_secs = 0
        self._progress_frac = 0.0
        self._start_time = time.time()

        self.lbl_elapsed.setText("Elapsed:   00:00:00")
        self.lbl_remaining.setText("Remaining: --:--")

    def _stop_timer(self):
        if getattr(self, "_tick_timer", None):
            self._tick_timer.stop()
            self._tick_timer.deleteLater()
            self._tick_timer = None

    @pyqtSlot()
    def copy_ffmpeg_log_to_clipboard(self):
        if getattr(self, "_last_queue_cmds", None):
            text = "\n".join(" ".join(shlex.quote(str(a)) for a in cmd) for cmd in self._last_queue_cmds)
        elif getattr(self, "_last_ffmpeg_log", "").strip():
            text = self._last_ffmpeg_log
        else:
            QMessageBox.warning(self, "Nessun comando", "Non è stato generato alcun comando FFmpeg.")
            return

        QApplication.clipboard().setText(text)
        QMessageBox.information(self, "Log copiato", "Comando(i) FFmpeg copiato(i) negli appunti.")

    def _print_cmd_log(
        self,
        cmd: list[str],
        video_log: list[str] | None = None,
        audio_log: list[str] | None = None,
        subtitle_log: list[str] | None = None,
        chapter_log: list[str] | None = None,
    ):
        video_log = video_log or []
        audio_log = audio_log or []
        subtitle_log = subtitle_log or []
        chapter_log = chapter_log or []

        def q(s):  # noqa: E731
            return shlex.quote(str(s))

        full_log = [
            "\n" + "═" * 53,
            "📦 CONFIGURAZIONE FINALE FFmpeg",
            "═" * 53,
            *video_log,
            "",
            *audio_log,
            "",
            *subtitle_log,
            "",
            *chapter_log,
            "",
            "🧾 Comando FFmpeg finale:",
            "    " + " ".join(q(c) for c in cmd),
            "═" * 53 + "\n",
        ]
        self._last_ffmpeg_log = "\n".join(full_log)

        cursor = self.txt_info.textCursor()
        fmt = cursor.charFormat()
        old_color = fmt.foreground()
        self.txt_info.setTextColor(Qt.blue)
        self.txt_info.append(self._last_ffmpeg_log)
        self.txt_info.setTextColor(old_color.color())
        self.btn_copy_log.setEnabled(True)

    def _probe_src_colorimetry(self, f: Path) -> dict:
        """
        Legge da ffprobe: color_space (matrix), color_primaries, color_transfer, width, height.
        Ritorna sempre un dict con chiavi: matrix, primaries, transfer, width, height.
        Se non disponibili, inferisce 709 per HD e bt470bg per SD.
        """
        import json, subprocess
        info = {"matrix": "", "primaries": "", "transfer": "", "width": 0, "height": 0}
        try:
            out = subprocess.check_output(
                [
                    C.FFPROBE_BIN, "-v", "error", "-select_streams", "v:0",
                    "-show_entries", "stream=color_space,color_primaries,color_transfer,width,height",
                    "-of", "json", str(f),
                ],
                text=True
            )
            st = json.loads(out)["streams"][0]
            w = int(st.get("width") or 0)
            h = int(st.get("height") or 0)
            cs = (st.get("color_space") or "").strip().lower()
            cp = (st.get("color_primaries") or "").strip().lower()
            ct = (st.get("color_transfer") or "").strip().lower()
            # fallback sensati
            is_hd = h >= 720 or w >= 1280
            default = "bt709" if is_hd else "bt470bg"
            info.update({
                "matrix": cs or default,
                "primaries": cp or default,
                "transfer": ct or default,
                "width": w, "height": h,
            })
        except Exception:
            # fallback grezzo: usa risoluzione per decidere
            try:
                import os
                # se non sappiamo nulla, prova a prendere h da mediainfo/ffprobe altrove… ma ok così.
            except Exception:
                pass
        return info

    def _choose_matrix_for_target(self, w: int | None, h: int | None) -> str | None:
        """
        Ritorna la matrice colore desiderata per la risoluzione di ARRIVO:
          • 576 → bt470bg (PAL SD)
          • 480/486 → smpte170m (NTSC SD)
          • >=720p (o >=1280 oriz.) → bt709 (HD)
          • altrimenti None (non forzare).
        """
        if not w or not h:
            return None
        # SD PAL
        if h in (576, 575, 574):
            return "bt470bg"
        # SD NTSC
        if h in (480, 486):
            return "smpte170m"
        # HD (720p+ o larghezza >= 1280)
        if h >= 720 or w >= 1280:
            return "bt709"
        return None
