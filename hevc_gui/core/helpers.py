# -*- coding: utf-8 -*-
"""
Funzioni di supporto usate dalla GUI e da altri moduli.
"""

import shlex
from pathlib import Path
from datetime import datetime

# importa le costanti dal package hevc_gui.core
from hevc_gui.core import constants as C
import shutil
from typing import List, Dict
from .constants import TMP_DIR, FFMPEG_BIN

# IMPORT AGGIUNTO: serve a build_audio_cmds()
from .audio_helpers import audio_tracks_with_title


def build_filterchain(filters: list[str]) -> list[str]:
    """
    Ritorna ['-vf', 'f1,f2,…'] oppure [] se la lista è vuota.
    """
    chain = ",".join([f for f in filters if f])
    return ["-vf", chain] if chain else []


def make_logfile(cmd: list[str]) -> Path:
    """
    Scrive il comando FFmpeg in un file LOG_YYYYMMDD_HHMMSS.txt
    dentro la cartella temporanea e restituisce Path al file.
    """
    C.TEMP_DIR.mkdir(exist_ok=True)
    log = C.TEMP_DIR / f"LOG_{datetime.now():%Y%m%d_%H%M%S}.txt"
    log.write_text(" ".join(shlex.quote(c) for c in cmd), encoding="utf-8")
    return log


def cleanup_temp(remove_all: bool = False):
    """
    Pulisce la directory temporanea C.TEMP_DIR:
      • rimuove tutti i file
      • rimuove ricorsivamente tutte le sottocartelle
      • se remove_all=True prova anche a eliminare la cartella principale (se vuota)
    """
    tmp = C.TEMP_DIR
    if not tmp.exists():
        return

    for entry in tmp.iterdir():
        try:
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink(missing_ok=True)
        except Exception:
            pass

    if remove_all:
        try:
            tmp.rmdir()
        except OSError:
            pass


def build_audio_cmds(src: str) -> list[tuple[Path, list[str]]]:
    """
    Per ogni traccia audio individuata con ffprobe:
      - crea il comando di estrazione ffmpeg
      - restituisce (Path_output, cmd_list)
    """
    cmds: list[tuple[Path, list[str]]] = []
    for idx, _ in audio_tracks_with_title(src):  # indice globale
        out = Path(TMP_DIR) / f"audio_track{idx}.m4a"
        cmd = [
            FFMPEG_BIN,
            "-y",
            "-i",
            src,
            "-map",
            f"0:{idx}",
            "-c:a",
            "copy",
            str(out),
        ]
        cmds.append((out, cmd))
    return []  # TODO: implementare e restituire la lista di argomenti


# ------------------------------------------------------------------------
def ensure_tmp() -> None:
    """
    Crea la directory temporanea se non esiste.
    """
    TMP_DIR.mkdir(parents=True, exist_ok=True)


# -----------------------------------------------------------------------
def get_base_name(path: str | Path) -> str:
    """
    Restituisce lo stem (nome senza estensione) di un file.
    """
    return Path(path).stem


def extract_audio_titles(raw_audio_opts: List[List[str]]) -> List[str]:
    """
    Dato raw_audio_opts = [[...,'title=Italiano...',...], [...,'title=English...',...],...]
    estrae e restituisce ['Italiano...', 'English...', …].
    """
    titles: List[str] = []
    for opts in raw_audio_opts:
        for o in opts:
            if o.startswith("title="):
                titles.append(o.split("=", 1)[1])
                break
    return titles


# ----------------------------------------------------------------------
def build_full_ffmpeg_cmd(
    input_file: Path,
    output_file: Path,
    video_tmp: Path,
    audio_opts: List[List[str]],
    subtitle_infos: List[Dict],
    chapter_opts: List[str],
) -> List[str]:
    """
    Raggruppa in un solo comando FFmpeg:
      - ricodifica video (video_tmp)
      - ricodifica audio (audio_opts pre-convertiti in file .m4a)
      - include sottotitoli interni/esterni (subtitle_infos)
      - include capitoli (chapter_opts)
    Restituisce la lista di argomenti pronta per QProcess o per salvare in coda.
    """
    # qui dentro chiami build_ffmpeg_mux_cmd e prima assicuri che i file audio esistano

    # ... replica tutta la logica di build_ffmpeg_mux_cmd da MainWindow ...
    return []  # TODO: implementare e restituire la lista di argomenti
