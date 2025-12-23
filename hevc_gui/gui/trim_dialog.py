#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hevc_gui/gui/trim_dialog.py

Dialog TRIM (segmento interno da eliminare).

UI stile crop/color:
- Frame a sinistra (QGraphicsView: background nero, no border, no scrollbar, fit automatico)
- Controlli a destra (Enable + SEEK/IN/OUT + bottoni)
- Sotto al frame: label tempo + slider (molto sensibile: millisecondi) + pulsanti ancorati a destra

Fix importanti:
- Frame NON deformato: applico correzione SAR (pixel non quadrati, tipico DVD/SD) nel -vf di ffmpeg:
    scale=trunc(iw*sar/2)*2:ih,setsar=1
  perché PNG non porta metadata SAR e altrimenti vedi “stirato”.

- SEEK spin segue lo slider e viceversa.
- IN/OUT non vengono “forzati” mentre editi (niente OUT che “torna a IN”).
  Controllo validità solo quando premi Preview/Apply.

Preview:
- salva trim settings
- prova a settare mw._preview_offset_sec (se esiste) e chiama mw.launch_preview(filtered=True)
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
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
    QCheckBox,
    QSlider,
    QDoubleSpinBox,
    QMessageBox,
    QWidget,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsPixmapItem,
    QSizePolicy,
    QFormLayout,
    QFrame,
)

# ── dipendenze progetto (con fallback) ─────────────────────────────────────────
try:
    from hevc_gui.video.trim_tools import load_trim_settings, save_trim_settings, clear_trim_settings, TrimSpec
except Exception:  # pragma: no cover
    @dataclass
    class TrimSpec:
        start_sec: float = 0.0
        end_sec: float = 0.0
        enabled: bool = False

    def load_trim_settings() -> TrimSpec:  # type: ignore
        return TrimSpec()

    def save_trim_settings(*args, **kwargs):  # type: ignore
        return None

    def clear_trim_settings(*args, **kwargs):  # type: ignore
        return None

try:
    from hevc_gui.video.crop_tools import load_crop_settings, inject_crop
except Exception:  # pragma: no cover
    def load_crop_settings():  # type: ignore
        return None, False, False, False
    def inject_crop(vf_parts, spec):  # type: ignore
        return None

try:
    from hevc_gui.video.color_tools import build_color_eq_filter
except Exception:  # pragma: no cover
    def build_color_eq_filter(*args, **kwargs):  # type: ignore
        return ""

try:
    from hevc_gui.core import constants as C
    _FFMPEG = getattr(C, "FFMPEG_BIN", "ffmpeg")
    _FFPROBE = getattr(C, "FFPROBE_BIN", "ffprobe")
except Exception:  # pragma: no cover
    _FFMPEG = "ffmpeg"
    _FFPROBE = "ffprobe"


def _fmt_hhmmss_mmm(sec: float) -> str:
    if sec < 0:
        sec = 0.0
    ms = int(round(sec * 1000.0))
    h = ms // 3600000
    ms -= h * 3600000
    m = ms // 60000
    ms -= m * 60000
    s = ms // 1000
    ms -= s * 1000
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _probe_duration(path: Path) -> float:
    try:
        out = subprocess.check_output(
            [
                _FFPROBE, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=nokey=1:noprint_wrappers=1",
                str(path),
            ],
            text=True,
        ).strip()
        return float(out) if out else 0.0
    except Exception:
        return 0.0


class TrimView(QGraphicsView):
    """View pulita: no frame, no scrollbar, background nero, fit automatico."""
    def __init__(self, dlg: "TrimDialog"):
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


class TrimDialog(QDialog):
    def __init__(self, input_path: str, grab_time: float = 10.0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Trim (elimina segmento)")
        self.setModal(True)
        self.resize(1180, 720)

        self._path = Path(input_path) if input_path else None
        self._dur = _probe_duration(self._path) if self._path and self._path.is_file() else 0.0
        if self._dur <= 0:
            self._dur = 1.0

        # stato
        spec = load_trim_settings()
        self._enabled = bool(getattr(spec, "enabled", False))
        self._start_sec = float(getattr(spec, "start_sec", 0.0) or 0.0)
        self._end_sec = float(getattr(spec, "end_sec", 0.0) or 0.0)
        self._seek_sec = float(grab_time or 0.0)
        self._seek_sec = max(0.0, min(self._seek_sec, self._dur))

        self._guard = False
        self._last_pm: Optional[QPixmap] = None

        # scene/view
        self.scene = QGraphicsScene(self)
        self.view = TrimView(self)
        self.view.setScene(self.scene)
        self.img_item = QGraphicsPixmapItem()
        self.scene.addItem(self.img_item)

        # debounce frame grab
        self._t = QTimer(self)
        self._t.setSingleShot(True)
        self._t.timeout.connect(self._refresh_frame)

        self._build_ui()
        self._load_into_ui()
        self._refresh_time_labels()
        self._t.start(10)

    # ───────────────── UI ─────────────────

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(10)

        # sinistra: view + bottom row
        left = QVBoxLayout()
        left.setSpacing(6)

        self.view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left.addWidget(self.view, 1)

        self.lbl_time = QLabel(self)
        self.lbl_time.setText("SEEK 00:00:00.000 / 00:00:00.000")

        self.sld_seek = QSlider(Qt.Horizontal, self)
        self.sld_seek.setMinimum(0)
        self.sld_seek.setMaximum(int(self._dur * 1000))
        self.sld_seek.setSingleStep(10)      # 10 ms
        self.sld_seek.setPageStep(250)       # 250 ms
        self.sld_seek.setValue(int(self._seek_sec * 1000))
        self.sld_seek.valueChanged.connect(self._on_seek_slider)
        self.sld_seek.actionTriggered.connect(self._on_seek_action)

        self.btn_preview = QPushButton("Preview filtrata", self)
        self.btn_apply = QPushButton("Applica", self)
        self.btn_cancel = QPushButton("Annulla", self)

        self.btn_preview.clicked.connect(self._on_preview)
        self.btn_apply.clicked.connect(self._on_apply)
        self.btn_cancel.clicked.connect(self.reject)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        bottom.addWidget(self.lbl_time)
        bottom.addWidget(self.sld_seek, 1)
        bottom.addWidget(self.btn_preview)
        bottom.addWidget(self.btn_apply)
        bottom.addWidget(self.btn_cancel)

        left.addLayout(bottom)
        root.addLayout(left, 1)

        # destra: controlli
        right_w = QWidget(self)
        right_w.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        right_w.setMaximumWidth(300)

        right = QVBoxLayout(right_w)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(10)

        self.chk_enable = QCheckBox("Abilita TRIM (elimina segmento)", self)
        self.chk_enable.setChecked(self._enabled)
        self.chk_enable.stateChanged.connect(self._on_enable_changed)
        right.addWidget(self.chk_enable)

        # spin SEEK / IN / OUT (secondi con millisecondi)
        def _mk_spin(max_sec: float) -> QDoubleSpinBox:
            sp = QDoubleSpinBox(self)
            sp.setDecimals(3)
            sp.setRange(0.0, max(0.0, float(max_sec)))
            sp.setSingleStep(0.050)
            sp.setKeyboardTracking(False)
            sp.setFixedWidth(140)
            sp.setAlignment(Qt.AlignRight)
            return sp

        self.spin_seek = _mk_spin(self._dur)
        self.spin_in = _mk_spin(self._dur)
        self.spin_out = _mk_spin(self._dur)

        self.spin_seek.valueChanged.connect(self._on_seek_spin)
        self.spin_in.valueChanged.connect(self._on_in_spin)
        self.spin_out.valueChanged.connect(self._on_out_spin)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        form.setFormAlignment(Qt.AlignTop)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(10)

        form.addRow("SEEK (s):", self.spin_seek)
        form.addRow("IN (s):", self.spin_in)
        form.addRow("OUT (s):", self.spin_out)

        fw = QWidget(self)
        fw.setLayout(form)
        right.addWidget(fw)

        # bottoni set IN/OUT
        row_btn = QHBoxLayout()
        self.btn_set_in = QPushButton("IN ← SEEK", self)
        self.btn_set_out = QPushButton("OUT ← SEEK", self)
        self.btn_set_in.clicked.connect(self._set_in_from_seek)
        self.btn_set_out.clicked.connect(self._set_out_from_seek)
        row_btn.addWidget(self.btn_set_in)
        row_btn.addWidget(self.btn_set_out)
        right.addLayout(row_btn)

        self.lbl_warn = QLabel("", self)
        self.lbl_warn.setStyleSheet("color:#ff8080;")
        self.lbl_warn.setWordWrap(True)
        right.addWidget(self.lbl_warn)

        self.btn_reset = QPushButton("Reset TRIM", self)
        self.btn_reset.clicked.connect(self._on_reset)
        right.addWidget(self.btn_reset)

        right.addStretch(1)
        root.addWidget(right_w)

    # ───────────────── load/sync ─────────────────

    def _load_into_ui(self):
        self._guard = True
        try:
            self.spin_seek.setValue(self._seek_sec)
            self.spin_in.setValue(max(0.0, min(self._dur, self._start_sec)))
            self.spin_out.setValue(max(0.0, min(self._dur, self._end_sec)))
        finally:
            self._guard = False

    def _refresh_time_labels(self):
        self._seek_sec = self.sld_seek.value() / 1000.0
        self.lbl_time.setText(f"SEEK {_fmt_hhmmss_mmm(self._seek_sec)} / {_fmt_hhmmss_mmm(self._dur)}")
        self.sld_seek.setToolTip(_fmt_hhmmss_mmm(self._seek_sec))

        self.spin_seek.setToolTip(_fmt_hhmmss_mmm(float(self.spin_seek.value())))
        self.spin_in.setToolTip(_fmt_hhmmss_mmm(float(self.spin_in.value())))
        self.spin_out.setToolTip(_fmt_hhmmss_mmm(float(self.spin_out.value())))

        # warning validità solo se enabled
        self._update_validity_ui()

    def _update_validity_ui(self):
        if not self.chk_enable.isChecked():
            self.lbl_warn.setText("")
            self.btn_apply.setEnabled(True)
            self.btn_preview.setEnabled(True)
            return

        ins = float(self.spin_in.value())
        outs = float(self.spin_out.value())
        if outs <= ins + 1e-3:
            self.lbl_warn.setText("⚠️ Segmento non valido: OUT deve essere maggiore di IN.")
            # non disabilito Apply a forza, ma è meglio evitare “silenzio”
            self.btn_apply.setEnabled(True)
            self.btn_preview.setEnabled(True)
        else:
            self.lbl_warn.setText("")
            self.btn_apply.setEnabled(True)
            self.btn_preview.setEnabled(True)

    # ───────────────── events: seek / spins ─────────────────

    def _on_seek_action(self, action: int):
        if action in (
            QSlider.SliderSingleStepAdd,
            QSlider.SliderSingleStepSub,
            QSlider.SliderPageStepAdd,
            QSlider.SliderPageStepSub,
            QSlider.SliderMove,
        ):
            self._t.start(120)

    def _on_seek_slider(self, _v: int):
        if self._guard:
            return
        self._seek_sec = self.sld_seek.value() / 1000.0
        self._guard = True
        try:
            self.spin_seek.setValue(self._seek_sec)
        finally:
            self._guard = False
        self._refresh_time_labels()

        # condividi offset con main_window per preview
        try:
            p = self.parent()
            if p is not None:
                setattr(p, "_preview_offset_sec", float(self._seek_sec))
        except Exception:
            pass

        self._t.start(120)

    def _on_seek_spin(self, v: float):
        if self._guard:
            return
        v = max(0.0, min(self._dur, float(v)))
        self._seek_sec = v

        self._guard = True
        try:
            self.sld_seek.setValue(int(round(v * 1000.0)))
        finally:
            self._guard = False

        self._refresh_time_labels()
        self._t.start(120)

    def _on_in_spin(self, _v: float):
        if self._guard:
            return
        self._refresh_time_labels()

    def _on_out_spin(self, _v: float):
        if self._guard:
            return
        self._refresh_time_labels()

    def _set_in_from_seek(self):
        self.spin_in.setValue(float(self.spin_seek.value()))
        self._refresh_time_labels()

    def _set_out_from_seek(self):
        self.spin_out.setValue(float(self.spin_seek.value()))
        self._refresh_time_labels()

    def _on_enable_changed(self, _state: int):
        self._refresh_time_labels()

    # ───────────────── view fit ─────────────────

    def _fit_view(self):
        try:
            if self.img_item and not self.img_item.pixmap().isNull():
                self.view.fitInView(self.img_item, Qt.KeepAspectRatio)
        except Exception:
            pass

    # ───────────────── frame grab (crop+color + SAR fix) ─────────────────

    def _build_vf_for_frame(self) -> str:
        vf_parts: list[str] = []

        # 1) SAR fix (pixel quadrati) -> fondamentale per evitare “stiramento”
        # trunc(.../2)*2 per tenere width pari
        vf_parts.append("scale=trunc(iw*sar/2)*2:ih,setsar=1")

        # 2) crop (se attivo)
        try:
            crop_spec, crop_enabled, _force_169, _force_scope = load_crop_settings()
            if crop_enabled and crop_spec:
                inject_crop(vf_parts, crop_spec)
        except Exception:
            pass

        # 3) colore (preview: NON consume)
        try:
            eq = build_color_eq_filter()
            if eq:
                vf_parts.append(eq)
        except Exception:
            pass

        # 4) limita dimensione per dialog (no upscale aggressivo)
        vf_parts.append("scale='min(iw,960)':-2")

        return ",".join([x for x in vf_parts if x])

    def _refresh_frame(self):
        if not self._path or not self._path.is_file():
            return

        t = max(0.0, min(self._dur, self._seek_sec))
        vf = self._build_vf_for_frame()

        cmd = [
            _FFMPEG, "-v", "error", "-nostdin",
            "-ss", f"{t:.3f}",
            "-i", str(self._path),
            "-frames:v", "1",
            "-an", "-sn", "-dn",
        ]
        if vf:
            cmd += ["-vf", vf]
        cmd += ["-f", "image2pipe", "-vcodec", "png", "pipe:1"]

        try:
            png = subprocess.check_output(cmd)
            pm = QPixmap()
            if pm.loadFromData(png, "PNG"):
                self._last_pm = pm
                self.img_item.setPixmap(pm)
                self.scene.setSceneRect(pm.rect())
                self._fit_view()
            else:
                # se non decodifica, non rompere tutto
                pass
        except Exception:
            pass

    # ───────────────── actions ─────────────────

    def _on_reset(self):
        try:
            clear_trim_settings(disable_only=False)
        except Exception:
            pass

        self._guard = True
        try:
            self.chk_enable.setChecked(False)
            self.spin_in.setValue(0.0)
            self.spin_out.setValue(0.0)
        finally:
            self._guard = False
        self._refresh_time_labels()

    def _validate_or_warn(self) -> bool:
        if not self.chk_enable.isChecked():
            return True
        ins = float(self.spin_in.value())
        outs = float(self.spin_out.value())
        if outs <= ins + 1e-3:
            QMessageBox.warning(self, "Trim", "Segmento non valido: OUT deve essere maggiore di IN.")
            return False
        return True

    def _on_apply(self):
        if not self._validate_or_warn():
            return
        save_trim_settings(
            start_sec=float(self.spin_in.value()),
            end_sec=float(self.spin_out.value()),
            enabled=bool(self.chk_enable.isChecked()),
        )
        self.accept()

    def _on_preview(self):
        if not self._validate_or_warn():
            return

        save_trim_settings(
            start_sec=float(self.spin_in.value()),
            end_sec=float(self.spin_out.value()),
            enabled=bool(self.chk_enable.isChecked()),
        )

        mw = self.parent()
        if mw and hasattr(mw, "launch_preview"):
            try:
                mw._preview_offset_sec = max(0.0, float(self.spin_in.value()) - 2.0)
            except Exception:
                pass
            try:
                mw.launch_preview(filtered=True)
            except Exception as e:
                QMessageBox.critical(self, "Preview", f"Errore Preview filtrata:\n{e}")
        else:
            QMessageBox.information(self, "Preview", "Parent non disponibile per la preview filtrata.")
