#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sys
import json
import subprocess
import shutil
import time
from pathlib import Path
from typing import List, Optional

# [DEBUG] Log su console opzionale: esporta LDVD_DEBUG=1
LDVD_DEBUG = os.getenv("LDVD_DEBUG", "0") not in ("", "0", "false", "no", "False", "No")


def _dprint(*a, **k):
    if LDVD_DEBUG:
        try:
            print(*a, **k, flush=True)
        except Exception:
            pass


def _find_subtitle_edit_cmd(self) -> Optional[List[str]]:
    # 1) override completo da env
    cmd_env = os.getenv("SUBTITLE_EDIT_CMD")
    if cmd_env:
        try:
            import shlex
            parts = shlex.split(cmd_env)
            if parts:
                return parts
        except Exception:
            return [cmd_env]

    # 2) SNAP: preferisci l'EXE vero + mono (evita wrapper /snap/bin/subtitle-edit)
    snap_exe = "/snap/subtitle-edit/current/subedit/SubtitleEdit.exe"
    if os.path.exists(snap_exe):
        mono_bin = shutil.which("mono") or "mono"
        return [mono_bin, snap_exe]

    # 3) binario normale (deb/flatpak/altro) se esiste
    se_bin = shutil.which("subtitle-edit") or shutil.which("subtitleedit") or shutil.which("SubtitleEdit")
    if se_bin:
        return [se_bin]

    return None

# PyQt
from PyQt5.QtCore import QObject, QTimer, QItemSelectionModel, QThread, Qt, pyqtSignal
from PyQt5.QtWidgets import QFileDialog, QMessageBox, QShortcut, QInputDialog
from PyQt5.QtGui import QKeySequence

# ===== Import robusti: prima relativi (package), poi fallback stessa cartella =====
try:
    from .gui import DVDExtractorView
    from .dvd_probe import (
        get_cdrom_mount_point,
        get_dvd_title,
        suggest_movie_title,
        get_dvd_device,
    )
    from .vob_utils import natural_sort_vobs
    from .qworkers import CopyWorker
    from .titlecase_utils import title_case
    from .fallback_vobcopy import VobcopyWorker, VobcopyStageVTSWorker
    from .vob_sidecar import postprocess_vob, sidecar_path_for, load_sidecar
    from .srt_ocr import extract_srt_for_vob, run_srt_ocr_for_vob
except Exception:
    import importlib.util

    PKG_DIR = os.path.dirname(os.path.abspath(__file__))
    if PKG_DIR not in sys.path:
        sys.path.insert(0, PKG_DIR)

    from gui import DVDExtractorView  # type: ignore
    from dvd_probe import (  # type: ignore
        get_cdrom_mount_point,
        get_dvd_title,
        suggest_movie_title,
        get_dvd_device,
    )
    from vob_utils import natural_sort_vobs  # type: ignore
    from qworkers import CopyWorker  # type: ignore
    from titlecase_utils import title_case  # type: ignore
    from fallback_vobcopy import VobcopyWorker, VobcopyStageVTSWorker  # type: ignore

    try:
        from vob_sidecar import postprocess_vob, sidecar_path_for, load_sidecar  # type: ignore
    except Exception:
        _vp = os.path.join(PKG_DIR, "vob_sidecar.py")
        spec = importlib.util.spec_from_file_location("vob_sidecar", _vp)
        if spec and spec.loader:
            _m = importlib.util.module_from_spec(spec)  # type: ignore
            spec.loader.exec_module(_m)  # type: ignore
            postprocess_vob = getattr(_m, "postprocess_vob")  # type: ignore
            sidecar_path_for = getattr(_m, "sidecar_path_for")  # type: ignore
            load_sidecar = getattr(_m, "load_sidecar")  # type: ignore
        else:
            raise

    try:
        from srt_ocr import extract_srt_for_vob, run_srt_ocr_for_vob  # type: ignore
    except Exception:
        _sp = os.path.join(PKG_DIR, "srt_ocr.py")
        spec = importlib.util.spec_from_file_location("srt_ocr", _sp)
        if spec and spec.loader:
            _m = importlib.util.module_from_spec(spec)  # type: ignore
            spec.loader.exec_module(_m)  # type: ignore
            extract_srt_for_vob = getattr(_m, "extract_srt_for_vob")  # type: ignore
            run_srt_ocr_for_vob = getattr(_m, "run_srt_ocr_for_vob")  # type: ignore
        else:

            def extract_srt_for_vob(*a, **k):  # type: ignore
                return []

            def run_srt_ocr_for_vob(*a, **k):  # type: ignore
                return []


# ========================= Controller principale ==========================
class DVDExtractorController(QObject):
    """
    Preferenze in ~/.dvd_ripper_prefs.json:
      {
        "last_dir": "...",
        "title_lang": "it|en",
        "last_queue": ["...vob", ...],
        "last_output_vob": "/percorso/ultimo.vob",
        "ocr_srt": true|false
      }
    """

    vob_handoff = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = DVDExtractorView()

        # Toolbar "Clear"
        if hasattr(self.view, "actClear"):
            self.view.actClear.triggered.connect(self._on_clear_all)

        self.title_lang: str = "it"
        self.queue: List[str] = []
        self._worker: Optional[QThread] = None
        self.last_dir: Optional[str] = None
        self.last_output_vob: Optional[str] = None
        self.ocr_srt_enabled: bool = False

        # Percorso output corrente (job)
        self._current_out_path: Optional[str] = None

        # --- ETA / progress state ---
        self._copy_start_ts: Optional[float] = None
        self._copy_last_pct: int = 0

        self._eta_timer = QTimer(self)
        self._eta_timer.setInterval(500)
        self._eta_timer.timeout.connect(self._eta_tick)

        self._eta_remain_s: Optional[float] = None
        self._eta_last_tick_ts: Optional[float] = None

        # --- Staging polling (progress reale: dimensione file in dest_dir) ---
        self._stage_poll_timer = QTimer(self)
        self._stage_poll_timer.setInterval(250)  # più basso = più fluido
        self._stage_poll_timer.timeout.connect(self._stage_poll_tick)
        self._stage_poll_dir: Optional[str] = None
        self._stage_poll_prefix: Optional[str] = None

        # Stime (solo per avere un totale "largo" e non arrivare mai a 100% troppo presto)
        self._eta_expected_stage_bytes: int = 0
        self._eta_expected_concat_bytes: int = 0

        # Modalità BYTE (globale)
        self._eta_phase: str = "Vobcopy"
        self._eta_total_bytes: int = 0
        self._eta_done_bytes: int = 0
        self._eta_last_done_bytes: int = 0
        self._eta_last_bytes_ts: Optional[float] = None
        self._eta_speed_ema_bps: Optional[float] = None
        self._eta_stage_total_bytes: int = 0

        # Fallback percent
        self._eta_speed_ema: Optional[float] = None   # %/sec
        self._eta_last_p: int = 0
        self._eta_last_p_ts: Optional[float] = None

        # Dati per Subtitle Edit
        self._ifo_for_subedit: Optional[str] = None
        self._last_subedit_workdir: Optional[str] = None
        self._last_subedit_ifo: Optional[str] = None

        # Tracking VLC
        self._vlc_proc = None
        self._vlc_timer = None
        self._vlc_prev_status = None

        # Fallback handling: evita popup “fallita” sul FINISHED del CopyWorker che chiede fallback
        self._fallback_in_progress: bool = False

        # Wiring View → Controller
        v = self.view
        v.request_refresh_dvd.connect(self._on_refresh_dvd)
        v.request_open_folder.connect(self._on_open_folder)
        v.request_add_files.connect(self._on_add_files)
        v.request_eject.connect(self._on_eject)
        v.request_close_tray.connect(self._on_close_tray)
        v.request_extract.connect(self._on_extract)
        v.dir_activated.connect(self._on_dir_activated)
        v.file_activated.connect(self._on_file_activated)

        # Apri in VLC
        if hasattr(v, "request_open_in_vlc"):
            v.request_open_in_vlc.connect(self._on_open_in_vlc)

        # Apri sottotitoli .srt collegati (sidecar)
        if hasattr(v, "request_open_srt"):
            v.request_open_srt.connect(self._on_open_srt)

        # Apri Subtitle Edit
        if hasattr(v, "request_open_subtitle_edit"):
            v.request_open_subtitle_edit.connect(self._on_open_subtitle_edit)

        # Handoff HEVC
        if hasattr(v, "request_hevc_handoff"):
            v.request_hevc_handoff.connect(self._on_handoff_to_hevc)
        if hasattr(v, "request_handoff_to_hevc"):
            v.request_handoff_to_hevc.connect(self._on_handoff_to_hevc)

        v.request_cancel.connect(self._on_cancel)
        v.request_exit.connect(self._on_exit)
        v.request_set_title_lang.connect(self._on_change_title_lang)
        v.open_containing_requested.connect(self._on_open_containing)
        v.request_add_selection.connect(self._on_add_selection)
        v.request_remove_selected_from_queue.connect(self._on_remove_from_queue)
        v.request_move_up.connect(self._on_move_up)
        v.request_move_down.connect(self._on_move_down)
        v.request_clear_queue.connect(self._on_clear_queue)

        # Lingua di default per il titlecase
        self.view.set_titlecase_lang(self.title_lang)

        # Preferenze
        self._load_prefs()

        # Stato iniziale HEVC (disabilitato finché non estrai)
        self._set_handoff_enabled(False)

        # OCR SRT: inizializza stato view in base alle prefs
        try:
            self.view.set_ocr_srt_enabled(self.ocr_srt_enabled)
        except Exception:
            pass

        # Root iniziale
        if self.last_dir and os.path.isdir(self.last_dir):
            try:
                self.view.set_root_path(self.last_dir)
            except Exception:
                pass
        else:
            try:
                self.view.set_root_path("/")
            except Exception:
                pass

    # --------------- API pubbliche ---------------
    def show(self):
        if not getattr(self, "_wired_show_once", False):
            self._wired_show_once = True
            v = self.view
            if hasattr(v, "request_set_ocr_srt"):
                try:
                    v.request_set_ocr_srt.connect(self._on_change_ocr_srt)
                except Exception:
                    pass
        self.view.show()

    # --------------- Preferenze ---------------
    def _prefs_path(self) -> Path:
        return Path.home() / ".dvd_ripper_prefs.json"

    def _load_prefs(self) -> None:
        self._last_queue_raw = []
        self.last_output_vob = None
        self.ocr_srt_enabled = False
        try:
            p = self._prefs_path()
            if not p.exists():
                return
            data = json.loads(p.read_text(encoding="utf-8"))

            self.last_dir = data.get("last_dir") or None
            lang = (data.get("title_lang") or "it").lower()
            if lang in ("it", "en"):
                self.title_lang = lang
                self.view.set_titlecase_lang(lang)

            self.ocr_srt_enabled = bool(data.get("ocr_srt", False))
            try:
                self.view.set_ocr_srt_enabled(self.ocr_srt_enabled)
            except Exception:
                pass
        except Exception:
            self._last_queue_raw = []
            self.last_output_vob = None
            self.ocr_srt_enabled = False

    def _save_prefs(self) -> None:
        try:
            data = {
                "last_dir": self.last_dir or "",
                "title_lang": self.title_lang,
                "last_queue": self.queue,
                "last_output_vob": self.last_output_vob or "",
                "ocr_srt": bool(self.ocr_srt_enabled),
            }
            self._prefs_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _save_last_queue(self) -> None:
        try:
            self._save_prefs()
        except Exception:
            pass

    def _restore_last_queue(self) -> None:
        valid = [
            p
            for p in getattr(self, "_last_queue_raw", [])
            if p.lower().endswith(".vob") and os.path.isfile(p)
        ]
        if valid:
            self.queue = valid
            self._sync_queue_view()
        self._last_queue_raw = []

    # --------------- Snapshot IFO (lsdvd) ---------------
    def _try_write_lsdvd_snapshot(self, out_path: str):
        import ast
        import re
        import xml.etree.ElementTree as ET
        import subprocess

        def _run(cmd):
            r = subprocess.run(cmd, capture_output=True, text=True, check=False)
            return r.returncode, (r.stdout or ""), (r.stderr or "")

        base = Path(out_path).with_suffix("")
        dst = base.with_suffix(".lsdvd.json")

        dev = get_dvd_device() or get_cdrom_mount_point() or "/dev/sr0"
        if not dev:
            return

        rc, py_out, _ = _run(["lsdvd", "-Oy", "-a", "-s", str(dev)])
        lsdvd_py = None
        if rc == 0 and py_out.strip().startswith("lsdvd"):
            try:
                payload = py_out.split("=", 1)[1].strip()
                obj = ast.literal_eval(payload)
                if isinstance(obj, dict):
                    lsdvd_py = obj
            except Exception:
                lsdvd_py = None

        longest = None
        if lsdvd_py:
            try:
                lt = int(lsdvd_py.get("longest_track") or 0)
                if lt > 0:
                    longest = lt
            except Exception:
                longest = None
        if not longest and lsdvd_py and lsdvd_py.get("track"):
            best_i, best_len = 0, -1.0
            for i, t in enumerate(lsdvd_py.get("track") or []):
                try:
                    L = float(t.get("length") or 0.0)
                except Exception:
                    L = 0.0
                if L > best_len:
                    best_i, best_len = i, L
            longest = best_i + 1 if (best_len >= 0) else 1

        if longest is None:
            longest = 1

        chapters = []
        rcx, xml_out, _ = _run(["lsdvd", "-Ox", "-t", str(longest), str(dev)])
        if rcx == 0 and xml_out.strip().startswith("<"):
            try:
                root = ET.fromstring(xml_out)
                T = root.find(".//track")
                segs = []
                if T is not None:
                    for c in T.findall("./chapter"):
                        ltxt = (c.get("length") or c.text or "").strip()
                        m = re.match(r"(?:(\d+):)?(\d+):(\d+)\.(\d+)", ltxt)
                        if m:
                            hh = int(m.group(1) or "0")
                            mm = int(m.group(2))
                            ss = int(m.group(3))
                            ms = int(m.group(4))
                            segs.append(hh * 3600 + mm * 60 + ss + ms / 1000.0)
                if segs:
                    chapters = segs
            except Exception:
                chapters = []

        if lsdvd_py is None:
            rcpt, txt, _ = _run(["lsdvd", str(dev)])
            lsdvd_py = {"device": str(dev), "track": [], "longest_track": longest}
            try:
                import re as _re
                tracks = []
                for m in _re.finditer(
                    r"Title:\s*(\d+),\s*Length:\s*(\d+):(\d+):(\d+)\.(\d+)\s*,\s*Chapters:\s*(\d+)",
                    txt,
                ):
                    hh, mm, ss, ms = (
                        int(m.group(2)),
                        int(m.group(3)),
                        int(m.group(4)),
                        int(m.group(5)),
                    )
                    total = hh * 3600 + mm * 60 + ss + ms / 1000.0
                    tracks.append({"length": total, "audio": [], "subp": []})
                if tracks:
                    lsdvd_py["track"] = tracks
            except Exception:
                pass

        idx = max(0, int(longest) - 1)
        while len(lsdvd_py.setdefault("track", [])) <= idx:
            lsdvd_py["track"].append({})
        lsdvd_py["track"][idx].setdefault("chapters", chapters)
        lsdvd_py.setdefault("device", str(dev))
        lsdvd_py.setdefault("longest_track", int(longest))

        dst.write_text(json.dumps({"lsdvd": lsdvd_py}, ensure_ascii=False, indent=2), encoding="utf-8")

    # ========================= ETA globale (byte reali) =========================

    def _eta_begin(self, total_bytes: int | None = None, phase: str = "Vobcopy") -> None:
        """
        Inizio job ETA:
        - se total_bytes > 0 -> modalità BYTE (vera, staging+concat)
        - se total_bytes è None/0 -> modalità PERCENT (fallback legacy)
        """
        now = time.time()

        self._copy_start_ts = now
        self._copy_last_pct = 0

        self._eta_phase = (phase or "Vobcopy").strip() or "Vobcopy"

        tb = 0
        try:
            tb = int(total_bytes) if total_bytes else 0
        except Exception:
            tb = 0

        self._eta_total_bytes = max(0, tb)
        self._eta_done_bytes = 0
        self._eta_last_done_bytes = 0
        self._eta_last_bytes_ts = now
        self._eta_speed_ema_bps = None

        self._eta_remain_s = None
        self._eta_last_tick_ts = now

        self._eta_speed_ema = None
        self._eta_last_p = 0
        self._eta_last_p_ts = now

        if not self._eta_timer.isActive():
            self._eta_timer.start()

        self._render_eta_line()

    def _eta_stop(self) -> None:
        try:
            if self._eta_timer.isActive():
                self._eta_timer.stop()
        except Exception:
            pass

        self._eta_remain_s = None
        self._eta_last_tick_ts = None

        self._eta_total_bytes = 0
        self._eta_done_bytes = 0
        self._eta_last_done_bytes = 0
        self._eta_last_bytes_ts = None
        self._eta_speed_ema_bps = None

        self._eta_speed_ema = None
        self._eta_last_p = 0
        self._eta_last_p_ts = None

    def _eta_switch_phase(self, phase: str) -> None:
        now = time.time()
        self._eta_phase = (phase or "").strip() or getattr(self, "_eta_phase", "Vobcopy")

        self._eta_speed_ema_bps = None
        self._eta_speed_ema = None

        self._eta_last_done_bytes = int(getattr(self, "_eta_done_bytes", 0) or 0)
        self._eta_last_bytes_ts = now
        self._eta_last_p = int(getattr(self, "_copy_last_pct", 0) or 0)
        self._eta_last_p_ts = now

        self._eta_last_tick_ts = now
        self._render_eta_line()

    def _eta_update_bytes(self, done_bytes: int, total_bytes: int, phase: str | None = None) -> None:
        now = time.time()

        if phase:
            ph = phase.strip()
            if ph and ph != getattr(self, "_eta_phase", ""):
                self._eta_switch_phase(ph)

        try:
            total = int(total_bytes)
        except Exception:
            total = 0
        total = max(1, total)
        self._eta_total_bytes = total

        try:
            done = int(done_bytes)
        except Exception:
            done = 0
        done = max(0, min(done, total))

        prev_done = int(getattr(self, "_eta_done_bytes", 0) or 0)
        if done < prev_done:
            done = prev_done
        self._eta_done_bytes = done

        last_done = int(getattr(self, "_eta_last_done_bytes", done) or done)
        last_ts = getattr(self, "_eta_last_bytes_ts", None)

        dp = done - last_done
        dt = None
        if last_ts is not None:
            try:
                dt = max(0.0001, now - float(last_ts))
            except Exception:
                dt = None

        new_bps = None
        if dp > 0 and dt is not None:
            new_bps = float(dp) / float(dt)

        ema = getattr(self, "_eta_speed_ema_bps", None)
        if new_bps is not None and new_bps > 0:
            if ema is None:
                ema = new_bps
            else:
                alpha = 0.25
                ema = alpha * new_bps + (1.0 - alpha) * float(ema)
            self._eta_speed_ema_bps = ema

        remain = None
        if done >= total:
            remain = 0.0
        else:
            use_bps = float(self._eta_speed_ema_bps) if getattr(self, "_eta_speed_ema_bps", None) else None
            if use_bps and use_bps > 1e-6:
                remain = float(total - done) / use_bps
                remain = max(0.0, min(remain, 99 * 60 + 59))
                if remain <= 0.0:
                    remain = 1.0

        self._eta_remain_s = remain
        self._eta_last_tick_ts = now

        try:
            p_calc = int((done * 100) / total)
        except Exception:
            p_calc = 0
        p_calc = max(0, min(100, p_calc))

        last_pct = int(getattr(self, "_copy_last_pct", 0) or 0)
        p = p_calc if p_calc >= last_pct else last_pct
        self._copy_last_pct = p

        try:
            self.view.set_progress(p)
        except Exception:
            pass

        self._eta_last_done_bytes = done
        self._eta_last_bytes_ts = now

        self._render_eta_line()

    def _eta_tick(self) -> None:
        """
        Tick ETA: usa velocità media (%/sec) e smoothing.
        FIX: non mostrare mai 00:00 finché p < 100 (min 00:01).
        """
        import time

        now = time.time()

        try:
            p = int(getattr(self, "_copy_last_pct", 0) or 0)
        except Exception:
            p = 0
        p = max(0, min(100, p))

        start = getattr(self, "_copy_start_ts", None)
        if not start or p <= 0 or p >= 100:
            self._eta_remain_s = 0.0 if p >= 100 else None
            self._render_eta_line()
            return

        elapsed = max(0.2, now - float(start))
        avg_speed = float(p) / float(elapsed)  # %/sec

        ema = getattr(self, "_eta_speed_ema", None)
        alpha = 0.08
        if ema is None:
            ema = avg_speed
        else:
            ema = (1.0 - alpha) * float(ema) + alpha * float(avg_speed)
        self._eta_speed_ema = ema

        if ema > 1e-6:
            remain = float(100 - p) / float(ema)

            # clamp
            remain = max(0.0, min(remain, 99 * 60 + 59))

            # ✅ FIX: mai 00:00 finché non sei a 100%
            if p < 100 and remain < 1.0:
                remain = 1.0

            self._eta_remain_s = remain
        else:
            self._eta_remain_s = None

        self._render_eta_line()

    def _estimate_dvd_bytes(self, mount: str, wanted_names: list[str], vts_num: int) -> tuple[int, int]:
        """
        Stima i byte leggendo le dimensioni dei file sul DVD (VIDEO_TS).
        Ritorna: (stage_total_bytes, concat_total_bytes)

        stage_total = VOB+IFO+BUP (quello che vobcopy scriverà nello staging)
        concat_total = solo VOB (quello che verrà letto per creare il fileone)
        """
        stage = 0
        concat = 0
        video_ts = Path(mount) / "VIDEO_TS"
        pref = f"VTS_{int(vts_num):02d}_".upper()

        # Se wanted_names è vuoto, stimiamo tutti i VTS_xx_* (fallback)
        names = wanted_names[:] if wanted_names else []
        if not names and video_ts.is_dir():
            try:
                for p in video_ts.iterdir():
                    if not p.is_file():
                        continue
                    up = p.name.upper()
                    if up.startswith(pref) and up.endswith((".VOB", ".IFO", ".BUP")):
                        names.append(up)
            except Exception:
                pass

        # Somma dimensioni reali
        for n in names:
            try:
                p = video_ts / n
                if not p.is_file():
                    continue
                sz = p.stat().st_size
                stage += sz
                if n.upper().endswith(".VOB"):
                    concat += sz
            except Exception:
                pass

        # “Allunghiamo” un filo per non arrivare mai a 100% prima del termine reale
        # (meglio più lento che più veloce, come hai chiesto)
        if stage > 0:
            stage = int(stage * 1.08)
        if concat > 0:
            concat = int(concat * 1.08)

        # fallback minimo
        stage = max(stage, 1)
        concat = max(concat, 1)
        return stage, concat

    def _stop_stage_polling(self) -> None:
        """Ferma il polling staging."""
        try:
            t = getattr(self, "_stage_poll_timer", None)
            if t and t.isActive():
                t.stop()
        except Exception:
            pass


    def _on_stage_totals(self, stage_total: int, vobs_total: int) -> None:
        try:
            st = int(stage_total)
        except Exception:
            st = 0
        try:
            vb = int(vobs_total)
        except Exception:
            vb = 0

        self._eta_stage_total_bytes = max(0, st)
        global_total = max(1, self._eta_stage_total_bytes + max(0, vb))
        self._eta_begin(total_bytes=global_total, phase="Vobcopy")

    def _on_stage_bytes(self, done: int, stage_total: int) -> None:
        global_total = int(getattr(self, "_eta_total_bytes", 0) or 0)
        if global_total <= 0:
            try:
                global_total = max(1, int(stage_total))
            except Exception:
                global_total = 1
            self._eta_begin(total_bytes=global_total, phase="Vobcopy")

        self._eta_update_bytes(int(done), global_total, phase="Vobcopy")

    def _on_concat_bytes(self, done: int, total: int) -> None:
        stage_total = int(getattr(self, "_eta_stage_total_bytes", 0) or 0)
        global_total = int(getattr(self, "_eta_total_bytes", 0) or 0)

        try:
            done_i = max(0, int(done))
        except Exception:
            done_i = 0
        try:
            total_i = max(1, int(total))
        except Exception:
            total_i = 1

        # Se per qualche motivo non avevamo ancora un totale globale, impostiamolo adesso (fallback).
        if global_total <= 0:
            global_total = max(1, stage_total + int(total_i * 1.08))
            self._eta_total_bytes = global_total

        # clamp su total_i per evitare overflow strani
        if done_i > total_i:
            done_i = total_i

        global_done = stage_total + done_i
        if global_done > global_total:
            global_done = global_total

        self._eta_update_bytes(global_done, global_total, phase="Concat")

    def _on_progress(self, val: int):
        """
        Progress callback (staging vobcopy / copia).
        - NON resetta il timer su p==0 (bug attuale).
        - Calcola una stima di durata totale e aggiorna ETA anche quando la % non cambia,
          tramite QTimer (tick).
        """
        import time
        try:
            p = int(val)
        except Exception:
            p = 0
        p = max(0, min(100, p))

        now = time.time()
        last_pct = getattr(self, "_copy_last_pct", -1)

        # Se la % cala (es. nuovo job), allora sì: reset stima e start
        if getattr(self, "_copy_start_ts", None) is None or p < last_pct:
            self._copy_start_ts = now
            self._eta_total_s = None  # reset stima "tempo totale"
            self._eta_last_txt = None

        self._copy_last_pct = p
        self._eta_current_pct = p

        # Aggiorna stima tempo totale solo se ho p>0
        # (stima: total = elapsed / (p/100))
        if p > 0:
            try:
                elapsed = max(0.001, now - float(self._copy_start_ts))
                total_est = elapsed * 100.0 / float(p)

                prev = getattr(self, "_eta_total_s", None)
                if prev is None:
                    self._eta_total_s = total_est
                else:
                    # smoothing per evitare rimbalzi (EMA)
                    alpha = 0.20
                    self._eta_total_s = (1.0 - alpha) * prev + alpha * total_est
            except Exception:
                pass

        # Assicura timer ETA attivo (così la mm:ss scende anche a % ferma)
        try:
            t = self._ensure_eta_timer()
            if not t.isActive():
                t.start()
        except Exception:
            pass

        # Aggiorna subito la riga (oltre al tick)
        try:
            self._render_eta_line(now, force=True)
        except Exception:
            pass

        try:
            eta_dbg = getattr(self, "_eta_last_eta", "--:--")
            _dprint(f"[copy] progress={p}% ETA={eta_dbg}")
        except Exception:
            pass

    def _ensure_eta_timer(self):
        """
        Crea (lazy) un QTimer che aggiorna la riga Vobcopy ogni 250ms.
        In GUI vedrai cambiare la mm:ss una volta al secondo, come vuoi tu.
        """
        try:
            t = getattr(self, "_eta_timer", None)
        except Exception:
            t = None

        if t is None:
            from PyQt5.QtCore import QTimer
            t = QTimer(self.view)  # parent = view (così muore con la GUI)
            t.setInterval(250)
            t.timeout.connect(self._on_eta_tick)
            self._eta_timer = t

        return t


    def _on_eta_tick(self):
        import time
        now = time.time()

        # Se non c'è un job attivo, fermo il timer
        if getattr(self, "_copy_start_ts", None) is None:
            try:
                self._eta_timer.stop()
            except Exception:
                pass
            return

        try:
            self._render_eta_line(now, force=False)
        except Exception:
            pass


    def _format_eta_mmss(self, seconds) -> str:
        if seconds is None:
            return "--:--"
        try:
            s = int(round(float(seconds)))
        except Exception:
            return "--:--"
        if s < 0:
            s = 0
        m, ss = divmod(s, 60)
        return f"{m:02d}:{ss:02d}"

    def _make_bar(self, pct: int, width: int = 22) -> str:
        try:
            pct = int(pct)
        except Exception:
            pct = 0
        pct = max(0, min(100, pct))
        filled = int(round((pct / 100.0) * width))
        if filled <= 0:
            return "[" + "-" * width + "]"
        if filled >= width:
            return "[" + "=" * width + "]"
        return "[" + "=" * (filled - 1) + ">" + "-" * (width - filled) + "]"

    def _render_eta_line(self, now=None, force: bool = False) -> None:
        """
        Render riga progress: compatibile sia con chiamate vecchie senza argomenti,
        sia con chiamate nuove che passano 'now'.

        Mostra countdown anche quando la % non cambia, usando:
          remain = eta_total_s - elapsed
        """
        import time

        if now is None:
            now = time.time()

        # percent corrente
        try:
            p = int(getattr(self, "_eta_current_pct", getattr(self, "_copy_last_pct", 0)) or 0)
        except Exception:
            p = 0
        p = max(0, min(100, p))

        eta_str = "--:--"
        if p >= 100:
            eta_str = "00:00"
        else:
            remain = None

            # preferisci countdown da stima "tempo totale"
            total_s = getattr(self, "_eta_total_s", None)
            start_ts = getattr(self, "_copy_start_ts", None)
            if total_s is not None and start_ts is not None:
                try:
                    remain = float(total_s) - (now - float(start_ts))
                except Exception:
                    remain = None

            # fallback: remain_s (byte-mode o altro)
            if remain is None:
                remain = getattr(self, "_eta_remain_s", None)

            if remain is not None:
                try:
                    rem = float(remain)
                except Exception:
                    rem = None
                if rem is not None:
                    # mai 00:00 finché non è 100%
                    if rem < 1.0:
                        rem = 1.0
                    eta_str = self._format_eta_mmss(rem)

        bar = self._make_bar(p, width=22)

        phase = (getattr(self, "_eta_phase", "") or "").strip()
        phase_tok = ""
        if phase and phase.lower() not in ("vobcopy",):
            phase_tok = f"{phase} "

        txt = f"Vobcopy: {bar} {phase_tok}{p:3d}% {eta_str}"

        last = getattr(self, "_eta_last_txt", None)
        if (not force) and (last == txt):
            return
        self._eta_last_txt = txt

        try:
            self.view.set_progress_stage(txt)
        except Exception:
            pass

    # --- Apri DVD in VLC -------------------------------------------------
    def _on_open_in_vlc(self) -> None:
        dev = self._guess_dvd_device()
        if not dev:
            self.view.set_status("Nessun lettore DVD trovato (/dev/sr0, /dev/dvd, /dev/cdrom).")
            return

        if self._vlc_proc is not None:
            try:
                if self._vlc_proc.poll() is None:
                    self.view.set_status("VLC è già in esecuzione.")
                    return
            except Exception:
                self._vlc_proc = None

        try:
            self._vlc_prev_status = self.view.lblStatus.text()
        except Exception:
            self._vlc_prev_status = None

        cmd = self._build_vlc_dvd_cmd(dev)
        self.view.set_status(f"Avvio VLC su {dev}…")
        try:
            print(f"[LDVD] Avvio VLC: {cmd}")
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._vlc_proc = proc

            if self._vlc_timer is None:
                self._vlc_timer = QTimer(self)
                self._vlc_timer.setInterval(1500)
                self._vlc_timer.timeout.connect(self._check_vlc_process)
            if not self._vlc_timer.isActive():
                self._vlc_timer.start()

        except Exception as e:
            self.view.set_status(f"Errore avvio VLC: {e}")

    def _guess_dvd_device(self) -> str | None:
        for cand in ("/dev/sr0", "/dev/dvd", "/dev/cdrom"):
            if os.path.exists(cand):
                return cand
        return None

    def _build_vlc_dvd_cmd(self, dev: str) -> list[str]:
        vlc_bin = shutil.which("vlc") or "/usr/bin/vlc"
        mrl = "dvdsimple://" + dev
        return [vlc_bin, mrl]

    def _check_vlc_process(self):
        proc = getattr(self, "_vlc_proc", None)
        if proc is None:
            if getattr(self, "_vlc_timer", None):
                self._vlc_timer.stop()
            return

        try:
            rc = proc.poll()
        except Exception:
            rc = 0

        if rc is None:
            return

        self._vlc_proc = None
        if getattr(self, "_vlc_timer", None):
            self._vlc_timer.stop()

        try:
            txt = self.view.lblStatus.text()
        except Exception:
            txt = ""

        if "VLC" in txt or "Avvio VLC" in txt:
            prev = getattr(self, "_vlc_prev_status", None)
            if prev:
                self.view.set_status(prev)
            else:
                self.view.set_status("Pronto.")
        self._vlc_prev_status = None

    def _open_with_xdg(self, path: str) -> None:
        if not path or not os.path.isfile(path):
            QMessageBox.information(self.view, "Apri .srt", "Il file selezionato non esiste più sul disco.")
            return
        try:
            subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.view.set_status(f"Apro .srt: {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.warning(self.view, "Apri .srt", f"Impossibile aprire il file:\n{e}")

    # --- Apri .srt collegati -------------------------------------------------
    def _on_open_srt(self) -> None:
        base_dir: Optional[Path] = None

        vob_path = getattr(self, "last_output_vob", None)
        if vob_path:
            try:
                v = Path(vob_path).resolve()
                if v.is_file():
                    candidate = v.parent
                    base_dir = candidate
            except Exception:
                pass

        if base_dir is None:
            workdir = getattr(self, "_last_subedit_workdir", None)
            if workdir:
                try:
                    wd = Path(workdir).resolve()
                    if wd.is_dir():
                        base_dir = wd
                except Exception:
                    pass

        if base_dir is None or not base_dir.exists():
            QMessageBox.information(
                self.view,
                "Apri .srt",
                "Non ho trovato nessuna cartella con file .srt collegati.\n"
                "Assicurati di aver estratto almeno un VOB e/o completato l'OCR.",
            )
            return

        try:
            if str(base_dir).startswith("/dev/"):
                QMessageBox.information(
                    self.view,
                    "Apri .srt",
                    "La sorgente attuale sembra essere un device (/dev/...).\n"
                    "Non apro la root del DVD. Estrai prima il VOB su disco.",
                )
                return
        except Exception:
            pass

        base_dir_str = str(base_dir)

        try:
            self.view.set_status(f"Apro cartella VOB/.srt: {base_dir_str}")
        except Exception:
            pass

        try:
            if os.name == "nt":
                os.startfile(base_dir_str)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", base_dir_str])
            else:
                subprocess.Popen(["xdg-open", base_dir_str])
        except Exception as e:
            QMessageBox.warning(self.view, "Apri .srt", f"Impossibile aprire la cartella:\n{e}")

    # --- Subtitle Edit -------------------------------------------------
    def _find_subtitle_edit_cmd(self) -> Optional[List[str]]:
        cmd_env = os.getenv("SUBTITLE_EDIT_CMD")
        if cmd_env:
            try:
                import shlex
                parts = shlex.split(cmd_env)
                if parts:
                    return parts
            except Exception:
                return [cmd_env]

        # Snap wrapper (preferito e stabile anche da .desktop)
        if os.path.exists("/snap/bin/subtitle-edit"):
            return ["/snap/bin/subtitle-edit"]

        se_bin = shutil.which("subtitle-edit")
        if se_bin:
            return [se_bin]

        snap_exe = "/snap/subtitle-edit/current/subedit/SubtitleEdit.exe"
        if os.path.exists(snap_exe):
            mono_bin = shutil.which("mono") or "mono"
            return [mono_bin, snap_exe]

        return None

    def _on_open_subtitle_edit(self) -> None:
        # 1) scegli workdir “sensata”
        workdir = None

        wd_prev = getattr(self, "_last_subedit_workdir", None)
        if wd_prev and os.path.isdir(wd_prev):
            workdir = wd_prev

        if workdir is None and self.last_output_vob:
            try:
                vob = Path(self.last_output_vob).resolve()
                base = vob.with_suffix("")
                cand = base.parent / f"{base.name}_VTS"
                if cand.is_dir():
                    workdir = str(cand)
            except Exception:
                workdir = None

        if workdir is None and self.last_dir and os.path.isdir(self.last_dir):
            workdir = self.last_dir

        # ✅ FIX: mai cwd="/" e mai cwd non valida → fallback su HOME
        from pathlib import Path as _Path
        try:
            if (not workdir) or (not os.path.isdir(workdir)) or (os.path.abspath(workdir) == "/"):
                workdir = str(_Path.home())
        except Exception:
            workdir = str(_Path.home())

        self._last_subedit_workdir = workdir

        # 2) trova comando Subtitle Edit
        cmd_base = self._find_subtitle_edit_cmd()
        if not cmd_base:
            QMessageBox.warning(
                self.view,
                "Subtitle Edit",
                "Impossibile trovare Subtitle Edit.\n"
                "Installa 'subtitle-edit' oppure definisci SUBTITLE_EDIT_CMD.",
            )
            return

        cmd = list(cmd_base)

        # 3) debug (se LDVD_DEBUG=1)
        try:
            _dprint("[SubtitleEdit] cmd=", cmd)
            _dprint("[SubtitleEdit] PATH=", os.getenv("PATH"))
            _dprint("[SubtitleEdit] cwd=", workdir)
            _dprint("[DVD-Ripper] Avvio Subtitle Edit:", cmd, "cwd=", workdir)
        except Exception:
            pass

        # 4) avvio
        try:
            subprocess.Popen(cmd, cwd=workdir or None, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.view.set_status(f"Aperto Subtitle Edit (cartella: {os.path.basename(workdir)})")
        except Exception as e:
            QMessageBox.warning(self.view, "Subtitle Edit", f"Errore avviando Subtitle Edit:\n{e}")

    # --------------- Housekeeping ---------------
    def _housekeep_tick(self):
        self._refresh_titles_once()
        self._ensure_fs_roots_alive()

    def _ensure_fs_roots_alive(self):
        try:
            droot = getattr(self.view, "fsModelDirs", None)
            froot = getattr(self.view, "fsModelFiles", None)
            dpath = droot.rootPath() if droot else None
            fpath = froot.rootPath() if froot else None
        except Exception:
            dpath = fpath = None

        def gone(p: Optional[str]) -> bool:
            return bool(p) and not os.path.exists(p)

        if gone(dpath) or gone(fpath):
            if self.last_output_vob and os.path.isfile(self.last_output_vob):
                target = os.path.dirname(self.last_output_vob)
            elif self.last_dir and os.path.isdir(self.last_dir):
                target = self.last_dir
            else:
                target = os.path.expanduser("~")
            try:
                self.view.set_root_path(target)
                self.view.select_in_tree(target)
            except Exception:
                pass
            self.view.set_status(f"Sorgente non disponibile: root impostata a {target}")
            self.view.set_dvd_title("Nessun titolo")
            try:
                self.view.set_movie_title("—")
            except Exception:
                pass

    # --------------- Helpers titolo / root ---------------
    def _refresh_titles_once(self):
        raw = get_dvd_title()
        dvd_txt = title_case(raw, self.title_lang) if raw else "Nessun titolo"
        self.view.set_dvd_title(dvd_txt)

        if not self._current_movie_title():
            sug = suggest_movie_title(lang=self.title_lang)
            if not sug and raw:
                sug = title_case(raw, self.title_lang)
            if sug:
                self.view.set_movie_title(sug)

    def _current_movie_title(self) -> str:
        import re
        lbl = self.view.lblMovieTitle.text()
        m = re.search(r"<b>(.*?)</b>", lbl)
        val = m.group(1).strip() if m else ""
        if val in ("", "—"):
            return ""
        return val

    def _sanitize_filename(self, name: str) -> str:
        import re
        if not name:
            return "Film"
        name = re.sub(r"<[^>]+>", "", str(name))
        name = re.sub(r'[\\/:*?"<>|]', " ", name)
        name = re.sub(r"\s+", " ", name).strip(" .\t\r\n")
        return name or "Film"

    def _suggest_title_basename(self) -> str:
        cur = (self._current_movie_title() or "").strip()
        if cur:
            return self._sanitize_filename(title_case(cur, self.title_lang))
        raw = get_dvd_title()
        if raw:
            return self._sanitize_filename(title_case(raw, self.title_lang))
        sug = suggest_movie_title(lang=self.title_lang)
        if sug:
            return self._sanitize_filename(sug)
        return "Film"

    # --------------- Mount / drive ---------------
    def _set_root_to_mount(self) -> bool:
        try:
            mp = get_cdrom_mount_point()
            if not mp or not os.path.isdir(mp):
                return False
            self.view.set_root_path(mp)
            self.view.set_status(f"Root DVD: {mp}")
            self.last_dir = mp
            self._save_prefs()
            return True
        except Exception as e:
            self.view.set_status(f"Errore mount: {e}")
            return False

    def _try_mount_via_udisksctl(self) -> bool:
        try:
            dev = get_dvd_device()
            r = subprocess.run(
                ["udisksctl", "mount", "-b", dev],
                capture_output=True,
                text=True,
                check=False,
            )
            out = ((r.stdout or "") + " " + (r.stderr or "")).strip()
            if r.returncode == 0:
                self.view.set_status(out or "Mount richiesto; attendo il disco…")
                return True
            self.view.set_status(out or "Mount non riuscito.")
            return False
        except FileNotFoundError:
            self.view.set_status("udisksctl non disponibile (sudo apt install udisks2).")
            return False
        except Exception as e:
            self.view.set_status(f"Errore mount: {e}")
            return False

    # --------------- Eventi View: drive / lingua ---------------
    def _on_refresh_dvd(self):
        try:
            self.view.set_movie_title("—")
        except Exception:
            pass

        if self._set_root_to_mount():
            self._refresh_titles_once()
            return
        if self._try_mount_via_udisksctl():
            QTimer.singleShot(1500, lambda: (self._set_root_to_mount(), self._refresh_titles_once()))
        else:
            self.view.set_status("DVD non montato (inserisci il disco e riprova).")

    def _run_eject(self, cmd: list[str], action: str) -> bool:
        try:
            proc = subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            if proc.returncode == 0:
                self.view.set_status(f"Cassetto: {action} OK")
                return True
            err = (proc.stderr or "").strip()
            if err:
                err = f"\nDettagli: {err}"
            QMessageBox.information(
                self.view,
                "Info",
                f"Impossibile {action} il cassetto (rc={proc.returncode}).{err}",
            )
            return False
        except FileNotFoundError:
            QMessageBox.warning(self.view, "Errore", 'Il comando "eject" non è disponibile.')
            return False
        except Exception as e:
            QMessageBox.warning(self.view, "Errore", f"Impossibile {action} il cassetto: {e}")
            return False

    def _on_eject(self):
        ok = self._run_eject(["eject", get_dvd_device()], "aprire")
        if not ok:
            return

        if self.last_output_vob and os.path.isfile(self.last_output_vob):
            target_dir = os.path.dirname(self.last_output_vob) or "/"
        elif self.last_dir and os.path.isdir(self.last_dir):
            target_dir = self.last_dir
        else:
            target_dir = os.path.expanduser("~")

        try:
            self.view.set_root_path(target_dir)
            self.view.select_in_tree(target_dir)
        except Exception:
            pass

        try:
            self.queue.clear()
            self._sync_queue_view()
        except Exception:
            pass

        self.last_output_vob = None
        self._set_handoff_enabled(False)

        self.last_dir = target_dir
        self._save_prefs()

        self.view.set_dvd_title("Nessun titolo")
        try:
            self.view.set_movie_title("—")
        except Exception:
            pass

        self.view.set_status(f"DVD espulso. Root: {target_dir}")

    def _on_close_tray(self):
        ok = self._run_eject(["eject", "-t", get_dvd_device()], "chiudere")
        if not ok:
            try:
                act = getattr(self.view, "actCloseTray", None)
                if act:
                    act.setEnabled(False)
                    act.setToolTip("Chiusura via software non supportata da questo drive")
            except Exception:
                pass

    def _on_change_title_lang(self, code: str):
        code = (code or "it").lower()
        if code not in ("it", "en"):
            code = "it"
        self.title_lang = code
        self.view.set_titlecase_lang(code)
        self._refresh_titles_once()
        cur = self._current_movie_title()
        if cur:
            self.view.set_movie_title(title_case(cur, self.title_lang))
        self._save_prefs()

    def _on_change_ocr_srt(self, enabled: bool) -> None:
        self.ocr_srt_enabled = bool(enabled)
        try:
            self.view.set_ocr_srt_enabled(self.ocr_srt_enabled)
        except Exception:
            pass
        self._save_prefs()

    # --------------- Navigazione / locali ---------------
    def _on_open_folder(self):
        start_dir = self.last_dir if self.last_dir and os.path.isdir(self.last_dir) else os.path.expanduser("~")
        path = QFileDialog.getExistingDirectory(self.view, "Apri cartella", start_dir)
        if path:
            self.view.set_root_path(path)
            self.view.set_status(f"Root: {path}")
            self.last_dir = path
            self._save_prefs()

    def _on_add_files(self):
        start_dir = self.last_dir if self.last_dir and os.path.isdir(self.last_dir) else os.path.expanduser("~")
        files, _ = QFileDialog.getOpenFileNames(
            self.view,
            "Aggiungi file DVD (VOB/IFO)",
            start_dir,
            "DVD (VOB/IFO) (*.vob *.VOB *.ifo *.IFO);;Tutti i file (*.*)",
        )
        if files:
            self._on_add_selection(files)
            try:
                self.last_dir = os.path.dirname(files[0])
                self._save_prefs()
            except Exception:
                pass

    def _on_dir_activated(self, path: str):
        if not path or not os.path.isdir(path):
            return
        self.view.set_file_panel_path(path)
        self.view.set_status(f"Dir: {path}")
        self.last_dir = path
        self._save_prefs()

    def _on_file_activated(self, path: str):
        if not path:
            return
        if os.path.isdir(path):
            self._on_dir_activated(path)
            self.view.select_in_tree(path)
            return

        self.view.set_status(os.path.basename(path))
        if path.lower().endswith((".vob", ".ifo")) and os.path.isfile(path):
            self._on_add_selection([path])

    def _on_open_containing(self, ofile: str):
        if not ofile:
            return
        try:
            folder = os.path.dirname(ofile) or "."
            subprocess.Popen(["xdg-open", folder])
        except Exception:
            pass

    # --------------- Coda ---------------
    def _queue_vobs(self) -> List[str]:
        return [p for p in getattr(self, "queue", []) if p.lower().endswith(".vob")]

    def _on_add_selection(self, paths: List[str]):
        if not paths:
            return

        vobs = [p for p in paths if p.lower().endswith(".vob")]
        ifos = [p for p in paths if p.lower().endswith(".ifo")]

        if not vobs and not ifos:
            return

        new_items: List[str] = []

        if vobs:
            for p in natural_sort_vobs(vobs):
                if p not in self.queue:
                    new_items.append(p)

        if ifos:
            for p in sorted(set(ifos)):
                if p not in self.queue:
                    new_items.append(p)

        if new_items:
            self.queue.extend(new_items)

        if ifos:
            chosen = None
            if vobs:
                first_vob_dir = os.path.dirname(vobs[0])
                for cand in ifos:
                    if os.path.dirname(cand) == first_vob_dir:
                        chosen = cand
                        break
            if chosen is None:
                chosen = ifos[0]

            self._ifo_for_subedit = chosen
            if LDVD_DEBUG:
                _dprint(f"[DVD-Ripper] IFO scelto per Subtitle Edit: {chosen}")

        self._sync_queue_view()
        self._save_last_queue()

    def _on_remove_from_queue(self, rows: List[int]):
        if not rows:
            return
        for i in sorted(rows, reverse=True):
            if 0 <= i < len(self.queue):
                del self.queue[i]
        self._sync_queue_view()

    def _on_move_up(self, rows: List[int]):
        if not rows:
            return
        for i in sorted(rows):
            if i > 0:
                self.queue[i - 1], self.queue[i] = self.queue[i], self.queue[i - 1]
        self._sync_queue_view(select_rows=[max(r - 1, 0) for r in rows])

    def _on_move_down(self, rows: List[int]):
        if not rows:
            return
        for i in sorted(rows, reverse=True):
            if i < len(self.queue) - 1:
                self.queue[i + 1], self.queue[i] = self.queue[i], self.queue[i + 1]
        self._sync_queue_view(select_rows=[min(r + 1, len(self.queue) - 1) for r in rows])

    def _on_clear_queue(self):
        self.queue.clear()
        self._sync_queue_view()

    def _sync_queue_view(self, select_rows: Optional[List[int]] = None):
        self.view.set_queue_items(self.queue)
        if select_rows:
            sel: QItemSelectionModel = self.view.listQueue.selectionModel()
            if sel:
                sel.clearSelection()
                for r in select_rows:
                    idx = self.view.listQueue.model().index(r, 0)
                    sel.select(idx, QItemSelectionModel.Select)
        self._save_prefs()

    # --------------- Estrazione (copia VOB) ---------------
    def _choose_output(self, default_ext: str = "vob") -> Optional[str]:
        start_dir = self.last_dir if self.last_dir and os.path.isdir(self.last_dir) else os.path.expanduser("~")
        base = self._suggest_title_basename()
        default_ext = (default_ext or "vob").lower().lstrip(".")
        suggested = os.path.join(start_dir, f"{base}.{default_ext}")

        out, _ = QFileDialog.getSaveFileName(self.view, "Scegli nome file di output", suggested, "VOB (*.vob *.VOB)")
        if not out:
            return None

        ext = os.path.splitext(out)[1].lower()
        if ext != ".vob":
            out = out + ".vob"
        try:
            self.last_dir = os.path.dirname(out)
            self._save_prefs()
        except Exception:
            pass
        return out

    def _on_extract(self):
        if not self.queue:
            QMessageBox.warning(self.view, "Errore", "La coda è vuota. Aggiungi uno o più .vob.")
            return

        out = self._choose_output(default_ext="vob")
        if not out:
            return

        try:
            movie_title = os.path.splitext(os.path.basename(out))[0]
            self.view.set_movie_title(title_case(movie_title, self.title_lang))
        except Exception:
            pass

        self._start_copy_job(out)

    def _start_copy_job(self, out_path: str):
        """
        Avvia l'estrazione:
          - se sorgenti da DVD mount → staging selettivo via vobcopy -O (decritta) in <DVD>_VTS
          - se sorgenti già su disco → concat diretto (CopyWorker)

        FIX:
          - i segnali 'stage' NON devono andare su set_progress_stage, ma su set_status
          - progress resta su _on_progress (barra+ETA)
        """
        # salva output corrente (serve anche a _on_vts_stage_finished)
        self._current_out_path = out_path

        # prende i VOB dalla coda
        vobs = []
        try:
            for p in (self.queue or []):
                if p and str(p).lower().endswith(".vob"):
                    vobs.append(str(p))
        except Exception:
            pass

        if not vobs:
            QMessageBox.warning(self.view, "LDVD Ripper", "Nessun VOB in coda.")
            return

        # ordina “naturale” se disponibile
        try:
            vobs = natural_sort_vobs(vobs)
        except Exception:
            vobs = sorted(vobs)

        # ───────────────────────── DVD mount → vobcopy -O (staging selettivo)
        if self._sources_from_dvd_mount(vobs):
            # 1) mount
            mount = ""
            try:
                mount = (get_cdrom_mount_point() or "").strip()
            except Exception:
                mount = ""
            if not mount:
                try:
                    mount = self._guess_mount_from_path(vobs[0]) if vobs else ""
                except Exception:
                    mount = ""

            if not mount or not os.path.isdir(mount):
                QMessageBox.warning(self.view, "LDVD Ripper", "Non riesco a determinare il mount del DVD.")
                return

            # 2) VTS
            vts_num = None
            try:
                vts_num = self._guess_vts_number_from_sources(vobs)
            except Exception:
                vts_num = None
            if vts_num is None:
                QMessageBox.warning(self.view, "LDVD Ripper", "Non riesco a capire il VTS (VTS_01, VTS_02...).")
                return

            # 3) destinazione: <DVD_TITLE>_VTS accanto al fileone
            base = Path(out_path).with_suffix("")
            dvd_label = ""
            try:
                dvd_label = (get_dvd_title() or "").strip()
            except Exception:
                dvd_label = ""
            if dvd_label:
                try:
                    dvd_label = title_case(dvd_label, getattr(self, "title_lang", "it"))
                except Exception:
                    pass
                try:
                    dvd_label = self._sanitize_filename(dvd_label)
                except Exception:
                    pass
            else:
                dvd_label = base.name

            vts_dir = base.parent / f"{dvd_label}_VTS"
            try:
                vts_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                QMessageBox.warning(self.view, "LDVD Ripper", f"Impossibile creare:\n{vts_dir}\n{e}")
                return

            # 4) pulisci residui del VTS
            try:
                self._clean_vts_dest_dir(str(vts_dir), int(vts_num))
            except Exception:
                pass

            # 5) wanted_names: SOLO queue (VOB/IFO/BUP) per quel VTS, fallback ai vobs passati
            wanted_names = []
            try:
                wanted_names = self._wanted_vts_filenames_from_queue(self.queue or [], int(vts_num))
            except Exception:
                wanted_names = []
            if not wanted_names:
                try:
                    wanted_names = self._wanted_vts_filenames_from_queue(vobs or [], int(vts_num))
                except Exception:
                    wanted_names = [os.path.basename(x) for x in vobs]

            if not wanted_names:
                QMessageBox.warning(self.view, "LDVD Ripper", "Nessun file VTS valido in coda (solo .vob/.ifo/.bup).")
                return

            # 6) avvia staging
            import time
            self.view.set_busy(True)
            self.view.set_status("Preparazione segmenti (vobcopy -O) su disco…")
            try:
                self.view.set_progress_stage(f"Vobcopy: staging VTS_{int(vts_num):02d} → {vts_dir.name}")
            except Exception:
                pass
            self.view.set_progress(0)

            self._copy_start_ts = time.time()
            self._copy_last_pct = -1

            # chiamata “standard” (ma il worker che ti do sotto accetta anche l’altra)
            worker = VobcopyStageVTSWorker(mount, int(vts_num), wanted_names, str(vts_dir))
            self._worker = worker

            # FIX: stage → riga Stato
            worker.stage.connect(self.view.set_status)
            worker.progress.connect(self._on_progress)          # ETA!
            worker.finished.connect(self._on_vts_stage_finished)

            self._stage_vts_dir = str(vts_dir)
            self._stage_vts_num = int(vts_num)

            worker.start()
            return

        # ───────────────────────── sorgenti locali su disco → concat diretto
        import time
        self.view.set_busy(True)
        self.view.set_status("Estrazione in corso…")
        try:
            self.view.set_progress_stage("Copia VOB → file unico .vob")
        except Exception:
            pass
        self.view.set_progress(0)

        self._copy_start_ts = time.time()

        chunk_size = 4 * 1024 * 1024
        cw = CopyWorker(
            list(vobs),
            out_path,
            chunk_size=chunk_size,
            stage_in_ram=False,
            work_base=None,
            skip_on_eio=True,
            write_part_in_dest=True,
        )
        self.copy_worker = cw
        self._worker = cw

        # FIX: stage → riga Stato
        cw.stage.connect(self.view.set_status)
        cw.progress.connect(self._on_progress)
        cw.finished.connect(self._on_finished_copy)
        cw.need_vobcopy.connect(self._on_copy_need_vobcopy)
        cw.start()

    def _sources_from_dvd_mount(self, sources: list) -> bool:
        """
        True se le sorgenti sembrano provenire dal mount del DVD (VIDEO_TS),
        così scegliamo la strada 'vobcopy -O' invece della copia raw.
        """
        import os

        try:
            srcs = [os.path.realpath(str(s)) for s in (sources or []) if s]
        except Exception:
            srcs = [str(s) for s in (sources or []) if s]

        # 1) confronto diretto col mount rilevato
        mount = ""
        try:
            mount = (get_cdrom_mount_point() or "").strip()
        except Exception:
            mount = ""
        if mount:
            m = os.path.realpath(mount)
            mp = m + os.sep
            for s in srcs:
                if s == m or s.startswith(mp):
                    return True

        # 2) euristica VIDEO_TS
        for s in srcs:
            up = s.upper()
            if "/VIDEO_TS/" in up or up.endswith("/VIDEO_TS"):
                if s.startswith(("/media/", "/run/media/", "/mnt/")):
                    return True

        return False

    def _on_worker_stage(self, msg: str) -> None:
        """Messaggi di fase: vanno nella riga Stato (NON nella riga progress)."""
        try:
            s = (msg or "").strip()
            if s:
                self.view.set_status(s)
        except Exception:
            pass

    def _on_vts_stage_finished(self, ok: bool, msg: str, staged_vobs: list, ifo_path: str):
        if not ok:
            self.view.set_busy(False)
            self.view.set_progress(0)
            try:
                self.view.set_progress_stage("Errore")
            except Exception:
                pass
            self.view.set_status("Estrazione fallita.")
            QMessageBox.warning(self.view, "Estrazione (segmenti VTS)", msg or "Staging fallito.")
            return

        # staging OK: registra workdir per Subtitle Edit
        try:
            wd = getattr(self, "_stage_vts_dir", None)
            if wd and os.path.isdir(wd):
                self._last_subedit_workdir = wd
        except Exception:
            pass

        if ifo_path and os.path.isfile(ifo_path):
            self._last_subedit_ifo = ifo_path
            self._ifo_for_subedit = ifo_path

        vobs_local = [p for p in (staged_vobs or []) if p and os.path.isfile(p) and p.lower().endswith(".vob")]
        if not vobs_local:
            self.view.set_busy(False)
            QMessageBox.warning(self.view, "Estrazione", "Segmenti staging OK ma lista VOB vuota.")
            return

        out_path = getattr(self, "_current_out_path", None)
        if not out_path:
            self.view.set_busy(False)
            QMessageBox.warning(self.view, "Estrazione", "Percorso output mancante.")
            return

        import time
        self.view.set_status("Creo fileone .vob (concat locale)…")
        try:
            self.view.set_progress_stage("Copia segmenti locali → fileone .vob")
        except Exception:
            pass
        self.view.set_progress(0)

        self._copy_start_ts = time.time()
        self._copy_last_pct = -1

        chunk_size = 4 * 1024 * 1024
        cw = CopyWorker(
            list(vobs_local),
            out_path,
            chunk_size=chunk_size,
            stage_in_ram=False,
            work_base=None,
            skip_on_eio=False,
            write_part_in_dest=True,
        )
        self.copy_worker = cw
        self._worker = cw

        # FIX: stage → riga Stato (NON progress stage)
        cw.stage.connect(self.view.set_status)
        cw.progress.connect(self._on_progress)
        cw.finished.connect(self._on_finished_copy)
        cw.start()
        
    def _start_stage_polling(self, vts_dir: str, vts_num: int) -> None:
        """
        Polling "vero" dello staging Vobcopy:
        - somma i byte SCRITTI su disco dentro vts_dir *in modo ricorsivo*
          (include .vobcopy_stage_tmp e eventuali DISCNAME/VIDEO_TS creati da vobcopy)
        - converte bytes->% globale (staging+concat) e chiama _on_progress()

        Questo elimina:
          - progress bloccato a 0 mentre il file cresce nel tmp
          - salti tipo 13% al primo colpo (parte da 0 e sale regolare)
        """
        from PyQt5.QtCore import QTimer

        self._stage_poll_vts_dir = str(vts_dir)
        self._stage_poll_vts_num = int(vts_num)

        # reset stato polling (così parte davvero da 0)
        self._stage_poll_last_bytes = 0
        self._stage_poll_last_global_pct = -1
        self._stage_poll_last_emit_ts = 0.0

        # timer
        t = getattr(self, "_stage_poll_timer", None)
        if t is None:
            t = QTimer(self)
            t.setInterval(200)  # 5Hz: fluido ma non pesante
            t.timeout.connect(self._stage_poll_tick)
            self._stage_poll_timer = t

        if not self._stage_poll_timer.isActive():
            self._stage_poll_timer.start()

        # forzati 0 subito, così lo vedi “vivere”
        try:
            self._on_progress(0)
        except Exception:
            pass

    def _stage_poll_tick(self) -> None:
        """
        Tick del polling staging:
        misura byte scritti finora dentro la workdir VTS (ricorsivo),
        calcola percentuale globale e la invia a _on_progress().
        """
        import time
        from pathlib import Path

        vts_dir = getattr(self, "_stage_poll_vts_dir", "") or ""
        vts_num = int(getattr(self, "_stage_poll_vts_num", 0) or 0)
        if not vts_dir or vts_num <= 0:
            return

        root = Path(vts_dir)
        if not root.is_dir():
            return

        pref = f"VTS_{vts_num:02d}_".upper()

        # somma byte in modo ricorsivo: include tmp e folder annidate create da vobcopy
        bytes_now = 0
        try:
            for p in root.rglob("*"):
                if not p.is_file():
                    continue
                name = p.name.upper()

                # contiamo:
                # - VTS_xx_*.VOB / .IFO / .BUP
                # - eventuali file temporanei .PARTIAL / .TMP / .PART
                if not name.startswith(pref):
                    continue

                if not (
                    name.endswith(".VOB")
                    or name.endswith(".IFO")
                    or name.endswith(".BUP")
                    or name.endswith(".PARTIAL")
                    or name.endswith(".TMP")
                    or name.endswith(".PART")
                ):
                    continue

                try:
                    bytes_now += p.stat().st_size
                except Exception:
                    pass
        except Exception:
            return

        # monotonia (mai indietro)
        last_bytes = int(getattr(self, "_stage_poll_last_bytes", 0) or 0)
        if bytes_now < last_bytes:
            bytes_now = last_bytes
        self._stage_poll_last_bytes = bytes_now

        # stage_expected / global_total (se non ci sono, fallback safe)
        stage_expected = int(getattr(self, "_eta_expected_stage_bytes", 0) or 0)
        concat_expected = int(getattr(self, "_eta_expected_concat_bytes", 0) or 0)

        if stage_expected <= 0:
            # fallback “non bloccare”: se non sai quanto è, usa quello che stai vedendo
            stage_expected = max(1, bytes_now)

        if concat_expected <= 0:
            concat_expected = 1

        global_total = int(getattr(self, "_eta_global_total_bytes", 0) or 0)
        if global_total <= 0:
            global_total = max(1, stage_expected + concat_expected)

        # clamp: non far superare stage_expected (staging non può “andare oltre”)
        stage_done = min(bytes_now, stage_expected)

        # salva per la fase concat
        self._eta_stage_done_bytes = max(int(getattr(self, "_eta_stage_done_bytes", 0) or 0), int(stage_done))

        # percent globale
        gpct = int((self._eta_stage_done_bytes * 100) / global_total)
        gpct = max(0, min(99, gpct))  # 100 solo quando finisce TUTTO

        # non spammare UI: emetti solo se cambia o se passa un po' di tempo
        now = time.time()
        last_pct = int(getattr(self, "_stage_poll_last_global_pct", -1) or -1)
        last_emit = float(getattr(self, "_stage_poll_last_emit_ts", 0.0) or 0.0)

        if gpct != last_pct or (now - last_emit) > 0.6:
            self._stage_poll_last_global_pct = gpct
            self._stage_poll_last_emit_ts = now
            try:
                self._on_progress(gpct)
            except Exception:
                pass

    # --------------- Postprocess (sidecar + OCR SRT) ---------------
    def _run_postprocess_vob(self, vob_path: str) -> None:
        vob_path = str(vob_path)
        base = Path(vob_path).with_suffix("")
        snap = base.with_suffix(".lsdvd.json")

        if not snap.exists():
            self.view.set_status("Analisi DVD (lsdvd)…")
            try:
                self.view.set_progress_stage("Analisi DVD (lsdvd)…")
            except Exception:
                pass
            self._try_write_lsdvd_snapshot(vob_path)

        srt_mode = self._get_srt_mode_for_sidecar()
        want_srt = bool(getattr(self, "ocr_srt_enabled", False))

        self.view.set_status("Scrittura finale…")
        try:
            self.view.set_progress_stage("Scrittura finale…")
        except Exception:
            pass

        meta = None
        try:
            if hasattr(self.view, "set_progress_indeterminate"):
                try:
                    self.view.set_progress_indeterminate(True)
                except Exception:
                    pass

            meta = postprocess_vob(
                vob_path,
                status_cb=lambda s: self.view.set_progress_stage(f"Postprocess: {s}"),
                make_srt=want_srt,
                srt_mode=srt_mode,
            )

        except Exception as e:
            try:
                if hasattr(self.view, "set_progress_indeterminate"):
                    self.view.set_progress_indeterminate(False)
                self.view.set_busy(False)
            except Exception:
                pass
            self.view.set_status("Postprocess fallito.")
            try:
                self.view.set_progress_stage("Errore")
            except Exception:
                pass
            QMessageBox.warning(self.view, "Postprocess", f"Sidecar non generati: {e}")
            return
        finally:
            try:
                if hasattr(self.view, "set_progress_indeterminate"):
                    self.view.set_progress_indeterminate(False)
            except Exception:
                pass

        try:
            if want_srt:
                self._run_ocr_srt_for_vob(vob_path, meta)
        except Exception as e:
            if LDVD_DEBUG:
                _dprint(f"[DVD-Ripper] [OCR] Errore durante OCR: {e}")

        self.view.set_status("Completato.")
        try:
            self.view.set_progress_stage("Completato")
        except Exception:
            pass
        self.view.set_busy(False)

    def _prepare_subedit_workdir(self, vob_path: str) -> None:
        try:
            vob = Path(vob_path).resolve()
        except Exception:
            return
        if not vob.is_file():
            return

        base = vob.with_suffix("")
        workdir = base.parent / f"{base.name}_VTS"

        if workdir.is_dir():
            try:
                has_vob = any(p.is_file() and p.suffix.lower() == ".vob" for p in workdir.iterdir())
            except Exception:
                has_vob = False

            if has_vob:
                self._last_subedit_workdir = str(workdir)

                if not getattr(self, "_last_subedit_ifo", None):
                    try:
                        for cand in workdir.iterdir():
                            if cand.is_file() and cand.suffix.lower() == ".ifo":
                                self._last_subedit_ifo = str(cand)
                                self._ifo_for_subedit = str(cand)
                                break
                    except Exception:
                        pass

                if LDVD_DEBUG:
                    _dprint("[DVD-Ripper] Workdir Subtitle Edit già pronta; riuso senza seconda copia dal DVD.")
                return

        try:
            workdir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            if LDVD_DEBUG:
                _dprint(f"[DVD-Ripper] Impossibile creare workdir Subtitle Edit: {e}")
            return

        copied = 0

        for src in (self.queue or []):
            try:
                p = Path(src)
                if not p.is_file() or p.suffix.lower() != ".vob":
                    continue
                dest = workdir / p.name
                if dest.is_file():
                    try:
                        if dest.stat().st_size == p.stat().st_size:
                            continue
                    except Exception:
                        pass
                shutil.copy2(str(p), str(dest))
                copied += 1
            except Exception as e:
                if LDVD_DEBUG:
                    _dprint(f"[DVD-Ripper] copia VOB per Subtitle Edit fallita: {src} → {e}")

        try:
            if hasattr(self, "_ifo_for_subedit"):
                ifo_path = getattr(self, "_ifo_for_subedit")
                if ifo_path:
                    ifo = Path(ifo_path)
                    if ifo.is_file():
                        dest_ifo = workdir / ifo.name
                        do_copy = True
                        if dest_ifo.is_file():
                            try:
                                do_copy = dest_ifo.stat().st_size != ifo.stat().st_size
                            except Exception:
                                do_copy = True
                        if do_copy:
                            shutil.copy2(str(ifo), str(dest_ifo))
                            self._last_subedit_ifo = str(dest_ifo)
        except Exception as e:
            if LDVD_DEBUG:
                _dprint(f"[DVD-Ripper] copia IFO per Subtitle Edit fallita: {e}")

        self._last_subedit_workdir = str(workdir)

        if LDVD_DEBUG:
            _dprint(f"[DVD-Ripper] Workdir Subtitle Edit pronta (fallback locale): {workdir} (copiati {copied} VOB + eventuale IFO)")

    def _run_ocr_srt_for_vob(self, vob_path: str, meta: Optional[dict]) -> None:
        if not getattr(self, "ocr_srt_enabled", False):
            return

        vob = Path(vob_path)
        if not vob.exists():
            return

        try:
            meta_in = dict(meta or {})
        except Exception:
            meta_in = {}

        if not meta_in:
            try:
                sc_path = sidecar_path_for(vob)
                if sc_path and Path(sc_path).is_file():
                    meta_in = load_sidecar(sc_path)
            except Exception:
                meta_in = {}

        meta_in = meta_in or {}
        reqs = list(meta_in.get("srt_requests") or [])
        if not reqs:
            if LDVD_DEBUG:
                _dprint("[DVD-Ripper] [OCR] Nessun srt_requests nel sidecar; salto OCR.")
            return

        already = [r for r in reqs if r.get("target") and Path(str(r["target"])).is_file()]
        if already:
            if LDVD_DEBUG:
                _dprint("[DVD-Ripper] [OCR] SRT già presenti sui target; non rifaccio OCR.")
            return

        def _ocr_prog(p: int):
            try:
                v = max(0, min(100, int(p)))
            except Exception:
                v = 0
            try:
                self.view.set_progress(v)
            except Exception:
                pass
            try:
                self.view.set_progress_stage(f"OCR SRT… {v}%")
            except Exception:
                pass

        def _ocr_stage(msg: str):
            try:
                self.view.set_status(msg)
                if hasattr(self.view, "set_progress_stage"):
                    self.view.set_progress_stage(msg)
            except Exception:
                pass
            if LDVD_DEBUG:
                _dprint("[DVD-Ripper] [OCR]", msg)

        try:
            srts = extract_srt_for_vob(
                str(vob),
                requests=reqs,
                mode="all",
                status_cb=_ocr_stage,
                progress_cb=_ocr_prog,
            )
        except Exception as e:
            if LDVD_DEBUG:
                _dprint("[DVD-Ripper] [OCR] Errore durante extract_srt_for_vob:", e)
            return

        if not srts:
            _ocr_stage("OCR: nessun .srt ottenuto (controlla mencoder/vobsub2srt).")
            return

        produced_set = {Path(p).resolve() for p in srts if p}

        subs = list(meta_in.get("subtitles") or [])
        for sub in subs:
            lang = (sub.get("language") or "und").lower()
            existing = set(sub.get("external_files") or [])

            for r in reqs:
                r_lang = (r.get("language") or "und").lower()
                if r_lang != lang:
                    continue
                t = r.get("target")
                if not t:
                    continue
                pt = Path(t).resolve()
                if pt in produced_set:
                    existing.add(str(pt))

            if existing:
                sub["external_files"] = sorted(existing)

        meta_in["srt_generated"] = True

        try:
            sc_path = sidecar_path_for(vob)
            if sc_path:
                Path(sc_path).write_text(json.dumps(meta_in, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            if LDVD_DEBUG:
                _dprint("[DVD-Ripper] [OCR] errore scrivendo sidecar aggiornato:", e)

        _ocr_stage(f"OCR completato: creati {len(produced_set)} file .srt.")

    def _get_srt_mode_for_sidecar(self) -> str:
        if not getattr(self, "ocr_srt_enabled", False):
            return "none"
        return "all"

    # --------------- callback job (copia) ---------------
    def _on_finished_copy(self, ok: bool, msg: str):
        # stop ETA sempre al termine copia (o transizione fallita)
        self._eta_stop()
        self._copy_start_ts = None

        # Caso particolare: CopyWorker ha chiesto fallback e poi ha emesso finished(False, "FALLBACK_VOBCOPY")
        if (msg or "").strip() == "FALLBACK_VOBCOPY":
            return

        # In modalità fallback in corso, ignora eventuali eventi spuri del vecchio job
        if getattr(self, "_fallback_in_progress", False) and not ok:
            return

        try:
            self.view.set_progress_indeterminate(False)
        except Exception:
            pass

        if not ok:
            self.view.set_busy(False)
            self.view.set_progress(0)
            try:
                self.view.set_progress_stage("Errore")
            except Exception:
                pass
            self.view.set_status("Estrazione fallita.")
            QMessageBox.warning(self.view, "Estrazione", msg or "Estrazione fallita.")
            return

        # OK
        self._fallback_in_progress = False

        self.view.set_busy(True)
        self.view.set_progress(100)
        try:
            self.view.set_progress_stage("Scrittura finale…")
        except Exception:
            pass
        self.view.set_status("Scrittura finale…")

        out_vob = getattr(self, "_current_out_path", None)
        if not out_vob or not os.path.isfile(out_vob):
            self.view.set_busy(False)
            self.view.set_status("Completato.")
            try:
                self.view.set_progress_stage("Completato")
            except Exception:
                pass
            QMessageBox.information(self.view, "Estrazione", msg or "Estrazione completata.")
            return

        self._run_postprocess_vob(out_vob)
        self.last_output_vob = out_vob

        try:
            self._prepare_subedit_workdir(out_vob)
        except Exception:
            pass

        self._save_prefs()
        self._set_handoff_enabled(True)

        box = QMessageBox(self.view)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle("Estrazione completata")
        base = os.path.basename(out_vob)
        box.setText(f"{msg or 'Estrazione completata.'}\n\nCreati i sidecar accanto a:\n{base}")
        btn_hevc = box.addButton("Passa a HEVC", QMessageBox.AcceptRole)
        btn_open = box.addButton("Apri cartella", QMessageBox.ActionRole)
        btn_close = box.addButton("Chiudi", QMessageBox.RejectRole)
        box.setDefaultButton(btn_hevc)
        box.exec_()
        clicked = box.clickedButton()

        if clicked == btn_open:
            try:
                subprocess.Popen(["xdg-open", os.path.dirname(out_vob) or "."])
            except Exception:
                pass
            return

        if clicked == btn_hevc:
            self._on_handoff_to_hevc()
            return

    # --------------- fallback (EIO): staging VTS con vobcopy -O (NO fileone) ---------------
    def _on_copy_need_vobcopy(self, sources: list):
        self._eta_stop()

        out_path = ""
        try:
            out_path = getattr(self, "_current_out_path", None) or ""
        except Exception:
            out_path = ""

        if not out_path:
            QMessageBox.warning(self.view, "LDVD Ripper", "Fallback richiesto ma non ho un percorso di output valido.")
            return

        self._fallback_in_progress = True
        self._start_vts_stage_fallback(out_path, sources or [])

    def _start_vts_stage_fallback(self, out_path: str, sources: list):
        """
        Fallback automatico quando CopyWorker segnala EIO:
        stage selettivo via vobcopy -O su disco, poi concat locale.
        """
        # 1) mount
        mount = ""
        try:
            mount = (get_cdrom_mount_point() or "").strip()
        except Exception:
            mount = ""
        if not mount:
            try:
                mount = self._guess_mount_from_path(sources[0]) if sources else ""
            except Exception:
                mount = ""

        if not mount or not os.path.isdir(mount):
            QMessageBox.warning(self.view, "LDVD Ripper", "Fallback: non riesco a determinare il mount del DVD.")
            return

        # 2) VTS
        vts_num = None
        try:
            vts_num = self._guess_vts_number_from_sources(sources)
        except Exception:
            vts_num = None
        if vts_num is None:
            QMessageBox.warning(self.view, "LDVD Ripper", "Fallback: non riesco a capire il VTS (VTS_01, VTS_02...).")
            return

        # 3) destinazione: <DVD_TITLE>_VTS accanto al fileone
        base = Path(out_path).with_suffix("")
        dvd_label = ""
        try:
            dvd_label = (get_dvd_title() or "").strip()
        except Exception:
            dvd_label = ""
        if dvd_label:
            try:
                dvd_label = title_case(dvd_label, getattr(self, "title_lang", "it"))
            except Exception:
                pass
            try:
                dvd_label = self._sanitize_filename(dvd_label)
            except Exception:
                pass
        else:
            dvd_label = base.name

        vts_dir = base.parent / f"{dvd_label}_VTS"
        try:
            vts_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            QMessageBox.warning(self.view, "LDVD Ripper", f"Fallback: impossibile creare:\n{vts_dir}\n{e}")
            return

        # 4) pulisci residui
        try:
            self._clean_vts_dest_dir(str(vts_dir), int(vts_num))
        except Exception:
            pass

        # 5) wanted_names: prima QUEUE (VOB/IFO/BUP) per quel VTS, fallback ai sources
        wanted_names = []
        try:
            wanted_names = self._wanted_vts_filenames_from_queue(self.queue or [], int(vts_num))
        except Exception:
            wanted_names = []
        if not wanted_names:
            try:
                wanted_names = self._wanted_vts_filenames_from_queue(sources or [], int(vts_num))
            except Exception:
                wanted_names = [os.path.basename(x or "") for x in (sources or []) if x]

        if not wanted_names:
            QMessageBox.warning(self.view, "LDVD Ripper", "Fallback: nessun file VTS valido in coda (solo .vob/.ifo/.bup).")
            return

        # 6) avvio stage
        import time
        self.view.set_busy(True)
        self.view.set_status("Recupero I/O: staging segmenti (vobcopy -O) su disco…")
        try:
            self.view.set_progress_stage(f"Vobcopy: staging VTS_{int(vts_num):02d} → {vts_dir.name}")
        except Exception:
            pass
        self.view.set_progress(0)

        self._copy_start_ts = time.time()
        self._copy_last_pct = -1

        worker = VobcopyStageVTSWorker(mount, int(vts_num), wanted_names, str(vts_dir))
        self._worker = worker

        # FIX: stage → riga Stato
        worker.stage.connect(self.view.set_status)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_vts_stage_finished)

        self._stage_vts_dir = str(vts_dir)
        self._stage_vts_num = int(vts_num)

        worker.start()

    # --------------- Handoff a HEVC ---------------
    def _set_handoff_enabled(self, enabled: bool):
        try:
            self.view.set_handoff_enabled(bool(enabled))
        except Exception:
            pass

    def _pick_vob_for_handoff(self) -> Optional[str]:
        if self.last_output_vob and os.path.isfile(self.last_output_vob):
            return self.last_output_vob
        try:
            for p in self.queue:
                if p.lower().endswith(".vob") and os.path.isfile(p):
                    return p
        except Exception:
            pass
        fp, _ = QFileDialog.getOpenFileName(
            self.view,
            "Seleziona VOB da passare a HEVC",
            self.last_dir or os.path.expanduser("~"),
            "VOB (*.vob *.VOB);;Tutti i file (*.*)",
        )
        return fp or None

    def _on_handoff_to_hevc(self):
        path = self._pick_vob_for_handoff()
        if not path:
            QMessageBox.information(self.view, "Passa a HEVC", "Nessun VOB disponibile. Estrai prima un titolo.")
            return

        self.last_output_vob = path
        self._set_handoff_enabled(True)
        self._save_prefs()

        if getattr(self, "ocr_srt_enabled", False):
            try:
                self._run_ocr_srt_for_vob(path, None)
            except Exception as e:
                if LDVD_DEBUG:
                    _dprint(f"[DVD-Ripper] [OCR] errore durante la generazione pre-handoff: {e}")

        try:
            self.vob_handoff.emit(path)
        except Exception:
            pass

        try:
            print(f"HEVC_HANDOFF:{path}", flush=True)
            self.view.set_status(f"Inoltrato a HEVC: {os.path.basename(path)}")
        except Exception:
            pass

    # --------------- Annulla / Esci / Varie ---------------
    def _on_cancel(self):
        if self._worker and self._worker.isRunning():
            # CopyWorker: stop soft
            try:
                from .qworkers import CopyWorker as _CW
            except Exception:
                _CW = CopyWorker

            if isinstance(self._worker, _CW):
                try:
                    self._worker.stop()
                    self._worker.wait(2000)
                except Exception:
                    pass

                self._eta_stop()
                self._copy_start_ts = None
                self._fallback_in_progress = False

                self.view.set_busy(False)
                self.view.set_progress(0)
                self.view.set_status("Annullato")
                QMessageBox.information(self.view, "Annullato", "Estrazione annullata.")
                return

            # VobcopyStageVTSWorker: stop (termina subprocess)
            if hasattr(self._worker, "stop"):
                try:
                    self._worker.stop()
                except Exception:
                    pass
                try:
                    self._worker.wait(2000)
                except Exception:
                    pass

                self._eta_stop()
                self._copy_start_ts = None
                self._fallback_in_progress = False

                self.view.set_busy(False)
                self.view.set_progress(0)
                self.view.set_status("Annullato")
                QMessageBox.information(self.view, "Annullato", "Operazione annullata.")
                return

            QMessageBox.information(self.view, "Info", "Questo job non supporta annullamento.")
            return

        QMessageBox.information(self.view, "Info", "Nessun job in corso.")

    def _on_exit(self):
        try:
            if self._worker and self._worker.isRunning():
                QMessageBox.warning(self.view, "Uscita", "Attendi la fine dell'operazione o annulla.")
                return
        except Exception:
            pass
        self._save_prefs()
        self.view.close()

    # --------------- Clear + manutenzione ---------------
    def _clear_prefs_file(self):
        try:
            self._prefs_path().unlink(missing_ok=True)
        except Exception:
            pass

    def _purge_temp_dirs(self):
        try:
            here = Path(__file__).resolve().parent
            tmp = here.parent / ".tmp" / "dvd_ripper"
            if tmp.is_dir():
                for p in tmp.glob("**/*"):
                    try:
                        if p.is_file() and p.name.endswith(".part"):
                            p.unlink()
                    except Exception:
                        pass
        except Exception:
            pass

    def _on_clear_all(self):
        if getattr(self, "_worker", None) and self._worker.isRunning():
            QMessageBox.warning(self.view, "Operazione in corso", "Impossibile pulire mentre un'operazione è in corso.")
            return

        try:
            if hasattr(self, "queue"):
                try:
                    self.queue.clear()
                except Exception:
                    self.queue = []
            self.last_dir = None
            self.title_lang = "it"
            self.last_output_vob = None
            self._ifo_for_subedit = None
            self._last_subedit_workdir = None
            self._last_subedit_ifo = None
        except Exception:
            pass

        self._clear_prefs_file()
        self._purge_temp_dirs()

        try:
            self.view.reset_ui()
            self.view.set_titlecase_lang("it")
            self.view.set_busy(False)
            self.view.set_progress(0)
            try:
                self.view.set_root_path("/")
            except Exception:
                pass
        except Exception:
            pass

        try:
            self._save_prefs()
        except Exception:
            pass

        self._set_handoff_enabled(False)
        self.view.set_status("Pulito. Pronto.")
        if hasattr(self.view, "set_progress_stage"):
            self.view.set_progress_stage("Pronto")

    # --------------- Helpers per staging VTS ---------------
    def _guess_mount_from_path(self, any_path: str) -> Optional[str]:
        p = (any_path or "").replace("\\", "/")
        up = p.upper()
        if "/VIDEO_TS/" in up:
            idx = up.find("/VIDEO_TS/")
            if idx > 0:
                return p[:idx]
        try:
            d = os.path.dirname(any_path)
            if os.path.basename(d).upper() == "VIDEO_TS":
                return os.path.dirname(d)
        except Exception:
            pass
        return None

    def _guess_vts_number_from_sources(self, vob_paths: List[str]) -> Optional[int]:
        import re
        rx = re.compile(r"VTS_(\d{2})_", re.I)
        for p in (vob_paths or []):
            m = rx.search(os.path.basename(p))
            if m:
                try:
                    return int(m.group(1))
                except Exception:
                    return None
        return None

    def _wanted_vts_filenames_from_queue(self, sources: List[str], vts_num: int) -> List[str]:
        pref = f"VTS_{int(vts_num):02d}_"
        wanted: List[str] = []
        seen = set()

        for p in sources or []:
            bn = os.path.basename(p or "")
            if not bn:
                continue
            up = bn.upper()
            if not up.startswith(pref):
                continue
            if not up.endswith((".VOB", ".IFO")):
                continue
            if up not in seen:
                wanted.append(up)
                seen.add(up)

        return wanted

    def _clean_vts_dest_dir(self, dest_dir: str, vts_num: int) -> None:
        try:
            import shutil as _sh
            d = Path(dest_dir)
            if not d.is_dir():
                return

            pref = f"VTS_{int(vts_num):02d}_".upper()

            for p in d.iterdir():
                if p.is_file():
                    up = p.name.upper()
                    if up.startswith(pref) and (up.endswith(".VOB") or up.endswith(".IFO") or up.endswith(".BUP")):
                        try:
                            p.unlink()
                        except Exception:
                            pass
                    if up.startswith(pref) and up.endswith(".PARTIAL"):
                        try:
                            p.unlink()
                        except Exception:
                            pass

            for p in d.iterdir():
                if p.is_dir():
                    try:
                        _sh.rmtree(str(p), ignore_errors=True)
                    except Exception:
                        pass

        except Exception:
            pass
