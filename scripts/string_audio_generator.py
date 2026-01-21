#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ruff: noqa: E402
"""
string_audio_generator.py — Audio-Extractor + Preview per HEVC-GUI

Funzioni principali:
- Dialog "String Audio Generator" richiamato da HEVC-GUI per:
  • scegliere tracce audio interne o un file audio esterno;
  • applicare filtri (EQ, NR, DynAudNorm, Dialog Boost, Reverb, Stereo Enh, Compr, Limiter);
  • selezionare un profilo audio (Stereo, Samsung Stereo, Samsung 5.1 AC-3);
  • costruire una batch di comandi ffmpeg (solo segmenti audio) che HEVC-GUI userà
    nell’encode finale.

Questa versione:
- NON chiede più la lingua con popup: usa SOLO la combo cmb_lang;
- memorizza la lingua per-traccia (itemData della combo tracce);
- la combo lingua modifica SOLO la traccia selezionata, non tutte in automatico.
"""

from __future__ import annotations
import sys
from pathlib import Path
from hevc_gui.i18n import apply_i18n

# assicura import del package hevc_gui anche se avviato da scripts/
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from hevc_gui.i18n import L, init_qt_i18n, get_lang


def _t(it: str, en: str) -> str:
    """Fallback i18n:
    - se lingua EN: prova L(it); se non traduce, usa en
    - altrimenti: ritorna it
    """
    import os

    # PRIORITÀ: env (quando la GUI madre lancia questo script in inglese)
    lang = (os.environ.get("HEVC_LANG") or "").strip().lower()
    if not lang:
        try:
            lang = (get_lang() or "").strip().lower()
        except Exception:
            lang = ""
    if not lang:
        lang = "it"

    if lang.startswith("en"):
        try:
            tr = L(it)
        except Exception:
            tr = it
        return en if tr == it else tr
    return it


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
from PyQt5.QtCore import Qt, pyqtSlot, QProcess, QTimer, QCoreApplication
from PyQt5.QtGui import QFontMetrics


# --- UI helper: avoid truncated combobox contents ---
def _tune_combo(cmb, min_chars=10, max_items=30):
    try:
        from PyQt5.QtWidgets import QComboBox

        cmb.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        cmb.setMinimumContentsLength(min_chars)
        cmb.setMaxVisibleItems(max_items)
    except Exception:
        pass
    try:
        w = cmb.view().sizeHintForColumn(0) + 40
        if w > 0:
            cmb.view().setMinimumWidth(w)
    except Exception:
        pass


def _tr_sag(text: str) -> str:
    """Qt translate for scripts.string_audio_generator context."""
    return QCoreApplication.translate("scripts.string_audio_generator", text)


from hevc_gui.core import constants as C
from hevc_gui.core.audio_helpers import audio_tracks_with_title

try:
    from conversion_thread_external import ConversionThreadExternal
except ModuleNotFoundError:
    from scripts.conversion_thread_external import ConversionThreadExternal

# --- Preview: import robusto (preview oppure scripts.preview) ---
try:
    import preview as _preview_mod
except Exception:
    try:
        from scripts import preview as _preview_mod
    except Exception as _e:
        raise ImportError(f"Impossibile importare il modulo preview: {_e}")


def _ldvd_sidecar_for_media(path: str | Path) -> dict | None:
    """
    Prova a caricare <basename>.ldvdmeta.json accanto al file video/audio.
    Restituisce il dict o None se non trovato/illeggibile.
    """
    try:
        p = Path(path)
        side = p.with_suffix(".ldvdmeta.json")
        if not side.is_file():
            return None
        txt = side.read_text(encoding="utf-8")
        data = json.loads(txt)
        print(f"[AUDIO] Sidecar LDVD per audio: {side}", flush=True)
        return data
    except Exception as e:
        try:
            print(f"[AUDIO] Errore lettura sidecar audio {side}: {e}", flush=True)
        except Exception:
            pass
        return None


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

    def set_video_file(self, video_file: str | None):
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
            # 1) togli il binario
            while opts and opts[0] in (C.FFMPEG_BIN, "ffmpeg"):
                opts.pop(0)
            # 2) togli -y
            if opts and opts[0] == "-y":
                opts.pop(0)
            # 3) togli solo -i <video_originale>
            if video_in:
                i = 0
                while i < len(opts) - 1:
                    if opts[i] == "-i" and opts[i + 1] == video_in:
                        opts.pop(i)
                        opts.pop(i)
                    else:
                        i += 1
            cleaned.append(opts)

        # 4) in modalità audio esterno, rimappa 0:a:X → 1:X
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
    def __init__(self, parent=None, title=None):
        super().__init__(parent)
        if title is None:
            title = L("Preparazione preview")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.resize(520, 140)

        v = QVBoxLayout(self)
        self.lbl_file = QLabel(L(""), self)
        self.lbl_file.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl = QLabel(L("Inizializzazione…"), self)
        self.bar = QProgressBar(self)
        self.bar.setRange(0, 0)

        hb = QHBoxLayout()
        self.btn_cancel = QPushButton(L("Annulla"))
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
        self.lbl_file.setText(L("File: {0}").format(display_name))
        if full_path:
            self.lbl_file.setToolTip(full_path)
        if total_secs and total_secs > 0:
            self.bar.setRange(0, 100)
            self.bar.setValue(0)
            self.lbl.setText(L("Elaborazione… 0% (00:00:00 / {0})").format(self._hms(total_secs)))
        else:
            self.bar.setRange(0, 0)
            self.lbl.setText(L("Elaborazione…"))

        proc.readyReadStandardError.connect(self._on_stderr)
        proc.errorOccurred.connect(lambda e: self.lbl.setText(L("Errore processo: {0}").format(e)))
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
            self.lbl.setText(L("Elaborazione… {0}% ({1} / {2})  •  ETA ~ {3}").format(pct, self._hms(cur), self._hms(tot), self._hms(rem)))
        else:
            self.lbl.setText(L("Elaborazione… {0}").format(self._hms(cur)))

    def _on_finished(self, code, _status):
        if code == 0 and not self._cancelled:
            if self.bar.maximum() == 100:
                self.bar.setValue(100)
                self.lbl.setText(L("Completato."))
            self.accept()
        elif not self._cancelled:
            self.lbl.setText(L("ffmpeg terminato con codice {0}").format(code))
            QTimer.singleShot(1200, self.reject)


# =============================== DIALOG PRINCIPALE ===============================


class AudioConverter(QDialog):
    def __init__(self, auto: str, parent=None):
        super().__init__(parent)

        # finestra
        self.setWindowTitle(L("String Audio Generator"))
        self.resize(560, 700)
        self.setAcceptDrops(True)

        # stato interno
        self.batch = Batch()
        self._closing_via_finish = False
        self.file: Path | None = None
        self._orig_bitrates: dict[int, str] = {}
        self._orig_channels: dict[int, int] = {}

        # cache lingua/sidecar
        self._sidecar_cache = None
        self._sidecar_src: Path | None = None

        self.audio_externo = False
        self.external_audio_file: str | None = None
        self.conv_thread_external: ConversionThreadExternal | None = None
        self.external_audio_duration = 0.0

        # costruzione UI
        self._build_ui()
        apply_i18n(self, ctx="scripts.string_audio_generator")
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
        self.cmb_lang.currentIndexChanged.connect(self._on_lang_changed)

        # caricamento iniziale
        self.load_file(auto)

    # === Helpers lingua (unica fonte UI, ma per-traccia) =======================

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
            ("und", L("Sconosciuta")),
            ("ita", L("Italiano")),
            ("eng", L("Inglese")),
            ("fra", L("Francese")),
            ("deu", L("Tedesco")),
            ("spa", L("Spagnolo")),
        ]

    def _lang_code_from_combo(self) -> str:
        try:
            code = self.cmb_lang.currentData()
            if code:
                return str(code).strip().lower()
        except Exception:
            pass
        return "und"

    def _normalize_lang_code(self, code: str | None) -> str:
        if not code:
            return "und"
        code = str(code).strip()
        # mappa rapida 2→3 lettere
        if len(code) == 2:
            m = {
                "it": "ita",
                "en": "eng",
                "fr": "fra",
                "de": "deu",
                "es": "spa",
            }
            code = m.get(code.lower(), code)
        return code.lower() or "und"

    def _lang_human(self, code: str | None) -> str:
        if not code:
            return "—"
        code = self._normalize_lang_code(code)
        try:
            return (
                C.LANGUAGE_NAMES.get(code, None)
                or C.LANGUAGE_NAMES.get(code.upper(), None)
                or C.LANGUAGE_NAMES.get(code.lower(), None)
                or code
            )
        except Exception:
            return code

    def _set_lang_combo(self, code: str | None):
        """Porta la combo lingua sul codice dato senza scatenare update extra."""
        if not getattr(self, "cmb_lang", None):
            return
        code = self._normalize_lang_code(code)
        try:
            idx = self.cmb_lang.findData(code)
            if idx < 0:
                # prova anche la versione 2-lettere nel caso il dizionario sia strano
                short = code[:2]
                idx = self.cmb_lang.findData(short)
            if idx >= 0:
                self.cmb_lang.blockSignals(True)
                self.cmb_lang.setCurrentIndex(idx)
                self.cmb_lang.blockSignals(False)
        except Exception:
            pass

    def _normalize_lang_code(self, code: str | None) -> str:
        """
        Normalizza un codice lingua in ISO-639-2 (ita, eng, fra, deu, spa, por…)
        partendo da:
          - codici 2 lettere (it, en…)
          - codici 3 lettere (ita, eng…)
          - stringhe tipo 'Italiano', 'English', 'Français', ecc.
        Fallback: 'und'.
        """
        if not code:
            return "und"
        raw = str(code).strip()
        if not raw:
            return "und"

        low = raw.lower().replace("-", "_")

        # Map diretti 3 lettere
        map_3 = {
            "ita": "ita",
            "eng": "eng",
            "fra": "fra",
            "fre": "fra",
            "deu": "deu",
            "ger": "deu",
            "spa": "spa",
            "esp": "spa",
            "por": "por",
        }
        if low in map_3:
            return map_3[low]

        # Map 2 lettere → 3 lettere
        map_2 = {
            "it": "ita",
            "en": "eng",
            "fr": "fra",
            "de": "deu",
            "es": "spa",
            "pt": "por",
        }
        if low in map_2:
            return map_2[low]

        # Stringhe verbali (Italiano, English, Français…)
        if "ital" in low:
            return "ita"
        if "engl" in low or "ingl" in low:
            return "eng"
        if "fran" in low or "français" in low or "francais" in low:
            return "fra"
        if "tedes" in low or "german" in low or "deutsch" in low:
            return "deu"
        if "spagn" in low or "españ" in low or "spanish" in low:
            return "spa"
        if "portug" in low or "portugu" in low:
            return "por"

        # Se è già lungo 3 caratteri, tienilo (minuscolo)
        if len(low) == 3:
            return low

        return "und"

    def _load_sidecar_json(self) -> dict | None:
        """
        (Futuro aggancio con LDVD-Ripper) — se accanto al file esiste
        <basename>.ldvdmeta.json, lo carica una volta e lo cache-a.
        Per ora puoi usarlo solo come base per dedurre lingue/nome flussi.
        """
        if not self.file:
            return None
        try:
            if self._sidecar_src == self.file and isinstance(self._sidecar_cache, dict):
                return self._sidecar_cache
        except Exception:
            pass
        sidecar = self.file.with_suffix(".ldvdmeta.json")
        if not sidecar.exists():
            self._sidecar_cache = None
            self._sidecar_src = self.file
            return None
        try:
            data = json.loads(sidecar.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._sidecar_cache = data
                self._sidecar_src = self.file
                return data
        except Exception:
            self._sidecar_cache = None
            self._sidecar_src = self.file
        return None

    def _detect_lang_from_sidecar(self, a_idx: int) -> str | None:
        meta = self._load_sidecar_json()
        if not meta:
            return None
        try:
            tracks = meta.get("audio") or []
            for t in tracks:
                try:
                    if int(t.get("index", -1)) == int(a_idx):
                        lang = t.get("language") or t.get("lang") or "und"
                        return self._normalize_lang_code(lang)
                except Exception:
                    continue
        except Exception:
            pass
        return None

    def _detect_lang_with_ffprobe(self, path: str, a_idx: int) -> str | None:
        ffprobe = shutil.which("ffprobe") or "ffprobe"
        try:
            cmd = [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                f"a:{int(a_idx)}",
                "-show_entries",
                "stream=tags",
                "-of",
                "json",
                str(path),
            ]
            p = subprocess.run(cmd, capture_output=True, text=True, check=True)
            data = json.loads(p.stdout or "{}")
            ss = data.get("streams") or []
            if not ss:
                return None
            tags = ss[0].get("tags") or {}
            lang = tags.get("language") or tags.get("LANGUAGE")
            if not lang:
                return None
            return self._normalize_lang_code(lang)
        except Exception:
            return None

    def _detect_track_lang(self, path: str, a_idx: int, default: str | None = None) -> str:
        """
        Deduci una lingua plausibile per il flusso:
        - se c'è sidecar LDVD → preferiscilo;
        - altrimenti ffprobe tags.language;
        - fallback: default (combo) → 'und'.
        """
        lang = None
        try:
            # solo per il file "video principale" proviamo il sidecar
            if self.file and Path(path) == self.file:
                lang = self._detect_lang_from_sidecar(a_idx)
        except Exception:
            lang = None
        if not lang:
            lang = self._detect_lang_with_ffprobe(path, a_idx)
        if not lang:
            lang = default or "und"
        return self._normalize_lang_code(lang)

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
            "WIN_H": 700,
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
        lab_in = QLabel(L("Input track:"), path_row)
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
        LW_TRACCIA = fm.horizontalAdvance(L(L("Traccia:")))
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
        self.chk_force_mute = QCheckBox(L("Tratta come muto"), self)
        place(self.chk_force_mute, x, FORCE_MUTE_W, M["H_EDIT"])
        x_btn = x + FORCE_MUTE_W + M["HGAP"] + EXTRA_GAP
        ext_btn_w = max(120, min(W_TRACK - BTN_SHRINK, CANVAS_W - x_btn - 4))
        btn_ext = getattr(self, "btn_load_external_audio", None)
        if not isinstance(btn_ext, QPushButton):
            self.btn_load_external_audio = QPushButton(L("Carica traccia audio esterna"), self)
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
        self.cmb_track.addItem(L("Seleziona traccia…"), (-1, None, None))
        self.cmb_track.setEnabled(False)
        self.cmb_track.setMinimumWidth(W_TRACK)
        self.cmb_track.setMaximumWidth(W_TRACK)
        pairL(L(L("Traccia:")), self.cmb_track, W_TRACK)
        new_line()

        # ---------- R2b: Lingua (combo unica) ----------
        x = M["X0"]
        self.cmb_lang = QComboBox(self)
        for code, name in self._lang_choices():
            self.cmb_lang.addItem(f"{name} ({code})", code)

        _tune_combo(self.cmb_lang, min_chars=18, max_items=30)

        # default: prima prova "und", poi "ita"
        def _select_default_lang():
            idx_und = self.cmb_lang.findData("und")
            if idx_und >= 0:
                self.cmb_lang.setCurrentIndex(idx_und)
                return
            idx_ita = self.cmb_lang.findData("ita")
            if idx_ita >= 0:
                self.cmb_lang.setCurrentIndex(idx_ita)

        _select_default_lang()
        pairL(L("Lingua:"), self.cmb_lang, max(180, int(W_TRACK * 0.55)))
        new_line()

        # ---------- R3: Bit-rate + Sample rate ----------
        x = M["X0"]
        self.cmb_br = QComboBox(self)
        self.cmb_br.addItems(getattr(C, "AUD_BITRATES", ["Nessuno"]))
        _tune_combo(self.cmb_br, min_chars=8, max_items=40)
        pairL(L("Bit-rate:"), self.cmb_br, M["W_MED"])
        self.cmb_sr = QComboBox(self)
        self.cmb_sr.addItems(getattr(C, "AUD_SAMPLE_RATES", ["Nessuno"]))
        _tune_combo(self.cmb_sr, min_chars=8, max_items=40)
        pairL(L("Sample rate (Hz):"), self.cmb_sr, M["W_MED"])
        new_line()

        # ---------- R4: NR + Gain ----------
        x = M["X0"]
        self.chk_nr = lone(QCheckBox(L("Noise-Reduction"), self), 170)
        self.in_nr = QLineEdit(self)
        self.in_nr.setPlaceholderText(L("0–30 dB"))
        self.in_nr.setEnabled(False)
        self.chk_nr.toggled.connect(self.in_nr.setEnabled)
        pairL(L("Denoise nr:"), self.in_nr, M["W_NUM"])
        self.cmb_gain = QComboBox(self)
        self.cmb_gain.addItems(getattr(C, "AUD_GAIN_RANGE", ["0"]))
        self.cmb_gain.setCurrentText("0")
        pairL(L("Gain (dB):"), self.cmb_gain, M["W_NUM"])
        new_line()

        # ---------- R5: EQ ----------
        x = M["X0"]
        self.cmb_eq_bass = QComboBox(self)
        self.cmb_eq_bass.addItems(getattr(C, "AUD_EQ_DB_CHOICES", ["0"]))
        self.cmb_eq_bass.setCurrentText("0")
        pairL(L("Bass (dB):"), self.cmb_eq_bass, M["W_NUM"])
        self.cmb_eq_mid = QComboBox(self)
        self.cmb_eq_mid.addItems(getattr(C, "AUD_EQ_DB_CHOICES", ["0"]))
        self.cmb_eq_mid.setCurrentText("0")
        pairL(L("Mid (dB):"), self.cmb_eq_mid, M["W_NUM"])
        self.cmb_eq_treb = QComboBox(self)
        self.cmb_eq_treb.addItems(getattr(C, "AUD_EQ_DB_CHOICES", ["0"]))
        self.cmb_eq_treb.setCurrentText("0")
        pairL(L("High (dB):"), self.cmb_eq_treb, M["W_NUM"])
        new_line()

        # ---------- R6: Reverb / Stereo Enh / Compr ----------
        x = M["X0"]
        self.cmb_rev = QComboBox(self)
        self.cmb_rev.addItems(getattr(C, "AUD_REVERB_LEVELS", ["Nessuno"]))
        pairL(L("Reverb:"), self.cmb_rev, M["W_FX"])
        self.cmb_stereo = QComboBox(self)
        self.cmb_stereo.addItem(L("Nessuno"))
        try:
            self.cmb_stereo.addItems(list(getattr(C, "AUD_STEREO_ENHANCERS", {}).keys()))
        except Exception:
            pass
        pairL(L("Stereo Enh:"), self.cmb_stereo, M["W_FX"])
        self.cmb_comp_soft = QComboBox(self)
        # i18n: testo localizzato ma chiave stabile in itemData (logica non dipende dal testo)
        self.cmb_comp_soft.clear()
        self.cmb_comp_soft.addItem(_t("Nessuno", "None"), "none")
        self.cmb_comp_soft.addItem(_t("Leggero", "Light"), "light")
        self.cmb_comp_soft.addItem(_t("Medio", "Medium"), "medium")
        self.cmb_comp_soft.addItem(_t("Forte", "Strong"), "strong")

        self.cmb_comp_soft.setCurrentText("Nessuno")
        pairL(L("Compr."), self.cmb_comp_soft, M["W_FX"])
        new_line()

        # ---------- R7: Auto-loudness + Dialog Boost ----------
        x = M["X0"]
        self.chk_dyn = lone(QCheckBox(L("Auto-loudness (DynAudNorm)"), self))
        old_gap = M["HGAP"]
        M["HGAP"] = 6
        self.chk_dialog_boost = lone(QCheckBox(L("Dialog Boost (+2 dB @ 2 kHz)"), self))
        M["HGAP"] = old_gap
        new_line()

        # ---------- R8 ----------
        x = M["X0"]
        self.chk_keep_mono = lone(QCheckBox(L("Mantieni MONO se input mono (AAC 1.0)"), self), 310)
        self.chk_anticlip = lone(QCheckBox(L("Evita clipping"), self), 170)
        new_line()

        # ---------- R9: Preview ----------
        x = M["X0"]
        prev_lab = QLabel(L("Preview:"), self)
        w_prev_lab = prev_lab.sizeHint().width()
        place(prev_lab, x, w_prev_lab)
        x += w_prev_lab + M["HGAP"]

        self.te_prev_start = QTimeEdit(self)
        self.te_prev_start.setDisplayFormat("HH:mm:ss")
        self.te_prev_start.setAccelerated(True)
        self.te_prev_start.setButtonSymbols(QAbstractSpinBox.UpDownArrows)
        pairL(L("Start:"), self.te_prev_start, M["W_TIME"])

        self.cmb_prev = QComboBox(self)
        for seconds, label in getattr(C, "AUD_PREVIEW_OPTIONS", [(60, "1 min"), (300, "5 min"), (0, "∞")]):
            self.cmb_prev.addItem(label, seconds)
        pairL(L("Durata:"), self.cmb_prev, M["W_DUR"])

        self.cmb_prev.ensurePolished()
        self.cmb_prev.adjustSize()
        combo_h = max(self.cmb_prev.height(), M["H_EDIT"])
        BTN_H_FIX = 2
        BTN_Y_FIX = -1
        self.btn_prev = QPushButton(L("Preview"), self)
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
        self.chk_force_stereo = lone(QCheckBox(L("Stereo (downmix 2ch)"), self), 220)
        self.chk_force_stereo.setObjectName("chk_downmix")
        new_line()

        # ---------- R12: Profilo soundbar ----------
        lbl_sb = QLabel(L("Profilo soundbar:"), self)
        lbl_sb.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        place(lbl_sb, M["X0"], CANVAS_W - 2 * M["X0"])
        new_line()

        # ---------- R13: Samsung ----------
        x = M["X0"]
        self.chk_sb_stereo = QCheckBox(L("Samsung — Stereo (TV J + HW-R450)"), self)
        self.chk_sb_stereo.setObjectName("chk_sb_stereo")
        lone(self.chk_sb_stereo)
        self.chk_sb_51 = QCheckBox(L("Samsung — 5.1 AC-3 (48 kHz)"), self)
        self.chk_sb_51.setObjectName("chk_sb_51")
        lone(self.chk_sb_51)
        self._soundbar_injected = True
        new_line()

        # ---------- R14: Footer ----------
        self.lbl_pan_preset = QLabel(_t("Pan preset: — (nessun downmix)", "Preset: — (no downmix)"), self)
        place(self.lbl_pan_preset, M["X0"], CANVAS_W - 2 * M["X0"])

        # Vai a riga successiva per mettere i pulsanti separati
        new_line()

        self.btn_add = QPushButton(L("Agg. traccia"), self)
        self.btn_cancel = QPushButton(L("Annulla"), self)
        self.btn_ok = QPushButton(L("OK / Esci"), self)
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

    # ──────────────────────────── Drag & Drop ────────────────────────────────

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

    # ──────────────────────────── EQ helper ──────────────────────────────────

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

    # ──────────────────────────── Preview wiring ─────────────────────────────

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

    # ──────────────────────── Doppio click / layout helper ───────────────────
    # (INVARIATO rispetto alla tua versione, lasciato intatto per compatibilità)

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

            row_label = QLabel(L("Profilo soundbar"), container)
            row_box = QWidget(container)
            vb = QVBoxLayout(row_box)
            vb.setContentsMargins(0, 0, 0, 0)
            vb.setSpacing(4)
            hb = QHBoxLayout()
            hb.setContentsMargins(0, 0, 0, 0)
            hb.setSpacing(6)

            cb_st = QCheckBox(L("Samsung — Stereo (TV J + HW-R450)"), row_box)
            cb_51 = QCheckBox(L("Samsung — 5.1 AC-3 (48 kHz)"), row_box)
            cb_st.setObjectName("chk_sb_stereo")
            cb_51.setObjectName("chk_sb_51")
            hb.addWidget(cb_st)
            hb.addWidget(cb_51)
            hb.addStretch(1)
            vb.addLayout(hb)

            if not getattr(self, "lbl_pan_preset", None):
                self.lbl_pan_preset = QLabel(
                    _t("Pan preset: — (input stereo/mono o profili spenti)", "Preset: — (stereo/mono input or profiles off)"), row_box
                )
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

    # ────────────────────── Sidecar LDVD → lingua per traccia ─────────────────

    def _audio_lang_from_sidecar(self, sidecar: dict, audio_index: int, pos: int) -> str | None:
        """
        Ricava la lingua da sidecar LDVD per una traccia audio.

        audio_index = indice audio "logico" 0..N-1 (quello usato in GUI e in -map 0:a:N)
        pos         = posizione nella lista tracce (0,1,2,...) usata come fallback.

        Strategia:
          1) Prova a matchare 'index' / 'audio_index' / 'track_index' ecc. == audio_index
             (NON guarda più 'stream_index' in questa fase).
          2) Se non trova nulla, usa il fallback di posizione (pos).
        """
        try:
            audio_list = sidecar.get("audio") or sidecar.get("audios") or []
        except Exception:
            audio_list = []

        if not audio_list:
            return None

        # 1) Match esplicito per indice logico (0..N-1)
        for a in audio_list:
            if not isinstance(a, dict):
                continue
            for key in ("index", "audio_index", "a_index", "track_index", "track"):
                val = a.get(key)
                if val is None:
                    continue
                try:
                    if int(val) == int(audio_index):
                        lang = (a.get("language") or a.get("lang") or "").strip()
                        if lang:
                            return self._normalize_lang_code(lang)
                except Exception:
                    continue

        # 2) Fallback: usa semplicemente l'ordine (pos)
        if 0 <= pos < len(audio_list):
            a = audio_list[pos]
            if isinstance(a, dict):
                lang = (a.get("language") or a.get("lang") or "").strip()
                if lang:
                    return self._normalize_lang_code(lang)

        return None

    def _sidecar_get_audio_entry(self, sidecar: dict, audio_index: int, pos: int) -> dict | None:
        """
        Restituisce il dizionario dell'audio corrispondente da sidecar["audio"].

        audio_index = indice audio logico 0..N-1 (quello usato in -map 0:a:N).
        pos         = posizione nel loop (0,1,2,...) usata come fallback.

        Strategia:
          1) Se esiste un campo 'index' / 'audio_index' / ... uguale ad audio_index → usa quello.
          2) Altrimenti fallback su sidecar["audio"][pos].
        """
        try:
            audio_list = sidecar.get("audio") or sidecar.get("audios") or []
        except Exception:
            return None

        if not audio_list:
            return None

        # 1) match esplicito per indice logico 0..N-1
        for a in audio_list:
            if not isinstance(a, dict):
                continue
            for key in ("index", "audio_index", "a_index", "track_index", "track"):
                val = a.get(key)
                if val is None:
                    continue
                try:
                    if int(val) == int(audio_index):
                        return a
                except Exception:
                    continue

        # 2) fallback: usa la posizione nel vettore
        if 0 <= pos < len(audio_list):
            a = audio_list[pos]
            if isinstance(a, dict):
                return a

        return None

    def _fmt_track_label(self, idx: int, lang: str | None, br: str) -> str:
        """
        Costruisce l'etichetta “Traccia X - Italiano 384k …”.
        Ora usa *davvero* il parametro lang, con fallback alla combo globale.
        """
        lang_code = (lang or "").strip().lower()
        if not lang_code or lang_code == "und":
            lang_code = self._lang_code_from_combo()

        lang_full = self._lang_human(lang_code)

        ch = self._orig_channels.get(idx)
        if ch is None:
            try:
                ch = self._probe_audio_channels(str(self.file), idx)
                if ch:
                    self._orig_channels[idx] = ch
            except Exception:
                ch = None

        badge = ""
        try:
            if ch is not None:
                badge = self._badge_from_channels(int(ch))
        except Exception:
            pass

        parts = []
        if badge:
            parts.append(f"[{badge}]")
        parts.append(f"{L('Traccia')} {idx}")
        if lang_full and lang_full != "—":
            parts.append(f"- {lang_full}")
        if br:
            parts.append(f"- {(_t('Nessuno', 'None') if str(br) == 'Nessuno' else br)}")

        return " ".join(parts)

    def _badge_from_channels(self, ch: int) -> str:
        """
        Ritorna un piccolo badge testuale in base al numero di canali:
          - 'M'  → mono
          - 'S'  → stereo
          - 'MC' → multicanale (>2)
        ATTENZIONE: _fmt_track_label aggiunge già le parentesi quadre.
        """
        if ch <= 1:
            return "M"
        elif ch == 2:
            return "S"
        else:
            return "MC"

    def _probe_audio_channels(self, path: str, track_idx: int) -> int:
        """
        Determina il numero di canali decodificando ~1 secondo della traccia 0:a:<track_idx>
        in WAV e leggendo l'header. Usa un WAV "vecchio stile" (no WAVEFORMATEXTENSIBLE)
        così il modulo wave di Python non esplode con "unknown format: 65534".

        Ritorna:
            numero di canali (>=1) oppure 0 se fallisce.
        """
        import os
        import shutil
        import subprocess
        import tempfile
        import wave

        # Prova ad usare il binario configurato in constants, altrimenti ffmpeg di sistema
        try:
            ffmpeg_bin = shutil.which(getattr(C, "FFMPEG_BIN", "")) or shutil.which("ffmpeg") or "ffmpeg"
        except Exception:
            ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"

        # Preferisci /dev/shm se esiste ed è scrivibile, altrimenti tmp di sistema
        base_tmp = "/dev/shm"
        if not os.path.isdir(base_tmp) or not os.access(base_tmp, os.W_OK):
            base_tmp = tempfile.gettempdir()

        fd, tmp_path = tempfile.mkdtemp(prefix="hevc_chprobe_", dir=base_tmp), None
        # uso un file vero, non solo la dir
        tmp_path = os.path.join(fd, "probe.wav")

        try:
            cmd = [
                ffmpeg_bin,
                "-hide_banner",
                "-nostdin",
                "-loglevel",
                "error",
                "-i",
                path,
                "-map",
                f"0:a:{track_idx}",
                "-vn",
                "-sn",
                "-dn",
                "-c:a",
                "pcm_s16le",
                "-t",
                "1",
                "-f",
                "wav",
                "-write_channel_mask",
                "0",  # <-- evita WAVEFORMATEXTENSIBLE (tag 65534)
                "-y",
                tmp_path,
            ]
            subprocess.run(cmd, check=True)

            with wave.open(tmp_path, "rb") as wf:
                ch = wf.getnchannels()

            ch_int = int(ch or 0)
            print(f"[AUDIO] _probe_audio_channels: 0:a:{track_idx} → {ch_int} canali", flush=True)
            return ch_int
        except Exception as exc:
            print(f"[AUDIO] _probe_audio_channels fallita per 0:a:{track_idx}: {exc}", flush=True)
            return 0
        finally:
            try:
                if tmp_path and os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except Exception:
                pass
            try:
                if fd and os.path.isdir(fd):
                    os.rmdir(fd)
            except Exception:
                pass

    def _probe_stream_language(self, path: str, a_idx: int) -> str:
        """
        Usa ffprobe per recuperare il tag 'language' della traccia audio a:a_idx.
        Ritorna un codice normalizzato (ita/eng/…) o 'und'.
        """
        ffprobe = shutil.which("ffprobe") or "ffprobe"
        try:
            cmd = [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                f"a:{int(a_idx)}",
                "-show_entries",
                "stream_tags=language,LANGUAGE",
                "-of",
                "json",
                str(path),
            ]
            p = subprocess.run(cmd, capture_output=True, text=True, check=True)
            data = json.loads(p.stdout or "{}")
            streams = data.get("streams") or []
            if not streams:
                return "und"
            tags = streams[0].get("tags") or {}
            lang_raw = tags.get("language") or tags.get("LANGUAGE")
            return self._normalize_lang_code(lang_raw)
        except Exception:
            return "und"

    # ──────────────────────────── Caricamento file interno ────────────────────

    @pyqtSlot(str)
    def load_file(self, path: str) -> None:
        """
        Carica il sorgente e popola la combo delle tracce audio.

        Strategia aggiornata (DVD + sidecar):

          • Se esiste <video>.ldvdmeta.json con "audio": [...]
              - il sidecar decide ordine e lingua;
              - ffprobe serve solo per codec/layout/bitrate se mancanti;
              - i canali vengono SEMPRE misurati via _probe_audio_channels.

          • Se NON c'è sidecar:
              - usa solo ffprobe.
        """
        from pathlib import Path
        import json
        import subprocess
        import shutil

        # ───────── Stato base / file corrente ─────────
        self.file = Path(path)
        self._input_path = str(self.file)
        self.audio_externo = False
        self.external_audio_file = None

        try:
            self.path.setText(str(self.file))
        except Exception:
            pass

        try:
            self.batch.set_video_file(str(self.file))
        except Exception:
            pass

        # cache bitrate/canali azzerata
        self._orig_bitrates.clear()
        self._orig_channels.clear()

        # reset combo tracce
        self.cmb_track.blockSignals(True)
        self.cmb_track.clear()
        self.cmb_track.addItem(L("Seleziona traccia…"), (-1, None, None))
        self.cmb_track.setEnabled(False)
        self.btn_add.setEnabled(False)

        ui_default_lang = self._lang_code_from_combo() or "und"

        # ───────── Sidecar LDVD (se esiste) ─────────
        sidecar = self._load_sidecar_json()
        side_audio = []
        side_path = self.file.with_suffix(".ldvdmeta.json")
        if isinstance(sidecar, dict):
            side_audio = sidecar.get("audio") or sidecar.get("audios") or []
            if not isinstance(side_audio, list):
                side_audio = []

        if side_audio:
            try:
                side_by_lang = [
                    self._normalize_lang_code((a.get("language") or a.get("lang") or "und") if isinstance(a, dict) else "und")
                    for a in side_audio
                ]
                default_lang = None
                for a in side_audio:
                    if not isinstance(a, dict):
                        continue
                    if a.get("default"):
                        default_lang = self._normalize_lang_code(a.get("language") or a.get("lang") or "und")
                        break
                print(f"[AUDIO] Sidecar LDVD rilevato: {side_path}", flush=True)
                print(
                    f"[AUDIO] Debug sidecar audio len={len(side_audio)}; side_by_lang={side_by_lang}; default_lang={default_lang or 'und'}",
                    flush=True,
                )
            except Exception as exc:
                print(f"[AUDIO] Sidecar LDVD rilevato ma debug fallito: {exc}", flush=True)
        else:
            print(f"[AUDIO] Nessun sidecar LDVD trovato ({side_path} mancante o vuoto)", flush=True)

        # ───────── ffprobe: stream audio reali ─────────
        ffprobe_bin = shutil.which("ffprobe") or "ffprobe"
        ff_streams = []
        streams_by_global = {}
        audio_ord_by_global = {}
        try:
            cmd = [
                ffprobe_bin,
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=index,codec_name,channels,channel_layout,bit_rate:stream_tags=language,title,LANGUAGE,LANG",
                "-of",
                "json",
                str(self.file),
            ]
            p = subprocess.run(cmd, capture_output=True, text=True, check=True)
            info = json.loads(p.stdout or "{}")
            ff_streams = info.get("streams") or []
            for ord_idx, s in enumerate(ff_streams):
                try:
                    gidx = int(s.get("index"))
                except Exception:
                    continue
                streams_by_global[gidx] = s
                audio_ord_by_global[gidx] = ord_idx
        except Exception as exc:
            print(f"[AUDIO] ffprobe fallito per '{self.file}': {exc}", flush=True)
            ff_streams = []

        # ───────── Helper locali ─────────
        def _norm_br_label(raw) -> str | None:
            if raw is None:
                return None
            s = str(raw).strip().lower()
            if not s or s == "n/a":
                return None
            if s.endswith("k") and s[:-1].isdigit():
                return f"{int(s[:-1])}k"
            if s.isdigit():
                try:
                    v = int(s)
                    if v <= 0:
                        return None
                    kbps = max(1, round(v / 1000))
                    return f"{kbps}k"
                except Exception:
                    return None
            digits = "".join(ch for ch in s if ch.isdigit())
            if digits:
                try:
                    v = int(digits)
                    if v <= 0:
                        return None
                    if v < 1024:
                        return f"{v}k"
                    kbps = max(1, round(v / 1000))
                    return f"{kbps}k"
                except Exception:
                    return None
            return None

        def _channels_from_text(name_field: str, codec: str, ch_int: int) -> int:
            if ch_int > 0:
                return ch_int
            text = f"{codec} {name_field}".lower()
            if "5.1" in text or "6ch" in text:
                return 6
            if "2ch" in text or "2.0" in text:
                return 2
            if "mono" in text or "1ch" in text or "1.0" in text:
                return 1
            return ch_int

        # ───────── Costruisci elenco item ─────────
        items: list[tuple[str, tuple[int, str, str], bool]] = []
        default_combo_idx = 0  # 0 = placeholder "Seleziona traccia…"

        # ===== PATH 1: sidecar presente → lui comanda ordine e lingua =====
        if side_audio:
            ref_codec = None
            ref_ch = None
            ref_br = None

            for list_pos, entry in enumerate(side_audio):
                if not isinstance(entry, dict):
                    continue

                # a) indice logico 0..N-1 per -map 0:a:<idx>
                gidx = entry.get("stream_index")
                map_idx = None

                if gidx is not None:
                    try:
                        gidx_int = int(gidx)
                        if gidx_int in audio_ord_by_global:
                            map_idx = audio_ord_by_global[gidx_int]
                    except Exception:
                        map_idx = None

                if map_idx is None:
                    for key in ("index", "audio_index", "a_index", "track_index", "track"):
                        val = entry.get(key)
                        if val is None:
                            continue
                        try:
                            map_idx = int(val)
                            break
                        except Exception:
                            map_idx = None

                if map_idx is None:
                    map_idx = list_pos

                try:
                    map_idx = max(0, int(map_idx))
                except Exception:
                    map_idx = list_pos

                ff_s = ff_streams[map_idx] if 0 <= map_idx < len(ff_streams) else None

                # b) Lingua: PRIMA sidecar, poi ffprobe, poi default UI
                raw_lang = entry.get("lang") or entry.get("language")
                if (not raw_lang) and ff_s is not None:
                    tags = ff_s.get("tags") or {}
                    for k in ("language", "LANGUAGE", "lang", "LANG"):
                        if k in tags and tags[k]:
                            raw_lang = tags[k]
                            break

                if raw_lang:
                    lang_norm = self._normalize_lang_code(raw_lang)
                else:
                    lang_norm = ui_default_lang

                lang_name = self._lang_human(lang_norm)

                # c) Codec
                codec = entry.get("codec") or (ff_s.get("codec_name") if ff_s else None) or "audio"
                codec = str(codec).upper()

                # d) Canali: prima _probe_audio_channels, poi sidecar/ffprobe/testo
                ch_int = 0
                try:
                    ch_probe = self._probe_audio_channels(str(self.file), int(map_idx))
                except Exception:
                    ch_probe = 0
                if ch_probe > 0:
                    ch_int = ch_probe
                else:
                    ch_val = entry.get("channels")
                    if ch_val is None and ff_s is not None:
                        ch_val = ff_s.get("channels")
                    try:
                        ch_int = int(ch_val or 0)
                    except Exception:
                        ch_int = 0
                    name_field = (entry.get("name") or entry.get("title") or "").lower()
                    if ff_s is not None and not name_field:
                        name_field = (ff_s.get("channel_layout") or "").lower()
                    ch_int = _channels_from_text(name_field, codec, ch_int)

                if ch_int > 0:
                    self._orig_channels[int(map_idx)] = ch_int

                # e) Layout & badge
                layout = entry.get("layout") or (ff_s.get("channel_layout") if ff_s else "") or ""
                layout_l = str(layout).lower()

                if ch_int >= 3:
                    badge = "[MC]"
                elif ch_int == 2:
                    badge = "[S]"
                elif ch_int == 1:
                    badge = "[M]"
                else:
                    badge = ""

                if layout_l.startswith("5.1") or (not layout_l and ch_int == 6):
                    ch_desc = "5.1"
                elif ch_int >= 3:
                    ch_desc = f"{ch_int}CH"
                elif ch_int == 2:
                    ch_desc = "2.0"
                elif ch_int == 1:
                    ch_desc = "1.0"
                else:
                    ch_desc = ""

                if ch_desc:
                    fmt_desc = f"{codec} {ch_desc}"
                else:
                    fmt_desc = codec

                # f) Bitrate
                raw_br = entry.get("bitrate_label") or entry.get("bitrate")
                if (not raw_br) and ff_s is not None:
                    raw_br = ff_s.get("bit_rate")

                if not raw_br:
                    try:
                        raw_br = self._probe_audio_bitrate_label(str(self.file), int(map_idx))
                    except Exception:
                        raw_br = None

                br_lbl = _norm_br_label(raw_br)

                # Se ancora vuoto, copia bitrate da una traccia “simile”
                if (not br_lbl or br_lbl == "Nessuno") and ref_codec and ref_br and (ch_int > 0):
                    if codec == ref_codec and ch_int == ref_ch:
                        br_lbl = ref_br

                if not br_lbl:
                    br_lbl = "Nessuno"

                self._orig_bitrates[int(map_idx)] = br_lbl

                if (ref_codec is None) and (br_lbl != "Nessuno") and (ch_int > 0):
                    ref_codec, ref_ch, ref_br = codec, ch_int, br_lbl

                # g) Default (es. traccia italiana con "default": true)
                is_default = bool(entry.get("default"))

                # h) Etichetta combo
                parts = []
                if badge:
                    parts.append(badge)
                parts.append(f"{L('Traccia')} {map_idx}")
                parts.append(f"- {lang_name}")
                parts.append(f"- {(_t('Nessuno', 'None') if br_lbl == 'Nessuno' else br_lbl)}")
                parts.append(f"– {fmt_desc}")
                label = " ".join(parts)

                data_tuple = (int(map_idx), lang_norm, br_lbl)
                items.append((label, data_tuple, is_default))

                print(
                    f"[AUDIO] Traccia sidecar idx={map_idx} gidx={gidx} lang={lang_norm} ch={ch_int} br={br_lbl}",
                    flush=True,
                )

            # scelta default: prima 'default', poi lingua UI, poi prima traccia
            for combo_idx, (_lbl, data_tuple, is_def) in enumerate(items, start=1):
                if is_def:
                    default_combo_idx = combo_idx
                    break

            if default_combo_idx == 0 and items:
                for combo_idx, (_lbl, data_tuple, _is_def) in enumerate(items, start=1):
                    _idx, lang_norm, _br = data_tuple
                    if lang_norm == ui_default_lang:
                        default_combo_idx = combo_idx
                        break

            if default_combo_idx == 0 and items:
                default_combo_idx = 1

        # ===== PATH 2: nessun sidecar → solo ffprobe =====
        else:
            if not ff_streams:
                print("[AUDIO] Nessun stream audio trovato", flush=True)
            else:
                print("[AUDIO] Nessun sidecar: uso solo ffprobe per le tracce audio", flush=True)

            for map_idx, s in enumerate(ff_streams):
                s_data = dict(s)
                tags = s_data.get("tags") or {}

                raw_lang = None
                for k in ("language", "LANGUAGE", "lang", "LANG"):
                    if k in tags and tags[k]:
                        raw_lang = tags[k]
                        break

                if raw_lang:
                    lang_norm = self._normalize_lang_code(raw_lang)
                else:
                    lang_norm = ui_default_lang

                lang_name = self._lang_human(lang_norm)

                codec = (s_data.get("codec_name") or "audio").upper()

                try:
                    ch_int = int(s_data.get("channels") or 0)
                except Exception:
                    ch_int = 0

                if ch_int <= 0:
                    try:
                        ch_probe = self._probe_audio_channels(str(self.file), int(map_idx))
                    except Exception:
                        ch_probe = 0
                    if ch_probe > 0:
                        ch_int = ch_probe

                if ch_int > 0:
                    self._orig_channels[int(map_idx)] = ch_int

                layout_l = str(s_data.get("channel_layout") or "").lower()

                if ch_int >= 3:
                    badge = "[MC]"
                elif ch_int == 2:
                    badge = "[S]"
                elif ch_int == 1:
                    badge = "[M]"
                else:
                    badge = ""

                if layout_l.startswith("5.1") or (not layout_l and ch_int == 6):
                    ch_desc = "5.1"
                elif ch_int >= 3:
                    ch_desc = f"{ch_int}CH"
                elif ch_int == 2:
                    ch_desc = "2.0"
                elif ch_int == 1:
                    ch_desc = "1.0"
                else:
                    ch_desc = ""

                if ch_desc:
                    fmt_desc = f"{codec} {ch_desc}"
                else:
                    fmt_desc = codec

                bit_rate = s_data.get("bit_rate")
                br_lbl = _norm_br_label(bit_rate)
                if not br_lbl:
                    try:
                        br_lbl = self._probe_audio_bitrate_label(str(self.file), int(map_idx))
                    except Exception:
                        br_lbl = None
                br_lbl = _norm_br_label(br_lbl)
                if not br_lbl:
                    br_lbl = "Nessuno"

                self._orig_bitrates[int(map_idx)] = br_lbl

                parts = []
                if badge:
                    parts.append(badge)
                parts.append(f"{L('Traccia')} {map_idx}")
                parts.append(f"- {lang_name}")
                parts.append(f"- {(_t('Nessuno', 'None') if br_lbl == 'Nessuno' else br_lbl)}")
                parts.append(f"– {fmt_desc}")
                label = " ".join(parts)

                data_tuple = (int(map_idx), lang_norm, br_lbl)
                items.append((label, data_tuple, False))

                print(
                    f"[AUDIO] Traccia ffprobe idx={map_idx} lang={lang_norm} ch={ch_int} br={br_lbl}",
                    flush=True,
                )

            if items:
                default_combo_idx = 1

        # ───────── Scrivi nella combo ─────────
        for combo_idx, (label, data_tuple, _is_def) in enumerate(items, start=1):
            self.cmb_track.addItem(label, data_tuple)

        if items:
            self.cmb_track.setEnabled(True)
            self.btn_add.setEnabled(True)
            if default_combo_idx <= 0:
                default_combo_idx = 1
            self.cmb_track.setCurrentIndex(default_combo_idx)
        else:
            self.cmb_track.setCurrentIndex(0)
            self.cmb_track.setEnabled(False)
            self.btn_add.setEnabled(False)

        self.cmb_track.blockSignals(False)

        print(
            f"[AUDIO] Combo tracce: {self.cmb_track.count() - 1} tracce caricate",
            flush=True,
        )
        print("[DEBUG] Combo tracce:", flush=True)
        for i in range(self.cmb_track.count()):
            txt = self.cmb_track.itemText(i)
            data = self.cmb_track.itemData(i)
            print(f"  {i:02d}: text='{txt}' data={data}", flush=True)

        try:
            self._refresh_filter_availability()
            self._update_pan_preset_label()
        except Exception:
            pass

    # ──────────────────────────── Caricamento audio esterno ───────────────────

    @pyqtSlot()
    def load_external_audio(self, file_path: str | None = None):
        """
        Carica una traccia **esterna** e popola cmb_track con:
          (idx, lang, br) — NESSUN dialog lingua.
        Imposta Batch in modalità 'esterno' (Batch.file=None) per la flush corretta.

        NB: idx in itemData è l'indice audio 0..N-1 (come per le tracce interne).
        """
        # init cache
        if not hasattr(self, "_orig_channels"):
            self._orig_channels = {}
        if not hasattr(self, "_orig_bitrates"):
            self._orig_bitrates = {}

        # Se non arriva un path → apri file dialog
        if not file_path:
            start_dir = str(self.file.parent) if getattr(self, "file", None) else os.path.expanduser("~")
            filters = (
                "Audio (*.wav *.flac *.aac *.m4a *.mp3 *.ogg *.ac3 *.eac3);;Video con audio (*.mkv *.mp4 *.mov *.avi);;Tutti i file (*)"
            )
            file_path, _ = QFileDialog.getOpenFileName(self, L("Seleziona traccia audio esterna"), start_dir, filters)
            if not file_path:
                return  # annullato

        # Stato esterno ON
        self.external_audio_file = file_path
        self.audio_externo = True

        # Batch: segnala che NON c'è un video di riferimento (attiva path "esterno")
        try:
            self.batch.set_video_file(None)
        except Exception:
            pass

        ui_default_lang = self._lang_code_from_combo()

        # UI path
        try:
            self.path.setText(L("Audio esterno: {0}").format(file_path))
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
        self.cmb_track.addItem(L("Seleziona traccia…"), (-1, None, None))

        combo_default_lang = ui_default_lang or self._lang_code_from_combo()

        if tracks:
            for pos, (idx_raw, title) in enumerate(tracks):
                audio_idx = pos  # indice audio 0..N-1

                br_lbl = self._probe_audio_bitrate_label(file_path, audio_idx)
                if br_lbl:
                    self._orig_bitrates[audio_idx] = br_lbl

                ch = self._probe_audio_channels(file_path, audio_idx)
                if ch:
                    self._orig_channels[audio_idx] = ch

                trk_lang = self._probe_stream_language(file_path, audio_idx)
                if trk_lang == "und":
                    trk_lang = combo_default_lang

                label = self._fmt_track_label(audio_idx, trk_lang, br_lbl or "Nessuno")
                if title:
                    label += f" – {title}"
                # itemData = (indice audio, lingua per-traccia, bitrate reale|Nessuno)
                self.cmb_track.addItem(label, (audio_idx, trk_lang, br_lbl or "Nessuno"))

            # seleziona la prima traccia reale se presente
            self.cmb_track.setCurrentIndex(1 if self.cmb_track.count() > 1 else 0)
        else:
            # fallback: file con una singola pista “mutizzata”
            trk_lang = combo_default_lang or "und"
            self.cmb_track.addItem(self._fmt_track_label(0, trk_lang, "Nessuno"), (0, trk_lang, "Nessuno"))
            self.cmb_track.setCurrentIndex(1 if self.cmb_track.count() > 1 else 0)

        self.cmb_track.setEnabled(True)
        self.cmb_track.blockSignals(False)

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

    # ──────────────────────────── Indici / bitrate ────────────────────────────

    def _norm_audio_index(self, idx, pos_fallback: int) -> int:
        """
        Normalizza l'indice della traccia audio:

        - se arriva una stringa stile '0:a:2' → estrae il '2';
        - altrimenti prova a fare int(idx);
        - fallback finale: pos_fallback (0,1,2,…).
        """
        s = str(idx)
        if "a:" in s:
            try:
                return max(0, int(s.split(":")[-1]))
            except Exception:
                try:
                    return int(pos_fallback)
                except Exception:
                    return 0
        try:
            return int(idx)
        except Exception:
            try:
                return int(pos_fallback)
            except Exception:
                return 0

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

    # ──────────────────────────── Toggle “Tratta come muto” ───────────────────

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
            try:
                self.batch.set_video_file(None)
            except Exception:
                pass
            try:
                self.path.setText(L("Trattato come muto: in attesa di audio esterno…"))
            except Exception:
                pass
            self.cmb_track.clear()
            self.cmb_track.addItem(L("File muto → carica audio esterno…"), (-1, None, None))
            self.cmb_track.setEnabled(False)
            self.btn_load_external_audio.show()
            self.btn_add.setEnabled(False)
        else:
            # → Torna a modalità interna (usa il file video caricato)
            self.audio_externo = False
            self.external_audio_file = None
            try:
                self.batch.set_video_file(str(self.file) if self.file else None)
            except Exception:
                pass
            self.btn_load_external_audio.hide()
            if self.file:
                self.load_file(str(self.file))
            else:
                self.cmb_track.clear()
                self.cmb_track.addItem(L("Seleziona traccia…"), (-1, None, None))
                self.cmb_track.setEnabled(False)
            self.btn_add.setEnabled(False)

        try:
            self._refresh_filter_availability()
            self._update_pan_preset_label()
        except Exception:
            pass

    # ──────────────────────────── Cambio traccia / cambio lingua ──────────────

    @pyqtSlot(int)
    def _on_track_changed(self, combo_idx: int):
        """
        Cambio traccia:
          - NON forza più la lingua sulla combo: prende quella memorizzata per la traccia;
          - aggiorna la combo lingua di conseguenza;
          - abilita 'Agg. traccia' e fa i refresh pesanti.
        """
        data = self.cmb_track.itemData(combo_idx)
        if not isinstance(data, (tuple, list)) or len(data) < 3:
            self.btn_add.setEnabled(False)
            return
        idx, lang, br = data
        if idx is None or idx < 0:
            self.btn_add.setEnabled(False)
            return

        # assicura un codice lingua pulito
        eff_lang = self._normalize_lang_code(lang or self._lang_code_from_combo())
        label = self._fmt_track_label(idx, eff_lang, br)
        self.cmb_track.setItemText(combo_idx, label)
        self.cmb_track.setItemData(combo_idx, (idx, eff_lang, br))

        # porta la combo lingua sulla lingua della traccia selezionata
        self._set_lang_combo(eff_lang)

        self.btn_add.setEnabled(True)
        QTimer.singleShot(0, self._after_track_change_refresh_safe)

    @pyqtSlot(int)
    def _on_lang_changed(self, _combo_idx: int):
        """
        L'utente ha cambiato la lingua nella combo:
        aggiorna SOLO la traccia correntemente selezionata (label + itemData).
        """
        track_idx = self.cmb_track.currentIndex()
        data = self.cmb_track.itemData(track_idx)
        if not isinstance(data, (tuple, list)) or len(data) < 3:
            return
        idx, old_lang, br = data
        if idx is None or idx < 0:
            return

        new_lang = self._lang_code_from_combo() or old_lang or "und"
        new_lang = self._normalize_lang_code(new_lang)
        label = self._fmt_track_label(idx, new_lang, br)
        self.cmb_track.setItemText(track_idx, label)
        self.cmb_track.setItemData(track_idx, (idx, new_lang, br))

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
        if not isinstance(data, (tuple, list)) or len(data) < 3:
            return
        idx, lang, _ = data
        if idx < 0:
            return
        br = new_br if new_br != "Nessuno" else self._orig_bitrates.get(idx, "Nessuno")
        lang = self._normalize_lang_code(lang)
        label = self._fmt_track_label(idx, lang, br)
        self.cmb_track.setItemText(combo_idx, label)
        self.cmb_track.setItemData(combo_idx, (idx, lang, new_br))
        QTimer.singleShot(0, getattr(self, "_after_track_change_refresh_safe", lambda: None))

    # ──────────────────────────── Preview ─────────────────────────────────────

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

    # ──────────────────────────── Canali / filtro availability ────────────────

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
        """
        Ritorna i canali della traccia correntemente selezionata
        usando _probe_audio_channels() e l'indice audio 0..N-1.
        """
        try:
            data = self.cmb_track.currentData() or (-1, None, None)
            idx = data[0] if isinstance(data, (tuple, list)) and data else -1
            if idx is None or idx < 0:
                return 2

            if bool(getattr(self, "audio_externo", False)) and self.external_audio_file:
                ch = self._probe_audio_channels(self.external_audio_file, int(idx))
            else:
                if not self.file:
                    return 2
                ch = self._probe_audio_channels(str(self.file), int(idx))

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
                    self.lbl_pan_preset.setText(_t("Pan preset: — (input MONO mantenuto)", "Preset: — (MONO kept)"))
                elif in_ch > 2 and stereo_out:
                    preset = (
                        _t("Samsung R450", "Samsung R450")
                        if prof == getattr(C, "PROFILE_SAMSUNG_STEREO_KEY", "samsung_stereo")
                        else _t("TV generico", "Generic TV")
                    )
                    head = _t("Pan preset:", "Preset:")
                    dm = _t("downmix 5.1→2.0", "5.1→2.0 downmix")
                    self.lbl_pan_preset.setText(f"{head} {preset} ({dm})")
                else:
                    self.lbl_pan_preset.setText(_t("Pan preset: — (nessun downmix)", "Preset: — (no downmix)"))
        except Exception:
            pass

        self._update_pan_preset_label()

    # ──────────────────────────── Pan preset / descrittore ────────────────────

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
            lbl.setText(_t("Pan preset: Samsung (crossfeed)", "Preset: Samsung (crossfeed)"))
            lbl.setStyleSheet("color: #e11d48;")
            return
        if nch > 2 and key:
            lbl.setText(_t("Pan preset: downmix attivo", "Preset: downmix enabled"))
            lbl.setStyleSheet("color: #10b981;")
        else:
            lbl.setText(_t("Pan preset: — (nessun downmix)", "Preset: — (no downmix)"))
            lbl.setStyleSheet("")

    def _current_input_channels_hint(self) -> int:
        """
        Piccolo helper per sapere quanti canali ha la traccia corrente
        (serve per decidere pan preset, pseudo-stereo, ecc.).
        Usa SEMPRE l'indice audio 0..N-1.
        """
        try:
            data = self.cmb_track.currentData()
            if not isinstance(data, (tuple, list)) or not data:
                return 2
            idx = data[0]
            if idx is None or int(idx) < 0:
                return 2
            a_idx = int(idx)

            if self.audio_externo and self.external_audio_file:
                ch = self._probe_audio_channels(self.external_audio_file, a_idx)
            else:
                if not self.file:
                    return 2
                ch = self._probe_audio_channels(str(self.file), a_idx)

            return ch if ch > 0 else 2
        except Exception:
            return 2

    @pyqtSlot()
    def _update_pan_preset_label(self, *args, **kwargs):
        lbl = getattr(self, "lbl_pan_preset", None)
        if lbl is None:
            return

        try:
            in_ch = self._current_input_channels_hint()
        except Exception:
            in_ch = 2

        keep_mono = bool(getattr(self, "chk_keep_mono", None) and self.chk_keep_mono.isChecked())
        downmix_on = bool(getattr(self, "chk_force_stereo", None) and self.chk_force_stereo.isChecked())

        prof = getattr(self, "_soundbar_profile", "none")
        from hevc_gui.core import constants as C

        samsung_stereo = prof == getattr(C, "PROFILE_SAMSUNG_STEREO_KEY", "samsung_stereo")
        samsung_51 = prof == "samsung_5_1_ac3"

        try:
            eff_stereo = bool(self._effective_output_is_stereo(in_ch))
        except Exception:
            eff_stereo = in_ch >= 2 and not keep_mono

        if in_ch == 1 and keep_mono:
            lbl.setText(
                _t("Pan preset: — (input MONO mantenuto: nessun pan/pseudo-stereo)", "Pan preset: — (MONO kept: no pan/pseudo-stereo)")
            )
            lbl.setStyleSheet("")
            return

        if in_ch > 2 and downmix_on:
            which = _t("Samsung R450", "Samsung R450") if samsung_stereo else _t("TV generico", "Generic TV")
            cause = _t("forzato da “Stereo (downmix 2ch)”", "forced by “Stereo (2ch downmix)”")
            head = _t("Pan preset:", "Preset:")
            dm = _t("downmix 5.1→2.0", "5.1→2.0 downmix")
            lbl.setText(f"{head} {which} ({dm}, {cause})")
            lbl.setStyleSheet("color: #10b981;")
            return

        if eff_stereo and samsung_stereo:
            src = (
                _t("input MONO → pseudo-stereo", "MONO input → pseudo-stereo")
                if (in_ch == 1 and not keep_mono)
                else _t("uscita stereo", "stereo output")
            )
            head = _t("Pan preset:", "Preset:")
            tail = _t("profilo attivo", "profile enabled")
            lbl.setText(f"{head} Samsung (crossfeed, {src}, {tail})")
            lbl.setStyleSheet("color: #e11d48;")
            return

        if samsung_51:
            lbl.setText(
                _t("Pan preset: — (Uscita 5.1; profilo Samsung 5.1 attivo)", "Pan preset: — (5.1 output; Samsung 5.1 profile enabled)")
            )
            lbl.setStyleSheet("color: #2563eb;")
            return

        if in_ch > 2:
            extra = _t("input multicanale mantenuto (nessun downmix)", "multichannel input kept (no downmix)")
        elif in_ch == 2:
            extra = _t("stereo nativo (nessun crossfeed/preset)", "native stereo (no crossfeed/preset)")
        else:
            extra = _t("mono → pseudo-stereo senza crossfeed", "mono → pseudo-stereo without crossfeed")
        head = _t("Pan preset: —", "Preset: —")
        lbl.setText(f"{head} ({extra})")
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

    # ──────────────────────────── Costruzione catena filtri ───────────────────
    # (tutto identico alla tua versione, solo incollato qui per intero)

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

        # 5) Downmix / Soundbar
        force_st = bool(getattr(self, "chk_force_stereo", None) and self.chk_force_stereo.isChecked())

        # Se l'output effettivo è stereo e l'input è multicanale (>2),
        # prepariamo un pan esplicito 5.1 → 2.0 che includa DAVVERO il centro (dialoghi).
        need_downmix = bool(force_st and (channels_hint and channels_hint > 2) and not _has_pan(filters))
        if need_downmix:
            pan = None

            # Caso tipico DVD/Blu-ray: 5.1 (FL FR FC LFE SL SR)
            if channels_hint and channels_hint >= 6:
                if is_samsung_stereo:
                    # Mix per Samsung soundbar:
                    #  - manteniamo bene L/R
                    #  - centro (dialoghi) forte su entrambi
                    #  - un po' di surround + LFE
                    pan = "pan=stereo|c0=0.90*c0+0.75*c2+0.25*c4+0.20*c3|c1=0.90*c1+0.75*c2+0.25*c5+0.20*c3"
                else:
                    # Mix generico TV-friendly 5.1 → stereo
                    pan = "pan=stereo|c0=0.90*c0+0.70*c2+0.30*c4+0.20*c3|c1=0.90*c1+0.70*c2+0.30*c5+0.20*c3"
            else:
                # Per layout "strani" (3.0, 4.0, ecc.) usiamo ancora i preset da constants
                pan = C.AUD_PAN_PRESETS.get("stereo_samsung_r450" if is_samsung_stereo else "stereo_tv_generic")

            if pan:
                filters.append(pan)

        # Profilo Samsung con sorgente già stereo (2ch): crossfeed leggero + piccolo boost
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
            comp_sel = self.cmb_comp_soft.currentData()
        except Exception:
            comp_sel = None
        if not comp_sel:
            try:
                comp_sel = (self.cmb_comp_soft.currentText() or "").strip().lower()
            except Exception:
                comp_sel = "nessuno"
        if isinstance(comp_sel, str):
            comp_sel = comp_sel.strip().lower()

        # normalizza: supporta vecchie etichette IT e nuove chiavi EN
        norm = {
            "nessuno": "none",
            "none": "none",
            "leggero": "light",
            "light": "light",
            "medio": "medium",
            "medium": "medium",
            "forte": "strong",
            "strong": "strong",
        }
        comp_sel = norm.get(comp_sel, comp_sel)

        if comp_sel in ("light", "medium", "strong"):
            if comp_sel == "light":
                P = dict(
                    threshold="-12dB",
                    ratio=2.5,
                    attack=12,
                    release=220,
                    knee=6,
                    detection="rms",
                    link="average",
                    makeup=4,
                )
            elif comp_sel == "medio":
                P = dict(
                    threshold="-18dB",
                    ratio=3.0,
                    attack=10,
                    release=280,
                    knee=6,
                    detection="rms",
                    link="average",
                    makeup=5,
                )
            else:
                P = dict(
                    threshold="-22dB",
                    ratio=4.0,
                    attack=8,
                    release=350,
                    knee=8,
                    detection="rms",
                    link="average",
                    makeup=6,
                )
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

    # ──────────────────────────── Titolo audio (metadati) ─────────────────────

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

    # ──────────────────────────── Aggiungi segmento (traccia) ─────────────────

    @pyqtSlot()
    def add_seg(self):
        """
        Aggiunge **una** traccia audio alla batch.
        Lingua:
          - prima guarda itemData della traccia (per-traccia),
          - fallback combo lingua.

        NB: idx è l'indice audio 0..N-1, usato per:
          - ffprobe (a:idx)
          - ffmpeg -map 0:a:idx
          - current_opts() → preview.
        """
        is_ext = bool(self.audio_externo)

        # recupera info traccia corrente
        data = self.cmb_track.currentData()
        if not isinstance(data, (tuple, list)) or len(data) < 3:
            QMessageBox.warning(self, L("Audio"), L("Seleziona una traccia valida."))
            return
        idx, stored_lang, br = data
        if idx is None or idx < 0:
            QMessageBox.warning(self, L("Audio"), L("Seleziona una traccia valida."))
            return

        audio_idx = int(idx)
        lang = self._normalize_lang_code(stored_lang or self._lang_code_from_combo() or "und")

        if is_ext:
            if not self.external_audio_file:
                QMessageBox.warning(self, L("Audio esterno"), L("Nessun file audio esterno caricato."))
                return
            src_path = str(self.external_audio_file)
        else:
            src_path = str(self.file)

        # mappatura: sempre indice audio 0..N-1
        sidx = audio_idx
        map_str = f"0:a:{sidx}"
        idx_for_orig = audio_idx

        # aggiorna subito label+itemData con la lingua effettiva
        cur_txt = self._fmt_track_label(audio_idx, lang, br)
        self.cmb_track.setItemText(self.cmb_track.currentIndex(), cur_txt)
        self.cmb_track.setItemData(self.cmb_track.currentIndex(), (audio_idx, lang, br))

        # canali rilevati
        detected_ch = self._probe_audio_channels(src_path, sidx) or 2

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

        # [FIX 5.1 → stereo] Se l’input è multicanale e l’output effettivo è stereo,
        # assicuriamoci di avere un downmix esplicito DENTRO la catena filtri,
        # così il canale centrale (dialoghi) viene miscelato correttamente.
        try:
            eff_stereo = self._effective_output_is_stereo(detected_ch)
        except Exception:
            eff_stereo = detected_ch >= 2

        if detected_ch and detected_ch > 2 and eff_stereo:
            has_downmix = False
            for f in filters or []:
                if not isinstance(f, str):
                    continue
                # se c’è già un pan o un aresample/aformat che porta a stereo, non tocchiamo nulla
                if f.startswith("pan=") or "aresample=ocl=stereo" in f or "aformat=channel_layouts=stereo" in f:
                    has_downmix = True
                    break
            if not has_downmix:
                if filters is None:
                    filters = []
                # usa il rematrix di ffmpeg (5.1 → stereo con center dentro L/R)
                filters.insert(0, "aresample=ocl=stereo")

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

        if user_br_txt:
            out_br = _parse_kbps(user_br_txt)
        else:
            if idx_for_orig in self._orig_bitrates:
                out_br = _parse_kbps(self._orig_bitrates[idx_for_orig])
            else:
                out_br = 192

        try:
            if getattr(self, "cmb_sr", None):
                sr_txt = (self.cmb_sr.currentText() or "").strip()
                out_sr = int(sr_txt) if sr_txt.isdigit() else None
            else:
                out_sr = None
        except Exception:
            out_sr = None

        if wants_51:
            out_codec = "ac3"
            out_ch = 6
            out_layout = "5.1(side)"
            if not out_sr:
                out_sr = 48000
            if not out_br:
                out_br = 448
        else:
            out_codec = "aac"
            out_ch = 2 if detected_ch >= 2 else 1
            out_layout = "stereo" if out_ch == 2 else "mono"
            if not out_br:
                out_br = 192

        seg: list[str] = []
        seg += [C.FFMPEG_BIN, "-y", "-nostdin"]
        seg += ["-i", src_path]
        seg += ["-map", map_str]
        seg += ["-vn"]

        if out_sr:
            seg += ["-ar", str(out_sr)]
        seg += ["-ac", str(out_ch)]
        seg += ["-acodec", out_codec]

        if af_chain:
            seg += ["-af", af_chain]

        if out_codec == "aac":
            try:
                use_fdk = bool(getattr(self, "chk_use_fdk", None) and self.chk_use_fdk.isChecked())
            except Exception:
                use_fdk = False
            if use_fdk:
                seg += ["-c:a", "libfdk_aac", "-profile:a", "aac_low"]
            else:
                seg += ["-c:a", "aac", "-profile:a", "aac_low"]
        elif out_codec == "ac3":
            seg += ["-c:a", "ac3"]

        if out_br:
            seg += ["-b:a", f"{out_br}k"]

        if out_layout:
            seg += ["-ac", str(out_ch), "-channel_layout", out_layout]

        title = self._fmt_audio_title_from_flags(
            lang=lang,
            codec=out_codec,
            ac=out_ch,
            ar=out_sr,
            br=f"{out_br}k" if out_br else None,
        )

        seg += ["-metadata:s:a:0", f"language={lang}"]
        seg += ["-metadata:s:a:0", f"title={title}"]

        out_path = getattr(self, "out_path_edit", None)
        if isinstance(out_path, QLineEdit):
            target = out_path.text().strip()
            if not target:
                base = Path(src_path).name
                base_noext = os.path.splitext(base)[0]
                target = os.path.join(os.path.dirname(src_path), base_noext + "_conv.m4a")
        else:
            base = Path(src_path).name
            base_noext = os.path.splitext(base)[0]
            target = os.path.join(os.path.dirname(src_path), base_noext + "_conv.m4a")

        seg += [target]

        self.batch.add(seg)

        self.list.addItem(" ".join(shlex.quote(x) for x in seg))
        self.list.scrollToBottom()

        self.btn_add.setEnabled(False)

        try:
            self._update_pan_preset_label()
        except Exception:
            pass

    # ──────────────────────────── Opzioni correnti (per preview) ──────────────

    def current_opts(self) -> dict:
        """
        Raccoglie le impostazioni correnti in un dizionario usato da preview.
        La lingua qui è solo informativa (per il titolo).
        """
        data = self.cmb_track.currentData() or (-1, None, None)
        idx, lang, br = data if isinstance(data, (tuple, list)) else (-1, None, None)
        idx = int(idx) if idx is not None else -1
        lang = self._normalize_lang_code(lang or self._lang_code_from_combo() or "und")

        sr_txt = self.cmb_sr.currentText() if getattr(self, "cmb_sr", None) else "Nessuno"
        sr = int(sr_txt) if sr_txt.isdigit() else None

        try:
            rev = (self.cmb_rev.currentText() or "").strip()
        except Exception:
            rev = "Nessuno"

        opts = {
            "input": str(self.file) if self.file else self.external_audio_file,
            "track_index": idx,
            "is_external": bool(self.audio_externo),
            "lang": lang,
            "bitrate": br,
            "sample_rate": sr,
            "reverb": rev,
            "dyn": bool(getattr(self, "chk_dyn", None) and self.chk_dyn.isChecked()),
            "dialog_boost": bool(getattr(self, "chk_dialog_boost", None) and self.chk_dialog_boost.isChecked()),
            "keep_mono": bool(getattr(self, "chk_keep_mono", None) and self.chk_keep_mono.isChecked()),
        }
        return opts

    # ──────────────────────────── Profili audio esclusivi ─────────────────────

    def _setup_exclusive_audio_profiles(self):
        """
        Rende mutualmente esclusivi:
          - Stereo (downmix)
          - Samsung Stereo
          - Samsung 5.1
        """
        c_down = getattr(self, "chk_force_stereo", None)
        c_sb_st = getattr(self, "chk_sb_stereo", None)
        c_sb_51 = getattr(self, "chk_sb_51", None)

        group = [w for w in (c_down, c_sb_st, c_sb_51) if w is not None]

        def _on_toggle(src, key):
            def handler(state: bool):
                if not state:
                    return
                for w in group:
                    if w is src:
                        continue
                    try:
                        w.blockSignals(True)
                        w.setChecked(False)
                        w.blockSignals(False)
                    except Exception:
                        pass
                self._soundbar_profile = key
                self._refresh_filter_availability()
                self._update_pan_preset_label()

            return handler

        if c_down is not None:
            c_down.toggled.connect(_on_toggle(c_down, "none"))
        if c_sb_st is not None:
            c_sb_st.toggled.connect(_on_toggle(c_sb_st, "samsung_stereo"))
        if c_sb_51 is not None:
            c_sb_51.toggled.connect(_on_toggle(c_sb_51, "samsung_5_1_ac3"))

    # ──────────────────────────── Finish / reset ──────────────────────────────

    @pyqtSlot()
    def finish(self):
        """
        Chiude il dialog stampando su stdout la batch JSON (solo opzioni ffmpeg,
        senza binario, senza '-y' e con mapping corretto per audio esterno).
        """
        if not self.batch.items:
            if (
                QMessageBox.question(
                    self,
                    L("Nessuna traccia"),
                    _t(
                        "Non hai aggiunto nessuna traccia.\nVuoi uscire comunque?", "You didn't add any track.\nDo you want to exit anyway?"
                    ),
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                == QMessageBox.No
            ):
                return

        self._closing_via_finish = True
        try:
            self.batch.flush()
        except Exception as e:
            print(f"[string_audio_generator] Errore in flush(): {e}", file=sys.stderr, flush=True)
        self.accept()

    def closeEvent(self, event):
        if self._closing_via_finish:
            event.accept()
            return
        if self.batch.items:
            ans = QMessageBox.question(
                self,
                _t("Conferma", "Confirm"),
                L("Ci sono tracce nella lista.\nVuoi davvero chiudere e perdere la batch?"),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if ans != QMessageBox.Yes:
                event.ignore()
                return
        event.accept()

    @pyqtSlot()
    def _reset_defaults(self):
        """
        Resetta UI senza toccare il file sorgente:
        - mantiene self.file;
        - svuota list/batch;
        - riporta i controlli a default.
        """
        self.batch.items.clear()
        self.list.clear()
        self.chk_force_mute.setChecked(False)
        self.audio_externo = False
        self.external_audio_file = None

        self.cmb_br.setCurrentIndex(0)
        self.cmb_sr.setCurrentIndex(0)
        self.chk_nr.setChecked(False)
        self.in_nr.clear()
        self.cmb_gain.setCurrentText("0")
        self.cmb_eq_bass.setCurrentText("0")
        self.cmb_eq_mid.setCurrentText("0")
        self.cmb_eq_treb.setCurrentText("0")
        self.cmb_rev.setCurrentIndex(0)
        self.cmb_stereo.setCurrentIndex(0)
        self.cmb_comp_soft.setCurrentIndex(0)
        self.chk_dyn.setChecked(False)
        self.chk_dialog_boost.setChecked(False)
        self.chk_keep_mono.setChecked(False)
        self.chk_anticlip.setChecked(False)
        self.chk_force_stereo.setChecked(False)
        self.chk_sb_stereo.setChecked(False)
        self.chk_sb_51.setChecked(False)
        self._soundbar_profile = "none"

        if self.file:
            self.load_file(str(self.file))
        else:
            self.cmb_track.clear()
            self.cmb_track.addItem(L("Seleziona traccia…"), (-1, None, None))
            self.cmb_track.setEnabled(False)
            self.btn_add.setEnabled(False)

        self._update_pan_preset_label()
        self._refresh_filter_availability()


# ──────────────────────────── Entry point di test ────────────────────────────


def main():
    """
    Uso standalone (debug):
        python3 string_audio_generator.py /percorso/file_video_o_audio
    """
    from PyQt5.QtWidgets import QApplication

    app = QApplication(sys.argv)
    init_qt_i18n(app)
    if len(sys.argv) < 2:
        QMessageBox.critical(None, L("String Audio Generator"), L("Devi passare un file come argomento."))
        sys.exit(1)

    auto = sys.argv[1]
    dlg = AudioConverter(auto=auto)
    dlg.show()
    ret = app.exec_()
    sys.exit(ret)


if __name__ == "__main__":
    main()


# AUTO: stable _t follows HEVC get_lang
def _t(it: str, en: str, *_, **__) -> str:
    """IT/EN helper: segue la lingua di HEVC (get_lang/HEVC_LANG)."""
    try:
        lang = (get_lang() or "").lower()
    except Exception:
        lang = ""
    if not lang:
        import os

        lang = os.environ.get("HEVC_LANG", "").lower()
    return en if lang.startswith("en") else it


# AUTO: footer downmix i18n SAFE wrapper
# Non cambia logica/stato: traduce SOLO il testo finale delle label downmix/pan preset quando la lingua è EN.
def _hevc__sag_lang_is_en() -> bool:
    try:
        lang = (get_lang() or "").lower()
    except Exception:
        import os

        lang = os.environ.get("HEVC_LANG", "").lower()
    return lang.startswith("en")


def _hevc__sag_translate_footer_text(t: str) -> str:
    if not t:
        return t
    # replacements mirati (aggiungiamo qui solo frasi del footer downmix)
    repl = [
        ("Pan preset:", "Preset:"),
        ("nessun downmix", "no downmix"),
        ("downmix attivo", "downmix enabled"),
        ("input MONO mantenuto", "MONO kept"),
        ("nessun pan/pseudo-stereo", "no pan/pseudo-stereo"),
        ("input stereo/mono o profili spenti", "stereo/mono input or profiles off"),
        ("Uscita 5.1; profilo Samsung 5.1 attivo", "5.1 output; Samsung 5.1 profile enabled"),
        ("profilo Samsung 5.1 attivo", "Samsung 5.1 profile enabled"),
        ("Uscita 5.1", "5.1 output"),
    ]
    for it, en in repl:
        t = t.replace(it, en)
    return t


def _hevc__sag_patch_footer_labels(self) -> None:
    # tocchiamo SOLO label note; se non esistono, pace.
    for attr in ("lbl_pan_preset", "lbl_downmix", "lbl_downmix_state", "lbl_dm"):
        w = getattr(self, attr, None)
        if w is None:
            continue
        # QLabel-like: text()/setText()
        try:
            txt = w.text()
            w.setText(_hevc__sag_translate_footer_text(txt))
        except Exception:
            pass
        # anche tooltip se presente
        try:
            tip = w.toolTip()
            if tip:
                w.setToolTip(_hevc__sag_translate_footer_text(tip))
        except Exception:
            pass


def _hevc__sag_install_footer_i18n_wrapper():
    # trova una classe che abbia _update_pan_preset_label e wrappa quel metodo
    for _name, _obj in list(globals().items()):
        if isinstance(_obj, type) and hasattr(_obj, "_update_pan_preset_label"):
            _orig = getattr(_obj, "_update_pan_preset_label")

            # evita doppio wrapping
            if getattr(_orig, "_hevc_wrapped", False):
                return

            def _wrapped(self, *a, **k):
                r = _orig(self, *a, **k)
                if _hevc__sag_lang_is_en():
                    _hevc__sag_patch_footer_labels(self)
                return r

            _wrapped._hevc_wrapped = True
            setattr(_obj, "_update_pan_preset_label", _wrapped)
            return


_hevc__sag_install_footer_i18n_wrapper()


# AUTO: _t v2 uses translator probe + footer downmix tuning
# Obiettivo: far seguire _t alla lingua reale (QTranslator), senza dipendere solo da get_lang/HEVC_LANG.
def _hevc__is_en_via_translator_probe() -> bool:
    try:
        from hevc_gui.i18n import L

        # "Pronto." in EN TS => "Ready." (se il translator EN è attivo)
        probed = L("Pronto.")
        if probed and probed != "Pronto.":
            return True
    except Exception:
        pass
    return False


def _t(it: str, en: str, *_, **__) -> str:
    try:
        if _hevc__is_en_via_translator_probe():
            return en
    except Exception:
        pass
    try:
        lang = (get_lang() or "").lower()
    except Exception:
        lang = ""
    if not lang:
        import os

        lang = os.environ.get("HEVC_LANG", "").lower()
    return en if lang.startswith("en") else it


# Tuning extra SOLO per il footer Pan preset (copre i casi che hai mostrato).
def _hevc__sag_translate_footer_text(t: str) -> str:
    if not t:
        return t
    repl = [
        ("Pan preset:", "Preset:"),
        ("Uscita 5.1; profilo Samsung 5.1 attivo", "5.1 output; Samsung 5.1 profile enabled"),
        ("Samsung (crossfeed, uscita stereo, profilo attivo)", "Samsung (crossfeed, stereo output, profile enabled)"),
        ("stereo nativo (nessun crossfeed/preset)", "native stereo (no crossfeed/preset)"),
        ("nessun downmix", "no downmix"),
        ("downmix attivo", "downmix enabled"),
        ("uscita stereo", "stereo output"),
        ("profilo attivo", "profile enabled"),
    ]
    for it_s, en_s in repl:
        t = t.replace(it_s, en_s)
    return t


def _hevc__sag_patch_footer_labels(self) -> None:
    # Traduci SOLO testo/tooltip di lbl_pan_preset (e altri alias se esistono)
    for attr in ("lbl_pan_preset",):
        w = getattr(self, attr, None)
        if w is None:
            continue
        try:
            txt = w.text()
            w.setText(_hevc__sag_translate_footer_text(txt))
        except Exception:
            pass
        try:
            tip = w.toolTip()
            if tip:
                w.setToolTip(_hevc__sag_translate_footer_text(tip))
        except Exception:
            pass


# Wrappa _update_pan_preset_label se esiste (idempotente) e applica patch testo DOPO la logica.
def _hevc__sag_install_footer_wrapper_v2():
    for _name, _obj in list(globals().items()):
        if isinstance(_obj, type) and hasattr(_obj, "_update_pan_preset_label"):
            _orig = getattr(_obj, "_update_pan_preset_label")
            if getattr(_orig, "_hevc_wrapped_v2", False):
                return

            def _wrapped(self, *a, **k):
                r = _orig(self, *a, **k)
                # se EN (via translator o lang), ripulisci testo footer
                if _hevc__is_en_via_translator_probe() or _t("x", "y") == "y":
                    _hevc__sag_patch_footer_labels(self)
                return r

            _wrapped._hevc_wrapped_v2 = True
            setattr(_obj, "_update_pan_preset_label", _wrapped)
            return


_hevc__sag_install_footer_wrapper_v2()
