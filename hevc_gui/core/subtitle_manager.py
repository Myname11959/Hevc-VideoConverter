# subtitle_manager.py
# ──────────────────────────────────────────────────────────────
# Modulo semplificato per la gestione dei sottotitoli incorporati
# e conversione eventuale dei sottotitoli esterni in UTF-8.
# ──────────────────────────────────────────────────────────────

import subprocess
import json
import tempfile
from pathlib import Path

import chardet

from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QListWidget,
    QHBoxLayout,
    QPushButton,
    QAbstractItemView,
)

from hevc_gui.core import constants as C


class SubtitleManager:
    @staticmethod
    def probe_embedded(input_path: Path) -> list[dict]:
        """
        Usa ffprobe per estrarre i flussi di sottotitoli incorporati.
        Ritorna una lista di dict con 'index', 'language', 'title'.
        """
        cmd = [
            C.FFPROBE_BIN,
            "-v",
            "error",
            "-select_streams",
            "s",
            "-show_entries",
            "stream=index:stream_tags=language,title",
            "-of",
            "json",
            str(input_path),
        ]
        out = subprocess.check_output(cmd)
        info = json.loads(out)
        streams: list[dict] = []
        for s in info.get("streams", []):
            streams.append(
                {
                    "index": s["index"],
                    "language": s.get("tags", {}).get("language", "und"),
                    "title": s.get("tags", {}).get("title", ""),
                }
            )
        return streams

    @staticmethod
    def ensure_utf8(srt_path: Path) -> Path:
        """
        Verifica se il file esterno è in UTF-8; altrimenti lo ricodifica
        in C.TEMP_DIR e restituisce il nuovo Path.
        """
        raw = srt_path.read_bytes()
        enc = chardet.detect(raw).get("encoding") or "utf-8"
        if enc.lower() == "utf-8":
            return srt_path

        text = raw.decode(enc, errors="replace")
        C.TEMP_DIR.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(dir=str(C.TEMP_DIR), suffix=".srt", text=True)
        tmp = Path(temp_name)
        tmp.write_text(text, encoding="utf-8")
        return tmp

    @staticmethod
    def select_embedded_dialog(streams: list[dict], parent=None) -> list[dict]:
        """
        Dialog multi-select per scegliere uno o più flussi incorporati.
        Restituisce la lista dei dict selezionati, o [] se nessuno.
        """
        dlg = QDialog(parent)
        dlg.setWindowTitle("Scegli sottotitoli incorporati")
        layout = QVBoxLayout(dlg)

        listw = QListWidget()
        listw.setSelectionMode(QAbstractItemView.MultiSelection)
        for s in streams:
            label = f"#{s['index']} [{s['language']}] {s['title']}"
            listw.addItem(label)
        layout.addWidget(listw)

        # NEW: doppio clic = conferma (OK)
        def _on_dblclick(item):
            # in MultiSelection, assicuriamoci che l’item doppio-cliccato risulti selezionato
            try:
                if item and not item.isSelected():
                    item.setSelected(True)
            except Exception:
                pass
            dlg.accept()

        listw.itemDoubleClicked.connect(_on_dblclick)

        btns = QHBoxLayout()
        ok = QPushButton("OK")
        cancel = QPushButton("Annulla")
        ok.clicked.connect(dlg.accept)
        cancel.clicked.connect(dlg.reject)
        btns.addStretch()
        btns.addWidget(ok)
        btns.addWidget(cancel)
        layout.addLayout(btns)

        if dlg.exec_() == QDialog.Accepted:
            selected = []
            for item in listw.selectedItems():
                idx = listw.row(item)
                selected.append(streams[idx])
            return selected
        return []
