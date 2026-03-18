from __future__ import annotations

from pathlib import Path
from typing import Optional
import re
import subprocess

from PyQt5 import QtCore, QtGui, QtWidgets

from hevc_gui.mkv_suite.core.insert_clips import (
    InsertClipItem,
    build_insert_clips_plan,
    parse_progress_line,
    progress_percent_from_kv,
)
from hevc_gui.mkv_suite.core.precise_cut import ffprobe_json
from hevc_gui.mkv_suite.i18n import L as BASE_L


_INSERT_EN = {
    "Inserisci clip": "Insert clips",
    "Inserisci clip…": "Insert clips…",
    "Inserisci una o più clip nel file selezionato.": "Insert one or more clips into the selected file.",
    "Anteprima sorgente": "Source preview",
    "Anteprima": "Preview",
    "Anteprima clip": "Preview clip",
    "Anteprima risultato": "Preview result",
    "Torna alla sorgente": "Back to source",
    "Punto di inserimento": "Insertion point",
    "Usa posizione corrente": "Use current position",
    "Vai a": "Go to",
    "Vai": "Go",
    "Player non disponibile.": "Player not available.",
    "File sorgente": "Source file",
    "Clip": "Clip",
    "Clip muta": "Mute clip",
    "Volume clip": "Clip volume",
    "Contesto vicino": "Nearby context",
    "Media film": "Movie average",
    "Sfoglia clip…": "Browse clip…",
    "Aggiungi inserto": "Add insert",
    "Modifica inserto": "Edit insert",
    "Elimina inserto": "Delete insert",
    "Svuota elenco": "Clear list",
    "Inserto": "Insert",
    "Inserti": "Inserts",
    "Inserti…": "Inserts…",
    "Nessun inserto aggiunto": "No inserts added",
    "Inserti salvati:": "Saved inserts:",
    "Tempo": "Time",
    "Durata clip": "Clip duration",
    "Muta": "Mute",
    "Usa il formato hh:mm:ss.mmm": "Use format hh:mm:ss.mmm",
    "Scegli clip da inserire": "Choose clip to insert",
    "Seleziona prima una clip da inserire.": "Select a clip to insert first.",
    "Seleziona prima un inserto dall'elenco.": "Select an insert from the list first.",
    "Nessun inserto valido presente nell'elenco.": "No valid inserts are present in the list.",
    "Crea file con inserti": "Create file with inserts",
    "Preparazione inserti…": "Preparing inserts…",
    "Generazione preview sorgente…": "Building source preview…",
    "Preparazione anteprima risultato…": "Preparing result preview…",
    "Inserti in corso…": "Insert clips in progress…",
    "File con inserti creato:": "Inserted-clips file created:",
    "Creazione file con inserti fallita.": "Failed to create file with inserts.",
    "Anteprima risultato fallita.": "Result preview failed.",
    "Apri Dettagli per vedere il motivo.": "Open Details to see the reason.",
    "Comando eseguito:": "Executed command:",
    "Log finale:": "Final log:",
    "Nessun log disponibile.": "No log available.",
    "Scegli cartella output": "Choose output folder",
    "Cartella output": "Output folder",
    "Seleziona prima una cartella output.": "Select an output folder first.",
    "Apri cartella output": "Open output folder",
    "Nome file": "File name",
    "Chiudi": "Close",
    "Errore": "Error",
    "Info": "Info",
    "Il file di output esiste già. Vuoi sovrascriverlo?": "The output file already exists. Do you want to overwrite it?",
    "Play": "Play",
    "Pausa": "Pause",
    "Vol": "Vol",
    "Istruzioni / Manuale": "Instructions / Manual",
    "Informazioni sorgente": "Source information",
    "Nessun file sorgente selezionato.": "No source file selected.",
    "Seleziona un file video per iniziare.": "Select a video file to start.",
    "Apri manuale": "Open manual",
    "Info file": "File info",
    "Manuale Inserisci clip": "Insert clips manual",
    "Informazioni file sorgente": "Source file information",
    "Nessun dato disponibile.": "No data available.",
    "Video": "Video",
    "Audio": "Audio",
    "Sottotitoli": "Subtitles",
    "Contenitore": "Container",
    "Dimensione": "Size",
    "Bitrate": "Bitrate",
    "Risoluzione": "Resolution",
    "Frame rate": "Frame rate",
    "Lingua": "Language",
    "Titolo traccia": "Track title",
    "Canali": "Channels",
    "Sample rate": "Sample rate",
    "Durata": "Duration",
    "Percorso": "Path",
    "Formato pixel": "Pixel format",
    "SAR": "SAR",
    "DAR": "DAR",
}
def LT(s: str) -> str:
    try:
        probe = BASE_L("Chiudi")
        is_en = probe == "Close" or BASE_L("Sorgente") == "Source" or BASE_L("Apri") == "Open"
    except Exception:
        is_en = False
    if is_en:
        return _INSERT_EN.get(s, BASE_L(s))
    return BASE_L(s)


def _fmt_ms(ms: int) -> str:
    ms = max(0, int(ms))
    hh = ms // 3600000
    rem = ms % 3600000
    mm = rem // 60000
    rem %= 60000
    ss = rem // 1000
    mmm = rem % 1000
    return f"{hh:02d}:{mm:02d}:{ss:02d}.{mmm:03d}"


def _parse_tc(text: str) -> Optional[int]:
    s = str(text or "").strip()
    m = re.match(r"^(\d+):([0-5]\d):([0-5]\d)(?:\.(\d{1,3}))?$", s)
    if not m:
        return None
    hh = int(m.group(1))
    mm = int(m.group(2))
    ss = int(m.group(3))
    mmm = int((m.group(4) or "0").ljust(3, "0")[:3])
    return ((hh * 60 + mm) * 60 + ss) * 1000 + mmm


def _frame_ms_from_rate(rate: Optional[str]) -> int:
    s = (rate or "").strip()
    if not s or s in {"0/0", "N/A"}:
        return 40
    try:
        if "/" in s:
            a, b = s.split("/", 1)
            fps = float(a) / float(b)
        else:
            fps = float(s)
        if fps <= 0:
            return 40
        return max(1, int(round(1000.0 / fps)))
    except Exception:
        return 40



def _fmt_bytes(num: int) -> str:
    try:
        n = float(num)
    except Exception:
        return "?"
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while n >= 1024.0 and idx < len(units) - 1:
        n /= 1024.0
        idx += 1
    if idx == 0:
        return f"{int(n)} {units[idx]}"
    return f"{n:.2f} {units[idx]}"
class InsertItemsDialog(QtWidgets.QDialog):
    def __init__(self, owner: "InsertClipsDialog") -> None:
        super().__init__(owner)
        self._owner = owner
        self.setWindowTitle(LT("Inserti"))
        self.setModal(False)
        self.resize(520, 300)
        self.setMinimumSize(460, 260)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        self.lbl_status = QtWidgets.QLabel(LT("Nessun inserto aggiunto"), self)

        self.tbl = QtWidgets.QTableWidget(0, 4, self)
        self.tbl.setHorizontalHeaderLabels([LT("Tempo"), LT("Clip"), LT("Durata clip"), LT("Muta")])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.tbl.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.tbl.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.tbl.setAlternatingRowColors(True)
        hdr = self.tbl.horizontalHeader()
        hdr.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        hdr.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents)

        row_btn = QtWidgets.QHBoxLayout()
        self.btn_delete = QtWidgets.QPushButton(LT("Elimina inserto"), self)
        self.btn_clear = QtWidgets.QPushButton(LT("Svuota elenco"), self)
        self.btn_close = QtWidgets.QPushButton(LT("Chiudi"), self)
        for _b in (self.btn_delete, self.btn_clear, self.btn_close):
            _b.setMinimumHeight(22)
            _b.setMaximumHeight(22)
        row_btn.addWidget(self.btn_delete)
        row_btn.addWidget(self.btn_clear)
        row_btn.addStretch(1)
        row_btn.addWidget(self.btn_close)

        root.addWidget(self.lbl_status)
        root.addWidget(self.tbl, 1)
        root.addLayout(row_btn)

        self.tbl.itemSelectionChanged.connect(self._on_selection_changed)
        self.btn_delete.clicked.connect(self._delete_selected)
        self.btn_clear.clicked.connect(self._clear_all)
        self.btn_close.clicked.connect(self.close)

        self.sync_from_owner()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._geometry_restored:
            self._geometry_restored = True
            try:
                w = int(self._settings.value("window_width", 740))
                h = int(self._settings.value("window_height", 860))
            except Exception:
                w, h = 740, 860
            w = max(700, w)
            h = max(800, h)
            self.resize(w, h)
        QtCore.QTimer.singleShot(0, self._init_player_and_load)

    def sync_from_owner(self) -> None:
        owner = self._owner
        current_row = owner.tbl.currentRow() if getattr(owner, "tbl", None) is not None else -1

        self.tbl.blockSignals(True)
        self.tbl.setRowCount(0)

        count = owner.tbl.rowCount() if getattr(owner, "tbl", None) is not None else 0
        for r in range(count):
            row = self.tbl.rowCount()
            self.tbl.insertRow(row)
            for c in range(4):
                src_item = owner.tbl.item(r, c)
                if src_item is None:
                    continue
                dst = QtWidgets.QTableWidgetItem(src_item.text())
                dst.setData(QtCore.Qt.UserRole, src_item.data(QtCore.Qt.UserRole))
                self.tbl.setItem(row, c, dst)

        self.tbl.blockSignals(False)

        if 0 <= current_row < self.tbl.rowCount():
            self.tbl.selectRow(current_row)

        if count <= 0:
            self.lbl_status.setText(LT("Nessun inserto aggiunto"))
        else:
            self.lbl_status.setText(LT("Inserti salvati:") + f" {count}")

        self.btn_delete.setEnabled(self.tbl.currentRow() >= 0)
        self.btn_clear.setEnabled(count > 0)

    def _on_selection_changed(self) -> None:
        row = self.tbl.currentRow()
        try:
            if row >= 0:
                self._owner.tbl.setCurrentCell(row, 0)
        except Exception:
            pass
        self.btn_delete.setEnabled(row >= 0)

    def _delete_selected(self) -> None:
        row = self.tbl.currentRow()
        if row >= 0:
            try:
                self._owner.tbl.setCurrentCell(row, 0)
            except Exception:
                pass
        self._owner._remove_item()
        self.sync_from_owner()

    def _clear_all(self) -> None:
        self._owner._clear_items()
        self.sync_from_owner()



class InsertClipsDialog(QtWidgets.QDialog):
    def __init__(self, source_path: str | Path | None = None, parent=None):
        super().__init__(parent)
        self._source_path = Path(source_path).expanduser().resolve() if source_path else None
        self._proc: Optional[QtCore.QProcess] = None
        self._progress_state: dict[str, str] = {}
        self._debug_lines: list[str] = []
        self._debug_command = ""

        self._player = None
        self._duration_ms = 0
        self._current_ms = 0
        self._frame_ms = 40
        self._slider_drag = False
        self._items_dialog = None
        self._preview_result_path = None
        self._pending_seek_ms: Optional[int] = None
        self._player_loaded_path = self._source_path

        self.setWindowTitle(LT("Inserisci clip"))
        self.resize(740, 860)
        self.setModal(True)
        self.setMinimumSize(700, 800)
        self._settings = QtCore.QSettings("mkv-tools-suite", "insert_clips_dialog")
        self._geometry_restored = False

        self._build_ui()
        self._wire()
        self._load_info()
        self._apply_state()

        self._poll_timer = QtCore.QTimer(self)
        self._poll_timer.setInterval(120)
        self._poll_timer.timeout.connect(self._poll_player)

        self._seek_timer = QtCore.QTimer(self)
        self._seek_timer.setSingleShot(True)
        self._seek_timer.setInterval(70)
        self._seek_timer.timeout.connect(self._flush_pending_seek)

    def showEvent(self, event):
        super().showEvent(event)
        QtCore.QTimer.singleShot(0, lambda: self.resize(740, 860))
        QtCore.QTimer.singleShot(0, self._init_player_and_load)

    def closeEvent(self, event):
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
            self._seek_timer.stop()
        except Exception:
            pass
        try:
            if self._player is not None:
                self._player.terminate()
        except Exception:
            pass
        self._player = None
        super().closeEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        try:
            if self.isVisible() and not self.isMaximized() and not self.isMinimized():
                self._settings.setValue("window_width", int(self.width()))
                self._settings.setValue("window_height", int(self.height()))
        except Exception:
            pass

    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        gb_src = QtWidgets.QGroupBox(LT("File sorgente"), self)
        gl_src = QtWidgets.QGridLayout(gb_src)
        gl_src.setContentsMargins(8, 8, 8, 8)
        self.ed_source = QtWidgets.QLineEdit(self)
        self.ed_source.setReadOnly(True)

        self.btn_choose_source = QtWidgets.QPushButton(LT("Apri") + "…", self)
        self.btn_manual = QtWidgets.QToolButton(self)
        self.btn_info_src = QtWidgets.QToolButton(self)
        self.btn_manual.setToolTip(LT("Istruzioni / Manuale"))
        self.btn_info_src.setToolTip(LT("Informazioni sorgente"))
        self.btn_manual.setFixedSize(24, 24)
        self.btn_info_src.setFixedSize(24, 24)
        self._setup_header_icons()

        gl_src.addWidget(QtWidgets.QLabel(LT("File")), 0, 0)
        gl_src.addWidget(self.ed_source, 0, 1)
        gl_src.addWidget(self.btn_choose_source, 0, 2)
        gl_src.addWidget(self.btn_manual, 0, 3)
        gl_src.addWidget(self.btn_info_src, 0, 4)
        gl_src.setColumnStretch(1, 1)
        root.addWidget(gb_src)

        gb_prev = QtWidgets.QGroupBox(LT("Anteprima"), self)
        vl_prev = QtWidgets.QVBoxLayout(gb_prev)
        vl_prev.setContentsMargins(8, 8, 8, 8)
        vl_prev.setSpacing(10)

        self.video_frame = QtWidgets.QFrame(self)
        self.video_frame.setFrameShape(QtWidgets.QFrame.Box)
        self.video_frame.setMinimumSize(460, 280)
        self.video_frame.setStyleSheet("QFrame { background: #000; border: 1px solid #444; }")
        self.video_frame.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.video_frame.setAttribute(QtCore.Qt.WA_NativeWindow, True)
        self.video_frame.setAttribute(QtCore.Qt.WA_DontCreateNativeAncestors, True)
        vl_prev.addWidget(self.video_frame, 1)

        self.lbl_time = QtWidgets.QLabel("00:00:00.000 / 00:00:00.000", self)
        self.lbl_time.setAlignment(QtCore.Qt.AlignCenter)
        self.lbl_time.setMinimumHeight(26)
        self.lbl_time.setStyleSheet("QLabel { padding-top: 6px; padding-bottom: 2px; }")
        vl_prev.addWidget(self.lbl_time, 0)

        root.addWidget(gb_prev, 1)

        row_ctrl = QtWidgets.QHBoxLayout()
        self.btn_back1s = QtWidgets.QPushButton("<<", self)
        self.btn_back100 = QtWidgets.QPushButton("<", self)
        self.btn_backf = QtWidgets.QPushButton("<fine", self)
        self.btn_play = QtWidgets.QPushButton(LT("Play"), self)
        self.btn_fwd_f = QtWidgets.QPushButton("fine>", self)
        self.btn_fwd100 = QtWidgets.QPushButton(">", self)
        self.btn_fwd1s = QtWidgets.QPushButton(">>", self)
        self.lbl_vol = QtWidgets.QLabel(LT("Vol"), self)
        self.sld_vol = QtWidgets.QSlider(QtCore.Qt.Horizontal, self)
        self.sld_vol.setRange(0, 100)
        self.sld_vol.setValue(50)
        self.sld_vol.setMaximumWidth(90)

        self.sld_pos = QtWidgets.QSlider(QtCore.Qt.Horizontal, self)
        self.sld_pos.setRange(0, 0)
        self.sld_pos.setTracking(True)

        self.btn_backf.setToolTip(LT("Indietro di 1 frame"))
        self.btn_fwd_f.setToolTip(LT("Avanti di 1 frame"))

        for w in (self.btn_back1s, self.btn_back100, self.btn_backf, self.btn_play, self.btn_fwd_f, self.btn_fwd100, self.btn_fwd1s):
            row_ctrl.addWidget(w)
        row_ctrl.addSpacing(8)
        row_ctrl.addWidget(self.lbl_vol)
        row_ctrl.addWidget(self.sld_vol)
        row_ctrl.addSpacing(8)
        row_ctrl.addWidget(self.sld_pos, 1)
        root.addLayout(row_ctrl)

        self.gb_add = QtWidgets.QGroupBox(LT("Inserto"), self)
        gl_add = QtWidgets.QGridLayout(self.gb_add)

        self.ed_at = QtWidgets.QLineEdit(self)
        self.ed_at.setReadOnly(True)
        self.ed_at.setText("00:00:00.000")
        self.btn_use_current = QtWidgets.QPushButton(LT("Usa posizione corrente"), self)


        self.ed_clip = QtWidgets.QLineEdit(self)
        self.btn_browse_clip = QtWidgets.QPushButton(LT("Sfoglia clip…"), self)
        self.chk_mute = QtWidgets.QCheckBox(LT("Clip muta"), self)
        self.btn_add = QtWidgets.QPushButton(LT("Aggiungi inserto"), self)
        self.btn_update = QtWidgets.QPushButton(LT("Modifica inserto"), self)

        gl_add.addWidget(QtWidgets.QLabel(LT("Punto di inserimento")), 0, 0)
        gl_add.addWidget(self.ed_at, 0, 1)
        gl_add.addWidget(self.btn_use_current, 0, 2)


        gl_add.addWidget(QtWidgets.QLabel(LT("Clip")), 1, 0)
        gl_add.addWidget(self.ed_clip, 1, 1)
        gl_add.addWidget(self.btn_browse_clip, 1, 2)

        self.btn_preview_clip = QtWidgets.QPushButton(LT("Anteprima clip"), self)
        self.btn_preview_result = QtWidgets.QPushButton(LT("Anteprima risultato"), self)
        self.btn_restore_source = QtWidgets.QPushButton(LT("Torna alla sorgente"), self)

        row_edit = QtWidgets.QHBoxLayout()
        row_edit.addWidget(self.chk_mute)
        row_edit.addWidget(self.btn_preview_clip)
        row_edit.addWidget(self.btn_preview_result)
        row_edit.addWidget(self.btn_restore_source)
        row_edit.addWidget(self.btn_add)
        row_edit.addWidget(self.btn_update)
        row_edit.addStretch(1)
        gl_add.addLayout(row_edit, 2, 0, 1, 3)

        root.addWidget(self.gb_add)

        gb_audio = QtWidgets.QGroupBox(LT("Volume clip"), self)
        hl_audio = QtWidgets.QHBoxLayout(gb_audio)
        self.rb_audio_near = QtWidgets.QRadioButton(LT("Contesto vicino"), self)
        self.rb_audio_global = QtWidgets.QRadioButton(LT("Media film"), self)
        self.rb_audio_near.setChecked(True)
        self._bg_audio = QtWidgets.QButtonGroup(self)
        self._bg_audio.addButton(self.rb_audio_near)
        self._bg_audio.addButton(self.rb_audio_global)
        hl_audio.addWidget(self.rb_audio_near)
        hl_audio.addWidget(self.rb_audio_global)
        hl_audio.addStretch(1)
        root.addWidget(gb_audio)

        row_items = QtWidgets.QHBoxLayout()
        self.lbl_status = QtWidgets.QLabel(LT("Nessun inserto aggiunto"), self)
        self.btn_open_items = QtWidgets.QPushButton(LT("Inserti…"), self)
        row_items.addWidget(self.lbl_status)
        row_items.addStretch(1)
        row_items.addWidget(self.btn_open_items)
        root.addLayout(row_items)

        # hidden storage for inserts
        self.tbl = QtWidgets.QTableWidget(0, 4, self)
        self.tbl.setHorizontalHeaderLabels([LT("Tempo"), LT("Clip"), LT("Durata clip"), LT("Muta")])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.tbl.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.tbl.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.tbl.setAlternatingRowColors(True)
        self.tbl.hide()

        self.btn_remove = QtWidgets.QPushButton(LT("Elimina inserto"), self)
        self.btn_clear = QtWidgets.QPushButton(LT("Svuota elenco"), self)
        self.btn_remove.hide()
        self.btn_clear.hide()

        gb_out = QtWidgets.QGroupBox(LT("Output"), self)
        gl_out = QtWidgets.QGridLayout(gb_out)
        self.ed_out_dir = QtWidgets.QLineEdit(self)
        self.ed_out_dir.setClearButtonEnabled(True)
        self.btn_out_dir = QtWidgets.QToolButton(self)
        self.btn_out_dir.setText("…")
        self.ed_out_name = QtWidgets.QLineEdit(self)
        self.btn_open_out_dir = QtWidgets.QPushButton(LT("Apri cartella output"), self)

        self.ed_out_name.setMinimumWidth(260)
        self.ed_out_name.setMaximumWidth(360)
        self.btn_open_out_dir.setMinimumHeight(22)
        self.btn_open_out_dir.setMaximumHeight(22)

        gl_out.addWidget(QtWidgets.QLabel(LT("Cartella output")), 0, 0)
        gl_out.addWidget(self.ed_out_dir, 0, 1)
        gl_out.addWidget(self.btn_out_dir, 0, 2)

        gl_out.addWidget(QtWidgets.QLabel(LT("Nome file")), 1, 0)
        gl_out.addWidget(self.ed_out_name, 1, 1)
        gl_out.addWidget(self.btn_open_out_dir, 1, 2)

        root.addWidget(gb_out)

        self.progress = QtWidgets.QProgressBar(self)
        self.progress.setTextVisible(True)
        self.progress.setAlignment(QtCore.Qt.AlignCenter)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("0%")
        self.progress.setFixedHeight(18)
        self.progress.setMinimumWidth(260)
        self.progress.setStyleSheet(
            "QProgressBar::chunk { background: transparent; width: 0px; margin: 0px; border: none; }"
        )

        row_footer = QtWidgets.QHBoxLayout()
        row_footer.setSpacing(8)
        row_footer.addWidget(self.progress, 1)
        self.btn_create = QtWidgets.QPushButton(LT("Crea file con inserti"), self)
        self.btn_close = QtWidgets.QPushButton(LT("Chiudi"), self)
        row_footer.addWidget(self.btn_create)
        row_footer.addWidget(self.btn_close)
        root.addLayout(row_footer)

        for _b in (
            self.btn_back1s,
            self.btn_back100,
            self.btn_backf,
            self.btn_play,
            self.btn_fwd_f,
            self.btn_fwd100,
            self.btn_fwd1s,
            self.btn_use_current,
            self.btn_browse_clip,
            self.btn_preview_clip,
            self.btn_restore_source,
            self.btn_add,
            self.btn_update,
            self.btn_open_items,
            self.btn_create,
            self.btn_close,
        ):
            _b.setMinimumHeight(22)
            _b.setMaximumHeight(22)

        for _b in (self.btn_back1s, self.btn_back100, self.btn_fwd100, self.btn_fwd1s):
            _b.setMinimumWidth(30)
            _b.setMaximumWidth(30)

        self.btn_backf.setMinimumWidth(46)
        self.btn_backf.setMaximumWidth(46)
        self.btn_fwd_f.setMinimumWidth(46)
        self.btn_fwd_f.setMaximumWidth(46)
        self.btn_play.setMinimumWidth(52)
        self.btn_play.setMaximumWidth(52)
        self.lbl_vol.setMinimumWidth(24)
        self.lbl_vol.setMaximumWidth(24)
        self.sld_vol.setMinimumWidth(80)
        self.sld_vol.setMaximumWidth(110)
        self.btn_out_dir.setFixedSize(22, 22)

    def _wire(self) -> None:
        self.btn_browse_clip.clicked.connect(self._choose_clip)
        self.btn_add.clicked.connect(self._add_item)
        self.btn_update.clicked.connect(self._update_item)
        self.btn_remove.clicked.connect(self._remove_item)
        self.btn_clear.clicked.connect(self._clear_items)
        self.tbl.itemSelectionChanged.connect(self._on_select)
        self.btn_open_items.clicked.connect(self._open_items_dialog)

        self.btn_preview_clip.clicked.connect(self._preview_current_clip)
        self.btn_preview_result.clicked.connect(self._preview_current_result)
        self.btn_restore_source.clicked.connect(self._restore_source_preview)
        self.btn_choose_source.clicked.connect(self._choose_source_file)
        self.btn_manual.clicked.connect(self._show_manual)
        self.btn_info_src.clicked.connect(self._show_source_info)
        self.btn_out_dir.clicked.connect(self._choose_out_dir)
        self.btn_open_out_dir.clicked.connect(self._open_out_dir)
        self.btn_create.clicked.connect(self._create_output)
        self.btn_close.clicked.connect(self.reject)

        self.btn_use_current.clicked.connect(self._use_current_position)
        self.btn_play.clicked.connect(self._toggle_play)
        self.btn_back1s.clicked.connect(lambda: self._seek_rel_ms(-1000))
        self.btn_fwd1s.clicked.connect(lambda: self._seek_rel_ms(1000))
        self.btn_back100.clicked.connect(lambda: self._seek_rel_ms(-100))
        self.btn_fwd100.clicked.connect(lambda: self._seek_rel_ms(100))
        self.btn_backf.clicked.connect(lambda: self._seek_rel_ms(-self._frame_ms))
        self.btn_fwd_f.clicked.connect(lambda: self._seek_rel_ms(self._frame_ms))
        self.sld_pos.sliderPressed.connect(self._on_slider_pressed)
        self.sld_pos.valueChanged.connect(self._on_slider_value_changed_live)
        self.sld_pos.sliderReleased.connect(self._on_slider_released)
        self.sld_vol.valueChanged.connect(self._set_volume)

    def _load_info(self) -> None:
        if self._source_path is None or not Path(self._source_path).is_file():
            self.ed_source.clear()
            self.ed_out_dir.clear()
            self.ed_out_dir.setPlaceholderText("")
            self.ed_out_name.clear()
            self._duration_ms = 0
            self._frame_ms = 40
            self.sld_pos.setRange(0, 0)
            self._update_time_label(0)
            self._update_play_button_text(True)
            return

        self.ed_source.setText(str(self._source_path))
        self.ed_out_dir.clear()
        self.ed_out_dir.setPlaceholderText("")
        self.ed_out_name.setText(self._source_path.stem + "_inserted.mkv")
        self._load_video_info()


    def _source_parent_dir(self) -> Path:
        if self._source_path is not None:
            try:
                return Path(self._source_path).expanduser().resolve().parent
            except Exception:
                pass
        return Path.home()

    def _has_source(self) -> bool:
        try:
            return self._source_path is not None and Path(self._source_path).is_file()
        except Exception:
            return False

    def _sync_source_dependent_state(self) -> None:
        src_ok = self._has_source()

        for w in (
            self.gb_add,
            self.btn_use_current,
            self.btn_browse_clip,
            self.btn_preview_clip,
            self.btn_preview_result,
            self.btn_restore_source,
            self.btn_add,
            self.btn_update,
            self.btn_open_items,
            self.btn_create,
            self.btn_out_dir,
            self.btn_open_out_dir,
            self.btn_info_src,
            self.sld_pos,
            self.sld_vol,
            self.btn_play,
            self.btn_back1s,
            self.btn_back100,
            self.btn_backf,
            self.btn_fwd_f,
            self.btn_fwd100,
            self.btn_fwd1s,
            self.rb_audio_near,
            self.rb_audio_global,
        ):
            try:
                w.setEnabled(src_ok)
            except Exception:
                pass

        try:
            self.btn_choose_source.setEnabled(True)
        except Exception:
            pass

    def _choose_source_file(self) -> None:
        start = str(self._source_parent_dir())
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            LT("Apri"),
            start,
            "Video files (*.mkv *.mp4 *.avi *.mov *.ts *.m2ts *.m4v *.webm);;All files (*.*)",
        )
        if path:
            self._set_source_path(Path(path))

    def _set_source_path(self, path: str | Path | None) -> None:
        p = Path(path).expanduser().resolve() if path else None
        if p is None or not p.is_file():
            QtWidgets.QMessageBox.warning(self, LT("Errore"), LT("Seleziona un file video per iniziare."))
            return

        self._source_path = p
        self._player_loaded_path = p
        self._preview_result_path = None
        self._duration_ms = 0
        self._current_ms = 0
        self._frame_ms = 40

        try:
            self.tbl.setRowCount(0)
        except Exception:
            pass

        try:
            self.ed_at.setText("00:00:00.000")
            self.ed_clip.clear()
            self.chk_mute.setChecked(False)
        except Exception:
            pass

        self._load_info()
        self._apply_state()
        self._sync_source_dependent_state()

        if self._player is None:
            self._init_player_and_load()
        else:
            try:
                self._stop_playback()
            except Exception:
                pass
            try:
                self._player.command("loadfile", str(p), "replace")
            except Exception:
                pass
            self._poll_timer.start()
            QtCore.QTimer.singleShot(150, lambda: self._seek_to_ms(0, exact=True))


    def _setup_header_icons(self) -> None:
        help_path = Path(__file__).resolve().parents[1] / "assets" / "icons" / "ph_help.png"
        manual_icon = QtGui.QIcon(str(help_path)) if help_path.is_file() else QtGui.QIcon()
        info_icon = self.style().standardIcon(QtWidgets.QStyle.SP_MessageBoxInformation)

        if manual_icon.isNull():
            manual_icon = self.style().standardIcon(QtWidgets.QStyle.SP_DialogHelpButton)

        self.btn_manual.setIcon(manual_icon)
        self.btn_info_src.setIcon(info_icon)

        self.btn_manual.setText("")
        self.btn_info_src.setText("")

        self.btn_manual.setIconSize(QtCore.QSize(16, 16))
        self.btn_info_src.setIconSize(QtCore.QSize(16, 16))

        self.btn_manual.setAutoRaise(True)
        self.btn_info_src.setAutoRaise(True)

        self.btn_manual.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
        self.btn_info_src.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)

        self.btn_manual.setToolTip(LT("Istruzioni / Manuale"))
        self.btn_info_src.setToolTip(LT("Informazioni sorgente"))

    def _manual_text(self) -> str:
        is_en = False
        try:
            is_en = (LT("Chiudi") == "Close")
        except Exception:
            is_en = False

        if is_en:
            return """
<h3>Insert clips - quick guide</h3>
<p><b>Purpose:</b> insert one or more clips into the current source file and check the result before creating the final file.</p>

<h4>Basic workflow</h4>
<ol>
  <li>Move the player to the exact point where the clip must be inserted.</li>
  <li>Press <b>Use current position</b>. This saves the insertion point.</li>
  <li>Choose the clip with <b>Browse clip…</b>.</li>
  <li>Press <b>Add insert</b> to save it in the list.</li>
  <li>Open <b>Inserts…</b> to check what you have saved.</li>
  <li>Use <b>Preview clip</b> to view only the selected clip.</li>
  <li>Use <b>Preview result</b> to see how the final result will look around the insertion point.</li>
  <li>Choose the audio mode that sounds better.</li>
  <li>Choose the output folder and file name.</li>
  <li>Press <b>Create file with inserts</b>.</li>
</ol>

<h4>What the main buttons do</h4>
<ul>
  <li><b>Use current position</b>: copies the current player position into the insertion point field.</li>
  <li><b>Add insert</b>: saves the current insert in the list.</li>
  <li><b>Edit insert</b>: updates the selected insert from the list.</li>
  <li><b>Inserts…</b>: shows the saved inserts.</li>
  <li><b>Preview clip</b>: plays only the clip.</li>
  <li><b>Preview result</b>: plays a short preview of the final mounted result.</li>
  <li><b>Back to source</b>: returns to the original source preview.</li>
</ul>

<h4>Useful notes</h4>
<ul>
  <li>If the insertion point is wrong, move the player again and press <b>Use current position</b>.</li>
  <li>If the result looks wrong, use <b>Preview result</b> before creating the final file.</li>
  <li>If output folder is empty, choose it manually before creating the file.</li>
</ul>
"""
        return """
<h3>Inserisci clip - guida rapida</h3>
<p><b>Scopo:</b> inserire una o più clip nel file sorgente corrente e controllare il risultato prima di creare il file finale.</p>

<h4>Procedura base</h4>
<ol>
  <li>Sposta il player nel punto esatto in cui vuoi inserire la clip.</li>
  <li>Premi <b>Usa posizione corrente</b>. Questo salva il punto di inserimento.</li>
  <li>Scegli la clip con <b>Sfoglia clip…</b>.</li>
  <li>Premi <b>Aggiungi inserto</b> per salvarla nell'elenco.</li>
  <li>Apri <b>Inserti…</b> per controllare cosa hai salvato.</li>
  <li>Usa <b>Anteprima clip</b> per vedere solo la clip selezionata.</li>
  <li>Usa <b>Anteprima risultato</b> per vedere come verrà il montaggio finale attorno al punto di inserimento.</li>
  <li>Scegli la modalità audio che suona meglio.</li>
  <li>Scegli cartella output e nome file.</li>
  <li>Premi <b>Crea file con inserti</b>.</li>
</ol>

<h4>A cosa servono i pulsanti principali</h4>
<ul>
  <li><b>Usa posizione corrente</b>: copia la posizione attuale del player nel campo del punto di inserimento.</li>
  <li><b>Aggiungi inserto</b>: salva l'inserto corrente nell'elenco.</li>
  <li><b>Modifica inserto</b>: aggiorna l'inserto selezionato dall'elenco.</li>
  <li><b>Inserti…</b>: mostra l'elenco degli inserti salvati.</li>
  <li><b>Anteprima clip</b>: riproduce solo la clip.</li>
  <li><b>Anteprima risultato</b>: riproduce una preview breve del risultato finale montato.</li>
  <li><b>Torna alla sorgente</b>: rimette nel player il video originale.</li>
</ul>

<h4>Note utili</h4>
<ul>
  <li>Se il punto di inserimento è sbagliato, sposta di nuovo il player e premi <b>Usa posizione corrente</b>.</li>
  <li>Se il risultato non ti convince, controlla prima con <b>Anteprima risultato</b> invece di creare subito il file finale.</li>
  <li>Se la cartella output è vuota, sceglila manualmente prima di creare il file.</li>
</ul>
"""
    def _show_text_dialog(self, title: str, text: str, width: int = 780, height: int = 560) -> None:
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(title)
        dlg.resize(width, height)

        lay = QtWidgets.QVBoxLayout(dlg)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        box = QtWidgets.QTextBrowser(dlg)
        box.setOpenExternalLinks(False)
        box.setReadOnly(True)

        if "<h3>" in text or "<p>" in text or "<ul>" in text or "<ol>" in text:
            box.setHtml(text)
        else:
            box.setPlainText(text)

        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        btn = QtWidgets.QPushButton(LT("Chiudi"), dlg)
        btn.clicked.connect(dlg.accept)
        row.addWidget(btn)

        lay.addWidget(box, 1)
        lay.addLayout(row)
        dlg.exec_()
    def _show_manual(self) -> None:
        self._show_text_dialog(LT("Manuale Inserisci clip"), self._manual_text(), 820, 620)
    def _source_info_text(self) -> str:
        try:
            data = ffprobe_json(self._source_path)
        except Exception as e:
            return f"{LT('Errore')}: {e}"

        fmt = data.get("format") or {}
        streams = data.get("streams") or []

        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        audios = [s for s in streams if s.get("codec_type") == "audio"]
        subs = [s for s in streams if s.get("codec_type") == "subtitle"]

        lines = []
        lines.append(f"{LT('Percorso')}: {self._source_path}")
        lines.append(f"{LT('Contenitore')}: {fmt.get('format_long_name') or fmt.get('format_name') or '?'}")
        lines.append(f"{LT('Dimensione')}: {_fmt_bytes(int(fmt.get('size') or 0))}")
        try:
            dur_ms = int(round(float(fmt.get('duration') or 0.0) * 1000.0))
            lines.append(f"{LT('Durata')}: {_fmt_ms(dur_ms)}")
        except Exception:
            lines.append(f"{LT('Durata')}: ?")
        try:
            br = int(fmt.get('bit_rate') or 0)
            lines.append(f"{LT('Bitrate')}: {br // 1000} kb/s" if br > 0 else f"{LT('Bitrate')}: ?")
        except Exception:
            lines.append(f"{LT('Bitrate')}: ?")

        if video:
            lines.append("")
            lines.append(f"[{LT('Video')}]")
            lines.append(f"Codec: {video.get('codec_name') or '?'}")
            lines.append(f"{LT('Risoluzione')}: {video.get('width') or '?'}x{video.get('height') or '?'}")
            rate = video.get('avg_frame_rate') or video.get('r_frame_rate') or '?'
            lines.append(f"{LT('Frame rate')}: {rate}")
            lines.append(f"{LT('Formato pixel')}: {video.get('pix_fmt') or '?'}")
            lines.append(f"{LT('SAR')}: {video.get('sample_aspect_ratio') or '?'}")
            lines.append(f"{LT('DAR')}: {video.get('display_aspect_ratio') or '?'}")

        if audios:
            for idx, a in enumerate(audios, start=1):
                lines.append("")
                lines.append(f"[{LT('Audio')} #{idx}]")
                lines.append(f"Codec: {a.get('codec_name') or '?'}")
                lines.append(f"{LT('Canali')}: {a.get('channels') or '?'}")
                sr = a.get('sample_rate') or '?'
                lines.append(f"{LT('Sample rate')}: {sr}")
                tags = a.get('tags') or {}
                lines.append(f"{LT('Lingua')}: {tags.get('language') or '?'}")
                lines.append(f"{LT('Titolo traccia')}: {tags.get('title') or '?'}")

        if subs:
            for idx, s in enumerate(subs, start=1):
                lines.append("")
                lines.append(f"[{LT('Sottotitoli')} #{idx}]")
                lines.append(f"Codec: {s.get('codec_name') or '?'}")
                tags = s.get('tags') or {}
                lines.append(f"{LT('Lingua')}: {tags.get('language') or '?'}")
                lines.append(f"{LT('Titolo traccia')}: {tags.get('title') or '?'}")

        if not lines:
            return LT("Nessun dato disponibile.")
        return "\n".join(lines)

    def _show_source_info(self) -> None:
        if not self._has_source():
            QtWidgets.QMessageBox.information(self, LT("Info"), LT("Nessun file sorgente selezionato."))
            return
        self._show_text_dialog(LT("Informazioni file sorgente"), self._source_info_text(), 760, 560)

    def _load_video_info(self) -> None:
        if not self._has_source():
            self._duration_ms = 0
            self._frame_ms = 40
            self.sld_pos.setRange(0, 0)
            self._update_time_label(0)
            self._update_play_button_text(True)
            return

        try:
            data = ffprobe_json(self._source_path)
            fmt = data.get("format") or {}
            self._duration_ms = int(round(float(fmt.get("duration") or 0.0) * 1000.0))
            streams = data.get("streams") or []
            v = next((s for s in streams if s.get("codec_type") == "video"), None)
            rate = None
            if v:
                rate = v.get("avg_frame_rate") or v.get("r_frame_rate")
            self._frame_ms = _frame_ms_from_rate(rate)
        except Exception:
            self._duration_ms = 0
            self._frame_ms = 40

        self.sld_pos.setRange(0, max(0, self._duration_ms))
        self._update_time_label(0)
        self._update_play_button_text(True)

    def _apply_state(self) -> None:
        self._on_select()
        self._refresh_status()
        self._update_time_label(0)
        self._update_play_button_text(True)
        self.btn_restore_source.setEnabled(False)
        self._sync_source_dependent_state()

    def _update_time_label(self, current_ms: Optional[int] = None) -> None:
        if current_ms is None:
            current_ms = self._current_ms
        self.lbl_time.setText(f"{_fmt_ms(int(current_ms))} / {_fmt_ms(self._duration_ms)}")

    def _update_play_button_text(self, paused: bool) -> None:
        self.btn_play.setText(LT("Play") if paused else LT("Pausa"))

    def _refresh_status(self) -> None:
        n = self.tbl.rowCount()
        if n <= 0:
            self.lbl_status.setText(LT("Nessun inserto aggiunto"))
        else:
            self.lbl_status.setText(LT("Inserti salvati:") + f" {n}")

        dlg = getattr(self, "_items_dialog", None)
        if dlg is not None and dlg.isVisible():
            try:
                dlg.sync_from_owner()
            except Exception:
                pass

    def _open_items_dialog(self) -> None:
        dlg = getattr(self, "_items_dialog", None)
        if dlg is None:
            dlg = InsertItemsDialog(self)
            self._items_dialog = dlg
        dlg.sync_from_owner()
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _on_select(self) -> None:
        row = self.tbl.currentRow()
        self.btn_update.setEnabled(row >= 0)
        self.btn_remove.setEnabled(row >= 0)
        self.btn_clear.setEnabled(self.tbl.rowCount() > 0)

        try:
            self.btn_preview_clip.setEnabled(bool(self.ed_clip.text().strip()) and self._has_source())
        except Exception:
            pass

        restore_enabled = False
        try:
            if self._has_source():
                loaded = getattr(self, "_player_loaded_path", None)
                if loaded is not None:
                    loaded_p = Path(loaded).expanduser().resolve()
                    src_p = Path(self._source_path).expanduser().resolve()
                    restore_enabled = (loaded_p != src_p)
        except Exception:
            restore_enabled = False

        try:
            self.btn_restore_source.setEnabled(restore_enabled)
        except Exception:
            pass

        try:
            self._populate_editor_from_selected()
        except Exception:
            pass
    def _populate_editor_from_selected(self) -> None:
        row = self.tbl.currentRow()
        if row < 0:
            return
        it0 = self.tbl.item(row, 0)
        it1 = self.tbl.item(row, 1)
        it3 = self.tbl.item(row, 3)
        if it0 is not None:
            self.ed_at.setText(it0.text())
        if it1 is not None:
            self.ed_clip.setText(it1.text())
        if it3 is not None:
            try:
                self.chk_mute.setChecked(bool(it3.data(QtCore.Qt.UserRole)))
            except Exception:
                self.chk_mute.setChecked(str(it3.text()).strip().lower() in {"yes", "true", "1", "si", "sì"})
        self.btn_preview_clip.setEnabled(bool(self.ed_clip.text().strip()))

    def _init_player_and_load(self) -> None:
        if self._player is not None:
            return
        if not self._has_source():
            return
        try:
            import mpv  # type: ignore
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, LT("Errore"), LT("Player non disponibile.") + "\n" + str(e))
            return

        try:
            self._player = mpv.MPV(
                wid=str(int(self.video_frame.winId())),
                osc=False,
                pause=True,
                idle=True,
                keep_open="always",
                force_window="yes",
                input_default_bindings=False,
                input_vo_keyboard=False,
                cursor_autohide="no",
                audio_display="no",
            )

            try:
                self._player.volume = int(self.sld_vol.value())
            except Exception:
                try:
                    self._player.command("set", "volume", str(int(self.sld_vol.value())))
                except Exception:
                    pass

            self._player.command("loadfile", str(self._source_path), "replace")
            try:
                self._player.command("set", "pause", "yes")
            except Exception:
                try:
                    self._player.pause = True
                except Exception:
                    pass

            self._poll_timer.start()
            QtCore.QTimer.singleShot(150, lambda: self._seek_to_ms(0, exact=True))

        except Exception as e:
            self._player = None
            QtWidgets.QMessageBox.warning(self, LT("Errore"), LT("Player non disponibile.") + "\n" + str(e))
    def _player_command(self, *args):
        if self._player is None:
            self._init_player_and_load()
        if self._player is None:
            return
        return self._player.command(*args)

    def _probe_duration_ms(self, path: Path) -> int:
        p = Path(path).expanduser().resolve()
        if not p.is_file():
            return 0
        try:
            data = ffprobe_json(p)
            return int(round(float((data.get("format") or {}).get("duration") or 0.0) * 1000.0))
        except Exception:
            return 0

    def _load_media_for_preview(self, path: str | Path, *, autoplay: bool = True) -> None:
        target = Path(path).expanduser().resolve()
        if not target.is_file():
            raise RuntimeError(LT("Seleziona prima una clip da inserire."))

            QtWidgets.QMessageBox.warning(self, LT("Errore"), LT("Player non disponibile.") + "\n" + str(e))
        self._player_command("loadfile", str(target), "replace")
        self._player_loaded_path = target

        self._duration_ms = self._probe_duration_ms(target)
        self.sld_pos.setRange(0, max(0, self._duration_ms))
        self._current_ms = 0
        self.sld_pos.setValue(0)
        self._update_time_label(0)
        self.btn_restore_source.setEnabled(target != self._source_path)

        QtCore.QTimer.singleShot(180, lambda: self._seek_to_ms(0, exact=True))
        if autoplay:
            QtCore.QTimer.singleShot(260, self._start_playback)

    def _restore_source_preview(self) -> None:
        if not self._has_source():
            return
        try:
            self._load_media_for_preview(self._source_path, autoplay=False)
            self.btn_restore_source.setEnabled(False)
        except Exception:
            pass

    def _preview_current_clip(self) -> None:
        clip_text = self.ed_clip.text().strip()
        if not clip_text:
            QtWidgets.QMessageBox.warning(self, LT("Errore"), LT("Seleziona prima una clip da inserire."))
            return
        clip_path = Path(clip_text).expanduser().resolve()
        if not clip_path.is_file():
            QtWidgets.QMessageBox.warning(self, LT("Errore"), LT("Seleziona prima una clip da inserire."))
            return
        try:
            self._load_media_for_preview(clip_path, autoplay=True)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, LT("Errore"), str(e))


    def _preview_tmp_dir(self) -> Path:
        root = Path(__file__).resolve().parents[3] / "tmp" / "insert_result_preview"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _run_capture(self, cmd: list[str]) -> tuple[int, str]:
        cp = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return int(cp.returncode), str(cp.stdout or "")


    def _audio_match_mode(self) -> str:
        try:
            if self.rb_audio_global.isChecked():
                return "global"
        except Exception:
            pass
        return "nearby"

    def _build_insert_plan(self, source_path, output_path, items):
        return build_insert_clips_plan(
            source_path,
            output_path,
            items,
            audio_match_mode=self._audio_match_mode(),
        )

    def _preview_current_result(self) -> None:
        try:
            at_ms, clip_path, mute = self._read_editor_values()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, LT("Errore"), str(e))
            return

        try:
            try:
                src_duration_ms = int(self._probe_duration_ms(self._source_path))
            except Exception:
                data = ffprobe_json(self._source_path)
                src_duration_ms = int(round(float((data.get("format") or {}).get("duration") or 0.0) * 1000.0))

            if src_duration_ms <= 0:
                raise RuntimeError("Durata sorgente non disponibile.")

            before_ms = 5000
            after_ms = 5000
            start_ms = max(0, at_ms - before_ms)
            end_ms = min(src_duration_ms, at_ms + after_ms)
            local_insert_ms = at_ms - start_ms

            tmp_dir = self._preview_tmp_dir()
            src_preview = tmp_dir / f"{self._source_path.stem}_src_preview.mkv"
            out_preview = tmp_dir / f"{self._source_path.stem}_insert_preview.mkv"

            for p in (src_preview, out_preview):
                try:
                    if p.exists():
                        p.unlink()
                except Exception:
                    pass

            extract_cmd = [
                "ffmpeg",
                "-hide_banner",
                "-nostdin",
                "-y",
                "-loglevel", "error",
                "-ss", f"{start_ms / 1000.0:.3f}",
                "-to", f"{end_ms / 1000.0:.3f}",
                "-i", str(self._source_path),
                "-map", "0:v:0",
                "-map", "0:a?",
                "-sn",
                "-dn",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "18",
                "-c:a", "aac",
                "-b:a", "192k",
                str(src_preview),
            ]

            self._set_progress_busy(LT("Generazione preview sorgente…"))
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            try:
                code1, log1 = self._run_capture(extract_cmd)
            finally:
                QtWidgets.QApplication.restoreOverrideCursor()

            if code1 != 0 or not src_preview.is_file():
                self._set_progress_idle()
                msg = QtWidgets.QMessageBox(self)
                msg.setIcon(QtWidgets.QMessageBox.Critical)
                msg.setWindowTitle(LT("Errore"))
                msg.setText(LT("Anteprima risultato fallita."))
                msg.setInformativeText(LT("Apri Dettagli per vedere il motivo."))
                msg.setDetailedText(log1.strip() or LT("Nessun log disponibile."))
                msg.setStandardButtons(QtWidgets.QMessageBox.Ok)
                msg.exec_()
                return

            plan = self._build_insert_plan(
                src_preview,
                out_preview,
                [InsertClipItem(insert_at=local_insert_ms / 1000.0, clip_path=clip_path, mute=mute)],
            )

            self._set_progress_busy(LT("Preparazione anteprima risultato…"))
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            try:
                code2, log2 = self._run_capture(plan.command)
            finally:
                QtWidgets.QApplication.restoreOverrideCursor()

            if code2 != 0 or not out_preview.is_file():
                self._set_progress_idle()
                details = (
                    LT("Comando eseguito:") + "\n" + " ".join(plan.command) +
                    "\n\n" + LT("Log finale:") + "\n" + (log2.strip() or LT("Nessun log disponibile."))
                )
                msg = QtWidgets.QMessageBox(self)
                msg.setIcon(QtWidgets.QMessageBox.Critical)
                msg.setWindowTitle(LT("Errore"))
                msg.setText(LT("Anteprima risultato fallita."))
                msg.setInformativeText(LT("Apri Dettagli per vedere il motivo."))
                msg.setDetailedText(details)
                msg.setStandardButtons(QtWidgets.QMessageBox.Ok)
                msg.exec_()
                return

            self._preview_result_path = out_preview
            self._set_progress_idle()
            self._load_media_for_preview(out_preview, autoplay=True)

        except Exception as e:
            self._set_progress_idle()
            QtWidgets.QMessageBox.warning(self, LT("Errore"), str(e))
    def _poll_player(self) -> None:
        if self._player is None:
            return

        try:
            dur = getattr(self._player, "duration", None)
            if dur:
                dur_ms = max(0, int(float(dur) * 1000))
                if dur_ms > 0 and dur_ms != self._duration_ms:
                    self._duration_ms = dur_ms
                    try:
                        self.sld_pos.setRange(0, dur_ms)
                    except Exception:
                        self.sld_pos.setMaximum(dur_ms)
        except Exception:
            pass

        try:
            pos = getattr(self._player, "time_pos", None)
            if pos is None:
                try:
                    pos = self._player.property("time-pos")
                except Exception:
                    pos = None

            if pos is not None:
                self._current_ms = max(0, int(round(float(pos) * 1000.0)))
                if not self._slider_drag:
                    new_val = min(max(0, self._current_ms), self.sld_pos.maximum())
                    self.sld_pos.blockSignals(True)
                    try:
                        self.sld_pos.setValue(new_val)
                    finally:
                        self.sld_pos.blockSignals(False)
        except Exception:
            pass

        self.lbl_time.setText(f"{_fmt_ms(self._current_ms)} / {_fmt_ms(self._duration_ms)}")

        try:
            paused = bool(getattr(self._player, "pause", True))
        except Exception:
            try:
                paused = bool(self._player.property("pause"))
            except Exception:
                paused = True

        self.btn_play.setText(LT("Play") if paused else LT("Pausa"))
    def _seek_to_ms(self, ms: int, exact: bool = True) -> None:
        ms = max(0, min(int(ms), max(0, self._duration_ms)))
        mode = "absolute+exact" if exact else "absolute"
        try:
            self._player_command("seek", f"{ms / 1000.0:.3f}", mode)
            self._current_ms = ms
            if not self._slider_drag:
                self.sld_pos.blockSignals(True)
                try:
                    self.sld_pos.setValue(ms)
                finally:
                    self.sld_pos.blockSignals(False)
            self.lbl_time.setText(f"{_fmt_ms(self._current_ms)} / {_fmt_ms(self._duration_ms)}")
        except Exception:
            pass
    def _seek_rel_ms(self, delta_ms: int) -> None:
        self._seek_to_ms(self._current_ms + int(delta_ms), exact=True)

    def _start_playback(self) -> None:
        if self._player is None:
            return
        try:
            self._player.command("set", "pause", "no")
        except Exception:
            try:
                self._player.pause = False
            except Exception:
                pass
        self._update_play_button_text(False)

    def _stop_playback(self) -> None:
        if self._player is None:
            return
        try:
            self._player.command("set", "pause", "yes")
        except Exception:
            try:
                self._player.pause = True
            except Exception:
                pass
        self._update_play_button_text(True)

    def _toggle_play(self) -> None:
        if self._player is None:
            self._init_player_and_load()
        if self._player is None:
            return

        paused = True
        try:
            paused = bool(getattr(self._player, "pause", True))
        except Exception:
            try:
                paused = bool(self._player.property("pause"))
            except Exception:
                paused = True

        try:
            if paused:
                try:
                    self._player.pause = False
                except Exception:
                    self._player.command("set", "pause", "no")
                self.btn_play.setText(LT("Pausa"))
            else:
                try:
                    self._player.pause = True
                except Exception:
                    self._player.command("set", "pause", "yes")
                self.btn_play.setText(LT("Play"))
        except Exception:
            pass
    def _set_volume(self, value: int) -> None:
        if self._player is None:
            return
        try:
            self._player.volume = int(value)
        except Exception:
            try:
                self._player.command("set", "volume", str(int(value)))
            except Exception:
                pass
    def _on_slider_pressed(self) -> None:
        self._slider_drag = True

    def _on_slider_value_changed_live(self, value: int) -> None:
        self._current_ms = int(value)
        self._update_time_label(int(value))

        if not self._slider_drag:
            return

        self._pending_seek_ms = int(value)
        try:
            self._seek_timer.start()
        except Exception:
            self._seek_to_ms(int(value), exact=False)

    def _flush_pending_seek(self) -> None:
        if self._pending_seek_ms is None:
            return
        ms = int(self._pending_seek_ms)
        self._pending_seek_ms = None
        self._seek_to_ms(ms, exact=False)

    def _on_slider_released(self) -> None:
        final_ms = self.sld_pos.value()
        self._slider_drag = False
        try:
            self._seek_timer.stop()
        except Exception:
            pass
        self._pending_seek_ms = None
        self._seek_to_ms(final_ms, exact=True)
    def _use_current_position(self) -> None:
        self.ed_at.setText(_fmt_ms(self._current_ms))

    def _choose_clip(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            LT("Scegli clip da inserire"),
            str(self._source_parent_dir()),
            "Video files (*.mkv *.mp4 *.avi *.mov *.ts *.m2ts);;All files (*.*)",
        )
        if path:
            self.ed_clip.setText(path)
            try:
                self.btn_preview_clip.setEnabled(True)
            except Exception:
                pass

    def _choose_out_dir(self) -> None:
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            LT("Scegli cartella output"),
            self.ed_out_dir.text().strip() or str(self._source_path.parent),
        )
        if path:
            self.ed_out_dir.setText(path)

    def _open_out_dir(self) -> None:
        raw = self.ed_out_dir.text().strip()
        if not raw:
            QtWidgets.QMessageBox.warning(self, LT("Errore"), LT("Seleziona prima una cartella output."))
            return

        path = Path(raw).expanduser().resolve()
        if not path.exists() or not path.is_dir():
            QtWidgets.QMessageBox.warning(self, LT("Errore"), LT("Seleziona prima una cartella output."))
            return

        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))

    def _clip_duration_pretty(self, clip_path: Path) -> str:
        try:
            data = ffprobe_json(clip_path)
            dur = float((data.get("format") or {}).get("duration") or 0.0)
            return _fmt_ms(int(round(dur * 1000.0)))
        except Exception:
            return "?"

    def _set_row(self, row: int, at_ms: int, clip_path: Path, mute: bool) -> None:
        it0 = QtWidgets.QTableWidgetItem(_fmt_ms(at_ms))
        it0.setData(QtCore.Qt.UserRole, int(at_ms))
        it1 = QtWidgets.QTableWidgetItem(str(clip_path))
        it1.setData(QtCore.Qt.UserRole, str(clip_path))
        it2 = QtWidgets.QTableWidgetItem(self._clip_duration_pretty(clip_path))
        it3 = QtWidgets.QTableWidgetItem("yes" if mute else "no")
        it3.setData(QtCore.Qt.UserRole, bool(mute))
        self.tbl.setItem(row, 0, it0)
        self.tbl.setItem(row, 1, it1)
        self.tbl.setItem(row, 2, it2)
        self.tbl.setItem(row, 3, it3)

    def _sort_rows(self) -> None:
        rows = []
        for r in range(self.tbl.rowCount()):
            it0 = self.tbl.item(r, 0)
            it1 = self.tbl.item(r, 1)
            it3 = self.tbl.item(r, 3)
            if not it0 or not it1:
                continue
            rows.append((
                int(it0.data(QtCore.Qt.UserRole)),
                Path(str(it1.data(QtCore.Qt.UserRole))),
                bool(it3.data(QtCore.Qt.UserRole)) if it3 else False,
            ))
        rows.sort(key=lambda x: (x[0], str(x[1])))
        self.tbl.setRowCount(0)
        for at_ms, clip_path, mute in rows:
            row = self.tbl.rowCount()
            self.tbl.insertRow(row)
            self._set_row(row, at_ms, clip_path, mute)

    def _collect_items(self) -> list[InsertClipItem]:
        out: list[InsertClipItem] = []
        for r in range(self.tbl.rowCount()):
            it0 = self.tbl.item(r, 0)
            it1 = self.tbl.item(r, 1)
            it3 = self.tbl.item(r, 3)
            if not it0 or not it1:
                continue
            at_ms = int(it0.data(QtCore.Qt.UserRole))
            clip_path = Path(str(it1.data(QtCore.Qt.UserRole)))
            mute = bool(it3.data(QtCore.Qt.UserRole)) if it3 else False
            out.append(InsertClipItem(insert_at=at_ms / 1000.0, clip_path=clip_path, mute=mute))
        return out

    def _read_editor_values(self):
        at_ms = _parse_tc(self.ed_at.text().strip())
        if at_ms is None:
            raise RuntimeError(LT("Usa il formato hh:mm:ss.mmm"))
        clip_text = self.ed_clip.text().strip()
        if not clip_text:
            raise RuntimeError(LT("Seleziona prima una clip da inserire."))
        clip_path = Path(clip_text).expanduser().resolve()
        if not clip_path.is_file():
            raise RuntimeError(LT("Seleziona prima una clip da inserire."))
        return int(at_ms), clip_path, bool(self.chk_mute.isChecked())

    def _add_item(self) -> None:
        try:
            at_ms, clip_path, mute = self._read_editor_values()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, LT("Errore"), str(e))
            return
        row = self.tbl.rowCount()
        self.tbl.insertRow(row)
        self._set_row(row, at_ms, clip_path, mute)
        self._sort_rows()
        self._refresh_status()
        self._on_select()

    def _update_item(self) -> None:
        row = self.tbl.currentRow()
        if row < 0:
            QtWidgets.QMessageBox.information(self, LT("Info"), LT("Seleziona prima un inserto dall'elenco."))
            return
        try:
            at_ms, clip_path, mute = self._read_editor_values()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, LT("Errore"), str(e))
            return
        self._set_row(row, at_ms, clip_path, mute)
        self._sort_rows()
        self._refresh_status()
        self._on_select()

    def _remove_item(self) -> None:
        row = self.tbl.currentRow()
        if row < 0:
            return
        self.tbl.removeRow(row)
        self._refresh_status()
        self._on_select()

    def _clear_items(self) -> None:
        if self.tbl.rowCount() <= 0:
            return
        self.tbl.setRowCount(0)
        self._refresh_status()
        self._on_select()

    def _output_path(self) -> Path:
        out_dir = Path(self.ed_out_dir.text().strip() or self._source_path.parent)
        name = self.ed_out_name.text().strip() or (self._source_path.stem + "_inserted.mkv")
        return out_dir / name

    def _set_progress_idle(self) -> None:
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("0%")
        self.progress.setStyleSheet(
            "QProgressBar::chunk { background: transparent; width: 0px; margin: 0px; border: none; }"
        )

    def _set_progress_busy(self, text: str) -> None:
        self.progress.setRange(0, 0)
        self.progress.setFormat(text)
        self.progress.setStyleSheet("")

    def _set_progress_value(self, value: int) -> None:
        v = max(0, min(100, int(value)))
        self.progress.setRange(0, 100)
        self.progress.setValue(v)
        self.progress.setFormat(f"{v}%")
        if v <= 0:
            self.progress.setStyleSheet(
                "QProgressBar::chunk { background: transparent; width: 0px; margin: 0px; border: none; }"
            )
        else:
            self.progress.setStyleSheet("")

    def _create_output(self) -> None:
        items = self._collect_items()
        if not items:
            QtWidgets.QMessageBox.warning(self, LT("Errore"), LT("Nessun inserto valido presente nell'elenco."))
            return

        out_path = self._output_path()
        if out_path.exists():
            ans = QtWidgets.QMessageBox.question(
                self,
                LT("Conferma"),
                LT("Il file di output esiste già. Vuoi sovrascriverlo?") + "\n" + str(out_path),
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No,
            )
            if ans != QtWidgets.QMessageBox.Yes:
                return

        out_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            plan = self._build_insert_plan(self._source_path, out_path, items)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, LT("Errore"), str(e))
            return

        self._debug_lines = []
        self._debug_command = " ".join(plan.command)
        self._progress_state = {}

        proc = QtCore.QProcess(self)
        proc.setProgram(plan.command[0])
        proc.setArguments(plan.command[1:])
        proc.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        proc.readyReadStandardOutput.connect(lambda: self._on_stdout(plan))
        proc.finished.connect(lambda code, status: self._on_finished(plan, int(code), int(status)))
        self._proc = proc

        self._set_progress_busy(LT("Preparazione inserti…"))
        proc.start()
        if not proc.waitForStarted(3000):
            self._proc = None
            self._set_progress_idle()
            QtWidgets.QMessageBox.critical(self, LT("Errore"), LT("Creazione file con inserti fallita."))

    def _on_stdout(self, plan) -> None:
        if self._proc is None:
            return
        raw = bytes(self._proc.readAllStandardOutput()).decode("utf-8", errors="replace")
        if not raw:
            return

        for line in raw.splitlines():
            line = line.rstrip()
            if not line:
                continue
            self._debug_lines.append(line)
            if len(self._debug_lines) > 200:
                self._debug_lines = self._debug_lines[-200:]

            is_boundary, self._progress_state = parse_progress_line(line, self._progress_state)
            if not is_boundary:
                continue
            pct = progress_percent_from_kv(self._progress_state, float(getattr(plan, "total_duration", 0.0) or 0.0))
            if pct is not None:
                self._set_progress_value(int(round(pct)))
            if self._progress_state.get("progress") == "end":
                self._progress_state = {}

    def _on_finished(self, plan, exit_code: int, exit_status: int) -> None:
        self._proc = None
        debug_tail = "\n".join(self._debug_lines[-40:]).strip() or LT("Nessun log disponibile.")
        details = LT("Comando eseguito:") + "\n" + self._debug_command + "\n\n" + LT("Log finale:") + "\n" + debug_tail

        ok = (exit_code == 0 and Path(plan.output_path).is_file())
        if ok:
            self._set_progress_value(100)
            QtWidgets.QMessageBox.information(
                self,
                LT("Info"),
                LT("File con inserti creato:") + "\n" + str(plan.output_path),
            )
        else:
            self._set_progress_idle()
            msg = QtWidgets.QMessageBox(self)
            msg.setIcon(QtWidgets.QMessageBox.Critical)
            msg.setWindowTitle(LT("Errore"))
            msg.setText(LT("Creazione file con inserti fallita."))
            msg.setInformativeText(LT("Apri Dettagli per vedere il motivo."))
            msg.setDetailedText(details)
            msg.setStandardButtons(QtWidgets.QMessageBox.Ok)
            msg.exec_()
