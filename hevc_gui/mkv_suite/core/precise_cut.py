from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
import json
import shutil
import subprocess


@dataclass(slots=True)
class VideoStreamModel:
    source_index: int
    codec_name: str
    width: int
    height: int
    pix_fmt: str | None = None
    avg_frame_rate: str | None = None
    r_frame_rate: str | None = None
    sample_aspect_ratio: str | None = None
    display_aspect_ratio: str | None = None
    field_order: str | None = None
    bit_rate: int | None = None
    profile: str | None = None
    level: int | None = None
    color_range: str | None = None
    color_space: str | None = None
    color_transfer: str | None = None
    color_primaries: str | None = None
    title: str | None = None
    language: str | None = None
    disposition_default: bool = False
    disposition_forced: bool = False
    tags: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class AudioStreamModel:
    source_index: int
    codec_name: str
    bit_rate: int | None = None
    sample_rate: int | None = None
    channels: int | None = None
    channel_layout: str | None = None
    title: str | None = None
    language: str | None = None
    disposition_default: bool = False
    disposition_forced: bool = False
    tags: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class MediaModel:
    source_path: Path
    format_name: str | None
    duration: float | None
    title: str | None
    encoder: str | None
    video: VideoStreamModel
    audios: list[AudioStreamModel]


@dataclass(slots=True)
class PreciseCutPlan:
    source_path: Path
    output_path: Path
    in_sec: float
    out_sec: float
    segment_duration: float
    operation: str
    media: MediaModel
    command: list[str]


def _require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"Tool non trovato nel PATH: {name}")


def _run_capture(cmd: list[str]) -> str:
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"Comando fallito ({proc.returncode}): {' '.join(cmd)}\n{err}")
    return proc.stdout


def _as_int(value) -> int | None:
    if value in (None, "", "N/A"):
        return None
    try:
        return int(str(value))
    except Exception:
        return None


def _as_float(value) -> float | None:
    if value in (None, "", "N/A"):
        return None
    try:
        return float(str(value))
    except Exception:
        return None


def _as_bool_num(value) -> bool:
    try:
        return bool(int(value))
    except Exception:
        return False


def _clean_tag(value) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _fmt_sec(sec: float) -> str:
    return f"{float(sec):.6f}"


def _hhmmss_to_seconds(value: str) -> float | None:
    s = (value or "").strip()
    if not s:
        return None
    try:
        parts = s.split(":")
        if len(parts) != 3:
            return None
        hh = int(parts[0])
        mm = int(parts[1])
        ss = float(parts[2])
        return hh * 3600.0 + mm * 60.0 + ss
    except Exception:
        return None


def _valid_rate_str(rate: str | None) -> str | None:
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


def _valid_ratio_str(value: str | None) -> str | None:
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


def _ratio_for_filter(value: str | None) -> str | None:
    s = _valid_ratio_str(value)
    if not s:
        return None
    return s.replace(":", "/")


def ffprobe_json(input_path: str | Path) -> dict:
    _require_tool("ffprobe")
    p = str(Path(input_path))
    out = _run_capture([
        "ffprobe",
        "-v", "error",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        p,
    ])
    try:
        return json.loads(out)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"JSON ffprobe non valido per {p}: {exc}") from exc


def _pick_video_stream(streams: list[dict]) -> dict:
    videos = [s for s in streams if s.get("codec_type") == "video"]
    if not videos:
        raise RuntimeError("Nessuno stream video trovato nel file sorgente.")
    for s in videos:
        disp = s.get("disposition") or {}
        if _as_bool_num(disp.get("default", 0)):
            return s
    return videos[0]


def _pick_audio_streams(
    streams: list[dict],
    selected_audio_stream_indices: Iterable[int] | None,
) -> list[dict]:
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    if selected_audio_stream_indices is None:
        return audios
    wanted = {int(x) for x in selected_audio_stream_indices}
    return [s for s in audios if _as_int(s.get("index")) in wanted]


def probe_media_model(
    input_path: str | Path,
    selected_audio_stream_indices: Iterable[int] | None = None,
) -> MediaModel:
    data = ffprobe_json(input_path)
    streams = data.get("streams") or []
    fmt = data.get("format") or {}

    raw_v = _pick_video_stream(streams)
    raw_as = _pick_audio_streams(streams, selected_audio_stream_indices)

    vtags = raw_v.get("tags") or {}
    vdisp = raw_v.get("disposition") or {}
    video = VideoStreamModel(
        source_index=int(raw_v["index"]),
        codec_name=str(raw_v.get("codec_name") or "").lower().strip(),
        width=int(raw_v.get("width") or 0),
        height=int(raw_v.get("height") or 0),
        pix_fmt=_clean_tag(raw_v.get("pix_fmt")),
        avg_frame_rate=_clean_tag(raw_v.get("avg_frame_rate")),
        r_frame_rate=_clean_tag(raw_v.get("r_frame_rate")),
        sample_aspect_ratio=_clean_tag(raw_v.get("sample_aspect_ratio")),
        display_aspect_ratio=_clean_tag(raw_v.get("display_aspect_ratio")),
        field_order=_clean_tag(raw_v.get("field_order")),
        bit_rate=_as_int(raw_v.get("bit_rate")),
        profile=_clean_tag(raw_v.get("profile")),
        level=_as_int(raw_v.get("level")),
        color_range=_clean_tag(raw_v.get("color_range")),
        color_space=_clean_tag(raw_v.get("color_space")),
        color_transfer=_clean_tag(raw_v.get("color_transfer")),
        color_primaries=_clean_tag(raw_v.get("color_primaries")),
        title=_clean_tag(vtags.get("title")),
        language=_clean_tag(vtags.get("language")),
        disposition_default=_as_bool_num(vdisp.get("default", 0)),
        disposition_forced=_as_bool_num(vdisp.get("forced", 0)),
        tags={str(k): str(v) for k, v in vtags.items()},
    )

    audios = []
    for raw_a in raw_as:
        atags = raw_a.get("tags") or {}
        adisp = raw_a.get("disposition") or {}
        audios.append(
            AudioStreamModel(
                source_index=int(raw_a["index"]),
                codec_name=str(raw_a.get("codec_name") or "").lower().strip(),
                bit_rate=_as_int(raw_a.get("bit_rate")),
                sample_rate=_as_int(raw_a.get("sample_rate")),
                channels=_as_int(raw_a.get("channels")),
                channel_layout=_clean_tag(raw_a.get("channel_layout")),
                title=_clean_tag(atags.get("title")),
                language=_clean_tag(atags.get("language")),
                disposition_default=_as_bool_num(adisp.get("default", 0)),
                disposition_forced=_as_bool_num(adisp.get("forced", 0)),
                tags={str(k): str(v) for k, v in atags.items()},
            )
        )

    ftags = fmt.get("tags") or {}
    return MediaModel(
        source_path=Path(input_path),
        format_name=_clean_tag(fmt.get("format_name")),
        duration=_as_float(fmt.get("duration")),
        title=_clean_tag(ftags.get("title")),
        encoder=_clean_tag(ftags.get("encoder")),
        video=video,
        audios=audios,
    )


def choose_video_encoder(src_codec: str) -> tuple[str, list[str]]:
    c = (src_codec or "").lower().strip()
    if c in {"hevc", "h265", "libx265"}:
        return "libx265", ["-preset:v:0", "medium"]
    if c in {"h264", "avc", "libx264"}:
        return "libx264", ["-preset:v:0", "medium"]
    return "libx265", ["-preset:v:0", "medium"]


def choose_audio_encoder(src_codec: str) -> str:
    c = (src_codec or "").lower().strip()
    if c in {"aac", "he-aac", "aac_latm"}:
        return "aac"
    if c == "ac3":
        return "ac3"
    if c == "eac3":
        return "eac3"
    if c == "mp3":
        return "libmp3lame"
    if c == "flac":
        return "flac"
    if c == "opus":
        return "libopus"
    if c == "vorbis":
        return "libvorbis"
    return "aac"


def _video_rate_args(video: VideoStreamModel, encoder: str) -> list[str]:
    if video.bit_rate and video.bit_rate > 0:
        return ["-b:v:0", str(video.bit_rate)]
    if encoder == "libx264":
        return ["-crf:v:0", "18"]
    return ["-crf:v:0", "20"]


def _audio_rate_args(audio: AudioStreamModel, out_idx: int, encoder: str) -> list[str]:
    if audio.bit_rate and audio.bit_rate > 0:
        return [f"-b:a:{out_idx}", str(audio.bit_rate)]
    ch = audio.channels or 2
    if encoder == "aac":
        if ch <= 2:
            return [f"-b:a:{out_idx}", "192k"]
        if ch <= 6:
            return [f"-b:a:{out_idx}", "448k"]
        return [f"-b:a:{out_idx}", "640k"]
    if encoder in {"ac3", "eac3"}:
        if ch <= 2:
            return [f"-b:a:{out_idx}", "192k"]
        if ch <= 6:
            return [f"-b:a:{out_idx}", "640k"]
        return [f"-b:a:{out_idx}", "768k"]
    if encoder == "libmp3lame":
        return [f"-b:a:{out_idx}", "192k"]
    return []


def _normalize_video_profile(encoder: str, profile: str | None) -> str | None:
    p = (profile or "").strip().lower()
    if not p:
        return None

    if encoder == "libx265":
        p = p.replace(" ", "").replace("-", "")
        mapping = {
            "main": "main",
            "main10": "main10",
            "rext": "rext",
        }
        return mapping.get(p)

    if encoder == "libx264":
        p2 = p.replace(" ", "").replace("-", "")
        mapping = {
            "baseline": "baseline",
            "main": "main",
            "high": "high",
            "high10": "high10",
            "high422": "high422",
            "high444": "high444",
            "high444predictive": "high444",
        }
        return mapping.get(p2)

    return None


def _video_profile_args(video: VideoStreamModel, encoder: str) -> list[str]:
    prof = _normalize_video_profile(encoder, video.profile)
    if not prof:
        return []
    return ["-profile:v:0", prof]


def _video_timing_aspect_args(video: VideoStreamModel) -> list[str]:
    args: list[str] = []

    rate = _valid_rate_str(video.avg_frame_rate) or _valid_rate_str(video.r_frame_rate)
    if rate:
        args += ["-r:v:0", rate]

    dar = _valid_ratio_str(video.display_aspect_ratio)
    if dar:
        args += ["-aspect:v:0", dar]

    return args


def _video_metadata_args(video: VideoStreamModel) -> list[str]:
    args = []
    if video.pix_fmt:
        args += ["-pix_fmt:v:0", video.pix_fmt]
    if video.color_range:
        args += ["-color_range:v:0", video.color_range]
    if video.color_space:
        args += ["-colorspace:v:0", video.color_space]
    if video.color_transfer:
        args += ["-color_trc:v:0", video.color_transfer]
    if video.color_primaries:
        args += ["-color_primaries:v:0", video.color_primaries]
    if video.title:
        args += ["-metadata:s:v:0", f"title={video.title}"]
    if video.language:
        args += ["-metadata:s:v:0", f"language={video.language}"]
    return args


def _audio_metadata_args(audio: AudioStreamModel, out_idx: int) -> list[str]:
    args = []
    if audio.sample_rate:
        args += [f"-ar:a:{out_idx}", str(audio.sample_rate)]
    if audio.channels:
        args += [f"-ac:a:{out_idx}", str(audio.channels)]
    if audio.language:
        args += [f"-metadata:s:a:{out_idx}", f"language={audio.language}"]
    if audio.title:
        args += [f"-metadata:s:a:{out_idx}", f"title={audio.title}"]

    disp = []
    if audio.disposition_default:
        disp.append("default")
    if audio.disposition_forced:
        disp.append("forced")
    args += [f"-disposition:a:{out_idx}", "+".join(disp) if disp else "0"]
    return args


def _video_filter_tail(video: VideoStreamModel) -> str:
    parts: list[str] = []
    sar = _ratio_for_filter(video.sample_aspect_ratio)
    dar = _ratio_for_filter(video.display_aspect_ratio)

    if sar:
        parts.append(f"setsar={sar}")
    elif dar:
        parts.append(f"setdar={dar}")

    return ("," + ",".join(parts)) if parts else ""


def normalize_cut_ranges(
    cut_ranges: Iterable[tuple[float, float]],
    duration: float | None = None,
    epsilon: float = 0.001,
) -> list[tuple[float, float]]:
    cleaned: list[tuple[float, float]] = []

    for pair in cut_ranges:
        if pair is None:
            continue
        try:
            start = float(pair[0])
            end = float(pair[1])
        except Exception:
            raise RuntimeError(f"Intervallo non valido: {pair!r}")

        if duration is not None and duration > 0:
            if start < 0.0:
                start = 0.0
            if end > duration:
                end = duration

        if end <= start + epsilon:
            continue

        cleaned.append((start, end))

    cleaned.sort(key=lambda x: (x[0], x[1]))

    merged: list[list[float]] = []
    for start, end in cleaned:
        if not merged:
            merged.append([start, end])
            continue

        last = merged[-1]
        if start <= last[1] + epsilon:
            if end > last[1]:
                last[1] = end
        else:
            merged.append([start, end])

    return [(a, b) for a, b in merged]


def _compute_keep_ranges(
    duration: float,
    cut_ranges: Iterable[tuple[float, float]],
) -> list[tuple[float, float]]:
    cuts = normalize_cut_ranges(cut_ranges, duration=duration)
    keep: list[tuple[float, float]] = []

    pos = 0.0
    for start, end in cuts:
        if start > pos:
            keep.append((pos, start))
        pos = max(pos, end)

    if pos < duration:
        keep.append((pos, duration))

    return [(a, b) for a, b in keep if b > a]


def _build_filter_from_keep_ranges(
    media: MediaModel,
    keep_ranges: list[tuple[float, float]],
) -> tuple[str, list[str], float]:
    if not keep_ranges:
        raise RuntimeError("Con questi tagli non rimane nulla da esportare.")

    parts: list[str] = []
    maps: list[str] = []
    total_duration = sum((b - a) for a, b in keep_ranges)
    v = media.video
    vtail = _video_filter_tail(v)

    if len(keep_ranges) == 1:
        s, e = keep_ranges[0]
        parts.append(
            f"[0:{v.source_index}]trim=start={_fmt_sec(s)}:end={_fmt_sec(e)},setpts=PTS-STARTPTS{vtail}[v0]"
        )
        maps += ["-map", "[v0]"]

        for out_a_idx, a in enumerate(media.audios):
            lab = f"[a{out_a_idx}]"
            parts.append(
                f"[0:{a.source_index}]atrim=start={_fmt_sec(s)}:end={_fmt_sec(e)},asetpts=PTS-STARTPTS{lab}"
            )
            maps += ["-map", lab]

        return ";".join(parts), maps, total_duration

    # video
    v_inputs = []
    for idx, (s, e) in enumerate(keep_ranges):
        lab = f"[v{idx}]"
        parts.append(
            f"[0:{v.source_index}]trim=start={_fmt_sec(s)}:end={_fmt_sec(e)},setpts=PTS-STARTPTS{lab}"
        )
        v_inputs.append(lab)

    if vtail:
        concat_tail = vtail[1:] if vtail.startswith(",") else vtail
        parts.append("".join(v_inputs) + f"concat=n={len(keep_ranges)}:v=1:a=0[vcat]")
        parts.append(f"[vcat]{concat_tail}[v0]")
    else:
        parts.append("".join(v_inputs) + f"concat=n={len(keep_ranges)}:v=1:a=0[v0]")
    maps += ["-map", "[v0]"]

    # audio
    for out_a_idx, a in enumerate(media.audios):
        a_inputs = []
        for idx, (s, e) in enumerate(keep_ranges):
            lab = f"[a{out_a_idx}_{idx}]"
            parts.append(
                f"[0:{a.source_index}]atrim=start={_fmt_sec(s)}:end={_fmt_sec(e)},asetpts=PTS-STARTPTS{lab}"
            )
            a_inputs.append(lab)

        out_lab = f"[a{out_a_idx}]"
        parts.append("".join(a_inputs) + f"concat=n={len(keep_ranges)}:v=0:a=1{out_lab}")
        maps += ["-map", out_lab]

    return ";".join(parts), maps, total_duration


def build_precise_filter_complex(
    media: MediaModel,
    in_sec: float,
    out_sec: float,
    operation: str = "keep",
) -> tuple[str, list[str], float]:
    if out_sec <= in_sec:
        raise ValueError("OUT deve essere maggiore di IN.")

    start = float(in_sec)
    end = float(out_sec)
    dur = float(media.duration or 0.0)
    if dur <= 0:
        raise RuntimeError("Durata sorgente non disponibile per il taglio preciso.")

    op = (operation or "keep").strip().lower()

    if op == "keep":
        return _build_filter_from_keep_ranges(media, [(start, end)])

    keep_ranges = _compute_keep_ranges(dur, [(start, end)])
    return _build_filter_from_keep_ranges(media, keep_ranges)


def build_precise_multi_filter_complex(
    media: MediaModel,
    cut_ranges: Iterable[tuple[float, float]],
) -> tuple[str, list[str], float]:
    dur = float(media.duration or 0.0)
    if dur <= 0:
        raise RuntimeError("Durata sorgente non disponibile per il taglio preciso.")

    keep_ranges = _compute_keep_ranges(dur, cut_ranges)
    return _build_filter_from_keep_ranges(media, keep_ranges)


def build_precise_cut_command(
    media: MediaModel,
    output_path: str | Path,
    in_sec: float,
    out_sec: float,
    operation: str = "keep",
) -> tuple[list[str], float]:
    filter_complex, maps, progress_duration = build_precise_filter_complex(
        media=media,
        in_sec=in_sec,
        out_sec=out_sec,
        operation=operation,
    )

    v_encoder, v_base_args = choose_video_encoder(media.video.codec_name)

    cmd: list[str] = [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-y",
        "-loglevel", "error",
        "-nostats",
        "-stats_period", "0.25",
        "-progress", "pipe:1",
        "-i", str(media.source_path),
        "-map_metadata", "0",
        "-map_chapters", "-1",
        "-sn",
        "-dn",
        "-filter_complex", filter_complex,
        *maps,
        "-c:v:0", v_encoder,
        *v_base_args,
        *_video_rate_args(media.video, v_encoder),
        *_video_profile_args(media.video, v_encoder),
        *_video_timing_aspect_args(media.video),
        *_video_metadata_args(media.video),
    ]

    for out_a_idx, a in enumerate(media.audios):
        enc = choose_audio_encoder(a.codec_name)
        cmd += [f"-c:a:{out_a_idx}", enc]
        cmd += _audio_rate_args(a, out_a_idx, enc)
        cmd += _audio_metadata_args(a, out_a_idx)

    cmd += [str(Path(output_path))]
    return cmd, progress_duration


def build_precise_multi_cut_command(
    media: MediaModel,
    output_path: str | Path,
    cut_ranges: Iterable[tuple[float, float]],
) -> tuple[list[str], float]:
    filter_complex, maps, progress_duration = build_precise_multi_filter_complex(
        media=media,
        cut_ranges=cut_ranges,
    )

    v_encoder, v_base_args = choose_video_encoder(media.video.codec_name)

    cmd: list[str] = [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-y",
        "-loglevel", "error",
        "-nostats",
        "-stats_period", "0.25",
        "-progress", "pipe:1",
        "-i", str(media.source_path),
        "-map_metadata", "0",
        "-map_chapters", "-1",
        "-sn",
        "-dn",
        "-filter_complex", filter_complex,
        *maps,
        "-c:v:0", v_encoder,
        *v_base_args,
        *_video_rate_args(media.video, v_encoder),
        *_video_profile_args(media.video, v_encoder),
        *_video_timing_aspect_args(media.video),
        *_video_metadata_args(media.video),
    ]

    for out_a_idx, a in enumerate(media.audios):
        enc = choose_audio_encoder(a.codec_name)
        cmd += [f"-c:a:{out_a_idx}", enc]
        cmd += _audio_rate_args(a, out_a_idx, enc)
        cmd += _audio_metadata_args(a, out_a_idx)

    cmd += [str(Path(output_path))]
    return cmd, progress_duration


def build_precise_cut_plan(
    input_path: str | Path,
    output_path: str | Path,
    in_sec: float,
    out_sec: float,
    selected_audio_stream_indices: Iterable[int] | None = None,
    operation: str = "keep",
) -> PreciseCutPlan:
    media = probe_media_model(
        input_path=input_path,
        selected_audio_stream_indices=selected_audio_stream_indices,
    )
    cmd, segment_duration = build_precise_cut_command(
        media=media,
        output_path=output_path,
        in_sec=in_sec,
        out_sec=out_sec,
        operation=operation,
    )
    return PreciseCutPlan(
        source_path=Path(input_path),
        output_path=Path(output_path),
        in_sec=float(in_sec),
        out_sec=float(out_sec),
        segment_duration=float(segment_duration),
        operation=operation,
        media=media,
        command=cmd,
    )


def build_precise_multi_cut_plan(
    input_path: str | Path,
    output_path: str | Path,
    cut_ranges: Iterable[tuple[float, float]],
    selected_audio_stream_indices: Iterable[int] | None = None,
) -> PreciseCutPlan:
    media = probe_media_model(
        input_path=input_path,
        selected_audio_stream_indices=selected_audio_stream_indices,
    )
    norm = normalize_cut_ranges(cut_ranges, duration=float(media.duration or 0.0))
    if not norm:
        raise RuntimeError("Nessun taglio valido presente nell'elenco.")

    cmd, segment_duration = build_precise_multi_cut_command(
        media=media,
        output_path=output_path,
        cut_ranges=norm,
    )

    first_in = norm[0][0]
    last_out = norm[-1][1]

    return PreciseCutPlan(
        source_path=Path(input_path),
        output_path=Path(output_path),
        in_sec=float(first_in),
        out_sec=float(last_out),
        segment_duration=float(segment_duration),
        operation="multi_remove",
        media=media,
        command=cmd,
    )


def progress_percent_from_kv(info: dict[str, str], total_duration: float) -> float | None:
    if total_duration <= 0:
        return None

    sec = None
    if "out_time" in info:
        sec = _hhmmss_to_seconds(info["out_time"])
    if sec is None and "out_time_ms" in info:
        try:
            sec = float(info["out_time_ms"]) / 1_000_000.0
        except Exception:
            sec = None
    if sec is None and "out_time_us" in info:
        try:
            sec = float(info["out_time_us"]) / 1_000_000.0
        except Exception:
            sec = None
    if sec is None:
        return None

    pct = (sec / total_duration) * 100.0
    if pct < 0:
        pct = 0.0
    if pct > 100:
        pct = 100.0
    return pct


def parse_progress_line(line: str, state: dict[str, str]) -> tuple[bool, dict[str, str]]:
    s = (line or "").strip()
    if not s or "=" not in s:
        return False, state
    k, v = s.split("=", 1)
    state[k.strip()] = v.strip()
    if k.strip() == "progress":
        return True, state
    return False, state


__all__ = [
    "VideoStreamModel",
    "AudioStreamModel",
    "MediaModel",
    "PreciseCutPlan",
    "ffprobe_json",
    "probe_media_model",
    "choose_video_encoder",
    "choose_audio_encoder",
    "normalize_cut_ranges",
    "build_precise_filter_complex",
    "build_precise_multi_filter_complex",
    "build_precise_cut_command",
    "build_precise_multi_cut_command",
    "build_precise_cut_plan",
    "build_precise_multi_cut_plan",
    "parse_progress_line",
    "progress_percent_from_kv",
]
