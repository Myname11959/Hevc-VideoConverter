# -*- coding: utf-8 -*-
# scripts/preview.py — genera WAV di preview e apre l’oscilloscopio
from __future__ import annotations

import os
import sys
import shlex
import json
import subprocess
import re
from pathlib import Path
from typing import Any, Optional, List

from PyQt5.QtCore import Qt, QProcess, QEventLoop, QSettings
from PyQt5.QtWidgets import QProgressDialog, QMessageBox

# --- Scope dialog (UI player+oscillo) ---
try:
    from oscilloscope_preview import PreviewDialog as ScopeDialog  # type: ignore
except Exception:
    ScopeDialog = None  # caricheremo lo scope solo se disponibile

# -------------------- Opzioni runtime / path --------------------
USE_PROGRESS = os.getenv("HEVC_PREVIEW_PROGRESS", "1") == "1"
USE_POPUPS = os.getenv("HEVC_PREVIEW_POPUPS", "0") == "1"
TMP_BASE = Path(os.getenv("HEVC_PREVIEW_TMP", "/dev/shm")).expanduser()

FFMPEG = os.environ.get("FFMPEG", "/usr/bin/ffmpeg")
FFPROBE = os.environ.get("FFPROBE", "/usr/bin/ffprobe")

# Persistenza geometria finestra scope (solo fallback + restore; il layout è nello scope)
SCOPE_APP = "LorisPaganiniHomeStudio"
SCOPE_NAME = "HEVC-GUI"
SCOPE_KEY = "scope"
# ==================== Parametri UI regolabili (via env) ====================
# Larghezza/Altezza finestra di default all’avvio (fallback alla prima apertura).
# La finestra si ridimensiona automaticamente in base ai canali (logica nello scope).
SCOPE_DEF_W = int(os.getenv("HEVC_SCOPE_DEF_W", "560"))  # fallback prima apertura
SCOPE_DEF_H = int(os.getenv("HEVC_SCOPE_DEF_H", "318"))  # fallback prima apertura
# ==========================================================================


# ======================================================================
# Helpers base
# ======================================================================
def _log(msg: str) -> None:
    sys.stdout.write(msg.rstrip() + "\n")
    sys.stdout.flush()


def _warn_console(title: str, message: str, parent=None) -> None:
    _log(f"[WARN] {title}: {message}")
    if USE_POPUPS:
        try:
            QMessageBox.warning(parent, title, message)
        except Exception:
            pass


def _which(p: str) -> str:
    pp = Path(p)
    if pp.exists():
        return str(pp)
    for d in os.environ.get("PATH", "").split(":"):
        cand = Path(d) / p
        if cand.exists():
            return str(cand)
    return p


def _ensure_tmp_dir(base: Path) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    return base


def _clean(s: str) -> str:
    return str(s).strip().strip('"').strip("'")


# ======================================================================
# ffprobe helpers
# ======================================================================
def count_audio_streams(src: str) -> int:
    try:
        p = subprocess.run(
            [_which(FFPROBE), "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", src],
            capture_output=True,
            text=True,
        )
        if p.returncode != 0:
            return 0
        return sum(1 for ln in (p.stdout or "").splitlines() if ln.strip())
    except Exception:
        return 0


def probe_stream_info(src: str, track_idx: int) -> dict:
    """
    Prova a ottenere info base con ffprobe:
      channels, sample_rate, channel_layout.

    Può restituire un dict con channels=0 / sample_rate=0 se i campi
    non sono presenti: in quel caso gestiamo un fallback altrove.
    """
    try:
        p = subprocess.run(
            [
                _which(FFPROBE),
                "-v",
                "error",
                "-select_streams",
                f"a:{int(track_idx)}",
                "-show_entries",
                "stream=channels,sample_rate,channel_layout",
                "-of",
                "json",
                src,
            ],
            capture_output=True,
            text=True,
        )
        if p.returncode != 0:
            return {}
        data = json.loads(p.stdout or "{}")
        ss = data.get("streams") or []
        if not ss:
            return {}
        st = ss[0]
        return {
            "channels": int(st.get("channels") or 0),
            "sample_rate": int(st.get("sample_rate") or 0),
            "channel_layout": (st.get("channel_layout") or None),
        }
    except Exception:
        return {}


def _probe_audio_channels_fallback(src: str, track_idx: int) -> tuple[int, Optional[int]]:
    """
    Fallback robusto quando ffprobe non dà i canali direttamente sul VOB:
    - decodifica ~1s della traccia in WAV PCM;
    - usa ffprobe sul WAV per leggere channels / sample_rate.

    Ritorna (channels, sample_rate) oppure (0, None) se fallisce.
    """
    tmp_dir = _ensure_tmp_dir(TMP_BASE / "hevc_preview_probe")
    wav_path = tmp_dir / f"chprobe_{track_idx}.wav"

    # Pulisci eventuale residuo
    try:
        if wav_path.exists():
            wav_path.unlink()
    except Exception:
        pass

    # 1) ffmpeg → WAV breve
    cmd = [
        _which(FFMPEG),
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-i",
        src,
        "-map",
        f"0:a:{int(track_idx)}",
        "-vn",
        "-sn",
        "-dn",
        "-c:a",
        "pcm_s16le",
        "-t",
        "1",
        "-f",
        "wav",
        "-write_channel_mask",
        "0",  # disabilita il channel mask (resta WAVEEXT ma a ffprobe va benissimo)
        "-y",
        str(wav_path),
    ]

    try:
        subprocess.run(cmd, check=True)
    except Exception as exc:
        _log(f"[PREVIEW] Fallback ffmpeg fallita per 0:a:{track_idx}: {exc}")
        return 0, None

    # 2) ffprobe sul WAV generato
    try:
        p = subprocess.run(
            [
                _which(FFPROBE),
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=channels,sample_rate",
                "-of",
                "json",
                str(wav_path),
            ],
            capture_output=True,
            text=True,
        )
        if p.returncode != 0:
            raise RuntimeError(p.stderr or "ffprobe error on WAV")

        data = json.loads(p.stdout or "{}")
        ss = data.get("streams") or []
        if not ss:
            raise RuntimeError("no streams in WAV")

        st = ss[0]
        ch = int(st.get("channels") or 0)
        sr = int(st.get("sample_rate") or 0)
        ch_int = int(ch or 0)
        sr_int: Optional[int] = int(sr or 0) if sr else None

        _log(f"[PREVIEW] Fallback probe: 0:a:{track_idx} → {ch_int} canali, {sr_int or 'n/d'} Hz")
        return ch_int, sr_int
    except Exception as exc:
        _log(f"[PREVIEW] Fallback probe ffprobe fallita per 0:a:{track_idx}: {exc}")
        return 0, None
    finally:
        try:
            if wav_path.exists():
                wav_path.unlink()
        except Exception:
            pass


# ======================================================================
# Risoluzione sorgente/GUI
# ======================================================================
def resolve_source(ac: Any) -> Optional[str]:
    # audio esterno esplicito?
    try:
        if bool(getattr(ac, "audio_externo", False)) or bool(getattr(ac, "audio_esterno", False)):
            ext = getattr(ac, "external_audio_file", None) or getattr(ac, "audio_external_file", None)
            if ext:
                p = Path(_clean(ext)).expanduser()
                if p.is_file():
                    return str(p)
    except Exception:
        pass

    # attributi tipici del file interno
    for n in (
        "file",
        "_current_file",
        "current_file",
        "src",
        "src_path",
        "_src",
        "_src_path",
        "_infile",
        "input_path",
        "_input",
        "source",
        "srcfile",
        "src_file",
    ):
        v = getattr(ac, n, None)
        if not v:
            continue
        try:
            p = v if isinstance(v, Path) else Path(_clean(v))
            p = p.expanduser()
            if p.is_file():
                return str(p)
        except Exception:
            continue

    # QLineEdit 'path'
    try:
        le = getattr(ac, "path", None)
        if le is not None and hasattr(le, "text"):
            t = _clean(le.text())
            if t:
                p = Path(t).expanduser()
                if p.is_file():
                    return str(p)
    except Exception:
        pass
    return None


def resolve_track_index(ac) -> int:
    w = getattr(ac, "cmb_track", None)
    if not (w and hasattr(w, "currentIndex")):
        return 0
    try:
        data = w.currentData()
        if isinstance(data, dict):
            for k in ("index", "ff_index", "ff_idx", "idx"):
                if k in data and int(data[k]) >= 0:
                    return int(data[k])
        if isinstance(data, (tuple, list)) and data:
            d0 = data[0]
            if isinstance(d0, int) and d0 >= 0:
                return int(d0)
            m = re.search(r"a:(\d+)", str(d0))
            if m:
                return int(m.group(1))
        if isinstance(data, str):
            m = re.search(r"a:(\d+)", data)
            if m:
                return int(m.group(1))
    except Exception:
        pass
    # fallback: indice visivo (con placeholder alla posizione 0)
    try:
        idx = int(w.currentIndex())
        d0 = w.itemData(0)
        has_ph = isinstance(d0, (tuple, list)) and d0 and (d0[0] == -1)
        return max(0, idx - 1) if (idx > 0 and has_ph) else max(0, idx)
    except Exception:
        return 0

def resolve_track_for_preview(ac: Any) -> tuple[int, bool, Optional[dict]]:
    """
    Ritorna (idx, use_abs, meta):

      • idx      → se use_abs=False: indice audio 0..N-1 (come prima, 0:a:idx)
                   se use_abs=True : stream_index assoluto (useremo -map 0:idx)

      • use_abs  → True se nei dati combo c'è ff_index (sidecar LDVD),
                   False altrimenti (modo "classico" senza sidecar).

      • meta     → opzionale dict con channels/sample_rate/layout se forniti dai dati
                   combo (cioè dal sidecar). Se None, ci pensa ffprobe.
    """
    w = getattr(ac, "cmb_track", None)
    if not (w and hasattr(w, "currentIndex")):
        return 0, False, None

    try:
        data = w.currentData()
        # Caso "nuovo": itemData è un dict con ff_index e metadati dal sidecar
        if isinstance(data, dict):
            # preferisci ff_index se presente
            ff_idx = data.get("ff_index")
            if ff_idx is not None and int(ff_idx) >= 0:
                ff_idx = int(ff_idx)
                # Meta opzionale
                ch = int(data.get("channels") or 0)
                sr = int(data.get("sample_rate") or 0)
                layout = data.get("layout") or data.get("channel_layout")
                meta = {
                    "channels": ch,
                    "sample_rate": sr,
                    "channel_layout": layout,
                }
                # ripulisci meta da zero/None
                meta = {k: v for k, v in meta.items() if v}
                return ff_idx, True, (meta or None)

            # fallback: usa index/idx come indice audio 0..N-1
            for k in ("index", "idx"):
                if k in data and int(data[k]) >= 0:
                    return int(data[k]), False, None

        # Vecchi casi: tuple/list/str → delega a resolve_track_index()
    except Exception:
        pass

    # Fallback compatibile con il passato
    idx = resolve_track_index(ac)
    return idx, False, None

def resolve_preview_seconds(ac: Any) -> Optional[int]:
    w = getattr(ac, "cmb_prev", None)
    if w is not None:
        try:
            d = w.currentData()
            if isinstance(d, (int, float)) and d > 0:
                return int(d)
        except Exception:
            pass
        try:
            s = str(w.currentText()).lower().strip()
            if not s:
                return None
            if "min" in s:
                num = int("".join(ch for ch in s if ch.isdigit()))
                return max(1, num) * 60
            num = int("".join(ch for ch in s if ch.isdigit()))
            return num if num > 0 else None
        except Exception:
            pass
    return None


def resolve_preview_start(ac: Any) -> int:
    w = getattr(ac, "te_prev_start", None)
    if w is not None and hasattr(w, "time"):
        try:
            t = w.time()
            return max(0, int(t.hour()) * 3600 + int(t.minute()) * 60 + int(t.second()))
        except Exception:
            pass
    return 0


# ======================================================================
# AF/Output dalla GUI (robusto ma non invasivo)
# ======================================================================
def _af_from_ui(ac: Any, in_channels: int) -> tuple[Optional[str], Optional[int], Optional[int]]:
    """
    Ritorna (af_chain, out_ac, force_sr):
      • af_chain  : catena filtri generata dalla GUI, se esiste.
      • out_ac    : # canali richiesti (None se “lascia com'è”).
      • force_sr  : sample-rate forzato (None se “nessuno/originale”).
    """
    # 1) Sample-rate dalle combo note
    force_sr: Optional[int] = None
    for nm in ("cmb_sr", "cmb_samplerate", "cmb_sample_rate", "cmb_rate"):
        w = getattr(ac, nm, None)
        if w and hasattr(w, "currentText"):
            s = (w.currentText() or "").strip().lower()
            if s and s not in ("nessuno", "originale", "orig", "auto"):
                try:
                    val = int("".join(ch for ch in s if ch.isdigit()))
                    if val > 0:
                        force_sr = val
                except Exception:
                    pass
            break

    # 2) Filtri così come li crea la GUI
    af_chain: Optional[str] = None
    try:
        if hasattr(ac, "_build_filters_chain_from_ui"):
            filters = list(ac._build_filters_chain_from_ui(for_preview=True, channels_hint=in_channels))
        else:
            filters = []
    except Exception:
        filters = []

    # Se c'è un limiter, mettilo in coda e “soft”
    if any(f.strip().startswith("alimiter") for f in filters):
        fs = [f for f in filters if not f.strip().startswith("alimiter")]
        fs.append("alimiter=limit=0.965:attack=12:release=300")
        filters = fs
    af_chain = ",".join(f for f in filters if f) if filters else None

    # 3) Canali in uscita (checkbox/profili se presenti)
    out_ac: Optional[int] = None
    try:
        if getattr(ac, "chk_force_stereo", None) and ac.chk_force_stereo.isChecked():
            out_ac = 2
        prof = getattr(ac, "_soundbar_profile", "none")
        if prof == "samsung_5_1_ac3":
            out_ac = 6
        elif prof == "samsung_stereo":
            out_ac = 2
        if getattr(ac, "chk_keep_mono", None) and ac.chk_keep_mono.isChecked() and in_channels == 1:
            out_ac = 1
    except Exception:
        pass

    return af_chain, out_ac, force_sr


# ======================================================================
# Runner
# ======================================================================
class AudioPreview:
    def __init__(self, ac: Any):
        self.ac = ac
        self.ffmpeg = _which(FFMPEG)
        self.ffprobe = _which(FFPROBE)

    def _run_ffmpeg_with_qprocess(self, cmd: list[str], total_secs: int | None) -> int:
        if not USE_PROGRESS:
            # Esecuzione semplice (senza dialogo)
            p = subprocess.run(cmd, capture_output=True, text=True)
            if p.returncode != 0:
                raise RuntimeError(p.stderr or "ffmpeg error")
            return p.returncode

        pd = QProgressDialog("Generazione preview audio…", "Annulla", 0, 100, self.ac)
        pd.setWindowModality(Qt.ApplicationModal)
        pd.setMinimumDuration(200)
        pd.setValue(0)

        proc = QProcess(self.ac)
        proc.setProcessChannelMode(QProcess.SeparateChannels)
        proc.setProgram(cmd[0])
        proc.setArguments(cmd[1:])

        secs_total = float(total_secs or 0.0)

        def _parse_sec(line: str):
            line = (line or "").strip()
            if line.startswith("out_time_ms="):
                try:
                    return float(line.split("=", 1)[1]) / 1_000_000.0
                except Exception:
                    return None
            if line.startswith("out_time="):
                try:
                    t = line.split("=", 1)[1]
                    hh, mm, ss = t.split(":")
                    return int(hh) * 3600 + int(mm) * 60 + float(ss)
                except Exception:
                    return None
            return None

        def on_stdout():
            try:
                data = bytes(proc.readAllStandardOutput()).decode("utf-8", "ignore")
            except Exception:
                return
            for ln in data.splitlines():
                sec = _parse_sec(ln)
                if sec is not None and secs_total > 0:
                    pd.setValue(int(max(0.0, min(1.0, sec / secs_total)) * 100))

        pd.canceled.connect(lambda: proc.kill())
        proc.readyReadStandardOutput.connect(on_stdout)

        loop = QEventLoop()
        proc.finished.connect(lambda *_: (pd.setValue(100), pd.close(), loop.quit()))
        proc.start()
        loop.exec_()

        rc = proc.exitCode()
        if rc != 0:
            err = bytes(proc.readAllStandardError()).decode("utf-8", "ignore")
            raise RuntimeError(err or f"ffmpeg exited with {rc}")
        return rc

    def start(self) -> None:
        # sorgente
        src = resolve_source(self.ac)
        if not src:
            _warn_console("Sorgente mancante", "Nessun file di input valido per la preview.", self.ac)
            return
        _log(f"[PREVIEW] Sorgente: {src}")

        # traccia audio (indice + modalità mappatura)
        track_idx, use_abs, meta = resolve_track_for_preview(self.ac)

        if not use_abs:
            # modalità classica: 0:a:<idx>
            n_tracks = count_audio_streams(src)
            if n_tracks == 0:
                _warn_console("Preview", "Nessuna traccia audio trovata (o ffprobe è fallito).", self.ac)
                return
            if track_idx >= n_tracks:
                _log(f"[PREVIEW] Traccia richiesta {track_idx} fuori range (0..{n_tracks - 1}). Uso 0.")
                track_idx = 0
            _log(f"[PREVIEW] Traccia: 0:a:{track_idx}")
        else:
            # modalità sidecar LDVD: stream_index assoluto → -map 0:<idx>
            _log(f"[PREVIEW] Traccia: 0:{track_idx}")

        # durata/offset
        ts = resolve_preview_seconds(self.ac)
        total_secs = ts if (isinstance(ts, int) and ts > 0) else None  # None = tutto file
        start_off = max(0, int(resolve_preview_start(self.ac)))
        _log(f"[PREVIEW] Durata: {'ALL' if total_secs is None else str(total_secs) + 's'}")
        _log(f"[PREVIEW] Start:  {start_off}s")

        # Info traccia (canali / sample-rate / layout)
        if meta is not None:
            info = dict(meta)
            _log(f"[PREVIEW] Info traccia (da sidecar): {info}")
        else:
            info = probe_stream_info(src, track_idx)

            # Se ffprobe non ci dà i canali, prova il fallback con WAV di 1s
            if not info or not info.get("channels"):
                ch_fb, sr_fb = _probe_audio_channels_fallback(src, track_idx)
                if ch_fb:
                    info = {
                        "channels": ch_fb,
                        "sample_rate": sr_fb or 0,
                        "channel_layout": info.get("channel_layout") if info else None,
                    }
                    _log(f"[PREVIEW] Info traccia (fallback WAV): {info}")

            # (per sicurezza, se siamo in modalità assoluta e ancora non abbiamo info,
            #  prova il vecchio fallback per stream_index globale)
            if (not info) and use_abs:
                try:
                    p = subprocess.run(
                        [
                            _which(FFPROBE),
                            "-v",
                            "error",
                            "-show_entries",
                            "stream=index,channels,sample_rate,channel_layout",
                            "-of",
                            "json",
                            src,
                        ],
                        capture_output=True,
                        text=True,
                    )
                    data = json.loads(p.stdout or "{}")
                    for st in data.get("streams") or []:
                        if int(st.get("index", -1)) == int(track_idx):
                            info = {
                                "channels": int(st.get("channels") or 0),
                                "sample_rate": int(st.get("sample_rate") or 0),
                                "channel_layout": (st.get("channel_layout") or None),
                            }
                            _log(
                                f"[PREVIEW] Fallback probe (index): 0:{track_idx} → "
                                f"{info.get('channels', 0)} canali, {info.get('sample_rate', 0)} Hz"
                            )
                            break
                except Exception as e:
                    _log(f"[PREVIEW] Fallback probe fallita per 0:{track_idx}: {e}")

        _log(f"[PREVIEW] Info traccia: {info or 'n/d'}")

        in_ch = int((info or {}).get("channels") or 0) or 2

        # filtri/uscita coerenti con la GUI
        af_chain, out_ac, force_sr = _af_from_ui(self.ac, in_ch)
        _log(f"[PREVIEW] -af: {af_chain or '(none)'}")

        # WAV temporaneo
        tmp_dir = _ensure_tmp_dir(TMP_BASE / "hevc_preview")
        wav = tmp_dir / "preview_scope.wav"
        try:
            if wav.exists():
                wav.unlink()
        except Exception:
            pass

        # ffmpeg (seek PRIMA di -i, progress su stdout)
        cmd = [_which(FFMPEG), "-hide_banner", "-nostdin", "-progress", "pipe:1", "-nostats", "-y"]
        if start_off > 0:
            cmd += ["-ss", str(int(start_off))]
        cmd += ["-i", src, "-vn", "-sn", "-dn", "-loglevel", "error"]

        # mappatura traccia in base alla modalità
        if use_abs:
            # sidecar LDVD: stream_index assoluto
            cmd += ["-map", f"0:{int(track_idx)}"]
        else:
            # modalità "classica": a:<idx> (primo audio = 0)
            cmd += ["-map", f"0:a:{int(track_idx)}"]

        if af_chain:
            cmd += ["-af", af_chain]
        cmd += ["-c:a", "pcm_s16le"]
        if force_sr:
            cmd += ["-ar", str(int(force_sr))]
        if out_ac:
            cmd += ["-ac", str(int(out_ac))]
        if total_secs is not None:
            cmd += ["-t", str(int(total_secs))]
        # Importante: WAV PCM "non-Extensible" (niente 65534) anche multicanale
        cmd += ["-f", "wav", "-write_channel_mask", "0", str(wav)]

        _log("[PREVIEW] CMD: " + " ".join(shlex.quote(x) for x in cmd))

        try:
            self._run_ffmpeg_with_qprocess(cmd, total_secs)
        except Exception as e:
            _warn_console("Preview terminata", f"ffmpeg ha chiuso con errore:\n{e}", self.ac)
            return

        if not wav.exists():
            _warn_console("Preview", "File WAV non creato.", self.ac)
            return
        _log(f"[PREVIEW] WAV pronto: {wav}")

        if ScopeDialog is None:
            _log("[SCOPE] Modulo non disponibile: salto.")
            return

        # nomi canali per label
        ch_names = _scope_names_from_gui(af_chain, out_ac, in_ch)
        _log(f"[SCOPE] Piste GUI → {ch_names}")

        # apri scope (nessun autoplay: parte fermo, premi Play)
        try:
            scope = ScopeDialog(str(wav), self.ac, channel_names=ch_names, auto_cleanup=True)

            # ─── Mantieni un riferimento sul parent per evitare che il GC uccida il dialog ───
            try:
                setattr(self.ac, "_hevc_preview_scope", scope)
            except Exception:
                pass

            # Geometria: ripristina SOLO posizione e larghezza (non altezza!)
            st = QSettings(SCOPE_APP, SCOPE_NAME)
            try:
                w_saved = int(st.value(f"{SCOPE_KEY}/width", 0))
                x_saved = int(st.value(f"{SCOPE_KEY}/pos_x", -1))
                y_saved = int(st.value(f"{SCOPE_KEY}/pos_y", -1))
            except Exception:
                w_saved = 0
                x_saved = y_saved = -1

            if w_saved <= 0:
                w_saved = SCOPE_DEF_W

            try:
                scope.resize(int(w_saved), scope.height())
            except Exception:
                pass
            if x_saved >= 0 and y_saved >= 0:
                try:
                    scope.move(int(x_saved), int(y_saved))
                except Exception:
                    pass

            def _save_geom():
                try:
                    st.setValue(f"{SCOPE_KEY}/width", scope.width())
                    pos = scope.pos()
                    st.setValue(f"{SCOPE_KEY}/pos_x", int(pos.x()))
                    st.setValue(f"{SCOPE_KEY}/pos_y", int(pos.y()))
                    st.setValue(f"{SCOPE_KEY}/geometry", scope.saveGeometry())
                except Exception:
                    pass

            def _clear_ref(*_args):
                try:
                    if getattr(self.ac, "_hevc_preview_scope", None) is scope:
                        setattr(self.ac, "_hevc_preview_scope", None)
                except Exception:
                    pass

            try:
                scope.finished.connect(_save_geom)   # type: ignore
                scope.finished.connect(_clear_ref)   # type: ignore
            except Exception:
                pass

            scope.show()
            scope.raise_()
            scope.activateWindow()
        except Exception as e:
            _warn_console("Oscilloscopio", f"Impossibile aprire lo scope: {e}", self.ac)

def _scope_names_from_gui(af_chain: Optional[str], out_ac: Optional[int], in_ch: int) -> List[str]:
    joined = (af_chain or "").lower()

    # deduci layout dalla -af se possibile
    if "join=inputs=6" in joined or "pan=5.1" in joined or "channel_layout=5.1" in joined:
        return ["L", "R", "C", "LFE", "SL", "SR"]
    if "join=inputs=5" in joined or "channel_layout=5.0" in joined:
        return ["L", "R", "C", "SL", "SR"]
    if "join=inputs=2" in joined or "pan=stereo" in joined or "channel_layout=stereo" in joined:
        return ["L", "R"]

    ch = int(out_ac or in_ch or 2)
    if ch <= 1:
        return ["M"]
    if ch == 2:
        return ["L", "R"]
    if ch == 5:
        return ["L", "R", "C", "SL", "SR"]
    if ch >= 6:
        return ["L", "R", "C", "LFE", "SL", "SR"]
    return [f"Ch{i + 1}" for i in range(ch)]


# ======================================================================
# Entry points
# ======================================================================
def start_preview(ac: Any) -> None:
    _log("[PREVIEW] start_preview()")
    AudioPreview(ac).start()


def run_preview(ac: Any) -> None:
    _log("[PREVIEW] run_preview()")
    start_preview(ac)
