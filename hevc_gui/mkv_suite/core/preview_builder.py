from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Optional


def project_preview_dir(project_root: Path) -> Path:
    d = project_root / "tmp" / "preview"
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_preview_output(
    preview_dir: Path,
    src: Path,
    audio_tid: Optional[int],
    subtitle_tid: Optional[int] = None,
    audio_delay_ms: Optional[int] = None,
    subtitle_delay_ms: Optional[int] = None,
) -> Path:
    # backward compatibility: old call was (preview_dir, src, audio_tid, audio_delay_ms)
    if audio_delay_ms is None and subtitle_delay_ms is None:
        audio_delay_ms = int(subtitle_tid or 0)
        subtitle_tid = None
        subtitle_delay_ms = 0

    audio_delay_ms = int(audio_delay_ms or 0)
    subtitle_delay_ms = int(subtitle_delay_ms or 0)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    a = f"a{int(audio_tid)}_{audio_delay_ms:+d}ms" if audio_tid is not None else "ano"
    s = f"s{int(subtitle_tid)}_{subtitle_delay_ms:+d}ms" if subtitle_tid is not None else "sno"
    return preview_dir / f"{src.stem}_preview_{a}_{s}_{stamp}.mkv"


def build_preview_cmd(
    mkvmerge_bin: str,
    src: Path,
    out_file: Path,
    video_tid: int,
    audio_tid: Optional[int] = None,
    subtitle_tid: Optional[int] = None,
    audio_delay_ms: Optional[int] = None,
    subtitle_delay_ms: Optional[int] = None,
    external_subtitle_file: Optional[Path] = None,
) -> List[str]:
    # backward compatibility: old call was (..., video_tid, audio_tid, audio_delay_ms)
    if audio_delay_ms is None and subtitle_delay_ms is None and subtitle_tid is not None and audio_tid is not None:
        audio_delay_ms = int(subtitle_tid or 0)
        subtitle_tid = None
        subtitle_delay_ms = 0

    audio_delay_ms = int(audio_delay_ms or 0)
    subtitle_delay_ms = int(subtitle_delay_ms or 0)

    cmd: List[str] = [mkvmerge_bin, "-o", str(out_file)]

    # opzioni per il file principale
    cmd += ["--video-tracks", str(int(video_tid))]
    if audio_tid is not None:
        cmd += ["--audio-tracks", str(int(audio_tid))]
    else:
        cmd += ["--no-audio"]

    if external_subtitle_file is None:
        if subtitle_tid is not None:
            cmd += ["--subtitle-tracks", str(int(subtitle_tid))]
        else:
            cmd += ["--no-subtitles"]
    else:
        cmd += ["--no-subtitles"]

    cmd += ["--no-buttons"]

    if audio_tid is not None and audio_delay_ms != 0:
        cmd += ["--sync", f"{int(audio_tid)}:{audio_delay_ms}"]

    cmd += [str(src)]

    if external_subtitle_file is not None:
        if subtitle_delay_ms != 0:
            cmd += ["--sync", f"0:{subtitle_delay_ms}"]
        cmd += [str(external_subtitle_file)]
    elif subtitle_tid is not None and subtitle_delay_ms != 0:
        cmd += ["--sync", f"{int(subtitle_tid)}:{subtitle_delay_ms}"]

    return cmd
