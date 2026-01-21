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

- Fit/centratura robusti:
  resetTransform + sceneRect coerente + fitInView su QRectF + centerOn (evita “scentrato”)

Preview:
- salva trim settings
- prova a settare mw._preview_offset_sec (se esiste) e chiama mw.launch_preview(filtered=True)
- se la preview usa QProcess, aggancio finished per riaprire il TRIM allo stato/geometry di prima
- fallback: quando l'app torna attiva, riporta in primo piano il TRIM se era stato nascosto
"""

from __future__ import annotations

from hevc_gui.i18n import L
import os
import time

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import Qt, QTimer, QRectF, QProcess
from PyQt5.QtGui import QPixmap, QPainter, QBrush, QColor
from PyQt5.QtWidgets import (
    QApplication,
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

        # centratura “dura” (evita offset/traslazioni strane)
        self.setAlignment(Qt.AlignCenter)
        self.setTransformationAnchor(QGraphicsView.AnchorViewCenter)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)

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
        self.setWindowTitle(L("Trim (elimina segmento)"))
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

        # preview lifecycle
        self._pre_preview_geom = None
        self._preview_proc: Optional[QProcess] = None
        self._preview_waiting = False
        self._preview_seen_inactive = False
        self._app_state_hooked = False

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

    def showEvent(self, ev):
        # Se durante la preview qualcuno prova a riesporre questo dialog,
        # lo riblocchiamo: la TRIM deve tornare SOLO quando la preview è finita.
        if getattr(self, "_preview_guard_active", False):
            try:
                ev.ignore()
            except Exception:
                pass
            QTimer.singleShot(0, self.hide)
            return
        super().showEvent(ev)
        QTimer.singleShot(0, self._fit_view)

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
        self.lbl_time.setText(L("SEEK 00:00:00.000 / 00:00:00.000"))

        self.sld_seek = QSlider(Qt.Horizontal, self)
        self.sld_seek.setMinimum(0)
        self.sld_seek.setMaximum(int(self._dur * 1000))
        self.sld_seek.setSingleStep(10)      # 10 ms
        self.sld_seek.setPageStep(250)       # 250 ms
        self.sld_seek.setValue(int(self._seek_sec * 1000))
        self.sld_seek.valueChanged.connect(self._on_seek_slider)
        self.sld_seek.actionTriggered.connect(self._on_seek_action)

        self.btn_preview = QPushButton(L("Preview filtrata"), self)
        self.btn_apply = QPushButton(L("Applica"), self)
        self.btn_cancel = QPushButton(L("Annulla"), self)

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

        self.chk_enable = QCheckBox(L("Abilita TRIM (elimina segmento)"), self)
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
        # NB: lasciamo testi “tecnici” identici in IT/EN
        self.btn_set_in = QPushButton("IN \u2190 SEEK", self)
        self.btn_set_out = QPushButton("OUT \u2190 SEEK", self)
        self.btn_set_in.clicked.connect(self._set_in_from_seek)
        self.btn_set_out.clicked.connect(self._set_out_from_seek)
        row_btn.addWidget(self.btn_set_in)
        row_btn.addWidget(self.btn_set_out)
        right.addLayout(row_btn)

        self.lbl_warn = QLabel(L(""), self)
        self.lbl_warn.setStyleSheet("color:#ff8080;")
        self.lbl_warn.setWordWrap(True)
        right.addWidget(self.lbl_warn)

        self.btn_reset = QPushButton(L("Reset TRIM"), self)
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
        self.lbl_time.setText(L("SEEK {0} / {1}").format(_fmt_hhmmss_mmm(self._seek_sec), _fmt_hhmmss_mmm(self._dur)))
        self.sld_seek.setToolTip(_fmt_hhmmss_mmm(self._seek_sec))

        self.spin_seek.setToolTip(_fmt_hhmmss_mmm(float(self.spin_seek.value())))
        self.spin_in.setToolTip(_fmt_hhmmss_mmm(float(self.spin_in.value())))
        self.spin_out.setToolTip(_fmt_hhmmss_mmm(float(self.spin_out.value())))

        # warning validità solo se enabled
        self._update_validity_ui()

    def _update_validity_ui(self):
        if not self.chk_enable.isChecked():
            self.lbl_warn.setText(L(""))
            self.btn_apply.setEnabled(True)
            self.btn_preview.setEnabled(True)
            return

        ins = float(self.spin_in.value())
        outs = float(self.spin_out.value())
        if outs <= ins + 1e-3:
            self.lbl_warn.setText(L("⚠️ Segmento non valido: OUT deve essere maggiore di IN."))
            self.btn_apply.setEnabled(True)
            self.btn_preview.setEnabled(True)
        else:
            self.lbl_warn.setText(L(""))
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
        """
        Fit robusto e centrato:
        - resetTransform (niente accumuli)
        - fitInView su QRectF
        - centerOn
        """
        try:
            if not self.img_item:
                return
            pm = self.img_item.pixmap()
            if pm is None or pm.isNull():
                return

            rect = self.img_item.sceneBoundingRect()
            if rect.isNull() or rect.width() <= 0 or rect.height() <= 0:
                rect = self.scene.itemsBoundingRect()
            if rect.isNull() or rect.width() <= 0 or rect.height() <= 0:
                rect = QRectF(self.scene.sceneRect())

            self.view.setUpdatesEnabled(False)
            try:
                self.view.resetTransform()
                self.view.setSceneRect(rect)
                self.view.fitInView(rect, Qt.KeepAspectRatio)
                self.view.centerOn(rect.center())
            finally:
                self.view.setUpdatesEnabled(True)
                self.view.viewport().update()
        except Exception:
            pass

    # ───────────────── frame grab (crop+color + SAR fix) ─────────────────

    def _build_vf_for_frame(self) -> str:
        vf_parts: list[str] = []

        # 1) SAR fix (pixel quadrati) -> fondamentale per evitare “stiramento”
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
                self.scene.setSceneRect(QRectF(pm.rect()))
                self._fit_view()
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
            QMessageBox.warning(self, "Trim", L("Segmento non valido: OUT deve essere maggiore di IN."))
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

    # ───────────────── preview restore ─────────────────

    def _find_preview_qprocess(self, mw, ret=None) -> Optional[QProcess]:
        # 1) ritorno diretto
        if isinstance(ret, QProcess):
            return ret

        # 2) attributi “probabili”
        for nm in (
            "_preview_process", "preview_process",
            "_preview_proc", "preview_proc",
            "_proc_preview", "proc_preview",
            "_qproc_preview", "qproc_preview",
        ):
            try:
                v = getattr(mw, nm, None)
                if isinstance(v, QProcess):
                    return v
            except Exception:
                pass

        # 3) child objects
        try:
            procs = mw.findChildren(QProcess)
            if not procs:
                return None
            # preferisci quello running
            for p in reversed(procs):
                try:
                    if p.state() != QProcess.NotRunning:
                        return p
                except Exception:
                    continue
            return procs[-1]
        except Exception:
            return None

    def _hook_app_active_fallback(self):

        # Restore SOLO quando la preview ha davvero preso il focus (Inactive->Active)

        if getattr(self, '_app_state_hooked', False):

            return

        app = QApplication.instance()

        if not app:

            return


        def _on_state(st):

            try:

                if not getattr(self, '_preview_waiting', False):

                    return

                # se la preview prende focus, l'app diventa Inactive: arma il restore

                if st != Qt.ApplicationActive:

                    self._preview_seen_inactive = True

                    return

                # torna Active: restore SOLO se abbiamo visto almeno un Inactive

                if getattr(self, '_preview_seen_inactive', False) and not self.isVisible():

                    self._restore_after_preview()

            except Exception:

                pass


        try:

            app.applicationStateChanged.connect(_on_state)

            self._app_state_hooked = True

        except Exception:

            pass

        def _on_state(_st):
            # quando l'app torna attiva e noi stiamo “aspettando preview”, rimettiamo su il TRIM
            if self._preview_waiting and not self.isVisible():
                QTimer.singleShot(50, self._restore_after_preview)

        try:
            app.applicationStateChanged.connect(_on_state)
            self._app_state_hooked = True
        except Exception:
            pass

    def _restore_after_preview(self, *a):
        # disarma “waiting”
        self._preview_waiting = False

        # prova a staccare segnali (se c'era QProcess)
        try:
            if self._preview_proc:
                try:
                    self._preview_proc.finished.disconnect(self._restore_after_preview)
                except Exception:
                    pass
                self._preview_proc = None
        except Exception:
            pass

        try:
            if self._pre_preview_geom is not None:
                self.restoreGeometry(self._pre_preview_geom)
        except Exception:
            pass

        try:
            self.show()
            self.raise_()
            self.activateWindow()
        except Exception:
            pass

        QTimer.singleShot(0, self._fit_view)

    def _on_preview(self):
        if not self._validate_or_warn():
            return

        # Persisti i parametri TRIM: la preview filtrata usa le stesse impostazioni
        save_trim_settings(
            start_sec=float(self.spin_in.value()),
            end_sec=float(self.spin_out.value()),
            enabled=bool(self.chk_enable.isChecked()),
        )

        mw = self.parent()
        if not (mw and hasattr(mw, "launch_preview")):
            QMessageBox.information(self, "Preview", L("Parent non disponibile per la preview filtrata."))
            return

        # Offset: fai partire la preview un attimo prima di IN (utile per controllare lo stacco)
        try:
            mw._preview_offset_sec = max(0.0, float(self.spin_in.value()) - 2.0)
        except Exception:
            pass

        # Attiva guard: finché la preview è viva, questa finestra NON deve poter ricomparire
        self._preview_guard_active = True
        geo = self.saveGeometry()

        # Snapshot processi (se la preview usa QProcess con parent=main window)
        before = set()
        try:
            before = set(mw.findChildren(QProcess))
        except Exception:
            before = set()

        # chiudi TRIM (rimane in memoria con tutti i settaggi)
        self.hide()

        def _restore():
            if not getattr(self, "_preview_guard_active", False):
                return
            self._preview_guard_active = False

            # stop timer PID, se presente
            t = getattr(self, "_preview_pid_timer", None)
            if t is not None:
                try:
                    t.stop()
                except Exception:
                    pass
                try:
                    t.deleteLater()
                except Exception:
                    pass
                self._preview_pid_timer = None

            try:
                self.restoreGeometry(geo)
            except Exception:
                pass
            self.show()
            self.raise_()
            self.activateWindow()
            QTimer.singleShot(0, self._fit_view)

        def _pid_alive(pid: int) -> bool:
            if pid <= 0:
                return False
            try:
                os.kill(pid, 0)
                return True
            except ProcessLookupError:
                return False
            except PermissionError:
                return True
            except Exception:
                # fallback /proc
                try:
                    return os.path.exists(f"/proc/{pid}")
                except Exception:
                    return False

        def _watch_pid(pid: int):
            # Poll leggero: quando il processo sparisce, ripristina TRIM.
            self._preview_pid_timer = QTimer(self)
            self._preview_pid_timer.setInterval(400)
            self._preview_pid_timer.timeout.connect(lambda: (None if _pid_alive(pid) else _restore()))
            self._preview_pid_timer.start()

        # Lancia preview
        t0 = time.monotonic()
        try:
            ret = mw.launch_preview(filtered=True)
        except Exception as e:
            _restore()
            QMessageBox.critical(self, L("Preview"), L("Errore Preview filtrata:\n{0}").format(e))
            return
        dt = time.monotonic() - t0

        # Se launch_preview è BLOCCANTE (ritorna dopo la chiusura preview), ripristina subito.
        # (Soglia volutamente “alta” per non confondere con una partenza lenta async.)
        if dt > 1.0:
            _restore()
            return

        # 1) se ritorna un QProcess, agganciati al finished
        if isinstance(ret, QProcess):
            try:
                ret.finished.connect(lambda *_: _restore())
                return
            except Exception:
                pass

        # 2) se ritorna un pid (o tuple tipo (ok, pid)), poll del pid
        pid = None
        try:
            if isinstance(ret, tuple) and len(ret) >= 2 and isinstance(ret[1], int):
                pid = int(ret[1])
            elif isinstance(ret, int):
                pid = int(ret)
            elif hasattr(ret, "pid") and isinstance(getattr(ret, "pid"), int):
                pid = int(getattr(ret, "pid"))
        except Exception:
            pid = None

        if pid and pid > 0:
            _watch_pid(pid)
            return

        # 3) prova a trovare un nuovo QProcess creato dal main window per la preview
        try:
            after = set(mw.findChildren(QProcess))
            new = [p for p in after if p not in before]

            def _looks_like_preview(p: QProcess) -> bool:
                try:
                    prg = (p.program() or "").lower()
                    args = " ".join(p.arguments() or []).lower()
                except Exception:
                    prg, args = "", ""
                return any(x in prg or x in args for x in ("mpv", "ffplay", "vlc", "mplayer"))

            cand = None
            for p in new:
                if _looks_like_preview(p):
                    cand = p
                    break
            if cand is None:
                for p in new:
                    if p.state() == QProcess.Running:
                        cand = p
                        break
            if cand is None:
                for p in after:
                    if _looks_like_preview(p) and p.state() != QProcess.NotRunning:
                        cand = p
                        break

            if cand is not None:
                try:
                    cand.finished.connect(lambda *_: _restore())
                    return
                except Exception:
                    pass
        except Exception:
            pass

        # 4) fallback “focus-based”: quando l’app torna attiva dopo essere andata inactive, ripristina
        # (utile se la preview è esterna e non abbiamo handle/pid)
        try:
            from PyQt5.QtWidgets import QApplication
            app = QApplication.instance()
            if app is not None:
                self._preview_seen_inactive = False

                def _on_state(st):
                    if not getattr(self, "_preview_guard_active", False):
                        try:
                            app.applicationStateChanged.disconnect(_on_state)
                        except Exception:
                            pass
                        return
                    if st == Qt.ApplicationInactive:
                        self._preview_seen_inactive = True
                    if self._preview_seen_inactive and st == Qt.ApplicationActive:
                        try:
                            app.applicationStateChanged.disconnect(_on_state)
                        except Exception:
                            pass
                        _restore()

                app.applicationStateChanged.connect(_on_state)
                return
        except Exception:
            pass

        # Se non ho agganci (caso raro), almeno non lasciarti “sparire” la finestra.
        _restore()
