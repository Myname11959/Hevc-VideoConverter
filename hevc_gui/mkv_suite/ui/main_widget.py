#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, List, Tuple

from PyQt5.QtCore import Qt, QTimer, QUrl, QProcess
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem,
    QTabWidget, QTableWidget, QTableWidgetItem,
    QLabel, QLineEdit, QPushButton, QToolButton, QProgressBar,
    QFileDialog, QTextEdit, QGroupBox, QFormLayout, QSplitter,
    QMessageBox
)
from PyQt5.QtWidgets import QAction  # type: ignore

try:
    from hevc_gui.i18n import L
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

        self._last_in_dir = None  # ultima cartella input (runtime)

        # QProcess queue
        self._proc: Optional[QProcess] = None
        self._proc_buf: str = ""
        self._queue: List[Tuple[List[str], str, bool]] = []   # (cmd, label, allow_fail)
        self._queue_done_msg: str = ""
        self._cur_allow_fail: bool = False

        self._build_ui()
        self._wire_signals()

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
        hook("tag", self.apply_tags)
        hook("extract", self.extract_selected)
        hook("remux", self.remux_selected)
        hook("stop", self.stop_jobs)
        hook("reset", self.reset_all)
        hook("exit", self.exit_app)

        self._update_enabled()

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

        self.list_files = QListWidget()
        self.list_files.setSelectionMode(QListWidget.ExtendedSelection)
        lyt_left.addWidget(self.list_files, 1)

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
        self.tabs.addTab(self.tbl_tracks, L("Tracce"))

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
        btn_pick.setText("…")
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
        self.btn_choose_outdir.setText("…")
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
        self.btn_remux = QPushButton(L("Crea MKV"))
        self.btn_stop = QPushButton(L("Stop"))
        self.btn_reset = QPushButton(L("Annulla"))
        self.btn_exit = QPushButton(L("Esci"))

        self.btn_apply_tags.clicked.connect(self.apply_tags)
        self.btn_extract.clicked.connect(self.extract_selected)
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
        self.progress.setFixedHeight(18)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
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

    def _wire_signals(self) -> None:
        self.btn_add_files.clicked.connect(self.on_add_files)
        self.btn_remove_files.clicked.connect(self.on_remove_selected)
        self.list_files.itemSelectionChanged.connect(self._update_enabled)
        self.tbl_tracks.itemChanged.connect(self._on_track_item_changed)
        self.tbl_tracks.cellDoubleClicked.connect(self._mkv_suite_on_tracks_cell_double_clicked)

    # ---------- basic helpers ----------
        try:
            self._apply_all_tooltips()
        except Exception:
            pass
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

        self.btn_add_files.setEnabled(not self._busy)
        self.btn_remove_files.setEnabled(has_sel and (not self._busy))
        self.btn_choose_outdir.setEnabled(not self._busy)
        self.btn_open_outdir.setEnabled(True)

        self.btn_apply_tags.setEnabled(not self._busy)
        self.btn_extract.setEnabled(not self._busy)
        self.btn_remux.setEnabled(has_any and (not self._busy))

        self.btn_stop.setEnabled(self._busy)
        self.btn_reset.setEnabled(not self._busy)
        self.btn_exit.setEnabled(True)

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
                self._log(f"[OK] Capitoli generati (scene): {out_path}")
            except Exception as e:
                self._log(f"[ERR] Scrittura capitoli: {e}")
                try:
                    self.progress.setValue(0)
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

        finally:
            QTimer.singleShot(0, lambda: setattr(self, "_dlg_guard", False))

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
                it_id.setText("0")
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
        self._set_busy(True)
        self._queue_next()

    def _queue_next(self) -> None:
        if not self._queue:
            self.progress.setValue(0)
            self._set_busy(False)
            if self._queue_done_msg:
                self._log(self._queue_done_msg)
            return

        cmd, label, allow_fail = self._queue.pop(0)
        self._cur_allow_fail = bool(allow_fail)
        self._start_process(cmd, label)

    def _start_process(self, cmd: List[str], label: str) -> None:
        # reset progress for this step
        self.progress.setValue(0)
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
                except Exception:
                    pass
        self._proc_buf = ""

        rc = int(exitCode)
        if rc != 0 and not self._cur_allow_fail:
            self._log(f"[ERR] Comando fallito (rc={rc}).")
            self.progress.setValue(0)
            self._set_busy(False)
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
            v_out = out_root / f"{mkv.stem}_e.mkv"
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

        self._queue_start([(cmd, "mkvmerge", False)], done_msg=L(f"[OK] Rimux creato: {out_file}"))

    def stop_jobs(self) -> None:
        # stop QProcess + clear queue
        self._queue.clear()
        if self._proc and self._proc.state() != QProcess.NotRunning:
            try:
                self._proc.terminate()
            except Exception:
                pass
            QTimer.singleShot(800, lambda: (self._proc.kill() if self._proc and self._proc.state() != QProcess.NotRunning else None))
        self.progress.setValue(0)
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
