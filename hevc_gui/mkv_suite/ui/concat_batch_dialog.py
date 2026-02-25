#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from PyQt5.QtCore import Qt, QProcess, QSettings, QTimer
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QFileDialog, QSpinBox, QLineEdit, QAbstractItemView,
    QHeaderView, QMessageBox, QProgressBar, QTextEdit, QComboBox, QSplitter
)
from PyQt5.QtWidgets import QDialog

try:
    from hevc_gui.i18n import L
except Exception:
    def L(s: str) -> str:
        return s

from hevc_gui.mkv_suite.core.concat_batch import (
    ConcatItem, ConcatGroup,
    probe_concat_item, sort_items, mark_compat,
    build_groups_auto, build_groups_manual,
    build_append_cmd, fmt_duration, auto_group_diagnostics
)


class ConcatBatchDialog(QDialog):
    _RX_PROGRESS = re.compile(r"(?:Progresso|Progress)\s*:\s*(\d+)\s*%")

    COL_POS = 0
    COL_SEASON = 1
    COL_EP = 2
    COL_MANUAL_GROUP = 3
    COL_FILE = 4
    COL_TITLE = 5
    COL_DUR = 6
    COL_COMPAT = 7

    def __init__(self, host=None, parent=None):
        super().__init__(parent)
        self.host = host
        self._items: List[ConcatItem] = []
        self._groups: List[ConcatGroup] = []
        self._proc: Optional[QProcess] = None
        self._proc_buf: str = ""
        self._queue: List[ConcatGroup] = []
        self._busy = False
        self._last_in_dir: Optional[Path] = None

        self._block_files_item_changed = False
        self._block_groups_item_changed = False

        self._build_ui()
        self._unlock_resize_limits()
        self._update_mode_ui()
        self._update_auto_diagnostics()
        self._refresh_manual_group_tooltips()

        try:
            self.setModal(False)
        except Exception:
            pass
        try:
            self.setWindowTitle(L("Unisci episodi"))
        except Exception:
            pass
        try:
            self.resize(600, 800) #980,820
        except Exception:
            pass


    # -------------------- debug window size --------------------
    def _debug_report_window_size(self, why: str = "") -> None:
        try:
            inner = self.size()
            frame = self.frameGeometry().size()
            iw, ih = int(inner.width()), int(inner.height())
            fw, fh = int(frame.width()), int(frame.height())

            msg = f"[UI] Unisci episodi {why} | inner={iw}x{ih} | frame={fw}x{fh}"
            print(msg)

            try:
                if self.host is not None and hasattr(self.host, "_log"):
                    self.host._log(msg)
            except Exception:
                pass

            try:
                self.setWindowTitle(L("Unisci episodi"))
            except Exception:
                pass
        except Exception:
            pass

    def showEvent(self, event):
        try:
            self.resize(600, 800)
            self.setWindowTitle(L("Unisci episodi"))
        except Exception:
            pass
        try:
            super().showEvent(event)
        finally:
            self._debug_report_window_size("show")

    def resizeEvent(self, event):
        try:
            super().resizeEvent(event)
        finally:
            self._debug_report_window_size("resize")

    # -------------------- host helpers --------------------
    def _log_host(self, msg: str) -> None:
        try:
            if self.host is not None and hasattr(self.host, "_log"):
                self.host._log(msg)
        except Exception:
            pass

    def _log(self, msg: str) -> None:
        self.txt_log.append(msg)
        self._log_host(msg)

    def _get_tc(self):
        try:
            if self.host is not None:
                return getattr(self.host, "_tc", None)
        except Exception:
            pass
        return None

    def _mkvmerge_bin(self) -> str:
        tc = self._get_tc()
        mkvmerge_bin = ""
        try:
            mkvmerge_bin = getattr(tc, "mkvmerge", "") or ""
        except Exception:
            mkvmerge_bin = ""
        return mkvmerge_bin or "mkvmerge"

    def _ensure_out_dir(self) -> Optional[Path]:
        try:
            if self.host is not None:
                od = getattr(self.host, "_out_dir", None)
                if od is None:
                    chooser = getattr(self.host, "on_choose_outdir", None)
                    if callable(chooser):
                        ok = chooser()
                        if not ok:
                            return None
                job = getattr(self.host, "_job_dir", None) or getattr(self.host, "_out_dir", None)
                if job:
                    p = Path(job)
                    p.mkdir(parents=True, exist_ok=True)
                    remux = p / "remux"
                    remux.mkdir(parents=True, exist_ok=True)
                    return remux
        except Exception:
            pass

        p = Path.cwd() / "tmp" / "mkv_suite_concat_out"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _host_is_busy(self) -> bool:
        try:
            return bool(getattr(self.host, "_busy", False))
        except Exception:
            return False

    # -------------------- mode helpers --------------------
    def _is_manual_mode(self) -> bool:
        return self.cmb_mode.currentData() == "manual"

    def _is_auto_mode(self) -> bool:
        return not self._is_manual_mode()

    def _prefix_text(self) -> str:
        return (self.ed_prefix.text() or "").strip() or "serie"

    def _update_mode_ui(self) -> None:
        manual = self._is_manual_mode()
        self.spn_group.setEnabled(not manual)
        self.lbl_group_size.setEnabled(not manual)
        self.btn_sort.setEnabled(not self._busy)  # sempre disponibile, anche in manuale
        if manual:
            self.lbl_mode_hint.setText(L("Manuale: scrivi tu il numero Gruppo in ogni riga (stesso numero = stesso file finale)."))
        else:
            self.lbl_mode_hint.setText(L("Automatico: usa i tag/nomi episodio. Se incoerenti, controlla l'anteprima o passa a Manuale."))
        self._fill_files()              # aggiorna editabilità colonna Gruppo
        self._update_auto_diagnostics() # avviso/suggerimento
        self._rebuild_groups_preview(log_message=False)

    def _update_auto_diagnostics(self) -> None:
        if self._is_manual_mode():
            self.lbl_auto_diag.setText(L("Modalità Manuale attiva: nessun raggruppamento automatico."))
            return
        if not self._items:
            self.lbl_auto_diag.setText(L("Automatico (default): aggiungi file e vedrai qui eventuali avvisi sui tag episodio."))
            return

        d = auto_group_diagnostics(self._items)
        if d.get("ok"):
            self.lbl_auto_diag.setText(L("Automatico: tag episodio letti correttamente. Controlla comunque l'anteprima prima di unire."))
            return

        parts = []
        if d.get("missing_ep_rows"):
            parts.append(L("episodi non letti"))
        if d.get("duplicates"):
            parts.append(L("episodi duplicati"))
        if d.get("mixed_season_presence"):
            parts.append(L("stagione non uniforme"))
        if d.get("gaps"):
            parts.append(L("sequenza non continua"))

        msg = ", ".join(parts) if parts else L("tag incoerenti")
        self.lbl_auto_diag.setText(
            L("Avviso automatico: ") + msg + ". " + L("Controlla l'anteprima oppure usa Gruppi manuali.")
        )

    # -------------------- UI --------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        self.lbl_intro = QLabel(L("Unisci più MKV in sequenza senza ricodifica."))
        self.lbl_intro.setWordWrap(True)
        root.addWidget(self.lbl_intro)

        # Riga file (azioni base)
        row_top = QHBoxLayout()
        row_top.setSpacing(6)
        self.btn_add = QPushButton(L("Aggiungi MKV…"))
        self.btn_remove = QPushButton(L("Rimuovi selezionati"))
        self.btn_clear = QPushButton(L("Svuota"))
        self.btn_sort = QPushButton(L("Ordina"))
        row_top.addWidget(self.btn_add)
        row_top.addWidget(self.btn_remove)
        row_top.addWidget(self.btn_clear)
        row_top.addWidget(self.btn_sort)
        row_top.addStretch(1)
        root.addLayout(row_top)

        # Riga impostazioni 1 (modalità + grouping)
        row_cfg1 = QHBoxLayout()
        row_cfg1.setSpacing(6)

        row_cfg1.addWidget(QLabel(L("Modalità")))
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItem(L("Automatico"), "auto")
        self.cmb_mode.addItem(L("Gruppi manuali"), "manual")
        self.cmb_mode.setMinimumWidth(120)
        self.cmb_mode.setToolTip(L("Automatico (default) oppure Gruppi manuali."))
        row_cfg1.addWidget(self.cmb_mode)

        self.lbl_group_size = QLabel(L("Quante puntate per file"))
        row_cfg1.addWidget(self.lbl_group_size)

        self.spn_group = QSpinBox()
        self.spn_group.setRange(1, 99)
        self.spn_group.setValue(2)
        self.spn_group.setFixedWidth(72)
        self.spn_group.setToolTip(L("Usato solo in Automatico. Esempio: 2 crea 1+2, 3+4, 5+6..."))
        row_cfg1.addWidget(self.spn_group)

        row_cfg1.addStretch(1)
        root.addLayout(row_cfg1)

        # Riga impostazioni 2 (nome serie + anteprima)
        row_cfg2 = QHBoxLayout()
        row_cfg2.setSpacing(6)

        row_cfg2.addWidget(QLabel(L("Nome serie / prefisso")))
        self.ed_prefix = QLineEdit(L("serie"))
        self.ed_prefix.setPlaceholderText(L("es. La Freccia Nera"))
        self.ed_prefix.setMinimumWidth(180)
        self.ed_prefix.setToolTip(L("Nome base dei file finali (es. La Freccia Nera)."))
        try:
            self.ed_prefix.setMinimumContentsLength(10)
        except Exception:
            pass
        row_cfg2.addWidget(self.ed_prefix, 1)

        self.btn_make_groups = QPushButton(L("Prepara anteprima"))
        self.btn_make_groups.setMinimumWidth(130)
        self.btn_make_groups.setToolTip(L("Aggiorna l'anteprima dei file finali che verranno creati."))
        row_cfg2.addWidget(self.btn_make_groups)

        root.addLayout(row_cfg2)

        # Riga impostazioni 2 (messaggi brevi)
        self.lbl_mode_hint = QLabel("")
        self.lbl_mode_hint.setWordWrap(True)
        root.addWidget(self.lbl_mode_hint)

        self.lbl_auto_diag = QLabel("")
        self.lbl_auto_diag.setWordWrap(True)
        root.addWidget(self.lbl_auto_diag)

        # --- Area centrale con splitter (ridimensionabile) ---
        self._tables_splitter = QSplitter(Qt.Vertical)
        self._tables_splitter.setChildrenCollapsible(False)

        # Pannello superiore: lista file
        files_panel = QWidget(self)
        files_lay = QVBoxLayout(files_panel)
        files_lay.setContentsMargins(0, 0, 0, 0)
        files_lay.setSpacing(4)

        lbl_files = QLabel(L("Elenco episodi / file sorgenti"))
        lbl_files.setWordWrap(True)
        files_lay.addWidget(lbl_files)

        self.tbl_files = QTableWidget(0, 8)
        self.tbl_files.setHorizontalHeaderLabels([
            L("#"), L("S"), L("Ep"), L("Gruppo"), L("File"), L("Titolo tag"), L("Durata"), L("Compat")
        ])
        self.tbl_files.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_files.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tbl_files.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.SelectedClicked)
        self.tbl_files.setMinimumHeight(180)
        hh = self.tbl_files.horizontalHeader()
        try:
            hh.setMinimumSectionSize(24)
        except Exception:
            pass
        hh.setSectionResizeMode(self.COL_POS, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(self.COL_SEASON, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(self.COL_EP, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(self.COL_MANUAL_GROUP, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(self.COL_FILE, QHeaderView.Stretch)
        hh.setSectionResizeMode(self.COL_TITLE, QHeaderView.Stretch)
        hh.setSectionResizeMode(self.COL_DUR, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(self.COL_COMPAT, QHeaderView.ResizeToContents)
        files_lay.addWidget(self.tbl_files, 1)

        # Pannello inferiore: anteprima gruppi
        groups_panel = QWidget(self)
        groups_lay = QVBoxLayout(groups_panel)
        groups_lay.setContentsMargins(0, 0, 0, 0)
        groups_lay.setSpacing(4)

        self.lbl_preview = QLabel(L("Anteprima output (nomi dei file che verranno creati)."))
        self.lbl_preview.setWordWrap(True)
        groups_lay.addWidget(self.lbl_preview)

        self.tbl_groups = QTableWidget(0, 6)
        self.tbl_groups.setHorizontalHeaderLabels([
            L("Gruppo"), L("Range"), L("N file"), L("Output (anteprima)"), L("Compat"), L("Stato")
        ])
        self.tbl_groups.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_groups.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tbl_groups.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.SelectedClicked)
        self.tbl_groups.setMinimumHeight(140)
        hg = self.tbl_groups.horizontalHeader()
        try:
            hg.setMinimumSectionSize(24)
        except Exception:
            pass
        hg.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hg.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hg.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hg.setSectionResizeMode(3, QHeaderView.Stretch)
        hg.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        hg.setSectionResizeMode(5, QHeaderView.Stretch)
        groups_lay.addWidget(self.tbl_groups, 1)

        self._tables_splitter.addWidget(files_panel)
        self._tables_splitter.addWidget(groups_panel)
        try:
            self._tables_splitter.setStretchFactor(0, 3)
            self._tables_splitter.setStretchFactor(1, 2)
            self._tables_splitter.setSizes([280, 210])
        except Exception:
            pass

        root.addWidget(self._tables_splitter, 1)

        # Riga azioni finali
        row_run = QHBoxLayout()
        row_run.setSpacing(6)
        self.btn_merge_sel = QPushButton(L("Unisci gruppo selezionato"))
        self.btn_merge_all = QPushButton(L("Unisci tutti"))
        self.btn_stop = QPushButton(L("Stop"))
        self.btn_stop.setEnabled(False)

        self.btn_merge_sel.setMinimumWidth(150)
        self.btn_merge_all.setMinimumWidth(95)

        row_run.addWidget(self.btn_merge_sel)
        row_run.addWidget(self.btn_merge_all)
        row_run.addWidget(self.btn_stop)
        row_run.addStretch(1)
        root.addLayout(row_run)

        # Progress
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setMinimumHeight(18)
        root.addWidget(self.progress)

        # Log (più compatto)
        lbl_log = QLabel(L("Log"))
        root.addWidget(lbl_log)

        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMinimumHeight(90)
        self.txt_log.setMaximumHeight(130)
        root.addWidget(self.txt_log)

        # Tooltips UI principali (traducibili)
        def _tt(w, txt):
            try:
                w.setToolTip(txt)
            except Exception:
                pass
            try:
                w.setStatusTip(txt)
            except Exception:
                pass
            try:
                w.setWhatsThis(txt)
            except Exception:
                pass

        _tt(self.lbl_intro, L("Unisce episodi MKV in sequenza senza ricodifica video/audio."))
        _tt(self.btn_add, L("Aggiunge uno o più file MKV alla lista sorgente."))
        _tt(self.btn_remove, L("Rimuove dalla lista i file selezionati (non cancella i file dal disco)."))
        _tt(self.btn_clear, L("Svuota la lista file, l'anteprima gruppi e lo stato della progressione."))
        _tt(self.btn_sort, L("Ordina i file per stagione/episodio e poi per nome file."))
        _tt(self.cmb_mode, L("Seleziona la modalità di raggruppamento: Automatico oppure Gruppi manuali."))
        _tt(self.lbl_group_size, L("Numero di episodi da unire in ogni file finale (solo modalità Automatico)."))
        _tt(self.spn_group, L("Usato solo in Automatico. Esempio: 2 crea gruppi 1+2, 3+4, 5+6..."))
        _tt(self.ed_prefix, L("Prefisso/nome serie usato per generare i nomi dei file finali in anteprima."))
        _tt(self.btn_make_groups, L("Aggiorna l'anteprima dei gruppi e dei nomi output in base alle impostazioni correnti."))

        _tt(self.lbl_mode_hint, L("Suggerimenti rapidi sulla modalità selezionata."))
        _tt(self.lbl_auto_diag, L("Diagnostica automatica sui tag episodio per aiutare il raggruppamento."))

        _tt(self.tbl_files, L("Elenco file sorgenti. In 'Gruppi manuali' puoi modificare la colonna Gruppo per decidere quali episodi finiscono nello stesso file."))
        _tt(self.lbl_preview, L("Anteprima dei file output che verranno creati dall'unione."))
        _tt(self.tbl_groups, L("Elenco gruppi da creare. Puoi selezionare un gruppo e modificare il nome file di output nella colonna anteprima."))

        _tt(self.btn_merge_sel, L("Avvia l'unione del solo gruppo selezionato nell'anteprima."))
        _tt(self.btn_merge_all, L("Avvia l'unione di tutti i gruppi validi mostrati in anteprima."))
        _tt(self.btn_stop, L("Interrompe l'operazione di unione in corso."))
        _tt(self.progress, L("Progressione dell'operazione di unione corrente (0-100%)."))
        _tt(self.txt_log, L("Log operativo della finestra 'Unisci episodi'."))

        # Tooltip intestazioni tabella file
        try:
            _tips_files = {
                self.COL_POS: L("Posizione corrente del file nella lista."),
                self.COL_SEASON: L("Stagione rilevata dai tag/nome file (se disponibile)."),
                self.COL_EP: L("Numero episodio rilevato dai tag/nome file (se disponibile)."),
                self.COL_MANUAL_GROUP: L("Numero gruppo manuale. Stesso numero = stesso file finale (usato solo in 'Gruppi manuali')."),
                self.COL_FILE: L("Nome del file sorgente MKV."),
                self.COL_TITLE: L("Titolo embedded rilevato nel file MKV (se presente)."),
                self.COL_DUR: L("Durata del file sorgente."),
                self.COL_COMPAT: L("Compatibilità append rispetto al primo file (OK/MIX)."),
            }
            for c, txt in _tips_files.items():
                it = self.tbl_files.horizontalHeaderItem(c)
                if it is not None:
                    it.setToolTip(txt)
        except Exception:
            pass

        # Tooltip intestazioni tabella gruppi
        try:
            _tips_groups = {
                0: L("Indice gruppo (o ID manuale in modalità manuale)."),
                1: L("Intervallo episodi del gruppo (range)."),
                2: L("Numero di file contenuti nel gruppo."),
                3: L("Nome file di output in anteprima (modificabile)."),
                4: L("Compatibilità complessiva del gruppo (OK/MIX)."),
                5: L("Stato dell'operazione (in attesa, in corso, ok, errore, saltato...)."),
            }
            for c, txt in _tips_groups.items():
                it = self.tbl_groups.horizontalHeaderItem(c)
                if it is not None:
                    it.setToolTip(txt)
        except Exception:
            pass

        # Signals
        self.btn_add.clicked.connect(self.on_add_files)
        self.btn_remove.clicked.connect(self.on_remove_selected)
        self.btn_clear.clicked.connect(self.on_clear)
        self.btn_sort.clicked.connect(self.on_sort)
        self.btn_make_groups.clicked.connect(self.on_make_groups)
        self.btn_merge_sel.clicked.connect(self.on_merge_selected_group)
        self.btn_merge_all.clicked.connect(self.on_merge_all_groups)
        self.btn_stop.clicked.connect(self.on_stop)

        self.cmb_mode.currentIndexChanged.connect(self.on_mode_changed)
        self.spn_group.valueChanged.connect(self.on_preview_input_changed)
        self.ed_prefix.textChanged.connect(self.on_preview_input_changed)

        self.tbl_files.itemChanged.connect(self._on_files_item_changed)
        self.tbl_groups.itemChanged.connect(self._on_group_item_changed)

    # -------------------- table helpers --------------------
    def _it(self, s: str, editable: bool = False, align: Optional[int] = None) -> QTableWidgetItem:
        it = QTableWidgetItem("" if s is None else str(s))
        if not editable:
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
        if align is not None:
            it.setTextAlignment(align)
        return it

    def _fill_files(self) -> None:
        # non ordina automaticamente: preserva ordine attuale (importante in manuale)
        self._items = mark_compat(list(self._items))

        self._block_files_item_changed = True
        try:
            self.tbl_files.setRowCount(0)
            self.tbl_files.setRowCount(len(self._items))

            manual_mode = self._is_manual_mode()

            for r, it in enumerate(self._items):
                self.tbl_files.setItem(r, self.COL_POS, self._it(str(r + 1), align=Qt.AlignCenter))
                self.tbl_files.setItem(
                    r, self.COL_SEASON,
                    self._it("" if it.detected_season is None else str(it.detected_season), align=Qt.AlignCenter)
                )
                self.tbl_files.setItem(
                    r, self.COL_EP,
                    self._it("" if it.detected_order is None else str(it.detected_order), align=Qt.AlignCenter)
                )
                self.tbl_files.setItem(
                    r, self.COL_MANUAL_GROUP,
                    self._it("" if it.manual_group is None else str(it.manual_group), editable=manual_mode, align=Qt.AlignCenter)
                )
                self.tbl_files.setItem(r, self.COL_FILE, self._it(it.file_name))
                self.tbl_files.setItem(r, self.COL_TITLE, self._it(it.embedded_title or ""))
                self.tbl_files.setItem(r, self.COL_DUR, self._it(fmt_duration(it.duration_sec), align=Qt.AlignCenter))
                compat = "OK" if not it.warning else L("MIX")
                self.tbl_files.setItem(r, self.COL_COMPAT, self._it(compat, align=Qt.AlignCenter))

                if it.warning:
                    for c in range(self.tbl_files.columnCount()):
                        cell = self.tbl_files.item(r, c)
                        if cell is not None:
                            cell.setToolTip(L("Layout tracce differente dal primo file (mkvmerge potrebbe rifiutare l'append)."))

                # tooltip utile per colonna gruppo
                gcell = self.tbl_files.item(r, self.COL_MANUAL_GROUP)
                if gcell is not None:
                    if manual_mode:
                        gcell.setToolTip(L("Manuale: stesso numero = stesso file finale (es. 1,1,2,2,3,3,3)."))
                    else:
                        gcell.setToolTip(L("Ignorato in Automatico. Passa a 'Gruppi manuali' per usarlo."))

        finally:
            self._block_files_item_changed = False

        self._update_group_compat_cells()
        self._refresh_manual_group_tooltips()

    def _fill_groups(self) -> None:
        self._block_groups_item_changed = True
        try:
            self.tbl_groups.setRowCount(0)
            self.tbl_groups.setRowCount(len(self._groups))
            for r, g in enumerate(self._groups):
                ord_a = g.first_order
                ord_b = g.last_order
                if ord_a is not None and ord_b is not None:
                    rng = f"{ord_a}" if ord_a == ord_b else f"{ord_a}-{ord_b}"
                    if g.first_season is not None and g.single_season:
                        rng = f"S{g.first_season:02d} E{rng}"
                else:
                    rng = "-"

                compat = "OK"
                if any(x.warning for x in g.items):
                    compat = L("MIX")

                group_label = str(g.manual_id) if (g.source_mode == "manual" and g.manual_id is not None) else str(g.index)

                self.tbl_groups.setItem(r, 0, self._it(group_label, align=Qt.AlignCenter))
                self.tbl_groups.setItem(r, 1, self._it(rng, align=Qt.AlignCenter))
                self.tbl_groups.setItem(r, 2, self._it(str(g.count), align=Qt.AlignCenter))
                self.tbl_groups.setItem(r, 3, self._it(g.out_name, editable=True))
                self.tbl_groups.setItem(r, 4, self._it(compat, align=Qt.AlignCenter))
                self.tbl_groups.setItem(r, 5, self._it(g.status or ""))
        finally:
            self._block_groups_item_changed = False

    def _on_group_item_changed(self, item: QTableWidgetItem) -> None:
        if self._block_groups_item_changed:
            return
        if item is None:
            return
        r, c = item.row(), item.column()
        if r < 0 or r >= len(self._groups):
            return
        if c == 3:
            s = (item.text() or "").strip()
            if not s:
                s = self._groups[r].out_name or f"concat_{r+1:02d}.mkv"
            if not s.lower().endswith(".mkv"):
                s += ".mkv"
            self._groups[r].out_name = s

            self._block_groups_item_changed = True
            try:
                item.setText(s)
            finally:
                self._block_groups_item_changed = False

    def _on_files_item_changed(self, item: QTableWidgetItem) -> None:
        if self._block_files_item_changed:
            return
        if item is None:
            return
        r, c = item.row(), item.column()
        if r < 0 or r >= len(self._items):
            return
        if c != self.COL_MANUAL_GROUP:
            return

        txt = (item.text() or "").strip()
        val = None
        if txt:
            try:
                x = int(txt)
                if x > 0:
                    val = x
            except Exception:
                val = None

        self._items[r].manual_group = val

        # normalizza cella (solo numero valido o vuoto)
        self._block_files_item_changed = True
        try:
            item.setText("" if val is None else str(val))
        finally:
            self._block_files_item_changed = False

        if self._is_manual_mode():
            self._rebuild_groups_preview(log_message=False)

    def _update_group_compat_cells(self):
        if not self._groups:
            return
        for g in self._groups:
            g.status = ""
        self._fill_groups()

    # -------------------- preview / grouping --------------------
    def _rebuild_groups_preview(self, log_message: bool = False) -> None:
        if self._busy:
            return

        if not self._items:
            self._groups = []
            self._fill_groups()
            self._update_auto_diagnostics()
            return

        prefix = self._prefix_text()

        if self._is_manual_mode():
            self._groups = build_groups_manual(self._items, prefix=prefix)
            self._update_auto_diagnostics()
            if log_message:
                self._log(f"[OK] Anteprima manuale: {len(self._groups)} gruppi.")
            return self._fill_groups()

        # automatico
        d = auto_group_diagnostics(self._items)
        self._groups = build_groups_auto(self._items, group_size=int(self.spn_group.value()), prefix=prefix)
        self._update_auto_diagnostics()
        self._fill_groups()

        if log_message:
            n = int(self.spn_group.value())
            self._log(f"[OK] Anteprima automatica: {len(self._groups)} gruppi da {n} file.")
            if not d.get("ok"):
                self._log("[WARN] Tag episodio mancanti/incoerenti: controlla l'anteprima o usa Gruppi manuali.")

    def _refresh_manual_group_tooltips(self) -> None:
        """Aggiorna tooltip header/celle della colonna Gruppo in base alla modalità."""
        try:
            manual_mode = self._is_manual_mode()
        except Exception:
            manual_mode = False

        try:
            hdr = self.tbl_files.horizontalHeaderItem(self.COL_MANUAL_GROUP)
            if hdr is not None:
                if manual_mode:
                    hdr.setToolTip(L("Numero gruppo manuale. Stesso numero = stesso file finale (attivo in 'Gruppi manuali')."))
                else:
                    hdr.setToolTip(L("Colonna ignorata in modalità Automatico. Passa a 'Gruppi manuali' per usarla."))
        except Exception:
            pass

        try:
            if manual_mode:
                self.tbl_files.setToolTip(L("Elenco file sorgenti. In 'Gruppi manuali' puoi modificare la colonna Gruppo per decidere quali episodi finiscono nello stesso file."))
            else:
                self.tbl_files.setToolTip(L("Elenco file sorgenti. In modalità Automatico la colonna Gruppo è ignorata."))
        except Exception:
            pass

        try:
            for r in range(self.tbl_files.rowCount()):
                gcell = self.tbl_files.item(r, self.COL_MANUAL_GROUP)
                if gcell is None:
                    continue
                if manual_mode:
                    gcell.setToolTip(L("Manuale: stesso numero = stesso file finale (es. 1,1,2,2,3,3,3)."))
                else:
                    gcell.setToolTip(L("Ignorato in Automatico. Passa a 'Gruppi manuali' per usarlo."))
        except Exception:
            pass

    # --- geometry persistence (auto patch) ---
    def _restore_window_geometry_prefs(self) -> None:
        """Ripristina geometria dialog; default 600x800 al primo avvio."""
        try:
            st = QSettings("HEVC-GUI", "MKVSuiteEmbedded")
            geo = st.value("concat_batch_dialog/geometry")
            if geo:
                self.restoreGeometry(geo)
                return
        except Exception:
            pass
        try:
            self.resize(600, 800)
        except Exception:
            pass

    def _save_window_geometry_prefs(self) -> None:
        try:
            st = QSettings("HEVC-GUI", "MKVSuiteEmbedded")
            st.setValue("concat_batch_dialog/geometry", self.saveGeometry())
        except Exception:
            pass

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if getattr(self, "_geom_restored_once", False):
            return
        self._geom_restored_once = True
        try:
            QTimer.singleShot(0, self._restore_window_geometry_prefs)
        except Exception:
            pass

    def accept(self) -> None:
        try:
            self._save_window_geometry_prefs()
        except Exception:
            pass
        super().accept()

    def reject(self) -> None:
        try:
            self._save_window_geometry_prefs()
        except Exception:
            pass
        super().reject()

    def closeEvent(self, event) -> None:
        try:
            self._save_window_geometry_prefs()
        except Exception:
            pass
        super().closeEvent(event)

    # --- resize unlock (auto patch) ---
    def _unlock_resize_limits(self) -> None:
        """Sblocca eventuali vincoli residui su larghezza/altezza del dialog."""
        try:
            self.setSizeGripEnabled(True)
        except Exception:
            pass
        try:
            # min ragionevole, ma altezza non bloccata
            self.setMinimumSize(520, 420)
            self.setMaximumSize(16777215, 16777215)
        except Exception:
            pass

    # -------------------- actions --------------------
    def on_mode_changed(self) -> None:
        self._update_mode_ui()
        self._refresh_manual_group_tooltips()

    def on_preview_input_changed(self, *_args) -> None:
        # aggiorna anteprima sempre visibile
        self._rebuild_groups_preview(log_message=False)

    def on_add_files(self) -> None:
        if self._busy:
            return
        start_dir = ""
        try:
            if self._last_in_dir:
                start_dir = str(self._last_in_dir)
            elif self.host is not None:
                p = getattr(self.host, "_last_in_dir", None)
                if p:
                    start_dir = str(p)
        except Exception:
            start_dir = ""

        files, _ = QFileDialog.getOpenFileNames(
            self,
            L("Aggiungi file MKV da unire"),
            start_dir,
            "Matroska (*.mkv);;Tutti i file (*.*)"
        )
        if not files:
            return

        mkvmerge_bin = self._mkvmerge_bin()
        existing = {str(x.path) for x in self._items}

        added = 0
        errors = []
        for fp in files:
            try:
                p = Path(fp).expanduser().resolve()
                if p.suffix.lower() != ".mkv":
                    continue
                if str(p) in existing:
                    continue
                ci = probe_concat_item(p, mkvmerge_bin)
                self._items.append(ci)
                existing.add(str(p))
                added += 1
                self._last_in_dir = p.parent
            except Exception as e:
                errors.append(f"{Path(fp).name}: {e}")

        self._fill_files()
        self._update_auto_diagnostics()
        self._rebuild_groups_preview(log_message=False)

        if added:
            self._log(f"[OK] Aggiunti {added} file per unione.")
        if errors:
            self._log("[WARN] Alcuni file non sono stati letti:")
            for e in errors[:10]:
                self._log("  - " + e)

    def on_remove_selected(self) -> None:
        if self._busy:
            return
        rows = sorted({i.row() for i in self.tbl_files.selectedIndexes()}, reverse=True)
        if not rows:
            return
        for r in rows:
            if 0 <= r < len(self._items):
                self._items.pop(r)
        self._fill_files()
        self._rebuild_groups_preview(log_message=False)
        self._log(f"[OK] Rimossi {len(rows)} file dalla lista.")

    def on_clear(self) -> None:
        if self._busy:
            return
        self._items = []
        self._groups = []
        self.tbl_files.setRowCount(0)
        self.tbl_groups.setRowCount(0)
        self.progress.setValue(0)
        self._update_auto_diagnostics()
        self._log("[OK] Lista unione svuotata.")

    def on_sort(self) -> None:
        if self._busy:
            return
        self._items = sort_items(self._items)
        self._fill_files()
        self._rebuild_groups_preview(log_message=False)
        self._log("[OK] Ordinamento aggiornato (stagione/episodio -> filename).")

    def on_make_groups(self) -> None:
        if self._busy:
            return
        if not self._items:
            QMessageBox.information(self, L("Info"), L("Aggiungi prima dei file MKV."))
            return
        self._rebuild_groups_preview(log_message=True)

    def _selected_group(self) -> Optional[ConcatGroup]:
        rows = sorted({i.row() for i in self.tbl_groups.selectedIndexes()})
        if not rows:
            return None
        r = rows[0]
        if 0 <= r < len(self._groups):
            return self._groups[r]
        return None

    def on_merge_selected_group(self) -> None:
        g = self._selected_group()
        if g is None:
            QMessageBox.information(self, L("Info"), L("Seleziona un gruppo da unire."))
            return
        self._start_queue([g])

    def on_merge_all_groups(self) -> None:
        if not self._groups:
            QMessageBox.information(self, L("Info"), L("Prepara prima l'anteprima (gruppi)."))
            return
        self._start_queue(list(self._groups))

    # -------------------- runner --------------------
    def _set_busy(self, v: bool) -> None:
        self._busy = bool(v)
        for w in (
            self.btn_add, self.btn_remove, self.btn_clear, self.btn_sort,
            self.btn_make_groups, self.btn_merge_sel, self.btn_merge_all,
            self.cmb_mode, self.spn_group, self.ed_prefix
        ):
            try:
                w.setEnabled(not self._busy)
            except Exception:
                pass
        self.btn_stop.setEnabled(self._busy)

    def _set_group_status(self, g: ConcatGroup, status: str) -> None:
        g.status = status
        for r in range(len(self._groups)):
            if self._groups[r] is g:
                it = self.tbl_groups.item(r, 5)
                if it is None:
                    self.tbl_groups.setItem(r, 5, self._it(status))
                else:
                    it.setText(status)
                break

    def _start_queue(self, groups: List[ConcatGroup]) -> None:
        if self._busy:
            return
        if self._host_is_busy():
            QMessageBox.information(self, L("Attendi"), L("La MKV Suite sta già eseguendo un'operazione (Estrai/Crea MKV)."))
            return

        out_dir = self._ensure_out_dir()
        if not out_dir:
            self._log("[INFO] Unione annullata: cartella output non scelta.")
            return

        # Salta gruppi da 1 file (utile in automatico con 'resto')
        skipped = [g for g in groups if len(g.items) < 2]
        valid = [g for g in groups if len(g.items) >= 2]
        if skipped:
            for g in skipped:
                self._set_group_status(g, L("saltato (1 file)"))
            self._log(L("[INFO] Alcuni gruppi con 1 solo file sono stati saltati."))
        if not valid:
            QMessageBox.warning(self, L("Errore"), L("Non ci sono gruppi validi da unire (servono almeno 2 file per gruppo)."))
            return

        self._queue = list(valid)
        self.progress.setValue(0)
        self._set_busy(True)
        self._log(f"[RUN] Unione gruppi in: {out_dir}")
        self._run_next()

    def _run_next(self) -> None:
        if not self._queue:
            self.progress.setValue(100)
            self._set_busy(False)
            self._log("[OK] Unione completata.")
            return

        g = self._queue.pop(0)
        out_root = self._ensure_out_dir()
        if not out_root:
            self._set_group_status(g, "annullato")
            self._set_busy(False)
            self._log("[INFO] Operazione annullata.")
            return

        out_name = (g.out_name or "").strip() or f"concat_{g.index:02d}.mkv"
        if not out_name.lower().endswith(".mkv"):
            out_name += ".mkv"
        out_path = out_root / out_name

        mkvmerge_bin = self._mkvmerge_bin()
        inputs = [x.path for x in g.items]
        try:
            cmd = build_append_cmd(mkvmerge_bin, out_path, inputs)
        except Exception as e:
            self._set_group_status(g, "errore")
            self._log(f"[ERR] Gruppo {g.index}: {e}")
            self._run_next()
            return

        if any(x.warning for x in g.items):
            self._log(f"[WARN] Gruppo {g.index}: layout tracce misto, mkvmerge potrebbe fallire.")

        self._set_group_status(g, "in corso")
        self.progress.setValue(0)
        self._proc_buf = ""

        if self._proc is not None:
            try:
                self._proc.kill()
            except Exception:
                pass
            self._proc = None

        p = QProcess(self)
        self._proc = p
        p.setProcessChannelMode(QProcess.MergedChannels)

        def _read():
            if self._proc is None:
                return
            data = bytes(self._proc.readAllStandardOutput()).decode("utf-8", "replace")
            if not data:
                return
            data = data.replace("\r", "\n")
            self._proc_buf += data
            while "\n" in self._proc_buf:
                line, self._proc_buf = self._proc_buf.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                m = self._RX_PROGRESS.search(line)
                if m:
                    try:
                        self.progress.setValue(max(0, min(100, int(m.group(1)))))
                    except Exception:
                        pass

        def _done(code, _status):
            try:
                _read()
            except Exception:
                pass
            if code == 0:
                self.progress.setValue(100)
                self._set_group_status(g, "ok")
                self._log(f"[OK] Gruppo {g.index} -> {out_path.name}")
                self._run_next()
                return
            self._set_group_status(g, f"errore rc={code}")
            self._log(f"[ERR] Gruppo {g.index} fallito (rc={code}).")
            self._run_next()

        p.readyReadStandardOutput.connect(_read)
        p.finished.connect(_done)

        self._log("[RUN] " + " ".join(cmd))
        p.start(cmd[0], cmd[1:])

    def on_stop(self) -> None:
        if not self._busy:
            return
        try:
            if self._proc is not None:
                self._proc.kill()
        except Exception:
            pass
        self._queue = []
        self._set_busy(False)
        self.progress.setValue(0)
        self._log("[STOP] Unione interrotta.")
