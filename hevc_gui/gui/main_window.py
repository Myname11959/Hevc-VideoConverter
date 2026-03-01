#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# hevc_gui/gui/main_window.py (inizio del file)

from __future__ import annotations
from hevc_gui.i18n import L

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
from typing import Optional, List, Union
from pathlib import Path

# Assicuriamoci che Python trovi lo script in scripts/
scripts_dir = Path(__file__).parent.parent.parent / "scripts"
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

# Ora possiamo importare AudioConverter direttamente
from string_audio_generator import AudioConverter

from PyQt5.QtCore import Qt, pyqtSlot, QUrl, QTimer, QTime, QEventLoop, QProcess, QProcessEnvironment
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
from ..core.subtitle_helper import select_subtitles, KIND_MAP

from ..core.chapter import ChapterManager
from ..core.chapter_worker import ChapterWorker
from ..core.progressbar_nozero import ProgressBarNoZeroChunk
from ..core.helpers import select_reverb_expr, join_filters, add_filter_arg

# Crop: lettura dai Settings + iniezione nella vf chain
from hevc_gui.video.crop_tools import load_crop_settings, inject_crop, clear_crop_settings
from hevc_gui.video.color_tools import build_color_eq_filter, clear_color_settings
from hevc_gui.gui.trim_dialog import TrimDialog
from hevc_gui.core.ldvd_sidecar import load_sidecar_for
from .menubar import setup_menubar, refresh_icons, add_donate_to_help
from .appearance_settings import CONFIG_PATH
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
        self.setPlaceholderText(L("Trascina qui un file video oppure premi «Apri…»"))
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
        self.setWindowTitle(L("Gestione Coda"))
        self.setFixedSize(600, 400)
        self.command_queue = command_queue.copy()
        layout = QVBoxLayout(self)

        self.text_edit = QPlainTextEdit(self)
        self.text_edit.setPlainText(self._queue_to_text(self.command_queue))
        self.text_edit.setToolTip(L("Modifica i comandi, uno per riga."))
        layout.addWidget(self.text_edit, 1)

        btns = QHBoxLayout()
        self.save_btn = QPushButton(L("Salva"), self)
        self.save_btn.clicked.connect(self.accept)
        self.cancel_btn = QPushButton(L("Annulla"), self)
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

                    def _kib(s):
                        return int(s.split()[0]) * 1024

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

    def _consume_after_encode_success(self) -> None:
        """
        Comportamento 'consume':
        dopo un encode completato con successo (mux OK) azzero crop/trim
        così non restano appiccicati al prossimo tentativo / prossimo file.
        """
        try:
            from hevc_gui.video.crop_tools import clear_crop_settings

            clear_crop_settings(disable_only=False)
        except Exception:
            pass

        try:
            from hevc_gui.video.trim_tools import clear_trim_settings

            clear_trim_settings(disable_only=False)
        except Exception:
            pass

        # (opzionale ma sensato) azzera offset preview “di tool”
        try:
            self._preview_offset_sec = 0.0
        except Exception:
            pass

    def _consume_video_tools_state(self, *, clear_color: bool, why: str = "") -> None:
        """
        “Consume” strumenti:
          - CROP: cancella anche rettangolo
          - TRIM: cancella anche IN/OUT
          - COLOR: solo su cambio file/uscita/reset (non serve dopo encode perché è già consume nel builder)
        """
        # Crop
        try:
            from hevc_gui.video.crop_tools import clear_crop_settings

            clear_crop_settings(disable_only=False)
            try:
                self.txt_info.append(f"[DBG] Crop consumato ({why}).")
            except Exception:
                pass
        except Exception:
            pass

        # Trim
        try:
            from hevc_gui.video.trim_tools import clear_trim_settings

            clear_trim_settings(disable_only=False)
            try:
                self.txt_info.append(f"[DBG] Trim consumato ({why}).")
            except Exception:
                pass
        except Exception:
            pass

        # Color (solo quando richiesto)
        if clear_color:
            try:
                from hevc_gui.video.color_tools import clear_color_settings

                clear_color_settings()
                try:
                    self.txt_info.append(f"[DBG] Color azzerato ({why}).")
                except Exception:
                    pass
            except Exception:
                pass

        # Preview offset sempre a zero quando “resettiamo contesto”
        try:
            self._preview_offset_sec = 0.0
        except Exception:
            pass

    # ───────────────── LDVD sidecar (DVD Ripper) ─────────────────

    def _load_ldvd_sidecar_if_present(self, src_path: str) -> None:
        """
        Se accanto al file sorgente c'è un sidecar LDVD
        (<basename>.ldvdmeta.json), lo carica in self._ldvd_sidecar.
        Se non c'è, azzera solo il riferimento.
        """
        # inizializza/azzera sempre
        self._ldvd_sidecar = None

        if not src_path:
            return

        try:
            sc = load_sidecar_for(src_path)
        except Exception as e:
            # logga solo in caso di errore “vero”
            try:
                self.txt_info.append(L("[HEVC] Errore nel leggere sidecar LDVD: {0}").format(e))
            except Exception:
                pass
            return

        if not sc:
            # nessun sidecar (caso normale per i file non provenienti da LDVD)
            return

        self._ldvd_sidecar = sc

        # Log sintetico
        try:
            self.txt_info.append(f"[HEVC] Sidecar LDVD rilevato: {sc.base_vob} → {sc.summary_for_log()}")
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

        self.setWindowTitle(L("HEVC - Video Converter"))

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
        self._subtitle_maps: list[str] = []  # es: ['0:s:0','0:s:3'] per subs interni selezionati

        self._subtitle_out_opts: list[str] = []
        self._elapsed_secs = self._eta_secs = 0
        self._tick_timer = None
        self._audio_procs: list[QProcess] = []
        self._current_audio_idx = 0
        self.ffmpeg_proc: QProcess | None = None
        self._total_duration = 0.0
        self._last_output: Path | None = None
        self.preview_proc: QProcess | None = None
        self.dvd_proc: QProcess | None = None

        self._marquee_timer = QTimer(self)
        self._marquee_timer.timeout.connect(self._advance_marquee)
        self.block_width = 30
        self._marquee_value = 0
        self._marquee_direction = 1

        self._last_ffmpeg_log = ""
        self._is_paused = False
        self._last_queue_run: list[list[str]] | None = None

        # Costruzione UI e collegamenti
        self._build_ui()  # ← dentro _build_ui esiste già: self.edit_path.textChanged.connect(self._path_changed)
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
        self.btn_open = QPushButton(L("Apri video…"))
        self.btn_open.setToolTip(L("Seleziona un file video da convertire"))
        self.btn_open.clicked.connect(self.open_file)
        h1.addWidget(self.btn_open)
        self.edit_path = PathLineEdit()
        self.edit_path.setToolTip(L("Percorso del file video da convertire"))
        self.edit_path.textChanged.connect(self._path_changed)
        h1.addWidget(self.edit_path, 1)
        vbox.addLayout(h1)

        # Bitrate / CRF / Preset
        hrate = QHBoxLayout()
        self.rd_br = QRadioButton(L("Bit-rate"))
        self.rd_crf = QRadioButton(L("CRF"))
        self.rd_crf.setChecked(True)
        self.cmb_br = QComboBox()
        self.cmb_br.addItems([L(x) for x in C.BITRATE_OPTIONS])
        self.cmb_br.setEnabled(False)
        self.cmb_crf = QComboBox()
        self.cmb_crf.addItems([L(x) for x in C.CRF_OPTIONS])
        self.rd_br.toggled.connect(lambda val: (self.cmb_br.setEnabled(val), self.cmb_crf.setEnabled(not val)))
        hrate.addWidget(self.rd_br)
        hrate.addWidget(self.cmb_br)
        hrate.addSpacing(20)
        hrate.addWidget(self.rd_crf)
        hrate.addWidget(self.cmb_crf)
        hrate.addSpacing(20)
        hrate.addWidget(QLabel(L("Preset:")))
        self.cmb_preset = QComboBox()
        self.cmb_preset.addItems([L(x) for x in C.PRESET_OPTIONS])
        hrate.addWidget(self.cmb_preset)
        vbox.addLayout(hrate)

        # Filtri video
        hfilters = QHBoxLayout()
        lbl = QLabel(L("Sharpness:"))
        self.cmb_sharp = QComboBox()
        self.cmb_sharp.addItems([L(x) for x in C.SHARPNESS_LEVELS])
        self.cmb_sharp.currentTextChanged.connect(self.update_filters)
        hfilters.addWidget(lbl)
        hfilters.addWidget(self.cmb_sharp)
        hfilters.addSpacing(20)
        lbl = QLabel(L("Smoothness:"))
        self.cmb_smth = QComboBox()
        self.cmb_smth.addItems([L(x) for x in C.SMOOTHNESS_LEVELS])
        self.cmb_smth.currentTextChanged.connect(self.update_filters)
        hfilters.addWidget(lbl)
        hfilters.addWidget(self.cmb_smth)
        hfilters.addSpacing(20)
        lbl = QLabel(L("Resize:"))
        self.cmb_resize = QComboBox()
        self.cmb_resize.addItems([L(x) for x in C.RESOLUTIONS])
        self.cmb_resize.currentTextChanged.connect(self.update_filters)
        hfilters.addWidget(lbl)
        hfilters.addWidget(self.cmb_resize)
        hfilters.addStretch()
        vbox.addLayout(hfilters)

        # Frame-rate, B&W, deinterlacciamento
        hfr = QHBoxLayout()
        hfr.addWidget(QLabel(L("Frame-rate:")))

        self.cmb_frmode = QComboBox()
        self.cmb_frmode.addItems([L(x) for x in C.FR_MODE])
        self.cmb_frval = QComboBox()
        self.cmb_frval.addItems(list(C.FR_CONST_VALUES))  # valori FPS NON tradotti (evita 23,976 in EN)
        self.cmb_frval.setEnabled(False)

        self.cmb_frmode.currentTextChanged.connect(
            lambda t: self.cmb_frval.setEnabled(str(t or "").strip().lower() in ("costante", "constant"))
        )

        for _label in ("Originale", "Nessuno"):
            if _label in C.FR_MODE:
                self.cmb_frmode.setCurrentText(_label)
                break
        else:
            self.cmb_frmode.setCurrentIndex(0)
        self.cmb_frval.setEnabled(str(self.cmb_frmode.currentText() or "").strip().lower() in ("costante", "constant"))

        hfr.addWidget(self.cmb_frmode)
        hfr.addSpacing(15)
        hfr.addWidget(QLabel(L("Valore:")))
        hfr.addWidget(self.cmb_frval)
        hfr.addSpacing(40)

        self.rd_color = QRadioButton(L("Color"))
        self.rd_bw = QRadioButton(L("B&W"))
        self.rd_color.setChecked(True)
        grp_col = QButtonGroup(self)
        grp_col.addButton(self.rd_color)
        grp_col.addButton(self.rd_bw)
        hfr.addWidget(self.rd_color)
        hfr.addWidget(self.rd_bw)

        hfr.addSpacing(40)
        self.chk_deint = QCheckBox(L("Deinterlacciamento"))
        self.chk_deint.toggled.connect(self.update_filters)
        hfr.addWidget(self.chk_deint)
        hfr.addStretch()
        vbox.addLayout(hfr)

        # Pulsanti Estrai audio, Sottotitoli, Capitoli, Preview
        haudio_prev = QHBoxLayout()
        self.btn_audio = QPushButton(L("Estrai audio"))
        self.btn_audio.clicked.connect(self.extract_audio)

        self.btn_subtitle = QPushButton(L("Sottotitoli"))
        self.btn_subtitle.clicked.connect(self.on_subtitle_clicked)
        self.btn_subtitle.setEnabled(False)

        self.btn_chapter = QPushButton(L("Capitoli"))
        self.btn_chapter.clicked.connect(self.on_chapter_clicked)
        self.btn_chapter.setEnabled(False)

        # Preview RAW = originale (nessun filtro)
        self.btn_preview = QPushButton(L("Preview"))
        self.btn_preview.clicked.connect(self.preview_raw)

        # Preview FILTRATA = filtri/crop/colore/trim
        self.btn_preview_filtered = QPushButton(L("Preview filtrata"))
        self.btn_preview_filtered.clicked.connect(self.preview_filtered)

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
        self.btn_minfo = QPushButton(L("MediaInfo"))
        self.btn_minfo.clicked.connect(self.show_mediainfo)
        self.btn_salva = QPushButton(L("Salva Coda"))
        self.btn_salva.clicked.connect(self.save_gui_queue_to_file)
        self.btn_gestisci = QPushButton(L("Gestisci Coda"))
        self.btn_gestisci.clicked.connect(self.open_queue_manager)
        self.btn_elabora = QPushButton(L("Elabora Coda"))
        self.btn_elabora.clicked.connect(self.start_queue_processing)
        self.btn_convert = QPushButton(L("Converti"))
        self.btn_convert.clicked.connect(self.on_convert_clicked)
        btn_help = QPushButton(L("Help"))
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
        self.btn_dir_output = QPushButton(L("Directory Output"))
        self.btn_dir_output.clicked.connect(self.open_output_directory)
        self.btn_copy_log = QPushButton(L("Copia Log FFmpeg"))
        self.btn_copy_log.clicked.connect(self.copy_ffmpeg_log_to_clipboard)
        self.btn_copy_log.setEnabled(False)
        self.btn_pause = QPushButton(L("Pausa"))
        self.btn_pause.clicked.connect(self.toggle_pause)
        self.btn_pause.setEnabled(False)
        self.btn_cancel = QPushButton(L("Interrompi"))
        self.btn_cancel.clicked.connect(self.cancel_job)
        self.btn_reset_gui = QPushButton(L("Reset GUI"))
        self.btn_reset_gui.clicked.connect(self.reset_gui_only)
        self.btn_exit = QPushButton(L("Esci"))
        self.btn_exit.clicked.connect(self.exit_app)
        self.btn_info = QPushButton(L("Info"))
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
        self.lbl_status = QLabel(L("Wait for conversion…"))
        self.lbl_elapsed = QLabel(L("Elapsed: 00:00"))
        self.lbl_remaining = QLabel(L("Remaining: --:--"))
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

        # --- Azioni Strumenti dirette (Crop / Colore / Trim) -----------------
        # Abilitate solo se c'è un file valido e NON c'è una conversione in corso
        for name in ("act_crop", "act_color", "act_trim"):
            act = getattr(self, name, None)
            if act is not None:
                try:
                    act.setEnabled(has_file and not running)
                except Exception:
                    pass

        # (facoltativo) blocca/abilita l’intera toolbar in un colpo
        if hasattr(self, "_menu_toolbar"):
            self._menu_toolbar.setEnabled(not running)

    def _update_tools_actions_enabled(self):
        """
        Abilita/disabilita le azioni Strumenti (crop / color / trim)
        in base alla presenza di un file video corrente.
        """
        has_file = bool(getattr(self, "_current_file", None))

        for name in ("act_crop", "act_color", "act_trim"):
            act = getattr(self, name, None)
            if act is not None:
                act.setEnabled(has_file)

    def _consume_video_state(self, where: str = "") -> None:
        """
        Consume = niente persistenza tra file / dopo encode:
        - crop
        - trim
        - colore
        """
        try:
            from hevc_gui.video.crop_tools import clear_crop_settings

            clear_crop_settings(disable_only=False)
        except Exception:
            pass
        try:
            from hevc_gui.video.trim_tools import clear_trim_settings

            clear_trim_settings(disable_only=False)
        except Exception:
            pass
        try:
            from hevc_gui.video.color_tools import clear_color_settings

            clear_color_settings()
        except Exception:
            pass

        try:
            if where:
                self.txt_info.append(f"[DBG] consume crop/trim/colore ({where})")
        except Exception:
            pass

    @pyqtSlot()
    def open_dvd_ripper(self):
        # --- export icon theme for child tools (LDVD/SAG) ---
        try:
            import os
            from PyQt5.QtGui import QIcon

            os.environ["HEVC_QT_ICON_THEME_NAME"] = QIcon.themeName() or ""
            os.environ["HEVC_QT_ICON_THEME_SEARCH_PATHS"] = os.pathsep.join(QIcon.themeSearchPaths() or [])
            try:
                os.environ["HEVC_QT_ICON_FALLBACK_THEME_NAME"] = QIcon.fallbackThemeName() or ""
            except Exception:
                pass
        except Exception:
            pass

        """
        Lancia LDVD-Ripper (hevc_gui.dvd_ripper.app) come processo separato
        e ascolta eventuali handoff HEVC_HANDOFF:/percorso.vob.
        Inoltre: eredita tema (style/font/qss/icon theme) dalla GUI principale.
        """
        if self.dvd_proc and self.dvd_proc.state() == QProcess.Running:
            if hasattr(self, "txt_info"):
                self.txt_info.append(L("DVD Ripper è già in esecuzione."))
            return

        if hasattr(self, "txt_info"):
            self.txt_info.append(L("> Avvio DVD Ripper..."))

        proc = QProcess(self)
        self.dvd_proc = proc

        python = sys.executable or "python3"

        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
        proc.setWorkingDirectory(root_dir)

        proc.setProgram(python)
        proc.setArguments(["-m", "hevc_gui.dvd_ripper.app"])

        # ── EREDITA TEMA DALLA GUI PRINCIPALE ───────────────────────────────
        try:
            env = QProcessEnvironment.systemEnvironment()

            app = QApplication.instance()
            if app is not None:
                # Qt style (Fusion, Windows, ecc.)
                try:
                    sname = app.style().objectName() or ""
                    if sname:
                        env.insert("HEVC_QT_STYLE", sname)
                except Exception:
                    pass

                # Font
                try:
                    f = app.font()
                    fam = f.family() or ""
                    if fam:
                        env.insert("HEVC_QT_FONT_FAMILY", fam)
                    ps = int(f.pointSize()) if f.pointSize() > 0 else 0
                    if ps > 0:
                        env.insert("HEVC_QT_FONT_SIZE", str(ps))
                except Exception:
                    pass

                # Icon theme (se lo usi)
                try:
                    tname = QIcon.themeName() or ""
                    if tname:
                        env.insert("HEVC_ICON_THEME", tname)
                except Exception:
                    pass

                # Stylesheet (QSS) → lo scriviamo su file e passiamo il path
                try:
                    qss = app.styleSheet() or ""
                    if qss.strip():
                        base = (
                            getattr(self, "session_dir", None)
                            or getattr(self, "tmp_dir", None)
                            or Path(os.environ.get("HEVC_RAM_TMP", "/dev/shm/hevc_gui"))
                        )
                        base = Path(base)
                        base.mkdir(parents=True, exist_ok=True)
                        qss_path = base / "theme_from_main.qss"
                        qss_path.write_text(qss, encoding="utf-8")
                        env.insert("HEVC_QT_STYLESHEET_FILE", str(qss_path))
                except Exception:
                    pass

            proc.setProcessEnvironment(env)
        except Exception:
            pass
        # ───────────────────────────────────────────────────────────────────

        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.readyReadStandardOutput.connect(self._on_dvd_ripper_stdout)
        proc.finished.connect(self._on_dvd_ripper_finished)

        proc.start()
        if not proc.waitForStarted(3000):
            if hasattr(self, "txt_info"):
                self.txt_info.append(L("Impossibile avviare DVD Ripper."))
            QMessageBox.critical(self, "DVD Ripper", L("Impossibile avviare DVD Ripper."))
            self.dvd_proc = None
            return

        if hasattr(self, "txt_info"):
            self.txt_info.append(L("> DVD Ripper avviato."))

    @pyqtSlot()
    def _on_dvd_ripper_stdout(self):
        """
        Parla le righe emesse da DVD Ripper e intercetta:
          HEVC_HANDOFF:/percorso/al/file.vob
        """
        if not self.dvd_proc:
            return

        data = bytes(self.dvd_proc.readAllStandardOutput()).decode(errors="ignore")
        if not data:
            return

        for raw_line in data.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            # Log completo nel pannello info
            if hasattr(self, "txt_info"):
                self.txt_info.append(f"[DVD-Ripper] {line}")

            # Protocollo: HEVC_HANDOFF:/percorso/al/file.vob
            if line.startswith("HEVC_HANDOFF:"):
                path_str = line[len("HEVC_HANDOFF:") :].strip()
                from pathlib import Path as _P

                p = _P(path_str)

                if not p.exists():
                    QMessageBox.warning(
                        self,
                        "DVD Ripper",
                        L("Percorso ricevuto da DVD Ripper non valido:\n{path}").format(path=path_str),
                    )
                    continue

                s = str(p)

                # Aggiorna la QLineEdit dell'input: da qui partirà già _path_changed
                line_edit = None
                if hasattr(self, "edit_path"):
                    line_edit = self.edit_path
                elif hasattr(self, "line_input"):
                    line_edit = self.line_input
                elif hasattr(self, "leInput"):
                    line_edit = self.leInput

                if line_edit is not None:
                    line_edit.setText(s)

                if hasattr(self, "txt_info"):
                    self.txt_info.append(L("> Handoff DVD → HEVC: {path}").format(path=s))

    @pyqtSlot(int, QProcess.ExitStatus)
    def _on_dvd_ripper_finished(self, exit_code: int, exit_status: QProcess.ExitStatus):
        if hasattr(self, "txt_info"):
            self.txt_info.append(L("[DVD-Ripper] terminato (exit {code}).").format(code=exit_code))
        self.dvd_proc = None

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

    @pyqtSlot(str)
    def _path_changed(self, text: str):
        try:
            old_file = getattr(self, "_current_file", None)

            p = Path(text).expanduser()
            new_file = p if p.is_file() else None

            # ✅ Nuovo file valido → CONSUME tool (one-shot tra file)
            if new_file is not None and (old_file is None or Path(old_file) != new_file):
                try:
                    clear_crop_settings(disable_only=False)
                except Exception:
                    pass
                try:
                    from hevc_gui.video.trim_tools import clear_trim_settings

                    clear_trim_settings(disable_only=False)
                except Exception:
                    pass
                try:
                    clear_color_settings()
                except Exception:
                    pass
                try:
                    self._preview_offset_sec = 0.0
                except Exception:
                    pass

            self._current_file = new_file

            # abilita convert “base”
            try:
                self.btn_convert.setEnabled(self._current_file is not None)
            except Exception:
                pass

            # auto-suggerimento fps + sidecar
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
                        self.txt_info.append(L("! Impossibile rilevare il frame-rate sorgente (ffprobe)."))
                    except Exception:
                        pass

                try:
                    self._load_ldvd_sidecar_if_present(str(self._current_file))
                except Exception as e:
                    if hasattr(self, "logger"):
                        self.logger.exception(f"_load_ldvd_sidecar_if_present() error: {e}")
            else:
                try:
                    self._ldvd_sidecar = None
                except Exception:
                    pass

            # abilita/disabilita azioni strumenti
            if hasattr(self, "_update_tools_actions_enabled"):
                try:
                    self._update_tools_actions_enabled()
                except Exception:
                    pass

            if hasattr(self, "logger"):
                self.logger.debug(f"_path_changed(): text='{text}' • file_ok={self._current_file is not None}")

        except Exception as e:
            if hasattr(self, "logger"):
                self.logger.exception(f"_path_changed() fatal: {e}")
        finally:
            try:
                self._update_buttons_enabled()
            except Exception:
                pass

    def _probe_src_fps(self, f: Path) -> float | None:
        try:
            out = subprocess.check_output(
                [
                    C.FFPROBE_BIN,
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=avg_frame_rate",
                    "-of",
                    "default=nokey=1:noprint_wrappers=1",
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
        # --- HEVC_FR_EN_FIX_V1: robust framerate suggestion across IT/EN labels ---
        def _to_float(v) -> float | None:
            try:
                return float(str(v).strip().replace(",", "."))
            except Exception:
                return None

        candidates: list[tuple[float, str]] = []
        for x in getattr(C, "FR_CONST_VALUES", []):
            xs = str(x).strip()
            if not xs:
                continue
            if xs.lower() in ("nessuno", "none"):
                continue
            fv = _to_float(xs)
            if fv is None:
                continue
            candidates.append((fv, xs))

        best = min(candidates, key=lambda p: abs(p[0] - float(fps)))[1] if candidates else "23.976"

        picked = False
        try:
            target = _to_float(best)
            if target is not None and hasattr(self, "cmb_frval") and self.cmb_frval is not None:
                for i in range(self.cmb_frval.count()):
                    t = self.cmb_frval.itemText(i)
                    v = _to_float(t)
                    if v is not None and abs(v - target) < 0.02:
                        self.cmb_frval.setCurrentIndex(i)
                        picked = True
                        break
        except Exception:
            picked = False

        if not picked:
            try:
                self.cmb_frval.setCurrentText(best)
                picked = True
            except Exception:
                picked = False

        # se il combo è editabile (o diventa editabile con helper), prova comunque
        if not picked:
            try:
                self.cmb_frval.setEditText(best)
            except Exception:
                pass

        try:
            self.txt_info.append(
                L("> Frame-rate sorgente: {0} fps → suggerito '{1}' (se in modalità Costante).").format(fps, best)
            )
        except Exception:
            pass

    @pyqtSlot()
    def open_output_directory(self):
        if not self._last_output:
            QMessageBox.warning(self, L("Nessuna directory"), L("Nessun file convertito finora."))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._last_output.parent)))

    @pyqtSlot()
    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Apri video", "", "Video (*.mp4 *.mkv *.avi *.mov *.ts *.m2ts *.vob);;Tutti (*)")
        if not path:
            return

        # ✅ Tra un file e l’altro: niente roba “vecchia” attiva
        try:
            clear_crop_settings(disable_only=False)
        except Exception:
            pass
        try:
            from hevc_gui.video.trim_tools import clear_trim_settings

            clear_trim_settings(disable_only=False)
        except Exception:
            pass
        try:
            # se vuoi che anche il colore non “migri” sul nuovo file
            # (coerente col tuo “non memorizzare dopo cambio file”)
            clear_color_settings()
        except Exception:
            pass

        try:
            self._preview_offset_sec = 0.0
        except Exception:
            pass

        self.edit_path.setText(str(path))
        self.txt_info.append(f"> Aperto: {path}")

    def ask_output_path(self, suggested: Path):
        p, _ = QFileDialog.getSaveFileName(
            self,
            "Salva output…",
            str(suggested),
            "MKV (*.mkv);MP4 (*.mp4);Tutti i file (*)",
        )
        return Path(p) if p else None

    # alias di compatibilità (se in giro chiami ancora ask_output_file)
    ask_output_file = ask_output_path

    @pyqtSlot()
    def reset_gui_only(self):
        # ✅ reset GUI → azzera strumenti (crop+trim+color)
        self._consume_video_tools_state(clear_color=True, why="reset_gui_only")

        # Ripristina solo la GUI (campi, log, progress bar),
        # senza cancellare tmp/ né il file queue.json.

        self.edit_path.clear()
        self._current_file = None
        self._last_output = None

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

        self._audio_opts.clear()
        self._subtitle_inputs.clear()
        self._subtitle_langs.clear()
        self._subtitle_types.clear()
        self._subtitle_maps.clear()

        self._subs_integrated_count = 0
        self._chapter_opts.clear()
        self._chapters_handled = False
        self._subs_integrated_count = 0

        self.txt_info.clear()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.lbl_status.setText(L("Wait for conversion…"))
        self.lbl_elapsed.setText(L("Elapsed: 00:00"))
        self.lbl_remaining.setText(L("Remaining: --:--"))
        self._audio_progress = {}

        self._last_queue_cmds = []
        self._last_ffmpeg_log = ""
        self.btn_copy_log.setEnabled(False)

        for _label in ("Originale", "Nessuno"):
            if _label in C.FR_MODE:
                self.cmb_frmode.setCurrentText(_label)
                break
        else:
            self.cmb_frmode.setCurrentIndex(0)

        self.cmb_frval.setEnabled(str(self.cmb_frmode.currentText() or "").strip().lower() in ("costante", "constant"))

        self._update_buttons_enabled()

        for name in ("act_crop", "act_color", "act_trim"):
            act = getattr(self, name, None)
            if act is not None:
                act.setEnabled(False)

    @pyqtSlot()
    def extract_audio(self):
        if not self._current_file:
            return
        dlg = AudioConverter(str(self._current_file), parent=self)
# SAG_TRACK_EDITOR_HOOK
        try:
            from hevc_gui.core.sag_track_editor import attach_track_editor
            attach_track_editor(dlg, L)
        except Exception as _e:
            try:
                self.txt_info.append(L("! SAG: editor tracce non disponibile ({0})").format(_e))
            except Exception:
                pass
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
            self.txt_info.append(L("! Nessuna traccia audio aggiunta."))
            return

        try:
            raw_opts = json.loads(raw)
            self._audio_opts = raw_opts
            self.txt_info.append(f"[DEBUG] _audio_opts = {self._audio_opts}")
            self.txt_info.append(f"> Opzioni audio ricevute: {len(raw_opts)} tracce")
        except Exception as e:
            self._audio_opts = []
            self.txt_info.append(L("! Errore estrazione audio: {0}").format(e))

    def show_mediainfo(self):
        if not self._current_file:
            QMessageBox.information(self, "MediaInfo", L("Nessun file selezionato."))
            return
        MediaInfoDialog(self._current_file, self).exec_()

    def open_crop_tool(self):
        if not self._current_file:
            QMessageBox.information(self, "Crop", "Seleziona prima un file video.")
            return
        try:
            from hevc_gui.gui.crop_dialog import CropDialog
        except Exception as e:
            QMessageBox.critical(self, L("Errore"), f"Modulo crop non disponibile:\n{e}")
            return

        dlg = CropDialog(str(self._current_file), parent=self)
        dlg.exec_()
        # STOP: NON rilanciare automaticamente la preview su Accepted.
        # La preview deve partire SOLO quando premi "Preview filtrata" dentro il dialog.

    @pyqtSlot()
    def open_trim_tool(self):
        """
        Apre il dialog di TRIM per selezionare il segmento da ELIMINARE.

        - Richiede un file corrente (_current_file)
        - Usa, come punto di partenza per la preview interna,
          l'offset usato da crop/color (_preview_offset_sec) se esiste,
          altrimenti ~10 secondi.
        """
        if not getattr(self, "_current_file", None):
            QMessageBox.warning(
                self,
                "Trim",
                "Seleziona prima un file video da convertire.",
            )
            return

        try:
            start_sec = float(getattr(self, "_preview_offset_sec", 10.0) or 10.0)
        except Exception:
            start_sec = 10.0

        dlg = TrimDialog(
            input_path=str(self._current_file),
            grab_time=start_sec,
            parent=self,
        )
        dlg.exec_()
        # Dopo "Applica", il trim è salvato in QSettings e:
        #  - launch_preview(filtered=True) usa già il TRIM
        #  - build_ffmpeg_audio_cmds / build_ffmpeg_external_audio_cmd
        #    tagliano l'audio nello stesso buco.
        # Quando patcheremo il builder video, anche l'encode userà il TRIM.

    @pyqtSlot()
    def open_color_tool(self):
        if not self._current_file:
            QMessageBox.information(self, "Colore", "Seleziona prima un file video.")
            return
        try:
            from hevc_gui.gui.color_dialog import ColorDialog
        except Exception as e:
            QMessageBox.critical(self, L("Errore"), f"Modulo colore non disponibile:\n{e}")
            return

        dlg = ColorDialog(str(self._current_file), parent=self)
        dlg.exec_()  # ← NIENTE auto-preview qui: Applica deve solo salvare e chiudere

    @pyqtSlot()
    def on_actionTrim_triggered(self):
        if not self._current_file:
            QMessageBox.warning(
                self,
                "Taglio",
                "Seleziona prima un file video.",
            )
            return

        dlg = TrimDialog(str(self._current_file), parent=self)
        dlg.exec_()
        # Dopo OK, i settings sono salvati e usati da preview/encode

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
            # i18n-safe: usa key stabile (UserRole+999 / userData) e non crashare
            idx = cmb.currentIndex()
            try:
                ROLE = int(Qt.UserRole) + 999
                key = cmb.itemData(idx, ROLE) or cmb.itemData(idx) or cmb.currentText()
            except Exception:
                key = cmb.currentText()
            val = src.get(key)
            if val is None:
                # fallback: se la UI mostra 'None' ma le chiavi sono italiane tipo 'Nessuno'
                txt = str(cmb.currentText() or "").strip().lower()
                if txt in ("none", "no one", "nobody"):
                    for k in src.keys():
                        if str(k).strip().lower().startswith("nessun"):
                            val = src.get(k)
                            break
            if val is None:
                val = ""
            if val and val not in self._filters:
                self._filters.append(val)

    # ───────────────────── Color tools (luminosità/colore) ─────────────────────

    def _inject_color_filters(self, vf_parts: list[str]) -> None:
        """
        Legge le impostazioni salvate dal ColorDialog e,
        se abilitate, aggiunge il filtro eq=... alla catena -vf.
        """
        try:
            from hevc_gui.video.color_tools import load_color_settings, build_color_filter
        except Exception:
            # modulo non disponibile → niente colore extra
            return

        try:
            res = load_color_settings()
        except Exception:
            return

        # ci aspettiamo (spec, enabled) oppure (spec, enabled, altro…)
        if not isinstance(res, tuple) or len(res) < 2:
            return

        spec, enabled = res[0], bool(res[1])
        if not enabled or spec is None:
            return

        # costruisce la stringa ffmpeg, es: "eq=brightness=0.05:contrast=1.10:saturation=1.15"
        flt = build_color_filter(spec)
        if not flt:
            return

        # evitiamo doppioni
        if flt in vf_parts:
            return

        # lo mettiamo SUBITO dopo il crop, se esiste, altrimenti in coda
        crop_idx = -1
        for i, f in enumerate(vf_parts):
            if f.strip().startswith("crop="):
                crop_idx = i
                break

        if crop_idx >= 0:
            vf_parts.insert(crop_idx + 1, flt)
        else:
            vf_parts.append(flt)

    @pyqtSlot()
    def preview_raw(self):
        """
        Preview RAW (originale): nessun filtro/crop/colore/trim.
        """
        try:
            self.launch_preview(filtered=False)
        except TypeError:
            # compatibilità se qualcuno chiama launch_preview senza keyword
            self.launch_preview(False)

    @pyqtSlot()
    def preview_filtered(self):
        """
        Preview FILTRATA: applica filtri/crop/colore/trim.
        """
        try:
            self.launch_preview(filtered=True)
        except TypeError:
            self.launch_preview(True)

    # --- Alias retrocompatibilità (vecchi nomi usati in giro) ---
    @pyqtSlot()
    def on_preview_filtered_clicked(self):
        return self.preview_filtered()

    @pyqtSlot()
    def start_preview_filtered(self):
        return self.preview_filtered()

    @pyqtSlot()
    def _on_preview_filtered(self):
        return self.preview_filtered()

    @pyqtSlot()
    def launch_preview(self, filtered: bool = False):
        import re
        from PyQt5.QtWidgets import QApplication

        if self.preview_proc and self.preview_proc.state() == QProcess.Running:
            return
        if not self._current_file:
            return

        # ─────────────────────────────────────────────────────────────
        # FIX FOCUS: se preview parte da un dialog modale (crop/color/trim),
        # quel dialog si tiene la tastiera → ffplay non riceve frecce/space.
        # Quindi lo minimizziamo e lo ripristiniamo a fine preview.
        # ─────────────────────────────────────────────────────────────
        self._preview_restore_widget = None
        try:
            w = QApplication.activeModalWidget()
            if w is not None:
                self._preview_restore_widget = w
                w.hide()
        except Exception:
            self._preview_restore_widget = None

        ffplay = getattr(C, "FFPLAY_BIN", "ffplay")
        args = [
            ffplay,
            "-autoexit",
            "-window_title",
            "HEVC-Video Converter - Preview",
            "-x",
            "800",
            "-y",
            "600",
        ]

        # offset di partenza condiviso (RAW o filtered: ok)
        try:
            start_time = float(getattr(self, "_preview_offset_sec", 0.0) or 0.0)
        except Exception:
            start_time = 0.0
        if start_time > 0:
            args += ["-ss", f"{start_time:.3f}"]

        # RAW: niente filtri, niente trim, niente audio filter
        if not filtered:
            args.append(str(self._current_file))
            p = QProcess(self)
            self.preview_proc = p
            p.setProcessChannelMode(QProcess.MergedChannels)
            p.finished.connect(self._on_preview_finished)
            p.errorOccurred.connect(self._on_preview_error)
            p.start(args[0], args[1:])
            return

        # ───────────── filtered preview: qui dentro TUTTE le modifiche ─────────────

        vf_parts: list[str] = list(getattr(self, "_filters", []))
        af_chain = None
        force_169 = False
        force_scope = False
        scale_idx = -1

        # B/N
        if getattr(self, "rd_bw", None) and self.rd_bw.isChecked():
            bw = "hue=s=0"
            if not any(("hue=" in f and "s=0" in f) or ("format=gray" in f) for f in vf_parts):
                vf_parts.append(bw)

        # Crop + flags
        try:
            ret = load_crop_settings()
            spec = ret[0] if len(ret) >= 1 else None
            enabled = bool(ret[1]) if len(ret) >= 2 else False
            force_169 = bool(ret[2]) if len(ret) >= 3 else False
            force_scope = bool(ret[3]) if len(ret) >= 4 else False
        except Exception:
            spec, enabled = (None, False)
            force_169 = force_scope = False

        if enabled and spec:
            inject_crop(vf_parts, spec)

        # Pad in preview (come avevi)
        for i, f in enumerate(vf_parts):
            if re.match(r"^scale=\d+:\d+", f.strip()):
                scale_idx = i
                break
        if scale_idx >= 0:
            m = re.match(r"^scale=(\d+):(\d+)", vf_parts[scale_idx].strip())
            if m:
                target_w = int(m.group(1))
                target_h = int(m.group(2))
                if not force_scope:
                    pad_str = (f"pad={target_w}:{target_h}:( {target_w}-iw )/2:( {target_h}-ih )/2").replace(" ", "")
                    if not any(s.startswith(f"pad={target_w}:{target_h}:") for s in vf_parts):
                        vf_parts.insert(scale_idx + 1, pad_str)

        # Colore globale (eq=...)
        try:
            color_eq = build_color_eq_filter()
            if color_eq:
                vf_parts.append(color_eq)
        except Exception:
            pass

        # setdar forzato (rimane come nel tuo file attuale)
        if not any(s.strip().startswith("setdar=") for s in vf_parts):
            if force_169:
                vf_parts.append("setdar=16/9")
            elif force_scope and scale_idx < 0:
                vf_parts.append("setdar=2.35/1")

        chain = ",".join(vf_parts)

        # TRIM: SOLO in preview filtrata
        try:
            from hevc_gui.video.trim_tools import load_trim_settings, build_video_trim_chain, build_audio_trim_chain

            trim_spec = load_trim_settings()
        except Exception:
            trim_spec = None
            build_video_trim_chain = None  # type: ignore
            build_audio_trim_chain = None  # type: ignore

        if (
            trim_spec
            and getattr(trim_spec, "enabled", False)
            and trim_spec.end_sec > trim_spec.start_sec + 1e-3
            and build_video_trim_chain is not None
        ):
            chain = build_video_trim_chain(chain, trim_spec.start_sec, trim_spec.end_sec)
            try:
                af_chain = build_audio_trim_chain("", trim_spec.start_sec, trim_spec.end_sec)
            except Exception:
                af_chain = None

        if chain:
            args += ["-vf", chain]
        if af_chain:
            args += ["-af", af_chain]

        args.append(str(self._current_file))

        p = QProcess(self)
        self.preview_proc = p
        p.setProcessChannelMode(QProcess.MergedChannels)
        p.finished.connect(self._on_preview_finished)
        p.errorOccurred.connect(self._on_preview_error)
        p.start(args[0], args[1:])

    @pyqtSlot()
    def _on_preview_finished(self):
        self.preview_proc = None

        w = getattr(self, "_preview_restore_widget", None)
        if w is not None:
            try:
                w.show()
                w.raise_()
                w.activateWindow()
                w.setFocus()
            except Exception:
                pass
        self._preview_restore_widget = None

    @pyqtSlot(QProcess.ProcessError)
    def _on_preview_error(self, _err=None):
        # se ffplay non parte o muore subito, ripristina comunque il dialog
        self.preview_proc = None

        w = getattr(self, "_preview_restore_widget", None)
        if w is not None:
            try:
                w.show()
                w.raise_()
                w.activateWindow()
                w.setFocus()
            except Exception:
                pass
        self._preview_restore_widget = None

    def _probe_duration(self, f: Path) -> float:
        try:
            out = subprocess.check_output(
                [
                    C.FFPROBE_BIN,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(f),
                ],
                text=True,
            )
            return float(out.strip()) or 1.0
        except Exception as e:
            self.txt_info.append(L("Errore lettura durata: {0}").format(e))
            QMessageBox.warning(
                self,
                L("Errore FFprobe"),
                f"Non posso misurare la durata del file video:\n{e}\n\nControlla che ffprobe sia installato e accessibile.",
            )
            return 1.0

    def build_ffmpeg_video_cmd(self, video_tmp: Path) -> list[str]:
        """
        Ricodifica video secondo i parametri GUI.

        GARANZIA: MAI deformazioni.
          - niente setdar “a forza bruta”
          - se force_169 / force_scope: ottieni il DAR richiesto solo con scale+pad (barre nere)
          - se SD 720x576/480 e crop non ~4:3: rimuove aspect vecchi e usa scale=720:-2 + setsar=1
        """
        import os
        import re
        import json
        import subprocess
        from hevc_gui.video.trim_tools import load_trim_settings, build_video_trim_chain

        cmd: list[str] = [C.FFMPEG_BIN, "-y", "-nostdin", "-i", str(self._current_file)]

        vf_parts: list[str] = []

        # ─────────────────────────────────────────────────────────────
        # Helpers locali (robusti)
        # ─────────────────────────────────────────────────────────────
        def _find_scale(parts: list[str]) -> tuple[int, int | None, int | None]:
            """Trova il primo scale=W:H (H può essere negativo tipo -2)."""
            for i, f in enumerate(parts):
                m = re.search(r"scale\s*=\s*(\d+)\s*:\s*(-?\d+)", f.replace(" ", ""))
                if m:
                    return i, int(m.group(1)), int(m.group(2))
            return -1, None, None

        def _strip_filters(parts: list[str], prefixes: tuple[str, ...]) -> list[str]:
            """
            Rimuove filtri per prefisso, anche quando sono “incollati” nello stesso elemento.
            Esempio: "...,setsar=16/15,setdar=4/3" -> li toglie.
            """
            out: list[str] = []
            for f in parts:
                chunks = [c.strip() for c in f.split(",") if c.strip()]
                chunks = [c for c in chunks if not any(c.startswith(p) for p in prefixes)]
                if chunks:
                    out.append(",".join(chunks))
            return out

        def _is_close(x: float, target: float, tol: float = 0.02) -> bool:
            try:
                return abs(x - target) <= tol
            except Exception:
                return False

        def _even_round(x: float) -> int:
            v = int(round(x))
            return v if v % 2 == 0 else v + 1

        def _probe_src_wh() -> tuple[int, int]:
            """width/height sorgente (best effort)."""
            try:
                out = subprocess.check_output(
                    [
                        C.FFPROBE_BIN,
                        "-v",
                        "error",
                        "-select_streams",
                        "v:0",
                        "-show_entries",
                        "stream=width,height",
                        "-of",
                        "json",
                        str(self._current_file),
                    ],
                    text=True,
                )
                st = json.loads(out)["streams"][0]
                return int(st.get("width", 0) or 0), int(st.get("height", 0) or 0)
            except Exception:
                return 0, 0

        # ─────────────────────────────────────────────────────────────
        # 1) Filtri base GUI
        # ─────────────────────────────────────────────────────────────
        if getattr(self, "chk_deint", None) and self.chk_deint.isChecked():
            vf_parts.append("yadif=1:-1:0")

        for cmb, levels in (
            (getattr(self, "cmb_sharp", None), C.SHARPNESS_LEVELS),
            (getattr(self, "cmb_smth", None), C.SMOOTHNESS_LEVELS),
            (getattr(self, "cmb_resize", None), C.RESOLUTIONS),
        ):
            if cmb is None:
                continue
            val = levels.get(cmb.currentText(), "")
            if val:
                vf_parts.append(val)

        def _rewrite_sd_16x9_container(parts: list[str]) -> list[str]:
            """
            Se trova scale=720:576 o scale=720:480, riscrive la catena in:
              - pre-scale nel dominio display 16:9 (PAL:1024x576 | NTSC:854x480) con FOAR=decrease
              - pad nel dominio display (letterbox/pillarbox)
              - scale finale a 720x576/480 con le opzioni originali (colormatrix/flags ecc.)
              - setsar (PAL 64/45, NTSC 32/27) + setdar=16/9
            E rimuove qualunque setsar/setdar/pad "vecchio" nel frame SD.
            """
            import re

            # trova primo scale=W:H
            scale_idx = -1
            tw = th = None
            for i, f in enumerate(parts):
                s = f.replace(" ", "")
                m = re.search(r"scale=(\d+):(-?\d+)", s)
                if m:
                    scale_idx = i
                    tw = int(m.group(1))
                    th = int(m.group(2))
                    break

            if scale_idx < 0 or tw is None or th is None:
                return parts
            if (tw, th) not in ((720, 576), (720, 480)):
                return parts

            # target SD → parametri container 16:9
            if (tw, th) == (720, 576):
                disp_w = 1024
                sar = "64/45"
            else:  # 720x480
                disp_w = 854
                sar = "32/27"

            # estrai opzioni originali dello scale (tutto dopo scale=tw:th:)
            orig = parts[scale_idx].replace(" ", "")
            base_opts = ""
            prefix = f"scale={tw}:{th}"
            if orig.startswith(prefix):
                base_opts = orig[len(prefix):]
                if base_opts.startswith(":"):
                    base_opts = base_opts[1:]

            # togli FOAR dall'ultimo scale (lo vogliamo SOLO nel pre-scale)
            base_opts = ":".join([p for p in base_opts.split(":") if p and not p.startswith("force_original_aspect_ratio=")])

            # flags per il pre-scale (se non troviamo flags=..., lanczos)
            flags_only = "flags=lanczos"
            for p in base_opts.split(":"):
                if p.startswith("flags="):
                    flags_only = p
                    break

            scale_pre = f"scale={disp_w}:{th}:{flags_only}:force_original_aspect_ratio=decrease"
            pad_pre = f"pad={disp_w}:{th}:(ow-iw)/2:(oh-ih)/2:color=black"
            scale_final = f"scale={tw}:{th}" + (f":{base_opts}" if base_opts else "")

            # ricostruisci lista:
            # - sostituisci lo scale target con (scale_pre, pad_pre, scale_final)
            # - elimina pad=720:576 / pad=720:480, setsar=*, setdar=*
            out: list[str] = []
            for i, f in enumerate(parts):
                if i == scale_idx:
                    out.extend([scale_pre, pad_pre, scale_final])
                    continue

                chunks = [c.strip() for c in f.split(",") if c.strip()]
                cleaned = []
                for c in chunks:
                    if c.startswith("setsar=") or c.startswith("setdar="):
                        continue
                    if c.startswith("pad=720:576:") or c.startswith("pad=720:480:"):
                        continue
                    cleaned.append(c)

                if cleaned:
                    out.append(",".join(cleaned))

            # chiudi aspect in modo robusto
            out.append(f"setsar={sar}")
            out.append("setdar=16/9")
            return out

        def _bw_filter_local() -> str:
            if getattr(self, "rd_bw", None) and self.rd_bw.isChecked():
                return "hue=s=0"
            return ""

        bw = _bw_filter_local()
        if bw and not any(("hue=" in f and "s=0" in f) or ("format=gray" in f) for f in vf_parts):
            vf_parts.append(bw)

        # ─────────────────────────────────────────────────────────────
        # 2) Crop dai settings (prima dello scale)
        # ─────────────────────────────────────────────────────────────
        try:
            ret = load_crop_settings()
            spec = ret[0] if len(ret) >= 1 else None
            enabled = bool(ret[1]) if len(ret) >= 2 else False
            force_169 = bool(ret[2]) if len(ret) >= 3 else False
            force_scope = bool(ret[3]) if len(ret) >= 4 else False
        except Exception:
            spec, enabled, force_169, force_scope = None, False, False, False

        if enabled and spec:
            inject_crop(vf_parts, spec)

        # DAR del crop (se attivo)
        crop_dar: float | None = None
        try:
            if enabled and spec and getattr(spec, "w", 0) and getattr(spec, "h", 0):
                crop_dar = float(spec.w) / float(spec.h)
        except Exception:
            crop_dar = None

        # Questo flag serve a “bloccare” FOAR+pad generici quando abbiamo già deciso noi.
        skip_foar_and_pad = False

        # ─────────────────────────────────────────────────────────────
        # 3) Caso FORCE 16:9 / 2.35 → MAI setdar forzato, solo canvas+pad
        #    (barre nere, zero deformazioni, sempre)
        # ─────────────────────────────────────────────────────────────
        if force_169 or force_scope:
            desired_dar = (16.0 / 9.0) if force_169 else (2.35 / 1.0)

            # elimina aspect/pad precedenti (es. preset 4:3 o pad generato)
            vf_parts = _strip_filters(vf_parts, prefixes=("setsar=", "setdar=", "pad="))

            si, tw, th = _find_scale(vf_parts)

            # Se non c’è scale, usiamo larghezza “sensata”:
            # - preferisci crop width (se c’è), altrimenti sorgente, altrimenti 720.
            if tw is None:
                if enabled and spec and getattr(spec, "w", 0):
                    tw = int(spec.w)
                else:
                    sw, sh = _probe_src_wh()
                    tw = sw if sw > 0 else 720

            # Canvas:
            # - se scale ha altezza numerica (es. 720x576) → canvas = quella (mantieni output)
            # - se scale ha -2 o non c’è → canvas calcolata dal DAR desiderato (pixel quadrati)
            if th is not None and th > 0:
                canvas_w = int(tw)
                canvas_h = int(th)
            else:
                canvas_w = int(tw)
                canvas_h = _even_round(canvas_w / desired_dar)

            # Assicura scale “decrease” dentro il canvas, preservando eventuali extra (matrix/flags)
            if si >= 0:
                f0 = vf_parts[si]
                # riscrive solo "scale=W:H" -> "scale=canvas_w:canvas_h"
                f1 = re.sub(r"(scale\s*=\s*)\d+\s*:\s*-?\d+", rf"\g<1>{canvas_w}:{canvas_h}", f0)
                if "force_original_aspect_ratio=" not in f1.replace(" ", ""):
                    f1 = f1 + ":force_original_aspect_ratio=decrease"
                vf_parts[si] = f1
            else:
                vf_parts.append(f"scale={canvas_w}:{canvas_h}:force_original_aspect_ratio=decrease")

            # Pad per centrare: crea barre nere (letterbox/pillarbox) quando serve
            vf_parts.append(f"pad={canvas_w}:{canvas_h}:(ow-iw)/2:(oh-ih)/2")

            # Pixel quadrati: evita anamorfismi strani
            vf_parts.append("setsar=1")

            skip_foar_and_pad = True

            try:
                self.txt_info.append(
                    f"[DBG] FORCE canvas: dar={'16:9' if force_169 else '2.35'} canvas={canvas_w}x{canvas_h} (scale+pad, no deformazioni)"
                )
            except Exception:
                pass

        # ─────────────────────────────────────────────────────────────
        # 4) FIX SD + crop non 4:3 (solo se NON siamo in force canvas)
        # ─────────────────────────────────────────────────────────────
        if not skip_foar_and_pad:
            scale_idx_tmp, target_w_tmp, target_h_tmp = _find_scale(vf_parts)

            is_sd_target = (
                scale_idx_tmp >= 0
                and target_w_tmp == 720
                and (target_h_tmp in (576, 480) or (target_h_tmp is not None and target_h_tmp > 0))
            )

            if is_sd_target and crop_dar is not None and not _is_close(crop_dar, 4 / 3):
                # tolgo aspect/pad ereditati (tipico: setsar/setdar 4:3 dal preset)
                vf_parts = _strip_filters(vf_parts, prefixes=("setsar=", "setdar=", "pad="))

                # trasformo scale in 720:-2 (altezza coerente col crop)
                f0 = vf_parts[scale_idx_tmp]
                vf_parts[scale_idx_tmp] = re.sub(r"(scale\s*=\s*\d+\s*:\s*)-?\d+", r"\g<1>-2", f0)

                # pixel quadrati (cerchi restano cerchi)
                vf_parts.append("setsar=1")

                # blocco pad/FOAR generici dopo
                skip_foar_and_pad = True

                try:
                    self.txt_info.append(f"[DBG] SD+crop non 4:3: scale=720:-2 + setsar=1 (crop DAR≈{crop_dar:.3f})")
                except Exception:
                    pass

        # ─────────────────────────────────────────────────────────────
        # 5) Auto-colorimetria + (eventuale) FOAR nello scale
        #    (aggiornato per riconoscere anche scale con -2)
        # ─────────────────────────────────────────────────────────────
        scale_idx, target_w, target_h = _find_scale(vf_parts)

        forcing_matrix = None
        try:
            if scale_idx >= 0 and target_w is not None:
                # target SD: width==720 (anche se height è -2)
                if target_w == 720 and (target_h in (576, 480, 486) or (target_h is not None and target_h < 0)):
                    forcing_matrix = "bt470bg"
                elif target_h is not None and (target_w >= 1280 or target_h >= 720):
                    forcing_matrix = "bt709"

                if forcing_matrix:
                    # matrice ingresso
                    try:
                        meta = subprocess.check_output(
                            [
                                C.FFPROBE_BIN,
                                "-v",
                                "error",
                                "-select_streams",
                                "v:0",
                                "-show_entries",
                                "stream=width,height,color_space",
                                "-of",
                                "json",
                                str(self._current_file),
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

                    orig = vf_parts[scale_idx].strip()
                    compact = orig.replace(" ", "")
                    has_in = "in_color_matrix=" in compact
                    has_out = "out_color_matrix=" in compact
                    has_flag = "flags=" in compact
                    has_foar = "force_original_aspect_ratio=" in compact

                    prefix = re.sub(r"(scale\s*=\s*\d+\s*:\s*-?\d+).*", r"\1", compact)
                    extras = []
                    if not has_in:
                        extras.append(f"in_color_matrix={in_matrix}")
                    if not has_out:
                        extras.append(f"out_color_matrix={forcing_matrix}")
                    if not has_flag:
                        extras.append("flags=lanczos")

                    # FOAR ha senso solo con height numerica e solo se non abbiamo già deciso noi
                    if not has_foar and not skip_foar_and_pad and target_h is not None and target_h > 0:
                        extras.append("force_original_aspect_ratio=decrease")

                    vf_parts[scale_idx] = prefix + (":" + ":".join(extras) if extras else "")

                    cmd += ["-colorspace", forcing_matrix]

                    try:
                        self.txt_info.append(f"[DBG] Auto colorimetria: {in_matrix} → {forcing_matrix} (scale {target_w}x{target_h})")
                    except Exception:
                        pass

            elif scale_idx >= 0 and not skip_foar_and_pad:
                # aggiungi FOAR solo se H numerica
                if target_h is not None and target_h > 0:
                    orig = vf_parts[scale_idx].strip()
                    if "force_original_aspect_ratio=" not in orig.replace(" ", ""):
                        vf_parts[scale_idx] = orig + ":force_original_aspect_ratio=decrease"
        except Exception as e:
            try:
                self.txt_info.append(f"[WARN] Auto colorimetria/FOAR non applicata: {e}")
            except Exception:
                pass

        # ─────────────────────────────────────────────────────────────
        # 6) Pad generico post-scale (solo se H numerica e solo se non skip)
        # ─────────────────────────────────────────────────────────────
        scale_idx, target_w, target_h = _find_scale(vf_parts)
        if (
            scale_idx >= 0
            and target_w is not None
            and target_h is not None
            and target_h > 0
            and not force_scope  # (se vuoi, qui puoi scegliere policy diverse)
            and not skip_foar_and_pad
        ):
            pad_regex = re.compile(r"pad\s*=\s*(\d+)\s*:\s*(\d+)", re.I)
            already_same_pad = False
            for f in vf_parts:
                m = pad_regex.search(f.replace(" ", ""))
                if m and int(m.group(1)) == target_w and int(m.group(2)) == target_h:
                    already_same_pad = True
                    break
            if not already_same_pad:
                vf_parts.insert(scale_idx + 1, f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2")

        # ─────────────────────────────────────────────────────────────
        # 7) Colore (consume=True)
        # ─────────────────────────────────────────────────────────────
        try:
            color_eq = build_color_eq_filter(consume=True)
            if color_eq:
                vf_parts.append(color_eq)
        except Exception:
            pass

        # Debug filtri (pre-TRIM)
        try:
            sharp_lbl = getattr(self, "cmb_sharp", None).currentText() if getattr(self, "cmb_sharp", None) else ""
            sharp_val = C.SHARPNESS_LEVELS.get(sharp_lbl, "")
            self.txt_info.append(f"[DBG] Sharpness: '{sharp_lbl}' → {sharp_val or '(nessuno)'}")
            self.txt_info.append(f"[DBG] -vf base (senza TRIM) = {','.join(vf_parts)}")
        except Exception:
            pass

        # ─────────────────────────────────────────────────────────────
        # 8) TRIM video (segmento da ELIMINARE) via split/trim/concat
        # ─────────────────────────────────────────────────────────────
        vf_parts = _rewrite_sd_16x9_container(vf_parts)
        chain = ",".join(vf_parts) if vf_parts else ""

        trim_spec = None
        try:
            trim_spec = load_trim_settings()
        except Exception:
            trim_spec = None

        if (
            trim_spec
            and getattr(trim_spec, "enabled", False)
            and getattr(trim_spec, "end_sec", 0.0) > getattr(trim_spec, "start_sec", 0.0) + 1e-3
        ):
            try:
                start_sec = float(getattr(trim_spec, "start_sec", 0.0))
                end_sec = float(getattr(trim_spec, "end_sec", 0.0))
                chain = build_video_trim_chain(chain, start_sec, end_sec)
                try:
                    self.txt_info.append(f"[DBG] Video TRIM: elimino segmento {start_sec:.3f}s–{end_sec:.3f}s")
                except Exception:
                    pass
            except Exception as e:
                try:
                    self.txt_info.append(f"[WARN] Trim video non applicato: {e}")
                except Exception:
                    pass

        if chain:
            cmd += ["-vf", chain]

        # ─────────────────────────────────────────────────────────────
        # 9) Codec + parametri base
        # ─────────────────────────────────────────────────────────────
        cmd += ["-map", "0:v:0", "-c:v", "libx265"]

        preset = getattr(self, "cmb_preset", None).currentText() if getattr(self, "cmb_preset", None) else "faster"
        if preset and preset != "Nessuno":
            cmd += ["-preset", preset]

        if getattr(self, "cmb_br", None) and self.cmb_br.isEnabled():
            br = self.cmb_br.currentText()
            if br and br != "Nessuno":
                cmd += ["-b:v", br, "-maxrate", "1500k", "-bufsize", "2000k"]
        else:
            crf = getattr(self, "cmb_crf", None).currentText() if getattr(self, "cmb_crf", None) else "24"
            if crf and crf != "Nessuno":
                cmd += ["-crf", crf]

        # --- HEVC_FR_EN_FIX_V1: normalize framerate mode/value (IT/EN + comma decimals) ---
        fr_mode_text = getattr(self, "cmb_frmode", None).currentText().strip() if getattr(self, "cmb_frmode", None) else ""
        fr_val_text = getattr(self, "cmb_frval", None).currentText().strip() if getattr(self, "cmb_frval", None) else ""

        fr_mode_key = str(fr_mode_text or "").strip().lower()
        if fr_mode_key in ("costante", "constant"):
            fr_mode_key = "constant"
        elif fr_mode_key in ("variabile", "variable"):
            fr_mode_key = "variable"
        elif fr_mode_key in ("originale", "original"):
            fr_mode_key = "original"
        elif fr_mode_key in ("nessuno", "none"):
            fr_mode_key = "none"

        fr_val_norm = str(fr_val_text or "").strip().replace(",", ".")

        try:
            self.txt_info.append(
                f"[DBG] FR: mode='{fr_mode_text}' ({fr_mode_key}) value='{fr_val_text}' norm='{fr_val_norm}'"
            )
        except Exception:
            pass

        if (
            fr_mode_key == "constant"
            and fr_val_norm
            and fr_val_norm.lower() not in ("nessuno", "none")
        ):
            try:
                fr_num = float(fr_val_norm)
                if fr_num <= 0:
                    raise ValueError("fps<=0")
                fr = str(fr_num).rstrip("0").rstrip(".")
            except Exception:
                # lascia comunque passare il testo normalizzato (evita regressioni con combo editable)
                fr = fr_val_norm
            cmd += ["-r", fr, "-vsync", "cfr"]
        elif fr_mode_key == "variable":
            cmd += ["-vsync", "vfr"]
        else:
            cmd += ["-vsync", "0"]

        cmd += ["-pix_fmt", "yuv420p", "-profile:v", "main", "-level", "4.0"]

        # threads / x265 params
        V_THREADS = os.getenv("HEVC_V_THREADS", "2")
        X265_POOLS = os.getenv("HEVC_X265_POOLS", "2")
        X265_FT = os.getenv("HEVC_X265_FRAME_THREADS", "1")

        def _inject_threads(c: list[str]) -> list[str]:
            codec = ""
            try:
                idx = c.index("-c:v")
                if idx + 1 < len(c):
                    codec = c[idx + 1]
            except ValueError:
                pass

            if "-threads" not in c:
                c += ["-threads", V_THREADS]

            if codec == "libx265" and "-x265-params" not in c:
                c += ["-x265-params", f"pools={X265_POOLS}:frame-threads={X265_FT}"]

            return c

        cmd += ["-an", "-sn", "-dn"]
        cmd = _inject_threads(cmd)
        cmd.append(str(video_tmp))

        try:
            self.txt_info.append(f"[DBG] Comando VIDEO finale: {' '.join(cmd)}")
        except Exception:
            pass

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
        import re

        spec = list(self._audio_opts[idx]) if 0 <= idx < len(self._audio_opts) else []
        spec = self._clean_opts(spec)
        # --- HEVC_STRIP_SAG_MARKER_V1 ---
        # rimuove marker SAG e token 'path' spuri finiti nella spec
        if isinstance(spec, (list, tuple)):
            spec = [x for x in spec if x != "__HEVC_SAG_EXTERNAL__"]
            # rimuovi eventuali token che sembrano path e non sono argomenti di opzioni
            # (es: '/home/..._conv.m4a' infilato a metà comando)
            cleaned = []
            i = 0
            while i < len(spec):
                x = spec[i]
                # se è un path e NON è dopo -i, e non è dopo un'opzione che prende argomento,
                # allora è spazzatura e lo scartiamo.
                if isinstance(x, str) and (x.startswith('/') or x.startswith('~')):
                    prev = cleaned[-1] if cleaned else None
                    if prev not in ('-i','-map','-metadata','-metadata:s:a:0','-metadata:s:a:1','-metadata:s:a:2'):
                        # scarta token spurio
                        i += 1
                        continue
                cleaned.append(x)
                i += 1
            spec = cleaned
        # --- END HEVC_STRIP_SAG_MARKER_V1 ---

        # strip eventuale marker SAG (__HEVC_SAG_EXT__ <path>)
        if len(spec) >= 2 and spec[0] == "__HEVC_SAG_EXT__":
            spec = list(spec[2:])

        # ripulisci spec: togli binario/flags e soprattutto '-i <...>' (lo reinseriamo noi)
        stripd = []
        j = 0
        while j < len(spec):
            tok = spec[j]
            if tok in (C.FFMPEG_BIN, 'ffmpeg', '-y', '-nostdin', '-hide_banner'):
                j += 1
                continue
            if tok == '-loglevel' and j + 1 < len(spec):
                j += 2
                continue
            if tok == '-i' and j + 1 < len(spec):
                j += 2
                continue
            stripd.append(tok)
            j += 1
        # elimina eventuale output finale presente nella spec (SAG standalone)
        if stripd and isinstance(stripd[-1], str) and not stripd[-1].startswith('-'):
            stripd = stripd[:-1]
        spec = stripd


        def _get_flag(seq, keys, default=None):
            for k in keys:
                if k in seq:
                    p = seq.index(k)
                    if p + 1 < len(seq):
                        return seq[p + 1]
            return default

        # ── container/estensione in base al codec ─────────────────────────
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
            '-default_mode', 'passthrough',
            container = ["-f", "matroska"]
            tail = []

        fname = f"track_{'QUEUE_' if for_queue else ''}{video_id}_{idx}{ext}" if video_id is not None else f"track_ext{idx}{ext}"
        out = audio_dir / fname

        # ───────────────────────────────────────────────────────────────
        # TRIM settings (una volta)
        # ───────────────────────────────────────────────────────────────
        trim_enabled = False
        trim_in = 0.0
        trim_out = 0.0
        try:
            from hevc_gui.video.trim_tools import load_trim_settings

            ts = load_trim_settings()
            if ts and getattr(ts, "enabled", False):
                trim_in = float(getattr(ts, "start_sec", 0.0) or 0.0)
                trim_out = float(getattr(ts, "end_sec", 0.0) or 0.0)
                if trim_out > trim_in + 1e-3:
                    trim_enabled = True
        except Exception:
            trim_enabled = False

        # ───────────────────────────────────────────────────────────────
        # Comando base
        # ───────────────────────────────────────────────────────────────
        cmd = [C.FFMPEG_BIN, "-y", "-nostdin"]

        # forza input esterno (sostituisce eventuale -i presente)
        if "-i" not in spec:
            spec = ["-i", audio_file] + spec
        else:
            i_pos = spec.index("-i")
            if i_pos + 1 < len(spec):
                spec[i_pos + 1] = audio_file

        # assicura -vn (solo audio)
        if "-vn" not in spec:
            spec += ["-vn"]
        # rileva la traccia richiesta (es: -map 0:a:2) → vale anche per audio esterno
        audio_map = "0:a:0"
        audio_idx_for_fc = 0
        try:
            if "-map" in spec:
                p = spec.index("-map")
                if p + 1 < len(spec):
                    idx_map = spec[p + 1]
                    mm = re.match(r"^0:a:(\d+)$", str(idx_map))
                    if mm:
                        audio_map = str(idx_map)
                        audio_idx_for_fc = int(mm.group(1))
        except Exception:
            pass


        # ───────────────────────────────────────────────────────────────
        # Ricostruisci spec “pulita”:
        # - rimuovi -af (lo ricreiamo)
        # - rimuovi -map (con TRIM useremo [aout], senza TRIM mappiamo 0:a:0)
        # ───────────────────────────────────────────────────────────────
        cleaned: list[str] = []
        it = iter(spec)
        while True:
            try:
                tok = next(it)
            except StopIteration:
                break

            if tok == "-af":
                _ = next(it, "")
                continue

            if tok == "-map":
                _ = next(it, "")
                continue

            # normalizza anche -c:a:0 ecc (opzionale)
            m = re.match(r"^-(c:a|ac|b:a|ar)(?::\d+)?$", tok)
            if m:
                tok = f"-{m.group(1)}"

            cleaned.append(tok)

        # ───────────────────────────────────────────────────────────────
        # Chain filtri GUI (post-concat)
        # ───────────────────────────────────────────────────────────────
        try:
            gui_filters = self._ac_collect_audio_filters_from_ui()
        except Exception:
            gui_filters = []

        if gui_filters:
            post_chain = ("aresample," if sys.platform == "darwin" else "aresample=resampler=soxr,") + join_filters(gui_filters)

        else:
            post_chain = ("aresample," if sys.platform == "darwin" else "aresample=resampler=soxr,") + "dynaudnorm=f=250:g=31:p=0.95:m=50"
        # ───────────────────────────────────────────────────────────────
        # Applica TRIM come nel comando “perfetto”
        # ───────────────────────────────────────────────────────────────
        if trim_enabled:
            fc = (
                f"[0:a:{audio_idx_for_fc}]asplit[a1][a2];"
                f"[a1]atrim=start=0:end={trim_in:.3f},asetpts=PTS-STARTPTS[a1t];"
                f"[a2]atrim=start={trim_out:.3f},asetpts=PTS-STARTPTS[a2t];"
                f"[a1t][a2t]concat=n=2:v=0:a=1,"
                f"{post_chain}[aout]"
            )

            cmd += cleaned
            cmd += ["-filter_complex", fc]
            cmd += ["-map", "[aout]"]  # IMPORTANT: solo output tagliato
            cmd += container + tail

            try:
                self.txt_info.append(f"[DBG] External audio TRIM ON: elimino segmento {trim_in:.3f}s–{trim_out:.3f}s")
                self.txt_info.append(f"[DBG] external audio filter_complex = {fc}")
            except Exception:
                pass

        else:
            # senza trim: usa -af e mappa la prima traccia audio
            cmd += cleaned
            cmd += ["-map", audio_map]
            cmd += ["-af", post_chain]
            cmd += container + tail

            try:
                self.txt_info.append(f"[DBG] External audio TRIM OFF: -af = {post_chain}")
            except Exception:
                pass

        # ── thread limiter come prima ────────────────────────────────────
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
        import os

        steps: list[tuple[Path, list[str]]] = []
        if not getattr(self, "_audio_opts", None):
            return steps

        # ── raccogli bitrate eventuali (-b:a xxxk) per fallback ────────────────
        br_map: dict[int, str] = {}
        for idx, spec in enumerate(self._audio_opts):
            for j, tok in enumerate(spec):
                if tok.startswith("-b:a") and j + 1 < len(spec):
                    br_map[idx] = spec[j + 1]
                    break

        in_video = str(self._current_file) if self._current_file else None

        # --- HEVC_SAG_EXT_AUDIO_FROM_QUEUE_V2 ---
        # Usa metadata per-traccia salvati da SAG (external + audio_file), senza confronti path/nome.
        sag_tracks = None
        _sag_is_ext = None
        _sag_audio_file = None
        try:
            import json
            import glob
            from pathlib import Path as _P

            def _sag_truthy(v):
                if isinstance(v, bool):
                    return v
                if isinstance(v, (int, float)):
                    return bool(v)
                if isinstance(v, str):
                    return v.strip().lower() in ("1", "true", "yes", "y", "on")
                return False

            def _sag_pick_tracks(entry):
                if not isinstance(entry, dict):
                    return None
                for k in ("sag_audio_tracks", "audio_tracks", "audio_jobs", "tracks_audio", "sag_tracks", "tracks"):
                    v = entry.get(k)
                    if isinstance(v, list) and v:
                        return v
                return None

            def _sag_is_ext_fn(t):
                if not isinstance(t, dict):
                    return False
                for k in ("_sag_external", "is_external", "external", "from_external", "sag_external"):
                    if k in t:
                        return _sag_truthy(t.get(k))
                return False

            def _sag_audio_file_fn(t):
                if not isinstance(t, dict):
                    return None
                for k in (
                    "audio_file", "audio_path",
                    "external_file", "external_path",
                    "ext_file", "ext_path",
                    "src_audio", "src_audio_file", "src_audio_path",
                    "source_audio", "source_audio_file", "source_audio_path",
                    "file", "path",
                ):
                    v = t.get(k)
                    if isinstance(v, str) and v.strip():
                        return v
                return None

            def _sag_find_queue_file():
                cand = []
                # RAM / tmp tipici
                cand += [
                    _P("/dev/shm/hevc_gui/sag_queue.json"),
                    _P("/dev/shm/hevc_gui/sessions/sag_queue.json"),
                    _P("/dev/shm/hevc_gui/tmp/sessions/sag_queue.json"),
                ]
                for pat in (
                    "/dev/shm/hevc_gui/sessions/*/sag_queue.json",
                    "/dev/shm/hevc_gui/sessions/*/*/sag_queue.json",
                    "/dev/shm/hevc_gui/tmp/sessions/*/sag_queue.json",
                    "/dev/shm/hevc_gui/tmp/sessions/*/*/sag_queue.json",
                ):
                    for x in glob.glob(pat):
                        cand.append(_P(x))

                # root_progetto/tmp/sessions (tuo requisito macOS)
                try:
                    root = _P(__file__).resolve().parents[2]
                    cand.append(root / "tmp" / "sessions" / "sag_queue.json")
                    for x in (root / "tmp" / "sessions").glob("*/sag_queue.json"):
                        cand.append(x)
                except Exception:
                    pass

                # home
                home = _P.home()
                cand += [
                    home / ".config" / "hevc_gui" / "sag_queue.json",
                    home / ".cache" / "hevc_gui" / "sag_queue.json",
                ]

                for qf in cand:
                    try:
                        if qf.is_file():
                            return qf
                    except Exception:
                        pass
                return None

            qf = _sag_find_queue_file()
            entry = None
            if qf:
                data = json.loads(qf.read_text(encoding="utf-8"))

                want_job_id = None
                for attr in ("_sag_job_id", "sag_job_id"):
                    v = getattr(self, attr, None)
                    if v:
                        want_job_id = str(v)
                        break

                if isinstance(data, list) and data:
                    if want_job_id:
                        for e in reversed(data):
                            if isinstance(e, dict) and str(e.get("sag_job_id", "")) == want_job_id:
                                entry = e
                                break
                    if entry is None:
                        entry = next((e for e in reversed(data) if isinstance(e, dict)), None)
                elif isinstance(data, dict):
                    entry = data

            sag_tracks = _sag_pick_tracks(entry) if entry else None
            _sag_is_ext = _sag_is_ext_fn
            _sag_audio_file = _sag_audio_file_fn
        except Exception:
            sag_tracks = None
            _sag_is_ext = None
            _sag_audio_file = None


        # ── TRIM settings (una volta sola) ─────────────────────────────────────
        trim_enabled = False
        trim_in = 0.0
        trim_out = 0.0
        try:
            from hevc_gui.video.trim_tools import load_trim_settings

            ts = load_trim_settings()
            if ts and getattr(ts, "enabled", False):
                trim_in = float(getattr(ts, "start_sec", 0.0) or 0.0)
                trim_out = float(getattr(ts, "end_sec", 0.0) or 0.0)
                # TRIM valido solo se OUT > IN
                if trim_out > trim_in + 1e-3:
                    trim_enabled = True
        except Exception:
            trim_enabled = False

        for i, spec in enumerate(self._audio_opts):
            if not isinstance(spec, (list, tuple)) or not spec:
                continue

            # --- HEVC_SAG_EXT_AUDIO_FROM_QUEUE_V2 (per-traccia) ---
            if sag_tracks and _sag_is_ext and _sag_audio_file and i < len(sag_tracks):
                t = sag_tracks[i]
                try:
                    if _sag_is_ext(t):
                        af = _sag_audio_file(t)
                        if af:
                            out, cmd = self.build_ffmpeg_external_audio_cmd(
                                audio_file=af,
                                idx=i,
                                audio_dir=audio_dir,
                                video_id=video_id,
                                for_queue=for_queue,
                            )
                            steps.append((out, cmd))
                            continue
                except Exception:
                    pass

            # ── Caso audio ESTERNO: delega all'altro builder ────────────────
            # HEVC_SAG_EXT marker: niente confronti path/estensione/nome.
            # SAG marker external audio: univoco (niente confronti su path/nome/estensione)
            if "__HEVC_SAG_EXTERNAL__" in spec:
                _spec = [t for t in spec if t != "__HEVC_SAG_EXTERNAL__"]
                audio_file = None
                try:
                    k = _spec.index("-i")
                    if k + 1 < len(_spec):
                        audio_file = _spec[k + 1]
                except ValueError:
                    audio_file = None
                # pulisci comunque la spec (tolgo il marker) per evitare sorprese dopo
                spec = _spec
                if audio_file:
                    out, cmd = self.build_ffmpeg_external_audio_cmd(
                        audio_file=audio_file,
                        idx=i,
                        audio_dir=audio_dir,
                        video_id=video_id,
                        for_queue=for_queue,
                    )
                    steps.append((out, cmd))
                    continue

            if len(spec) >= 2 and spec[0] == "__HEVC_SAG_EXT__":
                audio_file = str(spec[1])
                out, cmd = self.build_ffmpeg_external_audio_cmd(
                    audio_file=audio_file,
                    idx=i,
                    audio_dir=audio_dir,
                    video_id=video_id,
                    for_queue=for_queue,
                )
                steps.append((out, cmd))
                continue

            forced_ext = "__HEVC_SAG_EXT__" in spec
            if len(spec) >= 2 and spec[0] == "-i" and (
                forced_ext or (not in_video) or os.path.abspath(spec[1]) != os.path.abspath(in_video)
            ):
                out, cmd = self.build_ffmpeg_external_audio_cmd(
                    audio_file=spec[1],
                    idx=i,
                    audio_dir=audio_dir,
                    video_id=video_id,
                    for_queue=for_queue,
                )
                steps.append((out, cmd))
                continue

            # ── Normalizzazione flag per audio interno ──────────────────────
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

            # ── container/estensione in base al codec ───────────────────────
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

            # ───────────────────────────────────────────────────────────────
            # 1) Costruisci comando base
            # ───────────────────────────────────────────────────────────────
            cmd: list[str] = [C.FFMPEG_BIN, "-y", "-nostdin"]
            if in_video:
                cmd += ["-i", in_video]
            cmd += ["-vn"]  # IMPORTANT: niente -async 1

            # ───────────────────────────────────────────────────────────────
            # 2) Ricava quale stream audio vuoi (da -map) + opzioni/mmetadata
            # ───────────────────────────────────────────────────────────────
            # audio_map = "0:a:N" (dopo la tua normalizzazione)
            audio_map: Optional[str] = None
            audio_idx_for_fc: int = 0  # usato in -filter_complex [0:a:IDX]

            # opzioni che possiamo copiare pari pari
            copied_opts: list[str] = []
            copied_meta: list[str] = []

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
                        # indice audio 0-based: usa esattamente quello passato in -map 0:a:N
                        new_idx = int(m.group(1))
                        audio_map = f"0:a:{new_idx}"
                        audio_idx_for_fc = new_idx
                    # NON aggiungiamo -map qui: lo facciamo dopo (dipende se TRIM attivo)

                elif re.match(r"^-metadata(?::s:a(?::\d+)?)?$", tok):
                    val = next(it, "")
                    copied_meta += [tok, val]

                elif re.match(r"^-(?:c:a|ac|b:a|ar)$", tok):
                    # NOTA: -af lo gestiamo noi
                    val = next(it, "")
                    copied_opts += [tok, val]

                elif tok == "-af":
                    # se arriva già, lo ignoriamo: la chain la ricostruiamo noi
                    _ = next(it, "")
                    continue

                else:
                    # altre robe non utili qui
                    pass

            # se non c'è -map, scegliamo deterministicamente la prima traccia audio
            if audio_map is None:
                audio_map = "0:a:0"
                audio_idx_for_fc = 0

            # ───────────────────────────────────────────────────────────────
            # 3) Costruisci la chain filtri GUI (post-concat)
            # ───────────────────────────────────────────────────────────────
            try:
                gui_filters = self._ac_collect_audio_filters_from_ui()
            except Exception:
                gui_filters = []

            if gui_filters:
                post_chain = "aresample=resampler=soxr," + join_filters(gui_filters)
            else:
                # fallback “default”
                post_chain = "aresample=resampler=soxr,dynaudnorm=f=250:g=31:p=0.95:m=50"
            # ───────────────────────────────────────────────────────────────
            # 4) Se TRIM attivo → usa filter_complex + map [aout]
            # ───────────────────────────────────────────────────────────────
            if trim_enabled:
                # qui replichiamo ESATTAMENTE il comando che ti ha dato risultato perfetto:
                # tieni 0..IN e OUT..fine, poi concat, poi filtri.
                fc = (
                    f"[0:a:{audio_idx_for_fc}]asplit[a1][a2];"
                    f"[a1]atrim=start=0:end={trim_in:.3f},asetpts=PTS-STARTPTS[a1t];"
                    f"[a2]atrim=start={trim_out:.3f},asetpts=PTS-STARTPTS[a2t];"
                    f"[a1t][a2t]concat=n=2:v=0:a=1,"
                    f"{post_chain}[aout]"
                )

                cmd += ["-filter_complex", fc]
                cmd += copied_meta
                cmd += copied_opts

                # IMPORTANT: mappiamo SOLO l’output filtrato/tagliato
                cmd += ["-map", "[aout]"]

                try:
                    self.txt_info.append(f"[DBG] Audio TRIM ON: elimino segmento {trim_in:.3f}s–{trim_out:.3f}s")
                    self.txt_info.append(f"[DBG] audio filter_complex = {fc}")
                except Exception:
                    pass

            else:
                # ── niente trim: flusso semplice con -af ────────────────────
                cmd += ["-map", audio_map]
                cmd += copied_meta
                cmd += copied_opts

                # inserisci -af (filtri) una sola volta
                cmd += ["-af", post_chain]

                try:
                    self.txt_info.append(f"[DBG] Audio TRIM OFF: -af = {post_chain}")
                except Exception:
                    pass

            # ───────────────────────────────────────────────────────────────
            # 5) Bitrate fallback se mancava -b:a
            # ───────────────────────────────────────────────────────────────
            if i in br_map and "-b:a" not in cmd:
                try:
                    pos = cmd.index("-c:a") + 2
                except ValueError:
                    pos = len(cmd)
                cmd[pos:pos] = ["-b:a", br_map[i]]

            # ───────────────────────────────────────────────────────────────
            # 6) Contenitore + output
            # ───────────────────────────────────────────────────────────────
            cmd += container + tail

            # ── Limita thread (come prima) ─────────────────────────────────
            if "-filter_threads" not in cmd:
                cmd += ["-filter_threads", "1"]
            if "-threads" not in cmd:
                cmd += ["-threads", "1"]

            cmd += [str(out)]

            try:
                self.txt_info.append("[DEBUG] audio cmd: " + shlex.join(cmd))
            except Exception:
                pass

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
            QMessageBox.critical(self, L("Errore video"), f"Ricodifica video fallita (code {exit_code})")
            self._full_reset()
            return

        if not Path(self.video_tmp).is_file():
            self.txt_info.append(f"[ERROR] Output video non trovato: {self.video_tmp}")
            QMessageBox.critical(self, L("Errore"), f"Output video non trovato:\n{self.video_tmp}")
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
        self.lbl_status.setText(L("🎵 Ricodifica tracce audio…"))

        video_id = getattr(self, "_current_video_id", None)
        if video_id is None:
            QMessageBox.critical(self, L("Errore"), "ID video non trovato per audio.")
            return

        audio_steps = self.build_ffmpeg_audio_cmds(audio_dir=self.audio_dir, video_id=video_id, for_queue=False)

        if not audio_steps:
            if not self._allow_silent and not getattr(self, "audio_externo", False):
                QMessageBox.information(self, "Audio", L("Nessuna traccia audio da codificare."))
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
            QMessageBox.critical(self, L("Errore"), f"Non posso creare {self.audio_dir}")
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
            self.txt_info.append(L("[DEBUG] Avvio audio seriale #{0}: {1}").format(idx, cmd_str))

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
            QMessageBox.critical(self, L("Errore audio"), f"Traccia {idx} fallita (code {exit_code})")
        else:
            if out and not Path(out).is_file():
                self.txt_info.append(f"[ERROR] Output audio mancante (traccia {idx}): {out}")
                QMessageBox.critical(self, L("Errore audio"), f"Output mancante:\n{out}")
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
            self.lbl_status.setText(L("🔗 Muxing…"))
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
            QMessageBox.critical(self, L("Errore audio"), f"Traccia {idx} fallita (code {exit_code})")
            return

        if all(p.state() != QProcess.Running for p in self._audio_procs):
            self.txt_info.append("[DEBUG] Tutte tracce audio pronte, lancio mux…")
            self.lbl_status.setText(L("🔗 Muxing…"))
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

    def _normalize_sub_kind(self, raw: str) -> tuple[str, str | None]:
        """
        Normalizza il 'kind' dei sottotitoli in:
          - etichetta da mostrare nel titolo
          - eventuale flag di disposition ffmpeg (forced/default/sdh)
        Esempi:
          "forced", "FORCED", "forzati"      -> ("forced", "forced")
          "sdh", "hi", "hearing_impaired"    -> ("sdh", "sdh")
          "default"                          -> ("default", "default")
          "normal", "", None, altro          -> ("normal", None)
        """
        if not raw:
            return ("normal", None)

        k = str(raw).strip().lower()

        # forced
        if k in ("forced", "forzati", "forced_only", "forced-sdh", "sdh-forced"):
            return ("forced", "forced")

        # sdh / hearing impaired
        if k in ("sdh", "hi", "hearing_impaired", "hearing-impaired"):
            return ("sdh", "sdh")

        # default (usato come “sub principale”)
        if k in ("default", "main"):
            return ("default", "default")

        # tutto il resto → solo label, nessun flag
        return (k, None)


    # ───────────────────────────────────────────────────────────────
    # HEVC_AUTO_AUDIO_DELAY_MUX_V1
    # Legge Delay audio da mediainfo (container) e genera itsoffset per mux.
    # itsoffset = -Delay  (es: Delay 3.200s => -itsoffset -3.200)
    # ───────────────────────────────────────────────────────────────
    def _mi_audio_delay_ms_map(self, src_path):
        import json
        import subprocess
        import re
        from pathlib import Path as _P

        key = str(_P(src_path))

        # cache semplice per non richiamare mediainfo 100 volte
        try:
            if getattr(self, "_mi_delay_cache_key", None) == key:
                return dict(getattr(self, "_mi_delay_cache_map", {}) or {})
        except Exception:
            pass

        def _parse_ms(v):
            if v is None:
                return 0
            s = str(v).strip()
            if not s:
                return 0

            # 00:00:03.200 (opzionale segno -)
            m = re.match(r"^(-)?(\d+):(\d+):(\d+(?:\.\d+)?)$", s)
            if m:
                sign = -1 if m.group(1) else 1
                hh = int(m.group(2)); mm = int(m.group(3)); ss = float(m.group(4))
                return int(round(sign * (hh*3600 + mm*60 + ss) * 1000.0))

            # "3 s 200 ms"
            m = re.match(r"^(-)?\s*(?:(\d+)\s*s\s*)?(?:(\d+)\s*ms)?\s*$", s)
            if m and (m.group(2) or m.group(3)):
                sign = -1 if m.group(1) else 1
                sec = int(m.group(2) or 0)
                ms  = int(m.group(3) or 0)
                return sign * (sec*1000 + ms)

            # numero "nudo": mediainfo spesso dà secondi (es "3.200")
            try:
                f = float(s.replace(",", "."))
                return int(round(f * 1000.0)) if abs(f) < 1000 else int(round(f))
            except Exception:
                return 0

        out_map = {}
        try:
            raw = subprocess.check_output(["mediainfo", "--Full", "--Output=JSON", key], text=True)
            js = json.loads(raw)
            tracks = (js.get("media", {}) or {}).get("track", []) or []
            audios = [t for t in tracks if t.get("@type") == "Audio"]

            for idx, a in enumerate(audios):
                # applichiamo SOLO se il delay viene dal container (cautela)
                src = (a.get("Delay_Source_String") or a.get("Delay_Source") or "").strip().lower()
                if src and src != "container":
                    out_map[idx] = 0
                    continue

                v = (
                    a.get("Delay_String3")
                    or a.get("Delay_String2")
                    or a.get("Delay_String1")
                    or a.get("Delay_String")
                    or a.get("Delay")
                )
                out_map[idx] = _parse_ms(v)
        except Exception:
            out_map = {}

        try:
            self._mi_delay_cache_key = key
            self._mi_delay_cache_map = dict(out_map)
        except Exception:
            pass

        return out_map

    def _src_audio_index_from_spec(self, raw_audio_opts, job_i):
        """
        Ritorna N da -map 0:a:N per il job job_i, oppure None se non sicuro.
        (Versione prudente: se non capisco la mappa, NON applico offset.)
        """
        import re
        try:
            if not raw_audio_opts or job_i < 0 or job_i >= len(raw_audio_opts):
                return None
            spec = raw_audio_opts[job_i] or []

            # se è audio esterno/SAG, non applichiamo delay del container (cautela)
            if "__HEVC_SAG_EXTERNAL__" in spec or "__HEVC_SAG_EXT__" in spec:
                return None

            if "-map" in spec:
                p = spec.index("-map")
                if p + 1 < len(spec):
                    m = re.match(r"^0:a:(\d+)$", str(spec[p + 1]))
                    if m:
                        return int(m.group(1))
        except Exception:
            return None
        return None
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
            "-fflags",
            "+genpts+discardcorrupt",
            "-avoid_negative_ts",
            "make_zero",
            "-y",
            "-nostdin",
            "-i",
            str(input_mkv),
            "-i",
            str(video_temp),
        ]

        # ingressi audio (+ itsoffset automatico da MediaInfo Delay, se presente)
        import os
        delay_map = {}
        try:
            enabled = str(os.getenv("HEVC_AUTO_AUDIO_DELAY", "1")).strip().lower() not in ("0", "false", "no", "off")
            if enabled:
                delay_map = self._mi_audio_delay_ms_map(input_mkv)
        except Exception:
            delay_map = {}

        for i, a in enumerate(audio_files):
            try:
                src_idx = self._src_audio_index_from_spec(raw_audio_opts, i)
                ms = int(delay_map.get(int(src_idx), 0)) if src_idx is not None else 0

                # soglia anti-rumore: sotto 10ms non tocchiamo
                if abs(ms) >= 10:
                    off = -(ms / 1000.0)
                    cmd += ["-itsoffset", "{0:.3f}".format(off)]
            except Exception:
                pass

            cmd += ["-i", str(a)]

        # ingressi sottotitoli esterni (file)
        for sub in self._subtitle_inputs:
            cmd += ["-i", str(sub)]

        # capitoli (se presenti)
        chap_path = Path(chapters_file)
        if chap_path.is_file():
            cmd += ["-i", str(chap_path)]
            chap_idx = 2 + len(audio_files) + len(self._subtitle_inputs)
            cmd += ["-map_chapters", str(chap_idx)]

        # video: prendi solo il video ricodificato
        cmd += [
            "-map",
            "1:v",
            "-c:v",
            "copy",
            "-metadata:s:v:0",
            f"title={clean_name}",
        ]

        # audio: copia tutte le tracce esterne generate, con il loro title
        audio_titles = self.extract_audio_titles(raw_audio_opts)
        for i, title in enumerate(audio_titles):
            inp = 2 + i  # input index per l'audio i-esimo
            cmd += [
                "-map",
                f"{inp}:a",
                "-c:a",
                "copy",
                f"-metadata:s:a:{i}",
                f"title={title}",
            ]

        # Sottotitoli incorporati (stream 0:s:x)
        track_idx = 0
        internal_count = len(self._subtitle_langs) - len(self._subtitle_inputs)
        # Se la GUI ci passa map espliciti (0:s:N), usali. Fallback: 0:s:<idx>
        try:
            internal_maps = list(getattr(self, "_subtitle_maps", []) or [])
            if internal_maps:
                internal_count = len(internal_maps)
        except Exception:
            internal_maps = []
        for idx in range(internal_count):
            lang = self._subtitle_langs[idx]
            kind = self._subtitle_types[idx]

            map_str = internal_maps[idx] if idx < len(internal_maps) and internal_maps[idx] else f"0:s:{idx}"
            cmd += [
                "-map",
                map_str,
                "-c:s",
                "copy",
                f"-metadata:s:s:{track_idx}",
                f"language={lang}",
                f"-metadata:s:s:{track_idx}",
                f"title=Subs {track_idx + 1} – {lang} [{kind}]",
            ]

            # ⚠ QUI il fix: usiamo KIND_MAP → "sdh" diventa "hearing_impaired", ecc.
            disp = KIND_MAP.get(kind)
            if disp:
                cmd += [f"-disposition:s:{track_idx}", disp]

            track_idx += 1

        # Sottotitoli esterni (file agganciati)
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
                "-map",
                f"{inp}:s:0",
                "-c:s",
                "copy",
                f"-metadata:s:s:{track_idx}",
                f"language={lang}",
                f"-metadata:s:s:{track_idx}",
                f"title=Subs {track_idx + 1} – {lang} [{kind}]",
            ]

            # stesso fix anche per i file esterni
            disp = KIND_MAP.get(kind)
            if disp:
                cmd += [f"-disposition:s:{track_idx}", disp]

            track_idx += 1

        # metadata globali + opzioni container
        cmd += [
            "-metadata",
            f"title={clean_name}",
            *getattr(self, '_subtitle_out_opts', []),
            '-default_mode', 'passthrough',
            "-cluster_time_limit",
            "20",
            "-cluster_size_limit",
            "32768",
            "-f",
            "matroska",
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
        # ferma timer/animazioni
        try:
            self._stop_timer()
        except Exception:
            pass
        try:
            if getattr(self, "_marquee_timer", None):
                self._marquee_timer.stop()
        except Exception:
            pass

        # torna progressbar normale
        try:
            self.progress.setFormat("%p%")
            self.progress.setRange(0, 100)
        except Exception:
            pass

        # UI base
        try:
            self.btn_pause.setEnabled(False)
            self.btn_cancel.setEnabled(False)
        except Exception:
            pass

        if exit_code != 0:
            try:
                self.progress.setValue(0)
            except Exception:
                pass
            self.txt_info.append(f"[DEBUG] ❌ Mux fallito (exit code {exit_code}).")
            QMessageBox.critical(self, "Mux", f"Mux fallito (codice {exit_code}).")
        else:
            try:
                self.progress.setValue(100)
            except Exception:
                pass
            self.txt_info.append("[DEBUG] ✅ Mux completato con successo.")

            # ✅ CONSUME: dopo encode riuscito → crop/trim spariscono
            self._consume_after_encode_success()

            QMessageBox.information(self, "Mux", "✅ Mux completato!")

        # stato finale
        try:
            self.lbl_status.setText(L("Wait for conversion..."))
            self.lbl_status.setStyleSheet("")
        except Exception:
            pass

        # fine job
        self.ffmpeg_proc = None
        self._update_buttons_enabled()

    @pyqtSlot()
    def on_convert_clicked(self):
        if not self._current_file:
            return

        if not self._audio_opts and not getattr(self, "audio_externo", False):
            reply = QMessageBox.question(
                self,
                L("Attenzione: video senza audio"),
                L("Non hai estratto alcuna traccia audio.\nIl video risultante sarà muto.\nVuoi comunque procedere?"),
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
                    L(
                        "Ci sono {0} comandi in coda.\nSì → salva ed esegui tutta la coda\nNo  → esegui solo questo job\nAnnulla → niente"
                    ).format(len(existing))
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
        self.lbl_status.setText(L("🔨 Ricodifica video…"))
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
            self.lbl_status.setText(L("🔨 Ricodifica video…"))
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
            self.lbl_status.setText(L("🎵 Ricodifica audio…"))
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
            self.lbl_status.setText(L("🔗 Muxing…"))
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
                # dopo MUX OK del batch
                self._consume_after_encode_success()

        self._stop_timer()
        for b in (self.btn_convert, self.btn_elabora, self.btn_salva):
            b.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self.lbl_status.setText(L("Wait for conversion…"))

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
        code = 0
        try:
            code = int(self.ffmpeg_proc.exitCode()) if self.ffmpeg_proc else 0
        except Exception:
            code = 1

        try:
            self._stop_timer()
        except Exception:
            pass

        try:
            self.progress.setFormat("%p%")
            self.progress.setRange(0, 100)
            self.progress.setValue(100 if code == 0 else 0)
        except Exception:
            pass

        if code == 0:
            # ✅ CONSUME anche qui
            self._consume_after_encode_success()
            QMessageBox.information(self, "Conversione completata", "✅ Conversione completata!")
        else:
            QMessageBox.critical(self, L("Errore FFmpeg"), f"❌ Conversione fallita (code {code})")

        try:
            self.lbl_status.setText(L("Wait for conversion..."))
            self.lbl_status.setStyleSheet("")
        except Exception:
            pass

        try:
            self.btn_pause.setEnabled(False)
            self.btn_cancel.setEnabled(False)
        except Exception:
            pass

        self.ffmpeg_proc = None
        try:
            self.reset_state(True)
        except Exception:
            pass

        self._update_buttons_enabled()

    def run_queue(self):
        return self.start_queue_processing()

    @pyqtSlot()
    def save_gui_queue_to_file(self):
        if not self._current_file:
            QMessageBox.warning(self, L("Errore"), "Seleziona prima un file video.")
            return

        if not self._audio_opts and not getattr(self, "audio_externo", False):
            reply = QMessageBox.question(
                self,
                "Attenzione: video senza audio",
                (L("Non hai estratto alcuna traccia audio.\nIl file in coda sarà privo di audio.\nVuoi comunque salvare la coda?")),
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

        raw_audio = self.build_ffmpeg_audio_cmds(
            audio_dir=self.audio_dir,
            video_id=None,
            for_queue=True,
        )
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

        # ───── comandi ffmpeg (video + audio + mux) ─────
        all_cmds = [video_cmd] + audio_cmds + [mux_cmd]

        # filtra eventuali None (se una build_* ha fallito e ha ritornato None)
        valid_cmds = [c for c in all_cmds if c]

        # se non c'è NESSUN comando valido, esci
        if not valid_cmds:
            QMessageBox.critical(
                self,
                L("Errore"),
                L("Nessun comando valido da salvare in coda.\nControlla i parametri di video/audio."),
            )
            return

        # ───── LOG in txt_info e _last_ffmpeg_log ─────
        log = [
            "\n" + "═" * 53,
            "📦 COMANDI SALVATI IN CODA",
            "═" * 53,
        ]
        for i, cmd in enumerate(valid_cmds, 1):
            if isinstance(cmd, (list, tuple)):
                parts = [str(x) for x in cmd]
            else:
                parts = [str(cmd)]
            try:
                line = shlex.join(parts)
            except Exception:
                line = " ".join(parts)
            log.append(f"[{i}/{len(valid_cmds)}] {line}")
        log.append("═" * 53 + "\n")

        self._last_ffmpeg_log = "\n".join(log)
        self._last_queue_cmds = [c.copy() if isinstance(c, list) else list(c) for c in valid_cmds]

        self.txt_info.setTextColor(Qt.blue)
        self.txt_info.append(self._last_ffmpeg_log)
        self.txt_info.setTextColor(Qt.black)
        self.btn_copy_log.setEnabled(True)

        # ───── scrittura su queue (usa ancora qman, come prima) ─────
        for cmd in valid_cmds:
            if not cmd:
                continue
            # stringa leggibile del comando
            if isinstance(cmd, (list, tuple)):
                parts = [str(x) for x in cmd]
            else:
                parts = [str(cmd)]
            try:
                line = shlex.join(parts)
            except Exception:
                line = " ".join(parts)

            added = qman.add(cmd)
            with qman.TMP_QUEUE_FILE.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

            prefix = "✅" if added else "❌"
            self.txt_info.append(f"{prefix} {'Aggiunto' if added else 'Presente'}:\n  {line}")

        self.command_queue = qman.load()
        self.is_queue_saved = True
        self._update_buttons_enabled()
        self._video_idx_queue += 1

    def open_queue_manager(self, *_args, **_kw):
        dlg = QueueDialog(self.command_queue, self)
        if dlg.exec_() == QDialog.Accepted:
            newq = dlg.get_updated_queue()
            if newq != self.command_queue:
                qman.save(newq)
                self._last_queue_run = None
                self.command_queue = newq
                self.txt_info.append("Coda aggiornata e salvata.")
            else:
                self.txt_info.append(L("Nessuna modifica alla coda."))
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
                L("Coda già avviata"),
                L("Hai già avviato questa stessa coda di comandi.\nSei sicuro di volerla lanciare di nuovo?"),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        if not queue:
            QMessageBox.warning(self, "Attenzione", L("La coda è vuota."))
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
            QMessageBox.warning(self, L("Errore"), L("Impossibile eseguire la coda: {0}").format(e))

    def delete_queue_file(self):
        from pathlib import Path

        qfile = Path(qman.QUEUE_FILE)
        if qfile.exists():
            qfile.unlink()

    def _ask_stop(self) -> bool:
        if self.ffmpeg_proc and self.ffmpeg_proc.state() == QProcess.Running:
            ans = QMessageBox.question(
                self,
                L("Conversione in corso"),
                L("È in corso una conversione.\nInterromperla subito?"),
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
        from hevc_gui.video.crop_tools import clear_crop_settings

        try:
            from hevc_gui.video.trim_tools import clear_trim_settings
        except Exception:
            clear_trim_settings = None  # opzionale

        # salva dimensioni finestra
        size = self.size()
        save_window_size(size.width(), size.height())

        # se c'è una conversione in corso, chiedi conferma
        proc = getattr(self, "ffmpeg_proc", None)
        running = bool(proc and proc.state() == QProcess.Running)
        if running:
            ans = QMessageBox.question(
                self,
                L("Conversione in corso"),
                L("È in corso una conversione.\nInterromperla ed uscire?"),
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
                L("Conferma uscita"),
                L("Sei sicuro di voler uscire?"),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if ans != QMessageBox.Yes:
                event.ignore()
                return

        # coda: tieni o butta?
        keep = self._ask_keep_queue()
        if keep is None:
            event.ignore()
            return
        elif not keep:
            qman.clear()

        # ── QUI: prima di chiudere, dimentica crop/trim persistenti ──
        try:
            clear_crop_settings(disable_only=False)
        except Exception:
            pass

        if clear_trim_settings is not None:
            try:
                clear_trim_settings(disable_only=False)
            except Exception:
                pass
        try:
            self._consume_video_tools_state(clear_color=True, why="closeEvent")
        except Exception:
            pass

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
        APP_VERSION = ""
        try:
            from pathlib import Path
            _hevc_ver_file = Path(__file__).resolve().parents[1] / "VERSION"
            if _hevc_ver_file.is_file():
                APP_VERSION = (_hevc_ver_file.read_text(encoding="utf-8").strip() or "")
        except Exception:
            APP_VERSION = ""
        if not APP_VERSION:
            try:
                from hevc_gui.core.constants import APP_VERSION  # legacy fallback
            except Exception:
                APP_VERSION = "unknown"

        pp_w, pp_h = 120, 120
        logo_w, logo_h = 160, 160
        from PyQt5.QtCore import QSize

        dlg = QDialog(self)
        dlg.setWindowTitle(L("Info"))
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
            + L("Ver. {0}<br><br>").format(APP_VERSION)
            + "<b>LorisPaganiniHomeStudio – 2025</b><br><br>"
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
            donate_btn = QPushButton(L(""))
            pm = QPixmap(str(pp_icon_path)).scaled(pp_w, pp_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            donate_btn.setIcon(QIcon(pm))
            donate_btn.setIconSize(QSize(pp_w, pp_h))
            donate_btn.setFixedSize(pp_w, pp_h)
            donate_btn.setToolTip(L("Dona su PayPal"))
            donate_btn.setAccessibleName("Dona su PayPal")
            donate_btn.setCursor(Qt.PointingHandCursor)
            donate_btn.setFlat(True)
            donate_btn.setStyleSheet(
                "QPushButton { border: none; padding: 0; background: transparent; }QPushButton:pressed { transform: translateY(1px); }"
            )
            donate_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://paypal.me/loris1159")))
            layout.addWidget(donate_btn, alignment=Qt.AlignHCenter)
        else:
            donate_btn = QPushButton(L("Dona (PayPal)"))
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
                    "-v",
                    "error",
                    "-select_streams",
                    "s",
                    "-show_entries",
                    "stream=index",
                    "-of",
                    "csv=p=0",
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

        # 1) Se provieni da LDVD-Ripper e c'è un file capitoli sidecar, proponilo subito
        sc = getattr(self, "_ldvd_sidecar", None)
        if sc is not None and sc.chapters_file and sc.chapters_file.is_file():
            use_sidecar = (
                QMessageBox.question(
                    self,
                    "Chapters da DVD",
                    (
                        L(
                            "È stato trovato un file capitoli generato da DVD Ripper:\n{0}\n\nVuoi usare questi capitoli per l'encode?"
                        ).format(sc.chapters_file)
                    ),
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                == QMessageBox.Yes
            )

            if use_sidecar:
                self._chapter_opts = ["-i", str(sc.chapters_file)]
                self._chapters_handled = True
                self.txt_info.append(f"> Capitoli da DVD Ripper selezionati ({sc.chapters_file}).")
                return
            else:
                self.txt_info.append("! Capitoli da DVD Ripper ignorati su scelta utente.")

        # 2) Comportamento “classico”: embedded → eventualmente generazione per scene-change
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
                self.lbl_status.setText(L("Verifica capitoli incorporati…"))
                self._start_marquee()
                QApplication.processEvents()
                try:
                    meta = ChapterManager.get_or_convert_chapters(self._current_file)
                except Exception as exc:
                    self._stop_marquee()
                    QMessageBox.critical(self, "Capitoli", str(exc))
                else:
                    self._stop_marquee()
                    self.lbl_status.setText(L("Wait for conversion…"))
                    self._chapter_opts = ["-i", meta]
                    self.txt_info.append("> Capitoli incorporati compatibili e selezionati.")
                return

        thr, ok = QInputDialog.getDouble(
            self,
            "Threshold Scene Change",
            "Inserisci soglia (0.0–1.0):",
            0.40,
            0.0,
            1.0,
            2,
        )
        if not ok:
            self.txt_info.append("! Capitoli: soglia non confermata.")
            return

        self.lbl_status.setText(L("Generating chapters, wait…"))
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
        self.lbl_status.setText(L("Wait for conversion…"))
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
        self.lbl_status.setText(L("Wait for conversion..."))
        self.lbl_status.setStyleSheet("")

        self.txt_info.append(L("! Errore generazione capitoli: {0}").format(msg))
        QMessageBox.critical(self, L("Chapters"), L("Errore generazione capitoli:\n{0}").format(msg))

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
            QMessageBox.information(self, "Pausa non disponibile", L("La sospensione del processo non è supportata su Windows."))
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
                self.btn_pause.setText(L("Continue"))
            else:
                os.kill(target_pid, signal.SIGCONT)
                if getattr(self, "_tick_timer", None):
                    self._tick_timer.start(1000)
                self._is_paused = False
                self.btn_pause.setText(L("Pause"))
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

        self.lbl_elapsed.setText(L("Elapsed:   00:00:00"))
        self.lbl_remaining.setText(L("Remaining: --:--"))

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
            QMessageBox.warning(self, L("Nessun comando"), L("Non è stato generato alcun comando FFmpeg."))
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
        import json
        import subprocess

        info = {"matrix": "", "primaries": "", "transfer": "", "width": 0, "height": 0}
        try:
            out = subprocess.check_output(
                [
                    C.FFPROBE_BIN,
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=color_space,color_primaries,color_transfer,width,height",
                    "-of",
                    "json",
                    str(f),
                ],
                text=True,
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
            info.update(
                {
                    "matrix": cs or default,
                    "primaries": cp or default,
                    "transfer": ct or default,
                    "width": w,
                    "height": h,
                }
            )
        except Exception:
            # fallback grezzo: usa risoluzione per decidere
            try:
                pass
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





    def _post_mkvpropedit_fix(self, ffmpeg_cmd) -> None:
        """Post-step: forza flag default/forced dei sottotitoli in MKV via mkvpropedit.
        Soft dependency: se mkvpropedit non c'è, non fallire.
        """
        try:
            from shutil import which
            import subprocess
            from pathlib import Path
        except Exception:
            return

        if not isinstance(ffmpeg_cmd, (list, tuple)) or not ffmpeg_cmd:
            return
        # deve essere mux matroska
        if "matroska" not in ffmpeg_cmd:
            return
        out = ffmpeg_cmd[-1]
        try:
            outp = Path(str(out))
        except Exception:
            return
        if outp.suffix.lower() != ".mkv":
            return

        sub_types = list(getattr(self, "_subtitle_types", []) or [])
        if not sub_types:
            return

        exe = which("mkvpropedit")
        if not exe:
            try:
                self.txt_info.append("! mkvpropedit non trovato: installa mkvtoolnix per sistemare default/forced dei sottotitoli.")
            except Exception:
                pass
            return

        # default: primo non-forced (regular). Se sono tutti forced, default sul primo.
        default_idx = 0
        for i, k in enumerate(sub_types):
            if (k or "").lower() != "forced":
                default_idx = i
                break

        args = [exe, str(outp)]
        for i, k in enumerate(sub_types):
            kk = (k or "").lower()
            forced = 1 if kk == "forced" else 0
            default = 1 if (i == default_idx and forced == 0) else 0
            track = f"track:s{i+1}"  # mkvpropedit: s1,s2,...
            args += ["--edit", track, "--set", f"flag-default={default}", "--set", f"flag-forced={forced}"]

        try:
            subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                self.txt_info.append("> mkvpropedit: flag sottotitoli aggiornati (default/forced)")
            except Exception:
                pass
        except Exception:
            try:
                self.txt_info.append("! mkvpropedit: errore durante l'aggiornamento flag sottotitoli")
            except Exception:
                pass
            return
