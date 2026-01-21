#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hevc_gui/gui/crop_dialog.py

Dialog di crop con preview frame (ffmpeg) + rettangolo trascinabile/ridimensionabile.

UI (come “prima”):
- Frame a sinistra.
- Controlli (enable/flags + X/Y/W/H) a destra del frame.
- Sotto al frame: label tempo + slider (largo quanto il frame) + pulsanti ancorati a destra.

Fix richiesti:
- Niente bordo bianco attorno al frame (QGraphicsView senza frame + background nero).
- Niente scrollbar (view sempre fit).
- “Applica” NON deve far ripartire la preview (quello si sistema in main_window.py).

Il “consume” post-encode / cambio-file è gestito dalla MainWindow.
"""

from __future__ import annotations
from hevc_gui.i18n import L

import subprocess
from pathlib import Path
from typing import Optional, Callable

from PyQt5.QtCore import Qt, QRectF, QTimer
from PyQt5.QtGui import QPixmap, QPen, QColor, QPainter, QBrush
from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QCheckBox,
    QSpinBox,
    QMessageBox,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QSlider,
    QFormLayout,
    QWidget,
    QSizePolicy,
    QFrame,
)

from hevc_gui.core import constants as C

from hevc_gui.video.crop_tools import (
    CropSpec,  # compat / typing
    load_crop_settings,
    save_crop_settings,
    clear_crop_settings,
    probe_resolution,
)

FRAME_PATH = Path("/dev/shm/hevc_gui/crop_frame.png")


def _even(x: int) -> int:
    """Rende pari (per codec/compat: molte pipeline vogliono valori pari)."""
    return (x // 2) * 2


class CropView(QGraphicsView):
    """View “pulita”: no frame, no scrollbar, background nero, fit automatico."""
    def __init__(self, dlg: "CropDialog"):
        super().__init__(dlg)
        self._dlg = dlg

        # Rendering migliore (linee + pixmap più smooth)
        self.setRenderHints(
            self.renderHints()
            | QPainter.Antialiasing
            | QPainter.SmoothPixmapTransform
        )
        self.setAlignment(Qt.AlignCenter)

        # Niente scrollbar: vogliamo sempre vedere tutto il frame (fitInView)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # Via il bordo (QFrame) + sfondo nero
        self.setFrameShape(QFrame.NoFrame)
        self.setLineWidth(0)
        self.setMidLineWidth(0)
        self.setStyleSheet("QGraphicsView { background: #000; border: 0px; }")
        self.setBackgroundBrush(QBrush(QColor(0, 0, 0)))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        # Quando la finestra si ridimensiona, rifai il fit del frame
        self._dlg._fit_view()

    def showEvent(self, ev):
        super().showEvent(ev)
        # Fit dopo che Qt ha fatto layout/size reali
        QTimer.singleShot(0, self._dlg._fit_view)


class _CropRect(QGraphicsRectItem):
    """
    Rettangolo crop:
    - MOVE trascinando dentro
    - RESIZE trascinando bordi/angoli (con “maniglie” visibili)
    """
    MIN_W = 16.0
    MIN_H = 16.0

    HIT = 8.0        # area sensibile (px) per agganciare bordi/angoli
    HANDLE = 7.0     # dimensione (px) delle maniglie disegnate

    def __init__(self, r: QRectF, on_changed: Optional[Callable[[], None]] = None):
        super().__init__(r)

        self._bounds = QRectF(0, 0, 0, 0)     # limiti del frame (pixmap)
        self._on_changed = on_changed          # callback quando cambia rect

        self._mode = None                      # "move", "l","r","t","b","tl","tr","bl","br"
        self._press_pos = None                 # QPointF in coordinate dell'item
        self._start_rect = None                # QRectF iniziale prima del drag

        # ── BORDO RETTANGOLO CROP (cyan) ─────────────────────────────
        # Qui si decide lo spessore: setWidth(1) = 1px (più sottile)
        pen = QPen(QColor(0, 255, 255))
        pen.setWidth(1)            # ← assottigliato (prima era 2)
        pen.setCosmetic(True)      # spessore costante a schermo anche con fitInView/zoom
        self.setPen(pen)

        # Nessun riempimento: vogliamo vedere il video sotto al rettangolo.
        brush = QBrush()
        brush.setStyle(Qt.NoBrush)
        self.setBrush(brush)

        self.setZValue(10)
        self.setAcceptHoverEvents(True)

    def set_bounds(self, b: QRectF) -> None:
        """Imposta i limiti (bounds) su cui il rect deve rimanere clippato."""
        self._bounds = QRectF(b)

    def _handle_rects(self, r: QRectF):
        """Ritorna le 8 maniglie (rect) intorno al crop rect."""
        hs = self.HANDLE
        cx = r.center().x()
        cy = r.center().y()
        return [
            QRectF(r.left() - hs/2,  r.top() - hs/2,    hs, hs),   # TL
            QRectF(cx - hs/2,        r.top() - hs/2,    hs, hs),   # T
            QRectF(r.right() - hs/2, r.top() - hs/2,    hs, hs),   # TR
            QRectF(r.left() - hs/2,  cy - hs/2,         hs, hs),   # L
            QRectF(r.right() - hs/2, cy - hs/2,         hs, hs),   # R
            QRectF(r.left() - hs/2,  r.bottom() - hs/2, hs, hs),   # BL
            QRectF(cx - hs/2,        r.bottom() - hs/2, hs, hs),   # B
            QRectF(r.right() - hs/2, r.bottom() - hs/2, hs, hs),   # BR
        ]

    def paint(self, painter: QPainter, option, widget=None):
        # Disegna il rettangolo base (bordo cyan)
        super().paint(painter, option, widget)

        # Disegna le maniglie (sempre visibili)
        r = self.rect()
        painter.save()
        painter.setPen(QPen(QColor(0, 0, 0, 180), 1))
        painter.setBrush(QBrush(QColor(0, 255, 255, 220)))
        for hr in self._handle_rects(r):
            painter.drawRect(hr)
        painter.restore()

    def _hit_test(self, p) -> Optional[str]:
        """
        Decide cosa stai “agganciando” col mouse:
        - angoli (tl,tr,bl,br)
        - lati (l,r,t,b)
        - interno (move)
        """
        r = self.rect()
        m = self.HIT

        # Se sei troppo lontano dal rect, non agganciare nulla
        if not r.adjusted(-m, -m, m, m).contains(p):
            return None

        left   = abs(p.x() - r.left()) <= m
        right  = abs(p.x() - r.right()) <= m
        top    = abs(p.y() - r.top()) <= m
        bottom = abs(p.y() - r.bottom()) <= m

        if left and top:
            return "tl"
        if right and top:
            return "tr"
        if left and bottom:
            return "bl"
        if right and bottom:
            return "br"
        if left:
            return "l"
        if right:
            return "r"
        if top:
            return "t"
        if bottom:
            return "b"

        # Dentro al rect (ma lontano dai bordi) → move
        if r.adjusted(m, m, -m, -m).contains(p):
            return "move"
        return None

    def _set_cursor_for_mode(self, mode: Optional[str]):
        """Cambia cursore in base all'azione."""
        if mode in ("tl", "br"):
            self.setCursor(Qt.SizeFDiagCursor)
        elif mode in ("tr", "bl"):
            self.setCursor(Qt.SizeBDiagCursor)
        elif mode in ("l", "r"):
            self.setCursor(Qt.SizeHorCursor)
        elif mode in ("t", "b"):
            self.setCursor(Qt.SizeVerCursor)
        elif mode == "move":
            self.setCursor(Qt.SizeAllCursor)
        else:
            self.unsetCursor()

    def hoverMoveEvent(self, event):
        mode = self._hit_test(event.pos())
        self._set_cursor_for_mode(mode)
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event):
        self._mode = self._hit_test(event.pos())
        self._press_pos = event.pos()
        self._start_rect = QRectF(self.rect())
        if self._mode is None:
            event.ignore()
            return
        event.accept()

    def mouseMoveEvent(self, event):
        if not self._mode or self._press_pos is None or self._start_rect is None:
            super().mouseMoveEvent(event)
            return

        dx = event.pos().x() - self._press_pos.x()
        dy = event.pos().y() - self._press_pos.y()

        r0 = QRectF(self._start_rect)
        left = r0.left()
        top = r0.top()
        right = r0.right()
        bottom = r0.bottom()

        if self._mode == "move":
            nr = QRectF(r0)
            nr.translate(dx, dy)
        else:
            # Resize: aggiorna i lati/angoli coinvolti
            if "l" in self._mode:
                left = min(left + dx, right - self.MIN_W)
            if "r" in self._mode:
                right = max(right + dx, left + self.MIN_W)
            if "t" in self._mode:
                top = min(top + dy, bottom - self.MIN_H)
            if "b" in self._mode:
                bottom = max(bottom + dy, top + self.MIN_H)
            nr = QRectF(left, top, right - left, bottom - top)

        # Clamp nei bounds del frame
        nr = self._clamp_rect(nr)
        self.setRect(nr)

        if self._on_changed:
            self._on_changed()

        event.accept()

    def mouseReleaseEvent(self, event):
        if self._on_changed:
            self._on_changed()
        self._mode = None
        self._press_pos = None
        self._start_rect = None
        event.accept()

    def _clamp_rect(self, r: QRectF) -> QRectF:
        """Mantiene il rect dentro i bounds e rispetta MIN_W/MIN_H."""
        b = self._bounds
        if b.width() <= 0 or b.height() <= 0:
            return r

        w = min(r.width(), b.width())
        h = min(r.height(), b.height())
        w = max(w, self.MIN_W)
        h = max(h, self.MIN_H)

        x = r.x()
        y = r.y()

        x = max(b.left(), min(x, b.right() - w))
        y = max(b.top(),  min(y, b.bottom() - h))

        return QRectF(x, y, w, h)


class CropDialog(QDialog):
    def __init__(self, input_path: str, parent=None, grab_time: float = 10.0):
        super().__init__(parent)
        self.setWindowTitle(L("Crop"))

        self.input_path = input_path
        self.grab_time = float(grab_time or 0.0)

        self.src_w = 0
        self.src_h = 0
        self.src_dur = 0.0

        self.scene = QGraphicsScene(self)
        self.scene.setBackgroundBrush(QBrush(QColor(0, 0, 0)))  # niente bianco “fuori frame”

        self.view = CropView(self)
        self.view.setScene(self.scene)

        self.pix_item: Optional[QGraphicsPixmapItem] = None
        self.crop_item: Optional[_CropRect] = None
        self._pix_bounds = QRectF(0, 0, 0, 0)

        # Maschere scure “fuori crop” (per evidenziare l'area selezionata)
        self._mask_brush = QBrush(QColor(0, 0, 0, 120))
        self.mask_top = QGraphicsRectItem()
        self.mask_bottom = QGraphicsRectItem()
        self.mask_left = QGraphicsRectItem()
        self.mask_right = QGraphicsRectItem()
        for m in (self.mask_top, self.mask_bottom, self.mask_left, self.mask_right):
            m.setBrush(self._mask_brush)
            m.setPen(QPen(Qt.NoPen))  # IMPORTANT: setPen vuole un QPen, non Qt.NoPen
            m.setZValue(5)
            self.scene.addItem(m)

        # Debounce: quando sposti lo slider, estrai un frame dopo 25ms (non ad ogni tick)
        self._seek_timer = QTimer(self)
        self._seek_timer.setSingleShot(True)
        self._seek_timer.timeout.connect(self._grab_frame)

        self._build_ui()

        self._load_source_info()
        self._init_time_slider()
        self._grab_frame()
        self._load_previous_settings_into_ui()

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
        self.btn_cancel.clicked.connect(self.reject)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)
        bottom_row.addWidget(self.lbl_time)
        bottom_row.addWidget(self.sld_time, 1)
        bottom_row.addWidget(self.btn_preview)
        bottom_row.addWidget(self.btn_apply)
        bottom_row.addWidget(self.btn_cancel)

        left.addLayout(bottom_row)
        root.addLayout(left, 1)

        # destra: controlli
        right_w = QWidget(self)
        right_w.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        right_w.setMaximumWidth(260)

        right = QVBoxLayout(right_w)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(10)

        self.chk_enable = QCheckBox(L("Crop attivo"), self)
        self.chk_force_169 = QCheckBox(L("Forza DAR 16:9"), self)
        self.chk_force_scope = QCheckBox(L("Forza DAR 2.35:1"), self)
        right.addWidget(self.chk_enable)
        right.addWidget(self.chk_force_169)
        right.addWidget(self.chk_force_scope)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        form.setFormAlignment(Qt.AlignTop)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(10)

        def _mk_spin(minv: int, maxv: int) -> QSpinBox:
            sp = QSpinBox(self)
            sp.setRange(minv, maxv)
            sp.setKeyboardTracking(False)
            sp.setFixedWidth(120)
            sp.setAlignment(Qt.AlignRight)
            sp.valueChanged.connect(self._on_spin_changed)
            return sp

        self.sp_x = _mk_spin(0, 99999)
        self.sp_y = _mk_spin(0, 99999)
        self.sp_w = _mk_spin(16, 99999)
        self.sp_h = _mk_spin(16, 99999)

        form.addRow("X:", self.sp_x)
        form.addRow("Y:", self.sp_y)
        form.addRow("W:", self.sp_w)
        form.addRow("H:", self.sp_h)

        fw = QWidget(self)
        fw.setLayout(form)
        right.addWidget(fw)
        right.addStretch(1)

        root.addWidget(right_w)

        self.resize(1180, 760)

    # ───────────────── view fit ─────────────────

    def _fit_view(self):
        """Fit senza deformare, niente scrollbar."""
        if self._pix_bounds.width() <= 0 or self._pix_bounds.height() <= 0:
            return
        self.view.resetTransform()
        self.scene.setSceneRect(self._pix_bounds)
        self.view.fitInView(self._pix_bounds, Qt.KeepAspectRatio)
        if self.pix_item is not None:
            self.view.centerOn(self.pix_item)

    # ───────────────── source info / time ─────────────────

    def _load_source_info(self):
        try:
            self.src_w, self.src_h = probe_resolution(self.input_path)
        except Exception:
            self.src_w, self.src_h = (0, 0)

        try:
            out = subprocess.check_output(
                [
                    C.FFPROBE_BIN, "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    self.input_path,
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
            self.sld_time.setValue(t0)
            self.lbl_time.setText(self._fmt_time(t0, self.src_dur))
        else:
            self.sld_time.setMaximum(600)
            self.sld_time.setValue(int(self.grab_time))
            self.lbl_time.setText(self._fmt_time(int(self.grab_time), 0.0))

    def _fmt_time(self, t: int, tot: float = 0.0) -> str:
        def mmss(x):
            m = int(x) // 60
            s = int(x) % 60
            return f"{m:02d}:{s:02d}"
        return f"{mmss(t)} / {mmss(tot)}" if tot > 0 else mmss(t)

    def _on_seek_changed(self, v: int):
        self.grab_time = float(v)
        self.lbl_time.setText(self._fmt_time(v, self.src_dur))
        # aggiorna offset condiviso (utile anche ad altri tool)
        try:
            p = self.parent()
            if p is not None:
                setattr(p, "_preview_offset_sec", float(v))
        except Exception:
            pass
        self._seek_timer.start(25)

    def _on_seek_action(self, action: int):
        if action in (
            QSlider.SliderSingleStepAdd,
            QSlider.SliderSingleStepSub,
            QSlider.SliderPageStepAdd,
            QSlider.SliderPageStepSub,
            QSlider.SliderMove,
        ):
            self._seek_timer.start(25)

    # ───────────────── frame grab ─────────────────

    def _grab_frame(self):
        if not self.input_path:
            return

        FRAME_PATH.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            getattr(C, "FFMPEG_BIN", "ffmpeg"),
            "-hide_banner",
            "-nostdin",
            "-ss", f"{self.grab_time:.2f}",
            "-i", self.input_path,
            "-frames:v", "1",
            "-an", "-sn", "-dn",
            "-y", str(FRAME_PATH),
        ]

        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            QMessageBox.critical(self, L("Errore"), L("Impossibile estrarre un frame con ffmpeg."))
            return

        pix = QPixmap(str(FRAME_PATH))
        if pix.isNull():
            QMessageBox.critical(self, L("Errore"), L('Frame vuoto/illeggibile.'))
            return

        self._set_pixmap(pix)

    def _set_pixmap(self, pix: QPixmap):
        # Rimuovi pixmap precedente (se esiste)
        if self.pix_item is not None:
            try:
                self.scene.removeItem(self.pix_item)
            except Exception:
                pass
            self.pix_item = None

        # Aggiungi nuova pixmap
        self.pix_item = QGraphicsPixmapItem(pix)
        self.pix_item.setZValue(0)
        self.scene.addItem(self.pix_item)

        self._pix_bounds = QRectF(0, 0, pix.width(), pix.height())

        # Se il rect non esiste (o è stato eliminato da Qt), ricrealo
        need_new = False
        if self.crop_item is None:
            need_new = True
        else:
            try:
                _ = self.crop_item.rect()
            except RuntimeError:
                need_new = True

        if need_new:
            # Rect di default: 90% del frame centrato
            dw = max(16, int(pix.width() * 0.90))
            dh = max(16, int(pix.height() * 0.90))
            dx = int((pix.width() - dw) / 2)
            dy = int((pix.height() - dh) / 2)

            self.crop_item = _CropRect(QRectF(dx, dy, dw, dh), on_changed=self._on_crop_rect_changed)
            self.crop_item.set_bounds(self._pix_bounds)
            self.scene.addItem(self.crop_item)
        else:
            self.crop_item.set_bounds(self._pix_bounds)
            self.crop_item.setRect(self.crop_item._clamp_rect(self.crop_item.rect()))
            if self.crop_item.scene() is not self.scene:
                self.scene.addItem(self.crop_item)

        self._update_masks()
        self._sync_fields_from_rect()
        self._fit_view()

    # ───────────────── masks + sync ─────────────────

    def _update_masks(self):
        if not self.pix_item or not self.crop_item:
            return
        bw = float(self._pix_bounds.width())
        bh = float(self._pix_bounds.height())
        r = self.crop_item.rect()

        # 4 rettangoli scuri che coprono l'area fuori dal crop
        self.mask_top.setRect(QRectF(0, 0, bw, max(0.0, r.top())))
        self.mask_bottom.setRect(QRectF(0, r.bottom(), bw, max(0.0, bh - r.bottom())))
        self.mask_left.setRect(QRectF(0, r.top(), max(0.0, r.left()), max(0.0, r.height())))
        self.mask_right.setRect(QRectF(r.right(), r.top(), max(0.0, bw - r.right()), max(0.0, r.height())))

    def _mark_crop_used(self):
        """Se tocchi rect/spin, abilita automaticamente il crop."""
        if hasattr(self, "chk_enable") and not self.chk_enable.isChecked():
            self.chk_enable.setChecked(True)

    def _on_crop_rect_changed(self):
        self._mark_crop_used()
        self._sync_fields_from_rect()
        self._update_masks()

    # ───────────────── load/save ─────────────────

    def _load_previous_settings_into_ui(self):
        spec, enabled, force_169, force_scope = load_crop_settings()

        self.chk_enable.setChecked(bool(enabled))
        self.chk_force_169.setChecked(bool(force_169))
        self.chk_force_scope.setChecked(bool(force_scope))

        if spec and self.crop_item and self.pix_item:
            x = max(0, min(spec.x, int(self._pix_bounds.width()) - 16))
            y = max(0, min(spec.y, int(self._pix_bounds.height()) - 16))
            w = max(16, min(spec.w, int(self._pix_bounds.width()) - x))
            h = max(16, min(spec.h, int(self._pix_bounds.height()) - y))
            self.crop_item.set_bounds(self._pix_bounds)
            self.crop_item.setRect(QRectF(x, y, w, h))
            self.crop_item.setRect(self.crop_item._clamp_rect(self.crop_item.rect()))
            self._sync_fields_from_rect()
            self._update_masks()
            self._fit_view()

    def _sync_fields_from_rect(self):
        if not self.crop_item:
            return
        r = self.crop_item.rect()
        self.sp_x.blockSignals(True)
        self.sp_y.blockSignals(True)
        self.sp_w.blockSignals(True)
        self.sp_h.blockSignals(True)
        try:
            self.sp_x.setValue(int(r.x()))
            self.sp_y.setValue(int(r.y()))
            self.sp_w.setValue(int(r.width()))
            self.sp_h.setValue(int(r.height()))
        finally:
            self.sp_x.blockSignals(False)
            self.sp_y.blockSignals(False)
            self.sp_w.blockSignals(False)
            self.sp_h.blockSignals(False)

    def _on_spin_changed(self, _v: int):
        if not self.crop_item:
            return

        self._mark_crop_used()

        x = int(self.sp_x.value())
        y = int(self.sp_y.value())
        w = int(self.sp_w.value())
        h = int(self.sp_h.value())

        x = max(0, min(x, int(self._pix_bounds.width()) - 16))
        y = max(0, min(y, int(self._pix_bounds.height()) - 16))
        w = max(16, min(w, int(self._pix_bounds.width()) - x))
        h = max(16, min(h, int(self._pix_bounds.height()) - y))

        self.crop_item.set_bounds(self._pix_bounds)
        self.crop_item.setRect(QRectF(x, y, w, h))
        self.crop_item.setRect(self.crop_item._clamp_rect(self.crop_item.rect()))
        self._update_masks()

    def _save_current_crop(self, *, show_warning: bool) -> bool:
        if not self.crop_item:
            if show_warning:
                QMessageBox.warning(self, "Attenzione", L("Nessun frame disponibile."))
            return False

        r = self.crop_item.rect()
        w = _even(int(r.width()))
        h = _even(int(r.height()))
        x = _even(int(r.x()))
        y = _even(int(r.y()))

        if w < 16 or h < 16:
            if show_warning:
                QMessageBox.warning(self, "Attenzione", L('Selezione troppo piccola.'))
            return False

        save_crop_settings(
            w, h, x, y,
            enabled=self.chk_enable.isChecked(),
            force_169=self.chk_force_169.isChecked(),
            force_scope=self.chk_force_scope.isChecked(),
        )
        return True

    def _apply(self):
        if not self._save_current_crop(show_warning=True):
            return
        self.accept()

    def _on_preview(self):
        if not self._save_current_crop(show_warning=True):
            return

        parent = self.parent()
        if parent is None:
            QMessageBox.warning(self, "Preview", L('Preview filtrata non disponibile (finestra principale assente).'))
            return

        launch = getattr(parent, "launch_preview", None)
        if not callable(launch):
            QMessageBox.warning(self, "Preview", L('La finestra principale non espone launch_preview().'))
            return

        try:
            launch(filtered=True)
        except Exception as e:
            QMessageBox.critical(self, L("Preview"), L("Errore durante la Preview filtrata:\n{0}").format(e))

    def reject(self):
        # “Annulla (spegni)” → pulisci/azzera crop
        try:
            clear_crop_settings(disable_only=False)
        except Exception:
            pass
        super().reject()
