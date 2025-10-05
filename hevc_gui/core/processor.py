# hevc_gui/core/processor.py

from pathlib import Path
import subprocess
from . import constants as C  # FFMPEG_BIN, TEMP_DIR, …
from .helpers import (
    make_logfile,
    cleanup_temp,
)  # build_filterchain, make_logfile, cleanup_temp
from .audio_helpers import (
    audio_tracks_with_title,
)  # audio_tracks_with_title
from .chapter import (
    ChapterManager,
    ChapterError,
)  # get_or_convert_chapters


def process_file(
    input_file: Path,
    output_file: Path,
    subtitle_files: list[Path] = (),
):
    """
    Esegue in pipeline:
      1) estrazione “copy” del video
      2) conversione di tutte le tracce audio in .m4a
      3) estrazione/compatibilizzazione capitoli in FFmetadata
      4) mux finale (video+audio+subs+chapters)
      5) pulizia tmp
    """
    tmp = C.TEMP_DIR
    tmp.mkdir(exist_ok=True)
    audio_dir = tmp / "audio_tracks"
    audio_dir.mkdir(exist_ok=True)
    video_tmp = tmp / "video_temp.mkv"

    # 1) estrai video
    cmd_video = [
        C.FFMPEG_BIN,
        "-y",
        "-nostdin",
        "-i",
        str(input_file),
        "-map",
        "0:v",
        "-c:v",
        "copy",
        str(video_tmp),
    ]
    subprocess.run(cmd_video, check=True)

    # 2) estrai liste tracce audio e costruisci comandi
    specs = audio_tracks_with_title(str(input_file))
    # specs = [(idx, title), …]
    audio_cmds = []
    for i, (idx, _) in enumerate(specs):
        out = audio_dir / f"track{i}.m4a"
        # 1 sola traccia per -map
        cmd = [
            C.FFMPEG_BIN,
            "-y",
            "-nostdin",
            "-i",
            str(input_file),
            "-map",
            f"0:{idx}",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-ac",
            "2",
            str(out),
        ]
        audio_cmds.append((out, cmd))

    for _, cmd in audio_cmds:
        subprocess.run(cmd, check=True)

    # 3) genera/recupera capitoli FFmetadata
    try:
        chap_file = ChapterManager.get_or_convert_chapters(input_file)
        chap_opts = ["-i", str(chap_file), "-map_metadata", "0"]
    except ChapterError:
        chap_opts = []

    # 4) costruisci mux finale
    cmd = [C.FFMPEG_BIN, "-y", "-nostdin", "-hide_banner", "-i", str(video_tmp)]
    # aggiungi input audio
    for out, _ in audio_cmds:
        cmd += ["-i", str(out)]
    # aggiungi input sottotitoli
    for s in subtitle_files:
        cmd += ["-i", str(s)]
    # input capitoli
    cmd += chap_opts

    # mappature e opzioni
    # video
    cmd += ["-map", "0:v", "-c:v", "copy"]
    # audio
    for i in range(len(audio_cmds)):
        cmd += [
            "-map",
            f"{i + 1}:a",
            "-c:a",
            "copy",
            f"-metadata:s:a:{i}",
            "language=ita",
        ]
    # sottotitoli
    first_sub = 1 + len(audio_cmds)
    for j in range(len(subtitle_files)):
        cmd += [
            "-map",
            f"{first_sub + j}:s",
            "-c:s",
            "copy",
            f"-metadata:s:s:{j}",
            "language=ita",
            "-disposition:s:0",
            "forced",
        ]
    # capitoli / metadata
    # chap_opts include già -map_metadata 0

    cmd.append(str(output_file))

    # metti il comando su file di log
    make_logfile(cmd)  #

    # esegui il mux
    subprocess.run(cmd, check=True)

    # 5) pulisci tmp
    cleanup_temp(remove_all=True)  #
