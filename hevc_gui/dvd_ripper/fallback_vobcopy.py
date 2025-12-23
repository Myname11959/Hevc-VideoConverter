#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fallback_vobcopy.py

Contiene 2 worker:

A) VobcopyStageVTSWorker
   - scopo: estrarre su DISCO SOLO i file del VTS che l’utente ha messo in coda
   - copia .IFO/.BUP con shutil (sono leggibili)
   - per i .VOB usa vobcopy -O <filename> (decritta con libdvdcss)
   - appiattisce eventuali directory annidate prodotte da vobcopy (DISCNAME/VIDEO_TS/...)
   - restituisce: (ok, msg, staged_vobs[], ifo_path)

B) VobcopyWorker
   - legacy: crea un unico VOB tramite vobcopy -n <title>
"""

from __future__ import annotations
from typing import List, Optional, Tuple
from pathlib import Path
import os
import re
import time
import shutil
import tempfile
import subprocess
import math
from PyQt5.QtCore import QThread, pyqtSignal


LDVD_DEBUG = os.environ.get("LDVD_DEBUG", "0") not in ("0", "", "false", "False")


def _dprint(*a, **k) -> None:
    if not LDVD_DEBUG:
        return
    try:
        kk = dict(k)
        kk.setdefault("flush", True)
        print(*a, **kk)
    except Exception:
        pass


def _select_stage_dir(prefer_ram: bool) -> Path:
    """
    Cartella temporanea per i file generati da vobcopy.

    NO /tmp di sistema: usiamo <repo_root>/tmp/dvd_ripper
    (es: /mnt/Storage/Hevc_gui/tmp/dvd_ripper).
    """
    # 1) RAM (se richiesto)
    if prefer_ram:
        for p in (Path("/dev/shm"), Path("/run/shm")):
            try:
                if p.is_dir() and os.access(str(p), os.W_OK):
                    d = p / "dvd_ripper"
                    d.mkdir(parents=True, exist_ok=True)
                    return d
            except Exception:
                pass

    # 2) tmp del progetto: <repo_root>/tmp/dvd_ripper
    try:
        repo_root = Path(__file__).resolve().parents[2]  # .../Hevc_gui
        d = repo_root / "tmp" / "dvd_ripper"
        d.mkdir(parents=True, exist_ok=True)
        if os.access(str(d), os.W_OK):
            return d
    except Exception:
        pass

    # 3) fallback sicuro (sempre NON /tmp): ~/.cache/hevc_gui/tmp/dvd_ripper
    base = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
    d = base / "hevc_gui" / "tmp" / "dvd_ripper"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _video_ts_dir(mount_path: str) -> Path:
    """
    Ritorna <mount>/VIDEO_TS (case-insensitive), oppure <mount>.
    """
    mp = Path(mount_path)
    if not mp.is_dir():
        return mp
    # prova VIDEO_TS
    cand = mp / "VIDEO_TS"
    if cand.is_dir():
        return cand
    # prova varianti case-insensitive
    try:
        for ch in mp.iterdir():
            if ch.is_dir() and ch.name.lower() == "video_ts":
                return ch
    except Exception:
        pass
    return mp


def _parse_percent(line: str) -> Optional[int]:
    """
    Estrae una percentuale da una riga di output.

    Supporta:
      - 10%
      - 10.8%
      - 10,8%
      - spazi vari prima del simbolo %

    Ritorna SEMPRE l'intero 0..100 (parte intera), oppure None.
    """
    if not line:
        return None

    # Esempi: " 10%", "10.8%", "10,8 %"
    m = re.search(r"(\d{1,3})(?:[.,]\d+)?\s*%", line)
    if not m:
        return None

    try:
        v = int(m.group(1))
    except Exception:
        return None

    if v < 0:
        v = 0
    if v > 100:
        v = 100
    return v


def _nat_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


# =============================================================================
#  Worker A: staging VTS selettivo (SOLO queue) → dest_dir
# =============================================================================
class VobcopyStageVTSWorker(QThread):
    stage = pyqtSignal(str)
    progress = pyqtSignal(int)  # 0..100
    finished = pyqtSignal(bool, str, list, str)

    def __init__(self, mount_path: str, vts_num: int, arg3, arg4=None, *, wanted_files=None, prefer_ram: bool = False):
        """
        Compatibilità chiamate:
          A) VobcopyStageVTSWorker(mount, vts_num, wanted_names, dest_dir)
          B) VobcopyStageVTSWorker(mount, vts_num, dest_dir, wanted_files=wanted_names)

        Il controller nel tuo progetto usa entrambe in punti diversi.
        """
        super().__init__()
        self.mount_path = str(mount_path)
        self.vts_num = int(vts_num)
        self.prefer_ram = bool(prefer_ram)

        # normalizza argomenti
        if wanted_files is None:
            # pattern A
            wanted = arg3
            dest_dir = arg4
        else:
            # pattern B
            dest_dir = arg3
            wanted = wanted_files

        if not dest_dir or not isinstance(dest_dir, str):
            raise TypeError("VobcopyStageVTSWorker: dest_dir mancante o non-stringa")

        self.wanted_files = [os.path.basename(x or "") for x in (wanted or []) if x]
        self.dest_dir = str(dest_dir)

        self._stop = False
        self._proc: Optional[subprocess.Popen] = None

    def stop(self):
        self._stop = True
        p = self._proc
        if p and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass

    def _locate_extracted(self, root: Path, name: str) -> Optional[Path]:
        name_u = name.upper()
        try:
            for p in root.rglob("*"):
                if p.is_file() and p.name.upper() == name_u:
                    return p
        except Exception:
            pass
        return None

    def run(self):
        run_dir: Optional[Path] = None
        try:
            dd = Path(self.dest_dir)
            dd.mkdir(parents=True, exist_ok=True)

            pref = f"VTS_{self.vts_num:02d}_".lower()

            # filtra wanted (solo questo VTS, estensioni sensate)
            wanted = []
            for bn in (self.wanted_files or []):
                low = (bn or "").lower()
                if low.startswith(pref) and low.endswith((".vob", ".ifo", ".bup")):
                    wanted.append(os.path.basename(bn))

            if not wanted:
                self.finished.emit(False, "Nessun file valido per staging (vuoto dopo filtro VTS_XX_).", [], "")
                return

            wanted.sort(key=_nat_key)

            vtsdir = _video_ts_dir(self.mount_path)
            if not vtsdir.exists():
                self.finished.emit(False, f"VIDEO_TS non trovato: {vtsdir}", [], "")
                return

            # Precalcolo dimensioni per % reale (a byte)
            sizes = {}
            bytes_total = 0
            for name in wanted:
                src = vtsdir / name
                sz = 0
                try:
                    if src.exists():
                        sz = int(src.stat().st_size)
                except Exception:
                    sz = 0
                sizes[name] = max(0, sz)
                bytes_total += max(0, sz)

            # fallback se per qualche motivo non ho size
            if bytes_total <= 0:
                bytes_total = len(wanted)

            def emit_pct(done_bytes: int, cur_bytes: int = 0, force: bool = False):
                if self._stop:
                    return
                try:
                    if bytes_total > 0 and bytes_total != len(wanted):
                        pct = int(round(100.0 * float(done_bytes + max(0, cur_bytes)) / float(bytes_total)))
                    else:
                        # fallback “a file”
                        pct = int(round(100.0 * float(done_bytes) / float(bytes_total)))
                except Exception:
                    pct = 0
                if pct < 0:
                    pct = 0
                if pct > 100:
                    pct = 100

                now = time.time()
                last_pct = getattr(self, "_last_emit_pct", -1)
                last_ts = getattr(self, "_last_emit_ts", 0.0)

                # emetti se cambia o ogni ~0.35s (per ETA “al secondo”)
                if force or pct != last_pct or (now - last_ts) >= 0.35:
                    self._last_emit_pct = pct
                    self._last_emit_ts = now
                    try:
                        self.progress.emit(int(pct))
                    except Exception:
                        pass

            # directory temporanea dove vobcopy scrive (poi noi “appiattiamo” in dest_dir)
            stage_base = _select_stage_dir(self.prefer_ram)
            run_dir = Path(tempfile.mkdtemp(prefix=f"ldvd_vobcopy_stage_{self.vts_num:02d}_", dir=str(stage_base)))

            staged_vobs: list = []
            ifo_path = ""

            done_bytes = 0
            n = len(wanted)

            # progress a 0 subito
            emit_pct(0, 0, force=True)

            import select

            for idx, name in enumerate(wanted, start=1):
                if self._stop:
                    self.finished.emit(False, "Annullato.", [], "")
                    return

                low = name.lower()
                src = vtsdir / name
                expected = sizes.get(name, 0)

                # Stage text (va su set_status nel controller)
                try:
                    self.stage.emit(f"Vobcopy: {name} ({idx}/{n})")
                except Exception:
                    pass

                # IFO/BUP: copia semplice
                if low.endswith((".ifo", ".bup")):
                    try:
                        if src.exists():
                            shutil.copy2(str(src), str(dd / name))
                            if low.endswith(".ifo") and (f"vts_{self.vts_num:02d}_0.ifo" == low):
                                ifo_path = str(dd / name)
                            # aggiorna progress “a byte”
                            done_bytes += max(expected, 1 if bytes_total == len(wanted) else 0)
                            emit_pct(done_bytes, 0, force=True)
                        else:
                            _dprint(f"[vobcopy-stage] manca: {src}")
                    except Exception as e:
                        self.finished.emit(False, f"Errore copiando {name}: {e}", [], "")
                        return
                    continue

                # VOB: vobcopy -O (decritta)
                #
                # FIX CRITICO:
                # vobcopy, dentro -o <run_dir>, crea la cartella col nome del DVD (es: URLA_DEL_SILENZIO/VIDEO_TS).
                # Alla seconda chiamata dentro lo stesso run_dir la cartella esiste già e vobcopy chiede [c/x/q] su stdin.
                # In GUI si blocca. Con -x + stdin=DEVNULL diventa non-interattivo e NON si pianta.
                cmd = ["vobcopy", "-x", "-O", name, "-l", "-i", self.mount_path, "-o", str(run_dir)]
                _dprint(f"[vobcopy-stage] run: {' '.join(cmd)}")

                try:
                    p = subprocess.Popen(
                        cmd,
                        stdin=subprocess.DEVNULL,       # <-- FIX: niente prompt bloccanti
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        bufsize=1,
                        universal_newlines=True,
                    )
                except Exception as e:
                    self.finished.emit(False, f"Impossibile avviare vobcopy: {e}", [], "")
                    return

                self._proc = p

                # prova a trovare il file output mentre cresce
                out_guess: Optional[Path] = None
                last_find_ts = 0.0
                last_stdout_ts = 0.0
                cur_bytes = 0
                cur_bytes_from_percent: Optional[int] = None

                while p.poll() is None:
                    if self._stop:
                        try:
                            p.terminate()
                        except Exception:
                            pass
                        self.finished.emit(False, "Annullato.", [], "")
                        return

                    # 1) leggi output (non bloccante) con timeout corto
                    try:
                        r, _, _ = select.select([p.stdout], [], [], 0.20) if p.stdout else ([], [], [])
                    except Exception:
                        r = []

                    if r and p.stdout:
                        try:
                            line = p.stdout.readline()
                        except Exception:
                            line = ""
                        if line:
                            last_stdout_ts = time.time()
                            sline = line.strip()
                            if sline:
                                # non spammo ogni riga: tengo solo le “utili”
                                pp = _parse_percent(sline)
                                if pp is not None and expected > 0:
                                    cur_bytes_from_percent = int(round(expected * (pp / 100.0)))
                                # se vuoi vedere log grezzo:
                                # self.stage.emit(f"Vobcopy: {sline}")
                        else:
                            # nessuna riga
                            pass

                    # 2) trova output file (non ogni giro, costa)
                    now = time.time()
                    if out_guess is None and (now - last_find_ts) >= 0.8:
                        last_find_ts = now
                        try:
                            out_guess = self._locate_extracted(run_dir, name)
                        except Exception:
                            out_guess = None

                    # 3) calcola bytes correnti
                    if cur_bytes_from_percent is not None:
                        cur_bytes = max(0, cur_bytes_from_percent)
                    else:
                        if out_guess is not None:
                            try:
                                cur_bytes = int(out_guess.stat().st_size)
                            except Exception:
                                cur_bytes = 0
                        else:
                            cur_bytes = 0

                    # clamp se conosco expected
                    if expected > 0 and cur_bytes > expected:
                        cur_bytes = expected

                    # 4) emetti progress “a byte” frequentemente (ETA fluida)
                    if bytes_total != len(wanted):
                        emit_pct(done_bytes, cur_bytes)
                    else:
                        # fallback “a file”
                        emit_pct(done_bytes + 1, 0)

                # processo finito
                rc = p.returncode
                self._proc = None

                if rc != 0:
                    self.finished.emit(False, f"vobcopy fallito su {name} (rc={rc}).", [], "")
                    return

                # individua output finale e spostalo in dest
                outp = out_guess
                if outp is None:
                    outp = self._locate_extracted(run_dir, name)

                if not outp or not outp.exists():
                    self.finished.emit(False, f"vobcopy OK ma output non trovato per {name}.", [], "")
                    return

                try:
                    # appiattisci in dest_dir
                    shutil.move(str(outp), str(dd / name))
                except Exception as e:
                    self.finished.emit(False, f"Impossibile spostare {name} in dest: {e}", [], "")
                    return

                # registra segmenti (>0)
                try:
                    # i segmenti film sono VTS_XX_1.VOB, _2.VOB, ... (non _0)
                    if re.match(rf"^VTS_{self.vts_num:02d}_[1-9]\d*\.VOB$", name.upper()):
                        staged_vobs.append(str(dd / name))
                except Exception:
                    pass

                # aggiorna done_bytes e “forza” progress
                if bytes_total != len(wanted):
                    # usa size reale se possibile, altrimenti expected
                    real_sz = 0
                    try:
                        real_sz = int((dd / name).stat().st_size)
                    except Exception:
                        real_sz = 0
                    done_bytes += max(real_sz, expected, 1)
                    emit_pct(done_bytes, 0, force=True)
                else:
                    done_bytes += 1
                    emit_pct(done_bytes, 0, force=True)

            # cleanup temp
            try:
                shutil.rmtree(str(run_dir), ignore_errors=True)
            except Exception:
                pass

            staged_vobs.sort(key=_nat_key)

            # se non ho ifo_path ma esiste quello “standard”, passalo
            if not ifo_path:
                cand = dd / f"VTS_{self.vts_num:02d}_0.IFO"
                if cand.exists():
                    ifo_path = str(cand)

            # validazioni minime
            if not staged_vobs:
                self.finished.emit(False, "Staging OK ma nessun segmento VOB (>0) trovato.", [], ifo_path or "")
                return

            for pth in staged_vobs:
                try:
                    if os.path.getsize(pth) < 128 * 1024:
                        self.finished.emit(False, f"Segmento troppo piccolo (probabile errore): {os.path.basename(pth)}", [], ifo_path or "")
                        return
                except Exception:
                    pass

            # progress 100% finale
            try:
                self.progress.emit(100)
            except Exception:
                pass

            self.finished.emit(True, "OK", staged_vobs, ifo_path or "")
            return

        except Exception as e:
            try:
                if run_dir is not None:
                    shutil.rmtree(str(run_dir), ignore_errors=True)
            except Exception:
                pass
            self.finished.emit(False, f"Errore staging: {e}", [], "")


# =============================================================================
#  Worker B: legacy (fileone con -n)
# =============================================================================
def _try_find_dvd_device() -> Optional[str]:
    for dev in ("/dev/dvd", "/dev/sr0", "/dev/cdrom"):
        try:
            if os.path.exists(dev):
                return dev
        except Exception:
            pass
    return None


def infer_title_from_vobs(selected_vobs: List[str], mount_path: str) -> int:
    """
    Prova a mappare VTS_xx → titolo (track) usando lsdvd -Ox.
    Se fallisce, fallback “ragionevole”: titolo = 1.
    """
    vts_num = None
    for s in selected_vobs or []:
        bn = os.path.basename(s)
        m = re.match(r"VTS_(\d{2})_\d+\.VOB$", bn, re.I)
        if m:
            vts_num = int(m.group(1))
            break

    if vts_num is None:
        return 1

    dvd_dev = mount_path if str(mount_path).startswith("/dev/") else (_try_find_dvd_device() or mount_path)

    try:
        p = subprocess.run(
            ["lsdvd", "-Ox", str(dvd_dev)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20,
        )
        xml = (p.stdout or "") + "\n" + (p.stderr or "")
        # cerca blocchi track e prova a prendere id + vts + length
        tracks: List[Tuple[int, int, int]] = []  # (id, vts, seconds)
        for blk in re.split(r"</track>", xml, flags=re.I):
            mid = re.search(r'track\s+id="(\d+)"', blk, flags=re.I)
            mvts = re.search(r"<vts>\s*(\d+)\s*</vts>", blk, flags=re.I) or re.search(r'vts="(\d+)"', blk, flags=re.I)
            mlen = re.search(r"<length>\s*([0-9:]+)\s*</length>", blk, flags=re.I)
            if not (mid and mvts):
                continue
            tid = int(mid.group(1))
            tvts = int(mvts.group(1))
            secs = 0
            if mlen:
                t = mlen.group(1).strip()
                parts = t.split(":")
                try:
                    if len(parts) == 3:
                        secs = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                    elif len(parts) == 2:
                        secs = int(parts[0]) * 60 + int(parts[1])
                except Exception:
                    secs = 0
            tracks.append((tid, tvts, secs))

        cand = [t for t in tracks if t[1] == vts_num]
        if cand:
            cand.sort(key=lambda x: x[2], reverse=True)
            return int(cand[0][0])
    except Exception:
        pass

    return 1


class VobcopyWorker(QThread):
    stage = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def __init__(self, mount_path: str, selected_vobs: List[str], final_path: str, prefer_ram: bool = True):
        super().__init__()
        self.mount_path = mount_path
        self.selected_vobs = list(selected_vobs)
        self.final_path = final_path
        self.prefer_ram = bool(prefer_ram)
        self._stop = False
        self._proc: Optional[subprocess.Popen] = None

    def stop(self):
        self._stop = True
        p = self._proc
        if p and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass

    def run(self):
        run_dir: Optional[Path] = None
        try:
            title_n = infer_title_from_vobs(self.selected_vobs, self.mount_path)
            self.stage.emit(f"Vobcopy: titolo {title_n}…")

            stage_base = _select_stage_dir(self.prefer_ram)
            run_dir = Path(tempfile.mkdtemp(prefix="vobcopy_", dir=str(stage_base)))

            # Anche qui mettiamo -x per coerenza (mai prompt)
            cmd = ["vobcopy", "-x", "-n", str(title_n), "-l", "-i", self.mount_path, "-o", str(run_dir)]
            self.stage.emit("Vobcopy: avvio…")
            _dprint(f"[VobcopyWorker] cmd={' '.join(cmd)}")

            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,          # <-- FIX: niente prompt bloccanti
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
            )

            try:
                assert self._proc.stdout is not None
                for line in self._proc.stdout:
                    if self._stop:
                        try:
                            self._proc.terminate()
                        except Exception:
                            pass
                        self.finished.emit(False, "Annullato.")
                        return
                    line = (line or "").strip()
                    if line:
                        self.stage.emit(f"Vobcopy: {line}")
            except Exception:
                pass

            rc = self._proc.wait()
            self._proc = None
            if rc != 0:
                self.finished.emit(False, f"vobcopy fallito (rc={rc})")
                return

            # scegli il VOB più grande prodotto
            vobs = []
            for p in run_dir.rglob("*.vob"):
                try:
                    vobs.append((p.stat().st_size, p))
                except Exception:
                    pass
            for p in run_dir.rglob("*.VOB"):
                try:
                    vobs.append((p.stat().st_size, p))
                except Exception:
                    pass
            if not vobs:
                self.finished.emit(False, "vobcopy finito ma non trovo VOB in output.")
                return

            vobs.sort(key=lambda x: x[0], reverse=True)
            src = vobs[0][1]
            dst = Path(self.final_path)

            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_suffix(dst.suffix + ".part")

            self.stage.emit(f"Scrivo: {dst.name}")
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass

            shutil.copy2(str(src), str(tmp))
            os.replace(str(tmp), str(dst))

            self.finished.emit(True, "OK")
        except Exception as e:
            self.finished.emit(False, f"Errore vobcopy: {e}")
        finally:
            if run_dir:
                try:
                    shutil.rmtree(str(run_dir), ignore_errors=True)
                except Exception:
                    pass
