from __future__ import annotations

from pathlib import Path
from typing import Optional
import subprocess
import shutil
import json

import mpv
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt

try:
    from hevc_gui.mkv_suite.i18n import L
except Exception:
    def LT(s: str) -> str:
        return s


try:
    from hevc_gui.mkv_suite.core.precise_cut import (
        build_precise_cut_plan,
        build_precise_multi_cut_plan,
        parse_progress_line,
        progress_percent_from_kv,
    )
except Exception:
    build_precise_cut_plan = None
    build_precise_multi_cut_plan = None
    parse_progress_line = None
    progress_percent_from_kv = None

BASE_L = L

_CUT_DIALOG_EN = {
    "A": "To",
    "Aggiungi qui i pezzi da togliere dal video.": "Add here the parts to remove from the video.",
    "Aggiungi taglio": "Add cut",
    "Aiuto": "Help",
    "Anteprima taglio": "Cut preview",
    "Anteprime": "Previews",
    "Apri": "Open",
    "Apri Dettagli per vedere il motivo.": "Open Details to see the reason.",
    "Azzera": "Reset",
    "Cartella output": "Output folder",
    "Seleziona prima una cartella output.": "Select an output folder first.",
    "Chiudi": "Close",
    "Comandi principali": "Main controls",
    "Comando eseguito:": "Executed command:",
    "Completato": "Completed",
    "Con più tagli viene usato automaticamente il taglio preciso.": "With multiple cuts, precise cut is used automatically.",
    "Con questi punti non rimane nulla da riprodurre.": "With these points nothing remains to be played.",
    "Conferma": "Confirm",
    "Conferma taglio rapido": "Confirm fast cut",
    "Crea file senza i tagli": "Create file without cuts",
    "Crea file tagliato": "Create cut file",
    "Creazione file tagliato fallita.": "Failed to create cut file.",
    "Creazione file tagliato fallita:": "Failed to create cut file:",
    "Da": "From",
    "Durata": "Duration",
    "Durata:": "Duration:",
    "Elimina taglio": "Delete cut",
    "Errore": "Error",
    "File": "File",
    "File name": "File name",
    "File tagliato creato:": "Cut file created:",
    "File sorgente:": "Source file:",
    "Istruzioni / Manuale": "Instructions / Manual",
    "Istruzioni taglio video": "Video cut instructions",
    "Impossibile avviare ffmpeg per il taglio preciso.": "Unable to start ffmpeg for precise cut.",
    "Impossibile avviare ffmpeg per i tagli multipli.": "Unable to start ffmpeg for multiple cuts.",
    "Info": "Info",
    "Informazioni": "Information",
    "Informazioni sorgente": "Source information",
    "Informazioni file sorgente": "Source file information",
    "Nessun file sorgente selezionato.": "No source file selected.",
    "Seleziona un file video per iniziare.": "Select a video file to start.",
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
    "Percorso": "Path",
    "Formato pixel": "Pixel format",
    "SAR": "SAR",
    "DAR": "DAR",
    "Log finale:": "Final log:",
    "Modalità": "Mode",
    "Mode": "Mode",
    "Modifica taglio": "Edit cut",
    "Modulo precise_cut non disponibile.": "precise_cut module not available.",
    "Nessun taglio aggiunto": "No cuts added",
    "Nessun taglio valido presente nell'elenco.": "No valid cuts in the list.",
    "Nessun log disponibile.": "No log available.",
    "Nome file": "File name",
    "Operazione": "Operation",
    "OUT deve essere maggiore di IN.": "OUT must be greater than IN.",
    "Output": "Output",
    "Output folder": "Output folder",
    "Per la massima precisione usa Taglio preciso": "For maximum precision use Precise cut",
    "Per togliere pubblicità o più spezzoni usa Tagli multipli": "To remove ads or multiple clips use Multiple cuts",
    "Per vedere il risultato completo con più tagli, crea prima il file.": "To see the complete result with multiple cuts, create the file first.",
    "Play/Pausa": "Play/Pause",
    "Preparazione taglio preciso…": "Preparing precise cut…",
    "Preparazione tagli multipli…": "Preparing multiple cuts…",
    "Preparazione…": "Preparing…",
    "Preview": "Preview",
    "Preview del file creato non disponibile, uso la preview simulata.": "Preview of the created file is not available, using simulated preview.",
    "Preview risultato": "Result preview",
    "Preview selezione": "Selection preview",
    "Pronto": "Ready",
    "Questa finestra serve per scegliere i punti del taglio direttamente dal player con audio.": "This window is used to choose cut points directly from the player with audio.",
    "Rimuovi il tratto IN → OUT": "Remove the IN → OUT range",
    "Scambia IN/OUT": "Swap IN/OUT",
    "Se devi togliere più pezzi dallo stesso video, usa il pulsante Tagli multipli…": "If you need to remove multiple parts from the same video, use the Multiple cuts… button.",
    "Se il file di output esiste già. Vuoi sovrascriverlo?": "The output file already exists. Do you want to overwrite it?",
    "Se il file esiste già, verrà chiesta conferma prima di sovrascriverlo": "If the file already exists, confirmation will be requested before overwriting it",
    "Segna IN": "Set IN",
    "Segna OUT": "Set OUT",
    "Seleziona prima un taglio dall'elenco.": "Select a cut from the list first.",
    "Sorgente": "Source",
    "Source": "Source",
    "spostamento di 1 secondo": "move by 1 second",
    "spostamento di 100 ms": "move by 100 ms",
    "spostamento di 1 frame": "move by 1 frame",
    "Suggerimenti": "Tips",
    "Svuota elenco": "Clear list",
    "Tagli multipli": "Multiple cuts",
    "Tagli multipli…": "Multiple cuts…",
    "Tagli salvati:": "Saved cuts:",
    "Taglio": "Cut",
    "Taglio e modalità": "Cut and mode",
    "Taglio preciso": "Precise cut",
    "Taglio preciso (ricodifica assistita)": "Precise cut (assisted re-encode)",
    "Taglio preciso in corso…": "Precise cut in progress…",
    "Taglio rapido": "Fast cut",
    "Taglio rapido (senza ricodifica)": "Fast cut (without re-encoding)",
    "Taglio singolo": "Single cut",
    "Taglio video": "Video cut",
    "Taglio selezionato non valido.": "Selected cut is not valid.",
    "Tieni il tratto": "Keep range",
    "Tieni solo il tratto IN → OUT": "Keep only the IN → OUT range",
    "torna alla finestra principale e premi Crea file senza i tagli": "go back to the main window and press Create file without cuts",
    "Vai a": "Go to",
    "Vol": "Vol",
    "Vuoi continuare con questi punti reali del taglio rapido?": "Do you want to continue with these actual fast-cut points?",
    "Vuoi svuotare l'elenco dei tagli?": "Do you want to clear the cut list?",
    "chiudi pure la finestrella: i tagli restano salvati": "you can close the small window: the cuts stay saved",
    "imposta DA e A per il primo pezzo da togliere": "set FROM and TO for the first part to remove",
    "mostra il risultato finale; se il file è già stato creato, apre proprio quello": "shows the final result; if the file is already created, it opens that file itself",
    "più lento, ma rispetta molto meglio i punti scelti e ricrea il file prendendo automaticamente i parametri utili dal sorgente": "slower, but it matches the chosen points much more accurately and recreates the file by automatically taking useful parameters from the source",
    "più veloce e senza ricodifica, ma può agganciarsi ai keyframe e non essere preciso al fotogramma": "faster and without re-encoding, but it may snap to keyframes and not be frame-accurate",
    "premi Aggiungi taglio": "press Add cut",
    "premi Crea file tagliato": "press Create cut file",
    "ripeti per tutti gli altri pezzi": "repeat for all the other parts",
    "riproduce il tratto scelto tra IN e OUT": "plays the selected part between IN and OUT",
    "riproduzione reale con audio": "real playback with audio",
    "salto diretto a un tempo preciso": "jump directly to an exact time",
    "scegli se tenere solo quel tratto oppure rimuoverlo": "choose whether to keep only that part or remove it",
    "usa Preview selezione o Preview risultato per controllare": "use Selection preview or Result preview to check it",
    "vai al punto finale e imposta OUT": "go to the end point and set OUT",
    "vai al punto iniziale e imposta IN": "go to the start point and set IN"
}

def LT(s: str) -> str:
    try:
        probe = BASE_L("Chiudi")
        is_en = probe == "Close" or BASE_L("Sorgente") == "Source" or BASE_L("Apri") == "Open"
    except Exception:
        is_en = False

    if is_en:
        return _CUT_DIALOG_EN.get(s, BASE_L(s))
    return BASE_L(s)

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

class MultiCutsDialog(QtWidgets.QDialog):
    def __init__(self, owner: "CutDialog") -> None:
        super().__init__(owner)
        self._owner = owner
        self.setWindowTitle(LT("Tagli multipli"))
        self.setModal(False)
        self.resize(620, 300)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        self.lbl_info = QtWidgets.QLabel(LT("Aggiungi qui i pezzi da togliere dal video."), self)

        self.tbl = QtWidgets.QTableWidget(0, 3, self)
        self.tbl.setHorizontalHeaderLabels([LT("Da"), LT("A"), LT("Durata")])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.tbl.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.tbl.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.tbl.setAlternatingRowColors(True)
        self.tbl.setMinimumHeight(160)
        hdr = self.tbl.horizontalHeader()
        hdr.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)

        row_btn = QtWidgets.QHBoxLayout()
        self.btn_add = QtWidgets.QPushButton(LT("Aggiungi taglio"), self)
        self.btn_update = QtWidgets.QPushButton(LT("Modifica taglio"), self)
        self.btn_delete = QtWidgets.QPushButton(LT("Elimina taglio"), self)
        self.btn_clear = QtWidgets.QPushButton(LT("Svuota elenco"), self)
        self.btn_preview = QtWidgets.QPushButton(LT("Anteprima taglio"), self)
        self.btn_close = QtWidgets.QPushButton(LT("Chiudi"), self)

        row_btn.addWidget(self.btn_add)
        row_btn.addWidget(self.btn_update)
        row_btn.addWidget(self.btn_delete)
        row_btn.addWidget(self.btn_clear)
        row_btn.addStretch(1)
        row_btn.addWidget(self.btn_preview)
        row_btn.addWidget(self.btn_close)

        root.addWidget(self.lbl_info)
        root.addWidget(self.tbl)
        root.addLayout(row_btn)

        self.tbl.itemSelectionChanged.connect(self._on_selection_changed)
        self.btn_add.clicked.connect(self._add_cut)
        self.btn_update.clicked.connect(self._update_cut)
        self.btn_delete.clicked.connect(self._delete_cut)
        self.btn_clear.clicked.connect(self._clear_cuts)
        self.btn_preview.clicked.connect(self._preview_cut)
        self.btn_close.clicked.connect(self.close)

        self.sync_from_owner()

    def sync_from_owner(self) -> None:
        owner = self._owner
        current_row = -1
        try:
            current_row = owner.tbl_multi_cuts.currentRow()
        except Exception:
            current_row = -1

        self.tbl.blockSignals(True)
        self.tbl.setRowCount(0)

        count = 0
        if getattr(owner, "tbl_multi_cuts", None) is not None:
            count = owner.tbl_multi_cuts.rowCount()

        for r in range(count):
            vals = owner._cut_list_row_values(r)
            if vals is None:
                continue
            start_ms, end_ms = vals
            row = self.tbl.rowCount()
            self.tbl.insertRow(row)

            item_a = QtWidgets.QTableWidgetItem(owner._format_ms(int(start_ms)))
            item_a.setData(QtCore.Qt.UserRole, int(start_ms))
            item_b = QtWidgets.QTableWidgetItem(owner._format_ms(int(end_ms)))
            item_b.setData(QtCore.Qt.UserRole, int(end_ms))
            item_d = QtWidgets.QTableWidgetItem(owner._format_ms(max(0, int(end_ms) - int(start_ms))))
            item_d.setData(QtCore.Qt.UserRole, max(0, int(end_ms) - int(start_ms)))

            self.tbl.setItem(row, 0, item_a)
            self.tbl.setItem(row, 1, item_b)
            self.tbl.setItem(row, 2, item_d)

        self.tbl.blockSignals(False)

        if 0 <= current_row < self.tbl.rowCount():
            self.tbl.selectRow(current_row)

        n = self.tbl.rowCount()
        if n <= 0:
            self.lbl_info.setText(LT("Aggiungi qui i pezzi da togliere dal video."))
        else:
            self.lbl_info.setText(LT("Tagli salvati:") + f" {n}")

        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        row = self.tbl.currentRow()
        has_rows = self.tbl.rowCount() > 0
        self.btn_update.setEnabled(row >= 0)
        self.btn_delete.setEnabled(row >= 0)
        self.btn_preview.setEnabled(row >= 0)
        self.btn_clear.setEnabled(has_rows)

    def _on_selection_changed(self) -> None:
        row = self.tbl.currentRow()
        if row >= 0 and getattr(self._owner, "tbl_multi_cuts", None) is not None:
            try:
                self._owner.tbl_multi_cuts.setCurrentCell(row, 0)
            except Exception:
                pass
        self._refresh_buttons()

    def _add_cut(self) -> None:
        self._owner._add_current_cut_to_list()
        self.sync_from_owner()

    def _update_cut(self) -> None:
        row = self.tbl.currentRow()
        if row >= 0 and getattr(self._owner, "tbl_multi_cuts", None) is not None:
            self._owner.tbl_multi_cuts.setCurrentCell(row, 0)
        self._owner._update_selected_cut_in_list()
        self.sync_from_owner()

    def _delete_cut(self) -> None:
        row = self.tbl.currentRow()
        if row >= 0 and getattr(self._owner, "tbl_multi_cuts", None) is not None:
            self._owner.tbl_multi_cuts.setCurrentCell(row, 0)
        self._owner._delete_selected_cut_from_list()
        self.sync_from_owner()

    def _clear_cuts(self) -> None:
        self._owner._clear_cut_list()
        self.sync_from_owner()

    def _preview_cut(self) -> None:
        row = self.tbl.currentRow()
        if row >= 0 and getattr(self._owner, "tbl_multi_cuts", None) is not None:
            self._owner.tbl_multi_cuts.setCurrentCell(row, 0)
        self._owner._preview_selected_cut()
        self._refresh_buttons()


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


class CutDialog(QtWidgets.QDialog):
    def __init__(self, source_path: str | Path | None = None, parent=None):
        super().__init__(parent)

        self._source_path = Path(source_path).expanduser().resolve() if source_path else None
        self._duration_ms = 0
        self._current_ms = 0
        self._in_ms: Optional[int] = None
        self._out_ms: Optional[int] = None
        self._busy = False

        self._player: Optional[mpv.MPV] = None
        self._player_inited = False
        self._slider_dragging = False
        self._pending_seek_ms: Optional[int] = None
        self._preview_out_stop_ms: Optional[int] = None
        self._preview_skip_from_ms: Optional[int] = None
        self._preview_skip_to_ms: Optional[int] = None
        self._volume_value = 70
        self._keyframes_ms_cache: Optional[list[int]] = None

        self._precise_proc = None
        self._precise_plan = None
        self._precise_progress_state: dict[str, str] = {}
        self._precise_debug_lines: list[str] = []
        self._precise_debug_command = ""
        self._last_created_cut_path = None
        self._multi_cut_last_preview_row = -1
        self._multi_cuts_dialog = None
        self._multi_inline_group = None
        self._player_loaded_path = self._source_path

        self._repo_root = Path(__file__).resolve().parents[3]
        self._tmp_dir = self._repo_root / "tmp" / "cut_preview"
        self._tmp_dir.mkdir(parents=True, exist_ok=True)

        self._poll_timer = QtCore.QTimer(self)
        self._poll_timer.setInterval(120)

        self._seek_timer = QtCore.QTimer(self)
        self._seek_timer.setSingleShot(True)
        self._seek_timer.setInterval(35)

        self.setWindowTitle(LT(L("Taglio video")))
        self.setModal(True)
        self.resize(740, 860)
        self.setMinimumSize(700, 800)
        self._settings = QtCore.QSettings("mkv-tools-suite", "cut_dialog")
        self._geometry_restored = False

        self._build_ui()
        self._wire_signals()
        self._load_source_info()
        self._apply_initial_state()

    # ------------------------------------------------------------
    # UI
    # ------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # --- sorgente ---
        gb_src = QtWidgets.QGroupBox(LT("Sorgente"), self)
        gl_src = QtWidgets.QGridLayout(gb_src)
        gl_src.setContentsMargins(8, 8, 8, 8)
        gl_src.setHorizontalSpacing(6)
        gl_src.setVerticalSpacing(4)

        self.ed_source = QtWidgets.QLineEdit(self)
        self.ed_source.setReadOnly(True)

        # tenuta solo per compatibilità/info, non mostrata nel layout
        self.lbl_duration = QtWidgets.QLabel("00:00:00.000", self)
        self.lbl_duration.hide()

        self.btn_choose_source = QtWidgets.QPushButton(LT("Apri") + "…", self)
        self.btn_info = QtWidgets.QToolButton(self)
        self.btn_info.setText("i")
        self.btn_info.setToolTip(LT("Informazioni sorgente"))

        self.btn_help = QtWidgets.QToolButton(self)
        self.btn_help.setText("?")
        self.btn_help.setToolTip(LT("Aiuto"))

        gl_src.addWidget(QtWidgets.QLabel(LT("File")), 0, 0)
        gl_src.addWidget(self.ed_source, 0, 1)
        gl_src.addWidget(self.btn_choose_source, 0, 2)
        gl_src.addWidget(self.btn_info, 0, 3)
        gl_src.addWidget(self.btn_help, 0, 4)

        root.addWidget(gb_src)

        # --- preview ---
        gb_prev = QtWidgets.QGroupBox(LT("Preview"), self)
        vl_prev = QtWidgets.QVBoxLayout(gb_prev)
        vl_prev.setContentsMargins(8, 8, 8, 8)
        vl_prev.setSpacing(10)

        self.preview_host = QtWidgets.QFrame(self)
        self.preview_host.setMinimumSize(700, 320)
        self.preview_host.setStyleSheet("QFrame { background: #000; border: 1px solid #444; }")
        self.preview_host.setAttribute(Qt.WA_NativeWindow, True)
        self.preview_host.setAttribute(Qt.WA_DontCreateNativeAncestors, True)

        self.lbl_pos = QtWidgets.QLabel("00:00:00.000 / 00:00:00.000", self)
        self.lbl_pos.setAlignment(Qt.AlignCenter)
        self.lbl_pos.setMinimumHeight(26)
        self.lbl_pos.setVisible(True)
        self.lbl_pos.setStyleSheet("QLabel { padding-top: 6px; padding-bottom: 2px; }")

        vl_prev.addWidget(self.preview_host, 1)
        vl_prev.addWidget(self.lbl_pos, 0)

        root.addWidget(gb_prev, 1)

        # --- navigazione ---
        nav = QtWidgets.QHBoxLayout()

        self.btn_back_big = QtWidgets.QPushButton("<<", self)
        self.btn_back_small = QtWidgets.QPushButton("<", self)
        self.btn_back_fine = QtWidgets.QPushButton("<fine", self)
        self.btn_play_pause = QtWidgets.QPushButton(LT("Play"), self)
        self.btn_fwd_fine = QtWidgets.QPushButton("fine>", self)
        self.btn_fwd_small = QtWidgets.QPushButton(">", self)
        self.btn_fwd_big = QtWidgets.QPushButton(">>", self)

        self.lbl_volume = QtWidgets.QLabel(LT("Vol"), self)
        self.sld_volume = QtWidgets.QSlider(Qt.Horizontal, self)
        self.sld_volume.setMinimum(0)
        self.sld_volume.setMaximum(100)
        self.sld_volume.setValue(self._volume_value)
        self.sld_volume.setMaximumWidth(110)
        self.sld_volume.setToolTip(LT("Volume preview audio"))
        self.btn_back_fine.setToolTip(LT("Indietro di 1 frame"))
        self.btn_fwd_fine.setToolTip(LT("Avanti di 1 frame"))

        self.sld_pos = QtWidgets.QSlider(Qt.Horizontal, self)
        self.sld_pos.setTracking(True)
        self.sld_pos.setMinimum(0)
        self.sld_pos.setMaximum(0)

        self.ed_goto = QtWidgets.QLineEdit(self)
        self.ed_goto.setPlaceholderText("00:00:00.000")
        self.ed_goto.setText("00:00:00.000")
        self.ed_goto.setMaximumWidth(130)

        self.btn_goto = QtWidgets.QPushButton(LT("Vai a"), self)

        nav.addWidget(self.btn_back_big)
        nav.addWidget(self.btn_back_small)
        nav.addWidget(self.btn_back_fine)
        nav.addWidget(self.btn_play_pause)
        nav.addWidget(self.btn_fwd_fine)
        nav.addWidget(self.btn_fwd_small)
        nav.addWidget(self.btn_fwd_big)
        nav.addSpacing(8)
        nav.addWidget(self.lbl_volume)
        nav.addWidget(self.sld_volume)
        nav.addSpacing(8)
        nav.addWidget(self.sld_pos, 1)

        root.addLayout(nav)

        # --- taglio IN / OUT ---
        gb_cut = QtWidgets.QGroupBox(LT("Taglio"), self)
        vl_cut = QtWidgets.QVBoxLayout(gb_cut)
        vl_cut.setContentsMargins(8, 8, 8, 8)
        vl_cut.setSpacing(6)

        row_marks = QtWidgets.QHBoxLayout()
        row_marks.setSpacing(8)

        self.ed_in = QtWidgets.QTimeEdit(self)
        self.ed_in.setDisplayFormat("HH:mm:ss.zzz")
        self.ed_in.setTime(QtCore.QTime(0, 0, 0, 0))
        self.ed_in.setWrapping(True)
        self.ed_in.setMinimumWidth(140)

        self.ed_out = QtWidgets.QTimeEdit(self)
        self.ed_out.setDisplayFormat("HH:mm:ss.zzz")
        self.ed_out.setTime(QtCore.QTime(0, 0, 0, 0))
        self.ed_out.setWrapping(True)
        self.ed_out.setMinimumWidth(140)

        self.btn_goto.setMinimumWidth(58)
        self.btn_goto.setMaximumWidth(58)

        row_marks.addWidget(self.btn_goto)
        row_marks.addWidget(self.ed_goto)
        row_marks.addSpacing(16)

        row_marks.addWidget(QtWidgets.QLabel("IN", self))
        row_marks.addWidget(self.ed_in)
        row_marks.addSpacing(14)
        row_marks.addWidget(QtWidgets.QLabel("OUT", self))
        row_marks.addWidget(self.ed_out)
        row_marks.addStretch(1)

        self.btn_mark_in = QtWidgets.QPushButton(LT("Segna IN"), self)
        self.btn_mark_out = QtWidgets.QPushButton(LT("Segna OUT"), self)
        self.btn_set_in_from_current = QtWidgets.QPushButton(LT("Usa posizione corrente → IN"), self)
        self.btn_set_out_from_current = QtWidgets.QPushButton(LT("Usa posizione corrente → OUT"), self)
        self.btn_swap_marks = QtWidgets.QPushButton(LT("Scambia IN/OUT"), self)
        self.btn_clear_marks = QtWidgets.QPushButton(LT("Azzera"), self)

        row_btns = QtWidgets.QHBoxLayout()
        row_btns.setSpacing(6)
        row_btns.addWidget(self.btn_mark_in)
        row_btns.addWidget(self.btn_mark_out)
        row_btns.addWidget(self.btn_set_in_from_current)
        row_btns.addWidget(self.btn_set_out_from_current)
        row_btns.addWidget(self.btn_swap_marks)
        row_btns.addWidget(self.btn_clear_marks)
        row_btns.addStretch(1)

        vl_cut.addLayout(row_marks)
        vl_cut.addLayout(row_btns)

        root.addWidget(gb_cut)

        # --- configurazione taglio (orizzontale) ---
        gb_cfg = QtWidgets.QGroupBox(LT("Taglio e modalità"), self)
        hl_cfg = QtWidgets.QHBoxLayout(gb_cfg)
        hl_cfg.setContentsMargins(8, 8, 8, 8)
        hl_cfg.setSpacing(14)

        w_mode = QtWidgets.QWidget(self)
        vl_mode = QtWidgets.QVBoxLayout(w_mode)
        vl_mode.setContentsMargins(0, 0, 0, 0)
        vl_mode.setSpacing(4)

        self.rb_fast_cut = QtWidgets.QRadioButton(LT("Taglio rapido (senza ricodifica)"), self)
        self.rb_precise_cut = QtWidgets.QRadioButton(LT("Taglio preciso (ricodifica assistita)"), self)
        self.lbl_mode_hint = QtWidgets.QLabel("", self)
        self.lbl_mode_hint.hide()

        vl_mode.addWidget(QtWidgets.QLabel("<b>" + LT("Modalità") + "</b>", self))
        vl_mode.addWidget(self.rb_fast_cut)
        vl_mode.addWidget(self.rb_precise_cut)
        vl_mode.addWidget(self.lbl_mode_hint, 1)

        w_op = QtWidgets.QWidget(self)
        vl_op = QtWidgets.QVBoxLayout(w_op)
        vl_op.setContentsMargins(0, 0, 0, 0)
        vl_op.setSpacing(4)

        self.rb_keep_segment = QtWidgets.QRadioButton(LT("Tieni solo il tratto IN → OUT"), self)
        self.rb_remove_segment = QtWidgets.QRadioButton(LT("Rimuovi il tratto IN → OUT"), self)

        vl_op.addWidget(QtWidgets.QLabel("<b>" + LT("Operazione") + "</b>", self))
        vl_op.addWidget(self.rb_keep_segment)
        vl_op.addWidget(self.rb_remove_segment)
        vl_op.addStretch(1)

        hl_cfg.addWidget(w_mode, 1)
        hl_cfg.addWidget(w_op, 1)

        root.addWidget(gb_cfg)

        # --- output ---
        gb_out = QtWidgets.QGroupBox(LT("Output"), self)
        gl_out = QtWidgets.QGridLayout(gb_out)
        gl_out.setContentsMargins(8, 6, 8, 6)
        gl_out.setHorizontalSpacing(6)
        gl_out.setVerticalSpacing(4)

        self.ed_output_name = QtWidgets.QLineEdit(self)
        self.ed_output_dir = QtWidgets.QLineEdit(self)
        self.ed_output_dir.setClearButtonEnabled(True)
        self.ed_output_dir.setReadOnly(False)
        self.btn_choose_output_dir = QtWidgets.QToolButton(self)
        self.btn_choose_output_dir.setText("…")
        self.btn_open_output_dir = QtWidgets.QToolButton(self)
        self.btn_open_output_dir.setText(LT("Apri"))

        gl_out.addWidget(QtWidgets.QLabel(LT("Nome file")), 0, 0)
        gl_out.addWidget(self.ed_output_name, 0, 1, 1, 3)

        gl_out.addWidget(QtWidgets.QLabel(LT("Cartella output")), 1, 0)
        gl_out.addWidget(self.ed_output_dir, 1, 1)
        gl_out.addWidget(self.btn_choose_output_dir, 1, 2)
        gl_out.addWidget(self.btn_open_output_dir, 1, 3)


        root.addWidget(gb_out)
        # --- tagli multipli ---
        row_multi_open = QtWidgets.QHBoxLayout()
        self.lbl_multi_cuts_status = QtWidgets.QLabel(LT("Nessun taglio aggiunto"), self)
        self.btn_open_multi_cuts = QtWidgets.QPushButton(LT("Tagli multipli…"), self)
        row_multi_open.addWidget(self.lbl_multi_cuts_status)
        row_multi_open.addStretch(1)
        row_multi_open.addWidget(self.btn_open_multi_cuts)
        root.addLayout(row_multi_open)

        # storage nascosto per i tagli multipli (usato dal popup)
        self.lbl_multi_info = QtWidgets.QLabel(LT("Aggiungi qui i pezzi da togliere dal video."), self)

        self.tbl_multi_cuts = QtWidgets.QTableWidget(0, 3, self)
        self.tbl_multi_cuts.setHorizontalHeaderLabels([LT("Da"), LT("A"), LT("Durata")])
        self.tbl_multi_cuts.verticalHeader().setVisible(False)
        self.tbl_multi_cuts.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.tbl_multi_cuts.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.tbl_multi_cuts.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.tbl_multi_cuts.setAlternatingRowColors(True)
        self.tbl_multi_cuts.setMinimumHeight(120)
        hdr_multi = self.tbl_multi_cuts.horizontalHeader()
        hdr_multi.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        hdr_multi.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        hdr_multi.setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)

        self.btn_add_cut_item = QtWidgets.QPushButton(LT("Aggiungi taglio"), self)
        self.btn_update_cut_item = QtWidgets.QPushButton(LT("Modifica taglio"), self)
        self.btn_delete_cut_item = QtWidgets.QPushButton(LT("Elimina taglio"), self)
        self.btn_clear_cut_items = QtWidgets.QPushButton(LT("Svuota elenco"), self)
        self.btn_preview_selected_cut = QtWidgets.QPushButton(LT("Anteprima taglio"), self)

        for _w in (
            self.lbl_multi_info,
            self.tbl_multi_cuts,
            self.btn_add_cut_item,
            self.btn_update_cut_item,
            self.btn_delete_cut_item,
            self.btn_clear_cut_items,
            self.btn_preview_selected_cut,
        ):
            _w.hide()
            _w.setVisible(False)

        # --- pulsanti finali + progress ---
        row = QtWidgets.QHBoxLayout()

        self.progress_cut = QtWidgets.QProgressBar(self)
        self.progress_cut.setMinimumWidth(260)
        self.progress_cut.setMinimumHeight(18)
        self.progress_cut.setMaximumHeight(18)
        self.progress_cut.setTextVisible(True)
        self.progress_cut.setAlignment(QtCore.Qt.AlignCenter)
        self.progress_cut.setRange(0, 100)
        self.progress_cut.setValue(0)
        self.progress_cut.setFormat("0%")

        self.btn_preview_cut = QtWidgets.QPushButton(LT("Preview selezione"), self)
        self.btn_preview_result = QtWidgets.QPushButton(LT("Preview risultato"), self)
        self.btn_create_cut = QtWidgets.QPushButton(LT("Crea file tagliato"), self)
        self.btn_close = QtWidgets.QPushButton(LT("Chiudi"), self)

        # pulsanti più compatti / coerenti
        for _b in (
            self.btn_back_big,
            self.btn_back_small,
            self.btn_back_fine,
            self.btn_play_pause,
            self.btn_fwd_fine,
            self.btn_fwd_small,
            self.btn_fwd_big,
            self.btn_goto,
            self.btn_mark_in,
            self.btn_mark_out,
            self.btn_set_in_from_current,
            self.btn_set_out_from_current,
            self.btn_swap_marks,
            self.btn_clear_marks,
            self.btn_preview_cut,
            self.btn_preview_result,
            self.btn_create_cut,
            self.btn_close,
        ):
            _b.setMinimumHeight(22)
            _b.setMaximumHeight(22)

        for _b in (
            self.btn_back_big,
            self.btn_back_small,
            self.btn_fwd_small,
            self.btn_fwd_big,
        ):
            _b.setMinimumWidth(30)
            _b.setMaximumWidth(30)

        self.btn_back_fine.setMinimumWidth(46)
        self.btn_back_fine.setMaximumWidth(46)
        self.btn_fwd_fine.setMinimumWidth(46)
        self.btn_fwd_fine.setMaximumWidth(46)

        self.btn_play_pause.setMinimumWidth(52)
        self.btn_play_pause.setMaximumWidth(52)
        self.btn_goto.setMinimumWidth(52)
        self.btn_goto.setMaximumWidth(52)
        self.lbl_volume.setMinimumWidth(24)
        self.lbl_volume.setMaximumWidth(24)
        self.sld_volume.setMinimumWidth(80)
        self.sld_volume.setMaximumWidth(110)

        self.btn_info.setFixedSize(22, 22)
        self.btn_help.setFixedSize(22, 22)
        self._apply_header_button_icons()
        self.btn_choose_output_dir.setFixedSize(22, 22)
        self.btn_open_output_dir.setMinimumHeight(22)
        self.btn_open_output_dir.setMaximumHeight(22)

        row.addWidget(self.progress_cut, 1)
        row.addSpacing(8)
        row.addWidget(self.btn_preview_cut)
        row.addWidget(self.btn_preview_result)
        row.addWidget(self.btn_create_cut)
        row.addWidget(self.btn_close)

        root.addLayout(row)

    def _apply_header_button_icons(self) -> None:
        st = None
        try:
            st = self.style()
        except Exception:
            st = None

        try:
            if st is not None:
                self.btn_info.setIcon(st.standardIcon(QtWidgets.QStyle.SP_MessageBoxInformation))
                self.btn_info.setText("")
                self.btn_info.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
            else:
                self.btn_info.setText("I")
            self.btn_info.setToolTip(LT("Informazioni sorgente"))
        except Exception:
            try:
                self.btn_info.setText("I")
            except Exception:
                pass

        try:
            if st is not None:
                self.btn_help.setIcon(st.standardIcon(QtWidgets.QStyle.SP_DialogHelpButton))
                self.btn_help.setText("")
                self.btn_help.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
            else:
                self.btn_help.setText("📖")
            self.btn_help.setToolTip(LT("Istruzioni / Manuale"))
        except Exception:
            try:
                self.btn_help.setText("📖")
            except Exception:
                pass

    def _project_icon(self, candidates, fallback=None):
        """
        Cerca prima le icone del progetto MKV Tools; se non le trova,
        usa il fallback Qt standard.
        """
        here = Path(__file__).resolve()

        search_dirs = [
            here.parent,
            here.parent / "icons",
            here.parent / "assets",
            here.parent / "assets" / "icons",
            here.parent.parent,
            here.parent.parent / "icons",
            here.parent.parent / "assets",
            here.parent.parent / "assets" / "icons",
            here.parent.parent.parent,
            here.parent.parent.parent / "icons",
            here.parent.parent.parent / "assets",
            here.parent.parent.parent / "assets" / "icons",
            here.parent.parent.parent / "resources",
            here.parent.parent.parent / "resources" / "icons",
            here.parent.parent.parent.parent,
            here.parent.parent.parent.parent / "icons",
            here.parent.parent.parent.parent / "assets",
            here.parent.parent.parent.parent / "assets" / "icons",
            here.parent.parent.parent.parent / "resources",
            here.parent.parent.parent.parent / "resources" / "icons",
        ]

        for base in search_dirs:
            try:
                if not base.exists():
                    continue
            except Exception:
                continue

            for name in candidates:
                p = base / name
                try:
                    if p.is_file():
                        return QtGui.QIcon(str(p))
                except Exception:
                    pass

        if fallback is not None:
            try:
                return self.style().standardIcon(fallback)
            except Exception:
                pass

        return QtGui.QIcon()

    def _apply_header_button_icons(self) -> None:
        info_icon = self._project_icon(
            [
                "ph_info.png",
                "ph_info.svg",
                "info.png",
                "info.svg",
            ],
            fallback=QtWidgets.QStyle.SP_MessageBoxInformation,
        )

        manual_icon = self._project_icon(
            [
                "ph_help.png",
                "ph_help.svg",
                "ph_user_manual.png",
                "ph_manual.png",
                "ph_book.png",
                "manual.png",
                "help.png",
                "book.png",
            ],
            fallback=QtWidgets.QStyle.SP_DialogHelpButton,
        )

        try:
            self.btn_info.setIcon(info_icon)
            self.btn_info.setText("")
            self.btn_info.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
            self.btn_info.setToolTip(LT("Informazioni sorgente"))
        except Exception:
            try:
                self.btn_info.setText("I")
            except Exception:
                pass

        try:
            self.btn_help.setIcon(manual_icon)
            self.btn_help.setText("")
            self.btn_help.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
            self.btn_help.setToolTip(LT("Istruzioni / Manuale"))
        except Exception:
            try:
                self.btn_help.setText("?")
            except Exception:
                pass

    def _wire_signals(self) -> None:
        self.btn_close.clicked.connect(self.reject)
        self.btn_help.clicked.connect(self._show_help)
        self.btn_info.clicked.connect(self._show_info)
        self.btn_choose_source.clicked.connect(self._choose_source_file)

        self.btn_back_big.clicked.connect(lambda: self._seek_relative(-1000))
        self.btn_back_small.clicked.connect(lambda: self._seek_relative(-100))
        self.btn_back_fine.clicked.connect(self._frame_back_step)
        self.btn_fwd_fine.clicked.connect(self._frame_forward_step)
        self.btn_fwd_small.clicked.connect(lambda: self._seek_relative(+100))
        self.btn_fwd_big.clicked.connect(lambda: self._seek_relative(+1000))

        self.btn_play_pause.clicked.connect(self._toggle_playback)
        self.btn_goto.clicked.connect(self._on_goto_clicked)
        self.sld_volume.valueChanged.connect(self._on_volume_changed)

        self.sld_pos.sliderPressed.connect(self._on_slider_pressed)
        self.sld_pos.valueChanged.connect(self._on_slider_value_changed_live)
        self.sld_pos.sliderReleased.connect(self._on_slider_released)

        self._poll_timer.timeout.connect(self._on_poll_timer)
        self._seek_timer.timeout.connect(self._flush_pending_seek)

        self.btn_mark_in.clicked.connect(self._mark_in)
        self.btn_mark_out.clicked.connect(self._mark_out)
        self.btn_set_in_from_current.clicked.connect(self._set_in_from_current)
        self.btn_set_out_from_current.clicked.connect(self._set_out_from_current)
        self.btn_swap_marks.clicked.connect(self._swap_marks)
        self.btn_clear_marks.clicked.connect(self._clear_marks)

        self.ed_in.timeChanged.connect(lambda _t: self._sync_marks_from_fields())
        self.ed_out.timeChanged.connect(lambda _t: self._sync_marks_from_fields())

        self.rb_fast_cut.toggled.connect(self._update_mode_hint)
        self.rb_precise_cut.toggled.connect(self._update_mode_hint)
        self.rb_keep_segment.toggled.connect(self._update_output_name)
        self.rb_remove_segment.toggled.connect(self._update_output_name)

        self.btn_choose_output_dir.clicked.connect(self._choose_output_dir)
        self.btn_open_output_dir.clicked.connect(self._open_output_dir)

        self.btn_add_cut_item.clicked.connect(self._add_current_cut_to_list)
        self.btn_update_cut_item.clicked.connect(self._update_selected_cut_in_list)
        self.btn_delete_cut_item.clicked.connect(self._delete_selected_cut_from_list)
        self.btn_clear_cut_items.clicked.connect(self._clear_cut_list)
        self.btn_preview_selected_cut.clicked.connect(self._preview_selected_cut)
        self.tbl_multi_cuts.itemSelectionChanged.connect(self._update_multi_cut_ui)
        self.btn_open_multi_cuts.clicked.connect(self._open_multi_cuts_dialog)

        self.btn_preview_cut.clicked.connect(self._preview_cut)
        self.btn_preview_result.clicked.connect(self._preview_result)
        self.btn_create_cut.clicked.connect(self._create_cut)

    # ------------------------------------------------------------
    # player / lifecycle
    # ------------------------------------------------------------
    def showEvent(self, event) -> None:
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
        self._init_player_if_needed()

    def closeEvent(self, event) -> None:
        try:
            if not self.isMaximized() and not self.isMinimized():
                self._settings.setValue("window_width", int(self.width()))
                self._settings.setValue("window_height", int(self.height()))
        except Exception:
            pass
        try:
            self._stop_playback()
        except Exception:
            pass
        try:
            self._poll_timer.stop()
            self._seek_timer.stop()
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

    def _init_player_if_needed(self) -> None:
        if self._player_inited:
            return
        if self._source_path is None or not Path(self._source_path).is_file():
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
            self._player.volume = int(self._volume_value)
        except Exception:
            pass

        self._player.command("loadfile", str(self._source_path), "replace")
        self._poll_timer.start()

        QtCore.QTimer.singleShot(150, lambda: self._seek_to_ms(0, exact=True))

    def _load_source_info(self) -> None:
        if self._source_path is None or not Path(self._source_path).is_file():
            self.ed_source.clear()
            self._duration_ms = 0
            self.lbl_duration.setText(self._format_ms(0))
            self.sld_pos.setMaximum(0)
            try:
                self.ed_output_dir.clear()
                self.ed_output_dir.setPlaceholderText("")
            except Exception:
                self.ed_output_dir.setText("")
            self.ed_output_name.clear()
            return

        self.ed_source.setText(str(self._source_path))
        self._duration_ms = self._probe_duration_ms(self._source_path)
        self.lbl_duration.setText(self._format_ms(self._duration_ms))
        self.sld_pos.setMaximum(max(0, self._duration_ms))

        self.ed_output_dir.clear()
        self.ed_output_name.setText(self._default_output_name())


    def _source_parent_dir(self) -> Path:
        if self._source_path is not None:
            try:
                return Path(self._source_path).expanduser().resolve().parent
            except Exception:
                pass
        return Path.home()

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
        self._keyframes_ms_cache = None
        self._last_created_cut_path = None
        self._multi_cut_last_preview_row = -1

        try:
            self.tbl_multi_cuts.setRowCount(0)
        except Exception:
            pass

        self._load_source_info()
        self._clear_marks()
        self._set_current_ms(0, sync_slider=True)
        self._sync_mark_fields_to_state()
        self._update_enabled()
        self._update_position_label()

        if self._player is None:
            self._player_inited = False
            self._init_player_if_needed()
        else:
            try:
                self._stop_playback()
            except Exception:
                pass
            try:
                self._clear_preview_mode()
            except Exception:
                pass
            try:
                self._player.command("loadfile", str(p), "replace")
            except Exception:
                pass
            self._poll_timer.start()
            QtCore.QTimer.singleShot(150, lambda: self._seek_to_ms(0, exact=True))

    def _refresh_progress_bar_visual(self, value: int | None = None, *, busy: bool = False) -> None:
        try:
            self.progress_cut.setTextVisible(True)
            self.progress_cut.setAlignment(QtCore.Qt.AlignCenter)

            if busy:
                self.progress_cut.setStyleSheet("")
                return

            v = max(0, min(100, int(value or 0)))
            if v <= 0:
                self.progress_cut.setStyleSheet(
                    "QProgressBar::chunk { background: transparent; width: 0px; margin: 0px; border: none; }"
                )
            else:
                self.progress_cut.setStyleSheet("")
        except Exception:
            pass

    def _set_progress_idle(self) -> None:
        try:
            self.progress_cut.setRange(0, 100)
            self.progress_cut.setValue(0)
            self.progress_cut.setFormat("0%")
            self._refresh_progress_bar_visual(0, busy=False)
        except Exception:
            pass

    def _set_progress_busy_indeterminate(self, text: str) -> None:
        try:
            self.progress_cut.setRange(0, 0)
            self.progress_cut.setFormat(text)
            self._refresh_progress_bar_visual(None, busy=True)
        except Exception:
            pass

    def _set_progress_value(self, value: int, text: str | None = None) -> None:
        try:
            v = max(0, min(100, int(value)))
            self.progress_cut.setRange(0, 100)
            self.progress_cut.setValue(v)
            self.progress_cut.setFormat(f"{v}%")
            self._refresh_progress_bar_visual(v, busy=False)
        except Exception:
            pass

    def _apply_initial_state(self) -> None:
        self.rb_fast_cut.setChecked(True)
        self.rb_keep_segment.setChecked(True)
        self._update_mode_hint()
        self.ed_goto.setText("00:00:00.000")
        self._set_current_ms(0, sync_slider=True)
        self._sync_mark_fields_to_state()
        self._set_progress_idle()
        self._update_enabled()
        self._update_position_label()

    def _update_enabled(self) -> None:
        source_ok = (self._source_path is not None) and Path(self._source_path).is_file() and self._duration_ms > 0
        nav_ok = source_ok and not self._busy

        try:
            in_ms_ui = self._qtime_to_ms(self.ed_in.time())
            out_ms_ui = self._qtime_to_ms(self.ed_out.time())
        except Exception:
            in_ms_ui = int(self._in_ms or 0)
            out_ms_ui = int(self._out_ms or 0)

        marks_touched = (in_ms_ui != 0 or out_ms_ui != 0)

        for w in (
            self.btn_back_big,
            self.btn_back_small,
            self.btn_back_fine,
            self.btn_play_pause,
            self.btn_fwd_fine,
            self.btn_fwd_small,
            self.btn_fwd_big,
            self.sld_volume,
            self.sld_pos,
            self.ed_goto,
            self.btn_goto,
            self.ed_in,
            self.ed_out,
            self.btn_mark_in,
            self.btn_mark_out,
            self.btn_set_in_from_current,
            self.btn_set_out_from_current,
            self.btn_swap_marks,
            self.btn_clear_marks,
        ):
            try:
                w.setEnabled(nav_ok)
            except Exception:
                pass

        out_dir_ok = bool(self.ed_output_dir.text().strip()) and Path(self.ed_output_dir.text().strip()).exists()
        self.btn_open_output_dir.setEnabled(out_dir_ok)
        self.btn_choose_source.setEnabled(not self._busy)
        self.btn_info.setEnabled(source_ok)

        self.btn_preview_cut.setEnabled(source_ok and marks_touched and not self._busy)
        self.btn_preview_result.setEnabled(source_ok and marks_touched and not self._busy)
        self.btn_create_cut.setEnabled(source_ok and marks_touched and not self._busy)

    def _ms_to_qtime(self, ms: int) -> QtCore.QTime:
        ms = max(0, int(ms))
        h = ms // 3600000
        ms -= h * 3600000
        m = ms // 60000
        ms -= m * 60000
        s = ms // 1000
        ms -= s * 1000
        h = min(h, 23)
        return QtCore.QTime(h, m, s, ms)

    def _qtime_to_ms(self, t: QtCore.QTime) -> int:
        if not t.isValid():
            return 0
        return (((t.hour() * 60) + t.minute()) * 60 + t.second()) * 1000 + t.msec()

    def _format_ms(self, ms: int) -> str:
        ms = max(0, int(ms))
        h = ms // 3600000
        ms -= h * 3600000
        m = ms // 60000
        ms -= m * 60000
        s = ms // 1000
        ms -= s * 1000
        return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"

    def _parse_time_to_ms(self, text: str) -> Optional[int]:
        t = (text or "").strip()
        if not t:
            return None
        try:
            if "." in t:
                main, frac = t.split(".", 1)
                frac = (frac + "000")[:3]
            else:
                main, frac = t, "000"

            parts = main.split(":")
            if len(parts) != 3:
                return None
            hh, mm, ss = [int(x) for x in parts]
            ms = int(frac)
            total = ((hh * 3600) + (mm * 60) + ss) * 1000 + ms
            return max(0, total)
        except Exception:
            return None

    def _update_position_label(self) -> None:
        total = self._format_ms(self._duration_ms)
        cur = self._format_ms(self._current_ms)
        self.lbl_pos.setText(f"{cur} / {total}")

    def _probe_duration_ms(self, path: Path) -> int:
        if not path.is_file():
            return 0
        try:
            out = subprocess.check_output(
                [
                    "ffprobe",
                    "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(path),
                ],
                text=True,
            ).strip()
            sec = float(out or "0")
            return max(0, int(sec * 1000))
        except Exception:
            return 0

    # ------------------------------------------------------------
    # player control / polling
    # ------------------------------------------------------------
    def _clear_preview_mode(self) -> None:
        self._preview_out_stop_ms = None
        self._preview_skip_from_ms = None
        self._preview_skip_to_ms = None

    def _load_media_for_preview(self, path: Path, *, autoplay: bool = True) -> None:
        target = Path(path).expanduser().resolve()
        if not target.is_file():
            raise RuntimeError(LT("File di preview non trovato.") + "\n" + str(target))

        self._init_player_if_needed()
        if self._player is None:
            raise RuntimeError(LT("Player non disponibile."))

        self._stop_playback()
        self._clear_preview_mode()

        self._player_command("loadfile", str(target), "replace")
        self._player_loaded_path = target

        self._duration_ms = self._probe_duration_ms(target)
        self.sld_pos.setMaximum(max(0, self._duration_ms))
        self.lbl_duration.setText(self._format_ms(self._duration_ms))
        self._set_current_ms(0, sync_slider=True)
        self.ed_source.setText(str(target))

        QtCore.QTimer.singleShot(180, lambda: self._seek_to_ms(0, exact=True))
        if autoplay:
            QtCore.QTimer.singleShot(260, self._start_playback)

    def _restore_source_preview(self) -> None:
        if self._source_path is None or not Path(self._source_path).is_file():
            return

        target = Path(self._source_path).expanduser().resolve()
        self._duration_ms = self._probe_duration_ms(target)
        self.sld_pos.setMaximum(max(0, self._duration_ms))
        self.lbl_duration.setText(self._format_ms(self._duration_ms))
        self.ed_source.setText(str(target))

        if getattr(self, "_player_loaded_path", None) != target:
            self._load_media_for_preview(target, autoplay=False)

    def _load_keyframes_ms(self) -> list[int]:
        if self._keyframes_ms_cache is not None:
            return self._keyframes_ms_cache
        if self._source_path is None or not Path(self._source_path).is_file():
            self._keyframes_ms_cache = [0]
            return self._keyframes_ms_cache

        out: list[int] = [0]
        try:
            cp = subprocess.run(
                [
                    "ffprobe",
                    "-v", "error",
                    "-select_streams", "v:0",
                    "-skip_frame", "nokey",
                    "-show_entries", "frame=best_effort_timestamp_time",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(self._source_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            for raw in (cp.stdout or "").splitlines():
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    ms = max(0, int(float(raw) * 1000.0))
                    out.append(ms)
                except Exception:
                    pass
        except Exception:
            pass

        out = sorted(set(out))
        if not out:
            out = [0]
        self._keyframes_ms_cache = out
        return out

    def _prev_keyframe_ms(self, target_ms: int) -> int:
        target_ms = max(0, int(target_ms))
        kfs = self._load_keyframes_ms()
        prev = 0
        for k in kfs:
            if k > target_ms:
                break
            prev = k
        return prev

    def _next_keyframe_ms(self, target_ms: int) -> int:
        target_ms = max(0, int(target_ms))
        kfs = self._load_keyframes_ms()
        for k in kfs:
            if k >= target_ms:
                return k
        return max(0, self._duration_ms)

    def _rapid_real_points(self) -> tuple[int, int]:
        in_ms = int(self._in_ms or 0)
        out_ms = int(self._out_ms or 0)

        # Taglio rapido: aggancio "onesto" ai keyframe precedenti.
        # È il caso più conservativo e vicino al comportamento reale di stream copy.
        real_in = self._prev_keyframe_ms(in_ms)
        real_out = self._prev_keyframe_ms(out_ms)

        real_in = max(0, min(real_in, self._duration_ms))
        real_out = max(0, min(real_out, self._duration_ms))

        return real_in, real_out

    def _format_delta_ms(self, a: int, b: int) -> str:
        d = int(b) - int(a)
        sign = "+" if d >= 0 else "-"
        d = abs(d)
        if d >= 1000:
            return f"{sign}{d/1000.0:.3f}s"
        return f"{sign}{d}ms"

    def _rapid_shift_summary(self) -> tuple[str, int]:
        real_in, real_out = self._rapid_real_points()
        user_in = int(self._in_ms or 0)
        user_out = int(self._out_ms or 0)

        msg = (
            LT("Taglio rapido userà punti reali agganciati ai keyframe.") + "\n\n" +
            "IN  " + self._format_ms(user_in) + "  →  " + self._format_ms(real_in) +
            "  (" + self._format_delta_ms(user_in, real_in) + ")" + "\n" +
            "OUT " + self._format_ms(user_out) + "  →  " + self._format_ms(real_out) +
            "  (" + self._format_delta_ms(user_out, real_out) + ")"
        )
        max_shift = max(abs(real_in - user_in), abs(real_out - user_out))
        return msg, max_shift

    def _player_command(self, *args) -> None:
        if self._player is None:
            return
        try:
            self._player.command(*args)
        except Exception:
            pass

    def _set_current_ms(self, ms: int, *, sync_slider: bool) -> None:
        self._current_ms = max(0, min(int(ms), self._duration_ms if self._duration_ms > 0 else int(ms)))
        if sync_slider:
            self.sld_pos.blockSignals(True)
            self.sld_pos.setValue(self._current_ms)
            self.sld_pos.blockSignals(False)
        self._update_position_label()

    def _seek_to_ms(self, ms: int, *, exact: bool = True) -> None:
        self._set_current_ms(ms, sync_slider=True)
        if self._player is None:
            return
        mode = "absolute+exact" if exact else "absolute"
        self._player_command("seek", f"{self._current_ms / 1000.0:.3f}", mode)

    def _seek_relative(self, delta_ms: int) -> None:
        self._clear_preview_mode()
        self._seek_to_ms(self._current_ms + int(delta_ms), exact=True)

    def _start_playback(self) -> None:
        if self._player is None or self._duration_ms <= 0:
            return
        if self._current_ms >= self._duration_ms:
            self._seek_to_ms(0, exact=True)
        try:
            self._player.pause = False
        except Exception:
            self._player_command("set", "pause", "no")
        self.btn_play_pause.setText(LT("Pausa"))

    def _stop_playback(self) -> None:
        self._clear_preview_mode()
        if self._player is None:
            self.btn_play_pause.setText(LT("Play"))
            return
        try:
            self._player.pause = True
        except Exception:
            self._player_command("set", "pause", "yes")
        self.btn_play_pause.setText(LT("Play"))

    def _toggle_playback(self) -> None:
        if self._player is None:
            return
        paused = True
        try:
            paused = bool(self._player.pause)
        except Exception:
            pass
        if paused:
            self._start_playback()
        else:
            self._stop_playback()

    def _on_volume_changed(self, value: int) -> None:
        self._volume_value = max(0, min(100, int(value)))
        if self._player is not None:
            try:
                self._player.volume = int(self._volume_value)
            except Exception:
                pass

    def _frame_back_step(self) -> None:
        if self._player is None:
            return
        self._stop_playback()
        try:
            self._player.command("frame-back-step")
        except Exception:
            # fallback se il backend non supporta bene il comando
            self._seek_to_ms(self._current_ms - 40, exact=True)

    def _frame_forward_step(self) -> None:
        if self._player is None:
            return
        self._stop_playback()
        try:
            self._player.command("frame-step")
        except Exception:
            self._seek_to_ms(self._current_ms + 40, exact=True)

    def _on_poll_timer(self) -> None:
        if self._player is None:
            return

        try:
            dur = getattr(self._player, "duration", None)
            if dur:
                dur_ms = max(0, int(float(dur) * 1000))
                if dur_ms > 0 and dur_ms != self._duration_ms:
                    self._duration_ms = dur_ms
                    self.sld_pos.setMaximum(dur_ms)
                    self.lbl_duration.setText(self._format_ms(dur_ms))
        except Exception:
            pass

        try:
            pos = getattr(self._player, "time_pos", None)
            if pos is not None and not self._slider_dragging:
                self._set_current_ms(int(float(pos) * 1000), sync_slider=True)
        except Exception:
            pass

        try:
            paused = bool(getattr(self._player, "pause", True))
            self.btn_play_pause.setText(LT("Play") if paused else LT("Pausa"))
        except Exception:
            pass

        if (
            self._preview_skip_from_ms is not None
            and self._preview_skip_to_ms is not None
            and self._current_ms >= self._preview_skip_from_ms
            and self._current_ms < self._preview_skip_to_ms
        ):
            to_ms = int(self._preview_skip_to_ms)
            self._preview_skip_from_ms = None
            self._preview_skip_to_ms = None
            self._seek_to_ms(to_ms, exact=True)
            return

        if self._preview_out_stop_ms is not None and self._current_ms >= self._preview_out_stop_ms:
            self._stop_playback()
            self._preview_out_stop_ms = None

    # ------------------------------------------------------------
    # slider / goto
    # ------------------------------------------------------------
    def _on_slider_pressed(self) -> None:
        self._slider_dragging = True
        self._clear_preview_mode()

    def _on_slider_value_changed_live(self, value: int) -> None:
        self._set_current_ms(int(value), sync_slider=False)
        self._pending_seek_ms = int(value)
        self._seek_timer.start()

    def _flush_pending_seek(self) -> None:
        if self._pending_seek_ms is None:
            return
        ms = int(self._pending_seek_ms)
        self._pending_seek_ms = None
        self._seek_to_ms(ms, exact=True)

    def _on_slider_released(self) -> None:
        self._slider_dragging = False
        self._seek_timer.stop()
        self._pending_seek_ms = None
        self._seek_to_ms(self.sld_pos.value(), exact=True)

    def _on_goto_clicked(self) -> None:
        ms = self._parse_time_to_ms(self.ed_goto.text())
        if ms is None:
            QtWidgets.QMessageBox.warning(self, LT("Errore"), LT("Tempo non valido. Usa hh:mm:ss.mmm"))
            return
        self._clear_preview_mode()
        self._seek_to_ms(ms, exact=True)

    # ------------------------------------------------------------
    # markers
    # ------------------------------------------------------------
    def _mark_in(self) -> None:
        self._in_ms = self._current_ms
        self._sync_mark_fields_to_state()
        self._update_enabled()

    def _mark_out(self) -> None:
        self._out_ms = self._current_ms
        self._sync_mark_fields_to_state()
        self._update_enabled()

    def _set_in_from_current(self) -> None:
        self._mark_in()

    def _set_out_from_current(self) -> None:
        self._mark_out()

    def _swap_marks(self) -> None:
        self._in_ms, self._out_ms = self._out_ms, self._in_ms
        self._sync_mark_fields_to_state()
        self._update_enabled()

    def _clear_marks(self) -> None:
        self._in_ms = 0
        self._out_ms = 0
        self._sync_mark_fields_to_state()
        self._update_enabled()

    def _sync_mark_fields_to_state(self) -> None:
        self.ed_in.blockSignals(True)
        self.ed_out.blockSignals(True)
        try:
            self.ed_in.setTime(self._ms_to_qtime(0 if self._in_ms is None else self._in_ms))
            self.ed_out.setTime(self._ms_to_qtime(0 if self._out_ms is None else self._out_ms))
        finally:
            self.ed_in.blockSignals(False)
            self.ed_out.blockSignals(False)

    def _sync_marks_from_fields(self) -> None:
        self._in_ms = self._qtime_to_ms(self.ed_in.time())
        self._out_ms = self._qtime_to_ms(self.ed_out.time())
        self._update_enabled()

    def _validate_marks(self) -> tuple[bool, str]:
        if self._in_ms is None or self._out_ms is None:
            return False, LT("Imposta prima IN e OUT.")
        if self._out_ms <= self._in_ms:
            return False, LT("OUT deve essere maggiore di IN.")
        if self._out_ms > self._duration_ms:
            return False, LT("OUT supera la durata del file.")
        return True, ""

    # ------------------------------------------------------------
    # mode / output
    # ------------------------------------------------------------
    def _update_mode_hint(self) -> None:
        fast_tt = LT(
            "Taglio rapido:\n"
            "• più veloce\n"
            "• senza perdita\n"
            "• il punto finale può non essere preciso al fotogramma"
        )
        precise_tt = LT(
            "Taglio preciso:\n"
            "• più lento\n"
            "• richiede ricodifica assistita\n"
            "• rispetta meglio i punti scelti"
        )
        self.rb_fast_cut.setToolTip(fast_tt)
        self.rb_precise_cut.setToolTip(precise_tt)
        self.lbl_mode_hint.hide()

    def _guess_output_dir(self) -> Path:
        try:
            p = self.parent()
            out_dir = getattr(p, "_out_dir", None)
            if out_dir:
                out_path = Path(out_dir).expanduser()
                if out_path.exists():
                    return out_path
        except Exception:
            pass
        return self._source_path.parent

    def _default_output_name(self) -> str:
        stem = self._source_path.stem if self._source_path is not None else "cut_output"
        if self.rb_remove_segment.isChecked():
            return f"{stem}_cut_remove.mkv"
        return f"{stem}_cut_keep.mkv"

    def _update_output_name(self) -> None:
        self.ed_output_name.setText(self._default_output_name())

    def _choose_output_dir(self) -> None:
        start = self.ed_output_dir.text().strip() or str(self._source_parent_dir())
        d = QtWidgets.QFileDialog.getExistingDirectory(self, LT("Scegli cartella output"), start)
        if d:
            self.ed_output_dir.setText(d)
        self._update_enabled()

    def _open_output_dir(self) -> None:
        raw = self.ed_output_dir.text().strip()
        if not raw:
            QtWidgets.QMessageBox.warning(self, LT("Errore"), LT("Seleziona prima una cartella output."))
            return

        path = Path(raw).expanduser().resolve()
        if not path.exists() or not path.is_dir():
            QtWidgets.QMessageBox.warning(self, LT("Errore"), LT("Seleziona prima una cartella output."))
            return

        try:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, LT("Errore"), str(e))
    def _set_busy(self, v: bool) -> None:
        self._busy = bool(v)
        self._update_enabled()
        try:
            QtWidgets.QApplication.processEvents()
        except Exception:
            pass

    def _output_path(self) -> Path:
        out_dir_txt = (self.ed_output_dir.text() or "").strip()
        if out_dir_txt:
            out_dir = Path(out_dir_txt).expanduser()
        else:
            out_dir = self._source_parent_dir()
        name = (self.ed_output_name.text() or "").strip() or self._default_output_name()
        if not Path(name).suffix:
            name += ".mkv"
        return out_dir / name

    def _temp_job_dir(self) -> Path:
        base = self._tmp_dir / "fast_cut_jobs"
        base.mkdir(parents=True, exist_ok=True)
        i = 1
        while True:
            d = base / f"job_{i:03d}"
            if not d.exists():
                d.mkdir(parents=True, exist_ok=True)
                return d
            i += 1

    def _cleanup_job_dir(self, d: Path) -> None:
        try:
            shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass

    def _ffmpeg_base_cmd(self) -> list[str]:
        return [
            "ffmpeg",
            "-y",
            "-nostdin",
            "-hide_banner",
            "-loglevel", "error",
        ]

    def _ffconcat_quote(self, p: Path) -> str:
        txt = str(p)
        return "file '" + txt.replace("'", "'\\''") + "'"

    def _run_cmd(self, cmd: list[str], *, label: str) -> None:
        self._set_progress_busy_indeterminate(label)
        try:
            QtWidgets.QApplication.processEvents()
        except Exception:
            pass
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(err or f"Command failed ({proc.returncode})")

    def _build_fast_keep_cmd(self, out_file: Path) -> list[str]:
        in_ms = int(self._in_ms or 0)
        out_ms = int(self._out_ms or 0)
        return self._ffmpeg_base_cmd() + [
            "-ss", self._format_ms(in_ms),
            "-to", self._format_ms(out_ms),
            "-i", str(self._source_path),
            "-map", "0",
            "-c", "copy",
            str(out_file),
        ]

    def _build_fast_segment_cmd(self, out_file: Path, start_ms: int, end_ms: int | None) -> list[str]:
        cmd = self._ffmpeg_base_cmd() + [
            "-ss", self._format_ms(start_ms),
        ]
        if end_ms is not None:
            cmd += ["-to", self._format_ms(end_ms)]
        cmd += [
            "-i", str(self._source_path),
            "-map", "0",
            "-c", "copy",
            str(out_file),
        ]
        return cmd

    def _do_fast_keep(self, out_path: Path) -> None:
        real_in, real_out = self._rapid_real_points()

        cmd = self._ffmpeg_base_cmd() + [
            "-ss", self._format_ms(real_in),
            "-to", self._format_ms(real_out),
            "-i", str(self._source_path),
            "-map", "0",
            "-c", "copy",
            str(out_path),
        ]
        self._run_cmd(cmd, label=LT("Taglio rapido in corso…"))

    def _do_fast_remove(self, out_path: Path) -> None:
        in_ms, out_ms = self._rapid_real_points()

        work = self._temp_job_dir()
        try:
            parts: list[Path] = []

            if in_ms > 0:
                part1 = work / "part1.mkv"
                cmd1 = self._build_fast_segment_cmd(part1, 0, in_ms)
                self._run_cmd(cmd1, label=LT("Taglio rapido parte 1…"))
                if part1.is_file():
                    parts.append(part1)

            if out_ms < self._duration_ms:
                part2 = work / "part2.mkv"
                cmd2 = self._build_fast_segment_cmd(part2, out_ms, None)
                self._run_cmd(cmd2, label=LT("Taglio rapido parte 2…"))
                if part2.is_file():
                    parts.append(part2)

            if not parts:
                raise RuntimeError(LT("Nessun segmento utile prodotto."))

            if len(parts) == 1:
                self._set_progress_busy_indeterminate(LT("Finalizzazione…"))
                if out_path.exists():
                    out_path.unlink()
                shutil.move(str(parts[0]), str(out_path))
                return

            concat_txt = work / "concat.txt"
            concat_txt.write_text(
                "\n".join(self._ffconcat_quote(x) for x in parts) + "\n",
                encoding="utf-8",
            )

            cmd_concat = self._ffmpeg_base_cmd() + [
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_txt),
                "-c", "copy",
                str(out_path),
            ]
            self._run_cmd(cmd_concat, label=LT("Unione segmenti…"))
        finally:
            self._cleanup_job_dir(work)

    def _run_fast_cut(self) -> Path:
        out_path = self._output_path()
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if self.rb_keep_segment.isChecked():
            self._do_fast_keep(out_path)
        else:
            self._do_fast_remove(out_path)

        return out_path


    def _show_text_dialog(self, title: str, text: str, width: int = 760, height: int = 560) -> None:
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(title)
        dlg.resize(width, height)

        lay = QtWidgets.QVBoxLayout(dlg)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        box = QtWidgets.QPlainTextEdit(dlg)
        box.setReadOnly(True)
        box.setPlainText(text)

        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        btn = QtWidgets.QPushButton(LT("Chiudi"), dlg)
        btn.clicked.connect(dlg.accept)
        row.addWidget(btn)

        lay.addWidget(box, 1)
        lay.addLayout(row)
        dlg.exec_()

    def _ffprobe_json(self, path: Path) -> dict:
        cp = subprocess.run(
            [
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if cp.returncode != 0:
            raise RuntimeError((cp.stderr or cp.stdout or "").strip() or "ffprobe failed")
        return json.loads(cp.stdout or "{}")

    def _source_info_text(self) -> str:
        if self._source_path is None:
            return LT("Nessun dato disponibile.")

        try:
            data = self._ffprobe_json(Path(self._source_path))
        except Exception as e:
            return f"{LT('Errore')}: {e}"

        fmt = data.get("format") or {}
        streams = data.get("streams") or []

        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        audios = [s for s in streams if s.get("codec_type") == "audio"]
        subs = [s for s in streams if s.get("codec_type") == "subtitle"]

        out = []
        out.append(f"{LT('Percorso')}: {self._source_path}")
        out.append(f"{LT('Contenitore')}: {fmt.get('format_long_name') or fmt.get('format_name') or '?'}")
        try:
            out.append(f"{LT('Dimensione')}: {_fmt_bytes(int(fmt.get('size') or 0))}")
        except Exception:
            out.append(f"{LT('Dimensione')}: ?")
        try:
            dur_ms = int(round(float(fmt.get('duration') or 0.0) * 1000.0))
            out.append(f"{LT('Durata')}: {self._format_ms(dur_ms)}")
        except Exception:
            out.append(f"{LT('Durata')}: ?")
        try:
            br = int(fmt.get('bit_rate') or 0)
            out.append(f"{LT('Bitrate')}: {br // 1000} kb/s" if br > 0 else f"{LT('Bitrate')}: ?")
        except Exception:
            out.append(f"{LT('Bitrate')}: ?")

        if video:
            out.append("")
            out.append(f"[{LT('Video')}]")
            out.append(f"Codec: {video.get('codec_name') or '?'}")
            out.append(f"{LT('Risoluzione')}: {video.get('width') or '?'}x{video.get('height') or '?'}")
            rate = video.get('avg_frame_rate') or video.get('r_frame_rate') or '?'
            out.append(f"{LT('Frame rate')}: {rate}")
            out.append(f"{LT('Formato pixel')}: {video.get('pix_fmt') or '?'}")
            out.append(f"{LT('SAR')}: {video.get('sample_aspect_ratio') or '?'}")
            out.append(f"{LT('DAR')}: {video.get('display_aspect_ratio') or '?'}")

        if audios:
            for idx, a in enumerate(audios, start=1):
                out.append("")
                out.append(f"[{LT('Audio')} #{idx}]")
                out.append(f"Codec: {a.get('codec_name') or '?'}")
                out.append(f"{LT('Canali')}: {a.get('channels') or '?'}")
                out.append(f"{LT('Sample rate')}: {a.get('sample_rate') or '?'}")
                tags = a.get('tags') or {}
                out.append(f"{LT('Lingua')}: {tags.get('language') or '?'}")
                out.append(f"{LT('Titolo traccia')}: {tags.get('title') or '?'}")

        if subs:
            for idx, s in enumerate(subs, start=1):
                out.append("")
                out.append(f"[{LT('Sottotitoli')} #{idx}]")
                out.append(f"Codec: {s.get('codec_name') or '?'}")
                tags = s.get('tags') or {}
                out.append(f"{LT('Lingua')}: {tags.get('language') or '?'}")
                out.append(f"{LT('Titolo traccia')}: {tags.get('title') or '?'}")

        return "\n".join(out) if out else LT("Nessun dato disponibile.")


    def _show_info(self) -> None:
        if self._source_path is None:
            QtWidgets.QMessageBox.information(self, LT("Info"), LT("Nessun file sorgente selezionato."))
            return
        self._show_text_dialog(LT("Informazioni file sorgente"), self._source_info_text(), 760, 560)
    def _show_help(self) -> None:
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(LT("Istruzioni taglio video"))
        dlg.resize(860, 620)

        lay = QtWidgets.QVBoxLayout(dlg)
        view = QtWidgets.QTextBrowser(dlg)
        view.setReadOnly(True)
        view.setOpenExternalLinks(False)
        view.setHtml(self._help_html())
        lay.addWidget(view, 1)

        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        btn = QtWidgets.QPushButton(LT("Chiudi"), dlg)
        btn.clicked.connect(dlg.accept)
        row.addWidget(btn)
        lay.addLayout(row)

        dlg.exec_()

    def _help_html(self) -> str:
        return (
            "<h2>" + LT("Istruzioni taglio video") + "</h2>"

            "<p>" + LT("Questa finestra serve per scegliere i punti del taglio direttamente dal player con audio.") + "</p>"

            "<h3>" + LT("Comandi principali") + "</h3>"
            "<ul>"
            "<li><b>&lt;&lt; / &gt;&gt;</b>: " + LT("spostamento di 1 secondo") + "</li>"
            "<li><b>&lt; / &gt;</b>: " + LT("spostamento di 100 ms") + "</li>"
            "<li><b>&lt;fine / fine&gt;</b>: " + LT("spostamento di 1 frame") + "</li>"
            "<li><b>" + LT("Play/Pausa") + "</b>: " + LT("riproduzione reale con audio") + "</li>"
            "<li><b>" + LT("Vai a") + "</b>: " + LT("salto diretto a un tempo preciso") + "</li>"
            "</ul>"

            "<h3>" + LT("Taglio singolo") + "</h3>"
            "<ol>"
            "<li>" + LT("vai al punto iniziale e imposta IN") + "</li>"
            "<li>" + LT("vai al punto finale e imposta OUT") + "</li>"
            "<li>" + LT("scegli se tenere solo quel tratto oppure rimuoverlo") + "</li>"
            "<li>" + LT("usa Preview selezione o Preview risultato per controllare") + "</li>"
            "<li>" + LT("premi Crea file tagliato") + "</li>"
            "</ol>"

            "<h3>" + LT("Modalità") + "</h3>"
            "<ul>"
            "<li><b>" + LT("Taglio rapido") + "</b>: " + LT("più veloce e senza ricodifica, ma può agganciarsi ai keyframe e non essere preciso al fotogramma") + "</li>"
            "<li><b>" + LT("Taglio preciso") + "</b>: " + LT("più lento, ma rispetta molto meglio i punti scelti e ricrea il file prendendo automaticamente i parametri utili dal sorgente") + "</li>"
            "</ul>"

            "<h3>" + LT("Tagli multipli") + "</h3>"
            "<p>" + LT("Se devi togliere più pezzi dallo stesso video, usa il pulsante Tagli multipli…") + "</p>"
            "<ol>"
            "<li>" + LT("imposta DA e A per il primo pezzo da togliere") + "</li>"
            "<li>" + LT("premi Aggiungi taglio") + "</li>"
            "<li>" + LT("ripeti per tutti gli altri pezzi") + "</li>"
            "<li>" + LT("chiudi pure la finestrella: i tagli restano salvati") + "</li>"
            "<li>" + LT("torna alla finestra principale e premi Crea file senza i tagli") + "</li>"
            "</ol>"

            "<h3>" + LT("Anteprime") + "</h3>"
            "<ul>"
            "<li><b>" + LT("Preview selezione") + "</b>: " + LT("riproduce il tratto scelto tra IN e OUT") + "</li>"
            "<li><b>" + LT("Preview risultato") + "</b>: " + LT("mostra il risultato finale; se il file è già stato creato, apre proprio quello") + "</li>"
            "</ul>"

            "<h3>" + LT("Suggerimenti") + "</h3>"
            "<ul>"
            "<li>" + LT("Per la massima precisione usa Taglio preciso") + "</li>"
            "<li>" + LT("Per togliere pubblicità o più spezzoni usa Tagli multipli") + "</li>"
            "<li>" + LT("Se il file esiste già, verrà chiesta conferma prima di sovrascriverlo") + "</li>"
            "</ul>"
        )

    def _preview_cut(self) -> None:
        self._restore_source_preview()
        ok, msg = self._validate_marks()
        if not ok:
            QtWidgets.QMessageBox.warning(self, LT("Errore"), msg)
            return
        self._preview_out_stop_ms = int(self._out_ms or 0)
        self._seek_to_ms(int(self._in_ms or 0), exact=True)
        QtCore.QTimer.singleShot(120, self._start_playback)


    def _preview_result(self) -> None:
        real_out = getattr(self, "_last_created_cut_path", None)
        if real_out is not None:
            try:
                real_out = Path(real_out)
            except Exception:
                real_out = None
        if real_out is not None and real_out.is_file():
            try:
                self._load_media_for_preview(real_out, autoplay=True)
                return
            except Exception as e:
                QtWidgets.QMessageBox.warning(
                    self,
                    LT("Info"),
                    LT("Preview del file creato non disponibile, uso la preview simulata.") + "\n" + str(e),
                )

        if self._has_multi_cuts():
            QtWidgets.QMessageBox.information(
                self,
                LT("Info"),
                LT("Per vedere il risultato completo con più tagli, crea prima il file."),
            )
            return

        self._restore_source_preview()
        ok, msg = self._validate_marks()
        if not ok:
            QtWidgets.QMessageBox.warning(self, LT("Errore"), msg)
            return

        if self.rb_fast_cut.isChecked():
            in_ms, out_ms = self._rapid_real_points()
        else:
            in_ms = int(self._in_ms or 0)
            out_ms = int(self._out_ms or 0)
        dur = int(self._duration_ms or 0)

        self._stop_playback()
        self._clear_preview_mode()

        if self.rb_keep_segment.isChecked():
            self._preview_cut()
            return

        if in_ms <= 0 and out_ms >= dur:
            QtWidgets.QMessageBox.information(
                self,
                LT("Info"),
                LT("Con questi punti non rimane nulla da riprodurre."),
            )
            return

        if in_ms <= 0:
            self._seek_to_ms(out_ms, exact=True)
            QtCore.QTimer.singleShot(120, self._start_playback)
            return

        if out_ms >= dur:
            self._preview_out_stop_ms = in_ms
            self._seek_to_ms(0, exact=True)
            QtCore.QTimer.singleShot(120, self._start_playback)
            return

        self._preview_skip_from_ms = in_ms
        self._preview_skip_to_ms = out_ms
        self._seek_to_ms(0, exact=True)
        QtCore.QTimer.singleShot(120, self._start_playback)

    def _find_and_hide_inline_multi_group(self) -> None:
        grp = getattr(self, "_multi_inline_group", None)

        if grp is None:
            for _w in self.findChildren(QtWidgets.QGroupBox):
                try:
                    title = (_w.title() or "").strip()
                except Exception:
                    title = ""
                if title in {LT("Tagli multipli"), "Tagli multipli"}:
                    grp = _w
                    self._multi_inline_group = grp
                    break

        if grp is not None:
            try:
                grp.hide()
            except Exception:
                pass

    def _hide_inline_multi_widgets(self) -> None:
        names = [
            "lbl_multi_info",
            "tbl_multi_cuts",
            "btn_add_cut_item",
            "btn_update_cut_item",
            "btn_delete_cut_item",
            "btn_clear_cut_items",
            "btn_preview_selected_cut",
        ]
        for name in names:
            w = getattr(self, name, None)
            if w is not None:
                try:
                    w.hide()
                    w.setVisible(False)
                except Exception:
                    pass

        for gb in self.findChildren(QtWidgets.QGroupBox):
            try:
                title = (gb.title() or "").strip()
            except Exception:
                title = ""
            if title in {LT("Tagli multipli"), "Tagli multipli"}:
                try:
                    gb.hide()
                    gb.setVisible(False)
                    gb.setMaximumHeight(0)
                    gb.setMinimumHeight(0)
                except Exception:
                    pass
                break

    def _open_multi_cuts_dialog(self) -> None:
        dlg = getattr(self, "_multi_cuts_dialog", None)
        if dlg is None:
            dlg = MultiCutsDialog(self)
            self._multi_cuts_dialog = dlg

        try:
            dlg.sync_from_owner()
        except Exception:
            pass

        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _has_multi_cuts(self) -> bool:
        return bool(getattr(self, "tbl_multi_cuts", None) is not None and self.tbl_multi_cuts.rowCount() > 0)

    def _cut_list_row_values(self, row: int):
        if row < 0 or row >= self.tbl_multi_cuts.rowCount():
            return None
        item_a = self.tbl_multi_cuts.item(row, 0)
        item_b = self.tbl_multi_cuts.item(row, 1)
        if item_a is None or item_b is None:
            return None
        start_ms = item_a.data(QtCore.Qt.UserRole)
        end_ms = item_b.data(QtCore.Qt.UserRole)
        if start_ms is None or end_ms is None:
            return None
        return int(start_ms), int(end_ms)

    def _set_cut_table_row(self, row: int, start_ms: int, end_ms: int) -> None:
        dur_ms = max(0, int(end_ms) - int(start_ms))

        item_a = QtWidgets.QTableWidgetItem(self._format_ms(int(start_ms)))
        item_a.setData(QtCore.Qt.UserRole, int(start_ms))

        item_b = QtWidgets.QTableWidgetItem(self._format_ms(int(end_ms)))
        item_b.setData(QtCore.Qt.UserRole, int(end_ms))

        item_d = QtWidgets.QTableWidgetItem(self._format_ms(int(dur_ms)))
        item_d.setData(QtCore.Qt.UserRole, int(dur_ms))

        self.tbl_multi_cuts.setItem(row, 0, item_a)
        self.tbl_multi_cuts.setItem(row, 1, item_b)
        self.tbl_multi_cuts.setItem(row, 2, item_d)

    def _sort_cut_list_rows(self) -> None:
        rows = []
        for r in range(self.tbl_multi_cuts.rowCount()):
            vals = self._cut_list_row_values(r)
            if vals is not None:
                rows.append(vals)

        rows.sort(key=lambda x: (x[0], x[1]))

        self.tbl_multi_cuts.setRowCount(0)
        for start_ms, end_ms in rows:
            row = self.tbl_multi_cuts.rowCount()
            self.tbl_multi_cuts.insertRow(row)
            self._set_cut_table_row(row, start_ms, end_ms)

    def _multi_cut_ranges_ms(self) -> list[tuple[int, int]]:
        out = []
        for r in range(self.tbl_multi_cuts.rowCount()):
            vals = self._cut_list_row_values(r)
            if vals is not None:
                out.append(vals)
        return out

    def _multi_cut_ranges_sec(self) -> list[tuple[float, float]]:
        return [(a / 1000.0, b / 1000.0) for a, b in self._multi_cut_ranges_ms()]

    def _update_multi_cut_ui(self) -> None:
        self._hide_inline_multi_widgets()

        has_rows = self._has_multi_cuts()
        row = -1
        if getattr(self, "tbl_multi_cuts", None) is not None:
            row = self.tbl_multi_cuts.currentRow()

        if getattr(self, "btn_update_cut_item", None) is not None:
            self.btn_update_cut_item.setEnabled(row >= 0)
        if getattr(self, "btn_delete_cut_item", None) is not None:
            self.btn_delete_cut_item.setEnabled(row >= 0)
        if getattr(self, "btn_preview_selected_cut", None) is not None:
            self.btn_preview_selected_cut.setEnabled(row >= 0)
        if getattr(self, "btn_clear_cut_items", None) is not None:
            self.btn_clear_cut_items.setEnabled(has_rows)

        count = 0
        if getattr(self, "tbl_multi_cuts", None) is not None:
            count = self.tbl_multi_cuts.rowCount()

        if getattr(self, "lbl_multi_cuts_status", None) is not None:
            if count <= 0:
                self.lbl_multi_cuts_status.setText(LT("Nessun taglio aggiunto"))
            else:
                self.lbl_multi_cuts_status.setText(LT("Tagli salvati:") + f" {count}")

        if has_rows:
            self.btn_create_cut.setText(LT("Crea file senza i tagli"))
            self.rb_precise_cut.setChecked(True)
            self.rb_remove_segment.setChecked(True)

            self.rb_fast_cut.setEnabled(False)
            self.rb_precise_cut.setEnabled(False)
            self.rb_keep_segment.setEnabled(False)
            self.rb_remove_segment.setEnabled(False)
        else:
            self.btn_create_cut.setText(LT("Crea file tagliato"))

            self.rb_fast_cut.setEnabled(True)
            self.rb_precise_cut.setEnabled(True)
            self.rb_keep_segment.setEnabled(True)
            self.rb_remove_segment.setEnabled(True)

        dlg = getattr(self, "_multi_cuts_dialog", None)
        if dlg is not None and dlg.isVisible():
            try:
                dlg.sync_from_owner()
            except Exception:
                pass

    def _add_current_cut_to_list(self) -> None:
        ok, msg = self._validate_marks()
        if not ok:
            QtWidgets.QMessageBox.warning(self, LT("Errore"), msg)
            return

        start_ms = int(self._in_ms or 0)
        end_ms = int(self._out_ms or 0)
        if end_ms <= start_ms:
            QtWidgets.QMessageBox.warning(self, LT("Errore"), LT("OUT deve essere maggiore di IN."))
            return

        self.rb_precise_cut.setChecked(True)
        self.rb_remove_segment.setChecked(True)

        row = self.tbl_multi_cuts.rowCount()
        self.tbl_multi_cuts.insertRow(row)
        self._set_cut_table_row(row, start_ms, end_ms)
        self._sort_cut_list_rows()
        self._hide_inline_multi_widgets()
        self._update_multi_cut_ui()
        try:
            self.gb_multi.hide()
        except Exception:
            pass

    def _update_selected_cut_in_list(self) -> None:
        row = self.tbl_multi_cuts.currentRow()
        if row < 0:
            QtWidgets.QMessageBox.information(self, LT("Info"), LT("Seleziona prima un taglio dall'elenco."))
            return

        ok, msg = self._validate_marks()
        if not ok:
            QtWidgets.QMessageBox.warning(self, LT("Errore"), msg)
            return

        start_ms = int(self._in_ms or 0)
        end_ms = int(self._out_ms or 0)
        if end_ms <= start_ms:
            QtWidgets.QMessageBox.warning(self, LT("Errore"), LT("OUT deve essere maggiore di IN."))
            return

        self.rb_precise_cut.setChecked(True)
        self.rb_remove_segment.setChecked(True)

        self._set_cut_table_row(row, start_ms, end_ms)
        self._sort_cut_list_rows()
        self._update_multi_cut_ui()

    def _delete_selected_cut_from_list(self) -> None:
        row = self.tbl_multi_cuts.currentRow()
        if row < 0:
            return
        self.tbl_multi_cuts.removeRow(row)
        self._update_multi_cut_ui()

    def _clear_cut_list(self) -> None:
        if not self._has_multi_cuts():
            return
        ans = QtWidgets.QMessageBox.question(
            self,
            LT("Conferma"),
            LT("Vuoi svuotare l'elenco dei tagli?"),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if ans != QtWidgets.QMessageBox.Yes:
            return
        self.tbl_multi_cuts.setRowCount(0)
        self._update_multi_cut_ui()

    def _preview_selected_cut(self) -> None:
        row = self.tbl_multi_cuts.currentRow()
        if row < 0:
            QtWidgets.QMessageBox.information(self, LT("Info"), LT("Seleziona prima un taglio dall'elenco."))
            return

        vals = self._cut_list_row_values(row)
        if vals is None:
            QtWidgets.QMessageBox.warning(self, LT("Errore"), LT("Taglio selezionato non valido."))
            return

        start_ms, end_ms = vals
        self._restore_source_preview()
        self._preview_out_stop_ms = int(end_ms)
        self._seek_to_ms(int(start_ms), exact=True)
        QtCore.QTimer.singleShot(120, self._start_playback)
        self._multi_cut_last_preview_row = row

    def _start_precise_multi_cut(self, out_path: Path) -> None:
        if build_precise_multi_cut_plan is None:
            raise RuntimeError(LT("Modulo precise_cut non disponibile."))

        ranges_sec = self._multi_cut_ranges_sec()
        if not ranges_sec:
            raise RuntimeError(LT("Nessun taglio valido presente nell'elenco."))

        plan = build_precise_multi_cut_plan(
            input_path=self._source_path,
            output_path=out_path,
            cut_ranges=ranges_sec,
            selected_audio_stream_indices=self._selected_audio_stream_indices_for_precise_cut(),
        )

        self._precise_plan = plan
        self._precise_progress_state = {}
        self._precise_debug_lines = []
        self._precise_debug_command = " ".join(plan.command)

        proc = QtCore.QProcess(self)
        proc.setProgram(plan.command[0])
        proc.setArguments(plan.command[1:])
        proc.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        proc.readyReadStandardOutput.connect(self._on_precise_cut_stdout)
        proc.finished.connect(self._on_precise_cut_finished)

        self._precise_proc = proc
        self._set_progress_value(0, LT("Preparazione tagli multipli…"))
        proc.start()

        if not proc.waitForStarted(3000):
            self._precise_proc = None
            raise RuntimeError(LT("Impossibile avviare ffmpeg per i tagli multipli."))

    def _selected_audio_stream_indices_for_precise_cut(self):
        return None

    def _on_precise_cut_stdout(self) -> None:
        if self._precise_proc is None:
            return

        raw = bytes(self._precise_proc.readAllStandardOutput()).decode("utf-8", errors="replace")
        if not raw:
            return

        for line in raw.splitlines():
            line = line.rstrip()
            if not line:
                continue

            self._precise_debug_lines.append(line)
            if len(self._precise_debug_lines) > 200:
                self._precise_debug_lines = self._precise_debug_lines[-200:]

            if parse_progress_line is None or progress_percent_from_kv is None:
                continue

            is_boundary, self._precise_progress_state = parse_progress_line(
                line,
                self._precise_progress_state,
            )
            if not is_boundary:
                continue

            pct = progress_percent_from_kv(
                self._precise_progress_state,
                float(getattr(self._precise_plan, "segment_duration", 0.0) or 0.0),
            )
            if pct is not None:
                self._set_progress_value(int(round(pct)), LT("Taglio preciso in corso…"))

            if self._precise_progress_state.get("progress") == "end":
                self._precise_progress_state = {}

    def _on_precise_cut_finished(self, exit_code: int, exit_status: int) -> None:
        out_path = None
        try:
            out_path = getattr(self._precise_plan, "output_path", None)
        except Exception:
            out_path = None

        debug_tail = "\n".join(self._precise_debug_lines[-40:]).strip()
        if not debug_tail:
            debug_tail = LT("Nessun log disponibile.")

        cmd_text = str(getattr(self, "_precise_debug_command", "") or "").strip()
        if cmd_text:
            detailed = LT("Comando eseguito:") + "\n" + cmd_text + "\n\n" + LT("Log finale:") + "\n" + debug_tail
        else:
            detailed = debug_tail

        self._precise_proc = None
        self._precise_progress_state = {}

        ok = (int(exit_code) == 0 and out_path is not None and Path(out_path).is_file())
        if ok:
            self._last_created_cut_path = Path(out_path)
            self._set_progress_value(100, LT("Completato"))
            QtWidgets.QMessageBox.information(
                self,
                LT("Info"),
                LT("File tagliato creato:") + "\n" + str(out_path),
            )
        else:
            self._set_progress_idle()
            msg = QtWidgets.QMessageBox(self)
            msg.setIcon(QtWidgets.QMessageBox.Critical)
            msg.setWindowTitle(LT("Errore"))
            msg.setText(LT("Creazione file tagliato fallita."))
            msg.setInformativeText(LT("Apri Dettagli per vedere il motivo."))
            msg.setDetailedText(detailed)
            msg.setStandardButtons(QtWidgets.QMessageBox.Ok)
            msg.exec_()

        self._set_busy(False)
        self._update_enabled()
        self._update_multi_cut_ui()

    def _start_precise_cut(self, out_path: Path) -> None:
        if build_precise_cut_plan is None:
            raise RuntimeError(LT("Modulo precise_cut non disponibile."))

        operation = "keep" if self.rb_keep_segment.isChecked() else "remove"
        plan = build_precise_cut_plan(
            input_path=self._source_path,
            output_path=out_path,
            in_sec=float(int(self._in_ms or 0)) / 1000.0,
            out_sec=float(int(self._out_ms or 0)) / 1000.0,
            selected_audio_stream_indices=self._selected_audio_stream_indices_for_precise_cut(),
            operation=operation,
        )

        self._precise_plan = plan
        self._precise_progress_state = {}
        self._precise_debug_lines = []
        self._precise_debug_command = " ".join(plan.command)

        proc = QtCore.QProcess(self)
        proc.setProgram(plan.command[0])
        proc.setArguments(plan.command[1:])
        proc.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        proc.readyReadStandardOutput.connect(self._on_precise_cut_stdout)
        proc.finished.connect(self._on_precise_cut_finished)

        self._precise_proc = proc
        self._set_progress_value(0, LT("Preparazione taglio preciso…"))
        proc.start()

        if not proc.waitForStarted(3000):
            self._precise_proc = None
            raise RuntimeError(LT("Impossibile avviare ffmpeg per il taglio preciso."))

    def _create_cut(self) -> None:
        self._restore_source_preview()
        ok, msg = self._validate_marks()
        multi_mode = self._has_multi_cuts()

        if not multi_mode and not ok:
            QtWidgets.QMessageBox.warning(self, LT("Errore"), msg)
            return

        if multi_mode:
            self.rb_precise_cut.setChecked(True)
            self.rb_remove_segment.setChecked(True)

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

        if multi_mode and self.rb_fast_cut.isChecked():
            QtWidgets.QMessageBox.information(
                self,
                LT("Info"),
                LT("Con più tagli viene usato automaticamente il taglio preciso."),
            )
            self.rb_precise_cut.setChecked(True)

        if not multi_mode and self.rb_fast_cut.isChecked():
            summary, max_shift = self._rapid_shift_summary()
            if max_shift >= 500:
                ans = QtWidgets.QMessageBox.question(
                    self,
                    LT("Conferma taglio rapido"),
                    summary + "\n\n" + LT("Vuoi continuare con questi punti reali del taglio rapido?"),
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                    QtWidgets.QMessageBox.Yes,
                )
                if ans != QtWidgets.QMessageBox.Yes:
                    return

        self._stop_playback()
        self._set_busy(True)
        started_async = False

        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)

            if multi_mode:
                self._start_precise_multi_cut(out_path)
                started_async = True
                return

            if self.rb_precise_cut.isChecked():
                self._start_precise_cut(out_path)
                started_async = True
                return

            self._set_progress_busy_indeterminate(LT("Preparazione…"))
            out_done = self._run_fast_cut()
            self._last_created_cut_path = Path(out_done)
            self._set_progress_value(100, LT("Completato"))
            QtWidgets.QMessageBox.information(
                self,
                LT("Info"),
                LT("File tagliato creato:") + "\n" + str(out_done),
            )
        except Exception as e:
            self._set_progress_idle()
            QtWidgets.QMessageBox.critical(
                self,
                LT("Errore"),
                LT("Creazione file tagliato fallita:") + "\n" + str(e),
            )
        finally:
            if not started_async:
                self._set_busy(False)
                self._update_enabled()
                self._update_multi_cut_ui()
