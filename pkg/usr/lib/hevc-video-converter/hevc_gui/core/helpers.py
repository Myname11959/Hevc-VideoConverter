# -*- coding: utf-8 -*-
"""
Funzioni di supporto usate dalla GUI e da altri moduli.
"""

from __future__ import annotations

import shlex
import shutil
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple

# importa le costanti dal package hevc_gui.core
from hevc_gui.core import constants as C
from .constants import TMP_DIR, FFMPEG_BIN

# IMPORT AGGIUNTO: serve a build_audio_cmds()
from .audio_helpers import audio_tracks_with_title


# ─────────────────────────────────────────────────────────────────────────────
# Filtri: utility generiche (usabili per -vf e -af)
# ─────────────────────────────────────────────────────────────────────────────

def _norm_label(label: Optional[str]) -> str:
    """
    Normalizza un'etichetta UI in stile 'Moderato', 'Intermedio+', ecc.
    Esempi:
      '  moderato  ' -> 'Moderato'
      'intermedio+'  -> 'Intermedio+'
    """
    if not label:
        return ""
    return " ".join(w[:1].upper() + w[1:] for w in str(label).strip().split())


def select_sharpness_expr(label: Optional[str]) -> Optional[str]:
    """
    Dall'etichetta UI (chiave di C.SHARPNESS_LEVELS) restituisce l'espressione 'unsharp=...'
    oppure None se 'Nessuno'/vuoto/sconosciuto.
    """
    key = _norm_label(label)
    expr = C.SHARPNESS_LEVELS.get(key, "")
    return expr or None


def select_reverb_expr(label: Optional[str]) -> Optional[str]:
    """
    Dall'etichetta UI (chiave di C.AUD_REVERB_MAP) restituisce l'espressione 'aecho=...'
    oppure None se 'Nessuno'/vuoto/sconosciuto.
    """
    key = _norm_label(label)
    return C.AUD_REVERB_MAP.get(key)  # già None per "Nessuno"


def join_filters(filters: List[Optional[str]]) -> Optional[str]:
    """
    Concatena una lista di espressioni filtro in una singola chain separata da virgole.
    Ignora None/''.
    """
    parts = [f for f in (filters or []) if f]
    return ",".join(parts) if parts else None


def add_filter_arg(argv: List[str], flag: str, expr: Optional[str], for_shell: bool) -> None:
    """
    Aggiunge -vf/-af a argv.
    - for_shell=True  → racchiude l'espressione tra doppi apici (serve per i '|' del reverb).
    - for_shell=False → nessuna quote (lista token per QProcess/subprocess).
    """
    if not expr:
        return
    argv.append(flag)
    if for_shell:
        safe = expr.replace('"', r'\"')
        argv.append(f"\"{safe}\"")
    else:
        argv.append(expr)


def render_shell_command(argv: List[str]) -> str:
    """
    Converte argv (lista token) in stringa shell-safe.
    Se un token è già tra "..." (prodotto da add_filter_arg(..., for_shell=True)),
    lo lascia com'è; gli altri vengono quotati con shlex.quote.
    """
    out: List[str] = []
    for tok in argv:
        if len(tok) >= 2 and tok[0] == '"' and tok[-1] == '"':
            out.append(tok)
        else:
            out.append(shlex.quote(tok))
    return " ".join(out)


def build_filterchain(filters: List[str]) -> List[str]:
    """
    Ritorna ['-vf', 'f1,f2,…'] oppure [] se la lista è vuota.
    (Compat: usata in vari punti esistenti per la catena video.)
    """
    chain = ",".join([f for f in filters if f])
    return ["-vf", chain] if chain else []


def vf_from_parts(resize_expr: str = "", sharpness_label: str = "") -> List[str]:
    """
    Helper comodo: costruisce direttamente ['-vf', '...'] partendo da
    - resize_expr (es. 'scale=1280:720' oppure '')
    - sharpness_label (es. 'Intermedio', 'Moderato+', 'Nessuno')
    """
    chain: List[str] = []
    if resize_expr and resize_expr.strip():
        chain.append(resize_expr.strip())
    sharp = select_sharpness_expr(sharpness_label)
    if sharp:
        chain.append(sharp)
    return ["-vf", ",".join(chain)] if chain else []


def af_from_parts(
    eq_expr: str = "",
    reverb_label: str = "",
    dialog_boost_on: bool = False,
    for_shell: bool = False,
) -> List[str]:
    """
    Helper comodo: costruisce direttamente ['-af', '...'] (o ['-af', '"..."'] se for_shell=True)
    unendo eventuale EQ, Dialog Boost e Reverb (da constants).
    """
    chain: List[str] = []
    if eq_expr and eq_expr.strip():
        chain.append(eq_expr.strip())
    if dialog_boost_on:
        chain.append(C.AUD_DIALOG_BOOST_EQ)
    rv = select_reverb_expr(reverb_label)
    if rv:
        chain.append(rv)

    expr = ",".join(chain) if chain else ""
    if not expr:
        return []
    if for_shell:
        safe = expr.replace('"', r'\"')
        return ["-af", f"\"{safe}\""]
    return ["-af", expr]


# ─────────────────────────────────────────────────────────────────────────────
# Log & tmp
# ─────────────────────────────────────────────────────────────────────────────

def make_logfile(cmd: List[str]) -> Path:
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


def ensure_tmp() -> None:
    """
    Crea la directory temporanea se non esiste.
    """
    TMP_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# Utility path/testo
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# FFmpeg: estrazioni/mux (stub utili che puoi estendere)
# ─────────────────────────────────────────────────────────────────────────────

def build_audio_cmds(src: str) -> List[Tuple[Path, List[str]]]:
    """
    Per ogni traccia audio individuata con ffprobe:
      - crea il comando di estrazione ffmpeg
      - restituisce [(Path_output, cmd_list), ...]
    NOTE:
      • al momento usa -c:a copy e salva in .m4a -> cambia estensione/codec se serve.
      • ritorna la lista (fix del TODO esistente).
    """
    cmds: List[Tuple[Path, List[str]]] = []
    for idx, _ in audio_tracks_with_title(src):  # indice globale
        out = Path(TMP_DIR) / f"audio_track{idx}.m4a"
        cmd = [
            FFMPEG_BIN,
            "-y",
            "-i", src,
            "-map", f"0:{idx}",
            "-c:a", "copy",
            str(out),
        ]
        cmds.append((out, cmd))
    return cmds  # ← fix: prima tornava []


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
      - ricodifica video (video_tmp già pronto o da generare)
      - ricodifica/inserimento audio (audio_opts già convertiti o da mappare)
      - include sottotitoli (subtitle_infos)
      - include capitoli (chapter_opts)
    Restituisce la lista di argomenti pronta per QProcess o per salvare in coda.

    NOTA: è uno scheletro minimal che puoi completare con le tue regole di mapping.
    """
    argv: List[str] = [C.FFMPEG_BIN, "-y"]

    # Input principale
    argv += ["-i", str(input_file)]

    # Video: se hai già un temporaneo (video_tmp), mappalo; altrimenti lascia copy come segnaposto
    if video_tmp and video_tmp.exists():
        argv += ["-i", str(video_tmp)]
        # Map video dal tmp (stream 1:v:0) e copia (o imposta codec altrove)
        argv += ["-map", "1:v:0", "-c:v", "copy"]
    else:
        # fallback: usa il video dell'input (adatta poi in builder reale)
        argv += ["-map", "0:v:0", "-c:v", "copy"]

    # Audio: se audio_opts contiene percorsi già convertiti, aggiungili come input
    # (questo blocco è volutamente semplice; nel tuo builder reale farai mapping/ordini/tag)
    ext_audio_inputs: List[Path] = []
    for opts in audio_opts or []:
        # se opts contiene un path finale (ultimo token), prova ad aggiungerlo come input
        maybe_path = opts[-1] if opts else ""
        p = Path(str(maybe_path))
        if p.exists():
            argv += ["-i", str(p)]
            ext_audio_inputs.append(p)

    # Map audio: input 0 (sorgente) + eventuali input esterni
    # (di default copiamo tutte le tracce presenti per mostrare la struttura; adatta tu i -map)
    argv += ["-map", "0:a?", "-c:a", "copy"]  # il '?' evita errore se manca audio

    # Sottotitoli (placeholder): se hai subs esterni aggiungili come input + map
    for info in (subtitle_infos or []):
        sub_path = Path(str(info.get("path", "")))
        if sub_path.exists():
            argv += ["-i", str(sub_path)]
            # esempio semplice: mappa tutto come copy
            argv += ["-map", f"{len(ext_audio_inputs)+2}:s?", "-c:s", "copy"]  # best effort

    # Capitoli: se hai un file OGM/Matroska chapters.txt, in ffmpeg puoi dare -map_chapters
    for ch in (chapter_opts or []):
        chp = Path(str(ch))
        if chp.exists():
            argv += ["-map_chapters", str(chp)]

    # Output
    argv += [str(output_file)]
    return argv
