#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

"""
srt_ocr.py — Estrazione SRT da VOB usando mencoder + vobsub2srt.

API principali (compat con il vecchio codice):

    extract_srt_for_vob(vob_path, requests, mode="all",
                        status_cb=None, progress_cb=None) -> List[str]

    # alias di compatibilità:
    run_srt_ocr_for_vob(...)    → chiama extract_srt_for_vob(...)
    extract_srt_for_mkv(...)    → chiama extract_srt_for_vob(...)

Dove `requests` è una lista di dict come quelli nel sidecar:
    {
        "index": 0,
        "language": "it",
        "name": "IT — VobSub",
        "reason": "all",
        "target": "/path/Film.it.srt"
    }

Strategia:
  1) Controlla la presenza di mencoder e vobsub2srt.
  2) Usa il sidecar <vob>.ldvdmeta.json per mappare:
       request["index"] → meta["subtitles"][index]["stream_id"] → sid
     dove stream_id è di solito "0x20".."0x27" → sid = int(stream_id, 16) - 0x20.
  3) Per ogni request:
       - mencoder -sid <sid> -vobsubout TMP_BASE   (genera TMP_BASE.idx + TMP_BASE.sub)
       - vobsub2srt TMP_BASE                       (genera TMP_BASE.srt)
       - sposta TMP_BASE.srt su request["target"]
       - pulisce TMP_BASE.idx/.sub (se non servono per debug)
  4) Ritorna la lista dei percorsi .srt effettivamente creati.

Note importanti:
  - BUG FIX: niente più .sub/.idx senza "sidN": ora cerchiamo sempre
      "<tmp_root>/<nome_vob>.sidN.idx" e ".sidN.sub"
    che è quello che genera davvero mencoder.
  - Le opzioni extra per vobsub2srt (tipo --y-threshold 140, --dump-images)
    si passano da env:
        LDVD_VOBSUB2SRT_FLAGS="--y-threshold 140 --dump-images"
  - Le lingue a 2 lettere (it, en, fr, ...) vengono mappate a quelle usate
    di solito da Tesseract (ita, eng, fra, ...).
"""

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import json
import os
import shlex
import shutil
import subprocess

StatusCb = Optional[Callable[[str], None]]
ProgressCb = Optional[Callable[[int], None]]

# ───────────────────────────── Debug ─────────────────────────────

LDVD_DEBUG = os.getenv("LDVD_DEBUG", "0") not in ("", "0", "false", "no", "False", "No")
KEEP_VOBSUB_TMP = os.getenv("LDVD_KEEP_VOBSUB_TMP", "0") not in (
    "",
    "0",
    "false",
    "no",
    "False",
    "No",
)


def _dprint(*a: Any, **k: Any) -> None:
    if LDVD_DEBUG:
        try:
            print("[DVD-Ripper] [OCR]", *a, **k, flush=True)
        except Exception:
            pass


# ──────────────────────── Helper di sistema ───────────────────────


def _have_tool(name: str) -> Optional[str]:
    """Ritorna il path allo strumento se presente in PATH, altrimenti None."""
    path = shutil.which(name)
    _dprint(f"check tool {name!r} -> {path}")
    return path


def _run_cmd(
    cmd: List[str],
    status_cb: StatusCb = None,
    cwd: Optional[Path] = None,
) -> subprocess.CompletedProcess:
    """Esegue un comando esterno, loggando stdout/stderr in debug."""
    cwd_str = str(cwd) if cwd is not None else None
    msg_cmd = " ".join(shlex.quote(x) for x in cmd)
    if cwd_str:
        _dprint(f"Esecuzione comando: {msg_cmd} (cwd: {cwd_str} )")
    else:
        _dprint(f"Esecuzione comando: {msg_cmd}")

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            cwd=cwd_str,
        )
    except Exception as exc:
        msg = f"Errore eseguendo {cmd[0]!r}: {exc}"
        _dprint(msg)
        if status_cb:
            status_cb(msg)
        raise

    if proc.stdout:
        _dprint("stdout:", proc.stdout.strip())
    if proc.stderr:
        _dprint("stderr:", proc.stderr.strip())

    return proc


# ──────────────────────── Sidecar / mapping SID ────────────────────


def _load_sidecar_meta(vob: Path) -> Dict[str, Any]:
    """
    Carica <vob>.ldvdmeta.json se esiste, altrimenti {}.
    Non importa vob_sidecar per evitare dipendenze circolari.
    """
    meta_path = vob.with_suffix(".ldvdmeta.json")
    if not meta_path.is_file():
        _dprint(f"Sidecar non trovato: {meta_path}")
        return {}
    try:
        txt = meta_path.read_text(encoding="utf-8")
        meta = json.loads(txt)
        if isinstance(meta, dict):
            _dprint(f"Sidecar caricato: {meta_path}")
            return meta
        _dprint(f"Sidecar {meta_path} non è un dict JSON valido.")
    except Exception as exc:
        _dprint(f"Impossibile leggere/parlare sidecar {meta_path}: {exc}")
    return {}


def _sid_from_request(req: Dict[str, Any], subs: List[Dict[str, Any]], default_index: int) -> int:
    """
    Ricava il SID DVD da:
      - meta["subtitles"][index]["stream_id"] (tipicamente "0x20".."0x27")
      - oppure da req["sid"]/req["sub_id"], se presente
      - altrimenti usa default_index come fallback.

    Restituisce sempre un intero >= 0.
    """
    sid: Optional[int] = None

    # 1) Prova a usare index nel sidecar
    try:
        idx = int(req.get("index"))
    except Exception:
        idx = -1

    if 0 <= idx < len(subs):
        stream_id = subs[idx].get("stream_id")
        _dprint(f"sid_from_request: index={idx} → stream_id={stream_id!r}")
        if stream_id is not None:
            try:
                s = str(stream_id).strip()
                if s.lower().startswith("0x"):
                    # Es. "0x24" → 0x24 - 0x20 = 4
                    sid = int(s, 16) - 0x20
                else:
                    sid = int(s)
            except Exception as exc:
                _dprint(f"sid_from_request: stream_id {stream_id!r} non parsabile: {exc}")
                sid = None

    # 2) Prova chiavi alternative nella request
    if sid is None:
        for key in ("sid", "sub_id", "subtitle_id"):
            if key in req:
                try:
                    v = int(req[key])
                    if v >= 0:
                        sid = v
                        _dprint(f"sid_from_request: preso da req[{key!r}] = {sid}")
                        break
                except Exception:
                    continue

    # 3) Fallback: default_index
    if sid is None:
        sid = int(default_index)
        _dprint(f"sid_from_request: fallback default_index={default_index} → sid={sid}")

    if sid < 0:
        sid = 0

    return sid


def _map_tesseract_lang(lang: str) -> str:
    """
    Mappa codici lingua brevi (it, en, fr, ...) a quelli usati di solito da Tesseract.
    Se non abbiamo una mappa specifica, ritorna il valore originale.
    """
    if not lang:
        return ""
    lang = lang.lower()

    mapping = {
        "it": "ita",
        "en": "eng",
        "fr": "fra",
        "de": "deu",
        "es": "spa",
        "pt": "por",
        "nl": "nld",
        "el": "ell",
    }
    mapped = mapping.get(lang, lang)
    if mapped != lang:
        _dprint(f"mappa lingua OCR: {lang!r} → {mapped!r}")
    return mapped


def _extra_vobsub2srt_flags() -> List[str]:
    """
    Legge LDVD_VOBSUB2SRT_FLAGS e lo splitta in parametri aggiuntivi
    per vobsub2srt, es:
        export LDVD_VOBSUB2SRT_FLAGS="--y-threshold 140 --dump-images"
    """
    raw = os.getenv("LDVD_VOBSUB2SRT_FLAGS", "").strip()
    if not raw:
        return []
    try:
        parts = shlex.split(raw)
    except Exception as exc:
        _dprint(f"LDVD_VOBSUB2SRT_FLAGS malformato ({raw!r}): {exc}")
        return []
    _dprint(f"Extra flags vobsub2srt da env: {parts}")
    return parts


# ───────────────────── OCR principale per VOB ─────────────────────


def extract_srt_for_vob(
    vob_path: str | Path,
    requests: List[Dict[str, Any]],
    mode: str = "all",
    status_cb: StatusCb = None,
    progress_cb: ProgressCb = None,
) -> List[str]:
    """
    Esegue l’OCR dei sottotitoli partendo da un VOB (o da un file compatibile con mencoder).

    Parametri:
        vob_path    → percorso del .vob
        requests    → lista di richieste SRT (vedi docstring in cima al file)
        mode        → "all" / "hint" / altro (attualmente usato solo per filtrare)
        status_cb   → callback opzionale per messaggi di stato (string)
        progress_cb → callback opzionale per progress (0–100 int)

    Ritorna:
        Lista di percorsi .srt effettivamente creati.
    """
    created: List[str] = []

    vob = Path(vob_path)
    if not vob.exists():
        msg = f"OCR SRT: file sorgente non trovato: {vob}"
        _dprint(msg)
        if status_cb:
            status_cb(msg)
        return created

    requests = list(requests or [])
    if not requests:
        _dprint("OCR SRT: nessuna richiesta SRT (requests vuoto), non faccio nulla.")
        return created

    # 1) Verifica tool esterni
    miss: List[str] = []
    mencoder_path = _have_tool("mencoder")
    if not mencoder_path:
        miss.append("mencoder")
    vobsub2srt_path = _have_tool("vobsub2srt")
    if not vobsub2srt_path:
        miss.append("vobsub2srt")

    if miss:
        msg = f"OCR SRT disabilitato: mancano {', '.join(miss)} (installa i pacchetti relativi)."
        _dprint(msg)
        if status_cb:
            status_cb(msg)
        return created

    # 2) Carica meta per ricavare gli stream_id → sid
    meta = _load_sidecar_meta(vob)
    subs: List[Dict[str, Any]] = list(meta.get("subtitles") or [])

    # 3) Applica il mode ("all" / "hint")
    effective_requests: List[Dict[str, Any]] = []
    if mode == "hint":
        # Se nel sidecar c'è un hint, preferisci quello
        hint = meta.get("srt_hint")
        if isinstance(hint, dict):
            effective_requests = [hint]
            _dprint("OCR SRT: mode=hint, uso srt_hint dal sidecar.")
        elif requests:
            effective_requests = [requests[0]]
            _dprint("OCR SRT: mode=hint, uso la prima request come fallback.")
    else:
        effective_requests = list(requests)
        _dprint(f"OCR SRT: mode={mode!r}, uso tutte le {len(effective_requests)} richieste.")

    total = len(effective_requests)
    if total == 0:
        msg = "OCR SRT: nessuna richiesta effettiva da processare."
        _dprint(msg)
        if status_cb:
            status_cb(msg)
        return created

    # 4) Directory temporanea per i .idx/.sub/.srt intermedi
    tmp_root = Path("/dev/shm/dvd_ripper")
    try:
        tmp_root.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        _dprint(f"Impossibile creare {tmp_root}: {exc}, uso cartella locale .dvd_ocr_tmp")
        tmp_root = vob.parent / ".dvd_ocr_tmp"
        try:
            tmp_root.mkdir(parents=True, exist_ok=True)
        except Exception as exc2:
            _dprint(f"Impossibile creare {tmp_root}: {exc2} (userò comunque questa path)")

    _dprint(f"tmp_root scelto: {tmp_root}")

    if progress_cb:
        try:
            progress_cb(0)
        except Exception:
            pass

    extra_flags = _extra_vobsub2srt_flags()

    # 5) Loop sulle richieste
    for i, req in enumerate(effective_requests, start=1):
        raw_lang = (req.get("language") or req.get("lang") or "").lower()
        t_lang = _map_tesseract_lang(raw_lang)
        target = req.get("target") or ""
        default_index = i - 1

        sid = _sid_from_request(req, subs, default_index=default_index)

        if not target:
            # Fallback se per qualche motivo il sidecar non ha indicato il target
            stem_lang = raw_lang if raw_lang else f"sid{sid}"
            target = str(vob.with_suffix(f".{stem_lang}.srt"))

        target_path = Path(target)

        # Base temporanea (in tmp_root) per idx/sub/srt
        base = tmp_root / f"{vob.stem}.sid{sid}"
        # BUG FIX: niente with_suffix qui, che tagliava ".sidN" e produceva solo ".sub"
        tmp_idx = Path(str(base) + ".idx")
        tmp_sub = Path(str(base) + ".sub")
        tmp_srt = Path(str(base) + ".srt")

        # Pulisce eventuali residui di run precedenti
        for junk in (tmp_idx, tmp_sub, tmp_srt):
            try:
                if junk.exists():
                    junk.unlink()
            except Exception:
                pass

        _dprint(
            f"OCR SRT: richiesta {i}/{total} → sid={sid}, "
            f"lang={raw_lang!r}, t_lang={t_lang!r}, target={target_path}"
        )
        if status_cb:
            status_cb(
                f"OCR SRT: estrazione sottotitoli stream {sid} "
                f"({raw_lang or 'lang sconosciuta'})…"
            )

        # 5.1) mencoder: genera VobSub (.sub + .idx)
        cmd_ext = [
            mencoder_path,
            str(vob),
            "-o",
            os.devnull,
            "-nosound",
            "-ovc",
            "copy",
            "-sid",
            str(sid),
            "-vobsubout",
            str(base),
            "-vobsuboutindex",
            "0",
        ]
        proc_ext = _run_cmd(cmd_ext, status_cb=status_cb, cwd=tmp_root)

        if proc_ext.returncode != 0 or (not tmp_sub.exists()):
            msg = (
                f"OCR SRT: mencoder per sid {sid} ha fallito "
                f"(exit {proc_ext.returncode}) o .sub non trovato ({tmp_sub})."
            )
            _dprint(msg)
            if status_cb:
                status_cb(msg)
            # passa alla prossima richiesta
            continue

        # 5.2) vobsub2srt: OCR vero e proprio
        cmd_ocr = [vobsub2srt_path, str(base)]
        if t_lang:
            cmd_ocr.extend(["--tesseract-lang", t_lang])
        if extra_flags:
            cmd_ocr.extend(extra_flags)

        proc_ocr = _run_cmd(cmd_ocr, status_cb=status_cb, cwd=tmp_root)

        if proc_ocr.returncode != 0 or (not tmp_srt.exists()):
            msg = (
                f"OCR SRT: vobsub2srt per sid {sid} ha fallito "
                f"(exit {proc_ocr.returncode}) o .srt non trovato ({tmp_srt})."
            )
            _dprint(msg)
            if status_cb:
                status_cb(msg)
            # manteniamo i tmp per eventuale debug (non li eliminiamo)
            continue

        # 5.3) Sposta lo SRT nel target finale
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        try:
            shutil.move(str(tmp_srt), str(target_path))
            created.append(str(target_path))
            _dprint(f"Creato SRT: {target_path}")
            if status_cb:
                status_cb(f"OCR SRT: creato {target_path.name}")
        except Exception as exc:
            msg = f"OCR SRT: impossibile spostare {tmp_srt} → {target_path}: {exc}"
            _dprint(msg)
            if status_cb:
                status_cb(msg)

        # 5.4) Pulisce (o conserva) i file VobSub temporanei per questa traccia
        if not KEEP_VOBSUB_TMP:
            for junk in (tmp_sub, tmp_idx):
                try:
                    if junk.exists():
                        junk.unlink()
                except Exception:
                    pass
        else:
            _dprint(
                f"KEEP_VOBSUB_TMP=1 → lascio i VobSub temporanei: "
                f"base={base}"
            )

        # 5.5) aggiorna progress
        if progress_cb:
            try:
                frac = i / total
                val = max(10, min(100, int(frac * 100)))
                progress_cb(val)
            except Exception:
                pass

    # fine loop richieste

    if progress_cb:
        try:
            progress_cb(100)
        except Exception:
            pass

    if created:
        msg = f"OCR SRT completato: generati {len(created)} file .srt."
    else:
        msg = "OCR SRT completato: nessun .srt generato."

    _dprint(msg)
    if status_cb:
        status_cb(msg)

    return created


# ────────────────────── Alias di compatibilità ──────────────────────


def run_srt_ocr_for_vob(
    vob_path: str | Path,
    requests: List[Dict[str, Any]],
    mode: str = "all",
    status_cb: StatusCb = None,
    progress_cb: ProgressCb = None,
) -> List[str]:
    """
    Compat: vecchio nome usato in alcuni punti del codice.
    """
    return extract_srt_for_vob(
        vob_path=vob_path,
        requests=requests,
        mode=mode,
        status_cb=status_cb,
        progress_cb=progress_cb,
    )


def extract_srt_for_mkv(
    *args: Any,
    **kwargs: Any,
) -> List[str]:
    """
    Compat: in vecchie versioni si parlava di MKV, ma ora accettiamo sempre un VOB
    come primo argomento; gli altri parametri sono identici.
    """
    return extract_srt_for_vob(*args, **kwargs)
