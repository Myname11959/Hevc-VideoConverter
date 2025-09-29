# subtitle_helper.py
# ─────────────────────────────────────────────────────────────────────
# Wizard per la gestione dei sottotitoli:
#
# • riconosce gli stream incorporati nel video (via SubtitleManager)
# • permette di scegliere Lingua + Tipo (normal / forced / sdh) per
#   ciascun sottotitolo
# • consente di aggiungere un file esterno (.srt / .ass) se il
#   video non ne contiene
# • riempie in MainWindow i campi:
#       _subtitle_inputs   (solo Path per file esterni)
#       _subtitle_langs    (codici ISO – es. 'ita', 'eng', 'und')
#       _subtitle_types    ('normal', 'forced', 'sdh', …)
#       _subtitle_opts     (solo coppie "-map spec" o "-i file")
#       _subtitle_out_opts (-disposition …)
# ─────────────────────────────────────────────────────────────────────

import tempfile
from pathlib import Path
from typing import Tuple

import chardet

from PyQt5.QtWidgets import (
    QDialog,
    QFormLayout,
    QComboBox,
    QDialogButtonBox,
    QFileDialog,
)

from hevc_gui.core import constants as C
from hevc_gui.core.subtitle_manager import (
    SubtitleManager as sman,
)  # <—— qui il nuovo import

# Mappa tipo → ffmpeg disposition
KIND_MAP = {
    "normal": None,
    "default": "default",
    "forced": "forced",
    "sdh": "sdh",
    "commentary": "comment",
    "karaoke": "karaoke",
}


def ensure_utf8(srt_path: Path, temp_dir: Path) -> Path:
    """
    Se il file non è UTF-8, lo ricodifica e restituisce il path del nuovo file.
    """
    raw = srt_path.read_bytes()
    enc = chardet.detect(raw).get("encoding") or "utf-8"
    if enc.lower() == "utf-8":
        return srt_path

    text = raw.decode(enc, errors="replace")
    temp_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkstemp(dir=str(temp_dir), suffix=srt_path.suffix)[1])
    tmp.write_text(text, encoding="utf-8")
    return tmp


class SubTagDialog(QDialog):
    """
    Dialog per scegliere lingua + tipo (normal, forced, sdh…) per un sottotitolo.
    """

    def __init__(self, parent=None, pre_lang: str = "und"):
        super().__init__(parent)
        self.setWindowTitle("Sottotitolo")
        lay = QFormLayout(self)

        self.cmb_lang = QComboBox()
        self.cmb_lang.addItem("Unknown", "und")
        for code, full in sorted(C.LANGUAGE_NAMES.items()):
            self.cmb_lang.addItem(f"{full} ({code})", code.lower())
        idx = self.cmb_lang.findData(pre_lang.lower())
        if idx >= 0:
            self.cmb_lang.setCurrentIndex(idx)
        lay.addRow("Lingua:", self.cmb_lang)

        self.cmb_kind = QComboBox()
        self.cmb_kind.addItems(list(KIND_MAP.keys()))
        lay.addRow("Tipo:", self.cmb_kind)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def result(self) -> Tuple[str, str]:
        return self.cmb_lang.currentData(), self.cmb_kind.currentText()


def select_subtitles(main_win) -> None:
    """
    Procedura di selezione sottotitoli:
    - Azzera i campi sottotitoli della MainWindow
    - Propone selezione multipla per sottotitoli incorporati
    - Consente di aggiungere sottotitoli esterni (più volte)
    - Popola tutti i campi: inputs, langs, types, opts, out_opts
    """
    mw = main_win

    # Reset dei campi
    mw._subtitle_inputs.clear()
    mw._subtitle_opts.clear()
    mw._subtitle_langs.clear()
    mw._subtitle_types.clear()
    mw._subtitle_out_opts.clear()

    # ────────────── Embedded ──────────────
    streams = sman.probe_embedded(mw._current_file)
    if streams:
        sels = sman.select_embedded_dialog(streams, parent=mw)
        if sels:
            for s in sels:
                spec = f"0:{s['index']}"
                pre_lang = s.get("language", "und")
                mw._subtitle_opts += ["-map", spec]
                dlg = SubTagDialog(mw, pre_lang=pre_lang)
                if dlg.exec_() == QDialog.Accepted:
                    lang, kind = dlg.result()
                    mw._subtitle_langs.append(lang or pre_lang)
                    mw._subtitle_types.append(kind)

    # ────────────── Esterni (loop multiplo) ──────────────
    while True:
        path, _ = QFileDialog.getOpenFileName(
            mw,
            "Seleziona file di sottotitoli esterni",
            str(mw._current_file.parent),
            "SubRip (*.srt);;ASS (*.ass);;Tutti i file (*)",
        )
        if not path:
            break  # interrotto

        fixed_path = ensure_utf8(Path(path), C.TEMP_DIR)
        mw._subtitle_inputs.append(fixed_path)
        mw._subtitle_opts += ["-i", str(fixed_path)]

        dlg = SubTagDialog(mw, pre_lang="und")
        if dlg.exec_() == QDialog.Accepted:
            lang, kind = dlg.result()
            mw._subtitle_langs.append(lang)
            mw._subtitle_types.append(kind)
        else:
            mw._subtitle_inputs.pop()
            continue

    # ────────────── Nessun sottotitolo → esci ──────────────
    if not mw._subtitle_types:
        mw.txt_info.append("! Nessun sottotitolo aggiunto.")
        return

    # ────────────── Costruzione flag -disposition ──────────────
    for idx, kind in enumerate(mw._subtitle_types):
        flag = KIND_MAP.get(kind)
        if flag:
            mw._subtitle_out_opts += [f"-disposition:s:{idx}", flag]

    # ────────────── UI update ──────────────
    mw.txt_info.append(f"> Sottotitoli: {len(mw._subtitle_types)} tracce selezionate")
    mw.btn_chapter.setEnabled(True)
    mw.btn_copy_log.setEnabled(False)
