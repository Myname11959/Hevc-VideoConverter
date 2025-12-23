# ----------------------------------------------------------------------
#  Nuova versione "robusta" di ChapterManager
#  • usa capitoli già compatibili                       (ffmpeg → OK)
#  • se non lo sono, li converte in FFmetadata quando possibile
#    (QuickTime ©chp, Nero/MP4 JSON, …)
#  • per ogni video crea una propria sottocartella in TMP_DIR
# ----------------------------------------------------------------------

import json
import re
import subprocess
import hashlib
from pathlib import Path
from typing import List, Dict
from PyQt5.QtWidgets import QMessageBox, QInputDialog
from hevc_gui.core import constants as C  # il TMP_DIR viene da qui

# ── helper per directory “per video” ────────────────────────────────────


def _per_video_chapters_dir(video_path: Path) -> Path:
    """
    Restituisce un path unico per i metadata dei capitoli di questo video,
    costruito come TMP_DIR/hevc_gui_chapters/<stem>_<hash>/
    """
    # calcola hash breve del path (per evitare caratteri strani)
    h = hashlib.sha1(str(video_path).encode("utf-8")).hexdigest()[:8]
    base = C.TMP_DIR / "hevc_gui_chapters" / f"{video_path.stem}_{h}"
    base.mkdir(parents=True, exist_ok=True)
    return base


# --- Funzioni originali per generazione capitoli ---


def run_ffmpeg_command(input_file, threshold, ffmpeg_output_file):
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-i",
        input_file,
        "-vf",
        f"select='gt(scene,{threshold})',showinfo",
        "-an",
        "-f",
        "null",
        "-",
    ]
    with open(ffmpeg_output_file, "w") as f:
        subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT)


def parse_ffmpeg_log(ffmpeg_output_file):
    timestamps = []
    with open(ffmpeg_output_file, "r") as f:
        for line in f:
            if "pts_time" in line:
                parts = line.split("pts_time:")
                if len(parts) > 1:
                    try:
                        timestamps.append(float(parts[1].split(" ")[0]))
                    except ValueError:
                        continue
    return timestamps


def filter_timestamps(timestamps, min_duration, max_duration):
    filtered = [0]
    for i in range(1, len(timestamps)):
        delta = timestamps[i] - filtered[-1]
        if delta >= min_duration:
            if delta <= max_duration:
                filtered.append(timestamps[i])
            else:
                new_ts = filtered[-1] + max_duration
                while new_ts < timestamps[i]:
                    filtered.append(new_ts)
                    new_ts += max_duration
    return filtered


def write_chapters_file(timestamps, chapters_output_file):
    with open(chapters_output_file, "w", encoding="utf-8") as f:
        f.write(";FFMETADATA1\n")
        for idx in range(len(timestamps) - 1):
            start = int(timestamps[idx] * 1000)
            end = int(timestamps[idx + 1] * 1000)
            f.write(f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={start}\nEND={end}\ntitle=Chapter {idx + 1}\n")
        # ultimo capitolo di 1ms
        last_start = int(timestamps[-1] * 1000)
        f.write(f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={last_start}\nEND={last_start + 1}\ntitle=Chapter {len(timestamps)}\n")


def get_video_duration(input_file):
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        input_file,
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return float(res.stdout)


def generate_chapters(
    input_file,
    threshold,
    min_duration,
    max_duration,
    ffmpeg_output_file,
    chapters_output_file,
):
    if threshold == 0:
        duration = get_video_duration(input_file)
        timestamps = [i * max_duration for i in range(int(duration / max_duration) + 1)]
    else:
        run_ffmpeg_command(input_file, threshold, ffmpeg_output_file)
        timestamps = parse_ffmpeg_log(ffmpeg_output_file)
        if not timestamps:
            raise RuntimeError("No timestamps found in ffmpeg log.")
        timestamps = filter_timestamps(timestamps, min_duration, max_duration)
    write_chapters_file(timestamps, chapters_output_file)


def auto_generate_chapter_file(input_file: str, threshold: float) -> str:
    """
    Genera automaticamente i capitoli per scene-change e li salva in
    TMP_DIR/hevc_gui_chapters/<video>_<hash>/<video>_auto_chapters.txt.
    Ritorna il path al file generato.
    """
    video = Path(input_file)
    tmp = _per_video_chapters_dir(video)
    ffmpeg_log = tmp / "ffmpeg_log.txt"
    chapters_output = tmp / f"{video.stem}_auto_chapters.txt"
    min_dur, max_dur = 180, 300

    generate_chapters(str(video), threshold, min_dur, max_dur, str(ffmpeg_log), str(chapters_output))
    return str(chapters_output)


class ChapterError(RuntimeError):
    """Eccezione personalizzata per problemi con i capitoli."""


class ChapterManager:
    # ---------- estrazione diretta FFmpeg ---------------------------------
    @staticmethod
    def _extract_ffmetadata(src: Path, dst: Path) -> bool:
        """True se FFmpeg ha estratto almeno una riga CHAPTER=…"""
        cmd = [
            "ffmpeg",
            "-y",
            "-nostdin",
            "-loglevel",
            "error",
            "-i",
            str(src),
            "-map_chapters",
            "0",
            "-f",
            "ffmetadata",
            str(dst),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            txt = dst.read_text(errors="ignore")
            return bool(re.search(r"^CHAPTER\d{2}=", txt, re.M))
        except subprocess.CalledProcessError:
            return False

    # ---------- fallback QuickTime/©chp  ----------------------------------
    @staticmethod
    def _qtchp_to_ffmetadata(src: Path, dst: Path) -> bool:
        """
        Converte capitoli QuickTime (`udta/©chp`) in file FFmetadata.
        Ritorna True se sono stati trovati capitoli, False altrimenti.
        """
        try:
            raw = subprocess.check_output(
                [
                    "ffprobe",
                    "-v",
                    "quiet",
                    "-print_format",
                    "json",
                    "-show_chapters",
                    str(src),
                ],
                text=True,
            )
            info = json.loads(raw)
            chapters: List[Dict] = info.get("chapters", [])
            if not chapters:
                return False

            lines = [";FFMETADATA1"]
            for i, ch in enumerate(chapters, 1):
                t0 = float(ch["start_time"])
                lines += [
                    "[CHAPTER]",
                    "TIMEBASE=1/1000",
                    f"START={int(t0 * 1000)}",
                    f"END={int((t0 + 0.001) * 1000)}",
                    f"title={ch.get('tags', {}).get('title', f'Chapter {i}')}",
                ]
            dst.write_text("\n".join(lines), encoding="utf-8")
            return True
        except Exception:
            return False

    # ---------- nuovo: OGM → FFmetadata -----------------------------------
    @staticmethod
    def _ogm_to_ffmetadata(src: Path, dst: Path) -> bool:
        """
        Converte un file OGM/Matroska chapters.txt (CHAPTERxx=… / CHAPTERxxNAME=…)
        in un file FFmetadata (FFMETADATA1) con blocchi [CHAPTER].

        Esempio input:

          CHAPTER01=00:00:00.000
          CHAPTER01NAME=Intro
          CHAPTER02=00:05:12.500
          CHAPTER02NAME=Scena 2

        Gli END sono creati come START+1 ms (chapters “a punto”),
        che è sufficiente per la maggior parte dei player.
        """
        try:
            lines_in = src.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            return False

        times: Dict[int, float] = {}
        names: Dict[int, str] = {}

        rx_time = re.compile(r"^CHAPTER(\d+)\s*=\s*([0-9:.]+)")
        rx_name = re.compile(r"^CHAPTER(\d+)NAME\s*=\s*(.*)")

        def _parse_ts(ts: str) -> float | None:
            # accetta HH:MM:SS.mmm
            try:
                parts = ts.strip().split(":")
                if len(parts) != 3:
                    return None
                h = int(parts[0])
                m = int(parts[1])
                s = float(parts[2])
                return h * 3600 + m * 60 + s
            except Exception:
                return None

        for raw in lines_in:
            line = raw.strip()
            if not line:
                continue
            m = rx_time.match(line)
            if m:
                idx = int(m.group(1))
                t = _parse_ts(m.group(2))
                if t is not None:
                    times[idx] = t
                continue
            m = rx_name.match(line)
            if m:
                idx = int(m.group(1))
                title = m.group(2).strip()
                names[idx] = title or f"Chapter {idx:02d}"

        if not times:
            # niente CHAPTERxx=… → non è un file OGM valido
            return False

        # ordina per indice capitolo
        indices = sorted(times.keys())
        out: List[str] = [";FFMETADATA1"]

        for idx in indices:
            t0 = times[idx]
            start = int(round(t0 * 1000))
            end = start + 1  # punto singolo, come nel fallback QuickTime
            title = names.get(idx) or f"Chapter {idx:02d}"
            out += [
                "[CHAPTER]",
                "TIMEBASE=1/1000",
                f"START={start}",
                f"END={end}",
                f"title={title}",
            ]

        try:
            dst.write_text("\n".join(out), encoding="utf-8")
            return True
        except OSError:
            return False

    # ---------- API pubbliche --------------------------------------------
    @staticmethod
    def get_embedded_chapters(input_file: Path) -> List[Dict]:
        """Ritorna la lista di capitoli che ffprobe trova nel video."""
        try:
            out = subprocess.check_output(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-print_format",
                    "json",
                    "-show_chapters",
                    str(input_file),
                ],
                text=True,
            )
            return json.loads(out).get("chapters", [])
        except Exception:
            return []

    @classmethod
    def get_or_convert_chapters(cls, video: Path) -> Path:
        """
        Cerca di ottenere un file FFmetadata compatibile con FFmpeg.

        Priorità:

          0) se esiste <basename>.chapters_ogm.txt accanto al video,
             prova a convertirlo in FFmetadata;
          1) prova l’estrazione diretta con FFmpeg;
          2) se fallisce, tenta la conversione (QuickTime ©chp);
          3) se non c’è alcun formato gestibile, genera automaticamente;
          4) se ancora nulla ⇒ solleva ChapterError.
        """
        # dir dedicata e nome per questo video
        tmp_dir = _per_video_chapters_dir(video)
        meta = tmp_dir / f"{video.stem}_chapters.txt"

        # 0) sidecar OGM accanto al file video (universale, vale anche per VOB LDVD)
        ogm = video.with_suffix(".chapters_ogm.txt")
        try:
            if ogm.is_file():
                if cls._ogm_to_ffmetadata(ogm, meta):
                    return meta
        except Exception:
            # meglio non esplodere se il file è strano
            pass

        # 1) estrazione diretta da capitoli incorporati
        if cls._extract_ffmetadata(video, meta):
            return meta

        # 2) fallback QuickTime (©chp ecc.)
        if cls._qtchp_to_ffmetadata(video, meta):
            return meta

        # 3) fallback automatico scene-change
        auto_meta = Path(auto_generate_chapter_file(str(video), 0.4))
        if auto_meta.exists():
            return auto_meta

        # 4) nessun capitolo compatibile
        raise ChapterError("Nessun capitolo compatibile trovato.")

    # ---------- dialogo GUI ----------------------------------------------
    @classmethod
    def run_selection(cls, input_file: Path, parent=None) -> List[str]:
        """
        Usato dal GUI per il pulsante “Capitoli”.
        Restituisce opzioni FFmpeg da aggiungere (-i <meta> -map_metadata …).
        """
        embedded = cls.get_embedded_chapters(input_file)
        if embedded:
            count = len(embedded)
            if (
                QMessageBox.question(
                    parent,
                    "Chapters",
                    f"Trovati {count} capitoli incorporati. Vuoi usarli?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                == QMessageBox.Yes
            ):
                meta = cls.get_or_convert_chapters(input_file)
                QMessageBox.information(parent, "Chapters", f"Usati {count} capitoli incorporati.")
                # map_metadata placeholder → MainWindow lo sostituirà
                return ["-i", str(meta), "-map_metadata", "DUMMY"]

        # generazione automatica via threshold
        thr, ok = QInputDialog.getDouble(
            parent,
            "Threshold Scene Change",
            "Inserisci soglia (0.0 – 1.0):",
            0.4,
            0.0,
            1.0,
            2,
        )
        if not ok:
            return []

        meta_path = auto_generate_chapter_file(str(input_file), thr)
        gen_cnt = Path(meta_path).read_text(encoding="utf-8").count("[CHAPTER]")

        if (
            QMessageBox.question(
                parent,
                "Chapters",
                f"Generati {gen_cnt} capitoli. Vuoi usarli?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            == QMessageBox.Yes
        ):
            QMessageBox.information(parent, "Chapters", f"Usati {gen_cnt} capitoli generati.")
            return ["-i", meta_path, "-map_metadata", "DUMMY"]

        return []
