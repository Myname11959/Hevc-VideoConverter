# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import shutil
from pathlib import Path

from PyQt5.QtCore import QObject, QProcess
from PyQt5.QtWidgets import QMessageBox, QFileDialog, QProgressDialog

TEXT_CODEC_TO_EXT = {
    "S_TEXT/UTF8": "srt",
    "S_TEXT/ASS": "ass",
    "S_TEXT/SSA": "ssa",
    "S_TEXT/USF": "usf",
    "S_TEXT/WEBVTT": "vtt",
}

SUPPORTED_EXT = {".srt", ".ass", ".ssa", ".vtt", ".sub", ".txt"}

def _which(cmd: str) -> str:
    return shutil.which(cmd) or ""

def _is_probably_text_sub_codec(codec_id: str) -> bool:
    cid = (codec_id or "").strip().upper()
    return cid.startswith("S_TEXT/")

def _ext_for_codec(codec_id: str) -> str:
    cid = (codec_id or "").strip().upper()
    return TEXT_CODEC_TO_EXT.get(cid, "srt")

def _safe_mkdir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

class GnomeSubtitlesEditor(QObject):
    """
    Bridge semplice:
      - individua riga subs
      - estrae la traccia (se interna)
      - apre gnome-subtitles
      - default: non distruttivo (copia *_edit.ext)
      - SHIFT+doppio click: sovrascrive (edit in-place)
    """
    def __init__(self, parent=None, mkvextract_bin: str = "mkvextract"):
        super().__init__(parent)
        self.parent_widget = parent
        self.mkvextract_bin = mkvextract_bin
        self._proc_extract: QProcess | None = None
        self._proc_editor: QProcess | None = None
        self._busy: QProgressDialog | None = None
        self.last_opened_target: Path | None = None
        self.last_job_dir: Path | None = None

    # ------------------------ UI/model helpers -------------------------------
    def _header_map(self, model) -> dict:
        # headerData might return localized strings (Tipo/Type ecc.)
        cols = model.columnCount()
        out = {}
        for c in range(cols):
            h = model.headerData(c, 1)  # Qt.Horizontal == 1
            if h is None:
                continue
            s = str(h).strip().lower()
            out[s] = c
        return out

    def is_subtitle_row(self, model, row: int) -> bool:
        hmap = self._header_map(model)
        # try Type/Tipo column
        for key in ("type", "tipo", "track type", "tipo traccia"):
            if key in hmap:
                v = model.index(row, hmap[key]).data()
                s = str(v).strip().lower()
                if "sub" in s or "sott" in s:
                    return True
        # fallback: scan some cells
        cols = min(model.columnCount(), 8)
        for c in range(cols):
            v = model.index(row, c).data()
            s = str(v).strip().lower()
            if "subtitles" in s or "sottotit" in s:
                return True
        return False

    def extract_track_id(self, model, row: int) -> int | None:
        hmap = self._header_map(model)
        for key in ("id", "#", "track id", "id traccia"):
            if key in hmap:
                v = model.index(row, hmap[key]).data()
                try:
                    return int(str(v).strip())
                except Exception:
                    pass
        # fallback: find first pure int cell
        cols = min(model.columnCount(), 6)
        for c in range(cols):
            v = model.index(row, c).data()
            s = str(v).strip()
            if s.isdigit():
                return int(s)
        return None

    def extract_codec_id(self, model, row: int) -> str:
        hmap = self._header_map(model)
        for key in ("codec", "codec id", "formato", "tipo codec"):
            if key in hmap:
                v = model.index(row, hmap[key]).data()
                s = str(v).strip()
                if s:
                    return s
        return ""

    def find_path_in_row(self, model, row: int) -> str:
        # if row contains an external subtitle path, we can open it directly
        cols = model.columnCount()
        for c in range(cols):
            v = model.index(row, c).data()
            s = str(v).strip()
            if not s:
                continue
            if ("/" in s or s.startswith("~")) and len(s) > 4:
                p = Path(os.path.expanduser(s))
                if p.is_file() and p.suffix.lower() in SUPPORTED_EXT:
                    return str(p)
        return ""

    def _walk_attr(self, w, names):
        cur = w
        while cur is not None:
            for n in names:
                if hasattr(cur, n):
                    val = getattr(cur, n)
                    if isinstance(val, (str, Path)) and str(val):
                        return str(val)
            cur = cur.parent() if hasattr(cur, "parent") else None
        return ""

    def guess_current_source_path(self, widget) -> str:
        # best-effort: common attribute names
        return self._walk_attr(widget, [
            "_current_source_path", "current_source_path",
            "_source_path", "source_path",
            "_current_input", "current_input",
            "_selected_source", "selected_source",
        ])

    def guess_job_dir(self, widget) -> str:
        return self._walk_attr(widget, [
            "_job_dir", "job_dir",
            "_output_dir", "output_dir",
            "out_dir", "_out_dir",
        ])

    # ------------------------ editor launching -------------------------------
    def _resolve_gnome_subtitles_cmd(self) -> list[str] | None:
        exe = _which("gnome-subtitles")
        if exe:
            return [exe]
        flatpak = _which("flatpak")
        if flatpak:
            # Try flatpak app id (best effort)
            # If not installed, flatpak run will fail -> we warn
            return [flatpak, "run", "org.gnome.GnomeSubtitles"]
        return None

    def _ensure_job_dir(self, job_dir_hint: str) -> Path | None:
        if job_dir_hint:
            p = Path(job_dir_hint).expanduser()
            if p.is_dir():
                for sub in ("extract", "chapters", "remux"):
                    _safe_mkdir(p / sub)
                self.last_job_dir = p
                return p

        d = QFileDialog.getExistingDirectory(self.parent_widget, "Scegli cartella OUTPUT (job)", "")
        if not d:
            return None
        p = Path(d)
        for sub in ("extract", "chapters", "remux"):
            _safe_mkdir(p / sub)
        self.last_job_dir = p
        return p

    def _warn(self, title: str, msg: str) -> None:
        QMessageBox.warning(self.parent_widget, title, msg)

    def _info(self, title: str, msg: str) -> None:
        QMessageBox.information(self.parent_widget, title, msg)

    def edit_external_file(self, subtitle_path: str, job_dir_hint: str, overwrite: bool) -> None:
        self.last_opened_target = None
        cmd = self._resolve_gnome_subtitles_cmd()
        if not cmd:
            self._warn("gnome-subtitles non trovato",
                       "Installa gnome-subtitles (Mint/Ubuntu: sudo apt install gnome-subtitles)\n"
                       "Oppure via Flatpak.")
            return

        src = Path(subtitle_path).expanduser()
        if not src.is_file():
            self._warn("File non trovato", f"Impossibile aprire:\n{src}")
            return

        if overwrite:
            target = src
        else:
            job = self._ensure_job_dir(job_dir_hint)
            if not job:
                return
            target = job / "extract" / (src.stem + "_edit" + src.suffix)
            if not target.exists():
                shutil.copy2(src, target)

        self.last_opened_target = Path(target)
        self._launch_editor(cmd, target)

    def edit_internal_track(self, source_path: str, track_id: int, codec_id: str,
                            job_dir_hint: str, overwrite: bool) -> None:
        cmd = self._resolve_gnome_subtitles_cmd()
        if not cmd:
            self._warn("gnome-subtitles non trovato",
                       "Installa gnome-subtitles (Mint/Ubuntu: sudo apt install gnome-subtitles)\n"
                       "Oppure via Flatpak.")
            return

        src = Path(source_path).expanduser()
        if not src.is_file():
            self._warn("Sorgente non trovata", f"File MKV non trovato:\n{src}")
            return

        if codec_id and not _is_probably_text_sub_codec(codec_id):
            self._warn("Sottotitolo non modificabile",
                       f"Questa traccia sembra non testuale (codec: {codec_id}).\n"
                       "gnome-subtitles lavora bene con sottotitoli testuali (SRT/ASS/SSA/VTT).")
            return

        job = self._ensure_job_dir(job_dir_hint)
        if not job:
            return

        ext = _ext_for_codec(codec_id)
        base = src.stem
        out_extract = job / "extract" / f"{base}_T{track_id}_e.{ext}"
        out_edit = out_extract if overwrite else job / "extract" / f"{base}_T{track_id}_edit.{ext}"
        self.last_opened_target = Path(out_edit)

        # if already extracted, skip extraction
        if out_extract.exists():
            if (not overwrite) and (not out_edit.exists()):
                shutil.copy2(out_extract, out_edit)
            self._launch_editor(cmd, out_edit)
            return

        mkvextract = _which(self.mkvextract_bin) or self.mkvextract_bin
        self._proc_extract = QProcess(self.parent_widget)
        self._proc_extract.setProgram(mkvextract)
        self._proc_extract.setArguments(["tracks", str(src), f"{track_id}:{out_extract}"])

        self._busy = QProgressDialog("Estrazione sottotitolo...", "Stop", 0, 0, self.parent_widget)
        self._busy.setWindowTitle("MKV Suite")
        self._busy.setMinimumDuration(0)
        self._busy.canceled.connect(lambda: self._proc_extract.kill() if self._proc_extract else None)
        self._busy.show()

        def _done(exitCode, exitStatus):
            if self._busy:
                self._busy.close()
                self._busy = None

            if not out_extract.exists():
                self._warn("Estrazione fallita",
                           "mkvextract non ha prodotto il file sottotitolo.\n"
                           "Controlla che MKVToolNix sia installato e la traccia sia valida.")
                return

            if (not overwrite) and (not out_edit.exists()):
                shutil.copy2(out_extract, out_edit)

            self._launch_editor(cmd, out_edit)

        self._proc_extract.finished.connect(_done)
        self._proc_extract.start()

    def _launch_editor(self, base_cmd: list[str], file_path: Path) -> None:
        # Launch gnome-subtitles asynchronously
        self._proc_editor = QProcess(self.parent_widget)
        self._proc_editor.setProgram(base_cmd[0])
        self._proc_editor.setArguments(base_cmd[1:] + [str(file_path)])

        # If flatpak app isn't installed, QProcess will end quickly -> show hint
        def _finished(exitCode, exitStatus):
            if base_cmd[0].endswith("flatpak") and exitCode != 0:
                self._warn("Flatpak",
                           "Sembra che org.gnome.GnomeSubtitles non sia installato.\n"
                           "Prova:\n  flatpak install flathub org.gnome.GnomeSubtitles")
            # no forced message after normal close: user already saved inside editor

        self._proc_editor.finished.connect(_finished)
        self._proc_editor.start()
