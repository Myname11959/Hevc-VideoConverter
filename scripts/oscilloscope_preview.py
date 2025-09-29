#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Oscilloscopio multi-canale (verticale) per preview audio.

- Disposizione VERTICALE: un frame (label + onda) per canale, in colonna.
- Dimensione finestra *dinamica* in base al numero di canali.
- Barra bottoni a larghezza piena (Expanding).
- Nessun autoplay; stop certo e cleanup del WAV alla chiusura.

API:
    PreviewDialog(
        audio_file: str,
        parent=None,
        *,
        channel_layout: str | None = "stereo",
        channel_names: list[str] | None = None,
        auto_cleanup: bool = True,
    )

Nota: lo scope mostra i canali del WAV che gli passi. Se il tuo preview genera 5.0,
passa channel_names=['L','R','C','SL','SR'] (o channel_layout='5.0' se usi la mappa sotto).
"""

import os

os.environ["PYQTGRAPH_QT_LIB"] = "PyQt5"  # per pyqtgraph

import ctypes
import numpy as np
import pyqtgraph as pg

from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QSlider,
    QLabel,
    QScrollArea,
    QSizePolicy,
)
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent, QAudioProbe

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
    # se non presente, ripiega su "stereo"
    return list(L.get(layout, L["stereo"]))


def _color_for(ch: str) -> str:
    Cmap = _C_COLORS or _DEFAULT_COLORS
    return Cmap.get(ch, "white")


class Oscilloscope(QWidget):
    """
    Oscilloscopio multi-canale con layout VERTICALE:
    per ogni canale -> Label + PlotWidget in colonna.
    """

    # altezza “target” per un canale (label + plot + spazi)
    PER_CH_HEIGHT = 120  # px circa
    PLOT_MIN_H = 95

    def __init__(
        self,
        parent=None,
        *,
        channel_layout: str | None = None,
        channel_names: list[str] | None = None,
    ):
        super().__init__(parent)

        # Determina i canali richiesti
        names = _layout_names(channel_layout, channel_names)
        self.channel_names = names
        self.nch = len(names)

        # UI: scroll area verticale con una sezione per canale
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        outer.addWidget(self.scroll, stretch=1)

        content = QWidget(self.scroll)
        self.scroll.setWidget(content)

        vbox = QVBoxLayout(content)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.setSpacing(10)

        self.plots = []
        self.curves = []
        self.buffers = []

        for ch_name in names:
            # Etichetta canale
            color = _color_for(ch_name)
            lab = QLabel(f"◉ {ch_name}", alignment=Qt.AlignLeft)
            vbox.addWidget(lab)

            # Plot
            pw = pg.PlotWidget(parent=self)
            pw.setBackground((24, 24, 24))
            pw.setYRange(-1, 1)
            pw.setMouseEnabled(False, False)
            pw.hideAxis("bottom")
            pw.hideAxis("left")
            pw.plotItem.setClipToView(True)
            pw.plotItem.setDownsampling(mode="peak")
            curve = pw.plot(pen=pg.mkPen(color, width=1))
            curve.setClipToView(True)

            # Ogni plot cresce in larghezza, ma ha altezza fissa “comoda”
            pw.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            pw.setMinimumHeight(self.PLOT_MIN_H)

            vbox.addWidget(pw)

            self.plots.append(pw)
            self.curves.append(curve)
            self.buffers.append(np.zeros(1024, dtype=np.float32))

    def set_channel_layout(self, layout: str | None = None, names: list[str] | None = None):
        """
        Reimposta canali/etichette SENZA dover ricreare il widget esterno.
        Se preferisci rimpiazzare il widget (come fa la PreviewDialog) va bene lo stesso.
        """
        new_names = _layout_names(layout, names)
        self.channel_names = new_names
        self.nch = len(new_names)

        # Se il numero cambia, è più semplice ricostruire i plot
        for pw in self.plots:
            pw.setParent(None)
            pw.deleteLater()
        self.plots.clear()
        self.curves.clear()
        self.buffers.clear()

        # Aggiungi nuovi plot
        layout_obj = self.findChild(QScrollArea).widget().layout()  # layout del contenitore interno
        for ch_name in new_names:
            color = _color_for(ch_name)
            lab = QLabel(f"◉ {ch_name}", alignment=Qt.AlignLeft)
            layout_obj.addWidget(lab)

            pw = pg.PlotWidget(parent=self)
            pw.setBackground((24, 24, 24))
            pw.setYRange(-1, 1)
            pw.setMouseEnabled(False, False)
            pw.hideAxis("bottom")
            pw.hideAxis("left")
            pw.plotItem.setClipToView(True)
            pw.plotItem.setDownsampling(mode="peak")
            curve = pw.plot(pen=pg.mkPen(color, width=1))
            curve.setClipToView(True)

            pw.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            pw.setMinimumHeight(self.PLOT_MIN_H)

            layout_obj.addWidget(pw)

            self.plots.append(pw)
            self.curves.append(curve)
            self.buffers.append(np.zeros(1024, dtype=np.float32))

    def recommended_height(self) -> int:
        """Altezza finestra consigliata per la sola parte di canali."""
        return max(2 * self.PLOT_MIN_H, self.nch * self.PER_CH_HEIGHT)

    @staticmethod
    def _update_array(old: np.ndarray, new: np.ndarray) -> np.ndarray:
        n = len(new)
        if n >= len(old):
            return new[-len(old) :]
        old = np.roll(old, -n)
        old[-n:] = new
        return old

    def update_buffer(self, buffer):
        """QAudioProbe -> aggiorna i canali (PCM interlacciato)."""
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

        # Mappa indici “standard”: FL FR FC LFE SL SR
        if actual_ch == 1:
            std_map = {"M": 0, "L": 0, "R": 0}
        elif actual_ch == 2:
            std_map = {"L": 0, "R": 1}
        elif actual_ch >= 6:
            std_map = {"L": 0, "R": 1, "C": 2, "LFE": 3, "SL": 4, "SR": 5}
        else:
            # 3/4/5 canali: usa gli indici disponibili in ordine
            std_map = {name: min(i, actual_ch - 1) for i, name in enumerate(self.channel_names)}

        for i, name in enumerate(self.channel_names):
            idx = std_map.get(name, 0)
            chan = frames[:, idx].astype(np.float32) / 32768.0
            self.buffers[i] = self._update_array(self.buffers[i], chan)
            self.curves[i].setData(self.buffers[i])


class PreviewDialog(QDialog):
    """
    Dialog di preview con player+probe e Oscilloscope multi-canale (verticale).
    Nessun autoplay; stop certo alla chiusura; auto-cleanup del WAV.
    Supporta resize dinamico via set_channel_layout().
    """

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

        # Oscilloscopio verticale
        self.osc = Oscilloscope(
            self,
            channel_layout=channel_layout,
            channel_names=channel_names,
        )

        # Player & Probe (nessun autoplay)
        self.player = QMediaPlayer(self)
        self.player.setMedia(QMediaContent(QUrl.fromLocalFile(self.audio_file)))
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

    # ---------------- UI ----------------

    def _build_ui(self):
        self._main = QVBoxLayout(self)  # memorizzo il layout per sostituzioni future
        self._main.addWidget(self.osc, stretch=1)

        # Barra tempo + label
        bottom = QHBoxLayout()
        self.slider = QSlider(Qt.Horizontal, self)
        self.slider.setRange(0, 1)
        self.time_label = QLabel("00:00 / 00:00", self)
        self.time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        bottom.addWidget(self.slider, 1)
        bottom.addWidget(self.time_label, 0)
        self._main.addLayout(bottom)

        # Bottoni (Expanding -> riempiono tutta la riga)
        btn_layout = QHBoxLayout()

        def _btn(text):
            b = QPushButton(text, self)
            b.setAutoDefault(False)
            b.setMinimumHeight(32)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            return b

        self.btn_play = _btn("Play")
        self.btn_pause = _btn("Pause")
        self.btn_stop = _btn("Stop")
        self.btn_prev = _btn('« 5"')
        self.btn_next = _btn('5" »')
        self.btn_close = _btn("Chiudi")

        for b in (
            self.btn_play,
            self.btn_pause,
            self.btn_stop,
            self.btn_prev,
            self.btn_next,
            self.btn_close,
        ):
            btn_layout.addWidget(b, 1)

        self._main.addLayout(btn_layout)

    def _apply_initial_size(self):
        ch_h = self.osc.recommended_height()
        other = 48 + 56 + 32  # slider + label + bottoni
        target_h = ch_h + other
        target_w = 900 if self.osc.nch >= 2 else 720
        try:
            desk = QApplication.desktop()
            avail = desk.availableGeometry(self)
            target_w = min(avail.width() - 80, max(680, target_w))
            target_h = min(avail.height() - 80, max(360, target_h))
        except Exception:
            target_w = max(680, target_w)
            target_h = max(360, target_h)
        self.resize(int(target_w), int(target_h))

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

    # --------- resize on-the-fly ----------
    def set_channel_layout(self, layout: str | None = None, names: list[str] | None = None):
        """Ricrea l'oscilloscopio con un nuovo layout (es. 'stereo' ↔ '5.1') e ridimensiona la finestra."""
        # 1) Sgancia il probe dall'osc attuale
        try:
            self.probe.audioBufferProbed.disconnect(self.osc.update_buffer)
        except Exception:
            pass

        # 2) Crea un nuovo Oscilloscope con il layout richiesto
        new_osc = Oscilloscope(self, channel_layout=layout, channel_names=names)

        # 3) Sostituisci il widget nel layout (stesso slot)
        idx = self._main.indexOf(self.osc)
        if idx < 0:
            idx = 0
        self._main.insertWidget(idx, new_osc, 1)
        self._main.removeWidget(self.osc)
        self.osc.setParent(None)
        self.osc.deleteLater()

        # 4) collega il probe al nuovo osc e applica nuova dimensione
        self.osc = new_osc
        self.probe.audioBufferProbed.connect(self.osc.update_buffer)
        self._apply_initial_size()

    # --------------- Playback helpers ---------------

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
        """Stop certo + rilascio media + auto-cleanup WAV."""
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
                # un piccolo retry se il file fosse ancora impegnato
                from PyQt5.QtCore import QTimer

                QTimer.singleShot(200, lambda p=self.audio_file: (os.path.isfile(p) and os.remove(p)))

    def closeEvent(self, ev):
        # ferma il player
        try:
            self.player.stop()
        except Exception:
            pass
        # elimina il WAV se richiesto
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


# Test rapido
if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)
    wav = os.path.join(TEMP_DIR, "preview_scope.wav")
    # prova con 5.0
    dlg = PreviewDialog(str(wav), None, channel_layout="5.0")
    dlg.exec_()
