#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hevc_gui/gui/color_dialog.py

GUI “come crop”:
- Frame a sinistra (QGraphicsView pulita: no frame, no scrollbar, fit automatico).
- Controlli colore a destra (compatti).
- Sotto al frame: label tempo + slider (largo) + pulsanti ancorati a destra.

Comportamento:
- Il frame di preview viene estratto con ffmpeg al tempo selezionato.
- I parametri colore aggiornano il frame (debounce).
- "Preview filtrata" salva e chiama la preview filtrata sul parent.
- "Applica" salva e CHIUDE (NON lancia preview: se riparte è main_window).
- "Annulla (spegni)" = clear_color_settings() e chiude.
"""

from __future__ import annotations
from hevc_gui.i18n import L

import os
import subprocess
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPixmap, QPainter, QBrush, QColor
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QCheckBox,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsPixmapItem,
    QWidget,
    QMessageBox,
    QDoubleSpinBox,
    QAbstractSlider,
    QFormLayout,
    QSizePolicy,
    QFrame,
)

from hevc_gui.video.color_tools import (
    load_color_settings,
    save_color_settings,
    clear_color_settings,
)
from hevc_gui.core import constants as C


RAM_DIR = Path("/dev/shm/hevc_gui")
RAM_DIR.mkdir(parents=True, exist_ok=True)
FRAME_PATH = RAM_DIR / "color_frame.png"


class ColorView(QGraphicsView):
    """View pulita stile crop: no bordo, no scrollbar, background nero, fit automatico."""
    def __init__(self, dlg: "ColorDialog"):
        super().__init__(dlg)
        self._dlg = dlg

        self.setRenderHints(
            self.renderHints()
            | QPainter.Antialiasing
            | QPainter.SmoothPixmapTransform
        )
        self.setAlignment(Qt.AlignCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # via il bordo (QFrame) + sfondo nero
        self.setFrameShape(QFrame.NoFrame)
        self.setLineWidth(0)
        self.setMidLineWidth(0)
        self.setStyleSheet("QGraphicsView { background: #000; border: 0px; }")

        self.setFrameShape(QFrame.NoFrame)
        self.setLineWidth(0)
        self.setMidLineWidth(0)
        self.setStyleSheet("QGraphicsView { background: #000; border: 0px; }")
        self.setBackgroundBrush(QBrush(QColor(0, 0, 0)))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._dlg._fit_view()

    def showEvent(self, ev):
        super().showEvent(ev)
        QTimer.singleShot(0, self._dlg._fit_view)


class ColorDialog(QDialog):
    """
    input_path: file video corrente, passato dalla MainWindow.
    grab_time:  secondi iniziali per il frame di preview.
    """

    def __init__(
        self,
        input_path: Optional[str],
        grab_time: float = 10.0,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(L("Luminosità / Colore…"))
        self.setModal(True)

        self.input_path = input_path
        self.grab_time = float(grab_time or 0.0)
        self.src_dur: float = 0.0
        self.pix: Optional[QPixmap] = None

        # scene/view
        self.scene = QGraphicsScene(self)
        self.view = ColorView(self)
        self.view.setScene(self.scene)
        self.img_item = QGraphicsPixmapItem()
        self.scene.addItem(self.img_item)

        # timer debounce (seek + parametri)
        self._seek_timer = QTimer(self)
        self._seek_timer.setSingleShot(True)
        self._seek_timer.timeout.connect(self._grab_frame)

        self._build_ui()

        # init video + slider + ui
        self._load_video_info()
        self._init_time_slider()
        self._load_settings_into_ui()   # comportamento attuale: parte “neutra”
        self._grab_frame()

    # ───────────────── UI ─────────────────

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(10)

        # COLONNA SINISTRA: view + (tempo+slider+pulsanti)
        left = QVBoxLayout()
        left.setSpacing(6)

        self.view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left.addWidget(self.view, 1)

        # bottom row: tempo + slider + pulsanti (a destra)
        self.lbl_time = QLabel(L("00:00 / 00:00"), self)

        self.sld_time = QSlider(Qt.Horizontal, self)
        self.sld_time.setMinimum(0)
        self.sld_time.valueChanged.connect(self._on_seek_changed)
        self.sld_time.actionTriggered.connect(self._on_seek_action)

        self.btn_preview = QPushButton(L("Preview filtrata"), self)
        self.btn_apply = QPushButton(L("Applica"), self)
        self.btn_cancel = QPushButton(L("Annulla (spegni)"), self)

        self.btn_preview.clicked.connect(self._on_preview)
        self.btn_apply.clicked.connect(self._apply)
        self.btn_cancel.clicked.connect(self._on_cancel)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)
        bottom_row.addWidget(self.lbl_time)
        bottom_row.addWidget(self.sld_time, 1)
        bottom_row.addWidget(self.btn_preview)
        bottom_row.addWidget(self.btn_apply)
        bottom_row.addWidget(self.btn_cancel)

        left.addLayout(bottom_row)
        root.addLayout(left, 1)

        # PANNELLO DESTRO: controlli compatti
        right_w = QWidget(self)
        right_w.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        right_w.setMaximumWidth(260)

        right = QVBoxLayout(right_w)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(10)

        right.addWidget(QLabel(L("Correzione colore"), self))

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        form.setFormAlignment(Qt.AlignTop)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(10)

        self.sp_bright = self._mk_dspin(-1.0, 1.0, 0.05, 3)
        self.sp_contrast = self._mk_dspin(0.1, 3.0, 0.05, 3)
        self.sp_saturation = self._mk_dspin(0.0, 3.0, 0.05, 3)
        self.sp_gamma = self._mk_dspin(0.1, 3.0, 0.05, 3)

        form.addRow(L("Luminosità:"), self.sp_bright)
        form.addRow(L("Contrasto:"), self.sp_contrast)
        form.addRow(L("Saturazione:"), self.sp_saturation)
        form.addRow(L("Gamma:"), self.sp_gamma)

        right.addLayout(form)

        self.chk_enable = QCheckBox(L("Abilita correzione colore"), self)
        self.chk_enable.stateChanged.connect(lambda _s: self._seek_timer.start(150))
        right.addWidget(self.chk_enable)

        self.btn_reset = QPushButton(L("Reset valori"), self)
        self.btn_reset.setToolTip(L("Riporta i parametri ai default (non lancia preview)."))
        self.btn_reset.clicked.connect(self._on_reset)
        right.addWidget(self.btn_reset)

        right.addStretch(1)
        root.addWidget(right_w)

        self.resize(1180, 760)

        # collego i cambi parametri dopo aver creato i widget
        for sp in (self.sp_bright, self.sp_contrast, self.sp_saturation, self.sp_gamma):
            sp.valueChanged.connect(self._on_color_param_changed)

    def _mk_dspin(self, mn: float, mx: float, step: float, dec: int) -> QDoubleSpinBox:
        sp = QDoubleSpinBox(self)
        sp.setRange(mn, mx)
        sp.setSingleStep(step)
        sp.setDecimals(dec)
        sp.setAlignment(Qt.AlignRight)
        sp.setKeyboardTracking(False)
        sp.setFixedWidth(120)
        return sp

    # ───────────────── video info / time ─────────────────

    def _load_video_info(self):
        if not self.input_path:
            self.src_dur = 0.0
            return
        try:
            out = subprocess.check_output(
                [
                    getattr(C, "FFPROBE_BIN", "ffprobe"),
                    "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(self.input_path),
                ],
                text=True,
            ).strip()
            self.src_dur = float(out) if out else 0.0
        except Exception:
            self.src_dur = 0.0

    def _init_time_slider(self):
        if self.src_dur and self.src_dur > 1.0:
            self.sld_time.setMaximum(int(self.src_dur))
            t0 = min(int(self.grab_time), int(self.src_dur))
            self.sld_time.setValue(max(0, t0))
            self.lbl_time.setText(self._fmt_time(self.sld_time.value(), self.src_dur))
        else:
            self.sld_time.setMaximum(600)
            self.sld_time.setValue(max(0, int(self.grab_time)))
            self.lbl_time.setText(self._fmt_time(self.sld_time.value(), 0.0))

    def _fmt_time(self, t: int, tot: float = 0.0) -> str:
        def mmss(x):
            m = int(x) // 60
            s = int(x) % 60
            return f"{m:02d}:{s:02d}"
        return f"{mmss(t)} / {mmss(tot)}" if tot and tot > 0 else mmss(t)

    def _on_seek_changed(self, v: int):
        self.grab_time = float(v)
        self.lbl_time.setText(self._fmt_time(v, self.src_dur))
        # condividi offset per altri tool (crop/trim)
        try:
            p = self.parent()
            if p is not None:
                setattr(p, "_preview_offset_sec", float(v))
        except Exception:
            pass
        self._seek_timer.start(200)

    def _on_seek_action(self, action: int):
        if action in (
            QAbstractSlider.SliderSingleStepAdd,
            QAbstractSlider.SliderSingleStepSub,
            QAbstractSlider.SliderPageStepAdd,
            QAbstractSlider.SliderPageStepSub,
            QAbstractSlider.SliderMove,
        ):
            self._seek_timer.start(200)

    # ───────────────── preview frame ─────────────────

    def _build_eq_from_ui(self) -> str:
        if not self.chk_enable.isChecked():
            return ""

        b = float(self.sp_bright.value())
        c = float(self.sp_contrast.value())
        s = float(self.sp_saturation.value())
        g = float(self.sp_gamma.value())

        eps = 1e-3
        parts = []
        if abs(b) > eps:
            parts.append(f"brightness={b:.3f}")
        if abs(c - 1.0) > eps:
            parts.append(f"contrast={c:.3f}")
        if abs(s - 1.0) > eps:
            parts.append(f"saturation={s:.3f}")
        if abs(g - 1.0) > eps:
            parts.append(f"gamma={g:.3f}")

        if not parts:
            return ""
        return "eq=" + ":".join(parts)

    def _grab_frame(self):
        if not self.input_path:
            QMessageBox.warning(self, "Attenzione", L('Seleziona prima un file video nella finestra principale.'))
            return

        FRAME_PATH.parent.mkdir(parents=True, exist_ok=True)

        eq_filter = self._build_eq_from_ui()

        cmd = [
            getattr(C, "FFMPEG_BIN", "ffmpeg"),
            "-hide_banner",
            "-nostdin",
            "-ss", f"{self.grab_time:.2f}",
            "-i", str(self.input_path),
            "-frames:v", "1",
            "-an", "-sn", "-dn",
        ]
        if eq_filter:
            cmd += ["-vf", eq_filter]
        cmd += ["-y", str(FRAME_PATH)]

        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            QMessageBox.critical(self, L("Errore"), L("Impossibile estrarre un frame con ffmpeg."))
            return

        pix = QPixmap(str(FRAME_PATH))
        if pix.isNull():
            QMessageBox.critical(self, L("Errore"), L('Frame non valido.'))
            return

        self.pix = pix
        self.img_item.setPixmap(pix)
        self._fit_view()

    def _fit_view(self):
        if not self.pix:
            return
        try:
            br = self.img_item.boundingRect()
            if br.width() > 0 and br.height() > 0:
                self.view.fitInView(br, Qt.KeepAspectRatio)
        except Exception:
            pass

    # ───────────────── settings ─────────────────

    def _load_settings_into_ui(self):
        """
        Comportamento attuale del tuo progetto:
        apri “neutro” anche se in QSettings c'erano valori salvati.
        """
        self.sp_bright.setValue(0.0)
        self.sp_contrast.setValue(1.0)
        self.sp_saturation.setValue(1.0)
        self.sp_gamma.setValue(1.0)
        self.chk_enable.setChecked(False)

        # se vuoi, puoi rimettere la riga qui sotto per “mostrare” lo stato reale:
        # s = load_color_settings(); ... (ma per ora lasciamo com’è)
        _ = load_color_settings  # keep import used

    def _save_ui_to_settings(self) -> None:
        save_color_settings(
            brightness=float(self.sp_bright.value()),
            contrast=float(self.sp_contrast.value()),
            saturation=float(self.sp_saturation.value()),
            gamma=float(self.sp_gamma.value()),
            enabled=self.chk_enable.isChecked(),
        )

    # ───────────────── actions ─────────────────

    def _on_color_param_changed(self, _value: float):
        if not self.chk_enable.isChecked():
            self.chk_enable.setChecked(True)
        if not self.input_path:
            return
        self._seek_timer.start(200)

    def _on_reset(self):
        self.sp_bright.setValue(0.0)
        self.sp_contrast.setValue(1.0)
        self.sp_saturation.setValue(1.0)
        self.sp_gamma.setValue(1.0)
        self._seek_timer.start(150)

    def _apply(self):
        self._save_ui_to_settings()
        self.accept()

    def _on_cancel(self):
        clear_color_settings()
        self.reject()

    def _on_preview(self):
        self._save_ui_to_settings()

        parent = self.parent()
        if parent is None:
            QMessageBox.warning(self, "Preview", L('Preview filtrata non disponibile (finestra principale assente).'))
            return

        # Preferisci preview_filtered() se c'è
        fn = getattr(parent, "preview_filtered", None)
        if callable(fn):
            try:
                fn()
                return
            except Exception as e:
                QMessageBox.critical(self, L("Preview"), L("Errore Preview filtrata:\n{0}").format(e))
                return

        launch = getattr(parent, "launch_preview", None)
        if not callable(launch):
            QMessageBox.warning(self, "Preview", L("La finestra principale non espone preview_filtered() né launch_preview()."))
            return

        try:
            try:
                launch(filtered=True)
            except TypeError:
                launch(True)
        except Exception as e:
            QMessageBox.critical(self, L("Preview"), L("Errore durante la Preview filtrata:\n{0}").format(e))
