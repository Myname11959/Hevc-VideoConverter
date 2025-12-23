# -*- coding: utf-8 -*-
"""
hevc_gui/gui/crop_dialog.py

Finestra di crop:
- preview frame (estratto via ffmpeg),
- rettangolo cyan trascinabile/ridimensionabile (bordo 1px cosmetico),
- maschera scura intorno,
- spinbox WHXY con freccette (↑↓) e passo 2, sync bidirezionale,
- checkbox: Abilita crop, Blocca aspect, Forza 16:9, Forza 2.35:1,
- slider del tempo per scegliere il frame da catturare,
- salvataggio impostazioni in QSettings.
"""

from __future__ import annotations
import os
import subprocess
from pathlib import Path
from typing import Optional, Tuple, Callable

from PyQt5.QtCore import Qt, QRectF, QPointF, QSizeF, QTimer
from PyQt5.QtGui import QPixmap, QColor, QPen, QBrush, QPainter, QCursor
from PyQt5.QtWidgets import (
    QDialog, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QSpinBox, QSlider,
    QCheckBox, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QGraphicsRectItem, QWidget, QMessageBox, QAbstractSlider
)

from hevc_gui.video.crop_tools import clear_crop_settings

# ── Prova a importare le API dal tuo helper; se mancano, fallback locale ──
try:
    from hevc_gui.video.crop_tools import (
        probe_resolution as _probe_resolution,
        CropSpec, save_crop_settings, load_crop_settings
    )
except Exception:
    _probe_resolution = None  # type: ignore
    CropSpec = object         # placeholder
    def save_crop_settings(*args, **kwargs):  # type: ignore
        pass
    def load_crop_settings():  # type: ignore
        return None, False

# ─────────────────────── util ffprobe locali (fallback) ───────────────────────

def probe_resolution(path: Optional[str]) -> Optional[Tuple[int, int]]:
    """Preferisce la versione del tuo helper, altrimenti usa ffprobe."""
    if _probe_resolution:
        try:
            return _probe_resolution(path)  # type: ignore[misc]
        except Exception:
            pass
    if not path:
        return None
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
            text=True
        ).strip()
        if out:
            w, h = out.split(",")
            return int(w), int(h)
    except Exception:
        pass
    return None


def probe_duration(path: Optional[str]) -> float:
    if not path:
        return 0.0
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nokey=1:noprint_wrappers=1", str(path)],
            text=True
        ).strip()
        return float(out) if out else 0.0
    except Exception:
        return 0.0


# ───────────────────────── Overlay items ─────────────────────────

class MaskRect(QGraphicsRectItem):
    def __init__(self, rect=QRectF()):
        super().__init__(rect)
        self.setPen(QPen(Qt.NoPen))
        self.setBrush(QBrush(QColor(0, 0, 0, 160)))
        self.setZValue(10)


class CropRect(QGraphicsRectItem):
    """Rettangolo di crop con drag + maniglie; emette callback a ogni modifica."""
    HANDLE_SIZE = 8
    EDGE_MARGIN = 8
    MIN_W = 16
    MIN_H = 16

    def __init__(self, rect: QRectF):
        super().__init__(rect)
        self.setZValue(20)

        # bordo 1px cosmetico (sempre sottile, anche con zoom/HiDPI)
        pen = QPen(QColor(0, 210, 255))
        pen.setWidth(1)
        pen.setCosmetic(True)
        self.setPen(pen)
        self.setBrush(QBrush(Qt.NoBrush))

        self.setAcceptedMouseButtons(Qt.LeftButton)
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsRectItem.ItemIsSelectable, True)

        self._bounds = QRectF(0, 0, 0, 0)
        self._drag_mode: Optional[str] = None   # 'move','tl','t','tr','r','br','b','bl','l'
        self._press_pos = QPointF()
        self._start_rect = QRectF()
        self._aspect_lock_getter: Callable[[], bool] = (lambda: False)
        self._on_change: Optional[Callable[[QRectF], None]] = None

    # API
    def set_bounds(self, r: QRectF):
        self._bounds = QRectF(r)

    def set_aspect_lock_getter(self, fn: Callable[[], bool]):
        self._aspect_lock_getter = fn or (lambda: False)

    def set_change_callback(self, fn: Callable[[QRectF], None]):
        self._on_change = fn

    # util
    def _handles(self, r: QRectF) -> dict:
        s = self.HANDLE_SIZE
        cx = r.center().x(); cy = r.center().y()
        return {
            "tl": QRectF(r.left()-s/2,  r.top()-s/2,    s, s),
            "t":  QRectF(cx-s/2,        r.top()-s/2,    s, s),
            "tr": QRectF(r.right()-s/2, r.top()-s/2,    s, s),
            "r":  QRectF(r.right()-s/2, cy-s/2,         s, s),
            "br": QRectF(r.right()-s/2, r.bottom()-s/2, s, s),
            "b":  QRectF(cx-s/2,        r.bottom()-s/2, s, s),
            "bl": QRectF(r.left()-s/2,  r.bottom()-s/2, s, s),
            "l":  QRectF(r.left()-s/2,  cy-s/2,         s, s),
        }

    def _cursor_for(self, key: Optional[str]):
        return {
            "tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor,
            "tr": Qt.SizeBDiagCursor, "bl": Qt.SizeBDiagCursor,
            "t": Qt.SizeVerCursor, "b": Qt.SizeVerCursor,
            "l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor,
            "move": Qt.SizeAllCursor, None: Qt.ArrowCursor
        }.get(key, Qt.ArrowCursor)

    # eventi
    def hoverMoveEvent(self, ev):
        r = self.rect()
        pos = ev.pos()
        key = None
        for k, hr in self._handles(r).items():
            if hr.contains(pos):
                key = k; break
        if key is None and r.adjusted(self.EDGE_MARGIN, self.EDGE_MARGIN, -self.EDGE_MARGIN, -self.EDGE_MARGIN).contains(pos):
            key = "move"
        self.setCursor(QCursor(self._cursor_for(key)))
        super().hoverMoveEvent(ev)

    def mousePressEvent(self, ev):
        self._press_pos = ev.pos()
        self._start_rect = QRectF(self.rect())
        # maniglia o move?
        self._drag_mode = None
        for k, hr in self._handles(self._start_rect).items():
            if hr.contains(self._press_pos):
                self._drag_mode = k; break
        if self._drag_mode is None and self._start_rect.contains(self._press_pos):
            self._drag_mode = "move"
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if not self._drag_mode:
            return super().mouseMoveEvent(ev)

        p = ev.pos()
        dx = p.x() - self._press_pos.x()
        dy = p.y() - self._press_pos.y()

        r = QRectF(self._start_rect)
        bounds = QRectF(self._bounds)

        def lock_aspect(w, h, anchor=None):
            if not self._aspect_lock_getter():
                return w, h
            ar = self._start_rect.width() / max(1e-6, self._start_rect.height())
            if anchor in ("l","r","move"):
                h = w / max(1e-6, ar)
            elif anchor in ("t","b"):
                w = h * ar
            else:
                if abs(dx) > abs(dy):
                    h = w / max(1e-6, ar)
                else:
                    w = h * ar
            return w, h

        if self._drag_mode == "move":
            nr = QRectF(r)
            nr.translate(dx, dy)
            if nr.left() < bounds.left():   nr.moveLeft(bounds.left())
            if nr.top()  < bounds.top():    nr.moveTop(bounds.top())
            if nr.right() > bounds.right(): nr.moveRight(bounds.right())
            if nr.bottom()> bounds.bottom():nr.moveBottom(bounds.bottom())
            self._apply_rect(nr)
            return

        left, top, right, bottom = r.left(), r.top(), r.right(), r.bottom()
        if "l" in self._drag_mode: left  = min(max(bounds.left(), left + dx), right - self.MIN_W)
        if "r" in self._drag_mode: right = max(min(bounds.right(), right + dx), left  + self.MIN_W)
        if "t" in self._drag_mode: top   = min(max(bounds.top(), top + dy), bottom - self.MIN_H)
        if "b" in self._drag_mode: bottom= max(min(bounds.bottom(), bottom + dy), top + self.MIN_H)

        w = right - left
        h = bottom - top
        w, h = lock_aspect(w, h, anchor=self._drag_mode)

        if "l" in self._drag_mode: right = left + w
        if "r" in self._drag_mode: left  = right - w
        if "t" in self._drag_mode: bottom= top + h
        if "b" in self._drag_mode: top   = bottom - h

        nr = QRectF(QPointF(left, top), QPointF(right, bottom))
        nr = nr.intersected(bounds)
        if nr.width()  < self.MIN_W:  nr.setWidth(self.MIN_W)
        if nr.height() < self.MIN_H:  nr.setHeight(self.MIN_H)
        self._apply_rect(nr)

    def mouseReleaseEvent(self, ev):
        self._drag_mode = None
        super().mouseReleaseEvent(ev)

    def _apply_rect(self, r: QRectF):
        self.setRect(r.normalized())
        if callable(self._on_change):
            self._on_change(self.rect())

    def paint(self, painter: QPainter, option, widget=None):
        super().paint(painter, option, widget)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(Qt.NoPen))
        painter.setBrush(QBrush(QColor(0, 210, 255)))
        for hr in self._handles(self.rect()).values():
            painter.drawRect(hr)


class CropView(QGraphicsView):
    def __init__(self, parent: "CropDialog"):
        super().__init__(parent)
        self._dlg = parent
        self.setRenderHints(self.renderHints() | QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setAlignment(Qt.AlignCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setTransformationAnchor(QGraphicsView.AnchorViewCenter)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if getattr(self._dlg, "_has_pixmap", False):
            self._dlg._fit_view()

    def showEvent(self, ev):
        super().showEvent(ev)
        QTimer.singleShot(0, self._dlg._fit_view)

# ─────────────────────────── Dialog ───────────────────────────

RAM_DIR = Path("/dev/shm/hevc_gui")
RAM_DIR.mkdir(parents=True, exist_ok=True)
FRAME_PATH = RAM_DIR / "crop_frame.png"


class CropDialog(QDialog):
    """
    input_path: file fornito dalla main_window (nessun pick interno).
    grab_time:  secondi iniziali per il frame.
    """
    def __init__(self, input_path: Optional[str], grab_time: float = 10.0, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Imposta crop…")
        self.setModal(True)
        self.resize(1024, 640)
        self._has_pixmap = False

        self.input_path = input_path
        self.grab_time = float(grab_time)
        self.src_wh: Optional[Tuple[int, int]] = None
        self.src_dur: float = 0.0
        self.pix: Optional[QPixmap] = None
        self._guard = False
        self._pending_spec = None  # usato da _load_previous_settings

        # top bar
        top = QHBoxLayout()
        shown = os.path.basename(input_path) if input_path else "— nessun file selezionato —"
        self.lbl_path = QLabel(shown)
        self.btn_frame = QPushButton("Aggiorna frame")
        self.btn_frame.setToolTip("Estrai un frame al tempo selezionato (slider in basso).")
        top.addWidget(self.lbl_path, 1)
        top.addWidget(self.btn_frame)

        # scene/view
        self.scene = QGraphicsScene(self)
        self.view = CropView(self)
        # --- nel __init__ della CropDialog, dopo aver creato self.view ---
        self.view.setAlignment(Qt.AlignCenter)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.view.setScene(self.scene)
        self.img_item = QGraphicsPixmapItem()
        self.scene.addItem(self.img_item)

        # overlays
        self.mask_top = MaskRect(QRectF())
        self.mask_bottom = MaskRect(QRectF())
        self.mask_left = MaskRect(QRectF())
        self.mask_right = MaskRect(QRectF())
        for m in (self.mask_top, self.mask_bottom, self.mask_left, self.mask_right):
            m.setZValue(5)
            self.scene.addItem(m)

        self.crop_item = CropRect(QRectF(100, 100, 400, 300))
        self.scene.addItem(self.crop_item)

        # pannello dx
        side = QVBoxLayout()
        side.addWidget(QLabel("Selezione (W/H/X/Y)"))
        self.sp_w = self._mk_spin(16, 16384, 2); self.sp_w.setToolTip("Larghezza ritaglio (px)")
        self.sp_h = self._mk_spin(16, 16384, 2); self.sp_h.setToolTip("Altezza ritaglio (px)")
        self.sp_x = self._mk_spin(0, 16384, 2);  self.sp_x.setToolTip("Offset X (px)")
        self.sp_y = self._mk_spin(0, 16384, 2);  self.sp_y.setToolTip("Offset Y (px)")
        grid = self._mk_grid([("W", self.sp_w), ("H", self.sp_h), ("X", self.sp_x), ("Y", self.sp_y)])
        side.addLayout(grid)

        self.chk_lock = QCheckBox("Blocca aspect corrente")
        self.chk_lock.setToolTip("Mantieni le proporzioni del rettangolo mentre ridimensioni.")
        side.addWidget(self.chk_lock)

        self.chk_force_169 = QCheckBox("Forza 16:9 (no stretch)")
        self.chk_force_169.setToolTip("Adatta dentro container 16:9 senza stirare (in SD usa SAR 16:9).")
        self.chk_force_scope = QCheckBox("Forza 2.35:1 (no stretch)")
        self.chk_force_scope.setToolTip("Lettera dentro 16:9 o target con bande nere, senza stirare.")
        side.addWidget(self.chk_force_169)
        side.addWidget(self.chk_force_scope)

        side.addStretch(1)
        self.chk_enable = QCheckBox("Abilita crop in encode/preview")
        self.chk_enable.setChecked(False)  # default sicuro
        side.addWidget(self.chk_enable)

        btns = QHBoxLayout()
        self.btn_cancel = QPushButton("Annulla")
        self.btn_ok = QPushButton("Applica")
        btns.addStretch(1); btns.addWidget(self.btn_cancel); btns.addWidget(self.btn_ok)
        side.addLayout(btns)

        # layout centrale
        mid = QHBoxLayout()
        mid.addWidget(self.view, 1)
        w_side = QWidget(); w_side.setLayout(side); w_side.setFixedWidth(260)
        mid.addWidget(w_side)

        # slider tempo
        bottom = QHBoxLayout()
        bottom.addWidget(QLabel("Tempo:"))
        self.sld_time = QSlider(Qt.Horizontal)
        self.sld_time.setToolTip("Sposta il cursore per scegliere il tempo del frame da catturare.")
        self.sld_time.setMinimum(0)
        self.sld_time.setMaximum(600)  # aggiornato con la durata reale
        self.sld_time.setSingleStep(1)
        self.sld_time.setPageStep(5)
        bottom.addWidget(self.sld_time, 1)
        self.lbl_time = QLabel("0 s")
        bottom.addWidget(self.lbl_time)
        # --- debounce per l’estrazione frame ---
        self._seek_timer = QTimer(self)
        self._seek_timer.setSingleShot(True)
        self._seek_timer.timeout.connect(self._grab_frame)

        # segnali slider
        self.sld_time.valueChanged.connect(self._on_seek_changed)
        self.sld_time.sliderReleased.connect(self._grab_frame)
        self.sld_time.actionTriggered.connect(self._on_seek_action)

        # root
        root = QVBoxLayout(self)
        root.addLayout(top)
        root.addLayout(mid)
        root.addLayout(bottom)

        # signals
        self.btn_frame.clicked.connect(self._grab_frame)
        self.btn_ok.clicked.connect(self._apply)
        self.btn_cancel.clicked.connect(self.reject)
        self.sp_w.valueChanged.connect(self._spins_to_rect)
        self.sp_h.valueChanged.connect(self._spins_to_rect)
        self.sp_x.valueChanged.connect(self._spins_to_rect)
        self.sp_y.valueChanged.connect(self._spins_to_rect)
        self.chk_force_169.toggled.connect(self._ar_exclusive)
        self.chk_force_scope.toggled.connect(self._ar_exclusive)
        self.sld_time.valueChanged.connect(self._on_seek_changed)

        # collega ora le callback del rettangolo (dopo aver creato chk_lock)
        self.crop_item.set_aspect_lock_getter(lambda: self.chk_lock.isChecked())
        self.crop_item.set_change_callback(lambda _r: self._sync_masks_and_fields())

        # init
        self.btn_frame.setEnabled(bool(self.input_path))
        if self.input_path:
            self._load_video_info()
            self._grab_frame()
        self._load_previous_settings()

    # --------------- helpers UI ---------------

    def _mk_spin(self, lo: int, hi: int, step: int) -> QSpinBox:
        sp = QSpinBox(self)
        sp.setRange(lo, hi)
        sp.setSingleStep(step)
        sp.setAlignment(Qt.AlignRight)
        # freccette visibili (default)
        return sp

    def _mk_grid(self, rows):
        lay = QVBoxLayout()
        for label, widget in rows:
            h = QHBoxLayout()
            h.addWidget(QLabel(label), 0)
            h.addWidget(widget, 1)
            lay.addLayout(h)
        return lay

    def reject(self):
        # “Annulla” = come dopo un riavvio: nessun crop attivo
        clear_crop_settings(disable_only=False)  # usa False se vuoi anche cancellare la rect
        super().reject()

    # --------------- backend ---------------

    # funzione di utilità
    def _fit_view(self):
        pm = self.img_item.pixmap()
        if not pm or pm.isNull():
            return
        self.view.resetTransform()
        r = self.img_item.mapRectToScene(self.img_item.boundingRect()).adjusted(-1, -1, 1, 1)
        self.scene.setSceneRect(r)
        self.view.fitInView(r, Qt.KeepAspectRatio)
        self.view.centerOn(self.img_item)
        self._has_pixmap = True

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._fit_view()

    def _ar_exclusive(self):
        if self.sender() is self.chk_force_169 and self.chk_force_169.isChecked():
            self.chk_force_scope.blockSignals(True); self.chk_force_scope.setChecked(False); self.chk_force_scope.blockSignals(False)
        elif self.sender() is self.chk_force_scope and self.chk_force_scope.isChecked():
            self.chk_force_169.blockSignals(True); self.chk_force_169.setChecked(False); self.chk_force_169.blockSignals(False)

    def _load_video_info(self):
        self.src_wh = probe_resolution(self.input_path)
        self.src_dur = probe_duration(self.input_path)
        if self.src_dur > 1.0:
            self.sld_time.setMaximum(int(self.src_dur))
            self.sld_time.setValue(min(int(self.grab_time), int(self.src_dur)))
            self.lbl_time.setText(self._fmt_time(self.sld_time.value(), self.src_dur))

    def _fmt_time(self, t: int, tot: float = 0.0) -> str:
        def mmss(x):
            m = int(x) // 60
            s = int(x) % 60
            return f"{m:02d}:{s:02d}"
        return f"{mmss(t)} / {mmss(tot)}" if tot else mmss(t)

    def _on_seek_changed(self, v: int):
        self.grab_time = float(v)
        self.lbl_time.setText(self._fmt_time(v, self.src_dur))
        # debounce: aspetta 250 ms dall’ultimo movimento prima di catturare
        self._seek_timer.start(250)

    def _on_seek_action(self, action: int):
        # quando usi PgUp/PgDn o le freccette, riavvia il debounce
        if action in (
            QAbstractSlider.SliderSingleStepAdd, QAbstractSlider.SliderSingleStepSub,
            QAbstractSlider.SliderPageStepAdd,   QAbstractSlider.SliderPageStepSub,
            QAbstractSlider.SliderMove
        ):
            self._seek_timer.start(250)

    def _grab_frame(self):
        if not self.input_path:
            QMessageBox.warning(self, "Attenzione", "Seleziona prima un file video nella finestra principale.")
            return

        FRAME_PATH.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg", "-hide_banner", "-nostdin",
            "-ss", f"{self.grab_time:.2f}",
            "-i", self.input_path,
            "-frames:v", "1", "-an", "-sn",
            "-y", str(FRAME_PATH)
        ]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            QMessageBox.critical(self, "Errore", "Impossibile estrarre un frame con ffmpeg.")
            return

        pix = QPixmap(str(FRAME_PATH))
        if pix.isNull():
            QMessageBox.critical(self, "Errore", "Frame non valido.")
            return

        self.pix = pix
        self.img_item.setPixmap(pix)

        # NIENTE setSceneRect qui: lascia fare al fit
        self.crop_item.set_bounds(QRectF(0, 0, pix.width(), pix.height()))
        self._fit_view()

        # default: 90% area, centrata (multipli di 2)
        if self.src_wh and not self._pending_spec:
            w = pix.width(); h = pix.height()
            cw = max(16, (int(w * 0.9) // 2) * 2)
            ch = max(16, (int(h * 0.9) // 2) * 2)
            cx = ((w - cw) // 2 // 2) * 2
            cy = ((h - ch) // 2 // 2) * 2
            self.crop_item.setRect(QRectF(cx, cy, cw, ch))

        # ripristina eventuale selezione salvata
        if self._pending_spec:
            s = self._pending_spec
            self.crop_item.setRect(QRectF(s.x, s.y, s.w, s.h))
            self._pending_spec = None

        self._sync_masks_and_fields()

    def _sync_masks_and_fields(self):
        if not self.pix:
            return
        r = self.crop_item.rect()
        W, H = self.pix.width(), self.pix.height()

        # maschere
        self.mask_top.setRect(QRectF(0, 0, W, r.top()))
        self.mask_bottom.setRect(QRectF(0, r.bottom(), W, H - r.bottom()))
        self.mask_left.setRect(QRectF(0, r.top(), r.left(), r.height()))
        self.mask_right.setRect(QRectF(r.right(), r.top(), W - r.right(), r.height()))
        self.scene.update()

        # spinbox (evita loop)
        self._guard = True
        self.sp_w.setValue(int(round(r.width())) // 2 * 2)
        self.sp_h.setValue(int(round(r.height())) // 2 * 2)
        self.sp_x.setValue(int(round(r.x())) // 2 * 2)
        self.sp_y.setValue(int(round(r.y())) // 2 * 2)
        self._guard = False

    def _spins_to_rect(self):
        if self._guard or not self.pix:
            return
        x = self.sp_x.value()
        y = self.sp_y.value()
        w = max(self.sp_w.value(), 16)
        h = max(self.sp_h.value(), 16)

        bw = int(self.pix.width())
        bh = int(self.pix.height())
        w = min(w, bw)
        h = min(h, bh)
        x = min(max(0, x), bw - w)
        y = min(max(0, y), bh - h)

        self.crop_item.setRect(QRectF(x, y, w, h))

        # aggiorna maschere (niente update spin per non innescare loop)
        r = self.crop_item.rect()
        self.mask_top.setRect(QRectF(0, 0, bw, r.top()))
        self.mask_bottom.setRect(QRectF(0, r.bottom(), bw, bh - r.bottom()))
        self.mask_left.setRect(QRectF(0, r.top(), r.left(), r.height()))
        self.mask_right.setRect(QRectF(r.right(), r.top(), bw - r.right(), r.height()))
        self.scene.update()

    def _load_previous_settings(self):
        """
        Carica le preferenze da QSettings con fallback sicuri.
        Supporta sia (spec, enabled) sia (spec, enabled, force_169, force_scope).
        Se la spec è invalida → forza enabled=False.
        """
        # default sicuri
        spec = None
        enabled = False
        force_169 = False
        force_scope = False

        try:
            res = load_crop_settings()  # può restituire 2 o 4 valori
            if isinstance(res, tuple):
                if len(res) == 4:
                    spec, enabled, force_169, force_scope = res
                elif len(res) == 2:
                    spec, enabled = res
                else:
                    # shape inattesa → lascia i default
                    pass
        except Exception:
            # settings mancanti/corrotti → lascia i default
            pass

        # valida la spec (deve avere x,y,w,h con w,h>0)
        def _valid(s):
            try:
                return (
                    s is not None and
                    int(getattr(s, "w")) > 0 and
                    int(getattr(s, "h")) > 0 and
                    int(getattr(s, "x")) >= 0 and
                    int(getattr(s, "y")) >= 0
                )
            except Exception:
                return False

        if not _valid(spec):
            enabled = False  # spec non utilizzabile → disabilita crop

        # aggiorna i checkbox
        self.chk_enable.setChecked(bool(enabled))
        if hasattr(self, "chk_force_169"):
            self.chk_force_169.setChecked(bool(force_169))
        if hasattr(self, "chk_force_scope"):
            self.chk_force_scope.setChecked(bool(force_scope))

        # applica la rect se abbiamo già il frame; altrimenti differisci
        if _valid(spec):
            if getattr(self, "pix", None):
                self.crop_item.setRect(QRectF(spec.x, spec.y, spec.w, spec.h))
                self._sync_masks_and_fields()
            else:
                self._pending_spec = spec
        else:
            # nessuna spec valida: azzera eventuale pending e resetta campi UI
            self._pending_spec = None
            try:
                self.crop_item.setRect(QRectF(0, 0, 0, 0))
                self._sync_masks_and_fields()
            except Exception:
                pass

    def _apply(self):
        if not self.pix:
            QMessageBox.warning(self, "Attenzione", "Nessun frame disponibile.")
            return
        r = self.crop_item.rect()
        w = int(r.width()) // 2 * 2
        h = int(r.height()) // 2 * 2
        x = int(r.x()) // 2 * 2
        y = int(r.y()) // 2 * 2

        if w < 16 or h < 16:
            QMessageBox.warning(self, "Attenzione", "Selezione troppo piccola.")
            return

        save_crop_settings(
            w, h, x, y,
            enabled=self.chk_enable.isChecked(),
            force_169=self.chk_force_169.isChecked(),
            force_scope=self.chk_force_scope.isChecked(),
        )
        self.accept()
