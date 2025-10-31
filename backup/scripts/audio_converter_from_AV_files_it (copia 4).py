#!/usr/bin/env python3
"""Audio-Extractor + Preview per HEVC-GUI"""

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
)
from PyQt5.QtCore import Qt, pyqtSlot, QProcess, QTimer, QTime

from hevc_gui.core import constants as C
from hevc_gui.core.audio_helpers import audio_tracks_with_title
from conversion_thread_external import ConversionThreadExternal

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
    # 1) funzione run_preview
    fn = getattr(_preview_mod, "run_preview", None)
    if callable(fn):
        print("[UI] run_preview(mod.run_preview) …", flush=True)
        return fn(ac)
    # 2) funzione start_preview
    fn = getattr(_preview_mod, "start_preview", None)
    if callable(fn):
        print("[UI] run_preview(mod.start_preview) …", flush=True)
        return fn(ac)
    # 3) classe AudioPreview
    cls = getattr(_preview_mod, "AudioPreview", None)
    if cls is not None:
        print("[UI] run_preview(AudioPreview.start) …", flush=True)
        obj = cls(ac)
        return obj.start()
    # Se arrivi qui, il modulo non espone nulla utilizzabile
    raise ImportError(
        f"preview.py non espone run_preview/start_preview/AudioPreview. File caricato: {getattr(_preview_mod, '__file__', '?')}"
    )


class Batch:
    def __init__(self, video_file: str | None = None):
        """
        video_file: percorso del file video originale, usato per
        rimuovere solo quelle coppie '-i <video_originale>' in flush().
        Se None, siamo in modalità audio esterno.
        """
        self.items: list[list[str]] = []
        self.file: str | None = video_file

    def set_video_file(self, video_file: str):
        """Permette di impostare o cambiare il file video di input."""
        self.file = video_file

    def add(self, seg: list[str]):
        """Aggiunge un segmento (lista di flag/argomenti ffmpeg) alla batch."""
        self.items.append(seg)

    def flush(self):
        """
        - Togli 'ffmpeg' o C.FFMPEG_BIN e '-y'
        - Se self.file è definito, rimuove solo '-i <video_originale>'
        - Altrimenti (audio esterno), riscrive ogni '-map N:a:X' in '-map 1:X'
        - Stampa il JSON risultante
        """
        cleaned = []
        video_in = self.file  # se None, siamo in audio esterno

        # 1) Pulizia base di ogni segmento
        for seg in self.items:
            opts = seg.copy()

            # a) strip 'ffmpeg' o binario custom
            while opts and opts[0] in (C.FFMPEG_BIN, "ffmpeg"):
                opts.pop(0)

            # b) strip '-y'
            if opts and opts[0] == "-y":
                opts.pop(0)

            # c) se ho un video_in valido, rimuovo solo '-i <video_in>'
            if video_in:
                i = 0
                while i < len(opts) - 1:
                    if opts[i] == "-i" and opts[i + 1] == video_in:
                        opts.pop(i)
                        opts.pop(i)
                    else:
                        i += 1

            cleaned.append(opts)

        # 2) Se audio esterno, correggo tutte le map
        if video_in is None:
            import re

            for opts in cleaned:
                for i in range(len(opts) - 1):
                    if opts[i] == "-map":
                        m = re.match(r"\d+:a:(\d+)", opts[i + 1])
                        if m:
                            # riscrivo "0:a:X" o "1:a:X" → "1:X"
                            opts[i + 1] = f"1:{m.group(1)}"

        # 3) Serializzo in JSON
        print(json.dumps(cleaned, ensure_ascii=False))
        # (facoltativo) svuoto self.items se ti serve
        # self.items.clear()


class TagDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tag lingua mancante")
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Seleziona la lingua della traccia:"))

        self.cmb = QComboBox(self)
        self.cmb.setToolTip("Scegli la lingua della traccia audio selezionata (codice ISO)")
        self.cmb.addItems(sorted(C.LANGUAGE_NAMES.keys()))
        if "ITA" in C.LANGUAGE_NAMES:
            self.cmb.setCurrentText("ITA")
        layout.addWidget(self.cmb)

        btns = QHBoxLayout()
        ok = QPushButton("OK", self)
        cancel = QPushButton("Annulla", self)
        btns.addStretch()
        btns.addWidget(ok)
        btns.addWidget(cancel)
        layout.addLayout(btns)

        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)

    def selected(self) -> str:
        return self.cmb.currentText()


def get_media_duration_seconds(file_path: str) -> float:
    """Estrae durata media in secondi con ffprobe"""
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
        duration = float(result.stdout.strip())
        return duration
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

        # Nome file sopra la barra
        self.lbl_file = QLabel("", self)
        self.lbl_file.setTextInteractionFlags(Qt.TextSelectableByMouse)

        # Stato/progress text
        self.lbl = QLabel("Inizializzazione…", self)

        # Barra
        self.bar = QProgressBar(self)
        self.bar.setRange(0, 0)  # indeterminate finché non sappiamo la durata

        # Pulsante Annulla
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

    # — utils —
    @staticmethod
    def _hms(sec: int | float | None) -> str:
        if sec is None or sec < 0:
            return "??:??:??"
        sec = int(sec)
        h = sec // 3600
        m = (sec % 3600) // 60
        s = sec % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

    # — wiring —
    def attach_process(
        self,
        proc: QProcess,
        *,
        total_secs: int | None,
        display_name: str,
        full_path: str = "",
    ):
        """Collega il QProcess e imposta durata/nome file."""
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

        # Cerca time=hh:mm:ss.xx

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
            # Indeterminata: mostriamo solo il tempo trascorso
            self.lbl.setText(f"Elaborazione… {self._hms(cur)}")

    def _on_finished(self, code, _status):
        if code == 0 and not self._cancelled:
            # porta al 100% per un attimo, se determinata
            if self.bar.maximum() == 100:
                self.bar.setValue(100)
                self.lbl.setText("Completato.")
            self.accept()
        elif not self._cancelled:
            self.lbl.setText(f"ffmpeg terminato con codice {code}")
            QTimer.singleShot(1200, self.reject)


class AudioConverter(QDialog):
    def __init__(self, auto: str, parent=None):
        super().__init__(parent)

        # finestra
        self.setWindowTitle("Audio Converter")
        self.resize(480, 400)
        self.setAcceptDrops(True)  # drag&drop su tutta la finestra

        # stato interno
        self.batch = Batch()
        self._closing_via_finish = False
        self.file: Path | None = None
        self._orig_bitrates: dict[int, str] = {}

        self.audio_externo = False
        self.external_audio_file: str | None = None
        self.external_audio_lang: str | None = None
        self.conv_thread_external: ConversionThreadExternal | None = None
        self.external_audio_duration = 0.0

        # costruzione UI
        self._build_ui()
        self._wire_doubleclick_shortcuts()
        self._ensure_preview_wiring()
        self._connect_pan_preset_signals()
        # prima valutazione
        self._update_pan_preset_label()

        # progress bar (inizialmente nascosta)
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.layout().addWidget(self.progress_bar)
        self.progress_bar.hide()

        # pulsante carica audio esterno (inserito subito dopo path)
        self.btn_load_external_audio = QPushButton("Carica traccia audio esterna", self)
        self.layout().insertWidget(1, self.btn_load_external_audio)
        self.btn_load_external_audio.hide()

        # connessioni base
        self.btn_ok.clicked.connect(self.finish)
        self.btn_load_external_audio.clicked.connect(self.load_external_audio)
        self.cmb_track.currentIndexChanged.connect(self._on_track_changed)
        self.cmb_br.currentTextChanged.connect(self._update_track_title)

        # caricamento iniziale del file
        self.load_file(auto)

    def _build_ui(self):
        from hevc_gui.core import constants as C
        import os

        try:
            from sip import isdeleted as _sip_isdeleted
        except Exception:

            def _sip_isdeleted(obj):
                try:
                    obj.objectName()
                    return False
                except Exception:
                    return True

        # === Misure finestra e blocco centrale (stile "foto 1") ===
        target_w = int(os.getenv("AUDIOCONV_UI_WIDTH", "520"))
        form_w = int(os.getenv("AUDIOCONV_FORM_WIDTH", "480"))

        # === Finestra ===
        self.setWindowTitle("Audio Converter")
        self.resize(target_w, 520)
        self.setFixedWidth(target_w)
        self.setAcceptDrops(True)

        vmain = QVBoxLayout(self)
        vmain.setContentsMargins(8, 6, 8, 6)
        vmain.setSpacing(6)

        # Helper: riga centrata orizzontalmente, contenuti allineati a sinistra
        def add_row_centered(*widgets: QWidget, stretch_last: bool = False, spacing: int = 6):
            box = QWidget(self)
            box.setFixedWidth(form_w)
            hb = QHBoxLayout(box)
            hb.setContentsMargins(0, 0, 0, 0)
            hb.setSpacing(spacing)
            for w in widgets:
                if w is None:
                    continue
                hb.addWidget(w, 0, Qt.AlignLeft)
            if stretch_last:
                hb.addStretch(1)
            vmain.addWidget(box, 0, Qt.AlignHCenter)
            return box, hb

        # ---------------- RIGA 1: Percorso ----------------
        self.path = QLineEdit(self)
        self.path.setReadOnly(True)
        vmain.addWidget(self.path)

        # ---------------- RIGA 2: "Tratta come muto" ----------------
        self.chk_force_mute = QCheckBox("Tratta come muto", self)
        add_row_centered(self.chk_force_mute)

        # ---------------- RIGA 3: Traccia ----------------
        lbl_traccia = QLabel("Traccia:", self)
        self.cmb_track = QComboBox(self)
        self.cmb_track.addItem("Seleziona traccia…", (-1, None, None))
        self.cmb_track.setEnabled(False)
        add_row_centered(lbl_traccia, self.cmb_track, stretch_last=True)

        # ---------------- RIGA 4: Bit-rate → Sample rate ----------------
        lbl_br = QLabel("Bit-rate:", self)
        self.cmb_br = QComboBox(self)
        self.cmb_br.addItems(getattr(C, "AUD_BITRATES", ["Nessuno"]))
        lbl_sr = QLabel("Sample rate (Hz):", self)
        self.cmb_sr = QComboBox(self)
        self.cmb_sr.addItems(getattr(C, "AUD_SAMPLE_RATES", ["Nessuno"]))
        add_row_centered(lbl_br, self.cmb_br, QLabel("   "), lbl_sr, self.cmb_sr, stretch_last=True)

        # ---------------- RIGA 5: Noise-Reduction → Denoise nr → Gain ----------------
        self.chk_nr = QCheckBox("Noise-Reduction", self)
        lbl_nr = QLabel("Denoise nr:", self)
        self.in_nr = QLineEdit(self)
        self.in_nr.setPlaceholderText("0–30 dB")
        self.in_nr.setEnabled(False)
        self.chk_nr.toggled.connect(self.in_nr.setEnabled)
        lbl_gain = QLabel("Gain (dB):", self)
        self.cmb_gain = QComboBox(self)
        self.cmb_gain.addItems(getattr(C, "AUD_GAIN_RANGE", ["0"]))
        self.cmb_gain.setCurrentText("0")
        add_row_centered(self.chk_nr, QLabel("   "), lbl_nr, self.in_nr, QLabel("   "), lbl_gain, self.cmb_gain, stretch_last=True)

        # ---------------- RIGA 6: Bass → Mid → High ----------------
        lbl_b = QLabel("Bass (dB):", self)
        self.cmb_eq_bass = QComboBox(self)
        self.cmb_eq_bass.addItems(getattr(C, "AUD_EQ_DB_CHOICES", ["0"]))
        self.cmb_eq_bass.setCurrentText("0")
        lbl_m = QLabel("Mid (dB):", self)
        self.cmb_eq_mid = QComboBox(self)
        self.cmb_eq_mid.addItems(getattr(C, "AUD_EQ_DB_CHOICES", ["0"]))
        self.cmb_eq_mid.setCurrentText("0")
        lbl_h = QLabel("High (dB):", self)
        self.cmb_eq_treb = QComboBox(self)
        self.cmb_eq_treb.addItems(getattr(C, "AUD_EQ_DB_CHOICES", ["0"]))
        self.cmb_eq_treb.setCurrentText("0")
        add_row_centered(
            lbl_b, self.cmb_eq_bass, QLabel("   "), lbl_m, self.cmb_eq_mid, QLabel("   "), lbl_h, self.cmb_eq_treb, stretch_last=True
        )

        # Gain largo come High (dB)
        try:
            w_target = self.cmb_eq_treb.sizeHint().width()
            self.cmb_gain.setFixedWidth(w_target)
        except Exception:
            pass

        # ---------------- RIGA 7: Reverb → Stereo Enh → Compr. (tutto su una riga) ----------------
        lbl_rev = QLabel("Reverb:", self)
        self.cmb_rev = QComboBox(self)
        self.cmb_rev.addItems(getattr(C, "AUD_REVERB_LEVELS", ["Nessuno"]))

        lbl_st = QLabel("Stereo Enh:", self)
        self.cmb_stereo = QComboBox(self)
        self.cmb_stereo.addItem("Nessuno")
        try:
            self.cmb_stereo.addItems(list(getattr(C, "AUD_STEREO_ENHANCERS", {}).keys()))
        except Exception:
            pass

        lbl_comp = QLabel("Compr.", self)
        lbl_comp.setToolTip("Compressore")
        self.cmb_comp_soft = QComboBox(self)
        self.cmb_comp_soft.addItems(["Nessuno", "Leggero", "Medio", "Forte"])
        self.cmb_comp_soft.setCurrentText("Nessuno")

        # riga unica (senza QLabel spacer); spacing ridotto
        row7_box = QWidget(self)
        row7_layout = QHBoxLayout(row7_box)
        row7_layout.setContentsMargins(0, 0, 0, 0)
        row7_layout.setSpacing(6)
        for w in (lbl_rev, self.cmb_rev, lbl_st, self.cmb_stereo, lbl_comp, self.cmb_comp_soft):
            row7_layout.addWidget(w, 0, Qt.AlignLeft)
        row7_layout.addStretch(1)
        vmain.addWidget(row7_box, 0, Qt.AlignHCenter)

        # Reverb e Stereo Enh. della stessa larghezza di "Compr." (senza tagli)
        try:
            from PyQt5.QtWidgets import QSizePolicy, QComboBox as _QCB

            comp_w = (
                max(self.cmb_comp_soft.sizeHint().width(), self.cmb_comp_soft.width(), self.cmb_gain.sizeHint().width()) + 6
            )  # piccolo margine per la freccia
            # non forzo "Compr." (resta com'è), adeguo solo Reverb e Stereo Enh.
            for w in (self.cmb_rev, self.cmb_stereo):
                w.setSizePolicy(QSizePolicy.Fixed, w.sizePolicy().verticalPolicy())
                w.setMinimumWidth(comp_w)
                w.setMaximumWidth(comp_w)
                w.setSizeAdjustPolicy(_QCB.AdjustToMinimumContentsLengthWithIcon)
                w.setMinimumContentsLength(7)
        except Exception:
            pass

        # ---------------- RIGA 8: Auto-loudness → Dialog Boost ----------------
        self.chk_dyn = QCheckBox("Auto-loudness (DynAudNorm)", self)
        self.chk_dialog_boost = QCheckBox("Dialog Boost (+2 dB @ 2 kHz)", self)
        add_row_centered(self.chk_dyn, QLabel("   "), self.chk_dialog_boost, stretch_last=True)

        # ---------------- RIGA 9: Mantieni MONO → Evita clipping ----------------
        self.chk_keep_mono = QCheckBox("Mantieni MONO se input mono (AAC 1.0)", self)
        self.chk_anticlip = QCheckBox("Evita clipping (limiter soft)", self)
        add_row_centered(self.chk_keep_mono, QLabel("   "), self.chk_anticlip, stretch_last=True)

        # ---------------- RIGA 10: Preview ----------------
        lbl_prev = QLabel("Preview:", self)
        lbl_start = QLabel("Start:", self)
        self.te_prev_start = QTimeEdit(self)
        self.te_prev_start.setDisplayFormat("HH:mm:ss")
        self.te_prev_start.setTime(QTime(0, 0, 0))
        self.te_prev_start.setAccelerated(True)
        self.te_prev_start.setButtonSymbols(QAbstractSpinBox.UpDownArrows)
        lbl_dur = QLabel("Durata:", self)
        self.cmb_prev = QComboBox(self)
        for seconds, label in getattr(C, "AUD_PREVIEW_OPTIONS", [(60, "1 min"), (300, "5 min"), (0, "∞")]):
            self.cmb_prev.addItem(label, seconds)
        self.btn_prev = QPushButton("Preview", self)
        self.btn_prev.setObjectName("btn_prev")
        fm = self.fontMetrics()
        self.te_prev_start.setFixedWidth(fm.horizontalAdvance("00:00:00") + 40)
        add_row_centered(
            lbl_prev, lbl_start, self.te_prev_start, QLabel("   "), lbl_dur, self.cmb_prev, QLabel("   "), self.btn_prev, stretch_last=True
        )

        # ---------------- RIGA 11: lista comandi (ridotta a ~2 righe) ----------------
        self.list = QListWidget(self)
        self.list.setFixedWidth(form_w)
        fm = self.fontMetrics()
        row_h = fm.height() + 6
        fixed_h = row_h * 2 + 8
        self.list.setMinimumHeight(fixed_h)
        self.list.setMaximumHeight(fixed_h)
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        vmain.addWidget(self.list, 0, Qt.AlignHCenter)

        # ---------------- SOTTO: Stereo (downmix 2ch) ----------------
        self.chk_force_stereo = QCheckBox("Stereo (downmix 2ch)", self)
        add_row_centered(self.chk_force_stereo)

        # ---------------- PROFILO SOUNDBAR (solo qui) ----------------
        lbl_sb = QLabel("Profilo soundbar:", self)
        lbl_sb.setObjectName("lbl_sb")
        add_row_centered(lbl_sb)
        self.chk_sb_stereo = QCheckBox("Samsung — Stereo (TV J + HW-R450)", self)
        self.chk_sb_stereo.setObjectName("chk_sb_stereo")
        self.chk_sb_51 = QCheckBox("Samsung — 5.1 AC-3 (48 kHz)", self)
        self.chk_sb_51.setObjectName("chk_sb_51")
        add_row_centered(self.chk_sb_stereo, QLabel("   "), self.chk_sb_51, stretch_last=True)

        # blocca inject esterno
        self._soundbar_injected = True

        # ---------------- FOOTER: Pan preset a sx + bottoni a dx (ancorati a destra) ----------------
        from PyQt5.QtWidgets import QSizePolicy

        def _ensure_pan_label():
            lbl = getattr(self, "lbl_pan_preset", None)
            if lbl is None or _sip_isdeleted(lbl):
                lbl = QLabel("Pan preset: — (nessun downmix)", self)
                lbl.setObjectName("lbl_pan_preset")
                lbl.setStyleSheet("color: #666;")
                self.lbl_pan_preset = lbl
            return lbl

        self.lbl_pan_preset = _ensure_pan_label()

        footer_box = QWidget(self)
        footer_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        footer = QHBoxLayout(footer_box)
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(4)

        # sx: placeholder
        footer.addWidget(self.lbl_pan_preset, 0, Qt.AlignLeft)
        footer.addStretch(1)

        # dx: bottoni ravvicinati e ancorati al margine destro
        self.btn_add = QPushButton("Aggiungi traccia", self)
        self.btn_add.setEnabled(False)
        self.btn_cancel = QPushButton("Cancel", self)
        self.btn_ok = QPushButton("OK / Exit", self)
        for b in (self.btn_add, self.btn_cancel, self.btn_ok):
            b.setAutoDefault(False)
            b.setDefault(False)
            footer.addWidget(b, 0, Qt.AlignRight)

        vmain.addWidget(footer_box)  # niente AlignHCenter: bottoni a destra

    def dragEnterEvent(self, event):
        """
        Accetta il drag se contiene almeno un URL (file).
        """
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        """
        Gestisce il drop dei file:
        - Se siamo in “muto forzato” o audio_externo=True, tratta il file
          come sorgente audio esterno (load_external_audio).
        - Altrimenti lo carica normalmente come input video/audio (load_file).
        """
        urls = event.mimeData().urls()
        if not urls:
            return super().dropEvent(event)

        file_path = urls[0].toLocalFile()

        if self.chk_force_mute.isChecked() or self.audio_externo:
            # drag&drop in modalità “muto forzato” o esterno
            self.load_external_audio(file_path)
        else:
            # drag&drop normale
            self.load_file(file_path)

        event.acceptProposedAction()

    def _normalize_eq_combo(self, cmb: QComboBox):
        # oggi le combo EQ non sono editabili; funzione lasciata per eventuale futuro switch
        s = (cmb.currentText() or "").strip().replace(",", ".")
        try:
            v = float(s)
        except Exception:
            v = 0.0
        v = max(-18.0, min(18.0, v))  # clamp
        txt = f"{v:.2f}".rstrip("0").rstrip(".")
        if txt in ("-0", "+0", ""):
            txt = "0"
        cmb.setCurrentText(txt)

    def _ensure_preview_wiring(self):
        """Collega qualsiasi bottone/azione 'Preview' a run_preview(self)."""
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
        Inietta la riga 'Profilo soundbar' e compatta il box comandi.
        Il doppio-click → Preview è DISATTIVATO di default; per attivarlo:
          HEVC_PREVIEW_DBLCLICK=1
        Quando attivo reagisce solo se il widget è abilitato.
        """
        import os
        from PyQt5.QtCore import QObject, QEvent
        from PyQt5.QtWidgets import (
            QWidget,
            QLabel,
            QCheckBox,
            QHBoxLayout,
            QVBoxLayout,
            QGridLayout,
            QBoxLayout,
        )

        # flag: abilita doppio-click → preview solo via env var
        self._allow_dblclick_preview = os.getenv("HEVC_PREVIEW_DBLCLICK", "0") == "1"

        # ---------- helpers layout ----------
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
            # prova a trovare la label "Stereo Enh:" o la combo relativa
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

        # ---------- inserisce riga profilo soundbar + label pan ----------
        def _insert_soundbar_row():
            if getattr(self, "_soundbar_injected", False):
                return True

            anchor = _find_stereo_enh_anchor()
            lay, container, pos = _layout_of(anchor or self)

            # etichetta a sinistra (Form/Grid) o riga di titolo (Box)
            row_label = QLabel("Profilo soundbar", container)

            # box con i due checkbox + label pan
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

            # label pan (crea se manca)
            if not getattr(self, "lbl_pan_preset", None):
                self.lbl_pan_preset = QLabel("Pan preset: nessuno (input stereo/mono o profili spenti)", row_box)
                self.lbl_pan_preset.setStyleSheet("color: #777;")
            vb.addWidget(self.lbl_pan_preset)

            # stato interno
            self._soundbar_profile = "none"
            self.chk_sb_stereo = cb_st
            self.chk_sb_51 = cb_51

            # esclusività con "Stereo (downmix 2ch)"
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
            # aggiorna la disponibilità dei controlli quando cambi profilo soundbar
            cb_st.toggled.connect(lambda _: self._refresh_filter_availability())
            cb_51.toggled.connect(lambda _: self._refresh_filter_availability())

            # se abiliti il downmix esterno, spegni i profili
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

            # inserimento nel layout
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

        # ---------- compattazione del box comandi ----------
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
                    if any(k in name.lower() for k in ("cmd", "command", "preview", "ffmpeg")):
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

        # ---------- (opzionale) doppio-click → preview ----------
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
                    # solo se abilitato e widget attivo
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
                setattr(w, "_dblclick_filter_", f)  # evita GC
                w.installEventFilter(f)
            except Exception:
                pass

        def _wire_doubleclick():
            # se non attivo via env var, non cabliamo nulla
            if not self._allow_dblclick_preview:
                return
            names = ("cmb_eq_bass", "cmb_eq_mid", "cmb_eq_treb", "cmb_comp_soft", "cmb_stereo")
            for nm in names:
                w = getattr(self, nm, None)
                if w is not None and hasattr(w, "installEventFilter"):
                    _enable_dblclick(w, _trigger_preview)

        # ======= blocco da mantenere identico =======
        def _do_all():
            ok = _insert_soundbar_row()
            _shrink_cmd_box(max_lines=2)
            _wire_doubleclick()
            return ok

        if not _do_all():
            QTimer.singleShot(120, _do_all)

    def _fmt_track_label(self, idx: int, lang: str, br: str) -> str:
        """
        Etichetta combo tracce con badge [M]/[S]/[MC] + lingua + info br/SR quando disponibili.
        """
        # lingua “umana”
        from hevc_gui.core import constants as C

        lang_full = C.LANGUAGE_NAMES.get(lang, lang) if lang else "—"

        # sample-rate selezionato in GUI (solo info, non probiamo SR input qui)
        sr = self.cmb_sr.currentText() if getattr(self, "cmb_sr", None) else "Nessuno"

        # canali da cache (o probing last-minute se mancano)
        ch = None
        try:
            ch = self._orig_channels.get(idx) if hasattr(self, "_orig_channels") else None
            if ch is None:
                # come fallback, prova a leggere ora
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

    def _fmt_audio_title_from_flags(self, *, lang: str, codec: str, ac: int, ar: int | None, br: str | None) -> str:
        """
        Costruisce il title stream coerente coi flag che stiamo davvero usando.
        Esempio: 'Italiano • AC-3 5.1 • 48 kHz • 448 kb/s'
        """
        lang_full = C.LANGUAGE_NAMES.get(lang, lang)
        codec_lbl = {
            "aac": "AAC",
            "libfdk_aac": "AAC",
            "ac3": "AC-3",
            "eac3": "E-AC-3",
        }.get(str(codec).lower(), str(codec).upper())
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
    def load_external_audio(self, file_path: str | None = None):
        """
        Carica/aggancia una traccia audio esterna.
        Popola cmb_track con indici reali + badge [M]/[S]/[MC] e bitrate se trovabile.
        """
        if not hasattr(self, "_orig_channels"):
            self._orig_channels: dict[int, int] = {}

        # Se non arriva un path, chiedilo all'utente (cartella del file corrente se disponibile)
        if not file_path:
            start_dir = str(self.file.parent) if getattr(self, "file", None) else os.path.expanduser("~")
            filters = (
                "Audio (*.wav *.flac *.aac *.m4a *.mp3 *.ogg *.ac3 *.eac3);;Video con audio (*.mkv *.mp4 *.mov *.avi);;Tutti i file (*)"
            )
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "Seleziona traccia audio esterna",
                start_dir,
                filters,
            )
            if not file_path:
                return  # annullato

        # Stato esterno attivo
        self.external_audio_file = file_path
        self.audio_externo = True
        try:
            self.path.setText(f"Audio esterno: {file_path}")
        except Exception:
            pass

        # Popola la combo tracce con indici reali e bitrate/canali misurati
        try:
            tracks = list(audio_tracks_with_title(file_path))
        except Exception:
            tracks = []

        self._orig_bitrates = getattr(self, "_orig_bitrates", {})
        self._orig_channels = getattr(self, "_orig_channels", {})
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
                label = self._fmt_track_label(a_idx, None, br_lbl or "Nessuno")
                if title:
                    label += f" – {title}"
                self.cmb_track.addItem(label, (a_idx, None, br_lbl or "Nessuno"))
            # salta il placeholder
            self.cmb_track.setCurrentIndex(1 if self.cmb_track.count() > 1 else 0)
        else:
            # fallback (file con 1 pista “mutizzata”)
            self.cmb_track.addItem(self._fmt_track_label(0, None, "Nessuno"), (0, None, "Nessuno"))
            self.cmb_track.setCurrentIndex(1 if self.cmb_track.count() > 1 else 0)

        self.cmb_track.setEnabled(True)
        self.cmb_track.blockSignals(False)

        # UI di contesto
        try:
            self.btn_add.setEnabled(False)
            self.btn_load_external_audio.show()
        except Exception:
            pass

        # Debug
        try:
            print("[DEBUG] Combo tracce (esterne):")
            for i in range(self.cmb_track.count()):
                print(f"  {i:02d}: text='{self.cmb_track.itemText(i)}' data={self.cmb_track.itemData(i)}")
        except Exception:
            pass

        # Aggiorna availability/label
        try:
            self._refresh_filter_availability()
            self._update_pan_preset_label()
        except Exception:
            pass

    # ── Alias retro-compatibile: rimuovibile quando ti va ─────────────────
    def _load_external_audio(self, file_path: str):
        """Compat: instrada al nuovo load_external_audio()."""
        return self.load_external_audio(file_path)

    def _norm_audio_index(self, idx, pos_fallback: int) -> int:
        """
        Ritorna l'indice audio 0-based per -map 0:a:N.

        Regole:
        - Se idx è stringa tipo 'a:N' o '0:a:N' → usa N (già 0-based per -map 0:a:N).
        - In TUTTI gli altri casi (int, ecc.) → usa SEMPRE pos_fallback (0-based dall'enumerazione).
          Motivo: molte funzioni upstream passano 1-based (1,2,3...), mentre -map 0:a:N è 0-based.
        """
        s = str(idx)
        if "a:" in s:
            try:
                return max(0, int(s.split(":")[-1]))
            except Exception:
                return int(pos_fallback)
        return int(pos_fallback)

    def _probe_audio_bitrate_label(self, path: str, a_idx: int) -> str | None:
        """
        '192k' con il bitrate REALE della traccia a_idx (ffprobe).
        Se non trovabile (VBR senza bit_rate), torna None.
        """
        import json
        import subprocess

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
        Se attivo: passiamo in modalità 'audio esterno'. La combo tracce interne viene disabilitata
        e compare il bottone 'Carica traccia audio esterna'. Se disattivo, ripristina la UI.
        """
        if checked:
            self.audio_externo = True
            self.external_audio_file = None
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
            self.audio_externo = False
            self.btn_load_external_audio.hide()
            # ricarica elenco tracce dal file corrente (se presente)
            if self.file:
                self.load_file(str(self.file))
            else:
                self.cmb_track.clear()
                self.cmb_track.addItem("Seleziona traccia…", (-1, None, None))
                self.cmb_track.setEnabled(False)
            self.btn_add.setEnabled(False)
        # aggiorna label pan se presente
        try:
            self._update_pan_preset_label()
        except Exception:
            pass

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
        Carica un file (video o audio) come sorgente per l'estrazione.
        Popola cmb_track con (a_idx, lang=None, bitrate_reale | 'Nessuno') e badge [M]/[S]/[MC].
        """
        # cache canali/bitrate per le etichette
        if not hasattr(self, "_orig_channels"):
            self._orig_channels: dict[int, int] = {}
        self.file = Path(p)
        self._orig_bitrates.clear()
        self._orig_channels.clear()

        self.cmb_track.clear()
        self.cmb_track.addItem("Seleziona traccia…", (-1, None, None))

        # Modalità "Tratta come muto" → audio esterno
        if getattr(self, "chk_force_mute", None) and self.chk_force_mute.isChecked():
            self.audio_externo = True
            self.external_audio_file = str(self.file)
            self.path.setText(f"Trattato come muto: {self.file}")
            self.cmb_track.clear()
            self.cmb_track.addItem("File muto → carica audio esterno…", (-1, None, None))
            self.cmb_track.setEnabled(False)
            self.btn_load_external_audio.show()
            self.btn_add.setEnabled(False)
            return

        tracks = list(audio_tracks_with_title(str(self.file)))
        if not tracks:
            # nessuna traccia interna → audio esterno
            self.audio_externo = True
            self.external_audio_file = None
            self.path.clear()
            self.btn_load_external_audio.show()
            self.cmb_track.setEnabled(False)
            self.btn_add.setEnabled(False)
        else:
            # tracce interne
            self.audio_externo = False
            self.btn_load_external_audio.hide()
            self.path.setText(str(self.file))
            self.cmb_track.setEnabled(True)

            for pos, (idx_raw, title) in enumerate(tracks):
                a_idx = self._norm_audio_index(idx_raw, pos)
                # bitrate reale (se disponibile)
                br_lbl = self._probe_audio_bitrate_label(str(self.file), a_idx)
                if br_lbl:
                    self._orig_bitrates[a_idx] = br_lbl
                # canali reali → badge
                ch = self._probe_audio_channels(str(self.file), a_idx)
                if ch:
                    self._orig_channels[a_idx] = ch

                label = self._fmt_track_label(a_idx, None, br_lbl or "Nessuno")
                if title:
                    label += f" – {title}"
                self.cmb_track.addItem(label, (a_idx, None, br_lbl or "Nessuno"))

            self.btn_add.setEnabled(False)

        self.cmb_track.setCurrentIndex(0)

        # Debug mappa (opzionale)
        try:
            print("[DEBUG] Combo tracce:")
            for i in range(self.cmb_track.count()):
                print(f"  {i:02d}: text='{self.cmb_track.itemText(i)}' data={self.cmb_track.itemData(i)}")
        except Exception:
            pass

    @pyqtSlot()
    def add_seg(self):
        """
        Aggiunge **una** traccia audio alla batch da passare alla MainWindow.

        Regole:
          - Se audio esterno: usa l’unica traccia 0:a:0 del file caricato.
          - Se interno: usa l’indice reale scelto nella combo (0:a:{idx}).
          - Filtri: _build_filters_chain_from_ui(for_preview=False, channels_hint=detected_ch).
          - Codec/canali:
              • profilo soundbar 5.1 attivo → AC-3 5.1 @ 48 kHz, 448k di default
              • altrimenti: AAC stereo 2ch (o MONO 1ch se input mono + “Mantieni MONO”)
          - Bitrate:
              • se combo bitrate ≠ “Nessuno” → usa quello scelto dall’utente
              • se combo “Nessuno”:
                  - stereo → max(originale, 128k) (se originale non leggibile → 128k)
                  - mono   → 96k
                  - AC-3 5.1 → 448k
          - Title: **sempre** costruito da _fmt_audio_title_from_flags(...)
          - Metadata: language=<lang>, title=<title>.
        """

        # --- 1) Sorgente e scelta utente ------------------------------------------------
        is_ext = bool(self.audio_externo)
        if is_ext:
            if not self.external_audio_file:
                QMessageBox.warning(self, "Audio esterno", "Nessun file audio esterno caricato.")
                return
            src_path = str(self.external_audio_file)
            sidx = 0
            map_str = "0:a:0"
            lang = self.external_audio_lang or "und"
            br = "Nessuno"
            idx_for_orig = 0  # per probing originale
        else:
            data = self.cmb_track.currentData()
            if not isinstance(data, (tuple, list)) or len(data) < 3:
                QMessageBox.warning(self, "Audio", "Seleziona una traccia valida.")
                return
            idx, lang, br = data
            if idx < 0:
                QMessageBox.warning(self, "Audio", "Seleziona una traccia valida.")
                return
            # se manca la lingua, chiedila adesso
            if lang is None:
                dlg = TagDialog(self)
                if dlg.exec_() != QDialog.Accepted:
                    return
                lang = dlg.selected()
                # fallback bitrate: originale se lo avevamo misurato
                br = self._orig_bitrates.get(idx, "Nessuno")

            src_path = str(self.file)
            sidx = int(str(idx).split(":")[-1])
            map_str = f"0:a:{sidx}"
            idx_for_orig = idx

        # --- 2) Rileva canali in ingresso (per catena filtri coerente) -------------------
        detected_ch = 2
        try:
            from hevc_gui.core.ffprobe_utils import probe_audio_stream

            info = probe_audio_stream(src_path, stream_index=sidx) or {}
            detected_ch = int(info.get("channels") or 2)
        except Exception:
            pass

        # === NEW: se fai upmix MONO→STEREO (Mantieni MONO OFF) neutralizza i profili Samsung
        keep_mono = bool(getattr(self, "chk_keep_mono", None) and self.chk_keep_mono.isChecked())
        if detected_ch == 1 and not keep_mono:
            try:
                self._soundbar_profile = "none"
            except Exception:
                pass

        # --- 3) Profilo 5.1 sì/no (rispetta eventuale "Stereo (downmix 2ch)") -----------
        prof = getattr(self, "_soundbar_profile", "none")
        force_stereo = bool(getattr(self, "chk_force_stereo", None) and self.chk_force_stereo.isChecked())
        wants_51 = (prof == "samsung_5_1_ac3") and (not force_stereo)

        # --- 4) Costruisci catena filtri e (eventuale) loudnorm 2-pass -------------------
        filters = self._build_filters_chain_from_ui(for_preview=False, channels_hint=detected_ch)

        # Loudnorm 2-pass in encode reale (se selezionato)
        try:
            from hevc_gui.core.loudness import NORM_LOUDNORM2
        except Exception:
            NORM_LOUDNORM2 = None

        try:
            if NORM_LOUDNORM2 is not None and getattr(self, "cmb_norm", None) and self.cmb_norm.currentText() == NORM_LOUDNORM2:
                try:
                    from hevc_gui.core.loudness import (
                        measure_loudnorm_smart,
                        build_second_pass_filter_from_json,
                    )

                    stats = measure_loudnorm_smart(src_path, a_stream_idx=sidx, t=120)
                    if stats:
                        filters += build_second_pass_filter_from_json(stats, anticlipping=False)
                except Exception:
                    from hevc_gui.core.loudness import DEFAULT_I, DEFAULT_TP, DEFAULT_LRA

                    filters.append(f"loudnorm=I={DEFAULT_I}:TP={DEFAULT_TP}:LRA={DEFAULT_LRA}")
        except Exception:
            pass

        af_chain = ",".join(filters) if filters else None

        # --- Helpers bitrate --------------------------------------------------------------
        def _parse_kbps(s: str | None) -> int | None:
            if not s:
                return None
            txt = str(s).lower().strip()
            # prendi solo cifre
            digs = "".join(ch for ch in txt if ch.isdigit())
            if not digs:
                return None
            try:
                return int(digs)
            except Exception:
                return None

        # bitrate scelto dall'utente nella combo (se diverso da "Nessuno")
        user_br_txt = None
        try:
            if getattr(self, "cmb_br", None):
                ct = (self.cmb_br.currentText() or "").strip()
                if ct and ct.lower() != "nessuno":
                    user_br_txt = ct
        except Exception:
            pass

        # bitrate originale misurato (se disponibile)
        orig_br_txt = None
        try:
            if is_ext:
                orig_br_txt = self._probe_audio_bitrate_label(src_path, 0)
            else:
                orig_br_txt = self._orig_bitrates.get(idx_for_orig) or self._probe_audio_bitrate_label(str(self.file), sidx)
        except Exception:
            orig_br_txt = None
        orig_kbps = _parse_kbps(orig_br_txt)

        # --- 5) Codec / canali / sample-rate / bitrate -----------------------------------
        sr_sel = self.cmb_sr.currentText() if getattr(self, "cmb_sr", None) else "Nessuno"
        ar = int(sr_sel) if (sr_sel and sr_sel != "Nessuno" and sr_sel.isdigit()) else None

        if wants_51:
            codec, ac = "ac3", 6
            if not ar:
                ar = 48000
            # bitrate: preferisci scelta utente; altrimenti 448k
            if user_br_txt:
                br_eff = user_br_txt
            else:
                br_eff = "448k"
        else:
            if detected_ch == 1 and keep_mono:
                codec, ac = "aac", 1
                # MONO: scelta utente > default 96k
                if user_br_txt:
                    br_eff = user_br_txt
                else:
                    br_eff = "96k"
            else:
                # STEREO (origine stereo oppure upmix da mono)
                codec, ac = "aac", 2
                if user_br_txt:
                    # utente ha scelto → usa
                    br_eff = user_br_txt
                else:
                    # combo “Nessuno”: applichiamo il floor a 128k
                    if orig_kbps is None:
                        br_eff = "128k"  # non sappiamo l'originale → vai di 128
                    elif orig_kbps < 128:
                        br_eff = "128k"  # originale più basso → alza a 128
                    else:
                        br_eff = f"{orig_kbps}k"  # altrimenti mantieni l'originale

        # --- 6) Title SEMPRE derivato dai flag -------------------------------------------
        try:
            title = self._fmt_audio_title_from_flags(lang=lang, codec=codec, ac=ac, ar=ar, br=br_eff)
        except Exception:
            from hevc_gui.core import constants as C

            parts = [C.LANGUAGE_NAMES.get(lang, lang)]
            parts.append("AC-3 5.1" if (codec == "ac3" and ac == 6) else f"AAC {ac}ch")
            if ar:
                parts.append(f"{ar // 1000} kHz")
            if br_eff:
                parts.append(str(br_eff))
            title = " • ".join(parts)

        # --- 7) Segmento ffmpeg finale ----------------------------------------------------
        tag = len(self.batch.items)
        seg: list[str] = ["-i", src_path, "-map", map_str, "-vn"]
        if af_chain:
            seg += ["-af", af_chain]
        seg += [f"-c:a:{tag}", codec, f"-ac:{tag}", str(ac)]
        if ar:
            seg += [f"-ar:{tag}", str(ar)]
        if br_eff:
            seg += [f"-b:a:{tag}", str(br_eff)]
        seg += [
            f"-metadata:s:a:{tag}",
            f"language={lang}",
            f"-metadata:s:a:{tag}",
            f"title={title}",
        ]

        self.batch.add(seg)
        badge = "  [🔊 5.1]" if (codec == "ac3" and ac == 6) else ""
        self.list.addItem(" ".join(shlex.quote(a) for a in seg) + badge)

        if not is_ext:
            self.btn_add.setEnabled(False)

    def _build_filters_chain_from_ui(self, *, for_preview: bool, channels_hint: int) -> list[str]:
        from hevc_gui.core import constants as C

        filters: list[str] = []

        def _has_pan(fs: list[str]) -> bool:
            j = ",".join(fs).lower()
            return ("pan=stereo" in j) or ("pan=2c" in j)

        # Stato profilo Samsung
        prof = getattr(self, "_soundbar_profile", "none")
        is_samsung_stereo = prof == getattr(C, "PROFILE_SAMSUNG_STEREO_KEY", "samsung_stereo")

        # === MONO → STEREO se "Mantieni MONO" è OFF (pseudo-stereo; niente dual-mono)
        keep_mono = bool(getattr(self, "chk_keep_mono", None) and self.chk_keep_mono.isChecked())
        pseudo_applied = False
        if channels_hint == 1 and not keep_mono:
            filters.append(
                "asplit=2[a][b];[b]adelay=12:all=1,equalizer=f=3000:t=q:w=1.2:g=-1.5[br];[a][br]join=inputs=2:channel_layout=stereo"
            )
            pseudo_applied = True

        # 1) Gain (pre)
        try:
            gtxt = (self.cmb_gain.currentText() or "").strip()
            if gtxt and gtxt not in ("0", "0dB", "Nessuno"):
                g = float(gtxt[:-2]) if gtxt.lower().endswith("db") else float(gtxt)
                if abs(g) > 0.0001:
                    filters.append(f"volume={g}dB")
        except Exception:
            pass

        # 2) Noise Reduction
        try:
            if getattr(self, "chk_nr", None) and self.chk_nr.isChecked():
                nr_txt = (self.in_nr.text() or "").strip()
                if nr_txt:
                    val = float(nr_txt.replace(",", "."))
                    if 1 <= val <= 30:
                        filters.append(f"afftdn=nf=-{val:.1f}")
        except Exception:
            pass

        # 3) EQ (combo ±dB)
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

        # 4) Downmix 5.1 → 2.0 se l’utente ha spuntato "Stereo (downmix 2ch)"
        force_st = bool(getattr(self, "chk_force_stereo", None) and self.chk_force_stereo.isChecked())
        need_downmix = bool(force_st and (channels_hint and channels_hint > 2) and not _has_pan(filters))
        if need_downmix:
            pan = C.AUD_PAN_PRESETS.get("stereo_samsung_r450" if is_samsung_stereo else "stereo_tv_generic")
            if pan:
                filters.append(pan)

        # 4.1) Crossfeed "soft" solo se INPUT è già STEREO (non su mono, non su pseudo)
        if is_samsung_stereo and (channels_hint == 2) and (not _has_pan(filters)) and (not pseudo_applied):
            filters.append("pan=stereo|c0=0.92*c0+0.08*c1|c1=0.92*c1+0.08*c0")

        # 5) Dialog Boost
        try:
            if getattr(self, "chk_dialog_boost", None) and self.chk_dialog_boost.isChecked():
                stereo_out = self._effective_output_is_stereo(channels_hint)
                if (not stereo_out) and (channels_hint and channels_hint >= 6):
                    filters.append("pan=5.1(side)|FL=c0+0.06*c2|FR=c1+0.06*c2|FC=1.5*c2|LFE=c3|SL=c4|SR=c5")
                else:
                    filters.append("equalizer=f=2000:t=q:w=1.2:g=2")
        except Exception:
            pass

        # 6) Stereo enhancement (se effettivamente 2ch ora)
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

        # 7) Reverb
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

        # 7.5) DynAudNorm
        try:
            if getattr(self, "chk_dyn", None) and self.chk_dyn.isChecked():
                filters.append("dynaudnorm=f=250:g=31:p=0.95:m=50")
        except Exception:
            pass

        # 8) Compressore
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

            dyn_on = bool(getattr(self, "chk_dyn", None) and self.chk_dyn.isChecked())
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

        # 9) Limiter (ultimo). Se NON c'è comp/dyn → piccolo boost prima
        limiter_str = None
        try:
            if getattr(self, "chk_anticlip", None) and self.chk_anticlip.isChecked():
                limiter_str = "alimiter=limit=0.965:attack=12:release=300"
        except Exception:
            pass

        if limiter_str:
            dyn_on = bool(getattr(self, "chk_dyn", None) and self.chk_dyn.isChecked())
            if not comp_str and not dyn_on:
                filters.append("volume=3dB")
            filters.append(limiter_str)

        return filters

    def _current_detected_channels(self) -> int:
        """
        Rileva i canali della sorgente selezionata (traccia corrente).
        Robusto per input interno/esterno.
        """
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

    def _effective_output_is_stereo(self, in_ch: int) -> bool:
        """
        Dice se l’audio *in uscita* è (o sarà) stereo:
          - già mono/stereo in ingresso  → True
          - forzi "Stereo (downmix 2ch)" → True
          - profilo Samsung stereo       → True
          - altrimenti (5.1 senza downmix) → False
        """
        from hevc_gui.core import constants as C

        force_st = bool(getattr(self, "chk_force_stereo", None) and self.chk_force_stereo.isChecked())
        prof = getattr(self, "_soundbar_profile", "none")
        is_samsung_stereo = prof == getattr(C, "PROFILE_SAMSUNG_STEREO_KEY", "samsung_stereo")
        if in_ch <= 2:
            return True
        return bool(force_st or is_samsung_stereo)

    def _refresh_filter_availability(self, *_):
        """
        Abilita/disabilita i controlli in base all'input corrente.
        Su input MONO: profili Samsung e 'Stereo (downmix 2ch)' vengono spenti e disabilitati.
        """
        try:
            in_ch = self._current_detected_channels()
            stereo_out = self._effective_output_is_stereo(in_ch)

            # GUARD MONO: su input mono spegni/disable Samsung + downmix 2ch
            guard_mono = in_ch == 1

            sb_st = getattr(self, "chk_sb_stereo", None)  # "Samsung — Stereo"
            sb_51 = getattr(self, "chk_sb_51", None)  # "Samsung — 5.1 AC-3"
            force_st = getattr(self, "chk_force_stereo", None)  # "Stereo (downmix 2ch)"

            if guard_mono:
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
                for w in (sb_st, sb_51, force_st):
                    if w is not None:
                        try:
                            w.setEnabled(True)
                        except Exception:
                            pass

            # --- Stereo Enhancer: attivo solo quando l'uscita è stereo ---
            if getattr(self, "cmb_stereo", None):
                self.cmb_stereo.setEnabled(stereo_out)
                tip = "Attivo solo quando l’uscita è stereo." if not stereo_out else "Enhancer stereo."
                self.cmb_stereo.setToolTip(tip)

            # --- Aggiorna label "Pan preset" se presente ---
            if getattr(self, "lbl_pan_preset", None):
                from hevc_gui.core import constants as C

                prof = getattr(self, "_soundbar_profile", "none")
                if in_ch > 2 and stereo_out:
                    preset = "Samsung R450" if prof == getattr(C, "PROFILE_SAMSUNG_STEREO_KEY", "samsung_stereo") else "TV generico"
                    self.lbl_pan_preset.setText(f"Pan preset: {preset} (downmix 5.1→2.0)")
                else:
                    self.lbl_pan_preset.setText("Pan preset: — (nessun downmix)")
        except Exception:
            pass

        self._update_pan_preset_label()

    def _active_pan_preset_key(self) -> str | None:
        """
        Usa i CONTROLLI REALI di questa finestra:
          - 'samsung'  → quando è attivo il profilo 'Samsung — Stereo (TV J + HW-R450)'
          - 'generic'  → quando è spuntato "Stereo (downmix 2ch)" e l'input ha >2 canali
          - None       → altrimenti
        """
        # Profilo impostato da _wire_doubleclick_shortcuts()
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
        """
        Se input è stereo e il preset attivo è 'Samsung', applica un crossfeed leggero.
        Altrimenti non forza nulla.
        """
        key = getattr(self, "_active_pan_preset_key", lambda: None)()
        if nch == 2 and key == "samsung":
            # crossfeed leggero L<->R
            return "pan=stereo|c0=0.92*c0+0.08*c1|c1=0.92*c1+0.08*c0"
        return None

    def _update_pan_placeholder(self, nch: int, forced: bool = False) -> None:
        """
        Aggiorna l’etichetta “Pan preset”:
          - verde = downmix attivo (input > 2 canali)
          - rosso = crossfeed forzato (stereo + preset Samsung)
          - default = nessun pan
        Cerca la QLabel sia per objectName 'lbl_pan_preset' sia per testo 'Pan preset'.
        """
        # 1) trova la QLabel
        lbl = getattr(self, "lbl_pan_preset", None)
        if lbl is None:
            from PyQt5.QtWidgets import QLabel

            for w in self.findChildren(QLabel):
                try:
                    t = (w.text() or "").lower()
                    if "pan preset" in t:
                        lbl = w
                        break
                except Exception:
                    pass
        if lbl is None:
            return  # non c’è nessuna label in questa GUI: esci silenziosamente

        # 2) calcola stato in base al flag 'forced' e ai canali
        key = getattr(self, "_active_pan_preset_key", lambda: None)()

        if forced:  # forzato su stereo (Samsung)
            lbl.setText("Pan preset: Samsung (crossfeed)")
            lbl.setStyleSheet("color: #e11d48;")  # rosso
            return

        if nch > 2 and key:
            lbl.setText("Pan preset: downmix attivo")
            lbl.setStyleSheet("color: #10b981;")  # verde
        else:
            lbl.setText("Pan preset: — (nessun downmix)")
            lbl.setStyleSheet("")

    def _current_input_channels_hint(self) -> int:
        """
        Ritorna una stima dei canali della traccia selezionata (per la label).
        Non influenza l'encode: è solo per debug/UX.
        """
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
        # stato attuale canali in ingresso (hint) e preset scelto
        nch = self._current_input_channels_hint()
        key = self._active_pan_preset_key()

        # forziamo il pan SOLO se profilo "Samsung" ed ingresso stereo
        forced = nch == 2 and key == "samsung"

        # delega alla routine già esistente che colora placeholder:
        # - verde se downmix (nch>2)
        # - rosso se pan forzato su stereo
        # - grigio altrimenti
        self._update_pan_placeholder(nch, forced)

    def _connect_pan_preset_signals(self):
        """
        Aggiorna la label quando cambia qualcosa di rilevante.
        Nota: i due checkbox profilo soundbar (chk_sb_stereo/chk_sb_51) sono
        creati in _wire_doubleclick_shortcuts(); se esistono li connettiamo.
        """
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

    def current_opts(self) -> list[str]:
        """
        Ritorna una bozza di opzioni audio coerente con la GUI per mostrare/esportare
        un comando d’esempio (DEMO). Riflette la stessa logica di add_seg():
          - MONO + 'Mantieni MONO' → AAC 1.0 @ 96k (se combo br = 'Nessuno')
          - STEREO (anche upmix da mono) → AAC 2.0 @ max(originale, 128k) (se combo br = 'Nessuno')
          - Samsung 5.1 reale → AC-3 5.1 @ 48kHz @ 448k (se combo br = 'Nessuno')
        """

        # niente demo per audio esterno o se manca il file
        if self.audio_externo or not self.file:
            return []

        data = self.cmb_track.currentData()
        if not isinstance(data, (tuple, list)) or len(data) < 3:
            return []
        idx, lang, br = data
        if idx < 0 or lang is None:
            return []

        # canali di ingresso per comporre la catena coerente
        detected_ch = 2
        sidx = int(str(idx).split(":")[-1])
        try:
            from hevc_gui.core.ffprobe_utils import probe_audio_stream

            info = probe_audio_stream(str(self.file), stream_index=sidx) or {}
            detected_ch = int(info.get("channels") or 2)
        except Exception:
            pass

        # catena filtri reale (include pseudo-stereo da mono se 'Mantieni MONO' è OFF)
        filters = self._build_filters_chain_from_ui(for_preview=False, channels_hint=detected_ch)
        af_chain = ",".join(filters) if filters else None

        # stato profili / stereo downmix
        prof = getattr(self, "_soundbar_profile", "none")
        force_stereo = bool(getattr(self, "chk_force_stereo", None) and self.chk_force_stereo.isChecked())
        keep_mono = bool(getattr(self, "chk_keep_mono", None) and self.chk_keep_mono.isChecked())
        wants_51 = (prof == "samsung_5_1_ac3") and (not force_stereo)

        # sample rate dalla combo (se numerico)
        sr = self.cmb_sr.currentText() if getattr(self, "cmb_sr", None) else "Nessuno"
        ar = int(sr) if (sr and sr.isdigit()) else None

        # bitrate scelto dall'utente?
        user_br_txt = None
        try:
            ct = (self.cmb_br.currentText() or "").strip()
            if ct and ct.lower() != "nessuno":
                user_br_txt = ct
        except Exception:
            pass

        # bitrate originale (se noto)
        def _parse_kbps(s: str | None) -> int | None:
            if not s:
                return None
            digs = "".join(ch for ch in str(s).lower() if ch.isdigit())
            return int(digs) if digs else None

        orig_br_txt = self._orig_bitrates.get(idx, None)
        if not orig_br_txt:
            try:
                orig_br_txt = self._probe_audio_bitrate_label(str(self.file), sidx)
            except Exception:
                orig_br_txt = None
        orig_kbps = _parse_kbps(orig_br_txt)

        # codec/canali/bitrate (demo = stessa logica di add_seg)
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

        # title coerente coi flag
        try:
            title = self._fmt_audio_title_from_flags(lang=lang, codec=codec, ac=ac, ar=ar, br=br_eff)
        except Exception:
            from hevc_gui.core import constants as C

            parts = [C.LANGUAGE_NAMES.get(lang, lang)]
            parts.append("AC-3 5.1" if (codec == "ac3" and ac == 6) else f"AAC {ac}ch")
            if ar:
                parts.append(f"{ar // 1000} kHz")
            if br_eff:
                parts.append(str(br_eff))
            title = " • ".join(parts)

        # costruzione segmento demo (niente -i qui: è solo “opts”)
        tag = len(self.batch.items)
        seg: list[str] = [
            "-map",
            f"0:a:{idx}",
            f"-metadata:s:a:{tag}",
            f"title={title}",
            f"-c:a:{tag}",
            codec,
            f"-ac:{tag}",
            str(ac),
        ]
        if br_eff:
            seg += [f"-b:a:{tag}", str(br_eff)]
        if ar:
            seg += [f"-ar:{tag}", str(ar)]
        if af_chain:
            seg += ["-af", af_chain]

        return seg

    @pyqtSlot(int)
    def _on_track_changed(self, combo_idx: int):
        data = self.cmb_track.itemData(combo_idx)
        if not data:
            self.btn_add.setEnabled(False)
            return

        idx, lang, br = data
        if idx < 0:
            self.btn_add.setEnabled(False)
            return

        # Se manca la lingua, chiedila; bitrate: prendi l’originale se disponibile
        if lang is None:
            dlg = TagDialog(self)
            if dlg.exec_() != QDialog.Accepted:
                self.cmb_track.setCurrentIndex(0)
                return
            lang = dlg.selected()
            br = self._orig_bitrates.get(idx, "Nessuno")

        label = self._fmt_track_label(idx, lang, br)
        self.cmb_track.setItemText(combo_idx, label)
        self.cmb_track.setItemData(combo_idx, (idx, lang, br))
        self.btn_add.setEnabled(True)

    @pyqtSlot(str)
    def _update_track_title(self, new_br: str):
        combo_idx = self.cmb_track.currentIndex()
        data = self.cmb_track.itemData(combo_idx)
        if not data:
            return

        idx, lang, _ = data
        if idx < 0:
            return

        # Se l'utente mette "Nessuno", usa il bitrate originale (se esiste)
        br = new_br if new_br != "Nessuno" else self._orig_bitrates.get(idx, "Nessuno")

        label = self._fmt_track_label(idx, lang, br)
        self.cmb_track.setItemText(combo_idx, label)
        self.cmb_track.setItemData(combo_idx, (idx, lang, new_br))

    @pyqtSlot()
    def make_preview(self):
        """Entry point unico del Preview (usato da bottoni/azioni/UI)."""
        import traceback

        try:
            print("[UI] make_preview() chiamata → run_preview(self)", flush=True)
            run_preview(self)
            print("[UI] make_preview() OK (run_preview ha terminato)", flush=True)
        except Exception as e:
            print("[UI][ERRORE] make_preview():", e, flush=True)
            print(traceback.format_exc(), flush=True)

    @pyqtSlot()
    def finish(self):
        """
        Chiude il dialog restituendo il batch dei comandi.
        Se in modalità interna e non ci sono tracce aggiunte, chiede conferma UNA sola volta.
        """
        # --- ESTERNA ---
        if self.audio_externo:
            if not self.external_audio_file:
                QMessageBox.warning(self, "Errore", "Nessuna traccia esterna caricata.")
                return
            if not self.batch.items:
                seg = ["-i", self.external_audio_file, "-map", "0:a", "-c:a", "copy"]
                if self.external_audio_lang:
                    seg += ["-metadata:s:a:0", f"language={self.external_audio_lang}"]
                self.batch.add(seg)
            for i, seg in enumerate(self.batch.items):
                if seg[0] != "-i":
                    self.batch.items[i] = ["-i", str(self.external_audio_file)] + seg

            # Imposto il flag prima di accept()
            self._closing_via_finish = True
            self.batch.flush()
            self.accept()
            return

        # --- INTERNA ---
        if not self.batch.items:
            # metto subito il flag, così closeEvent non ridomanda
            self._closing_via_finish = True

            reply = QMessageBox.question(
                self,
                "Nessuna traccia",
                "Non hai aggiunto tracce audio.\nChiudere comunque?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                # se NO: annullo il flag e non chiudo
                self._closing_via_finish = False
                return

        # Se qui ho segmenti o l’utente ha confermato, preparo il batch
        for i, seg in enumerate(self.batch.items):
            if seg[0] != "-i":
                self.batch.items[i] = ["-i", str(self.file)] + seg

        # Finalizzo
        self._closing_via_finish = True
        self.batch.flush()
        self.accept()

    def _build_audio_filters(self) -> list[str]:
        """
        Costruisce la catena -af **coerente con la GUI** delegando alla funzione ufficiale
        (niente fallback, niente aresample/dynaudnorm automatici).
        """
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
        Ripristina tutti i controlli ai valori di default,
        incluso deselezionare 'Tratta come muto'.
        Mantiene self.file e il path mostrato; ripopola la combo tracce dal file.
        """
        # 1) Torno a modalità normale (deseleziono la checkbox) e stato esterno OFF
        if getattr(self, "chk_force_mute", None):
            self.chk_force_mute.setChecked(False)
        self.audio_externo = False

        # 2) Ripristino la combo delle tracce in base al file caricato (se presente)
        self.cmb_track.clear()
        self.cmb_track.addItem("Seleziona traccia…", (-1, None, None))
        if self.file:
            try:
                tracks = list(audio_tracks_with_title(str(self.file)))
            except Exception:
                tracks = []
            if tracks:
                self._orig_bitrates.clear()
                for pos, (idx_raw, title) in enumerate(tracks):
                    a_idx = self._norm_audio_index(idx_raw, pos)
                    br_lbl = self._probe_audio_bitrate_label(str(self.file), a_idx)
                    if br_lbl:
                        self._orig_bitrates[a_idx] = br_lbl
                    label = f"Traccia {a_idx}" + (f" – {title}" if title else "")
                    self.cmb_track.addItem(label, (a_idx, None, br_lbl or "Nessuno"))
                self.cmb_track.setEnabled(True)
            else:
                self.cmb_track.setEnabled(False)
            # ri-mostra il path del file (lo manteniamo)
            try:
                self.path.setText(str(self.file))
            except Exception:
                pass
        else:
            self.cmb_track.setEnabled(False)

        # 3) Svuoto batch e lista comandi (riparto pulito)
        try:
            self.batch.items.clear()
        except Exception:
            pass
        try:
            self.list.clear()
        except Exception:
            pass

        # 4) Riporto tutti i controlli ai valori iniziali
        for safe in (
            lambda: self.cmb_br.setCurrentText("Nessuno"),
            lambda: self.cmb_sr.setCurrentText("Nessuno"),
            lambda: self.cmb_gain.setCurrentText("0"),
            lambda: self.chk_nr.setChecked(False),
            lambda: (
                self.in_nr.clear(),
                self.in_nr.setEnabled(False),
                self.in_nr.setStyleSheet(""),
            ),
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

        # 5) Nascondi log e progress bar (se esistono)
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


if __name__ == "__main__":
    import argparse
    import sys
    import os
    from PyQt5.QtWidgets import QApplication

    parser = argparse.ArgumentParser(description="Estrattore Audio standalone (HEVC-GUI)")
    parser.add_argument("--audio", help="File audio ESTERNO (mp3/flac/aac/ac3...) da usare come sorgente")
    parser.add_argument("--lang", default="und", help="Lingua traccia esterna (es. ITA, ENG, und)")
    parser.add_argument("--force-stereo", action="store_true", help="Spunta 'Stereo (downmix 2ch)' (utile per input mono)")
    parser.add_argument("--headless", action="store_true", help="Non mostra la finestra: genera JSON e stampa")
    parser.add_argument("--show-cmd", action="store_true", help="Mostra la text-box del comando/preview")
    args = parser.parse_args()

    if args.show_cmd:
        os.environ["HEVC_PREVIEW_SHOW_CMD_BOX"] = "1"

    app = QApplication(sys.argv)
    # niente file video: lavoriamo in “audio esterno”
    dlg = AudioConverter(auto="", parent=None)

    if args.audio:
        # entra in modalità "audio esterno" e carica il file
        dlg.chk_force_mute.setChecked(True)
        dlg.load_external_audio(args.audio)
        dlg.external_audio_lang = args.lang
        if args.force_stereo and hasattr(dlg, "chk_force_stereo"):
            dlg.chk_force_stereo.setChecked(True)  # per test pseudo-stereo su input mono

    if args.headless:
        # aggiungi traccia e STAMPA SUBITO il JSON (batch.flush() in finish())
        dlg.add_seg()
        dlg.finish()
        sys.exit(0)

    dlg.show()
    app.exec_()
