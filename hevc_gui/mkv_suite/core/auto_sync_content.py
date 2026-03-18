from __future__ import annotations

import math
import re
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Dict, List, Tuple

from hevc_gui.mkv_suite.core.auto_sync import suggest_track_sync_ms


AUDIO_RATE = 4000
WIN_MS = 25
HOP_MS = 10
SCENE_TH = 0.18
SEARCH_SLACK_MS = 2200
STEP_MS = 10


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def _extract_audio_tracks_full(mkvmerge_bin: str, mkv: Path, audio_ids: List[int], tmp: Path) -> Dict[int, Path]:
    out: Dict[int, Path] = {}
    for tid in audio_ids:
        a_mka = tmp / f"a{tid}.mka"
        rr = _run([
            mkvmerge_bin, "-o", str(a_mka),
            "--no-video", "--no-subtitles", "--no-buttons",
            "--audio-tracks", str(tid),
            str(mkv)
        ])
        if rr.returncode == 0 and a_mka.is_file():
            out[int(tid)] = a_mka
    return out


def _parse_scene_times(ffmpeg_bin: str, mkv: Path, analyze_seconds: int, scene_th: float) -> List[float]:
    cmd = [
        ffmpeg_bin, "-hide_banner", "-nostats", "-v", "info",
        "-t", str(int(analyze_seconds)),
        "-i", str(mkv),
        "-an",
        "-vf", f"select='gt(scene,{scene_th})',showinfo",
        "-f", "null", "-"
    ]
    r = _run(cmd)
    txt = (r.stderr or "") + "\n" + (r.stdout or "")
    out = []
    for m in re.finditer(r"pts_time:([0-9.]+)", txt):
        try:
            out.append(float(m.group(1)))
        except Exception:
            pass

    ded = []
    last = None
    for t in sorted(out):
        if last is None or abs(t - last) >= 0.20:
            ded.append(t)
            last = t
    return ded


def _build_scene_signal(scene_times: List[float], n: int, hop_ms: int) -> List[float]:
    sig = [0.0] * n
    for t in scene_times:
        idx = int(round((t * 1000.0) / hop_ms))
        for off, w in [(-2, 0.20), (-1, 0.60), (0, 1.00), (1, 0.60), (2, 0.20)]:
            j = idx + off
            if 0 <= j < n:
                sig[j] += w
    return sig


def _decode_wav(ffmpeg_bin: str, src: Path, wav_path: Path, analyze_seconds: int, rate: int) -> None:
    cmd = [
        ffmpeg_bin, "-hide_banner", "-nostats", "-v", "error",
        "-t", str(int(analyze_seconds)),
        "-i", str(src),
        "-ac", "1",
        "-ar", str(int(rate)),
        "-c:a", "pcm_s16le",
        str(wav_path),
    ]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0 or not wav_path.is_file():
        raise RuntimeError((r.stderr or r.stdout or "").strip() or "ffmpeg wav decode failed")


def _read_wav_mono_s16(path: Path) -> List[int]:
    with wave.open(str(path), "rb") as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        nframes = wf.getnframes()
        if n_channels != 1 or sampwidth != 2:
            raise RuntimeError("expected mono s16 wav")
        raw = wf.readframes(nframes)

    import array
    a = array.array("h")
    a.frombytes(raw)
    return list(a)


def _build_audio_change_signal(samples: List[int], rate: int, win_ms: int, hop_ms: int) -> List[float]:
    if not samples:
        return []

    win = max(1, int(rate * win_ms / 1000))
    hop = max(1, int(rate * hop_ms / 1000))

    rms = []
    for i in range(0, max(1, len(samples) - win + 1), hop):
        chunk = samples[i:i + win]
        if not chunk:
            break
        acc = 0.0
        for x in chunk:
            fx = float(x) / 32768.0
            acc += fx * fx
        rms.append(math.sqrt(acc / len(chunk)))

    if not rms:
        return []

    sm = []
    for i in range(len(rms)):
        a = max(0, i - 2)
        b = min(len(rms), i + 3)
        sm.append(sum(rms[a:b]) / (b - a))

    flux = [0.0]
    for i in range(1, len(sm)):
        d = sm[i] - sm[i - 1]
        flux.append(max(0.0, d))

    vals = sorted(flux)
    q = vals[int(0.80 * (len(vals) - 1))] if vals else 0.0
    q = max(q, 0.0008)

    sig = [0.0] * len(flux)
    for i, d in enumerate(flux):
        if d >= q:
            for off, w in [(-2, 0.20), (-1, 0.60), (0, 1.00), (1, 0.60), (2, 0.20)]:
                j = i + off
                if 0 <= j < len(sig):
                    sig[j] += w * d

    return sig


def _score_shift(video_sig: List[float], audio_sig: List[float], shift_frames: int) -> float:
    n = min(len(video_sig), len(audio_sig))
    s = 0.0
    for i in range(n):
        j = i - shift_frames
        if 0 <= j < n:
            s += video_sig[i] * audio_sig[j]
    return s


def _top_candidate_shifts(
    video_sig: List[float],
    audio_sig: List[float],
    hint_ms: int,
    slack_ms: int,
    step_ms: int,
    hop_ms: int,
    top_n: int = 20,
) -> List[Tuple[int, float]]:
    out = []
    start = int(hint_ms - slack_ms)
    stop = int(hint_ms + slack_ms)
    for ms in range(start, stop + 1, int(step_ms)):
        sh = int(round(ms / float(hop_ms)))
        sc = _score_shift(video_sig, audio_sig, sh)
        out.append((ms, sc))
    out.sort(key=lambda x: x[1], reverse=True)
    return out[:top_n]


def _choose_best_shift(top: List[Tuple[int, float]], hint_ms: int) -> int:
    if not top:
        return int(hint_ms)

    # punteggio pesato: premia chi è vicino all'hint container
    weighted = []
    for ms, sc in top:
        prior = math.exp(-abs(int(ms) - int(hint_ms)) / 700.0)
        w = float(sc) * prior
        weighted.append((int(ms), float(sc), float(w)))

    weighted.sort(key=lambda x: x[2], reverse=True)
    best_ms, best_raw, best_w = weighted[0]

    # gruppo coerente vicino all'hint: se c'è, usa la mediana del gruppo
    near = [int(ms) for ms, sc, w in weighted if abs(int(ms) - int(hint_ms)) <= 260]
    if len(near) >= 3:
        near = sorted(near)
        n = len(near)
        if n % 2 == 1:
            cand = int(near[n // 2])
        else:
            cand = int(round((near[n // 2 - 1] + near[n // 2]) / 2.0))

        # non accettare cambio di segno rispetto all'hint
        if int(hint_ms) == 0 or cand == 0 or (cand * int(hint_ms) >= 0):
            return int(cand)

    # se il migliore cambia segno vicino all'hint, resta conservativo
    if int(hint_ms) != 0 and (best_ms * int(hint_ms) < 0) and abs(best_ms - int(hint_ms)) < 400:
        return int(hint_ms)

    # se si allontana troppo dall'hint, non fidarti
    if abs(best_ms - int(hint_ms)) > 1600:
        return int(hint_ms)

    # ambiguità: se primo e secondo sono vicini ma entrambi stanno nella stessa zona dell'hint,
    # accetta comunque il primo; torna al fallback solo se il migliore è debole
    if len(weighted) > 1:
        second_ms, second_raw, second_w = weighted[1]
        if best_w <= 0.0:
            return int(hint_ms)

        same_zone = (abs(int(best_ms) - int(hint_ms)) <= 260 and abs(int(second_ms) - int(hint_ms)) <= 260)
        if (second_w > 0 and (best_w / second_w) < 1.08) and not same_zone:
            return int(hint_ms)

    return int(best_ms)


def suggest_content_sync_ms(
    mkvmerge_bin: str,
    ffmpeg_bin: str,
    src_path: str | Path,
    analyze_seconds: int = 600,
    noise_db: float = -40.0,   # tenuti per compatibilità, ma non usati più
    silence_d: float = 0.08,   # tenuti per compatibilità, ma non usati più
    black_d: float = 0.08,     # tenuti per compatibilità, ma non usati più
    black_pic_th: float = 0.98,# tenuti per compatibilità, ma non usati più
    max_abs_ms: int = 5000,    # tenuti per compatibilità, ma non usati più
) -> Dict[int, int]:
    p = Path(src_path)
    if not p.is_file():
        raise FileNotFoundError(str(p))

    analyze_seconds = int(analyze_seconds) if int(analyze_seconds) > 0 else 600
    analyze_seconds = max(300, analyze_seconds)

    base_map = suggest_track_sync_ms(
        mkvmerge_bin=mkvmerge_bin,
        mkv_path=p,
        types=("audio",),
        threshold_ms=0,
    )

    audio_ids = sorted(int(k) for k in base_map.keys())
    if not audio_ids:
        return {}

    scene_times = _parse_scene_times(ffmpeg_bin, p, analyze_seconds, SCENE_TH)
    if not scene_times:
        return dict(base_map)

    n_frames = int((analyze_seconds * 1000) / HOP_MS)
    video_sig = _build_scene_signal(scene_times, n=n_frames, hop_ms=HOP_MS)
    if not any(x > 0 for x in video_sig):
        return dict(base_map)

    with tempfile.TemporaryDirectory(prefix="sync_scene_audio_final_") as td:
        tmp = Path(td)
        audio_files = _extract_audio_tracks_full(mkvmerge_bin, p, audio_ids, tmp)
        if not audio_files:
            return dict(base_map)

        out: Dict[int, int] = {}

        for tid in audio_ids:
            hint_ms = int(base_map.get(int(tid), 0))
            a_file = audio_files.get(int(tid))
            if not a_file:
                out[int(tid)] = hint_ms
                continue

            try:
                wav_path = tmp / f"a{tid}.wav"
                _decode_wav(ffmpeg_bin, a_file, wav_path, analyze_seconds, AUDIO_RATE)
                samples = _read_wav_mono_s16(wav_path)
                audio_sig = _build_audio_change_signal(samples, AUDIO_RATE, WIN_MS, HOP_MS)

                if not audio_sig or not any(x > 0 for x in audio_sig):
                    out[int(tid)] = hint_ms
                    continue

                top = _top_candidate_shifts(
                    video_sig=video_sig,
                    audio_sig=audio_sig,
                    hint_ms=hint_ms,
                    slack_ms=SEARCH_SLACK_MS,
                    step_ms=STEP_MS,
                    hop_ms=HOP_MS,
                    top_n=20,
                )

                out[int(tid)] = _choose_best_shift(top, hint_ms=hint_ms)

            except Exception:
                out[int(tid)] = hint_ms

        return out
