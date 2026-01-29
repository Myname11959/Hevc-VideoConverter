#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from PyQt5.QtCore import QThread, pyqtSignal
import subprocess
import re


class ConversionThreadExternal(QThread):
    """
    Thread di conversione per una *traccia audio esterna*.
    Retro-compatibile: se non passi codec/canali, resta AAC stereo.
    """

    progress = pyqtSignal(int)
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(
        self,
        input_file: str,
        output_file: str,
        filters: list[str],
        bitrate: str,
        samplerate: str,
        duration: float,
        parent=None,
        *,
        codec: str = "aac",  # <— nuovo (default come prima)
        channels: int | None = 2,  # <— nuovo (None = non forzare)
        extra_out_opts: list[str] | None = None,  # <— opzionale
    ):
        super().__init__(parent)
        self.input_file = input_file
        self.output_file = output_file
        self.filters = filters or []
        self.bitrate = bitrate
        self.samplerate = samplerate
        self.duration = duration
        self.codec = codec or "aac"
        self.channels = channels
        self.extra_out_opts = extra_out_opts or []

    def run(self):
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            self.input_file,
            "-vn",  # disabilita video nell’output
            "-c:a",
            self.codec,
        ]
        if self.channels:
            cmd += ["-ac", str(self.channels)]

        if self.bitrate and self.bitrate != "Nessuno":
            cmd += ["-b:a", self.bitrate]

        if self.samplerate and self.samplerate != "Nessuno":
            cmd += ["-ar", self.samplerate]

        if self.filters:
            cmd += ["-af", ",".join(self.filters)]

        if self.extra_out_opts:
            cmd += list(self.extra_out_opts)

        cmd.append(self.output_file)

        # avvio e progress
        try:
            process = subprocess.Popen(cmd, stderr=subprocess.PIPE, universal_newlines=True, bufsize=1)
        except Exception as e:
            self.error.emit(f"Errore avvio ffmpeg: {e}")
            return

        # time=00:01:23.45
        time_regex = re.compile(r"time=(\d+):(\d+):(\d+)\.(\d+)")

        while True:
            line = process.stderr.readline()
            if not line:
                break
            m = time_regex.search(line)
            if m and self.duration > 0:
                h, m_, s, _ = m.groups()
                current_sec = int(h) * 3600 + int(m_) * 60 + int(s)
                progress = int(min(99, (current_sec / self.duration) * 100))
                self.progress.emit(progress)

        retcode = process.wait()
        if retcode != 0:
            self.error.emit(f"Errore ffmpeg, codice ritorno {retcode}")
            return

        self.progress.emit(100)
        self.finished.emit()


