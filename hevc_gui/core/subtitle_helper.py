# subtitle_helper.py
# ─────────────────────────────────────────────────────────────────────
# Wizard per la gestione dei sottotitoli:
#
# • riconosce gli stream incorporati nel video (via SubtitleManager)
# • permette di scegliere Lingua + Tipo (normal / forced / sdh) per
#   ciascun sottotitolo
# • consente di aggiungere un file esterno (.srt / .ass) se il
#   video non ne contiene
# • (nuovo) prova a usare il sidecar LDVD (mw._ldvd_sidecar) per:
#       - proporre direttamente i VobSub/SRT “giusti”
#       - deduplicare per coppia (lingua, tipo)
#       - suggerire lingua/tipo per gli stream embedded del DVD
# • riempie in MainWindow i campi:
#       _subtitle_inputs   (solo Path per file esterni)
#       _subtitle_langs    (codici ISO – es. 'ita', 'eng', 'und')
#       _subtitle_types    ('normal', 'forced', 'sdh', …)
#       _subtitle_opts     (solo coppie "-map spec" o "-i file")
#       _subtitle_out_opts (-disposition …)
# ─────────────────────────────────────────────────────────────────────

from hevc_gui.i18n import L
import tempfile
import os
from pathlib import Path
from typing import Tuple, List, Dict, Any

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
)

# Mappa tipo → ffmpeg disposition
KIND_MAP = {
    "normal": None,
    "default": "default",
    "forced": "forced",
    "sdh": "hearing_impaired",
    "commentary": "comment",
    "karaoke": "karaoke",
}


# ─────────────────────────────────────────────────────────────────────
# Helper “furbi” per lingua / tipo / sidecar LDVD
# ─────────────────────────────────────────────────────────────────────

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
    Prova a dedurre il tipo di sottotitolo guardando il testo (nome/descrizione).
    Non è perfetto, ma aiuta:
      - 'forced', 'only signs' → 'forced'
      - 'sdh', 'hearing impaired', 'hoh' → 'sdh'
      - 'commentary' → 'commentary'
      - 'karaoke' → 'karaoke'
      - altrimenti 'normal'
    """
    s = (text or "").strip().lower()
    if not s:
        return "normal"

    if "forced" in s or "signs" in s or "only signs" in s:
        return "forced"
    if "sdh" in s or "hearing" in s or "impaired" in s or "hoh" in s:
        return "sdh"
    if "commentary" in s or "comment" in s:
        return "commentary"
    if "karaoke" in s:
        return "karaoke"

    return "normal"


def _get(obj: Any, key: str, default=None):
    """
    Accesso robusto sia a dict che a oggetti con attributi.
    """
    try:
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key)
    except Exception:
        return default


def _sidecar_hint_for_embedded(sidecar: Any, stream: Dict[str, Any]) -> Tuple[str, str] | None:
    """
    Se il sidecar LDVD conosce questo stream embedded (via stream_index/index/sub_index),
    prova a ricavare (lingua, tipo) “giusti”.

    Tipo:
      - se c'è un campo 'kind' valido nel JSON → usalo
      - altrimenti: 'forced' se forced=True, altrimenti inferenza dal nome
    """
    try:
        idx = int(stream.get("index"))
    except Exception:
        return None

    subtitles = _get(sidecar, "subtitles", []) or []
    for sub in subtitles:
        # 1) prova a matchare via stream_index (più affidabile)
        sub_idx = _get(sub, "stream_index", None)
        if sub_idx is None:
            # 2) fallback: index "per-tipo"
            sub_idx = _get(sub, "index", None)
        if sub_idx is None:
            # 3) fallback legacy: sub_index
            sub_idx = _get(sub, "sub_index", None)

        try:
            sub_idx = int(sub_idx)
        except Exception:
            continue

        if sub_idx != idx:
            continue

        lang = _norm_lang(_get(sub, "language", "") or "")
        if not lang:
            lang = "und"

        name = _get(sub, "name", "") or ""

        sc_kind = (_get(sub, "kind", "") or "").strip().lower()
        forced_flag = bool(
            _get(sub, "forced", False) or _get(sub, "is_forced", False)
        )
        base_kind = _infer_kind_from_text(name)

        if sc_kind in KIND_MAP:
            kind = sc_kind
        else:
            kind = "forced" if forced_flag else base_kind

        return lang, kind

    return None


def _collect_external_from_sidecar(sidecar: Any) -> List[Dict[str, Any]]:
    """
    Colleziona i sottotitoli ESTERNI dal sidecar LDVD, se presente.

    Restituisce una lista di dict:
        {
            "path": Path,
            "lang": "ita"/"eng"/...,
            "kind": "normal"/"forced"/"sdh"/"default"/...,
            "source": descrizione stringa
        }

    Logica:
        1) subtitles[].external_files:
           - prende tutti i file esterni noti associati al DVD
           - lingua da .language
           - tipo da .forced / nome (via _infer_kind_from_text)
        2) (opzionale) srt_requests[] o srt_hint:
           - SRT generati da OCR (quando LDVD ha fatto l'OCR)
        3) deduplica per PATH (se lo stesso file è elencato più volte)
           preferendo SRT (OCR) quando possibile
        4) deduplica per COPPIA (lingua, tipo):
           MAX 1 file per (lang, kind), preferendo SRT rispetto ad altri
    """
    if not sidecar:
        return []

    candidates: List[Dict[str, Any]] = []

    # 1) subtitles[].external_files
    subtitles = _get(sidecar, "subtitles", []) or []
    for sub in subtitles:
        lang = _norm_lang(_get(sub, "language", "") or "")
        name = _get(sub, "name", "") or ""
        forced_flag = bool(_get(sub, "forced", False))
        files = _get(sub, "external_files", []) or []

        base_kind = _infer_kind_from_text(name)
        kind = "forced" if forced_flag else base_kind

        for f in files:
            try:
                p = Path(f)
            except Exception:
                continue
            if not p.is_file():
                continue
            candidates.append(
                {
                    "path": p,
                    "lang": lang,
                    "kind": kind,
                    "source": "Sidecar subtitles.external_files",
                }
            )

    # 2) SRT da OCR: srt_requests[] o (vecchio) srt_hint
    srt_requests = _get(sidecar, "srt_requests", None)
    if srt_requests is None:
        srt_requests = []
        srt_hint = _get(sidecar, "srt_hint", None)
        if srt_hint:
            # forma compatta: proviamo a trattarla come un singolo “request”
            srt_requests = [srt_hint]

    for req in srt_requests or []:
        target = _get(req, "target", "") or _get(req, "path", "") or ""
        if not target:
            continue
        try:
            p = Path(target)
        except Exception:
            continue
        if not p.is_file():
            continue

        lang = _norm_lang(_get(req, "language", "") or "")
        name = _get(req, "name", "") or ""
        reason = _get(req, "reason", "") or ""
        hint = f"{name} {reason}".strip()
        kind = _infer_kind_from_text(hint)
        source = "SRT (OCR)" if p.suffix.lower() == ".srt" else "Sidecar SRT"

        candidates.append(
            {
                "path": p,
                "lang": lang,
                "kind": kind,
                "source": source,
            }
        )

    if not candidates:
        return []

    # Dedup per PATH: se lo stesso file appare più volte, tieni il “migliore”
    by_path: Dict[Path, Dict[str, Any]] = {}
    for item in candidates:
        p = item["path"]
        prev = by_path.get(p)
        if prev is None:
            by_path[p] = item
            continue
        # se uno dei due è un SRT (OCR) e l’altro no, preferisci lo SRT
        prev_src = (prev.get("source") or "").lower()
        cur_src = (item.get("source") or "").lower()
        if "srt" in cur_src and "srt" not in prev_src:
            by_path[p] = item

    uniq_by_path = list(by_path.values())

    # Dedup per coppia (lang, kind): max 1 file per (lingua, tipo)
    def _prio(it: Dict[str, Any]) -> tuple:
        # 0 = SRT, 1 = altro
        is_srt = 0 if it["path"].suffix.lower() == ".srt" else 1
        lang = it.get("lang") or "zzzz"
        # leggero bias per ita/eng (solo per “ordine”, non fondamentale)
        ita_bias = 0 if lang == "ita" else 1
        eng_bias = 0 if lang == "eng" else 1
        return (is_srt, ita_bias, eng_bias, str(lang), str(it.get("kind") or ""))

    uniq_by_path.sort(key=_prio)

    seen_lang_kind: set = set()
    final: List[Dict[str, Any]] = []
    for it in uniq_by_path:
        key = (it["lang"], it["kind"])
        if key in seen_lang_kind:
            continue
        seen_lang_kind.add(key)
        final.append(it)

    return final


# ─────────────────────────────────────────────────────────────────────
# Funzione helper per codifica UTF-8
# ─────────────────────────────────────────────────────────────────────

def ensure_utf8(srt_path: Path, temp_dir: Path) -> Path:
    """
    Se il file non è UTF-8, lo ricodifica e restituisce il path del nuovo file.

    Fix: se temp_dir non è scrivibile (tipico nel .deb quando punta a /usr/lib/...),
    usa un fallback scrivibile (preferenza RAM: /dev/shm/hevc_gui).
    """
    raw = srt_path.read_bytes()
    enc = chardet.detect(raw).get("encoding") or "utf-8"
    if enc.lower() == "utf-8":
        return srt_path

    text = raw.decode(enc, errors="replace")

    # HEVC_SUBTITLE_TMP_FALLBACK_V1
    temp_dir = Path(temp_dir)

    # prova prima la dir richiesta, poi fallback robusti
    cand_dirs = [
        temp_dir / "subtitles",
        Path("/dev/shm/hevc_gui/tmp/subtitles"),
        Path("/dev/shm/hevc_gui/subtitles"),
        Path(tempfile.gettempdir()) / "hevc_gui" / "tmp" / "subtitles",
        Path.home() / ".cache" / "hevc_gui" / "tmp" / "subtitles",
    ]

    picked = None
    for d in cand_dirs:
        try:
            d.mkdir(parents=True, exist_ok=True)
            t = d / ".hevc_write_test"
            t.write_text("1", encoding="utf-8")
            try:
                t.unlink()
            except FileNotFoundError:
                pass
            picked = d
            break
        except Exception:
            continue

    if picked is None:
        # fallback estremo: lascia temp_dir (fallirà con errore leggibile più avanti)
        picked = temp_dir

    tmp = Path(tempfile.mkstemp(dir=str(picked), suffix=srt_path.suffix)[1])
    tmp.write_text(text, encoding="utf-8")
    return tmp


class SubTagDialog(QDialog):
    """
    Dialog per scegliere lingua + tipo (normal, forced, sdh…) per un sottotitolo.
    """

    def __init__(self, parent=None, pre_lang: str = "und", pre_kind: str = "normal"):
        super().__init__(parent)
        self.setWindowTitle(L("Sottotitolo"))
        lay = QFormLayout(self)

        self.cmb_lang = QComboBox()
        self.cmb_lang.addItem(L("Unknown"), "und")
        for code, full in sorted(C.LANGUAGE_NAMES.items()):
            self.cmb_lang.addItem(f"{full} ({code})", code.lower())
        idx = self.cmb_lang.findData(pre_lang.lower())
        if idx >= 0:
            self.cmb_lang.setCurrentIndex(idx)
        lay.addRow("Lingua:", self.cmb_lang)

        self.cmb_kind = QComboBox()
        self.cmb_kind.addItems(list(KIND_MAP.keys()))
        kidx = self.cmb_kind.findText(pre_kind)
        if kidx >= 0:
            self.cmb_kind.setCurrentIndex(kidx)
        lay.addRow("Tipo:", self.cmb_kind)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def result(self) -> Tuple[str, str]:
        return self.cmb_lang.currentData(), self.cmb_kind.currentText()


# ─────────────────────────────────────────────────────────────────────
# Entry point: select_subtitles(main_win)
# ─────────────────────────────────────────────────────────────────────

def select_subtitles(main_win) -> None:
    """
    Procedura di selezione sottotitoli:
    - Azzera i campi sottotitoli della MainWindow
    - Propone selezione multipla per sottotitoli incorporati
    - (nuovo) prova a usare il sidecar LDVD (mw._ldvd_sidecar) per suggerire
      lingua/tipo degli embedded e agganciare eventuali SRT/VobSub esterni.
    - Consente comunque di aggiungere sottotitoli esterni (loop manuale)
    - Popola tutti i campi: inputs, langs, types, opts, out_opts

    Fix 2026-02-17:
    - preserva SELEZIONE MULTIPLA embedded
    - salva map embedded in mw._subtitle_maps
    - salva conteggio embedded in mw._subs_integrated_count
    - aggiunge -map solo dopo Accept (liste sempre allineate)
    """
    mw = main_win

    # Reset dei campi
    mw._subtitle_inputs.clear()
    mw._subtitle_opts.clear()
    mw._subtitle_langs.clear()
    mw._subtitle_types.clear()
    mw._subtitle_out_opts.clear()

    # Nuovi campi (retrocompatibili)
    if hasattr(mw, "_subtitle_maps"):
        mw._subtitle_maps.clear()
    else:
        mw._subtitle_maps = []
    mw._subs_integrated_count = 0

    sidecar = getattr(mw, "_ldvd_sidecar", None)

    # ────────────── Embedded ──────────────
    streams = sman.probe_embedded(mw._current_file)

    # Fallback: se ffprobe non vede nulla ma il sidecar ha i sottotitoli,
    # sintetizziamo una lista "streams" direttamente dal sidecar.
    if not streams and sidecar is not None:
        sc_subs = _get(sidecar, "subtitles", []) or []
        tmp_streams: List[Dict[str, Any]] = []
        for sub in sc_subs:
            lang = _norm_lang(_get(sub, "language", "") or "")
            kind = (_get(sub, "kind", "") or "normal").lower()
            if kind not in KIND_MAP:
                kind = "normal"

            idx = _get(sub, "stream_index", None)
            if idx is None:
                idx = _get(sub, "index", None)
            try:
                idx = int(idx)
            except Exception:
                continue

            tmp_streams.append(
                {
                    "index": idx,          # stream index (ffprobe "index")
                    "language": lang,
                    "kind": kind,
                    "codec": _get(sub, "format", "") or "vobsub",
                    "title": _get(sub, "name", "") or "",
                }
            )

        streams = tmp_streams

    embedded_maps: List[str] = []

    if streams:
        # Proviamo a derivare un indice relativo tra i soli sottotitoli (0:s:N),
        # mantenendo fallback su 0:<global_index> se non possiamo.
        rel_map: Dict[int, int] = {}
        try:
            idxs = []
            for d in streams:
                if "index" in d:
                    idxs.append(int(d["index"]))
            idxs_sorted = sorted(dict.fromkeys(idxs))
            rel_map = {g: i for i, g in enumerate(idxs_sorted)}
        except Exception:
            rel_map = {}

        sels = sman.select_embedded_dialog(streams, parent=mw)
        if sels:
            for s in sels:
                try:
                    gidx = int(s["index"])
                except Exception:
                    continue

                # Preferisci 0:s:<rel> (coerente con il resto della pipeline).
                # Se non abbiamo rel_map, fallback su stream index globale.
                if gidx in rel_map:
                    spec = f"0:s:{rel_map[gidx]}"
                else:
                    spec = f"0:{gidx}"

                # hint base da ffprobe + subtitle_manager (language + kind)
                pre_lang = s.get("language", "und") or "und"
                pre_kind = (s.get("kind") or "normal").lower()

                # se il sidecar conosce questo stream, migliora lingua/tipo
                if sidecar is not None:
                    try:
                        hint = _sidecar_hint_for_embedded(sidecar, s)
                    except Exception:
                        hint = None
                    if hint:
                        pre_lang, pre_kind = hint

                dlg = SubTagDialog(mw, pre_lang=_norm_lang(pre_lang), pre_kind=pre_kind)
                if dlg.exec_() != QDialog.Accepted:
                    continue

                lang, kind = dlg.result()

                # Append SOLO ora: liste sempre allineate
                mw._subtitle_opts += ["-map", spec]
                embedded_maps.append(spec)

                mw._subtitle_langs.append(lang or _norm_lang(pre_lang))
                mw._subtitle_types.append(kind)

    # Salva embedded maps + conteggio (usati dal mux/queue)
    mw._subtitle_maps = list(embedded_maps)
    mw._subs_integrated_count = len(embedded_maps)

    # ────────────── Esterni dal sidecar LDVD (auto-suggest) ──────────────
    if sidecar is not None:
        try:
            auto_ext = _collect_external_from_sidecar(sidecar)
        except Exception:
            auto_ext = []

        if auto_ext:
            try:
                mw.txt_info.append(
                    L('> Sidecar LDVD: trovati {0} sottotitoli esterni (deduplicati per lingua/tipo).').format(len(auto_ext))
                )
            except Exception:
                pass

            for item in auto_ext:
                path = item["path"]
                pre_lang = item.get("lang") or "und"
                pre_kind = item.get("kind") or "normal"
                src = item.get("source") or ""

                try:
                    mw.txt_info.append(
                        f"  - {path.name}  [{pre_lang} / {pre_kind}]  ← {src}"
                    )
                except Exception:
                    pass

                dlg = SubTagDialog(mw, pre_lang=_norm_lang(pre_lang), pre_kind=pre_kind)
                if dlg.exec_() != QDialog.Accepted:
                    continue
                lang, kind = dlg.result()

                fixed_path = ensure_utf8(path, C.TEMP_DIR)
                mw._subtitle_inputs.append(fixed_path)
                mw._subtitle_opts += ["-i", str(fixed_path)]
                mw._subtitle_langs.append(lang)
                mw._subtitle_types.append(kind)

    # ────────────── Esterni scelti a mano (loop multiplo) ──────────────
    while True:
        path, _ = QFileDialog.getOpenFileName(
            mw,
            L('Seleziona file di sottotitoli esterni'),
            str(mw._current_file.parent),
            L('SubRip (*.srt);;ASS (*.ass);;Tutti i file (*)'),
        )
        if not path:
            break

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
        mw.txt_info.append(L("! Nessun sottotitolo aggiunto."))
        return

    # Disposition: 1 solo default (il primo regular), forced solo dove serve
    default_idx = None
    for i, k in enumerate(mw._subtitle_types):
        if (k or "").lower() != "forced":
            default_idx = i
            break
    if default_idx is None:
        default_idx = 0

    for i, k in enumerate(mw._subtitle_types):
        kk = (k or "").lower()
    
        # override totale (non “modifier”): cancella tutto e reimposta solo ciò che serve
        mw._subtitle_out_opts += [f"-disposition:s:{i}", "0"]
        if i == default_idx:
            mw._subtitle_out_opts += [f"-disposition:s:{i}", "default"]
        if kk == "forced":
            mw._subtitle_out_opts += [f"-disposition:s:{i}", "forced"]

    # ────────────── UI update ──────────────
    mw.txt_info.append(L('> Sottotitoli: {0} tracce selezionate').format(len(mw._subtitle_types)))
    mw.btn_chapter.setEnabled(True)
    mw.btn_copy_log.setEnabled(False)

