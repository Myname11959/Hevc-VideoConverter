# -*- coding: utf-8 -*-
# scripts/preview.py — Preview audio fedele alla GUI (console-only + scope)
from __future__ import annotations

import os
import sys
import shlex
import json
import subprocess
from pathlib import Path
from typing import Any, Optional, List
import re

# -------------------- Opzioni runtime / path --------------------
USE_PROGRESS = os.getenv("HEVC_PREVIEW_PROGRESS", "1") == "1"
USE_POPUPS = os.getenv("HEVC_PREVIEW_POPUPS", "0") == "1"
TMP_BASE = Path(os.getenv("HEVC_PREVIEW_TMP", "/dev/shm")).expanduser()

FFMPEG = os.environ.get("FFMPEG", "/usr/bin/ffmpeg")
FFPROBE = os.environ.get("FFPROBE", "/usr/bin/ffprobe")

# -------------------- Qt (progress / popups) --------------------
try:
    from PyQt5.QtCore import Qt, QProcess, QEventLoop, QTimer
    from PyQt5.QtWidgets import QApplication, QProgressDialog, QMessageBox

    _QT_OK = True
except Exception:
    _QT_OK = False
    QApplication = object  # type: ignore
    QProgressDialog = object  # type: ignore
    QMessageBox = object  # type: ignore
    Qt = object  # type: ignore
    QProcess = object  # type: ignore
    QEventLoop = object  # type: ignore

# -------------------- Oscilloscopio --------------------
ScopeDialog = None
try:
    from oscilloscope_preview import PreviewDialog as ScopeDialog  # type: ignore
except Exception:
    ScopeDialog = None


# ======================================================================
# Helpers base
# ======================================================================
def _log(msg: str) -> None:
    sys.stdout.write(msg.rstrip() + "\n")
    sys.stdout.flush()


def _warn_console(title: str, message: str, parent=None) -> None:
    _log(f"[WARN] {title}: {message}")
    if USE_POPUPS and _QT_OK:
        try:
            QMessageBox.warning(parent, title, message)
        except Exception:
            pass


def _which(p: str) -> str:
    if Path(p).exists():
        return p
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
            [
                _which(FFPROBE),
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=index",
                "-of",
                "csv=p=0",
                src,
            ],
            capture_output=True,
            text=True,
        )
        if p.returncode != 0:
            return 0
        return sum(1 for ln in (p.stdout or "").splitlines() if ln.strip())
    except Exception:
        return 0


def list_audio_streams(src: str) -> list[dict]:
    try:
        p = subprocess.run(
            [
                _which(FFPROBE),
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_streams",
                "-of",
                "json",
                src,
            ],
            capture_output=True,
            text=True,
        )
        if p.returncode != 0:
            return []
        data = json.loads(p.stdout or "{}")
        return list(data.get("streams") or [])
    except Exception:
        return []


def probe_stream_info(src: str, track_idx: int) -> dict:
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


# ======================================================================
# Risoluzione sorgente/GUI
# ======================================================================
def resolve_source(ac: Any) -> Optional[str]:
    # Priorità: audio esterno esplicito
    try:
        if bool(getattr(ac, "audio_externo", False)) or bool(getattr(ac, "audio_esterno", False)):
            ext = getattr(ac, "external_audio_file", None) or getattr(ac, "audio_external_file", None)
            if ext:
                p = Path(_clean(ext)).expanduser()
                if p.is_file():
                    return str(p)
    except Exception:
        pass

    # Vari nomi attribuito per il file interno
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

    # Qualsiasi QLineEdit in GUI (best effort)
    if _QT_OK:
        try:
            from PyQt5.QtWidgets import QLineEdit

            for le in ac.findChildren(QLineEdit):
                try:
                    t = _clean(le.text())
                    if not t:
                        continue
                    p = Path(t).expanduser()
                    if p.is_file():
                        return str(p)
                except Exception:
                    continue
        except Exception:
            pass
    return None


def resolve_track_index(ac, src=None) -> int:
    """
    Ritorna l'indice 0-based per -map 0:a:N leggendo l'itemData della combo tracce.
    Priorità:
      • cmb_track.currentData() (dict/tuple/string) → prende N reale
      • fallback: currentIndex() con fix per il placeholder in posizione 0
    """
    w = getattr(ac, "cmb_track", None)
    if not (w and hasattr(w, "currentIndex")):
        return 0

    # currentData() con vari formati tollerati
    try:
        data = w.currentData()
        try:
            _log(f"[PREVIEW] itemData={repr(data)}; currentIndex={w.currentIndex()}")
        except Exception:
            pass

        if isinstance(data, dict):
            for k in ("index", "ff_index", "ff_idx", "idx"):
                if k in data:
                    i = int(data[k])
                    if i >= 0:
                        return i
            m = re.search(r"a:(\d+)", str(data.get("map", "")))
            if m:
                return int(m.group(1))

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

    # fallback: indice visivo
    try:
        idx = int(w.currentIndex())
        try:
            d0 = w.itemData(0)
            has_ph = isinstance(d0, (tuple, list)) and d0 and (d0[0] == -1)
        except Exception:
            has_ph = False
        return max(0, idx - 1) if (idx > 0 and has_ph) else max(0, idx)
    except Exception:
        return 0


def resolve_preview_seconds(ac: Any) -> Optional[int]:
    """
    Ritorna i secondi di preview dalla combo durate (cmb_prev).
    Legge prima itemData numerico, poi parse del testo (NN, MM:SS, ecc.).
    """
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
            if "min" in s:
                num = int("".join(ch for ch in s if ch.isdigit()))
                return max(1, num) * 60
            num = int("".join(ch for ch in s if ch.isdigit()))
            return num if num > 0 else None
        except Exception:
            pass

    # Fallback legacy (altri widget possibili)
    for nm in (
        "cmb_preview",
        "cmb_preview_secs",
        "preview_combo",
        "spn_preview_secs",
        "spin_preview_secs",
        "preview_seconds",
    ):
        w = getattr(ac, nm, None)
        if not w:
            continue
        try:
            if hasattr(w, "currentData"):
                d = w.currentData()
                if isinstance(d, (int, float)) and d > 0:
                    return int(d)
            if hasattr(w, "value"):
                v = int(w.value())
                return v if v > 0 else None
            if hasattr(w, "currentText"):
                s = str(w.currentText()).lower().strip()
            elif hasattr(w, "text"):
                s = str(w.text()).lower().strip()
            else:
                continue
            if not s:
                return None
            if "min" in s:
                num = int("".join(ch for ch in s if ch.isdigit()))
                return max(1, num) * 60
            num = int("".join(ch for ch in s if ch.isdigit()))
            return num if num > 0 else None
        except Exception:
            continue

    return None


def resolve_preview_start(ac: Any) -> int:
    """
    Offset di partenza preview in secondi.
      • legge QTimeEdit `te_prev_start` (HH:mm:ss)
      • fallback opzionale: combo `cmb_prev_start` (accetta HH:MM:SS / MM:SS / SS)
      • default 0
    """
    # QTimeEdit consigliato
    w = getattr(ac, "te_prev_start", None)
    if w is not None and hasattr(w, "time"):
        try:
            t = w.time()
            return max(0, int(t.hour()) * 3600 + int(t.minute()) * 60 + int(t.second()))
        except Exception:
            pass

    # Fallback legacy (combo testuale/numerica)
    w = getattr(ac, "cmb_prev_start", None)
    if w is not None:
        try:
            d = w.currentData()
            if isinstance(d, (int, float)) and d >= 0:
                return int(d)
        except Exception:
            pass
        try:
            s = (w.currentText() or "").strip()
            if s:
                parts = [p.strip() for p in s.split(":") if p.strip() != ""]
                if len(parts) == 3:
                    h, m, sec = parts
                    return max(0, int(h)) * 3600 + max(0, int(m)) * 60 + max(0, int(float(sec)))
                if len(parts) == 2:
                    m, sec = parts
                    return max(0, int(m)) * 60 + max(0, int(float(sec)))
                return max(0, int(float(parts[0])))
        except Exception:
            pass

    return 0


# ======================================================================
# Helper: nomi canali per lo scope, fedeli alla GUI
# ======================================================================
def _scope_names_from_gui(af_chain: Optional[str], out_ac: Optional[int], in_ch: int) -> List[str]:
    joined = (af_chain or "").lower()

    if ("pan=stereo" in joined) or ("channel_layout=stereo" in joined) or ("join=inputs=2" in joined):
        return ["L", "R"]
    if ("channel_layout=5.0" in joined) or ("5.0" in joined):
        return ["L", "R", "C", "SL", "SR"]
    if ("pan=5.1" in joined) or ("channel_layout=5.1" in joined) or ("join=inputs=6" in joined):
        return ["L", "R", "C", "LFE", "SL", "SR"]

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
# Preview runner
# ======================================================================
class AudioPreview:
    def __init__(self, ac: Any):
        self.ac = ac
        self.ffmpeg = _which(FFMPEG)
        self.ffprobe = _which(FFPROBE)
        self.pdlg: Optional[QProgressDialog] = None
        self._scope_ref = None
        self._in_ch_for_scope = 2

    # --------- AF dalla GUI (nessun fallback) ---------
    def _af_from_ui(self, in_channels: int) -> tuple[Optional[str], Optional[int], Optional[int]]:
        """
        Ritorna (af_chain, out_ac, force_sr) SENZA fallback:
          • af_chain: esattamente i filtri che la GUI costruisce.
          • out_ac  : solo se richiesto (Stereo / profilo soundbar / mantieni mono).
          • force_sr: solo se la combo SR ha un valore numerico.
        """
        # sample-rate (combo SR)
        force_sr: Optional[int] = None
        for nm in ("cmb_sr", "cmb_samplerate", "cmb_sample_rate", "cmb_rate"):
            w = getattr(self.ac, nm, None)
            if w and hasattr(w, "currentText"):
                s = (w.currentText() or "").strip()
                if s and s.lower() not in ("nessuno", "originale", "orig", "auto"):
                    try:
                        val = int("".join(ch for ch in s if ch.isdigit()))
                        if val > 0:
                            force_sr = val
                    except Exception:
                        pass
                break

        # catena filtri costruita dalla GUI
        filters: list[str] = []
        try:
            if hasattr(self.ac, "_build_filters_chain_from_ui"):
                filters = list(self.ac._build_filters_chain_from_ui(for_preview=True, channels_hint=in_channels))
        except Exception as e:
            _log(f"[PREVIEW] _build_filters_chain_from_ui errore: {e}")
            filters = []

        # de-dup senza cambiare ordine
        seen, clean = set(), []
        for f in filters:
            if f and f not in seen:
                clean.append(f)
                seen.add(f)

        # se l'utente ha messo un limiter, spostalo in coda e ammorbidisci i parametri
        has_limiter = any(f.strip().startswith("alimiter") for f in clean)
        if has_limiter:
            alims = [f for f in clean if f.strip().startswith("alimiter")]
            clean = [f for f in clean if not f.strip().startswith("alimiter")] + alims

            def _soften_alimiter(f: str) -> str:
                if not f.strip().startswith("alimiter"):
                    return f
                return "alimiter=limit=0.965:attack=12:release=300"

            clean = [_soften_alimiter(f) for f in clean]

        # canali richiesti dalla GUI (senza inferenze)
        out_ac: Optional[int] = None
        try:
            if getattr(self.ac, "chk_force_stereo", None) and self.ac.chk_force_stereo.isChecked():
                out_ac = 2
            prof = getattr(self.ac, "_soundbar_profile", "none")
            if prof == "samsung_5_1_ac3":
                out_ac = 6
            elif prof == "samsung_stereo":
                out_ac = 2
            if getattr(self.ac, "chk_keep_mono", None) and self.ac.chk_keep_mono.isChecked() and in_channels == 1:
                out_ac = 1
        except Exception:
            pass

        af_chain = ",".join(clean) if clean else None
        return af_chain, out_ac, force_sr

    # --------- Esecuzione ffmpeg con QProcess + progress ---------
    def _run_ffmpeg_with_qprocess(self, cmd: list[str], total_secs: int | None) -> int:
        if not _QT_OK:
            p = subprocess.run(cmd, capture_output=True, text=True)
            if p.returncode != 0:
                raise RuntimeError(p.stderr or "ffmpeg error")
            return p.returncode

        secs_total = float(total_secs or 0.0)

        pd = QProgressDialog("Generazione preview audio…", "Annulla", 0, 100, self.ac)
        pd.setWindowModality(Qt.ApplicationModal)
        pd.setMinimumDuration(200)
        pd.setValue(0)

        proc = QProcess(self.ac)
        proc.setProcessChannelMode(QProcess.SeparateChannels)
        proc.setProgram(cmd[0])
        proc.setArguments(cmd[1:])

        def _parse_ff_progress_seconds(line: str):
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
                sec = _parse_ff_progress_seconds(ln)
                if sec is not None and secs_total > 0:
                    frac = max(0.0, min(1.0, sec / secs_total))
                    pd.setValue(int(frac * 100))

        proc.readyReadStandardOutput.connect(on_stdout)

        def on_cancel():
            try:
                proc.kill()
            except Exception:
                pass

        pd.canceled.connect(on_cancel)

        loop = QEventLoop()

        def on_finished(_code: int, _status):
            pd.setValue(100)
            pd.close()
            loop.quit()

        proc.finished.connect(on_finished)

        proc.start()
        loop.exec_()

        rc = proc.exitCode()
        if rc != 0:
            err = ""
            try:
                err = bytes(proc.readAllStandardError()).decode("utf-8", "ignore")
            except Exception:
                pass
            raise RuntimeError(err or f"ffmpeg exited with {rc}")
        return rc

    # --------- Avvio preview ---------
    def start(self) -> None:
        # sorgente
        src = resolve_source(self.ac)
        if not src:
            _warn_console("Sorgente mancante", "Nessun file di input valido per la preview.", self.ac)
            return
        _log(f"[PREVIEW] Sorgente: {src}")

        # traccia audio (indice reale)
        track_idx = resolve_track_index(self.ac)
        n_tracks = count_audio_streams(src)
        if n_tracks == 0:
            _warn_console("Preview", "Nessuna traccia audio trovata (o ffprobe è fallito).", self.ac)
            return
        if track_idx >= n_tracks:
            _log(f"[PREVIEW] Traccia richiesta {track_idx} fuori range (0..{n_tracks - 1}). Uso 0.")
            track_idx = 0
        _log(f"[PREVIEW] Traccia: 0:a:{track_idx}")

        # durata/offset
        total_secs = resolve_preview_seconds(self.ac) or 600
        start_off = max(0, int(resolve_preview_start(self.ac)))
        _log(f"[PREVIEW] Durata: {total_secs}s")
        _log(f"[PREVIEW] Start:  {start_off}s")

        # probe input
        info = probe_stream_info(src, track_idx)
        in_ch = int(info.get("channels") or 0) or 2
        self._in_ch_for_scope = in_ch
        _log(f"[PREVIEW] Info traccia: {info or 'n/d'}")

        # filtri/uscita coerenti con la GUI
        af_chain, out_ac, force_sr = self._af_from_ui(in_ch)
        _log(f"[PREVIEW] -af: {af_chain or '(none)'}")

        # WAV temporaneo
        tmp_dir = _ensure_tmp_dir(TMP_BASE / "hevc_preview")
        wav = tmp_dir / "preview_scope.wav"
        try:
            if wav.exists():
                wav.unlink()
        except Exception:
            pass

        # comando ffmpeg (seek PRIMA di -i, progress su stdout)
        cmd = [
            self.ffmpeg,
            "-hide_banner",
            "-nostdin",
            "-progress",
            "pipe:1",
            "-nostats",
            "-y",
        ]
        if start_off > 0:
            cmd += ["-ss", str(int(start_off))]
        cmd += [
            "-i",
            src,
            "-vn",
            "-sn",
            "-dn",
            "-map",
            f"0:a:{int(track_idx)}",
            "-loglevel",
            "error",
        ]
        if af_chain:
            cmd += ["-af", af_chain]
        cmd += ["-c:a", "pcm_s16le"]
        if force_sr:
            cmd += ["-ar", str(int(force_sr))]
        if out_ac:
            cmd += ["-ac", str(int(out_ac))]
        if total_secs:
            cmd += ["-t", str(int(total_secs))]
        cmd += [str(wav)]

        _log("[PREVIEW] CMD: " + " ".join(shlex.quote(x) for x in cmd))

        # run
        try:
            self._run_ffmpeg_with_qprocess(cmd, total_secs)
        except Exception as e:
            _warn_console("Preview terminata", f"ffmpeg ha chiuso con errore:\n{e}", self.ac)
            return

        if not wav.exists():
            _warn_console("Preview", "File WAV non creato.", self.ac)
            return
        _log(f"[PREVIEW] WAV pronto: {wav}")

        # oscilloscopio
        if ScopeDialog is None:
            _log("[SCOPE] Modulo non disponibile: salto.")
            return

        ch_names = _scope_names_from_gui(af_chain, out_ac, in_ch)
        _log(f"[SCOPE] Piste GUI → {ch_names}")

        try:
            scope = ScopeDialog(str(wav), self.ac, channel_names=ch_names, auto_cleanup=True)
            self._scope_ref = scope
            setattr(self.ac, "_scope_dialog", scope)

            if hasattr(scope, "player"):
                try:
                    scope.player.stop()
                except Exception:
                    pass

            try:
                scope.destroyed.connect(lambda *_: getattr(scope, "player", None) and scope.player.stop())
            except Exception:
                pass

            scope.show()

            try:
                n = len(ch_names)
                if n <= 1:
                    layout_key = "mono"
                elif n == 2:
                    layout_key = "stereo"
                elif n == 5:
                    layout_key = "5.0"
                elif n >= 6:
                    layout_key = "5.1"
                else:
                    layout_key = "stereo"

                QTimer.singleShot(0, lambda lk=layout_key, cn=ch_names: scope.set_channel_layout(lk, cn))
            except Exception:
                pass

            scope.raise_()
            scope.activateWindow()

        except Exception as e:
            _warn_console("Oscilloscopio", f"Impossibile aprire lo scope: {e}", self.ac)


# ======================================================================
# Entry points compatibili con il wrapper
# ======================================================================
def start_preview(ac: Any) -> None:
    _log("[PREVIEW] start_preview()")
    _log(f"[PREVIEW] modulo: {__file__}")
    AudioPreview(ac).start()


def run_preview(ac: Any) -> None:
    _log("[PREVIEW] run_preview()")
    start_preview(ac)
