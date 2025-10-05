#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Oscilloscopio multi-canale (verticale) per preview audio — grafica + avvio rapido.

- Una riga per canale (etichetta sinistra + vasca).
- Etichetta compatta a due elementi: NOME (dx) + PALLINO → pallini allineati verticalmente.
- Spazio orizzontale etichetta↔vasca = spazio verticale tra vasche (di default).
- Spazio NOME↔PALLINO = 5px (configurabile via env).
- Nessuna scrollbar: la finestra si dimensiona in base ai canali.
- Auto-fit: niente vuoti sotto le vasche; resize automatico 6ch↔2ch e alla prima apertura.
- Priming muto del player per ridurre la latenza del primo Play (configurabile via env).
- Nessun autoplay; stop certo e cleanup del WAV alla chiusura.
"""

import os

os.environ["PYQTGRAPH_QT_LIB"] = "PyQt5"  # per pyqtgraph

import ctypes
import numpy as np
import pyqtgraph as pg

from PyQt5.QtCore import Qt, QUrl, QTimer
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QSlider,
    QLabel,
    QSizePolicy,
)
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent, QAudioProbe

# ==================== Parametri UI/regolabili (via env) ====================
# Spazio VERTICALE (in px) tra una “vasca” e la successiva
ROW_SPACING = int(os.getenv("HEVC_SCOPE_VSPACE", "10"))

# Spazio ORIZZONTALE (in px) tra etichetta e vasca (default = ROW_SPACING)
_HSPACE_ENV = os.getenv("HEVC_SCOPE_HSPACE", "").strip()
HSPACE = int(_HSPACE_ENV) if _HSPACE_ENV else ROW_SPACING

# Spazio (in px) tra NOME canale e PALLINO nella colonna etichette
NAME_DOT_SPACING = int(os.getenv("HEVC_SCOPE_NDSPACE", "5"))  # ← richiesto: da 4 a 5

# Altezza target (in px) del riquadro nero per ogni waveform
PLOT_H = int(os.getenv("HEVC_SCOPE_WAVE_H", "95"))

# Larghezza (in px) della colonna etichette; 0 = calcolo dinamico
_LABEL_W_ENV = os.getenv("HEVC_SCOPE_LABEL_W", "").strip()
LABEL_W = int(_LABEL_W_ENV) if _LABEL_W_ENV else 0

# Altezza bottoni e slider
BTN_H = int(os.getenv("HEVC_SCOPE_BTN_H", "32"))
SLIDER_H = int(os.getenv("HEVC_SCOPE_SLIDER_H", "12"))

# Larghezze finestra
STEREO_DEF_W = int(os.getenv("HEVC_SCOPE_ST_W", "580"))
MULTI_DEF_W = int(os.getenv("HEVC_SCOPE_MC_W", "900"))

# ====== Priming (riduzione latenza di Play) ======
PRIME_ON = os.getenv("HEVC_SCOPE_PRIME", "1") == "1"
PRIME_MS = max(0, int(os.getenv("HEVC_SCOPE_PRIME_MS", "80")))  # 60–120 ms ok
# ==========================================================================

# --- opzionale: directory temporanea per il test __main__
try:
    from hevc_gui.core.constants import TMP_DIR as TEMP_DIR  # type: ignore
except Exception:
    TEMP_DIR = os.getenv("TMPDIR", "/dev/shm")

# Proviamo a leggere layout/colori centralizzati; altrimenti fallback
try:
    from hevc_gui.core import constants as C  # type: ignore

    _C_LAYOUTS = getattr(C, "CHANNEL_LAYOUTS", None)
    _C_COLORS = getattr(C, "CHANNEL_COLORS", None)
except Exception:
    _C_LAYOUTS = _C_COLORS = None

# Fallback sicuri (aggiungo anche 5.0)
_DEFAULT_LAYOUTS = {
    "mono": ["M"],
    "stereo": ["L", "R"],
    "5.0": ["L", "R", "C", "SL", "SR"],
    "5.1": ["L", "R", "C", "LFE", "SL", "SR"],
}
_DEFAULT_COLORS = {
    "M": "yellow",
    "L": "yellow",
    "R": "cyan",
    "C": "orange",
    "LFE": "magenta",
    "SL": "green",
    "SR": "pink",
}


def _layout_names(layout: str | None, names: list[str] | None) -> list[str]:
    if names:
        return list(names)
    L = _C_LAYOUTS or _DEFAULT_LAYOUTS
    if not layout:
        layout = "stereo"
    return list(L.get(layout, L["stereo"]))


def _color_for(ch: str) -> str:
    Cmap = _C_COLORS or _DEFAULT_COLORS
    return Cmap.get(ch, "white")


def _calc_label_width(names: list[str], widget: QWidget) -> int:
    """Larghezza minima per la colonna etichette = larghezza(NOME più lungo) + spazio + larghezza('●') + padding."""
    if LABEL_W > 0:
        return LABEL_W
    fm = widget.fontMetrics()
    longest = max((n or "L") for n in names) if names else "L"
    dot_w = fm.horizontalAdvance("●")
    name_w = fm.horizontalAdvance(longest)
    # + NAME_DOT_SPACING (richiesta 5px) + un piccolo padding per sicurezza
    w = name_w + NAME_DOT_SPACING + dot_w + 6
    return max(36, min(160, w))


class _ChannelRow(QWidget):
    """Una riga: colonna etichetta (NOME dx + PALLINO) + area plot."""

    def __init__(self, ch_name: str, color: str, label_w: int, hspace: int, parent=None):
        super().__init__(parent)
        hb = QHBoxLayout(self)
        hb.setContentsMargins(6, 0, 6, 0)
        hb.setSpacing(hspace)

        # --- Colonna etichetta composta: [NOME(dx)]  (NAME_DOT_SPACING)  [●] ---
        self.label_col = QWidget(self)
        self.label_col.setMinimumWidth(label_w)
        self.label_col.setMaximumWidth(label_w)
        self.label_col.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        inner = QHBoxLayout(self.label_col)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(NAME_DOT_SPACING)  # ← 5px di default

        self.name_lbl = QLabel(ch_name, self.label_col)
        self.name_lbl.setAlignment(Qt.AlignVCenter | Qt.AlignRight)  # ← allinea a dx: pallini in colonna
        self.name_lbl.setStyleSheet("color:#000; font-weight:600; margin:0; padding:0;")

        self.dot_lbl = QLabel("●", self.label_col)
        self.dot_lbl.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.dot_lbl.setStyleSheet(f"color:{color}; margin:0; padding:0;")

        # opzionale: fissa la larghezza del pallino per una colonna perfetta
        fm = self.dot_lbl.fontMetrics()
        self.dot_lbl.setMinimumWidth(fm.horizontalAdvance("●"))
        self.dot_lbl.setMaximumWidth(fm.horizontalAdvance("●"))

        inner.addWidget(self.name_lbl, 1)
        inner.addWidget(self.dot_lbl, 0)

        # --- Plot (vasca) ---
        self.plot = pg.PlotWidget(self)
        self.plot.setBackground((24, 24, 24))
        self.plot.setYRange(-1, 1)
        self.plot.setMouseEnabled(False, False)
        self.plot.hideAxis("bottom")
        self.plot.hideAxis("left")
        self.plot.plotItem.setClipToView(True)
        self.plot.plotItem.setDownsampling(mode="peak")
        self.plot.setStyleSheet("border:1px solid #666;")

        self.curve = self.plot.plot(pen=pg.mkPen(color, width=1))
        self.plot.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.plot.setMinimumHeight(PLOT_H)
        self.plot.setMaximumHeight(PLOT_H)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(PLOT_H + 2)

        hb.addWidget(self.label_col)  # etichetta stretta
        hb.addWidget(self.plot, 1)  # vasca larga


class Oscilloscope(QWidget):
    """Oscilloscopio multi-canale verticale (etichette a sinistra + vasche)."""

    def __init__(self, parent=None, *, channel_layout: str | None = None, channel_names: list[str] | None = None):
        super().__init__(parent)
        names = _layout_names(channel_layout, channel_names)
        self.channel_names = names
        self.nch = len(names)

        self.label_w = _calc_label_width(names, self)

        self.vbox = QVBoxLayout(self)
        self.vbox.setContentsMargins(8, 8, 8, 8)
        self.vbox.setSpacing(ROW_SPACING)

        self.rows: list[_ChannelRow] = []
        self.curves = []
        self.buffers = []

        for ch_name in names:
            color = _color_for(ch_name)
            row = _ChannelRow(ch_name, color, self.label_w, HSPACE, self)
            self.vbox.addWidget(row)
            self.rows.append(row)
            self.curves.append(row.curve)
            self.buffers.append(np.zeros(1024, dtype=np.float32))

    def channels_block_height(self) -> int:
        if self.nch <= 0:
            return 2 * PLOT_H
        return self.nch * PLOT_H + (self.nch - 1) * ROW_SPACING

    def set_channel_layout(self, layout: str | None = None, names: list[str] | None = None):
        new_names = _layout_names(layout, names)
        self.channel_names = new_names
        self.nch = len(new_names)
        self.label_w = _calc_label_width(new_names, self)

        for r in self.rows:
            r.setParent(None)
            r.deleteLater()
        self.rows.clear()
        self.curves.clear()
        self.buffers.clear()

        for ch_name in new_names:
            color = _color_for(ch_name)
            row = _ChannelRow(ch_name, color, self.label_w, HSPACE, self)
            self.vbox.addWidget(row)
            self.rows.append(row)
            self.curves.append(row.curve)
            self.buffers.append(np.zeros(1024, dtype=np.float32))

    @staticmethod
    def _update_array(old: np.ndarray, new: np.ndarray) -> np.ndarray:
        n = len(new)
        if n >= len(old):
            return new[-len(old) :]
        old = np.roll(old, -n)
        old[-n:] = new
        return old

    def update_buffer(self, buffer):
        """QAudioProbe -> aggiorna i canali (si aspetta PCM 16 bit interlacciato)."""
        try:
            ptr = buffer.constData()
            size = buffer.byteCount()
            raw = ctypes.string_at(int(ptr), size)
            arr = np.frombuffer(raw, dtype=np.int16)
        except Exception:
            return

        actual_ch = max(1, buffer.format().channelCount())
        try:
            frames = arr.reshape(-1, actual_ch)
        except Exception:
            frames = arr.reshape(-1, 1)
            actual_ch = 1

        if actual_ch == 1:
            std_map = {"M": 0, "L": 0, "R": 0}
        elif actual_ch == 2:
            std_map = {"L": 0, "R": 1}
        elif actual_ch >= 6:
            std_map = {"L": 0, "R": 1, "C": 2, "LFE": 3, "SL": 4, "SR": 5}
        else:
            std_map = {name: min(i, actual_ch - 1) for i, name in enumerate(self.channel_names)}

        for i, name in enumerate(self.channel_names):
            idx = std_map.get(name, 0)
            chan = frames[:, idx].astype(np.float32) / 32768.0
            self.buffers[i] = self._update_array(self.buffers[i], chan)
            self.curves[i].setData(self.buffers[i])


class PreviewDialog(QDialog):
    """Dialog di preview con player+probe e Oscilloscope multi-canale."""

    def __init__(
        self,
        audio_file: str,
        parent=None,
        *,
        channel_layout: str | None = None,
        channel_names: list[str] | None = None,
        auto_cleanup: bool = True,
    ):
        super().__init__(parent)
        self.setWindowTitle("Preview Audio con Oscilloscopio")
        self.setAttribute(Qt.WA_DeleteOnClose, True)

        self.audio_file = audio_file
        self._auto_cleanup = bool(auto_cleanup)

        self.osc = Oscilloscope(self, channel_layout=channel_layout, channel_names=channel_names)

        self.player = QMediaPlayer(self)
        self.player.setMedia(QMediaContent(QUrl.fromLocalFile(self.audio_file)))
        self.player.setNotifyInterval(20)
        self.probe = QAudioProbe(self)
        self.probe.setSource(self.player)
        self.probe.audioBufferProbed.connect(self.osc.update_buffer)

        self._build_ui()
        self._connect_signals()

        try:
            self.player.stop()
        except Exception:
            pass

        self._apply_initial_size()

        if PRIME_ON:
            QTimer.singleShot(0, self._prime_pipeline)

    # ---------------- UI ----------------

    def _build_ui(self):
        self._main = QVBoxLayout(self)
        self._main.setContentsMargins(8, 6, 8, 8)
        self._main.setSpacing(6)

        self.osc.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._main.addWidget(self.osc)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(8)

        self.slider = QSlider(Qt.Horizontal, self)
        self.slider.setRange(0, 1)
        self.slider.setFixedHeight(SLIDER_H)

        self.time_label = QLabel("00:00 / 00:00", self)
        self.time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.time_label.setMinimumWidth(120)

        bottom.addWidget(self.slider, 1)
        bottom.addWidget(self.time_label, 0)
        self._main.addLayout(bottom)

        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(8)

        def _btn(text):
            b = QPushButton(text, self)
            b.setAutoDefault(False)
            b.setMinimumHeight(BTN_H)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            return b

        self.btn_play = _btn("Play")
        self.btn_pause = _btn("Pause")
        self.btn_stop = _btn("Stop")
        self.btn_prev = _btn('« 5"')
        self.btn_next = _btn('5" »')
        self.btn_close = _btn("Chiudi")

        for b in (self.btn_play, self.btn_pause, self.btn_stop, self.btn_prev, self.btn_next, self.btn_close):
            btn_layout.addWidget(b, 1)

        self._main.addLayout(btn_layout)

    def _apply_initial_size(self):
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)

        nch = max(1, self.osc.nch)

        m = self.osc.layout().contentsMargins()
        osc_h = self.osc.channels_block_height() + m.top() + m.bottom()
        self.osc.setFixedHeight(osc_h)

        try:
            self.layout().activate()
            self.adjustSize()
        except Exception:
            pass

        target_w = STEREO_DEF_W if nch == 2 else max(MULTI_DEF_W, 720)
        try:
            avail = QApplication.desktop().availableGeometry(self)
            target_h = min(self.height(), avail.height() - 80)
        except Exception:
            target_h = self.height()

        self.resize(int(target_w), int(target_h))

    # ------- AUTO-FIT dopo restoreGeometry esterno / prima apertura -------
    def showEvent(self, ev):
        super().showEvent(ev)
        QTimer.singleShot(0, self._auto_fit_after_restore)

    def _auto_fit_after_restore(self):
        try:
            m = self.osc.layout().contentsMargins()
            osc_h = self.osc.channels_block_height() + m.top() + m.bottom()
            self.osc.setFixedHeight(osc_h)

            self.setMinimumSize(0, 0)
            self.setMaximumSize(16777215, 16777215)
            self.layout().activate()
            self.adjustSize()

            try:
                avail = QApplication.desktop().availableGeometry(self)
                target_h = min(self.height(), avail.height() - 80)
            except Exception:
                target_h = self.height()

            self.resize(self.width(), int(target_h))
        except Exception:
            pass

    # ---------------- Priming per bassa latenza ----------------
    def _prime_pipeline(self):
        """Avvio muto e brevissimo per scaldare device/buffer → Play istantaneo."""
        try:
            self._prime_prev_muted = getattr(self.player, "isMuted", lambda: False)()
            self._prime_prev_vol = self.player.volume()
        except Exception:
            self._prime_prev_muted = False
            self._prime_prev_vol = 100

        try:
            if hasattr(self.player, "setMuted"):
                self.player.setMuted(True)
            else:
                self.player.setVolume(0)
        except Exception:
            pass

        try:
            self.player.play()
        except Exception:
            self._finish_prime()
            return

        QTimer.singleShot(max(10, PRIME_MS), self._finish_prime)

    def _finish_prime(self):
        try:
            self.player.pause()
            self.player.setPosition(0)
        except Exception:
            pass
        try:
            if hasattr(self.player, "setMuted"):
                self.player.setMuted(bool(self._prime_prev_muted))
            else:
                self.player.setVolume(int(self._prime_prev_vol))
        except Exception:
            pass

    # --------------- Playback helpers ---------------
    def _connect_signals(self):
        self.btn_play.clicked.connect(self.player.play)
        self.btn_pause.clicked.connect(self.player.pause)
        self.btn_stop.clicked.connect(self._on_stop)
        self.btn_prev.clicked.connect(lambda: self._jump(-5000))
        self.btn_next.clicked.connect(lambda: self._jump(5000))
        self.btn_close.clicked.connect(self._on_close)

        self.player.positionChanged.connect(self._on_position_changed)
        self.player.durationChanged.connect(self._on_duration_changed)
        self.slider.sliderMoved.connect(lambda p: self.player.setPosition(p))
        self.slider.sliderReleased.connect(lambda: self.player.setPosition(self.slider.value()))

    def _on_stop(self):
        try:
            self.player.stop()
            self.player.setPosition(0)
        except Exception:
            pass

    def _on_close(self):
        self._hard_stop()
        self.close()

    def _hard_stop(self):
        try:
            self.player.stop()
        except Exception:
            pass
        try:
            self.player.setMedia(QMediaContent())
        except Exception:
            pass
        try:
            self.probe.audioBufferProbed.disconnect(self.osc.update_buffer)
        except Exception:
            pass
        if self._auto_cleanup and self.audio_file:
            try:
                if os.path.isfile(self.audio_file):
                    os.remove(self.audio_file)
            except Exception:
                from PyQt5.QtCore import QTimer as _QT

                _QT.singleShot(200, lambda p=self.audio_file: (os.path.isfile(p) and os.remove(p)))

    def closeEvent(self, ev):
        try:
            self.player.stop()
        except Exception:
            pass
        if getattr(self, "_auto_cleanup", False):
            try:
                if os.path.isfile(self.audio_file):
                    os.remove(self.audio_file)
            except Exception:
                pass
        super().closeEvent(ev)

    def _jump(self, ms: int):
        try:
            self.player.setPosition(max(0, self.player.position() + ms))
        except Exception:
            pass

    def _on_position_changed(self, pos: int):
        dur = max(1, self.player.duration() or 1)
        self.slider.blockSignals(True)
        self.slider.setRange(0, dur)
        self.slider.setValue(pos)
        self.slider.blockSignals(False)
        self.time_label.setText(f"{_fmt_ms(pos)} / {_fmt_ms(dur)}")

    def _on_duration_changed(self, dur: int):
        self.slider.setRange(0, max(1, dur or 1))
        self.time_label.setText(f"00:00 / {_fmt_ms(dur or 0)}")


def _fmt_ms(ms: int) -> str:
    s = max(0, int(round(ms / 1000)))
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


# Test rapido (facoltativo)
if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)
    wav = os.path.join(TEMP_DIR, "preview_scope.wav")
    dlg = PreviewDialog(str(wav), None, channel_layout="5.0")
    dlg.exec_()
