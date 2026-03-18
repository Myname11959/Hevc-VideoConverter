from __future__ import annotations

from pathlib import Path
from typing import Optional
import math
import audioop
import shutil
import subprocess
import tempfile
import wave
import locale
import os

def _force_c_numeric_locale():
    """
    libmpv vuole LC_NUMERIC='C', altrimenti può crashare.
    """
    try:
        locale.setlocale(locale.LC_NUMERIC, "C")
        os.environ["LC_NUMERIC"] = "C"
        return
    except Exception:
        pass

    for cand in ("POSIX", "C.UTF-8"):
        try:
            locale.setlocale(locale.LC_NUMERIC, cand)
            os.environ["LC_NUMERIC"] = cand
            return
        except Exception:
            pass

_force_c_numeric_locale()

import mpv
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt

from hevc_gui.i18n import L
from hevc_gui.core import constants as C


def _dbfs_from_value(value: int, sample_width: int) -> float:
    if value <= 0:
        return -90.0
    try:
        max_amp = float((1 << (8 * int(sample_width) - 1)) - 1)
        if max_amp <= 0:
            return -90.0
        return 20.0 * math.log10(float(value) / max_amp)
    except Exception:
        return -90.0


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return -90.0
    vals = sorted(float(v) for v in values)
    if len(vals) == 1:
        return vals[0]
    p = max(0.0, min(100.0, float(pct)))
    idx = int(round((len(vals) - 1) * (p / 100.0)))
    idx = max(0, min(len(vals) - 1, idx))
    return vals[idx]


def analyze_noise_segment(input_path: str, map_spec: str | None, start_sec: int, dur_sec: int) -> dict:
    """
    Analisi reale di un tratto audio RAW:
    - estrae un WAV mono 16 kHz
    - misura RMS su finestre da ~100 ms
    - stima un noise floor ragionevole
    - propone nr/nf prudenti
    """
    ffmpeg_bin = getattr(C, "FFMPEG_BIN", None) or shutil.which("ffmpeg") or "ffmpeg"
    start_sec = max(0, int(start_sec or 0))
    dur_sec = max(5, int(dur_sec or 20))

    tmpdir = None
    try:
        tmpdir = Path(tempfile.mkdtemp(prefix="hevc_sag_nr_"))
        wav_path = tmpdir / "nr_probe.wav"

        cmd = [ffmpeg_bin, "-hide_banner", "-nostdin", "-loglevel", "error", "-y"]
        if start_sec > 0:
            cmd += ["-ss", str(start_sec)]
        cmd += ["-i", str(input_path)]
        if map_spec:
            cmd += ["-map", str(map_spec)]
        cmd += ["-vn", "-sn", "-dn", "-ac", "1", "-ar", "16000", "-t", str(dur_sec), "-c:a", "pcm_s16le", str(wav_path)]

        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if p.returncode != 0 or not wav_path.is_file():
            return {
                "ok": False,
                "error": (p.stderr or "").strip() or "ffmpeg non è riuscito a creare il campione di analisi.",
                "cmd": " ".join(cmd),
            }

        rms_vals: list[float] = []
        peak_vals: list[float] = []

        with wave.open(str(wav_path), "rb") as wf:
            sampwidth = int(wf.getsampwidth())
            rate = int(wf.getframerate())
            win_frames = max(int(rate * 0.10), 1)

            while True:
                data = wf.readframes(win_frames)
                if not data:
                    break
                try:
                    rms = audioop.rms(data, sampwidth)
                except Exception:
                    rms = 0
                try:
                    peak = audioop.max(data, sampwidth)
                except Exception:
                    peak = 0
                rms_vals.append(_dbfs_from_value(rms, sampwidth))
                peak_vals.append(_dbfs_from_value(peak, sampwidth))

        if not rms_vals:
            return {"ok": False, "error": "Nessun dato audio utile ricavato dal campione analizzato."}

        p10 = _percentile(rms_vals, 10)
        p25 = _percentile(rms_vals, 25)
        p50 = _percentile(rms_vals, 50)
        p90 = _percentile(rms_vals, 90)
        peak_max = max(peak_vals) if peak_vals else p90

        nf_suggest = max(-80.0, min(-20.0, round(p10)))
        if nf_suggest <= -58:
            nr_suggest = 4.0
        elif nf_suggest <= -52:
            nr_suggest = 6.0
        elif nf_suggest <= -46:
            nr_suggest = 8.0
        elif nf_suggest <= -40:
            nr_suggest = 10.0
        else:
            nr_suggest = 12.0

        if (p50 - p10) < 8.0:
            nr_suggest = min(15.0, nr_suggest + 1.0)

        summary = (
            f"{L('Analisi reale su spezzone RAW')} ({dur_sec}s)\n\n"
            f"RMS p10 (quiet floor): {p10:.1f} dBFS\n"
            f"RMS p25: {p25:.1f} dBFS\n"
            f"RMS mediano: {p50:.1f} dBFS\n"
            f"RMS p90: {p90:.1f} dBFS\n"
            f"Peak max: {peak_max:.1f} dBFS\n\n"
            f"{L('Noise floor suggerito')} (nf): {nf_suggest:.1f}\n"
            f"{L('Noise reduction suggerita')} (nr): {nr_suggest:.1f}\n\n"
            f"{L('Nota')}: {L('è un consiglio pratico, non una verità assoluta. Verifica sempre con Preview.')}"
        )

        return {
            "ok": True,
            "summary": summary,
            "nr": f"{nr_suggest:.1f}",
            "nf": f"{nf_suggest:.1f}",
        }

    finally:
        if tmpdir and tmpdir.exists():
            shutil.rmtree(tmpdir, ignore_errors=True)


class SAGNoiseReductionDialog(QtWidgets.QDialog):
    def __init__(
        self,
        parent=None,
        *,
        source_path: str,
        map_spec: str | None,
        track_label: str,
        start_sec: int,
        duration_sec: int,
        existing: dict | None = None,
    ):
        super().__init__(parent)
        self._source_path = str(source_path)
        self._map_spec = map_spec
        self._track_label = track_label or "—"
        self._cfg = dict(existing or {})
        self._player: Optional[mpv.MPV] = None
        self._player_inited = False
        self._poll_timer = QtCore.QTimer(self)
        self._poll_timer.setInterval(120)
        self._seek_timer = QtCore.QTimer(self)
        self._seek_timer.setSingleShot(True)
        self._seek_timer.setInterval(35)
        self._slider_dragging = False
        self._pending_seek_sec: Optional[float] = None
        self._preview_stop_sec: Optional[float] = None

        self._repo_root = Path(__file__).resolve().parents[2]
        self._tmp_dir = self._repo_root / "tmp" / "sag_noise_reduction"
        self._tmp_dir.mkdir(parents=True, exist_ok=True)
        self._tmp_preview_file = self._tmp_dir / "nr_preview.mkv"

        self.setWindowTitle(L("Noise reduction"))
        self.setModal(True)
        self.resize(640, 826)
        self.setMinimumSize(600, 700)
        self._settings = QtCore.QSettings("LorisPaganiniHomeStudio", "sag_noise_reduction_dialog")
        self._geom_restored = False

        self._build_ui(start_sec, duration_sec)
        self._wire_signals()

        if self._cfg.get("summary"):
            self.txt_result.setPlainText(str(self._cfg.get("summary") or ""))
        if self._cfg.get("nr") not in (None, "", "None"):
            self.ed_nr.setText(str(self._cfg.get("nr")))
        if self._cfg.get("nf") not in (None, "", "None"):
            self.ed_nf.setText(str(self._cfg.get("nf")))

    def _build_ui(self, start_sec: int, duration_sec: int) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        gb_src = QtWidgets.QGroupBox(L("Sorgente"), self)
        gl_src = QtWidgets.QGridLayout(gb_src)
        gl_src.setContentsMargins(8, 8, 8, 8)
        gl_src.setHorizontalSpacing(6)
        gl_src.setVerticalSpacing(4)

        self.ed_source = QtWidgets.QLineEdit(self)
        self.ed_source.setReadOnly(True)
        self.ed_source.setText(self._source_path)

        self.lbl_track = QtWidgets.QLabel(self._track_label, self)

        self.btn_help = QtWidgets.QToolButton(self)
        self.btn_help.setFixedSize(22, 22)
        try:
            _ic = QtGui.QIcon(":/icons/ph_help.png")
            if _ic.isNull():
                _cand = Path(__file__).resolve().parents[1] / "resources" / "icons" / "ph_help.png"
                if _cand.is_file():
                    _ic = QtGui.QIcon(str(_cand))
            if _ic.isNull():
                _ic = self.style().standardIcon(QtWidgets.QStyle.SP_DialogHelpButton)
            self.btn_help.setIcon(_ic)
            self.btn_help.setText("")
            self.btn_help.setToolButtonStyle(Qt.ToolButtonIconOnly)
        except Exception:
            self.btn_help.setText("?")
        self.btn_help.setToolTip(L("Istruzioni / Manuale"))

        gl_src.addWidget(QtWidgets.QLabel(L("File")), 0, 0)
        gl_src.addWidget(self.ed_source, 0, 1)
        gl_src.addWidget(self.btn_help, 0, 2)
        gl_src.addWidget(QtWidgets.QLabel(L("Traccia")), 1, 0)
        gl_src.addWidget(self.lbl_track, 1, 1, 1, 2)

        root.addWidget(gb_src)

        gb_prev = QtWidgets.QGroupBox(L("Preview"), self)
        vl_prev = QtWidgets.QVBoxLayout(gb_prev)
        vl_prev.setContentsMargins(8, 8, 8, 8)
        vl_prev.setSpacing(8)

        self.preview_host = QtWidgets.QFrame(self)
        self.preview_host.setMinimumSize(700, 280)
        self.preview_host.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.preview_host.setStyleSheet("QFrame { background: #000; border: 1px solid #444; }")
        self.preview_host.setAttribute(Qt.WA_NativeWindow, True)
        self.preview_host.setAttribute(Qt.WA_DontCreateNativeAncestors, True)

        self.lbl_pos = QtWidgets.QLabel("00:00:00 / 00:00:00", self)
        self.lbl_pos.setAlignment(Qt.AlignCenter)
        self.lbl_pos.setMinimumHeight(24)
        self.lbl_pos.setMaximumHeight(24)
        self.lbl_pos.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.lbl_pos.setStyleSheet("QLabel { padding-top: 2px; padding-bottom: 2px; color: palette(window-text); background: transparent; }")

        vl_prev.addWidget(self.preview_host, 1)
        vl_prev.addWidget(self.lbl_pos, 0)

        root.addWidget(gb_prev, 1)

        nav = QtWidgets.QHBoxLayout()
        self.btn_back_big = QtWidgets.QPushButton("<<", self)
        self.btn_back_small = QtWidgets.QPushButton("<", self)
        self.btn_play_pause = QtWidgets.QPushButton(L("Play"), self)
        self.btn_fwd_small = QtWidgets.QPushButton(">", self)
        self.btn_fwd_big = QtWidgets.QPushButton(">>", self)
        self.lbl_volume = QtWidgets.QLabel(L("Vol"), self)
        self.sld_volume = QtWidgets.QSlider(Qt.Horizontal, self)
        self.sld_volume.setMinimum(0)
        self.sld_volume.setMaximum(100)
        self.sld_volume.setValue(70)
        self.sld_volume.setMinimumWidth(72)
        self.sld_volume.setMaximumWidth(82)
        self.sld_volume.setToolTip(L("Volume preview audio"))

        self.sld_pos = QtWidgets.QSlider(Qt.Horizontal, self)
        self.sld_pos.setMinimum(0)
        self.sld_pos.setMaximum(0)
        self.sld_pos.setMinimumWidth(260)
        self.sld_pos.setToolTip(L("Posizione nel file"))

        for b in (self.btn_back_big, self.btn_back_small, self.btn_play_pause, self.btn_fwd_small, self.btn_fwd_big):
            b.setMinimumHeight(22)
            b.setMaximumHeight(22)

        nav.addWidget(self.btn_back_big)
        nav.addWidget(self.btn_back_small)
        nav.addWidget(self.btn_play_pause)
        nav.addWidget(self.btn_fwd_small)
        nav.addWidget(self.btn_fwd_big)
        nav.addSpacing(8)
        nav.addWidget(self.lbl_volume)
        nav.addWidget(self.sld_volume)
        nav.addSpacing(8)
        nav.addWidget(self.sld_pos, 1)
        root.addLayout(nav)

        gb_an = QtWidgets.QGroupBox(L("Analisi"), self)
        gl_an = QtWidgets.QGridLayout(gb_an)
        gl_an.setContentsMargins(8, 8, 8, 8)
        gl_an.setHorizontalSpacing(6)
        gl_an.setVerticalSpacing(4)

        self.time_start = QtWidgets.QTimeEdit(self)
        self.time_start.setDisplayFormat("HH:mm:ss")
        self.time_start.setWrapping(True)
        hh = int(start_sec // 3600)
        mm = int((start_sec % 3600) // 60)
        ss = int(start_sec % 60)
        self.time_start.setTime(QtCore.QTime(hh, mm, ss))

        self.cmb_dur = QtWidgets.QComboBox(self)
        for sec in (10, 15, 20, 30, 45, 60, 90, 120, 150, 180):
            self.cmb_dur.addItem(f"{sec} s", sec)
        idx = self.cmb_dur.findData(int(duration_sec))
        if idx < 0:
            idx = self.cmb_dur.findData(20)
        if idx >= 0:
            self.cmb_dur.setCurrentIndex(idx)

        self.btn_use_current = QtWidgets.QPushButton(L("Usa posizione corrente"), self)
        self.btn_preview_raw = QtWidgets.QPushButton(L("Preview tratto"), self)
        self.btn_analyze = QtWidgets.QPushButton(L("Analizza"), self)
        self.btn_preview_nr = QtWidgets.QPushButton(L("Preview con NR"), self)
        self.btn_back_source = QtWidgets.QPushButton(L("Torna al sorgente"), self)

        for _w in (
            self.time_start,
            self.cmb_dur,
            self.btn_use_current,
            self.btn_preview_raw,
            self.btn_analyze,
            self.btn_preview_nr,
            self.btn_back_source,
        ):
            try:
                _w.setMinimumHeight(22)
                _w.setMaximumHeight(22)
            except Exception:
                pass

        # player: piccoli per lasciare aria agli slider
        for _b, _mw, _xw in (
            (self.btn_back_big, 30, 30),
            (self.btn_back_small, 30, 30),
            (self.btn_play_pause, 54, 54),
            (self.btn_fwd_small, 30, 30),
            (self.btn_fwd_big, 30, 30),
        ):
            try:
                _b.setMinimumHeight(22)
                _b.setMaximumHeight(22)
                _b.setMinimumWidth(_mw)
                _b.setMaximumWidth(_xw)
            except Exception:
                pass

        # analisi: niente tagli di testo
        for _b, _mw, _xw in (
            (self.btn_use_current, 162, 162),
            (self.btn_preview_raw, 116, 116),
            (self.btn_analyze, 96, 96),
            (self.btn_preview_nr, 128, 128),
            (self.btn_back_source, 142, 142),
        ):
            try:
                _b.setMinimumHeight(22)
                _b.setMaximumHeight(22)
                _b.setMinimumWidth(_mw)
                _b.setMaximumWidth(_xw)
            except Exception:
                pass

        try:
            self.time_start.setMinimumWidth(128)
            self.time_start.setMaximumWidth(128)
            self.cmb_dur.setMinimumWidth(96)
            self.cmb_dur.setMaximumWidth(96)
        except Exception:
            pass

        try:
            self.lbl_volume.setMinimumWidth(22)
            self.lbl_volume.setMaximumWidth(22)
        except Exception:
            pass

        # tooltip
        try:
            self.btn_back_big.setToolTip(L("Indietro di 1 secondo"))
            self.btn_back_small.setToolTip(L("Indietro di 100 ms"))
            self.btn_play_pause.setToolTip(L("Play/Pausa"))
            self.btn_fwd_small.setToolTip(L("Avanti di 100 ms"))
            self.btn_fwd_big.setToolTip(L("Avanti di 1 secondo"))
            self.btn_use_current.setToolTip(L("Copia la posizione corrente dentro Start analisi"))
            self.btn_preview_raw.setToolTip(L("Riproduce il tratto RAW senza denoise"))
            self.btn_analyze.setToolTip(L("Analizza il tratto RAW e propone nr/nf"))
            self.btn_preview_nr.setToolTip(L("Crea una preview temporanea con il denoise applicato"))
            self.btn_back_source.setToolTip(L("Ricarica il file sorgente normale"))
            self.time_start.setToolTip(L("Punto iniziale del tratto da ascoltare e analizzare"))
            self.cmb_dur.setToolTip(L("Durata del tratto di analisi"))
        except Exception:
            pass

        gl_an.addWidget(QtWidgets.QLabel(L("Start analisi")), 0, 0)
        gl_an.addWidget(self.time_start, 0, 1)
        gl_an.addWidget(QtWidgets.QLabel(L("Durata analisi")), 0, 2)
        gl_an.addWidget(self.cmb_dur, 0, 3)
        gl_an.addWidget(self.btn_use_current, 0, 4)

        gl_an.addWidget(self.btn_preview_raw, 1, 1)
        gl_an.addWidget(self.btn_analyze, 1, 2)
        gl_an.addWidget(self.btn_preview_nr, 1, 3)
        gl_an.addWidget(self.btn_back_source, 1, 4)

        root.addWidget(gb_an)

        self.txt_result = QtWidgets.QTextEdit(self)
        self.txt_result.setReadOnly(True)
        self.txt_result.setMinimumHeight(88)
        self.txt_result.setMaximumHeight(110)
        root.addWidget(self.txt_result)

        gb_params = QtWidgets.QGroupBox(L("Parametri finali"), self)
        form = QtWidgets.QFormLayout(gb_params)
        form.setContentsMargins(8, 8, 8, 8)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(4)

        self.ed_nr = QtWidgets.QLineEdit(self)
        self.ed_nr.setPlaceholderText(L("0.01–97 dB"))
        self.ed_nf = QtWidgets.QLineEdit(self)
        self.ed_nf.setPlaceholderText(L("-80 … -20 dB"))

        for _w in (self.ed_nr, self.ed_nf):
            try:
                _w.setMinimumHeight(22)
                _w.setMaximumHeight(22)
            except Exception:
                pass

        form.addRow(L("Noise reduction nr:"), self.ed_nr)
        form.addRow(L("Noise floor nf:"), self.ed_nf)
        root.addWidget(gb_params)

        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, parent=self)
        try:
            bb.button(QtWidgets.QDialogButtonBox.Ok).setText(L("Applica a SAG"))
            bb.button(QtWidgets.QDialogButtonBox.Cancel).setText(L("Annulla"))

            _bok = bb.button(QtWidgets.QDialogButtonBox.Ok)
            _bcn = bb.button(QtWidgets.QDialogButtonBox.Cancel)
            for _b, _mw, _xw in ((_bcn, 100, 100), (_bok, 112, 112)):
                _b.setMinimumHeight(22)
                _b.setMaximumHeight(22)
                _b.setMinimumWidth(_mw)
                _b.setMaximumWidth(_xw)
        except Exception:
            pass
        bb.accepted.connect(self._on_accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._geom_restored:
            self._geom_restored = True
            try:
                w = int(self._settings.value("window_width", 820))
                h = int(self._settings.value("window_height", 760))
            except Exception:
                w, h = 640, 826
            w = max(600, w)
            h = max(700, h)
            self.resize(w, h)
            try:
                hint = self.sizeHint()
                if hint.width() > self.width() or hint.height() > self.height():
                    self.resize(max(self.width(), hint.width()), max(self.height(), hint.height()))
            except Exception:
                pass
        self._init_player_if_needed()
        try:
            QtCore.QTimer.singleShot(0, self._normalize_initial_layout)
        except Exception:
            pass

    def closeEvent(self, event) -> None:
        try:
            if not self.isMaximized() and not self.isMinimized():
                self._settings.setValue("window_width", int(self.width()))
                self._settings.setValue("window_height", int(self.height()))
        except Exception:
            pass
        try:
            self._poll_timer.stop()
        except Exception:
            pass
        try:
            if self._player is not None:
                try:
                    self._player.command("stop")
                except Exception:
                    pass
                try:
                    self._player.terminate()
                except Exception:
                    pass
        except Exception:
            pass
        self._player = None
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        try:
            if self.isVisible() and not self.isMaximized() and not self.isMinimized():
                self._settings.setValue("window_width", int(self.width()))
                self._settings.setValue("window_height", int(self.height()))
        except Exception:
            pass

    def _wire_signals(self) -> None:
        self.btn_back_big.clicked.connect(lambda: self._seek_relative(-1.0))
        self.btn_back_small.clicked.connect(lambda: self._seek_relative(-0.1))
        self.btn_fwd_small.clicked.connect(lambda: self._seek_relative(+0.1))
        self.btn_fwd_big.clicked.connect(lambda: self._seek_relative(+1.0))
        self.btn_play_pause.clicked.connect(self._toggle_playback)
        self.sld_volume.valueChanged.connect(self._on_volume_changed)
        self.sld_pos.sliderPressed.connect(self._on_slider_pressed)
        self.sld_pos.sliderReleased.connect(self._on_slider_released)
        self.sld_pos.valueChanged.connect(self._on_slider_value_changed)
        self._poll_timer.timeout.connect(self._on_poll_timer)
        self._seek_timer.timeout.connect(self._flush_pending_seek)

        self.btn_help.clicked.connect(self._show_help)
        self.btn_use_current.clicked.connect(self._set_start_from_current)
        self.btn_preview_raw.clicked.connect(self._preview_raw_segment)
        self.btn_analyze.clicked.connect(self._on_analyze)
        self.btn_preview_nr.clicked.connect(self._preview_with_nr)
        self.btn_back_source.clicked.connect(self._load_source_media)

    def _init_player_if_needed(self) -> None:
        _force_c_numeric_locale()
        if self._player_inited:
            return
        wid = int(self.preview_host.winId())
        self._player = mpv.MPV(
            wid=str(wid),
            osc=False,
            input_default_bindings=False,
            input_vo_keyboard=False,
            cursor_autohide="no",
            keep_open="always",
            force_window="yes",
            audio_display="no",
            pause=True,
        )
        self._player_inited = True
        try:
            self._player.volume = int(self.sld_volume.value())
        except Exception:
            pass
        self._load_media(self._source_path)
        self._poll_timer.start()
        QtCore.QTimer.singleShot(150, lambda: self._seek_to_sec(self._start_sec(), exact=True))


    def _normalize_initial_layout(self) -> None:
        try:
            self.layout().activate()
        except Exception:
            pass
        try:
            self.preview_host.updateGeometry()
            self.lbl_pos.updateGeometry()
            self.lbl_pos.repaint()
        except Exception:
            pass

    def _load_media(self, path: str) -> None:
        if self._player is None:
            return
        self._preview_stop_sec = None
        self._player.command("loadfile", str(path), "replace")
        self._set_play_pause_text(True)

    def _load_source_media(self) -> None:
        self._load_media(self._source_path)
        QtCore.QTimer.singleShot(150, lambda: self._seek_to_sec(self._start_sec(), exact=True))

    def _fmt_sec(self, sec: float) -> str:
        ms = max(0, int(float(sec) * 1000.0))
        h = ms // 3600000
        ms -= h * 3600000
        m = ms // 60000
        ms -= m * 60000
        s = ms // 1000
        return f"{h:02d}:{m:02d}:{s:02d}"

    def _current_sec(self) -> float:
        try:
            if self._player is not None and self._player.time_pos is not None:
                return float(self._player.time_pos)
        except Exception:
            pass
        return 0.0

    def _duration_sec(self) -> float:
        try:
            if self._player is not None and self._player.duration is not None:
                return float(self._player.duration)
        except Exception:
            pass
        return 0.0

    def _seek_to_sec(self, sec: float, *, exact: bool = False) -> None:
        if self._player is None:
            return
        sec = max(0.0, float(sec or 0.0))
        try:
            if exact:
                self._player.command("seek", sec, "absolute", "exact")
            else:
                self._player.command("seek", sec, "absolute")
        except Exception:
            pass

    def _seek_relative(self, delta_sec: float) -> None:
        self._seek_to_sec(self._current_sec() + float(delta_sec or 0.0))

    def _set_play_pause_text(self, paused: bool) -> None:
        try:
            self.btn_play_pause.setText(L("Play") if paused else L("Pause"))
        except Exception:
            pass

    def _toggle_playback(self) -> None:
        if self._player is None:
            return
        try:
            paused = bool(getattr(self._player, "pause", True))
            new_paused = (not paused)
            self._player.pause = new_paused
            self._set_play_pause_text(new_paused)
        except Exception:
            pass

    def _on_volume_changed(self, value: int) -> None:
        try:
            if self._player is not None:
                self._player.volume = int(value)
        except Exception:
            pass

    def _on_slider_pressed(self) -> None:
        self._slider_dragging = True

    def _on_slider_released(self) -> None:
        self._slider_dragging = False
        self._pending_seek_sec = float(self.sld_pos.value())
        self._flush_pending_seek()

    def _on_slider_value_changed(self, value: int) -> None:
        if self._slider_dragging:
            self.lbl_pos.setText(f"{self._fmt_sec(value)} / {self._fmt_sec(self._duration_sec())}")
            self._pending_seek_sec = float(value)
            try:
                self._seek_timer.start()
            except Exception:
                self._flush_pending_seek()

    def _flush_pending_seek(self) -> None:
        sec = self._pending_seek_sec
        self._pending_seek_sec = None
        if sec is None:
            return
        self._seek_to_sec(float(sec))

    def _on_poll_timer(self) -> None:
        cur = self._current_sec()
        dur = self._duration_sec()
        self.lbl_pos.setText(f"{self._fmt_sec(cur)} / {self._fmt_sec(dur)}")
        if not self._slider_dragging:
            try:
                self.sld_pos.blockSignals(True)
                self.sld_pos.setMaximum(max(0, int(dur)))
                self.sld_pos.setValue(max(0, min(int(cur), int(dur) if dur > 0 else int(cur))))
                self.sld_pos.blockSignals(False)
            except Exception:
                pass

        if self._preview_stop_sec is not None and cur >= float(self._preview_stop_sec):
            try:
                if self._player is not None:
                    self._player.pause = True
                    self._set_play_pause_text(True)
            except Exception:
                pass
            self._preview_stop_sec = None

    def _start_sec(self) -> int:
        try:
            t = self.time_start.time()
            return int(t.hour()) * 3600 + int(t.minute()) * 60 + int(t.second())
        except Exception:
            return 0

    def _analysis_duration(self) -> int:
        try:
            v = int(self.cmb_dur.currentData() or 20)
            return max(5, v)
        except Exception:
            return 20

    def _show_help(self) -> None:
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(L("Manuale Noise reduction"))
        dlg.resize(760, 560)
        dlg.setMinimumSize(700, 500)

        lay = QtWidgets.QVBoxLayout(dlg)
        view = QtWidgets.QTextBrowser(dlg)
        view.setOpenExternalLinks(True)
        view.setHtml(self._help_html())
        lay.addWidget(view, 1)

        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok, parent=dlg)
        bb.accepted.connect(dlg.accept)
        lay.addWidget(bb)

        try:
            dlg.exec()
        except Exception:
            dlg.exec_()

    def _help_html(self) -> str:
        return """
        <h2>Noise reduction: come si usa</h2>
        <p>Questa finestra serve per trovare un denoise sensato senza andare a tentoni.</p>

        <h3>Idea semplice</h3>
        <ol>
          <li>Vai in un punto del film dove senti bene il rumore di fondo.</li>
          <li>Premi <b>Preview tratto</b> per ascoltare quel pezzo.</li>
          <li>Se il punto ti sembra buono, premi <b>Analizza</b>.</li>
          <li>Il programma ti propone dei valori iniziali per <b>nr</b> e <b>nf</b>.</li>
          <li>Premi <b>Preview con NR</b> per sentire il risultato.</li>
          <li>Se ti piace, premi <b>Applica a SAG</b>.</li>
        </ol>

        <h3>Cosa fanno i pulsanti</h3>
        <ul>
          <li><b>&lt;&lt; / &lt; / &gt; / &gt;&gt;</b>: spostano il punto corrente nel file.</li>
          <li><b>Play / Pause</b>: avvia o mette in pausa il player.</li>
          <li><b>Usa posizione corrente</b>: copia il punto dove sei fermo dentro Start analisi.</li>
          <li><b>Preview tratto</b>: riproduce il pezzo RAW, senza denoise.</li>
          <li><b>Analizza</b>: misura il tratto RAW e propone valori iniziali.</li>
          <li><b>Preview con NR</b>: crea una preview temporanea con il denoise applicato.</li>
          <li><b>Torna al sorgente</b>: ricarica il file normale dopo una preview con NR.</li>
          <li><b>Applica a SAG</b>: salva i valori e li usa nella stringa finale.</li>
        </ul>

        <h3>Come scegliere il punto giusto</h3>
        <ul>
          <li>Meglio un punto con poco parlato, poca musica e rumore abbastanza chiaro.</li>
          <li>Evita scene con esplosioni, colonna sonora o urla, perché falsano l’analisi.</li>
          <li>Se il risultato non ti convince, cambia punto e rifai l’analisi.</li>
        </ul>

        <h3>Significato dei parametri</h3>
        <ul>
          <li><b>nr</b>: quanta riduzione rumore applicare.</li>
          <li><b>nf</b>: dove si trova il rumore di fondo stimato.</li>
        </ul>

        <p><b>Importante:</b> i valori proposti sono un punto di partenza, non una verità assoluta.</p>
        """

    def _set_start_from_current(self) -> None:
        cur = int(self._current_sec())
        hh = cur // 3600
        mm = (cur % 3600) // 60
        ss = cur % 60
        self.time_start.setTime(QtCore.QTime(hh, mm, ss))

    def _preview_raw_segment(self) -> None:
        self._load_source_media()
        start = self._start_sec()
        dur = self._analysis_duration()
        self._preview_stop_sec = float(start + dur)
        QtCore.QTimer.singleShot(150, lambda: self._seek_to_sec(start, exact=True))
        QtCore.QTimer.singleShot(280, self._play_now)

    def _play_now(self) -> None:
        try:
            if self._player is not None:
                self._player.pause = False
                self._set_play_pause_text(False)
        except Exception:
            pass

    def _current_afftdn_filter(self) -> str:
        nr_txt = (self.ed_nr.text() or "").strip()
        nf_txt = (self.ed_nf.text() or "").strip()
        parts = []

        if nr_txt:
            try:
                nr = float(nr_txt.replace(",", "."))
            except Exception:
                raise ValueError(L("Valore nr non valido."))
            if not (0.01 <= nr <= 97):
                raise ValueError(L("nr deve essere tra 0.01 e 97."))
            parts.append(f"nr={nr:.1f}")

        if nf_txt:
            try:
                nf = float(nf_txt.replace(",", "."))
            except Exception:
                raise ValueError(L("Valore nf non valido."))
            if not (-80 <= nf <= -20):
                raise ValueError(L("nf deve essere tra -80 e -20."))
            parts.append(f"nf={nf:.1f}")

        if not parts:
            raise ValueError(L("Inserisci almeno nr o nf, oppure usa Analizza."))
        return "afftdn=" + ":".join(parts)

    def _preview_with_nr(self) -> None:
        try:
            af = self._current_afftdn_filter()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, L("Errore"), str(e))
            return

        ffmpeg_bin = getattr(C, "FFMPEG_BIN", None) or shutil.which("ffmpeg") or "ffmpeg"
        start = self._start_sec()
        dur = self._analysis_duration()
        out_file = self._tmp_preview_file

        cmd = [ffmpeg_bin, "-hide_banner", "-nostdin", "-loglevel", "error", "-y"]
        if start > 0:
            cmd += ["-ss", str(start)]
        cmd += ["-i", self._source_path, "-t", str(dur), "-map", "0:v:0?"]
        if self._map_spec:
            cmd += ["-map", str(self._map_spec)]
        cmd += ["-sn", "-dn", "-af", af, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", str(out_file)]

        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if p.returncode != 0 or not out_file.is_file():
            QtWidgets.QMessageBox.warning(
                self,
                L("Errore"),
                L("Impossibile creare la preview con denoise:") + "\n" + ((p.stderr or "").strip() or "?"),
            )
            return

        self._load_media(str(out_file))
        self._preview_stop_sec = float(dur)
        QtCore.QTimer.singleShot(220, self._play_now)

    def _on_analyze(self) -> None:
        self.txt_result.setPlainText(L("Analisi in corso…"))
        try:
            QtWidgets.QApplication.processEvents()
        except Exception:
            pass

        res = analyze_noise_segment(
            self._source_path,
            self._map_spec,
            self._start_sec(),
            self._analysis_duration(),
        )
        if not res.get("ok"):
            QtWidgets.QMessageBox.warning(
                self,
                L("Errore"),
                L("Analisi noise reduction non riuscita:") + "\n" + str(res.get("error") or "?"),
            )
            return

        self.txt_result.setPlainText(str(res.get("summary") or ""))
        self.ed_nr.setText(str(res.get("nr") or ""))
        self.ed_nf.setText(str(res.get("nf") or ""))

    def _cfg_from_ui(self) -> dict:
        nr = None
        nf = None

        nr_txt = (self.ed_nr.text() or "").strip()
        if nr_txt:
            nr = float(nr_txt.replace(",", "."))
            if not (0.01 <= nr <= 97):
                raise ValueError(L("nr deve essere tra 0.01 e 97."))

        nf_txt = (self.ed_nf.text() or "").strip()
        if nf_txt:
            nf = float(nf_txt.replace(",", "."))
            if not (-80 <= nf <= -20):
                raise ValueError(L("nf deve essere tra -80 e -20."))

        if nr is None and nf is None:
            raise ValueError(L("Inserisci almeno nr o nf, oppure usa Analizza."))

        return {
            "nr": None if nr is None else f"{nr:.1f}",
            "nf": None if nf is None else f"{nf:.1f}",
            "summary": self.txt_result.toPlainText().strip(),
            "start_sec": self._start_sec(),
            "duration_sec": self._analysis_duration(),
        }

    def _on_accept(self) -> None:
        try:
            self._cfg = self._cfg_from_ui()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, L("Errore"), str(e))
            return
        self.accept()

    def get_config(self) -> dict:
        return dict(self._cfg or {})
