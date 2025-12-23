#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# subtitle_manager.py
# ──────────────────────────────────────────────────────────────
# Modulo semplificato per la gestione dei sottotitoli incorporati
# e conversione eventuale dei sottotitoli esterni in UTF-8.
# Ora usa il sidecar LDVD (<basename>.ldvdmeta.json) se presente
# per avere lingue, nomi e *kind* (normal/forced/sdh/…) più sensati
# e mostra anche il codec (VobSub/PGS/SubRip/…) nella lista iniziale.
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


# ──────────────────────────────────────────────────────────────
# Helper vari
# ──────────────────────────────────────────────────────────────

def _ldvd_sidecar_path_for(path: Path) -> Path:
    """/percorso/FILE.ext → /percorso/FILE.ldvdmeta.json"""
    base = Path(path)
    return base.with_suffix(".ldvdmeta.json")


def _load_ldvd_sidecar(path: Path) -> dict | None:
    """
    Prova a caricare il sidecar LDVD (<basename>.ldvdmeta.json).
    Restituisce il dict oppure None se assente/non valido.
    """
    side = _ldvd_sidecar_path_for(path)
    try:
        if side.is_file():
            txt = side.read_text(encoding="utf-8")
            data = json.loads(txt)
            print(f"[SUBS] Sidecar LDVD rilevato: {side}", flush=True)
            return data
    except Exception as e:
        print(f"[SUBS] Errore lettura sidecar {side}: {e}", flush=True)
    return None


def _norm_lang(lang: str) -> str:
    """
    Normalizza un codice lingua in qualcosa di “sensato”:
      - tutto lowercase
      - se vuoto → 'und'
      - prova a ricondurre 'it', 'italian', ecc. → 'ita', 'en' → 'eng', …
    """
    if not lang:
        return "und"
    s = str(lang).strip().lower()
    if not s:
        return "und"

    # già ISO-639-2
    if len(s) == 3:
        return s

    # mapping semplici e robusti
    if s in {"it", "ita", "italian", "italiano"}:
        return "ita"
    if s in {"en", "eng", "english"}:
        return "eng"
    if s in {"fr", "fra", "fre", "french", "francais", "français"}:
        return "fra"
    if s in {"de", "ger", "deu", "german", "deutsch"}:
        return "deu"
    if s in {"es", "spa", "spanish", "español"}:
        return "spa"

    # fallback: se è tipo 'ita (Italiano)' → prendi la prima parola
    if " " in s or "(" in s:
        s = s.replace("(", " ").split()[0].strip()

    if len(s) == 2:
        # prova ISO-639-1 → 639-2 "banale"
        if s == "it":
            return "ita"
        if s == "en":
            return "eng"
        if s == "fr":
            return "fra"
        if s == "de":
            return "deu"
        if s == "es":
            return "spa"

    return s or "und"


def _infer_kind_from_text(text: str) -> str:
    """
    Deduce un 'kind' approssimativo dal testo (nome/descrizione).
      - 'forced', 'only signs' → 'forced'
      - 'sdh', 'hearing impaired', 'hoh' → 'sdh'
      - 'commentary' → 'commentary'
      - 'karaoke' → 'karaoke'
      - altrimenti 'normal'
    """
    s = (text or "").strip().lower()
    if not s:
        return "normal"

    if "forced" in s or "only signs" in s or "signs only" in s:
        return "forced"
    if "sdh" in s or "hearing" in s or "impaired" in s or "hoh" in s:
        return "sdh"
    if "commentary" in s or "comment" in s:
        return "commentary"
    if "karaoke" in s:
        return "karaoke"

    return "normal"


def _codec_label_from_name(codec_name: str) -> str:
    """
    Traduzione “umana” del codec dei sottotitoli.
    """
    c = (codec_name or "").lower()
    if c in {"dvd_subtitle", "subdvd"}:
        return "VobSub"
    if c in {"hdmv_pgs_subtitle", "pgssub", "pgs"}:
        return "PGS"
    if c in {"subrip", "srt"}:
        return "SubRip"
    if c in {"ass", "ssa"}:
        return "ASS"
    if c in {"mov_text", "tx3g"}:
        return "MOV text"
    return codec_name or ""


def _kind_display(kind: str) -> str:
    """
    Come mostrare il 'kind' nella UI.
    """
    k = (kind or "normal").strip().lower()
    if k == "sdh":
        return "SDH"
    if k == "forced":
        return "forced"
    if k == "default":
        return "default"
    if k == "commentary":
        return "commentary"
    if k == "karaoke":
        return "karaoke"
    # 'normal' → stringa vuota (non mostriamo nulla)
    return ""


# ──────────────────────────────────────────────────────────────
# Classe principale
# ──────────────────────────────────────────────────────────────

class SubtitleManager:
    @staticmethod
    def probe_embedded(input_path: Path) -> list[dict]:
        """
        Usa ffprobe per estrarre i flussi di sottotitoli incorporati.
        Se esiste un sidecar LDVD (<basename>.ldvdmeta.json) usa le sue
        info 'subtitles' per:
          - lingua
          - nome (title)
          - kind (normal/forced/sdh/…)
        Ritorna una lista di dict con:
          {
            'index',
            'language',
            'title',
            'kind',
            'codec_name',
            'codec_label'
          }
        """
        cmd = [
            C.FFPROBE_BIN,
            "-v",
            "error",
            "-select_streams",
            "s",
            "-show_entries",
            "stream=index,codec_name:stream_tags=language,title",
            "-of",
            "json",
            str(input_path),
        ]

        out = subprocess.check_output(cmd)
        info = json.loads(out)
        raw_streams = info.get("streams", []) or []
        streams: list[dict] = []

        # Prova a caricare il sidecar LDVD
        sidecar = _load_ldvd_sidecar(Path(input_path))
        side_subs = []
        if isinstance(sidecar, dict):
            try:
                side_subs = sidecar.get("subtitles") or []
            except Exception:
                side_subs = []

        for pos, s in enumerate(raw_streams):
            tags = s.get("tags") or {}
            lang = tags.get("language", "und")
            title = tags.get("title", "") or ""

            codec_name = s.get("codec_name") or ""
            codec_label = _codec_label_from_name(codec_name)

            kind = "normal"

            # Allineiamo per posizione (pos) ai subtitles[] del sidecar:
            # in LDVD li abbiamo salvati già in ordine "naturale".
            if pos < len(side_subs):
                meta = side_subs[pos] or {}
                side_lang = (meta.get("language") or meta.get("lang") or "").strip()
                side_name = (meta.get("name") or "").strip()
                explicit_kind = (meta.get("kind") or "").strip().lower()
                forced_flag = bool(
                    meta.get("forced") or meta.get("is_forced")
                )

                if side_lang:
                    lang = side_lang
                if side_name:
                    title = side_name

                if explicit_kind in {
                    "normal",
                    "default",
                    "forced",
                    "sdh",
                    "commentary",
                    "karaoke",
                }:
                    kind = explicit_kind
                else:
                    # se non c'è un 'kind' esplicito nel JSON, ricava da
                    # forced_flag + nome (es. “SDH”, “forced”, …)
                    kind = "forced" if forced_flag else _infer_kind_from_text(side_name or title)
            else:
                # Nessuna info extra dal sidecar → inferenza grezza dal titolo
                kind = _infer_kind_from_text(title)

            lang_norm = _norm_lang(lang)
            streams.append(
                {
                    "index": s.get("index"),
                    "language": lang_norm or "und",
                    "title": title,
                    "kind": kind or "normal",
                    "codec_name": codec_name,
                    "codec_label": codec_label,
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
        fd, temp_name = tempfile.mkstemp(
            dir=str(C.TEMP_DIR),
            suffix=".srt",
            text=True,
        )
        _ = fd  # inutilizzato, ma lasciato per chiarezza
        tmp = Path(temp_name)
        tmp.write_text(text, encoding="utf-8")
        return tmp

    @staticmethod
    def select_embedded_dialog(streams: list[dict], parent=None) -> list[dict]:
        """
        Dialog multi-select per scegliere uno o più flussi incorporati.
        Restituisce la lista dei dict selezionati, o [] se nessuno.

        Mostra ora anche codec + kind, es.:
          #2 [ita] Italiano — VobSub (SDH)
          #3 [eng] English — VobSub (forced)
        """
        dlg = QDialog(parent)
        dlg.setWindowTitle("Scegli sottotitoli incorporati")
        layout = QVBoxLayout(dlg)

        listw = QListWidget()
        listw.setSelectionMode(QAbstractItemView.MultiSelection)

        for s in streams:
            idx = s.get("index")
            lang = _norm_lang(s.get("language", "und"))
            codec_label = s.get("codec_label") or ""
            kind = (s.get("kind") or "normal").lower()

            # Nome lingua “umano”
            lang_disp = C.LANGUAGE_NAMES.get(lang, lang.upper())

            # Kind in forma carina
            kind_disp = _kind_display(kind)

            parts = [lang_disp]
            if codec_label:
                parts.append(f"— {codec_label}")
            if kind_disp:
                parts.append(f"({kind_disp})")

            desc = " ".join(parts)
            label = f"#{idx} [{lang}] {desc}"
            listw.addItem(label)

        layout.addWidget(listw)

        # Doppio clic = conferma (OK)
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
                row = listw.row(item)
                selected.append(streams[row])
            return selected
        return []
