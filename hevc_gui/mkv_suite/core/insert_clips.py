from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional
import shutil
import subprocess
import re

from hevc_gui.mkv_suite.core.precise_cut import (
    probe_media_model,
    choose_video_encoder,
    choose_audio_encoder,
    parse_progress_line,
    progress_percent_from_kv,
)


@dataclass(slots=True)
class InsertClipItem:
    insert_at: float
    clip_path: Path
    mute: bool = False


@dataclass(slots=True)
class InsertClipsPlan:
    source_path: Path
    output_path: Path
    items: list[InsertClipItem]
    total_duration: float
    command: list[str]


def _require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"Tool non trovato nel PATH: {name}")


def _fmt_sec(sec: float) -> str:
    return f"{float(sec):.6f}"


def _valid_rate_str(rate: Optional[str]) -> Optional[str]:
    s = (rate or "").strip()
    if not s or s in {"0/0", "N/A"}:
        return None
    if "/" in s:
        a, b = s.split("/", 1)
        try:
            if int(a) <= 0 or int(b) <= 0:
                return None
        except Exception:
            return None
    return s


def _valid_ratio_str(value: Optional[str]) -> Optional[str]:
    s = (value or "").strip()
    if not s or s in {"0:0", "0:1", "N/A"}:
        return None
    if ":" not in s:
        return None
    a, b = s.split(":", 1)
    try:
        if int(a) <= 0 or int(b) <= 0:
            return None
    except Exception:
        return None
    return s


def _ratio_for_filter(value: Optional[str]) -> Optional[str]:
    s = _valid_ratio_str(value)
    if not s:
        return None
    return s.replace(":", "/")

def _even_int(value: float | int, fallback: int) -> int:
    try:
        n = int(round(float(value)))
    except Exception:
        n = int(fallback)
    if n <= 0:
        n = int(fallback)
    if n % 2:
        n += 1
    return max(2, n)


def _ratio_nums(value: Optional[str]) -> Optional[tuple[int, int]]:
    s = _valid_ratio_str(value)
    if not s:
        return None
    a, b = s.split(":", 1)
    try:
        ai = int(a)
        bi = int(b)
        if ai <= 0 or bi <= 0:
            return None
        return ai, bi
    except Exception:
        return None


def _source_display_geometry(video) -> tuple[int, int]:
    width = int(getattr(video, "width", 0) or 0) or 1920
    height = int(getattr(video, "height", 0) or 0) or 1080

    dar = _ratio_nums(getattr(video, "display_aspect_ratio", None))
    if dar:
        disp_w = _even_int(height * dar[0] / dar[1], width)
        return disp_w, _even_int(height, height)

    sar = _ratio_nums(getattr(video, "sample_aspect_ratio", None))
    if sar:
        disp_w = _even_int(width * sar[0] / sar[1], width)
        return disp_w, _even_int(height, height)

    return _even_int(width, width), _even_int(height, height)


def _audio_layout_name(channels: Optional[int], layout: Optional[str]) -> str:
    if layout:
        s = str(layout).strip()
        if s:
            return s
    ch = int(channels or 2)
    if ch <= 1:
        return "mono"
    if ch == 2:
        return "stereo"
    if ch == 6:
        return "5.1"
    if ch == 8:
        return "7.1"
    return "stereo"


def _normalize_items(items: Iterable[InsertClipItem], source_duration: float) -> list[InsertClipItem]:
    out: list[InsertClipItem] = []
    for item in items:
        at = float(item.insert_at)
        if at < 0.0:
            at = 0.0
        if at > source_duration:
            at = source_duration
        clip_path = Path(item.clip_path).expanduser().resolve()
        if not clip_path.is_file():
            raise RuntimeError(f"Clip non trovata: {clip_path}")
        out.append(InsertClipItem(insert_at=at, clip_path=clip_path, mute=bool(item.mute)))
    out.sort(key=lambda it: (it.insert_at, str(it.clip_path)))
    return out


def _video_rate_args(video, encoder: str) -> list[str]:
    if getattr(video, "bit_rate", None):
        return ["-b:v:0", str(int(video.bit_rate))]
    if encoder == "libx264":
        return ["-crf:v:0", "18"]
    return ["-crf:v:0", "20"]


def _audio_rate_args(audio, out_idx: int, encoder: str) -> list[str]:
    bit_rate = getattr(audio, "bit_rate", None)
    channels = int(getattr(audio, "channels", 2) or 2)
    if bit_rate:
        return [f"-b:a:{out_idx}", str(int(bit_rate))]
    if encoder == "aac":
        if channels <= 2:
            return [f"-b:a:{out_idx}", "192k"]
        if channels <= 6:
            return [f"-b:a:{out_idx}", "448k"]
        return [f"-b:a:{out_idx}", "640k"]
    if encoder in {"ac3", "eac3"}:
        if channels <= 2:
            return [f"-b:a:{out_idx}", "192k"]
        if channels <= 6:
            return [f"-b:a:{out_idx}", "640k"]
        return [f"-b:a:{out_idx}", "768k"]
    if encoder == "libmp3lame":
        return [f"-b:a:{out_idx}", "192k"]
    return []


def _video_metadata_args(video) -> list[str]:
    args = []
    if getattr(video, "pix_fmt", None):
        args += ["-pix_fmt:v:0", str(video.pix_fmt)]
    if getattr(video, "color_range", None):
        args += ["-color_range:v:0", str(video.color_range)]
    if getattr(video, "color_space", None):
        args += ["-colorspace:v:0", str(video.color_space)]
    if getattr(video, "color_transfer", None):
        args += ["-color_trc:v:0", str(video.color_transfer)]
    if getattr(video, "color_primaries", None):
        args += ["-color_primaries:v:0", str(video.color_primaries)]
    if getattr(video, "title", None):
        args += ["-metadata:s:v:0", f"title={video.title}"]
    if getattr(video, "language", None):
        args += ["-metadata:s:v:0", f"language={video.language}"]
    return args


def _audio_metadata_args(audio, out_idx: int) -> list[str]:
    args = []
    if getattr(audio, "sample_rate", None):
        args += [f"-ar:a:{out_idx}", str(int(audio.sample_rate))]
    if getattr(audio, "channels", None):
        args += [f"-ac:a:{out_idx}", str(int(audio.channels))]
    if getattr(audio, "language", None):
        args += [f"-metadata:s:a:{out_idx}", f"language={audio.language}"]
    if getattr(audio, "title", None):
        args += [f"-metadata:s:a:{out_idx}", f"title={audio.title}"]

    disp = []
    if getattr(audio, "disposition_default", False):
        disp.append("default")
    if getattr(audio, "disposition_forced", False):
        disp.append("forced")
    args += [f"-disposition:a:{out_idx}", "+".join(disp) if disp else "0"]
    return args


def _source_video_norm_steps(video) -> list[str]:
    steps: list[str] = []
    sar = _ratio_for_filter(getattr(video, "sample_aspect_ratio", None))
    dar = _ratio_for_filter(getattr(video, "display_aspect_ratio", None))
    if sar:
        steps.append(f"setsar={sar}")
    if dar:
        steps.append(f"setdar={dar}")
    return steps



def _parse_mean_volume_db(text: str) -> Optional[float]:
    m = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", str(text or ""))
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


def _probe_mean_volume_db(path: str | Path, start_sec: Optional[float] = None, dur_sec: Optional[float] = None) -> Optional[float]:
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "info"]
    if start_sec is not None and float(start_sec) > 0:
        cmd += ["-ss", _fmt_sec(float(start_sec))]
    if dur_sec is not None and float(dur_sec) > 0:
        cmd += ["-t", _fmt_sec(float(dur_sec))]
    cmd += [
        "-i", str(Path(path).expanduser().resolve()),
        "-map", "0:a:0?",
        "-vn",
        "-sn",
        "-dn",
        "-af", "volumedetect",
        "-f", "null",
        "-",
    ]
    cp = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return _parse_mean_volume_db(cp.stdout or "")


def _clamp_db(value: float, lo: float = -6.0, hi: float = 6.0) -> float:
    return max(lo, min(hi, float(value)))


def _nearby_active_ref_db(source_path: str | Path, at_sec: float, source_duration: float) -> Optional[float]:
    window = 3.0
    max_scan = 60.0
    threshold = -45.0
    radius = 0.0
    while radius <= max_scan:
        vals: list[float] = []

        b_end = float(at_sec) - radius
        b_start = b_end - window
        if b_end > 0.0 and b_start < b_end:
            mean_b = _probe_mean_volume_db(source_path, max(0.0, b_start), min(window, b_end - max(0.0, b_start)))
            if mean_b is not None and mean_b > threshold:
                vals.append(float(mean_b))

        a_start = float(at_sec) + radius
        a_end = a_start + window
        if a_start < float(source_duration):
            mean_a = _probe_mean_volume_db(source_path, a_start, min(window, max(0.0, float(source_duration) - a_start)))
            if mean_a is not None and mean_a > threshold:
                vals.append(float(mean_a))

        if vals:
            return sum(vals) / float(len(vals))

        radius += window

    return None


def _global_ref_db(source_path: str | Path) -> Optional[float]:
    return _probe_mean_volume_db(source_path, None, None)


def _clip_gain_db(
    source_path: str | Path,
    source_duration: float,
    insert_at: float,
    clip_path: str | Path,
    audio_match_mode: str,
) -> float:
    mode = str(audio_match_mode or "nearby").strip().lower()
    clip_db = _probe_mean_volume_db(clip_path, None, None)
    if clip_db is None:
        return 0.0

    if mode == "global":
        ref_db = _global_ref_db(source_path)
    else:
        ref_db = _nearby_active_ref_db(source_path, float(insert_at), float(source_duration))
        if ref_db is None:
            ref_db = _global_ref_db(source_path)

    if ref_db is None:
        return 0.0

    gain_db = _clamp_db(float(ref_db) - float(clip_db))
    if abs(gain_db) < 0.25:
        return 0.0
    return float(gain_db)


def build_insert_clips_plan(
    source_path: str | Path,
    output_path: str | Path,
    items: Iterable[InsertClipItem],
    audio_match_mode: str = "nearby",
) -> InsertClipsPlan:
    _require_tool("ffmpeg")
    _require_tool("ffprobe")

    source = probe_media_model(source_path)
    source_duration = float(source.duration or 0.0)
    if source_duration <= 0:
        raise RuntimeError("Durata sorgente non disponibile.")

    items_norm = _normalize_items(items, source_duration)
    if not items_norm:
        raise RuntimeError("Nessuna clip da inserire.")

    clip_media = []
    total_insert_duration = 0.0
    for item in items_norm:
        media = probe_media_model(item.clip_path)
        dur = float(media.duration or 0.0)
        if dur <= 0:
            raise RuntimeError(f"Durata clip non disponibile: {item.clip_path}")
        clip_media.append((item, media, dur))
        total_insert_duration += dur

    inputs: list[str] = ["-i", str(Path(source_path).expanduser().resolve())]
    clip_input_indices: list[int] = []
    silence_input_indices: list[int] = []

    primary_audio = source.audios[0] if source.audios else None
    silence_rate = int(getattr(primary_audio, "sample_rate", 48000) or 48000)
    silence_layout = _audio_layout_name(
        getattr(primary_audio, "channels", 2),
        getattr(primary_audio, "channel_layout", None),
    )

    next_input_idx = 1
    for item, media, dur in clip_media:
        clip_input_indices.append(next_input_idx)
        inputs += ["-i", str(item.clip_path)]
        next_input_idx += 1

        silence_input_indices.append(next_input_idx)
        inputs += ["-f", "lavfi", "-t", _fmt_sec(dur), "-i", f"anullsrc=r={silence_rate}:cl={silence_layout}"]
        next_input_idx += 1

    video = source.video
    width = int(video.width or 0) or 1920
    height = int(video.height or 0) or 1080
    width = _even_int(width, width)
    height = _even_int(height, height)

    disp_width, disp_height = _source_display_geometry(video)

    pix_fmt = str(getattr(video, "pix_fmt", None) or "yuv420p")
    fps = _valid_rate_str(getattr(video, "avg_frame_rate", None)) or _valid_rate_str(getattr(video, "r_frame_rate", None))
    vnorm_steps = _source_video_norm_steps(video)

    parts: list[str] = []
    maps: list[str] = []

    sequence_video_labels: list[str] = []
    sequence_audio_labels: list[list[str]] = [[] for _ in source.audios]

    pos = 0.0
    src_seg_idx = 0

    for idx, (item, media, dur) in enumerate(clip_media):
        at = float(item.insert_at)

        if at > pos:
            vlab = f"[sv{src_seg_idx}]"
            src_steps = [f"[0:{video.source_index}]trim=start={_fmt_sec(pos)}:end={_fmt_sec(at)}", "setpts=PTS-STARTPTS"]
            src_steps.extend(vnorm_steps)
            parts.append(",".join(src_steps) + vlab)
            sequence_video_labels.append(vlab)

            for aidx, audio in enumerate(source.audios):
                alab = f"[sa{aidx}_{src_seg_idx}]"
                parts.append(
                    f"[0:{audio.source_index}]atrim=start={_fmt_sec(pos)}:end={_fmt_sec(at)},asetpts=PTS-STARTPTS{alab}"
                )
                sequence_audio_labels[aidx].append(alab)

            src_seg_idx += 1

        clip_in = clip_input_indices[idx]
        sil_in = silence_input_indices[idx]

        cv = f"[cv{idx}]"
        clip_steps = [f"[{clip_in}:v:0]null"]

        if fps:
            clip_steps.append(f"fps={fps}")

        # 1) porta la clip alla sua geometria di display reale (square pixel)
        clip_steps.append("scale='trunc(iw*sar/2)*2':ih")
        clip_steps.append("setsar=1")

        # 2) falla entrare nel canvas di display della sorgente
        clip_steps.append(f"scale={disp_width}:{disp_height}:force_original_aspect_ratio=decrease")
        clip_steps.append(f"pad={disp_width}:{disp_height}:(ow-iw)/2:(oh-ih)/2:black")

        # 3) riporta il canvas alla matrice codificata della sorgente
        clip_steps.append(f"scale={width}:{height}")

        if pix_fmt:
            clip_steps.append(f"format={pix_fmt}")

        clip_steps.extend(vnorm_steps)

        parts.append(",".join(clip_steps) + cv)
        sequence_video_labels.append(cv)

        for aidx, audio in enumerate(source.audios):
            sr = int(getattr(audio, "sample_rate", 48000) or 48000)
            layout = _audio_layout_name(getattr(audio, "channels", 2), getattr(audio, "channel_layout", None))
            out_lab = f"[ca{aidx}_{idx}]"

            if aidx == 0 and (not item.mute) and getattr(media, "audios", None):
                clip_audio = media.audios[0]
                clip_a_index = int(clip_audio.source_index)
                gain_db = _clip_gain_db(
                    source_path,
                    source_duration,
                    at,
                    item.clip_path,
                    audio_match_mode,
                )
                a_steps = [f"[{clip_in}:{clip_a_index}]anull"]
                if abs(gain_db) >= 0.25:
                    a_steps.append(f"volume={gain_db:+.2f}dB")
                a_steps.append(f"aresample={sr}")
                a_steps.append(f"aformat=sample_rates={sr}:channel_layouts={layout}")
                a_steps.append(f"atrim=start=0:end={_fmt_sec(dur)}")
                a_steps.append("asetpts=PTS-STARTPTS")
                parts.append(",".join(a_steps) + out_lab)
            else:
                parts.append(
                    f"[{sil_in}:a:0]atrim=start=0:end={_fmt_sec(dur)},asetpts=PTS-STARTPTS{out_lab}"
                )
            sequence_audio_labels[aidx].append(out_lab)

        pos = at

    if pos < source_duration:
        vlab = f"[sv{src_seg_idx}]"
        src_steps = [f"[0:{video.source_index}]trim=start={_fmt_sec(pos)}:end={_fmt_sec(source_duration)}", "setpts=PTS-STARTPTS"]
        src_steps.extend(vnorm_steps)
        parts.append(",".join(src_steps) + vlab)
        sequence_video_labels.append(vlab)

        for aidx, audio in enumerate(source.audios):
            alab = f"[sa{aidx}_{src_seg_idx}]"
            parts.append(
                f"[0:{audio.source_index}]atrim=start={_fmt_sec(pos)}:end={_fmt_sec(source_duration)},asetpts=PTS-STARTPTS{alab}"
            )
            sequence_audio_labels[aidx].append(alab)

    if not sequence_video_labels:
        raise RuntimeError("Nessun segmento video utile generato.")

    parts.append("".join(sequence_video_labels) + f"concat=n={len(sequence_video_labels)}:v=1:a=0[vout]")
    maps += ["-map", "[vout]"]

    for aidx, labels in enumerate(sequence_audio_labels):
        if not labels:
            continue
        out_lab = f"[aout{aidx}]"
        parts.append("".join(labels) + f"concat=n={len(labels)}:v=0:a=1{out_lab}")
        maps += ["-map", out_lab]

    filter_complex = ";".join(parts)

    v_encoder, v_base = choose_video_encoder(video.codec_name)
    cmd: list[str] = [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-y",
        "-loglevel", "error",
        "-nostats",
        "-stats_period", "0.25",
        "-progress", "pipe:1",
        *inputs,
        "-map_metadata", "0",
        "-map_chapters", "-1",
        "-sn",
        "-dn",
        "-filter_complex", filter_complex,
        *maps,
        "-c:v:0", v_encoder,
        *v_base,
        *_video_rate_args(video, v_encoder),
        *_video_metadata_args(video),
    ]

    if fps:
        cmd += ["-r:v:0", fps]
    if getattr(video, "display_aspect_ratio", None):
        cmd += ["-aspect:v:0", str(video.display_aspect_ratio)]

    for aidx, audio in enumerate(source.audios):
        enc = choose_audio_encoder(audio.codec_name)
        cmd += [f"-c:a:{aidx}", enc]
        cmd += _audio_rate_args(audio, aidx, enc)
        cmd += _audio_metadata_args(audio, aidx)

    cmd += [str(Path(output_path).expanduser().resolve())]

    return InsertClipsPlan(
        source_path=Path(source_path).expanduser().resolve(),
        output_path=Path(output_path).expanduser().resolve(),
        items=items_norm,
        total_duration=source_duration + total_insert_duration,
        command=cmd,
    )
