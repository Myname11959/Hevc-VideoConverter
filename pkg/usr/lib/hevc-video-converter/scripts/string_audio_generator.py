#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audio-Extractor + Preview per HEVC-GUI (versione con lingua solo da combo UI)"""

from __future__ import annotations

import os
import re
import sys
import json
import shlex
import shutil
import subprocess
from pathlib import Path

from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QComboBox,
    QCheckBox,
    QListWidget,
    QMessageBox,
    QFormLayout,
    QTextEdit,
    QPlainTextEdit,
    QFileDialog,
    QProgressBar,
    QTimeEdit,
    QWidget,
    QAbstractSpinBox,
    QSizePolicy,
)
from PyQt5.QtCore import Qt, pyqtSlot, QProcess, QTimer
from PyQt5.QtGui import QFontMetrics

from hevc_gui.core import constants as C
from hevc_gui.core.audio_helpers import audio_tracks_with_title

try:
    from conversion_thread_external import ConversionThreadExternal
except ModuleNotFoundError:
    from scripts.conversion_thread_external import ConversionThreadExternal

# --- Preview: import robusto (funziona con qualsiasi versione di scripts/preview.py) ---
try:
    import preview as _preview_mod
except Exception as _e:
    raise ImportError(f"Impossibile importare il modulo preview: {_e}")


def run_preview(ac):
    """
    Wrapper robusto: chiama ciò che è disponibile nel modulo preview.
    Priorità: run_preview → start_preview → AudioPreview(...).start()
    """
    fn = getattr(_preview_mod, "run_preview", None)
    if callable(fn):
        print("[UI] run_preview(mod.run_preview) …", flush=True)
        return fn(ac)
    fn = getattr(_preview_mod, "start_preview", None)
    if callable(fn):
        print("[UI] run_preview(mod.start_preview) …", flush=True)
        return fn(ac)
    cls = getattr(_preview_mod, "AudioPreview", None)
    if cls is not None:
        print("[UI] run_preview(AudioPreview.start) …", flush=True)
        obj = cls(ac)
        return obj.start()
    raise ImportError(
        f"preview.py non espone run_preview/start_preview/AudioPreview. File caricato: {getattr(_preview_mod, '__file__', '?')}"
    )


class Batch:
    def __init__(self, video_file: str | None = None):
        """
        video_file: percorso del file video originale, usato per rimuovere solo
        quelle coppie '-i <video_originale>' in flush(). Se None → audio esterno.
        """
        self.items: list[list[str]] = []
        self.file: str | None = video_file

    def set_video_file(self, video_file: str):
        self.file = video_file

    def add(self, seg: list[str]):
        self.items.append(seg)

    def flush(self):
        """
        - Togli 'ffmpeg'/C.FFMPEG_BIN e '-y'
        - Se self.file è definito, rimuove solo '-i <video_originale>'
        - Se audio esterno (file=None) riscrive '-map N:a:X' → '-map 1:X'
        - Stampa il JSON risultante
        """
        cleaned = []
        video_in = self.file
        for seg in self.items:
            opts = seg.copy()
            while opts and opts[0] in (C.FFMPEG_BIN, "ffmpeg"):
                opts.pop(0)
            if opts and opts[0] == "-y":
                opts.pop(0)
            if video_in:
                i = 0
                while i < len(opts) - 1:
                    if opts[i] == "-i" and opts[i + 1] == video_in:
                        opts.pop(i)
                        opts.pop(i)
                    else:
                        i += 1
            cleaned.append(opts)

        if video_in is None:
            for opts in cleaned:
                for i in range(len(opts) - 1):
                    if opts[i] == "-map":
                        m = re.match(r"\d+:a:(\d+)", opts[i + 1])
                        if m:
                            opts[i + 1] = f"1:{m.group(1)}"

        print(json.dumps(cleaned, ensure_ascii=False))
        # self.items.clear()  # opzionale


def get_media_duration_seconds(file_path: str) -> float:
    """Estrae durata media in secondi con ffprobe."""
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            file_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
    except Exception:
        return 0.0


class PreviewProgressDialog(QDialog):
    def __init__(self, parent=None, title="Preparazione preview"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.resize(520, 140)

        v = QVBoxLayout(self)
        self.lbl_file = QLabel("", self)
        self.lbl_file.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl = QLabel("Inizializzazione…", self)
        self.bar = QProgressBar(self)
        self.bar.setRange(0, 0)

        hb = QHBoxLayout()
        self.btn_cancel = QPushButton("Annulla")
        hb.addStretch(1)
        hb.addWidget(self.btn_cancel)

        v.addWidget(self.lbl_file)
        v.addWidget(self.lbl)
        v.addWidget(self.bar)
        v.addLayout(hb)

        self._proc = None
        self._total_secs = None
        self._cancelled = False
        self._fname = ""

        self.btn_cancel.clicked.connect(self._on_cancel)

    @staticmethod
    def _hms(sec: int | float | None) -> str:
        if sec is None or sec < 0:
            return "??:??:??"
        sec = int(sec)
        h = sec // 3600
        m = (sec % 3600) // 60
        s = sec % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

    def attach_process(self, proc: QProcess, *, total_secs: int | None, display_name: str, full_path: str = ""):
        self._proc = proc
        self._total_secs = total_secs
        self._fname = display_name
        self.lbl_file.setText(f"File: {display_name}")
        if full_path:
            self.lbl_file.setToolTip(full_path)
        if total_secs and total_secs > 0:
            self.bar.setRange(0, 100)
            self.bar.setValue(0)
            self.lbl.setText(f"Elaborazione… 0% (00:00:00 / {self._hms(total_secs)})")
        else:
            self.bar.setRange(0, 0)
            self.lbl.setText("Elaborazione…")

        proc.readyReadStandardError.connect(self._on_stderr)
        proc.errorOccurred.connect(lambda e: self.lbl.setText(f"Errore processo: {e}"))
        proc.finished.connect(self._on_finished)

    def _on_cancel(self):
        self._cancelled = True
        try:
            if self._proc is not None:
                self._proc.kill()
        except Exception:
            pass
        self.reject()

    def _on_stderr(self):
        if self._proc is None:
            return
        try:
            chunk = bytes(self._proc.readAllStandardError()).decode("utf-8", "ignore")
        except Exception:
            return

        m = re.search(r"time=(\d+):(\d+):(\d+)(?:\.(\d+))?", chunk)
        if not m:
            return

        h, m_, s, _ = m.groups()
        cur = int(h) * 3600 + int(m_) * 60 + int(s)

        if self._total_secs and self._total_secs > 0:
            tot = self._total_secs
            pct = max(0, min(100, int(cur * 100 / max(1, tot))))
            rem = max(0, tot - cur)
            self.bar.setRange(0, 100)
            self.bar.setValue(pct)
            self.lbl.setText(f"Elaborazione… {pct}% ({self._hms(cur)} / {self._hms(tot)})  •  ETA ~ {self._hms(rem)}")
        else:
            self.lbl.setText(f"Elaborazione… {self._hms(cur)}")

    def _on_finished(self, code, _status):
        if code == 0 and not self._cancelled:
            if self.bar.maximum() == 100:
                self.bar.setValue(100)
                self.lbl.setText("Completato.")
            self.accept()
        elif not self._cancelled:
            self.lbl.setText(f"ffmpeg terminato con codice {code}")
            QTimer.singleShot(1200, self.reject)


# =============================== DIALOG PRINCIPALE ===============================


class AudioConverter(QDialog):
    def __init__(self, auto: str, parent=None):
        super().__init__(parent)

        # finestra
        self.setWindowTitle("String Audio Generator")
        self.resize(560, 680)
        self.setAcceptDrops(True)

        # stato interno
        self.batch = Batch()
        self._closing_via_finish = False
        self.file: Path | None = None
        self._orig_bitrates: dict[int, str] = {}
        self._orig_channels: dict[int, int] = {}

        self.audio_externo = False
        self.external_audio_file: str | None = None
        self.conv_thread_external: ConversionThreadExternal | None = None
        self.external_audio_duration = 0.0

        # costruzione UI
        self._build_ui()
        self._wire_doubleclick_shortcuts()
        self._ensure_preview_wiring()
        self._connect_pan_preset_signals()
        self._update_pan_preset_label()

        # progress bar nascosta
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.layout().addWidget(self.progress_bar)
        self.progress_bar.hide()

        # connessioni base
        self.btn_ok.clicked.connect(self.finish)
        self.btn_load_external_audio.clicked.connect(self.load_external_audio)
        self.cmb_track.currentIndexChanged.connect(self._on_track_changed)
        self.cmb_br.currentTextChanged.connect(self._update_track_title)

        # caricamento iniziale
        self.load_file(auto)

    # === Helpers lingua (unica fonte = combo UI) ==================================
    def _lang_choices(self):
        """
        Restituisce [(code, name)].
        Priorità: C.LANG_CHOICES → derivazione da C.LANGUAGE_NAMES → fallback minimo.
        """
        try:
            if hasattr(C, "LANG_CHOICES"):
                return list(C.LANG_CHOICES)
        except Exception:
            pass
        try:
            if hasattr(C, "LANGUAGE_NAMES") and isinstance(C.LANGUAGE_NAMES, dict):
                out = []
                for k, v in C.LANGUAGE_NAMES.items():
                    code = str(k).lower()
                    if len(code) == 3:
                        out.append((code, v))
                if out:
                    return sorted(out, key=lambda x: (x[1] or "").lower())
        except Exception:
            pass
        return [
            ("und", "Sconosciuta"),
            ("ita", "Italiano"),
            ("eng", "Inglese"),
            ("fra", "Francese"),
            ("deu", "Tedesco"),
            ("spa", "Spagnolo"),
        ]

    def _lang_code_from_combo(self) -> str:
        try:
            code = self.cmb_lang.currentData()
            if code:
                return str(code).strip().lower()
        except Exception:
            pass
        return "und"

    def _lang_human(self, code: str | None) -> str:
        if not code:
            return "—"
        code = str(code).strip()
        try:
            return (
                C.LANGUAGE_NAMES.get(code, None)
                or C.LANGUAGE_NAMES.get(code.upper(), None)
                or C.LANGUAGE_NAMES.get(code.lower(), None)
                or code
            )
        except Exception:
            return code

    def _build_ui(self):
        """
        UI piatta a coordinate, tutta ancorata a sinistra.
        R0  Input track + path
        R1  Tratta come muto + [Carica traccia audio esterna]
        R2  Traccia (combo) — stessa larghezza del path
        R2b Lingua (combo unica)
        R3  Bit-rate + Sample rate
        R4  Noise-Reduction + Denoise + Gain
        R5  EQ Bass/Mid/High
        R6  Reverb / Stereo Enh / Compr
        R7  Auto-loudness + Dialog Boost
        R8  Mantieni MONO + Evita clipping
        R9  Preview: Start + Durata + [Preview]
        R10 Lista comandi
        R11 Stereo (downmix)
        R12 Profilo soundbar (label)
        R13 Samsung — Stereo + Samsung — 5.1
        R14 Footer: Pan preset + Agg. traccia / Cancel / OK
        """
        M = {
            "WIN_W": 560,
            "WIN_H": 680,
            "MARG": 8,
            "ROW_H": 26,
            "VSP": 10,
            "L2F_GAP": 6,
            "HGAP": 14,
            "X0": 16,
            "W_MED": 136,
            "W_FX": 110,
            "W_NUM": 70,
            "W_TIME": 110,
            "W_DUR": 84,
            "W_BTN": 98,
            "H_EDIT": 24,
            "H_BTN": 32,
        }
        CANVAS_W = M["WIN_W"] - 2 * M["MARG"]
        self.setFixedSize(M["WIN_W"], M["WIN_H"])
        self.setAcceptDrops(True)
        vmain = QVBoxLayout(self)
        vmain.setContentsMargins(M["MARG"], M["MARG"], M["MARG"], M["MARG"])
        vmain.setSpacing(6)

        W_TRACK_REQ = 470
        W_LIST = 520
        LIST_ROWS = 2

        BTN_SHRINK = 120
        FORCE_MUTE_W = 154
        EXTRA_GAP = 8

        # ---------- R0 ----------
        path_row = QWidget(self)
        hl = QHBoxLayout(path_row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(M["L2F_GAP"])
        lab_in = QLabel("Input track:", path_row)
        self.path = QLineEdit(path_row)
        self.path.setReadOnly(True)
        hl.addWidget(lab_in, 0, Qt.AlignLeft)
        hl.addWidget(self.path, 0, Qt.AlignLeft)
        hl.addStretch(1)
        vmain.addWidget(path_row, 0, Qt.AlignLeft)

        # ---------- Canvas ----------
        self.canvas = QWidget(self)
        self.canvas.setFixedWidth(CANVAS_W)
        vmain.addWidget(self.canvas, 0, Qt.AlignLeft)

        fm = QFontMetrics(self.font())
        LW_TRACCIA = fm.horizontalAdvance("Traccia:")
        W_TRACK_MAX = max(160, CANVAS_W - M["X0"] - LW_TRACCIA - M["L2F_GAP"] - 8)
        W_TRACK = max(160, min(W_TRACK_REQ, W_TRACK_MAX))
        self.path.setFixedWidth(W_TRACK)

        y = 6

        def new_line(extra=0):
            nonlocal y
            y += M["ROW_H"] + M["VSP"] + extra

        def place(w, x, wdt, h=None):
            h = h or M["H_EDIT"]
            w.setParent(self.canvas)
            w.setGeometry(int(x), int(y), int(wdt), int(h))
            return w

        x = M["X0"]

        def pairL(text, widget, w_field):
            nonlocal x, y
            lab = QLabel(text, self)
            lab.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            lw = lab.sizeHint().width()
            need = lw + M["L2F_GAP"] + w_field
            if x + need > CANVAS_W - 4:
                new_line()
                x = M["X0"]
            place(lab, x, lw)
            x += lw + M["L2F_GAP"]
            place(widget, x, w_field)
            x += w_field + M["HGAP"]
            return lab, widget

        def lone(widget, prefer_w=None, h=None):
            nonlocal x, y
            wdt = prefer_w or (widget.sizeHint().width() + 18)
            if x + wdt > CANVAS_W - 4:
                new_line()
                x = M["X0"]
            place(widget, x, wdt, h or M["H_EDIT"])
            x += wdt + M["HGAP"]
            return widget

        # ---------- R1: Tratta come muto + bottone ----------
        x = M["X0"]
        self.chk_force_mute = QCheckBox("Tratta come muto", self)
        place(self.chk_force_mute, x, FORCE_MUTE_W, M["H_EDIT"])
        x_btn = x + FORCE_MUTE_W + M["HGAP"] + EXTRA_GAP
        ext_btn_w = max(120, min(W_TRACK - BTN_SHRINK, CANVAS_W - x_btn - 4))
        btn_ext = getattr(self, "btn_load_external_audio", None)
        if not isinstance(btn_ext, QPushButton):
            self.btn_load_external_audio = QPushButton("Carica traccia audio esterna", self)
        else:
            self.btn_load_external_audio.setParent(self.canvas)
        self.btn_load_external_audio.setFixedSize(ext_btn_w, M["H_BTN"])
        place(self.btn_load_external_audio, x_btn, ext_btn_w, M["H_BTN"])
        self.btn_load_external_audio.hide()
        try:
            self.btn_load_external_audio.clicked.connect(self.load_external_audio)
        except Exception:
            pass
        new_line()

        # ---------- R2: Traccia ----------
        x = M["X0"]
        self.cmb_track = QComboBox(self)
        self.cmb_track.addItem("Seleziona traccia…", (-1, None, None))
        self.cmb_track.setEnabled(False)
        self.cmb_track.setMinimumWidth(W_TRACK)
        self.cmb_track.setMaximumWidth(W_TRACK)
        pairL("Traccia:", self.cmb_track, W_TRACK)
        new_line()

        # ---------- R2b: Lingua (combo unica) ----------
        x = M["X0"]
        self.cmb_lang = QComboBox(self)
        for code, name in self._lang_choices():
            self.cmb_lang.addItem(f"{name} ({code})", code)

        # default
        def _select_default_lang():
            idx_und = self.cmb_lang.findData("und")
            if idx_und >= 0:
                self.cmb_lang.setCurrentIndex(idx_und)
                return
            idx_ita = self.cmb_lang.findData("ita")
            if idx_ita >= 0:
                self.cmb_lang.setCurrentIndex(idx_ita)

        _select_default_lang()
        pairL("Lingua:", self.cmb_lang, max(180, int(W_TRACK * 0.55)))
        new_line()

        # ---------- R3: Bit-rate + Sample rate ----------
        x = M["X0"]
        self.cmb_br = QComboBox(self)
        self.cmb_br.addItems(getattr(C, "AUD_BITRATES", ["Nessuno"]))
        pairL("Bit-rate:", self.cmb_br, M["W_MED"])
        self.cmb_sr = QComboBox(self)
        self.cmb_sr.addItems(getattr(C, "AUD_SAMPLE_RATES", ["Nessuno"]))
        pairL("Sample rate (Hz):", self.cmb_sr, M["W_MED"])
        new_line()

        # ---------- R4: NR + Gain ----------
        x = M["X0"]
        self.chk_nr = lone(QCheckBox("Noise-Reduction", self), 170)
        self.in_nr = QLineEdit(self)
        self.in_nr.setPlaceholderText("0–30 dB")
        self.in_nr.setEnabled(False)
        self.chk_nr.toggled.connect(self.in_nr.setEnabled)
        pairL("Denoise nr:", self.in_nr, M["W_NUM"])
        self.cmb_gain = QComboBox(self)
        self.cmb_gain.addItems(getattr(C, "AUD_GAIN_RANGE", ["0"]))
        self.cmb_gain.setCurrentText("0")
        pairL("Gain (dB):", self.cmb_gain, M["W_NUM"])
        new_line()

        # ---------- R5: EQ ----------
        x = M["X0"]
        self.cmb_eq_bass = QComboBox(self)
        self.cmb_eq_bass.addItems(getattr(C, "AUD_EQ_DB_CHOICES", ["0"]))
        self.cmb_eq_bass.setCurrentText("0")
        pairL("Bass (dB):", self.cmb_eq_bass, M["W_NUM"])
        self.cmb_eq_mid = QComboBox(self)
        self.cmb_eq_mid.addItems(getattr(C, "AUD_EQ_DB_CHOICES", ["0"]))
        self.cmb_eq_mid.setCurrentText("0")
        pairL("Mid (dB):", self.cmb_eq_mid, M["W_NUM"])
        self.cmb_eq_treb = QComboBox(self)
        self.cmb_eq_treb.addItems(getattr(C, "AUD_EQ_DB_CHOICES", ["0"]))
        self.cmb_eq_treb.setCurrentText("0")
        pairL("High (dB):", self.cmb_eq_treb, M["W_NUM"])
        new_line()

        # ---------- R6: Reverb / Stereo Enh / Compr ----------
        x = M["X0"]
        self.cmb_rev = QComboBox(self)
        self.cmb_rev.addItems(getattr(C, "AUD_REVERB_LEVELS", ["Nessuno"]))
        pairL("Reverb:", self.cmb_rev, M["W_FX"])
        self.cmb_stereo = QComboBox(self)
        self.cmb_stereo.addItem("Nessuno")
        try:
            self.cmb_stereo.addItems(list(getattr(C, "AUD_STEREO_ENHANCERS", {}).keys()))
        except Exception:
            pass
        pairL("Stereo Enh:", self.cmb_stereo, M["W_FX"])
        self.cmb_comp_soft = QComboBox(self)
        self.cmb_comp_soft.addItems(["Nessuno", "Leggero", "Medio", "Forte"])
        self.cmb_comp_soft.setCurrentText("Nessuno")
        pairL("Compr.", self.cmb_comp_soft, M["W_FX"])
        new_line()

        # ---------- R7: Auto-loudness + Dialog Boost ----------
        x = M["X0"]
        self.chk_dyn = lone(QCheckBox("Auto-loudness (DynAudNorm)", self))
        old_gap = M["HGAP"]
        M["HGAP"] = 6
        self.chk_dialog_boost = lone(QCheckBox("Dialog Boost (+2 dB @ 2 kHz)", self))
        M["HGAP"] = old_gap
        new_line()

        # ---------- R8 ----------
        x = M["X0"]
        self.chk_keep_mono = lone(QCheckBox("Mantieni MONO se input mono (AAC 1.0)", self), 310)
        self.chk_anticlip = lone(QCheckBox("Evita clipping", self), 170)
        new_line()

        # ---------- R9: Preview ----------
        x = M["X0"]
        prev_lab = QLabel("Preview:", self)
        w_prev_lab = prev_lab.sizeHint().width()
        place(prev_lab, x, w_prev_lab)
        x += w_prev_lab + M["HGAP"]

        self.te_prev_start = QTimeEdit(self)
        self.te_prev_start.setDisplayFormat("HH:mm:ss")
        self.te_prev_start.setAccelerated(True)
        self.te_prev_start.setButtonSymbols(QAbstractSpinBox.UpDownArrows)
        pairL("Start:", self.te_prev_start, M["W_TIME"])

        self.cmb_prev = QComboBox(self)
        for seconds, label in getattr(C, "AUD_PREVIEW_OPTIONS", [(60, "1 min"), (300, "5 min"), (0, "∞")]):
            self.cmb_prev.addItem(label, seconds)
        pairL("Durata:", self.cmb_prev, M["W_DUR"])

        self.cmb_prev.ensurePolished()
        self.cmb_prev.adjustSize()
        combo_h = max(self.cmb_prev.height(), M["H_EDIT"])
        BTN_H_FIX = 2
        BTN_Y_FIX = -1
        self.btn_prev = QPushButton("Preview", self)
        btn_w = max(M["W_BTN"], self.btn_prev.sizeHint().width() + 20)
        self.btn_prev.setParent(self.canvas)
        self.btn_prev.setGeometry(int(x), int(y + BTN_Y_FIX), int(btn_w), int(combo_h + BTN_H_FIX))
        new_line()

        # ---------- R10: Lista comandi ----------
        x = M["X0"]
        self.list = QListWidget(self)
        self.list_tracks = self.list  # alias compat
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        fm_list = self.list.fontMetrics()
        row_h = fm_list.height() + 6
        frame = 2 * self.list.frameWidth()
        H_LIST = max(LIST_ROWS * row_h + frame + 2, 40)
        place(self.list, x, W_LIST, H_LIST)
        new_line(extra=H_LIST - M["ROW_H"])

        # ---------- R11: Stereo (downmix) ----------
        x = M["X0"]
        self.chk_force_stereo = lone(QCheckBox("Stereo (downmix 2ch)", self), 220)
        self.chk_force_stereo.setObjectName("chk_downmix")
        new_line()

        # ---------- R12: Profilo soundbar ----------
        lbl_sb = QLabel("Profilo soundbar:", self)
        lbl_sb.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        place(lbl_sb, M["X0"], CANVAS_W - 2 * M["X0"])
        new_line()

        # ---------- R13: Samsung ----------
        x = M["X0"]
        self.chk_sb_stereo = QCheckBox("Samsung — Stereo (TV J + HW-R450)", self)
        self.chk_sb_stereo.setObjectName("chk_sb_stereo")
        lone(self.chk_sb_stereo)
        self.chk_sb_51 = QCheckBox("Samsung — 5.1 AC-3 (48 kHz)", self)
        self.chk_sb_51.setObjectName("chk_sb_51")
        lone(self.chk_sb_51)
        self._soundbar_injected = True
        new_line()

        # ---------- R14: Footer ----------
        self.lbl_pan_preset = QLabel("Pan preset: — (nessun downmix)", self)
        place(self.lbl_pan_preset, M["X0"], CANVAS_W - 2 * M["X0"])

        self.btn_add = QPushButton("Agg. traccia", self)
        self.btn_cancel = QPushButton("Annulla", self)
        self.btn_ok = QPushButton("OK / Esci", self)
        self.btn_add.setEnabled(False)
        for b in (self.btn_add, self.btn_cancel, self.btn_ok):
            b.setFixedHeight(M["H_BTN"])

        BTN_GAP = 8
        BTN_SHIFT_RIGHT = 12
        fm_btn = self.fontMetrics()

        def fit_btn(text, minw=88, pad=28):
            return max(minw, fm_btn.horizontalAdvance(text) + pad)

        w_add = fit_btn(self.btn_add.text())
        w_cancel = fit_btn(self.btn_cancel.text())
        w_ok = fit_btn(self.btn_ok.text())
        total_btn_w = w_add + w_cancel + w_ok + 2 * BTN_GAP
        x_btn_grp = CANVAS_W - total_btn_w - BTN_SHIFT_RIGHT

        def place_btn(btn, xx):
            place(btn, xx, fit_btn(btn.text()), M["H_BTN"])

        place(self.btn_add, x_btn_grp, w_add, M["H_BTN"])
        place(self.btn_cancel, x_btn_grp + w_add + BTN_GAP, w_cancel, M["H_BTN"])
        place(self.btn_ok, x_btn_grp + w_add + BTN_GAP + w_cancel + BTN_GAP, w_ok, M["H_BTN"])

        # Canvas height
        path_h = path_row.sizeHint().height()
        avail_h = M["WIN_H"] - (M["MARG"] * 2 + path_h + vmain.spacing())
        self.canvas.setFixedHeight(max(120, avail_h))

        # Anti-troncatura combo
        def _fix_combo(w, minw):
            try:
                w.setMinimumWidth(minw)
                w.setSizePolicy(QSizePolicy.Fixed, w.sizePolicy().verticalPolicy())
                if isinstance(w, QComboBox):
                    w.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
                    w.setMinimumContentsLength(6)
            except Exception:
                pass

        for w in (self.cmb_eq_bass, self.cmb_eq_mid, self.cmb_eq_treb, self.cmb_gain):
            _fix_combo(w, M["W_NUM"])
        for w in (self.cmb_rev, self.cmb_stereo, self.cmb_comp_soft):
            _fix_combo(w, M["W_FX"])
        for w in (self.cmb_br, self.cmb_sr):
            _fix_combo(w, M["W_MED"])
        _fix_combo(self.cmb_prev, M["W_DUR"])

        # Wiring base
        self.btn_prev.clicked.connect(self.make_preview)
        self.btn_add.clicked.connect(self.add_seg)
        self.btn_cancel.clicked.connect(self._reset_defaults)
        self.chk_force_mute.toggled.connect(self._on_force_mute_toggled)
        self.cmb_track.currentIndexChanged.connect(self._on_track_changed)
        # reagisci al toggle “Mantieni MONO…”
        self.chk_keep_mono.toggled.connect(self._refresh_filter_availability)
        self.chk_keep_mono.toggled.connect(self._update_pan_preset_label)

        # Mutua esclusione
        for _cb_name in ("chk_force_stereo", "chk_sb_stereo", "chk_sb_51"):
            cb = getattr(self, _cb_name, None)
            if cb is not None:
                try:
                    cb.toggled.disconnect()
                except Exception:
                    pass
        self._setup_exclusive_audio_profiles()
        self._connect_pan_preset_signals()
        self._update_pan_preset_label()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if not urls:
            return super().dropEvent(event)
        file_path = urls[0].toLocalFile()
        if self.chk_force_mute.isChecked() or self.audio_externo:
            self.load_external_audio(file_path)
        else:
            self.load_file(file_path)
        event.acceptProposedAction()

    def _normalize_eq_combo(self, cmb: QComboBox):
        s = (cmb.currentText() or "").strip().replace(",", ".")
        try:
            v = float(s)
        except Exception:
            v = 0.0
        v = max(-18.0, min(18.0, v))
        txt = f"{v:.2f}".rstrip("0").rstrip(".")
        if txt in ("-0", "+0", ""):
            txt = "0"
        cmb.setCurrentText(txt)

    def _ensure_preview_wiring(self):
        from PyQt5.QtWidgets import QPushButton

        wired = 0

        def _bind_btn(btn):
            nonlocal wired
            try:
                try:
                    btn.clicked.disconnect()
                except Exception:
                    pass
                btn.clicked.connect(lambda: self.make_preview())
                wired += 1
            except Exception:
                pass

        for name in ("btn_preview", "btn_prev", "btn_preview_filtered"):
            btn = getattr(self, name, None)
            if isinstance(btn, QPushButton):
                _bind_btn(btn)
        act = getattr(self, "actionPreview", None)
        try:
            if act and hasattr(act, "triggered"):
                try:
                    act.triggered.disconnect()
                except Exception:
                    pass
                act.triggered.connect(lambda: self.make_preview())
                wired += 1
        except Exception:
            pass
        print(f"[UI] _ensure_preview_wiring: collegati {wired} trigger Preview", flush=True)

    def _wire_doubleclick_shortcuts(self):
        """
        Inserisce (se serve) la riga profilo soundbar e compattazioni varie.
        Doppio-click → Preview solo se HEVC_PREVIEW_DBLCLICK=1.
        """
        import os
        from PyQt5.QtCore import QObject, QEvent
        from PyQt5.QtWidgets import QWidget, QLabel, QCheckBox, QHBoxLayout, QVBoxLayout, QGridLayout, QBoxLayout

        self._allow_dblclick_preview = os.getenv("HEVC_PREVIEW_DBLCLICK", "0") == "1"

        def _top_layout(widget: QWidget):
            lay = getattr(widget, "layout", lambda: None)()
            if lay:
                return lay
            best, best_n = None, -1
            for typ in (QFormLayout, QGridLayout, QBoxLayout):
                for lay in widget.findChildren(typ):
                    n = getattr(lay, "rowCount", getattr(lay, "count", lambda: 0))()
                    if isinstance(n, int) and n > best_n:
                        best, best_n = lay, n
            return best

        def _find_stereo_enh_anchor():
            for lab in self.findChildren(QLabel):
                try:
                    if str(lab.text()).strip().lower().startswith("stereo enh"):
                        return lab
                except Exception:
                    pass
            for nm in ("cmb_stereo", "cmb_stereo_enh", "cmb_enh"):
                w = getattr(self, nm, None)
                if w is not None:
                    return w
            return None

        def _layout_of(widget: QWidget):
            w = widget if isinstance(widget, QWidget) else None
            while w is not None:
                pw = w.parentWidget()
                if pw is None:
                    break
                lay = pw.layout()
                if lay:
                    try:
                        if isinstance(lay, QFormLayout):
                            for r in range(lay.rowCount()):
                                for role in (QFormLayout.LabelRole, QFormLayout.FieldRole):
                                    it = lay.itemAt(r, role)
                                    if it and it.widget() is w:
                                        return lay, pw, r
                        elif isinstance(lay, QGridLayout):
                            rows = lay.rowCount()
                            for r in range(rows):
                                for c in range(max(2, lay.columnCount())):
                                    it = lay.itemAtPosition(r, c)
                                    if it and it.widget() is w:
                                        return lay, pw, r
                        elif isinstance(lay, QBoxLayout):
                            for i in range(lay.count()):
                                it = lay.itemAt(i)
                                if it and it.widget() is w:
                                    return lay, pw, i
                    except Exception:
                        pass
                w = pw
            tl = _top_layout(self)
            return tl, self, None

        def _insert_soundbar_row():
            if getattr(self, "_soundbar_injected", False):
                return True
            anchor = _find_stereo_enh_anchor()
            lay, container, pos = _layout_of(anchor or self)

            row_label = QLabel("Profilo soundbar", container)
            row_box = QWidget(container)
            vb = QVBoxLayout(row_box)
            vb.setContentsMargins(0, 0, 0, 0)
            vb.setSpacing(4)
            hb = QHBoxLayout()
            hb.setContentsMargins(0, 0, 0, 0)
            hb.setSpacing(6)

            cb_st = QCheckBox("Samsung — Stereo (TV J + HW-R450)", row_box)
            cb_51 = QCheckBox("Samsung — 5.1 AC-3 (48 kHz)", row_box)
            cb_st.setObjectName("chk_sb_stereo")
            cb_51.setObjectName("chk_sb_51")
            hb.addWidget(cb_st)
            hb.addWidget(cb_51)
            hb.addStretch(1)
            vb.addLayout(hb)

            if not getattr(self, "lbl_pan_preset", None):
                self.lbl_pan_preset = QLabel("Pan preset: nessuno (input stereo/mono o profili spenti)", row_box)
                self.lbl_pan_preset.setStyleSheet("color: #777;")
            vb.addWidget(self.lbl_pan_preset)

            self._soundbar_profile = "none"
            self.chk_sb_stereo = cb_st
            self.chk_sb_51 = cb_51
            stereo_candidates = [getattr(self, "chk_force_stereo", None)]
            group = [cb_st, cb_51] + [w for w in stereo_candidates if w is not None]

            def _set_profile(mode: str):
                self._soundbar_profile = mode

            def _uncheck_others(src):
                for w in group:
                    if w is src:
                        continue
                    try:
                        w.blockSignals(True)
                        w.setChecked(False)
                        w.blockSignals(False)
                    except Exception:
                        pass

            def _on_stereo(ticked: bool):
                if ticked:
                    _uncheck_others(cb_st)
                    _set_profile("samsung_stereo")
                else:
                    if not any(w.isChecked() for w in group if w is not cb_st):
                        _set_profile("none")
                self._update_pan_preset_label()

            def _on_51(ticked: bool):
                if ticked:
                    _uncheck_others(cb_51)
                    _set_profile("samsung_5_1_ac3")
                else:
                    if not any(w.isChecked() for w in group if w is not cb_51):
                        _set_profile("none")
                self._update_pan_preset_label()

            cb_st.toggled.connect(_on_stereo)
            cb_51.toggled.connect(_on_51)
            cb_st.toggled.connect(lambda _: self._refresh_filter_availability())
            cb_51.toggled.connect(lambda _: self._refresh_filter_availability())

            for w in stereo_candidates:
                if w is None:
                    continue

                def _mk(wref):
                    def _on_ext_stereo(ticked: bool):
                        if ticked:
                            _uncheck_others(wref)
                            _set_profile("none")
                            self._update_pan_preset_label()
                        self._refresh_filter_availability()

                    return _on_ext_stereo

                try:
                    w.toggled.connect(_mk(w))
                except Exception:
                    pass

            try:
                if isinstance(lay, QFormLayout):
                    ins_row = (pos + 1) if (pos is not None) else lay.rowCount()
                    lay.insertRow(ins_row, row_label, row_box)
                elif isinstance(lay, QGridLayout):
                    ins_row = (pos + 1) if (pos is not None) else lay.rowCount()
                    lay.addWidget(row_label, ins_row, 0)
                    lay.addWidget(row_box, ins_row, 1)
                elif isinstance(lay, QBoxLayout):
                    ins_idx = (pos + 1) if (pos is not None) else lay.count()
                    lay.insertWidget(ins_idx, row_label)
                    lay.insertWidget(ins_idx + 1, row_box)
                else:
                    tl = _top_layout(self)
                    if isinstance(tl, QFormLayout):
                        tl.addRow(row_label, row_box)
                    elif isinstance(tl, QGridLayout):
                        r = tl.rowCount()
                        tl.addWidget(row_label, r, 0)
                        tl.addWidget(row_box, r, 1)
                    elif isinstance(tl, QBoxLayout):
                        tl.addWidget(row_label)
                        tl.addWidget(row_box)
                    else:
                        return False
            except Exception:
                return False

            self._soundbar_injected = True
            self._update_pan_preset_label()
            self._refresh_filter_availability()
            return True

        def _shrink_cmd_box(max_lines: int = 2):
            try:
                candidates = []
                for ed in list(self.findChildren(QPlainTextEdit)) + list(self.findChildren(QTextEdit)):
                    score = 0
                    try:
                        if getattr(ed, "isReadOnly", lambda: False)():
                            score += 2
                    except Exception:
                        pass
                    name = ed.objectName() if hasattr(ed, "objectName") else ""
                    if any(k in (name or "").lower() for k in ("cmd", "command", "preview", "ffmpeg")):
                        score += 3
                    score += max(ed.maximumHeight(), ed.height())
                    candidates.append((score, ed))
                if not candidates:
                    return
                ed = sorted(candidates, key=lambda x: x[0], reverse=True)[0][1]
                fm = ed.fontMetrics()
                line_h = fm.lineSpacing() if hasattr(fm, "lineSpacing") else fm.height()
                h = int(line_h * max_lines + 10)
                ed.setMinimumHeight(h)
                ed.setMaximumHeight(h)
                if isinstance(ed, QTextEdit):
                    ed.setLineWrapMode(QTextEdit.NoWrap)
            except Exception:
                pass

        def _find_preview_target():
            for name in ("btn_prev", "btn_preview", "btn_preview_filtered", "actionPreview"):
                obj = getattr(self, name, None)
                if obj is not None:
                    return obj
            return None

        def _trigger_preview():
            tgt = _find_preview_target()
            try:
                if tgt is None:
                    return
                if hasattr(tgt, "click"):
                    tgt.click()
                elif hasattr(tgt, "trigger"):
                    tgt.trigger()
            except Exception:
                pass

        class _DoubleClickFilter(QObject):
            def __init__(self, parent, cb):
                super().__init__(parent)
                self._parent = parent
                self._cb = cb

            def eventFilter(self, obj, ev):
                if ev.type() == QEvent.MouseButtonDblClick:
                    if not getattr(self._parent, "_allow_dblclick_preview", False):
                        return False
                    if hasattr(obj, "isEnabled") and not obj.isEnabled():
                        return False
                    try:
                        self._cb()
                    except Exception:
                        pass
                    return True
                return False

        def _enable_dblclick(w, cb):
            if w is None:
                return
            try:
                f = _DoubleClickFilter(self, cb)
                setattr(w, "_dblclick_filter_", f)
                w.installEventFilter(f)
            except Exception:
                pass

        def _wire_doubleclick():
            if not self._allow_dblclick_preview:
                return
            names = ("cmb_eq_bass", "cmb_eq_mid", "cmb_eq_treb", "cmb_comp_soft", "cmb_stereo")
            for nm in names:
                w = getattr(self, nm, None)
                if w is not None and hasattr(w, "installEventFilter"):
                    _enable_dblclick(w, _trigger_preview)

        def _do_all():
            ok = _insert_soundbar_row()
            _shrink_cmd_box(max_lines=2)
            _wire_doubleclick()
            return ok

        if not _do_all():
            QTimer.singleShot(120, _do_all)

    def _fmt_track_label(self, idx: int, lang: str | None, br: str) -> str:
        """
        Etichetta combo tracce con badge [M]/[S]/[MC] + lingua (da combo UI) + BR/SR.
        """
        lang = self._lang_code_from_combo()
        lang_full = self._lang_human(lang)
        sr = self.cmb_sr.currentText() if getattr(self, "cmb_sr", None) else "Nessuno"

        ch = self._orig_channels.get(idx)
        if ch is None:
            try:
                if self.audio_externo and self.external_audio_file:
                    ch = self._probe_audio_channels(self.external_audio_file, int(str(idx).split(":")[-1]))
                elif self.file:
                    ch = self._probe_audio_channels(str(self.file), int(str(idx).split(":")[-1]))
            except Exception:
                ch = None

        badge = self._badge_from_channels(int(ch)) if ch else ""
        pieces = [f"{badge} Traccia {idx}"]
        if lang_full and lang_full != "—":
            pieces.append(lang_full)
        if br and br != "Nessuno":
            pieces.append(br)
        if sr and sr != "Nessuno":
            try:
                if sr.isdigit():
                    pieces.append(f"{int(sr)}Hz")
            except Exception:
                pass
        return " – ".join(pieces)

    def _badge_from_channels(self, ch: int) -> str:
        if ch <= 1:
            return "[M]"
        elif ch == 2:
            return "[S]"
        else:
            return "[MC]"

    def _probe_audio_channels(self, path: str, a_idx: int) -> int:
        """Ritorna #canali dell'audio stream a_idx, 0 se non trovabile."""
        try:
            from hevc_gui.core.ffprobe_utils import probe_audio_stream

            info = probe_audio_stream(path, stream_index=int(a_idx)) or {}
            ch = int(info.get("channels") or 0)
            return ch if ch > 0 else 0
        except Exception:
            return 0

    @pyqtSlot(str)
    def load_file(self, p: str):
        """
        Carica file come sorgente; popola cmb_track con (idx, lang=<combo>, br or 'Nessuno').
        Nessun dialog lingua.
        """
        if not hasattr(self, "_orig_channels"):
            self._orig_channels: dict[int, int] = {}
        self.file = Path(p)
        # FIX: informa la Batch del video, così flush NON tratta come “audio esterno”
        try:
            self.batch.set_video_file(str(self.file))
        except Exception:
            pass

        self._orig_bitrates.clear()
        self._orig_channels.clear()

        self.cmb_track.clear()
        self.cmb_track.addItem("Seleziona traccia…", (-1, None, None))

        # Modalità "muto" → audio esterno guidato
        if getattr(self, "chk_force_mute", None) and self.chk_force_mute.isChecked():
            self.audio_externo = True
            self.external_audio_file = str(self.file)
            try:
                self.path.setText(f"Trattato come muto: {self.file}")
            except Exception:
                pass
            self.cmb_track.clear()
            self.cmb_track.addItem("File muto → carica audio esterno…", (-1, None, None))
            self.cmb_track.setEnabled(False)
            self.btn_load_external_audio.show()
            self.btn_add.setEnabled(False)
            return

        tracks = list(audio_tracks_with_title(str(self.file)))
        if not tracks:
            self.audio_externo = True
            self.external_audio_file = None
            self.path.clear()
            self.btn_load_external_audio.show()
            self.cmb_track.setEnabled(False)
            self.btn_add.setEnabled(False)
        else:
            self.audio_externo = False
            self.btn_load_external_audio.hide()
            self.path.setText(str(self.file))
            self.cmb_track.setEnabled(True)
            cur_lang = self._lang_code_from_combo()
            for pos, (idx_raw, title) in enumerate(tracks):
                a_idx = self._norm_audio_index(idx_raw, pos)
                br_lbl = self._probe_audio_bitrate_label(str(self.file), a_idx)
                if br_lbl:
                    self._orig_bitrates[a_idx] = br_lbl
                ch = self._probe_audio_channels(str(self.file), a_idx)
                if ch:
                    self._orig_channels[a_idx] = ch
                label = self._fmt_track_label(a_idx, cur_lang, br_lbl or "Nessuno")
                if title:
                    label += f" – {title}"
                self.cmb_track.addItem(label, (a_idx, cur_lang, br_lbl or "Nessuno"))
            self.btn_add.setEnabled(False)

        self.cmb_track.setCurrentIndex(0)
        try:
            print("[DEBUG] Combo tracce:")
            for i in range(self.cmb_track.count()):
                print(f"  {i:02d}: text='{self.cmb_track.itemText(i)}' data={self.cmb_track.itemData(i)}")
        except Exception:
            pass

    @pyqtSlot()
    def load_external_audio(self, file_path: str | None = None):
        """
        Carica una traccia **esterna** e popola cmb_track con:
          (idx, lang=<combo UI>, br) — NESSUN dialog lingua.
        Imposta Batch in modalità 'esterno' (Batch.file=None) per la flush corretta.
        """
        # init cache
        if not hasattr(self, "_orig_channels"):
            self._orig_channels: dict[int, int] = {}
        if not hasattr(self, "_orig_bitrates"):
            self._orig_bitrates: dict[int, str] = {}

        # Se non arriva un path → apri file dialog
        if not file_path:
            start_dir = str(self.file.parent) if getattr(self, "file", None) else os.path.expanduser("~")
            filters = (
                "Audio (*.wav *.flac *.aac *.m4a *.mp3 *.ogg *.ac3 *.eac3);;Video con audio (*.mkv *.mp4 *.mov *.avi);;Tutti i file (*)"
            )
            file_path, _ = QFileDialog.getOpenFileName(self, "Seleziona traccia audio esterna", start_dir, filters)
            if not file_path:
                return  # annullato

        # Stato esterno ON
        self.external_audio_file = file_path
        self.audio_externo = True

        # Batch: segnala che NON c'è un video file (così flush fa 0:a:x → 1:x)
        try:
            self.batch.set_video_file(None)
        except Exception:
            pass

        # Lingua: SOLO dalla combo UI
        try:
            # usa helper se presente
            cur_lang = self._lang_code_from_combo()
        except Exception:
            # fallback: prova cmb_lang, altrimenti 'und'
            try:
                idx = self.cmb_lang.currentIndex()
                cur_lang = (self.cmb_lang.itemData(idx) or self.cmb_lang.currentText() or "und").strip() or "und"
            except Exception:
                cur_lang = "und"
        self.external_audio_lang = cur_lang

        # UI path
        try:
            self.path.setText(f"Audio esterno: {file_path}")
        except Exception:
            pass

        # Lettura tracce e probing
        try:
            tracks = list(audio_tracks_with_title(file_path))
        except Exception:
            tracks = []

        self._orig_bitrates.clear()
        self._orig_channels.clear()

        self.cmb_track.blockSignals(True)
        self.cmb_track.clear()
        self.cmb_track.addItem("Seleziona traccia…", (-1, None, None))

        if tracks:
            for pos, (idx_raw, title) in enumerate(tracks):
                a_idx = self._norm_audio_index(idx_raw, pos)
                br_lbl = self._probe_audio_bitrate_label(file_path, a_idx)
                if br_lbl:
                    self._orig_bitrates[a_idx] = br_lbl
                ch = self._probe_audio_channels(file_path, a_idx)
                if ch:
                    self._orig_channels[a_idx] = ch

                label = self._fmt_track_label(a_idx, cur_lang, br_lbl or "Nessuno")
                if title:
                    label += f" – {title}"
                # itemData = (indice reale, lingua da combo, bitrate reale|Nessuno)
                self.cmb_track.addItem(label, (a_idx, cur_lang, br_lbl or "Nessuno"))

            # seleziona la prima traccia reale se presente
            self.cmb_track.setCurrentIndex(1 if self.cmb_track.count() > 1 else 0)
        else:
            # fallback: file con una singola pista “mutizzata”
            self.cmb_track.addItem(self._fmt_track_label(0, cur_lang, "Nessuno"), (0, cur_lang, "Nessuno"))
            self.cmb_track.setCurrentIndex(1 if self.cmb_track.count() > 1 else 0)

        self.cmb_track.setEnabled(True)
        self.cmb_track.blockSignals(False)

        # Bottoni e visibilità
        try:
            self.btn_add.setEnabled(False)
            self.btn_load_external_audio.show()
        except Exception:
            pass

        # Debug elenco
        try:
            print("[DEBUG] Combo tracce (esterne):")
            for i in range(self.cmb_track.count()):
                print(f"  {i:02d}: text='{self.cmb_track.itemText(i)}' data={self.cmb_track.itemData(i)}")
        except Exception:
            pass

        # Refresh abilitazioni/label
        try:
            self._refresh_filter_availability()
            self._update_pan_preset_label()
        except Exception:
            pass

    def _norm_audio_index(self, idx, pos_fallback: int) -> int:
        s = str(idx)
        if "a:" in s:
            try:
                return max(0, int(s.split(":")[-1]))
            except Exception:
                return int(pos_fallback)
        return int(pos_fallback)

    def _probe_audio_bitrate_label(self, path: str, a_idx: int) -> str | None:
        ffprobe = shutil.which("ffprobe") or "ffprobe"
        try:
            cmd = [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                f"a:{int(a_idx)}",
                "-show_entries",
                "stream=bit_rate:stream_tags=BPS,BPS-eng",
                "-of",
                "json",
                str(path),
            ]
            p = subprocess.run(cmd, capture_output=True, text=True, check=True)
            data = json.loads(p.stdout or "{}")
            ss = data.get("streams") or []
            if not ss:
                return None
            st = ss[0]
            br = st.get("bit_rate")
            if (not br or br == "N/A") and "tags" in st:
                br = st["tags"].get("BPS") or st["tags"].get("BPS-eng")
            if not br or br == "N/A":
                return None
            bps = int(str(br))
            if bps <= 0:
                return None
            kbps = max(1, round(bps / 1000))
            return f"{kbps}k"
        except Exception:
            return None

    @pyqtSlot(bool)
    def _on_force_mute_toggled(self, checked: bool):
        """
        Switch tra modalità 'muto/esterno' e 'interna'.
        Aggiorna anche Batch.file così flush() si comporta correttamente.
        """
        if checked:
            # → Modalità audio esterno
            self.audio_externo = True
            self.external_audio_file = None
            # Batch: nessun video di riferimento (attiva path "esterno")
            try:
                self.batch.set_video_file(None)
            except Exception:
                pass
            try:
                self.path.setText("Trattato come muto: in attesa di audio esterno…")
            except Exception:
                pass
            self.cmb_track.clear()
            self.cmb_track.addItem("File muto → carica audio esterno…", (-1, None, None))
            self.cmb_track.setEnabled(False)
            self.btn_load_external_audio.show()
            self.btn_add.setEnabled(False)
        else:
            # → Torna a modalità interna (usa il file video caricato)
            self.audio_externo = False
            self.external_audio_file = None
            # Batch: ripristina il video se noto (disattiva path "esterno")
            try:
                self.batch.set_video_file(str(self.file) if self.file else None)
            except Exception:
                pass
            self.btn_load_external_audio.hide()
            if self.file:
                self.load_file(str(self.file))
            else:
                self.cmb_track.clear()
                self.cmb_track.addItem("Seleziona traccia…", (-1, None, None))
                self.cmb_track.setEnabled(False)
            self.btn_add.setEnabled(False)

        # Aggiorna label e abilitazioni correlate
        try:
            self._refresh_filter_availability()
            self._update_pan_preset_label()
        except Exception:
            pass

    @pyqtSlot(int)
    def _on_track_changed(self, combo_idx: int):
        """
        Cambio traccia:
          - NIENTE dialog lingua: usiamo self.cmb_lang
          - Aggiorna etichetta/itemData con la lingua corrente
          - Abilita 'Agg. traccia'
          - Defer dei refresh pesanti
        """
        data = self.cmb_track.itemData(combo_idx)
        if not data:
            self.btn_add.setEnabled(False)
            return
        idx, _lang_old, br = data
        if idx is None or idx < 0:
            self.btn_add.setEnabled(False)
            return

        lang = self._lang_code_from_combo()
        label = self._fmt_track_label(idx, lang, br)
        self.cmb_track.setItemText(combo_idx, label)
        self.cmb_track.setItemData(combo_idx, (idx, lang, br))
        self.btn_add.setEnabled(True)
        QTimer.singleShot(0, self._after_track_change_refresh_safe)

    def _after_track_change_refresh_safe(self):
        try:
            self._refresh_filter_availability()
        except Exception:
            pass
        for maybe in (
            "_update_example_preview_cmd",
            "update_ffmpeg_preview",
            "_update_ffmpeg_textarea",
            "_refresh_preview_and_cmd",
            "on_audio_params_changed",
        ):
            fn = getattr(self, maybe, None)
            if callable(fn):
                try:
                    fn()
                except Exception:
                    pass
                break

    @pyqtSlot(str)
    def _update_track_title(self, new_br: str):
        combo_idx = self.cmb_track.currentIndex()
        data = self.cmb_track.itemData(combo_idx)
        if not data:
            return
        idx, lang, _ = data
        if idx < 0:
            return
        br = new_br if new_br != "Nessuno" else self._orig_bitrates.get(idx, "Nessuno")
        label = self._fmt_track_label(idx, lang, br)
        self.cmb_track.setItemText(combo_idx, label)
        self.cmb_track.setItemData(combo_idx, (idx, lang, new_br))
        QTimer.singleShot(0, getattr(self, "_after_track_change_refresh_safe", lambda: None))

    @pyqtSlot()
    def make_preview(self):
        import traceback

        try:
            print("[UI] make_preview() chiamata → run_preview(self)", flush=True)
            run_preview(self)
            print("[UI] make_preview() OK (run_preview ha terminato)", flush=True)
        except Exception as e:
            print("[UI][ERRORE] make_preview():", e, flush=True)
            print(traceback.format_exc(), flush=True)

    def _effective_output_is_stereo(self, in_ch: int) -> bool:
        """
        Ritorna True se l'OUTPUT effettivo sarà stereo.
        Regole:
          - MONO + 'Mantieni MONO' spuntato  → False (resta 1.0)
          - MONO + (non mantieni)            → True (facciamo pseudo-stereo)
          - Sorgente stereo                  → True
          - Multicanale                      → True solo se downmix forzato/Samsung stereo
        """
        try:
            keep_mono = bool(getattr(self, "chk_keep_mono", None) and self.chk_keep_mono.isChecked())
        except Exception:
            keep_mono = False

        force_st = bool(getattr(self, "chk_force_stereo", None) and self.chk_force_stereo.isChecked())
        prof = getattr(self, "_soundbar_profile", "none")
        is_samsung_stereo = prof == getattr(C, "PROFILE_SAMSUNG_STEREO_KEY", "samsung_stereo")

        if in_ch <= 0:
            in_ch = 2

        if in_ch == 1:
            # Se mantieni mono → output mono; altrimenti pseudo-stereo o downmix forzato
            return (not keep_mono) or force_st or is_samsung_stereo
        elif in_ch == 2:
            return True
        else:
            # >2 canali: serve un downmix esplicito
            return force_st or is_samsung_stereo

    def _current_detected_channels(self) -> int:
        try:
            from hevc_gui.core.ffprobe_utils import probe_audio_stream

            data = self.cmb_track.currentData() or (-1, None, None)
            idx = data[0] if isinstance(data, (tuple, list)) and data else -1
            if idx < 0:
                return 2
            if bool(getattr(self, "audio_externo", False)):
                info = probe_audio_stream(self.external_audio_file, stream_index=0) or {}
            else:
                sidx = int(str(idx).split(":")[-1])
                info = probe_audio_stream(str(self.file), stream_index=sidx) or {}
            ch = int(info.get("channels") or 0)
            return ch if ch > 0 else 2
        except Exception:
            return 2

    def _refresh_filter_availability(self, *_):
        """
        Abilitazioni/disabilitazioni dinamiche in base a canali, profili e 'Mantieni MONO'.
        Novità: con input MONO le checkbox restano abilitate, a meno che 'Mantieni MONO' sia spuntato.
        """
        try:
            in_ch = self._current_detected_channels()
        except Exception:
            in_ch = 2

        # Stato widget
        sb_st = getattr(self, "chk_sb_stereo", None)
        sb_51 = getattr(self, "chk_sb_51", None)
        force_st = getattr(self, "chk_force_stereo", None)
        keep_mono = bool(getattr(self, "chk_keep_mono", None) and self.chk_keep_mono.isChecked())

        # 1) Gestione MONO + Mantieni MONO
        if in_ch == 1 and keep_mono:
            # Monocanale “puro”: spegni e blocca i profili stereo/downmix
            for w in (sb_st, sb_51, force_st):
                if w is not None:
                    try:
                        w.blockSignals(True)
                        w.setChecked(False)
                        w.setEnabled(False)
                        w.blockSignals(False)
                    except Exception:
                        pass
            try:
                self._soundbar_profile = "none"
            except Exception:
                pass
        else:
            # Tutto il resto: lascia scegliere liberamente
            for w in (sb_st, sb_51, force_st):
                if w is not None:
                    try:
                        w.setEnabled(True)
                    except Exception:
                        pass

        # 2) Stereo Enh attivo solo se l'output effettivo è stereo
        try:
            stereo_out = self._effective_output_is_stereo(in_ch)
        except Exception:
            stereo_out = in_ch >= 2 and not keep_mono

        if getattr(self, "cmb_stereo", None):
            try:
                self.cmb_stereo.setEnabled(bool(stereo_out))
                tip = "Attivo solo quando l’uscita è stereo." if not stereo_out else "Enhancer stereo."
                self.cmb_stereo.setToolTip(tip)
            except Exception:
                pass

        # 3) Aggiorna label “Pan preset”
        try:
            if getattr(self, "lbl_pan_preset", None):
                prof = getattr(self, "_soundbar_profile", "none")
                if in_ch == 1 and keep_mono:
                    self.lbl_pan_preset.setText("Pan preset: — (input MONO mantenuto)")
                elif in_ch > 2 and stereo_out:
                    preset = "Samsung R450" if prof == getattr(C, "PROFILE_SAMSUNG_STEREO_KEY", "samsung_stereo") else "TV generico"
                    self.lbl_pan_preset.setText(f"Pan preset: {preset} (downmix 5.1→2.0)")
                else:
                    self.lbl_pan_preset.setText("Pan preset: — (nessun downmix)")
        except Exception:
            pass

        # 4) Chiudi aggiornando lo stato sintetico
        self._update_pan_preset_label()

    def _active_pan_preset_key(self) -> str | None:
        prof = getattr(self, "_soundbar_profile", "none")
        if prof == "samsung_stereo":
            return "samsung"
        try:
            in_ch = self._current_input_channels_hint()
        except Exception:
            in_ch = 2
        if in_ch > 2 and bool(getattr(self, "chk_force_stereo", None) and self.chk_force_stereo.isChecked()):
            return "generic"
        return None

    def _build_forced_pan_if_needed(self, nch: int) -> str | None:
        key = getattr(self, "_active_pan_preset_key", lambda: None)()
        if nch == 2 and key == "samsung":
            return "pan=stereo|c0=0.92*c0+0.08*c1|c1=0.92*c1+0.08*c0"
        return None

    def _update_pan_placeholder(self, nch: int, forced: bool = False) -> None:
        lbl = getattr(self, "lbl_pan_preset", None)
        if lbl is None:
            for w in self.findChildren(QLabel):
                try:
                    t = (w.text() or "").lower()
                    if "pan preset" in t:
                        lbl = w
                        break
                except Exception:
                    pass
        if lbl is None:
            return
        key = getattr(self, "_active_pan_preset_key", lambda: None)()
        if forced:
            lbl.setText("Pan preset: Samsung (crossfeed)")
            lbl.setStyleSheet("color: #e11d48;")
            return
        if nch > 2 and key:
            lbl.setText("Pan preset: downmix attivo")
            lbl.setStyleSheet("color: #10b981;")
        else:
            lbl.setText("Pan preset: — (nessun downmix)")
            lbl.setStyleSheet("")

    def _current_input_channels_hint(self) -> int:
        try:
            data = self.cmb_track.currentData()
            if not isinstance(data, (tuple, list)) or not data:
                return 2
            a_idx = int(str(data[0]).split(":")[-1])
            if self.audio_externo and self.external_audio_file:
                src = self.external_audio_file
                sidx = 0
            else:
                src = str(self.file) if self.file else None
                sidx = a_idx
            if not src:
                return 2
            from hevc_gui.core.ffprobe_utils import probe_audio_stream

            info = probe_audio_stream(src, stream_index=sidx) or {}
            return int(info.get("channels") or 2)
        except Exception:
            return 2

    @pyqtSlot()
    def _update_pan_preset_label(self) -> None:
        # Trova la label
        lbl = getattr(self, "lbl_pan_preset", None)
        if lbl is None:
            return

        # Stato d’ingresso e scelte utente
        try:
            in_ch = self._current_input_channels_hint()
        except Exception:
            in_ch = 2

        keep_mono  = bool(getattr(self, "chk_keep_mono", None) and self.chk_keep_mono.isChecked())
        downmix_on = bool(getattr(self, "chk_force_stereo", None) and self.chk_force_stereo.isChecked())

        prof = getattr(self, "_soundbar_profile", "none")
        # chiave configurabile in constants.py; fallback "samsung_stereo"
        from hevc_gui.core import constants as C
        samsung_stereo = (prof == getattr(C, "PROFILE_SAMSUNG_STEREO_KEY", "samsung_stereo"))
        samsung_51     = (prof == "samsung_5_1_ac3")

        try:
            eff_stereo = bool(self._effective_output_is_stereo(in_ch))
        except Exception:
            eff_stereo = (in_ch >= 2 and not keep_mono)

        # 1) MONO mantenuto → niente pan/pseudo-stereo
        if in_ch == 1 and keep_mono:
            lbl.setText("Pan preset: — (input MONO mantenuto: nessun pan/pseudo-stereo)")
            lbl.setStyleSheet("")
            return

        # 2) Multicanale + downmix forzato → pan 5.1→2.0 (Samsung o TV)
        if in_ch > 2 and downmix_on:
            which = "Samsung R450" if samsung_stereo else "TV generico"
            cause = "forzato da “Stereo (downmix 2ch)”"
            lbl.setText(f"Pan preset: {which} (downmix 5.1→2.0, {cause})")
            lbl.setStyleSheet("color: #10b981;")  # verde “attivo”
            return

        # 3) Uscita stereo + profilo Samsung stereo → crossfeed (anche da MONO→pseudo-stereo)
        if eff_stereo and samsung_stereo:
            src = "input MONO → pseudo-stereo" if (in_ch == 1 and not keep_mono) else "uscita stereo"
            lbl.setText(f"Pan preset: Samsung (crossfeed, {src}, profilo attivo)")
            lbl.setStyleSheet("color: #e11d48;")  # accento
            return

        # 4) Profilo Samsung 5.1 → uscita 5.1 (nessun pan 2.0)
        if samsung_51:
            lbl.setText("Pan preset: — (Uscita 5.1; profilo Samsung 5.1 attivo)")
            lbl.setStyleSheet("color: #2563eb;")  # blu
            return

        # 5) Default: nessun downmix/crossfeed attivo → specifica il “perché”
        if in_ch > 2:
            extra = "input multicanale mantenuto (nessun downmix)"
        elif in_ch == 2:
            extra = "stereo nativo (nessun crossfeed/preset)"
        else:
            # in_ch == 1 e non keep_mono: pseudo-stereo MA senza profilo Samsung → nessun crossfeed
            extra = "mono → pseudo-stereo senza crossfeed"
        lbl.setText(f"Pan preset: — ({extra})")
        lbl.setStyleSheet("")

    def _connect_pan_preset_signals(self):
        try:
            if getattr(self, "chk_force_stereo", None):
                self.chk_force_stereo.toggled.connect(self._update_pan_preset_label)
        except Exception:
            pass
        try:
            if getattr(self, "chk_sb_stereo", None):
                self.chk_sb_stereo.toggled.connect(self._update_pan_preset_label)
            if getattr(self, "chk_sb_51", None):
                self.chk_sb_51.toggled.connect(self._update_pan_preset_label)
        except Exception:
            pass
        try:
            self.cmb_track.currentIndexChanged.connect(lambda _=None: self._update_pan_preset_label())
            self.cmb_stereo.currentTextChanged.connect(lambda _=None: self._update_pan_preset_label())
        except Exception:
            pass

    def _build_filters_chain_from_ui(self, *, for_preview: bool, channels_hint: int) -> list[str]:
        from hevc_gui.core import constants as C

        filters: list[str] = []
        post_dyn_makeup_db = 0.0

        def _has_pan(fs: list[str]) -> bool:
            j = ",".join(fs).lower()
            return ("pan=stereo" in j) or ("pan=2c" in j)

        def _compact_volume(filters: list[str]) -> list[str]:
            out, pending = [], 0.0
            for f in filters:
                if f.startswith("volume=") and f.endswith("dB"):
                    try:
                        pending += float(f[len("volume=") : -2])
                        continue
                    except Exception:
                        pass
                if pending:
                    out.append(f"volume={pending}dB")
                    pending = 0.0
                out.append(f)
            if pending:
                out.append(f"volume={pending}dB")
            return out

        prof = getattr(self, "_soundbar_profile", "none")
        is_samsung_stereo = prof == getattr(C, "PROFILE_SAMSUNG_STEREO_KEY", "samsung_stereo")
        dyn_on = bool(getattr(self, "chk_dyn", None) and self.chk_dyn.isChecked())

        use_loudnorm2 = False
        try:
            if getattr(self, "cmb_norm", None):
                try:
                    from hevc_gui.core.loudness import NORM_LOUDNORM2

                    use_loudnorm2 = self.cmb_norm.currentText() == NORM_LOUDNORM2
                except Exception:
                    txt = (self.cmb_norm.currentText() or "").lower()
                    use_loudnorm2 = "loudnorm" in txt and "2" in txt
            elif getattr(self, "chk_loudnorm2", None):
                use_loudnorm2 = bool(self.chk_loudnorm2.isChecked())
            else:
                use_loudnorm2 = bool(getattr(self, "_force_loudnorm2", False))
        except Exception:
            use_loudnorm2 = bool(getattr(self, "_force_loudnorm2", False))

        keep_mono = bool(getattr(self, "chk_keep_mono", None) and self.chk_keep_mono.isChecked())
        pseudo_applied = False
        if channels_hint == 1 and not keep_mono:
            filters.append(
                "asplit=2[a][b];[b]adelay=12:all=1,equalizer=f=3000:t=q:w=1.2:g=-1.5[br];[a][br]join=inputs=2:channel_layout=stereo"
            )
            pseudo_applied = True

        gain_deferred = None
        try:
            gtxt = (self.cmb_gain.currentText() or "").strip()
            if gtxt and gtxt not in ("0", "0dB", "Nessuno"):
                g = float(gtxt[:-2]) if gtxt.lower().endswith("db") else float(gtxt)
                if abs(g) > 0.0001:
                    if dyn_on:
                        gain_deferred = f"volume={g}dB"
                    else:
                        filters.append(f"volume={g}dB")
        except Exception:
            pass

        try:
            if getattr(self, "chk_nr", None) and self.chk_nr.isChecked():
                nr_txt = (self.in_nr.text() or "").strip()
                if nr_txt:
                    val = float(nr_txt.replace(",", "."))
                    if 1 <= val <= 30:
                        filters.append(f"afftdn=nf=-{val:.1f}")
        except Exception:
            pass

        def _eq_piece(cmb, freq: int):
            try:
                txt = (cmb.currentText() or "").strip().replace(",", ".")
                if not txt or txt.lower() == "nessuno":
                    return
                v = float(txt)
                if abs(v) > 0.0001:
                    filters.append(f"equalizer=f={freq}:t=q:w=1:g={v}")
            except Exception:
                pass

        _eq_piece(self.cmb_eq_bass, 60)
        _eq_piece(self.cmb_eq_mid, 1000)
        _eq_piece(self.cmb_eq_treb, 3000)

        force_st = bool(getattr(self, "chk_force_stereo", None) and self.chk_force_stereo.isChecked())
        need_downmix = bool(force_st and (channels_hint and channels_hint > 2) and not _has_pan(filters))
        if need_downmix:
            pan = C.AUD_PAN_PRESETS.get("stereo_samsung_r450" if is_samsung_stereo else "stereo_tv_generic")
            if pan:
                filters.append(pan)

        if is_samsung_stereo and (channels_hint == 2) and (not _has_pan(filters)) and (not pseudo_applied):
            filters.append("pan=stereo|c0=0.92*c0+0.08*c1|c1=0.92*c1+0.08*c0")
            if not use_loudnorm2:
                if dyn_on:
                    post_dyn_makeup_db += 2.0
                else:
                    filters.append("volume=2dB")

        try:
            if getattr(self, "chk_dialog_boost", None) and self.chk_dialog_boost.isChecked():
                stereo_out = self._effective_output_is_stereo(channels_hint)
                if (not stereo_out) and (channels_hint and channels_hint >= 6):
                    filters.append("pan=5.1(side)|FL=c0+0.06*c2|FR=c1+0.06*c2|FC=1.5*c2|LFE=c3|SL=c4|SR=c5")
                else:
                    filters.append("equalizer=f=2000:t=q:w=1.2:g=2")
        except Exception:
            pass

        try:
            enh = (self.cmb_stereo.currentText() or "").strip()
            if enh and enh.lower() != "nessuno":
                enh_map = getattr(C, "AUD_STEREO_ENHANCERS", None) or {}
                f = enh_map.get(enh)
                if f:
                    is_now_stereo = pseudo_applied or need_downmix or (channels_hint == 2)
                    if is_now_stereo:
                        filters.append(f)
        except Exception:
            pass

        try:
            rev_key = (self.cmb_rev.currentText() or "").strip()
        except Exception:
            rev_key = ""
        if rev_key and rev_key.lower() != "nessuno":
            try:
                rev = getattr(C, "AUD_REVERB_MAP", {}).get(rev_key)
            except Exception:
                rev = None
            if rev:
                filters.append(rev)

        if dyn_on:
            filters.append("dynaudnorm=f=250:g=31:p=0.95:m=50")
            if gain_deferred:
                filters.append(gain_deferred)
            if post_dyn_makeup_db:
                filters.append(f"volume={post_dyn_makeup_db}dB")

        comp_str = None
        try:
            comp_sel = (self.cmb_comp_soft.currentText() or "").strip().lower()
        except Exception:
            comp_sel = "nessuno"
        if comp_sel in ("leggero", "medio", "forte"):
            if comp_sel == "leggero":
                P = dict(threshold="-12dB", ratio=2.5, attack=12, release=220, knee=6, detection="rms", link="average", makeup=4)
            elif comp_sel == "medio":
                P = dict(threshold="-18dB", ratio=3.0, attack=10, release=280, knee=6, detection="rms", link="average", makeup=5)
            else:
                P = dict(threshold="-22dB", ratio=4.0, attack=8, release=350, knee=8, detection="rms", link="average", makeup=6)
            if dyn_on:
                P["makeup"] = 1
            P["knee"] = max(1, min(8, int(P["knee"])))
            P["makeup"] = max(1, min(64, int(P["makeup"])))
            P["attack"] = max(1, int(P["attack"]))
            P["release"] = max(20, int(P["release"]))
            comp_str = (
                "acompressor="
                f"threshold={P['threshold']}:ratio={P['ratio']}:attack={P['attack']}:release={P['release']}:"
                f"knee={P['knee']}:link={P['link']}:detection={P['detection']}:makeup={P['makeup']}"
            )
            filters.append(comp_str)

        limiter_str = None
        try:
            if getattr(self, "chk_anticlip", None) and self.chk_anticlip.isChecked():
                limiter_str = "alimiter=limit=0.965:attack=12:release=300"
        except Exception:
            pass
        if limiter_str:
            if (comp_str is None) and (not dyn_on):
                filters.append("volume=3dB")
            filters.append(limiter_str)

        filters = _compact_volume(filters)
        return filters

    def _fmt_audio_title_from_flags(self, *, lang: str, codec: str, ac: int, ar: int | None, br: str | None) -> str:
        lang_full = self._lang_human(lang)
        codec_lbl = {"aac": "AAC", "libfdk_aac": "AAC", "ac3": "AC-3", "eac3": "E-AC-3"}.get(str(codec).lower(), str(codec).upper())
        ch_lbl = {1: "1.0", 2: "2.0", 6: "5.1"}.get(int(ac), f"{ac}ch")
        sr_lbl = (
            f"{int(ar) // 1000 * 1} kHz"
            if ar
            else (
                f"{int(self.cmb_sr.currentText()) // 1000 * 1} kHz"
                if getattr(self, "cmb_sr", None) and self.cmb_sr.currentText().isdigit()
                else None
            )
        )
        br_lbl = None
        if br:
            try:
                v = int(str(br).lower().replace("k", "").replace("kb/s", "").replace("kbps", "").replace("kbit/s", ""))
                br_lbl = f"{v} kb/s"
            except Exception:
                br_lbl = str(br)
        parts = [lang_full, f"{codec_lbl} {ch_lbl}"]
        if sr_lbl:
            parts.append(sr_lbl)
        if br_lbl:
            parts.append(br_lbl)
        return " • ".join(parts)

    @pyqtSlot()
    def add_seg(self):
        """
        Aggiunge **una** traccia audio alla batch.
        Lingua presa SOLO da self.cmb_lang (niente dialoghi).
        """
        is_ext = bool(self.audio_externo)
        lang = self._lang_code_from_combo() or "und"

        if is_ext:
            if not self.external_audio_file:
                QMessageBox.warning(self, "Audio esterno", "Nessun file audio esterno caricato.")
                return
            src_path = str(self.external_audio_file)
            sidx = 0
            map_str = "0:a:0"
            idx_for_orig = 0
        else:
            data = self.cmb_track.currentData()
            if not isinstance(data, (tuple, list)) or len(data) < 3:
                QMessageBox.warning(self, "Audio", "Seleziona una traccia valida.")
                return
            idx, _old_lang, br = data
            if idx < 0:
                QMessageBox.warning(self, "Audio", "Seleziona una traccia valida.")
                return
            cur_txt = self._fmt_track_label(idx, lang, br)
            self.cmb_track.setItemText(self.cmb_track.currentIndex(), cur_txt)
            self.cmb_track.setItemData(self.cmb_track.currentIndex(), (idx, lang, br))

            src_path = str(self.file)
            sidx = int(str(idx).split(":")[-1])
            map_str = f"0:a:{sidx}"
            idx_for_orig = idx

        detected_ch = 2
        try:
            from hevc_gui.core.ffprobe_utils import probe_audio_stream

            info = probe_audio_stream(src_path, stream_index=sidx) or {}
            detected_ch = int(info.get("channels") or 2)
        except Exception:
            pass

        keep_mono = bool(getattr(self, "chk_keep_mono", None) and self.chk_keep_mono.isChecked())
        if detected_ch == 1 and not keep_mono:
            try:
                self._soundbar_profile = "none"
            except Exception:
                pass

        prof = getattr(self, "_soundbar_profile", "none")
        force_stereo = bool(getattr(self, "chk_force_stereo", None) and self.chk_force_stereo.isChecked())
        wants_51 = (prof == "samsung_5_1_ac3") and (not force_stereo)

        filters = self._build_filters_chain_from_ui(for_preview=False, channels_hint=detected_ch)

        try:
            from hevc_gui.core.loudness import NORM_LOUDNORM2
        except Exception:
            NORM_LOUDNORM2 = None
        try:
            if NORM_LOUDNORM2 is not None and getattr(self, "cmb_norm", None) and self.cmb_norm.currentText() == NORM_LOUDNORM2:
                try:
                    from hevc_gui.core.loudness import measure_loudnorm_smart, build_second_pass_filter_from_json

                    stats = measure_loudnorm_smart(src_path, a_stream_idx=sidx, t=120)
                    if stats:
                        filters += build_second_pass_filter_from_json(stats, anticlipping=False)
                except Exception:
                    from hevc_gui.core.loudness import DEFAULT_I, DEFAULT_TP, DEFAULT_LRA

                    filters.append(f"loudnorm=I={DEFAULT_I}:TP={DEFAULT_TP}:LRA={DEFAULT_LRA}")
        except Exception:
            pass

        af_chain = ",".join(filters) if filters else None

        def _parse_kbps(s: str | None) -> int | None:
            if not s:
                return None
            digs = "".join(ch for ch in str(s).lower() if ch.isdigit())
            return int(digs) if digs else None

        user_br_txt = None
        try:
            if getattr(self, "cmb_br", None):
                ct = (self.cmb_br.currentText() or "").strip()
                if ct and ct.lower() != "nessuno":
                    user_br_txt = ct
        except Exception:
            pass

        orig_br_txt = None
        try:
            if is_ext:
                orig_br_txt = self._probe_audio_bitrate_label(src_path, 0)
            else:
                orig_br_txt = self._orig_bitrates.get(idx_for_orig) or self._probe_audio_bitrate_label(str(self.file), sidx)
        except Exception:
            orig_br_txt = None
        orig_kbps = _parse_kbps(orig_br_txt)

        sr_sel = self.cmb_sr.currentText() if getattr(self, "cmb_sr", None) else "Nessuno"
        ar = int(sr_sel) if (sr_sel and sr_sel != "Nessuno" and sr_sel.isdigit()) else None

        if wants_51:
            codec, ac = "ac3", 6
            if not ar:
                ar = 48000
            br_eff = user_br_txt or "448k"
        else:
            if detected_ch == 1 and keep_mono:
                codec, ac = "aac", 1
                br_eff = user_br_txt or "96k"
            else:
                codec, ac = "aac", 2
                if user_br_txt:
                    br_eff = user_br_txt
                else:
                    if orig_kbps is None or orig_kbps < 128:
                        br_eff = "128k"
                    else:
                        br_eff = f"{orig_kbps}k"

        try:
            title = self._fmt_audio_title_from_flags(lang=lang, codec=codec, ac=ac, ar=ar, br=br_eff)
        except Exception:
            parts = [self._lang_human(lang)]
            parts.append("AC-3 5.1" if (codec == "ac3" and ac == 6) else f"AAC {ac}ch")
            if ar:
                parts.append(f"{ar // 1000} kHz")
            if br_eff:
                parts.append(str(br_eff))
            title = " • ".join(parts)

        tag = len(self.batch.items)
        seg: list[str] = ["-i", src_path, "-map", map_str, "-vn"]
        if af_chain:
            seg += ["-af", af_chain]
        seg += [f"-c:a:{tag}", codec, f"-ac:{tag}", str(ac)]
        if ar:
            seg += [f"-ar:{tag}", str(ar)]
        if br_eff:
            seg += [f"-b:a:{tag}", str(br_eff)]
        seg += [f"-metadata:s:a:{tag}", f"language={lang}", f"-metadata:s:a:{tag}", f"title={title}"]

        self.batch.add(seg)  # <— INSERISCE DAVVERO
        badge = "  [🔊 5.1]" if (codec == "ac3" and ac == 6) else ""
        self.list.addItem(" ".join(shlex.quote(a) for a in seg) + badge)

        if not is_ext:
            self.btn_add.setEnabled(False)

    def current_opts(self) -> list[str]:
        """
        Bozza opzioni audio coerente con GUI (DEMO).
        Niente demo per audio esterno o se manca il file.
        """
        if self.audio_externo or not self.file:
            return []
        data = self.cmb_track.currentData()
        if not isinstance(data, (tuple, list)) or len(data) < 3:
            return []
        idx, lang, br = data
        if idx < 0 or lang is None:
            return []

        detected_ch = 2
        sidx = int(str(idx).split(":")[-1])
        try:
            from hevc_gui.core.ffprobe_utils import probe_audio_stream

            info = probe_audio_stream(str(self.file), stream_index=sidx) or {}
            detected_ch = int(info.get("channels") or 2)
        except Exception:
            pass

        filters = self._build_filters_chain_from_ui(for_preview=False, channels_hint=detected_ch)
        af_chain = ",".join(filters) if filters else None

        prof = getattr(self, "_soundbar_profile", "none")
        force_stereo = bool(getattr(self, "chk_force_stereo", None) and self.chk_force_stereo.isChecked())
        keep_mono = bool(getattr(self, "chk_keep_mono", None) and self.chk_keep_mono.isChecked())
        wants_51 = (prof == "samsung_5_1_ac3") and (not force_stereo)

        sr = self.cmb_sr.currentText() if getattr(self, "cmb_sr", None) else "Nessuno"
        ar = int(sr) if (sr and sr.isdigit()) else None

        def _parse_kbps(s: str | None) -> int | None:
            if not s:
                return None
            digs = "".join(ch for ch in str(s).lower() if ch.isdigit())
            return int(digs) if digs else None

        user_br_txt = None
        try:
            ct = (self.cmb_br.currentText() or "").strip()
            if ct and ct.lower() != "nessuno":
                user_br_txt = ct
        except Exception:
            pass

        orig_br_txt = self._orig_bitrates.get(idx, None)
        if not orig_br_txt:
            try:
                orig_br_txt = self._probe_audio_bitrate_label(str(self.file), sidx)
            except Exception:
                orig_br_txt = None
        orig_kbps = _parse_kbps(orig_br_txt)

        if wants_51:
            codec, ac = "ac3", 6
            if not ar:
                ar = 48000
            br_eff = user_br_txt or "448k"
        else:
            if detected_ch == 1 and keep_mono:
                codec, ac = "aac", 1
                br_eff = user_br_txt or "96k"
            else:
                codec, ac = "aac", 2
                if user_br_txt:
                    br_eff = user_br_txt
                else:
                    br_eff = "128k" if (orig_kbps is None or orig_kbps < 128) else f"{orig_kbps}k"

        try:
            title = self._fmt_audio_title_from_flags(lang=lang, codec=codec, ac=ac, ar=ar, br=br_eff)
        except Exception:
            parts = [self._lang_human(lang)]
            parts.append("AC-3 5.1" if (codec == "ac3" and ac == 6) else f"AAC {ac}ch")
            if ar:
                parts.append(f"{ar // 1000} kHz")
            if br_eff:
                parts.append(str(br_eff))
            title = " • ".join(parts)

        tag = len(self.batch.items)
        seg: list[str] = ["-map", f"0:a:{idx}", f"-metadata:s:a:{tag}", f"title={title}", f"-c:a:{tag}", codec, f"-ac:{tag}", str(ac)]
        if br_eff:
            seg += [f"-b:a:{tag}", str(br_eff)]
        if ar:
            seg += [f"-ar:{tag}", str(ar)]
        if af_chain:
            seg += ["-af", af_chain]
        return seg

    @pyqtSlot()
    def finish(self):
        """
        Chiude il dialog restituendo il batch dei comandi.
        Se interna e vuota, chiede conferma UNA sola volta.
        """
        if self.audio_externo:
            if not self.external_audio_file:
                QMessageBox.warning(self, "Errore", "Nessuna traccia esterna caricata.")
                return
            if not self.batch.items:
                seg = ["-i", self.external_audio_file, "-map", "0:a", "-c:a", "copy"]
                lang = self._lang_code_from_combo() or "und"
                seg += ["-metadata:s:a:0", f"language={lang}"]
                self.batch.add(seg)
            for i, seg in enumerate(self.batch.items):
                if seg[0] != "-i":
                    self.batch.items[i] = ["-i", str(self.external_audio_file)] + seg
            self._closing_via_finish = True
            self.batch.flush()
            self.accept()
            return

        if not self.batch.items:
            self._closing_via_finish = True
            reply = QMessageBox.question(
                self,
                "Nessuna traccia",
                "Non hai aggiunto tracce audio.\nChiudere comunque?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                self._closing_via_finish = False
                return

        for i, seg in enumerate(self.batch.items):
            if seg[0] != "-i":
                self.batch.items[i] = ["-i", str(self.file)] + seg

        self._closing_via_finish = True
        self.batch.flush()
        self.accept()

    def _build_audio_filters(self) -> list[str]:
        """Compat: delega alla chain ufficiale, senza fallback."""
        detected_ch = 2
        try:
            data = self.cmb_track.currentData()
            if isinstance(data, (tuple, list)) and len(data) >= 1 and data[0] >= 0:
                sidx = int(str(data[0]).split(":")[-1])
                from hevc_gui.core.ffprobe_utils import probe_audio_stream

                info = probe_audio_stream(str(self.file), stream_index=sidx) or {}
                detected_ch = int(info.get("channels") or 2)
        except Exception:
            pass
        return self._build_filters_chain_from_ui(for_preview=False, channels_hint=detected_ch)

    def _on_conversion_finished(self):
        self.progress_bar.hide()
        QMessageBox.information(self, "Conversione completata", "File audio convertito con successo.")
        self.accept()

    def _on_conversion_error(self, msg):
        self.progress_bar.hide()
        QMessageBox.critical(self, "Errore conversione", msg)

    def closeEvent(self, event):
        if self._closing_via_finish:
            event.accept()
            return
        reply = QMessageBox.question(
            self,
            "Uscire?",
            "Vuoi uscire dall'app?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            if self.batch.items:
                self.batch.flush()
            else:
                print("[]", file=sys.stderr)
            event.accept()
        else:
            event.ignore()

    def _reset_defaults(self):
        """
        Ripristina i controlli ai default, deseleziona 'Tratta come muto',
        ripopola la combo tracce dal file corrente e pulisce la lista/batch.
        """
        if getattr(self, "chk_force_mute", None):
            self.chk_force_mute.setChecked(False)
        self.audio_externo = False

        self.cmb_track.clear()
        self.cmb_track.addItem("Seleziona traccia…", (-1, None, None))
        if self.file:
            try:
                tracks = list(audio_tracks_with_title(str(self.file)))
            except Exception:
                tracks = []
            if tracks:
                self._orig_bitrates.clear()
                self._orig_channels.clear()
                cur_lang = self._lang_code_from_combo()
                for pos, (idx_raw, title) in enumerate(tracks):
                    a_idx = self._norm_audio_index(idx_raw, pos)
                    br_lbl = self._probe_audio_bitrate_label(str(self.file), a_idx)
                    if br_lbl:
                        self._orig_bitrates[a_idx] = br_lbl
                    ch = self._probe_audio_channels(str(self.file), a_idx)
                    if ch:
                        self._orig_channels[a_idx] = ch
                    label = self._fmt_track_label(a_idx, cur_lang, br_lbl or "Nessuno")
                    if title:
                        label += f" – {title}"
                    self.cmb_track.addItem(label, (a_idx, cur_lang, br_lbl or "Nessuno"))
                self.cmb_track.setEnabled(True)
            else:
                self.cmb_track.setEnabled(False)
            try:
                self.path.setText(str(self.file))
            except Exception:
                pass
        else:
            self.cmb_track.setEnabled(False)

        try:
            self.batch.items.clear()
        except Exception:
            pass
        try:
            self.list.clear()
        except Exception:
            pass

        for safe in (
            lambda: self.cmb_br.setCurrentText("Nessuno"),
            lambda: self.cmb_sr.setCurrentText("Nessuno"),
            lambda: self.cmb_gain.setCurrentText("0"),
            lambda: self.chk_nr.setChecked(False),
            lambda: (self.in_nr.clear(), self.in_nr.setEnabled(False), self.in_nr.setStyleSheet("")),
            lambda: self.cmb_eq_bass.setCurrentText("0"),
            lambda: self.cmb_eq_mid.setCurrentText("0"),
            lambda: self.cmb_eq_treb.setCurrentText("0"),
            lambda: self.cmb_rev.setCurrentIndex(0),
            lambda: (
                self.cmb_stereo.setCurrentText("Nessuno")
                if self.cmb_stereo.findText("Nessuno") >= 0
                else self.cmb_stereo.setCurrentIndex(0)
            ),
            lambda: (
                self.cmb_comp_soft.setCurrentText("Nessuno")
                if self.cmb_comp_soft.findText("Nessuno") >= 0
                else self.cmb_comp_soft.setCurrentIndex(0)
            ),
            lambda: self.chk_dialog_boost.setChecked(False),
            lambda: self.chk_keep_mono.setChecked(False),
            lambda: self.chk_anticlip.setChecked(False),
            lambda: self.cmb_prev.setCurrentIndex(0),
            lambda: self.chk_force_stereo.setChecked(False),
        ):
            try:
                safe()
            except Exception:
                pass

        try:
            if hasattr(self, "chk_sb_stereo"):
                self.chk_sb_stereo.setChecked(False)
            if hasattr(self, "chk_sb_51"):
                self.chk_sb_51.setChecked(False)
            self._soundbar_profile = "none"
        except Exception:
            pass

        try:
            if getattr(self, "txt_log", None):
                self.txt_log.hide()
        except Exception:
            pass
        try:
            if getattr(self, "progress_bar", None):
                self.progress_bar.hide()
        except Exception:
            pass

    # ======== MUTUA ESCLUSIONE PROFILI AUDIO ========
    def _setup_exclusive_audio_profiles(self):
        """
        Rende mutuamente esclusivi:
          - self.chk_force_stereo   (Stereo downmix 2ch)
          - self.chk_sb_stereo      (Samsung — Stereo)
          - self.chk_sb_51          (Samsung — 5.1 AC-3)
        Consentito lo stato 'nessuna' (tutti OFF).
        """
        self._excl_guard = False
        self._exclusive_cbs = [
            getattr(self, "chk_force_stereo", None),
            getattr(self, "chk_sb_stereo", None),
            getattr(self, "chk_sb_51", None),
        ]
        self._exclusive_cbs = [cb for cb in self._exclusive_cbs if cb is not None]
        if not self._exclusive_cbs:
            return
        for cb in self._exclusive_cbs:
            cb.toggled.connect(lambda on, who=cb: self._on_exclusive_cb_toggled(who, on))
        self._apply_profile_from_state()

    def _on_exclusive_cb_toggled(self, source_cb, is_on: bool):
        if self._excl_guard:
            return
        self._excl_guard = True
        try:
            if is_on:
                for cb in self._exclusive_cbs:
                    if cb is not source_cb and cb.isChecked():
                        try:
                            cb.blockSignals(True)
                            cb.setChecked(False)
                            cb.blockSignals(False)
                        except Exception:
                            pass
            self._apply_profile_from_state()
        finally:
            self._excl_guard = False
        self._after_profile_change()

    def _apply_profile_from_state(self):
        downmix_on = bool(getattr(self, "chk_force_stereo", None) and self.chk_force_stereo.isChecked())
        sb_st_on = bool(getattr(self, "chk_sb_stereo", None) and self.chk_sb_stereo.isChecked())
        sb_51_on = bool(getattr(self, "chk_sb_51", None) and self.chk_sb_51.isChecked())
        if sb_51_on:
            self._active_profile = "sb_51"
            self._soundbar_profile = "samsung_5_1_ac3"
        elif sb_st_on:
            self._active_profile = "sb_tvj"
            self._soundbar_profile = "samsung_stereo"
        elif downmix_on:
            self._active_profile = "downmix"
            self._soundbar_profile = "none"
        else:
            self._active_profile = "none"
            self._soundbar_profile = "none"

    def _after_profile_change(self):
        try:
            self._update_pan_preset_label()
        except Exception:
            pass
        try:
            self._refresh_filter_availability()
        except Exception:
            pass
        for maybe in (
            "_update_example_preview_cmd",
            "update_ffmpeg_preview",
            "_update_ffmpeg_textarea",
            "_refresh_preview_and_cmd",
            "on_audio_params_changed",
        ):
            fn = getattr(self, maybe, None)
            if callable(fn):
                try:
                    fn()
                    break
                except Exception:
                    continue

"""
# === Main ===
if __name__ == "__main__":
    import argparse
    from PyQt5.QtWidgets import QApplication

    parser = argparse.ArgumentParser(description="Generatore stringa audio (HEVC-GUI)")
    parser.add_argument("--audio", help="File audio ESTERNO (mp3/flac/aac/ac3...) da usare come sorgente")
    parser.add_argument("--lang", default="und", help="Lingua traccia esterna (es. ita, eng, und)")
    parser.add_argument("--force-stereo", action="store_true", help="Spunta 'Stereo (downmix 2ch)'")
    parser.add_argument("--headless", action="store_true", help="Non mostra la finestra: genera JSON e stampa")
    parser.add_argument("--show-cmd", action="store_true", help="Mostra la text-box del comando/preview")
    args = parser.parse_args()

    if args.show_cmd:
        os.environ["HEVC_PREVIEW_SHOW_CMD_BOX"] = "1"

    app = QApplication(sys.argv)
    dlg = AudioConverter(auto="", parent=None)

    if args.audio:
        dlg.chk_force_mute.setChecked(True)
        dlg.load_external_audio(args.audio)
        # usa la combo se presente; in CLI consenti override con --lang
        try:
            idx = dlg.cmb_lang.findData((args.lang or "und").lower().strip())
            if idx >= 0:
                dlg.cmb_lang.setCurrentIndex(idx)
        except Exception:
            pass
        if args.force_stereo and hasattr(dlg, "chk_force_stereo"):
            dlg.chk_force_stereo.setChecked(True)

    if args.headless:
        dlg.add_seg()
        dlg.finish()
        sys.exit(0)

    dlg.show()
    app.exec_()

# Alias esplicito per API più chiara
StringAudioGenerator = AudioConverter

__all__ = ["AudioConverter", "StringAudioGenerator"]
# [FINE FILE]
"""
# === Main (disabilitato) ===
if __name__ == "__main__":  # blocco l'uso stand-alone (anche con `python -m`)
    import sys
    print(
        "Questo modulo non è eseguibile da solo.\n"
        "Aprilo dall’app HEVC-GUI (MainWindow) e usalo solo dentro la GUI.",
        file=sys.stderr,
    )
    raise SystemExit(2)
