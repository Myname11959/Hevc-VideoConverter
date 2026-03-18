#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QMessageBox

from hevc_gui.mkv_suite.i18n import L
try:
    from hevc_gui.mkv_suite.i18n import L
except Exception:
    def L(s: str) -> str:
        return s

from hevc_gui.mkv_suite.ui.concat_batch_dialog import ConcatBatchDialog


class ConcatBatchTab(QWidget):
    """
    Scheda-lancio minimale.
    Lo strumento vero 'Unisci episodi' si apre in una finestra separata
    (più comoda da usare dentro la MKV Suite).
    """
    def __init__(self, host=None, parent=None):
        super().__init__(parent)
        self.host = host
        self._dlg = None
        self._build_ui()

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        title = QLabel(L("Unisci episodi"))
        f = title.font()
        try:
            f.setBold(True)
            f.setPointSize(max(f.pointSize(), 11))
            title.setFont(f)
        except Exception:
            pass
        lay.addWidget(title)

        info = QLabel(
            L(
                "Questo strumento si apre in una finestra separata, "
                "così hai più spazio per lavorare (file, gruppi, anteprima e log)."
            )
        )
        info.setWordWrap(True)
        lay.addWidget(info)

        info2 = QLabel(
            L(
                "Usa la finestra dedicata per unire più MKV in sequenza senza ricodifica, "
                "in automatico oppure con Gruppi manuali."
            )
        )
        info2.setWordWrap(True)
        lay.addWidget(info2)

        row = QHBoxLayout()
        self.btn_open = QPushButton(L("Apri finestra Unisci episodi"))
        self.btn_open.setMinimumHeight(34)
        self.btn_open.setMinimumWidth(260)
        self.btn_open.setToolTip(L("Apre lo strumento completo in una finestra separata."))
        row.addWidget(self.btn_open)
        row.addStretch(1)
        lay.addLayout(row)

        hint = QLabel(
            L(
                "Suggerimento: lascia aperta la finestra dedicata mentre lavori, "
                "così qui la scheda resta pulita e semplice."
            )
        )
        hint.setWordWrap(True)
        lay.addWidget(hint)

        lay.addStretch(1)

        self.btn_open.clicked.connect(self.on_open_dialog)

    def _ensure_dialog(self):
        if self._dlg is None:
            # parent = finestra principale, host = main widget MKV Suite
            parent_win = self.window()
            self._dlg = ConcatBatchDialog(host=self.host, parent=parent_win)
            try:
                self._dlg.setWindowModality(Qt.NonModal)
            except Exception:
                pass
            # Se l'utente chiude la finestra, azzera il riferimento
            try:
                self._dlg.destroyed.connect(self._on_dialog_destroyed)
            except Exception:
                pass
        return self._dlg

    def _on_dialog_destroyed(self, *_args):
        self._dlg = None

    def on_open_dialog(self) -> None:
        try:
            dlg = self._ensure_dialog()
            dlg.show()
            try:
                dlg.raise_()
                dlg.activateWindow()
            except Exception:
                pass
        except Exception as e:
            try:
                if self.host is not None and hasattr(self.host, "_log"):
                    self.host._log(f"[ERR] Apertura finestra 'Unisci episodi' fallita: {e}")
            except Exception:
                pass
            QMessageBox.warning(self, L("Errore"), L("Impossibile aprire la finestra 'Unisci episodi'."))
