#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List, Optional
import os, errno, time, threading, shutil
from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal

MIN_CHUNK = 16 * 1024  # 16 KiB


def _fmt_kib(n: int) -> str:
    return f"{n/1024:.0f} KiB" if n < 1024 * 1024 else f"{n/1024/1024:.2f} MiB"


class CopyWorker(QThread):
    """
    Copia/concat VOB.

    - progress(int): 0..100
    - bytes_progress(done_bytes, total_bytes): più “fluido” per ETA accurata
    - need_vobcopy(list[str]): richiede fallback vobcopy (tipico su DVD con EIO)
    """
    progress = pyqtSignal(int)               # 0..100
    stage    = pyqtSignal(str)               # testo fase (anche warning I/O)
    finished = pyqtSignal(bool, str)         # ok, message
    need_vobcopy = pyqtSignal(list)          # list[str] sorgenti selezionate

    bytes_progress = pyqtSignal(int, int)    # done_bytes, total_bytes  ✅

    def __init__(
        self,
        sources: List[str],
        final_path: str,
        chunk_size: int = 1024 * 1024,
        stage_in_ram: bool = True,
        work_base: Optional[str] = None,
        skip_on_eio: bool = True,
        skip_step: int = MIN_CHUNK,
        max_skip_bytes: int = 8 * 1024 * 1024,
        write_part_in_dest: bool = False,
    ):
        super().__init__()
        self.sources    = [s for s in sources if s and os.path.isfile(s)]
        self.final_path = final_path
        self.init_chunk = max(MIN_CHUNK, int(chunk_size))
        self.stage_in_ram = bool(stage_in_ram)
        self.work_base = work_base
        self.skip_on_eio = bool(skip_on_eio)
        self.skip_step = max(MIN_CHUNK, int(skip_step))
        self.max_skip_bytes = max(self.skip_step, int(max_skip_bytes))
        self.write_part_in_dest = bool(write_part_in_dest)

        self._stop_evt = threading.Event()
        self._last_pct = -1
        self._last_emit = 0.0

        self._skipped_total = 0
        self._last_skip_msg_ts = 0.0

        # throttle separato per bytes_progress
        self._last_bytes_emit = 0.0

    def stop(self):
        self._stop_evt.set()

    def _emit_progress(self, done: int, total: int, force: bool = False):
        if total <= 0:
            return

        done = max(0, min(int(done), int(total)))

        # 1) % (come prima)
        pct = int((done * 100) / total)
        now = time.time()
        if force or (pct != self._last_pct and (now - self._last_emit) > 0.08):
            self._last_pct = pct
            self._last_emit = now
            try:
                self.progress.emit(max(0, min(100, pct)))
            except Exception:
                pass

        # 2) bytes_progress (più frequente)
        if force or (now - self._last_bytes_emit) > 0.25:
            self._last_bytes_emit = now
            try:
                self.bytes_progress.emit(int(done), int(total))
            except Exception:
                pass

    def _project_tmp_dir(self) -> Path:
        """…/dvd_ripper/.tmp/dvd_ripper (locale al progetto)."""
        pkg_dir = Path(__file__).resolve().parent
        proj_root = pkg_dir.parent
        tmp_dir = proj_root / ".tmp" / "dvd_ripper"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        return tmp_dir

    def _choose_stage_dir(self, need_bytes: int) -> Path:
        """
        1) Prova RAM: /dev/shm/dvd_ripper (preferita)
        2) Se c'è 'work_base', usa quella
        3) Altrimenti tmp locale del progetto (…/dvd_ripper/.tmp/dvd_ripper)
        """
        MARGIN = 256 * 1024 * 1024  # 256 MiB

        # 1) RAM
        if self.stage_in_ram and Path("/dev/shm").is_dir():
            ram = Path("/dev/shm") / "dvd_ripper"
            try:
                ram.mkdir(parents=True, exist_ok=True)
            except Exception:
                ram = None
            if ram:
                try:
                    total, used, free = shutil.disk_usage(str(ram))
                except Exception:
                    free = 0
                if free >= need_bytes + MARGIN and os.access(str(ram), os.W_OK):
                    try:
                        self.stage.emit(
                            f"Info: scelgo RAM (/dev/shm) — free={free//(1024*1024)} MiB, "
                            f"need={(need_bytes//(1024*1024))} MiB"
                        )
                    except Exception:
                        pass
                    return ram

        # 2) work_base esplicita
        if self.work_base:
            base = Path(self.work_base)
            try:
                base.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            return base

        # 3) tmp locale progetto
        tmp = self._project_tmp_dir()
        try:
            total, used, free = shutil.disk_usage(str(tmp))
            self.stage.emit(
                f"Info: uso tmp locale — free={free//(1024*1024)} MiB, need={(need_bytes//(1024*1024))} MiB"
            )
        except Exception:
            pass
        return tmp

    def _io_skip(self, fin, how_many: int, src_name: str) -> int:
        """Prova a saltare 'how_many' byte nel file sorgente corrente."""
        try:
            pos_before = fin.tell()
            fin.seek(how_many, os.SEEK_CUR)
            pos_after = fin.tell()
            skipped = int(pos_after - pos_before)
        except Exception:
            skipped = 0

        if skipped > 0:
            self._skipped_total += skipped
            now = time.time()
            if now - self._last_skip_msg_ts > 0.25:
                self._last_skip_msg_ts = now
                self.stage.emit(
                    f"I/O: salto {_fmt_kib(skipped)} in '{os.path.basename(src_name)}' "
                    f"(totale saltato {_fmt_kib(self._skipped_total)})"
                )
        return skipped

    def _write_zeros(self, fout, n: int, chunk: int = 1024 * 1024):
        """Scrive n byte di zeri senza allocare un buffer gigante."""
        if n <= 0:
            return
        zero = b"\x00" * min(chunk, n)
        left = n
        while left > 0:
            w = min(left, len(zero))
            fout.write(zero[:w])
            left -= w

    def run(self):
        if not self.sources:
            self.finished.emit(False, "Nessun file sorgente valido.")
            return

        # dimensione totale attesa
        total = 0
        for s in self.sources:
            try:
                total += os.stat(s).st_size
            except Exception:
                pass
        if total <= 0:
            self.finished.emit(False, "Dimensione totale nulla.")
            return

        final_path = Path(self.final_path)

        # === decide dove scrivere lo staging ===
        stage_path: Path
        stage_dir: Optional[Path] = None

        if self.write_part_in_dest:
            try:
                final_path.parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            stage_path = final_path.with_suffix(final_path.suffix + ".part")
            try:
                if stage_path.exists():
                    stage_path.unlink()
            except Exception:
                pass
            self.stage.emit(f"Normale: scrivo su disco → {stage_path.name}")
        else:
            try:
                stage_dir = self._choose_stage_dir(total)
            except Exception as e:
                self.finished.emit(False, str(e))
                return

            name, ext = os.path.splitext(os.path.basename(self.final_path))
            if not ext:
                ext = ".vob"
            stage_path = stage_dir / f".copy_{os.getpid()}_{int(time.time())}{ext}"

            self.stage.emit(
                "Normale: copia in RAM…" if stage_dir.as_posix().startswith("/dev/shm")
                else "Normale: copia su tmp locale…"
            )

        bytes_done = 0
        chunk = self.init_chunk

        try:
            self._emit_progress(0, total, force=True)

            with open(stage_path, "wb", buffering=0) as fout:
                for src in self.sources:
                    if self._stop_evt.is_set():
                        try:
                            if stage_path.exists():
                                stage_path.unlink()
                        except Exception:
                            pass
                        self.finished.emit(False, "Estrazione annullata.")
                        return

                    self.stage.emit(f"Copia: {os.path.basename(src)}")

                    with open(src, "rb", buffering=0) as fin:
                        while not self._stop_evt.is_set():
                            try:
                                buf = fin.read(chunk)
                                if not buf:
                                    break
                                fout.write(buf)
                                bytes_done += len(buf)
                                self._emit_progress(bytes_done, total)

                            except OSError as e:
                                if e.errno in (errno.EIO, errno.EREMOTEIO, errno.EBUSY):
                                    # 1) riduci chunk se puoi
                                    if chunk > MIN_CHUNK:
                                        chunk = max(MIN_CHUNK, chunk // 4)
                                        time.sleep(0.02)
                                        continue

                                    # 2) chunk minimo -> prova skip + padding
                                    if self.skip_on_eio and self._skipped_total < self.max_skip_bytes:
                                        skipped = self._io_skip(fin, self.skip_step, src)
                                        if skipped > 0:
                                            # padding a zeri per non “accorciare” il file
                                            try:
                                                self._write_zeros(fout, skipped)
                                            except Exception:
                                                pass
                                            bytes_done += skipped
                                            self._emit_progress(bytes_done, total)
                                            continue

                                    # 3) troppi errori -> richiedi fallback vobcopy
                                    self.stage.emit("I/O: troppi errori, richiedo fallback vobcopy…")
                                    try:
                                        self.need_vobcopy.emit(list(self.sources))
                                    except Exception:
                                        pass
                                    # pulizia
                                    try:
                                        if stage_path.exists():
                                            stage_path.unlink()
                                    except Exception:
                                        pass
                                    self.finished.emit(False, "FALLBACK_VOBCOPY")
                                    return

                                # altro errore -> abort
                                raise

            # clamp finale
            if bytes_done > total:
                bytes_done = total
            self._emit_progress(total, total, force=True)

            # === commit finale ===
            if self.write_part_in_dest:
                # stage_path è già <final>.part: rename atomico
                try:
                    os.replace(str(stage_path), str(final_path))
                except Exception as e:
                    self.finished.emit(False, f"Impossibile finalizzare output: {e}")
                    return
            else:
                # stage_path è in RAM/tmp: copia su <final>.part, poi replace
                try:
                    final_path.parent.mkdir(parents=True, exist_ok=True)
                except Exception:
                    pass

                tmp = final_path.with_suffix(final_path.suffix + ".part")
                try:
                    if tmp.exists():
                        tmp.unlink()
                except Exception:
                    pass

                self.stage.emit(f"Scrivo finale: {final_path.name}")

                try:
                    # prova move diretto (se stesso filesystem)
                    os.replace(str(stage_path), str(tmp))
                except OSError as e:
                    # cross-device: copia + remove
                    if getattr(e, "errno", None) == errno.EXDEV:
                        with open(stage_path, "rb", buffering=0) as f_in, open(tmp, "wb", buffering=0) as f_out:
                            shutil.copyfileobj(f_in, f_out, length=4 * 1024 * 1024)
                        try:
                            stage_path.unlink()
                        except Exception:
                            pass
                    else:
                        self.finished.emit(False, f"Errore scrivendo output: {e}")
                        return

                try:
                    os.replace(str(tmp), str(final_path))
                except Exception as e:
                    self.finished.emit(False, f"Impossibile finalizzare output: {e}")
                    return

            msg = "OK"
            if self._skipped_total > 0:
                msg = f"OK (saltati {_fmt_kib(self._skipped_total)})"

            self.finished.emit(True, msg)

        except Exception as e:
            # cleanup best-effort
            try:
                if stage_path and stage_path.exists():
                    stage_path.unlink()
            except Exception:
                pass
            self.finished.emit(False, f"Errore copia/concat: {e}")
