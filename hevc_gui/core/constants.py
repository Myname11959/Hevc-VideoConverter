# -*- coding: utf-8 -*-
"""
Costanti e dizionari condivisi dall’interfaccia HEVC-GUI
"""

import os
from pathlib import Path

# ──────────────────────────── Radici progetto / cartelle tmp ─────────────────
# constants.py è in hevc_gui/core/
# .../Hevc_gui/hevc_gui/core/constants.py → risalgo a .../Hevc_gui
_PROJECT_ROOT = Path(__file__).parent.parent.parent  # .../Hevc_gui
PROJECT_ROOT = _PROJECT_ROOT  # alias

ROOT_DIR = PROJECT_ROOT / "hevc_gui"  # modulo interno
TMP_DIR = PROJECT_ROOT / "tmp"  # .../Hevc_gui/tmp
AUDIO_DIR = TMP_DIR / "audio_tracks"
CHAPTERS_DIR = TMP_DIR / "hevc_gui_chapters"
VIDEO_DIR = TMP_DIR / "video_temp"
TEMP_DIR = TMP_DIR  # alias legacy per queue.py

# Se desideri creare le cartelle subito, decommenta:
# for d in (TMP_DIR, AUDIO_DIR, CHAPTERS_DIR, VIDEO_DIR):
#     d.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────── Binari / directory scripts ──────────────────
FFMPEG_BIN = os.getenv("FFMPEG_BIN", "ffmpeg")
FFPROBE_BIN = os.getenv("FFPROBE_BIN", "ffprobe")
MEDIAINFO_BIN = os.getenv("MEDIAINFO_BIN", "mediainfo")

SCRIPTS_DIR = PROJECT_ROOT / "scripts"
# AUDIO_SCRIPT    = str(SCRIPTS_DIR / 'audio_converter_from_AV_files_it.py')
# SUBTITLE_SCRIPT = str(SCRIPTS_DIR / 'subtitle.py')

# ───────────────────────────────────── Video: filtri base ────────────────────
SHARPNESS_LEVELS = {
    "Nessuno": "",
    "Leggero": "unsharp=3:3:0.5",
    "Leggero-Moderato": "unsharp=3:3:0.75:3:3:0.5",
    "Moderato": "unsharp=5:5:1.0",
    "Moderato-Alto": "unsharp=5:5:1.5:5:5:1.0",
    "Alto": "unsharp=7:7:2.0",
    "Alto-Moderato": "unsharp=7:7:2.5:7:7:2.0",
    "Massimo": "unsharp=9:9:3.0:9:9:3.0",
}

SMOOTHNESS_LEVELS = {
    "Nessuno": "",
    "Leggero": "boxblur=1:1",
    "Leggero-Moderato": "boxblur=3:2",
    "Moderato": "boxblur=5:3",
    "Moderato-Alto": "boxblur=7:4",
    "Alto": "boxblur=9:5",
    "Alto-Moderato": "boxblur=10:6",
    "Massimo": "boxblur=14:8",
}

# ───────────────────────────── Video: bitrate / CRF / preset ─────────────────
BITRATE_OPTIONS = [
    "Nessuno",
    "500k",
    "800k",
    "1000k",
    "1200k",
    "2000k",
    "2500k",
    "3000k",
    "4000k",
    "5000k",
]

CRF_OPTIONS = ["Nessuno"] + [str(n) for n in range(0, 52)]

PRESET_OPTIONS = [
    "Nessuno",
    "ultrafast",
    "superfast",
    "veryfast",
    "faster",
    "fast",
    "medium",
    "slow",
    "slower",
    "veryslow",
    "placebo",
]

# ──────────────────────────────── Video: risoluzioni ─────────────────────────
RESOLUTIONS = {
    "Nessuno": "",
    "576p (720x576)": "scale=720:576",
    "720p (1280x720)": "scale=1280:720",
    "1080p (1920x1080)": "scale=1920:1080",
}

# Aspect ratio / SAR-DAR policy
ASPECT_POLICY_DEFAULT = os.getenv("ASPECT_POLICY", "square")  # square|pal16x9|preserve

# Valori SAR per PAL corretti
PAL_SAR_4_3 = "16/15"  # 720x576 → 4:3
PAL_SAR_16_9 = "64/45"  # 720x576 → 16:9 (corretto)

# Risoluzioni/sar “sicure” opzionali
SAFE_RESOLUTIONS = {
    "576p (1024x576) [quadrati]": "scale=1024:576,setsar=1",
    "720 wide (16:9 auto)": "scale=720:-2,setsar=1",
    "576p PAL 16:9 (720x576 anam)": f"scale=720:576,setsar={PAL_SAR_16_9},setdar=16/9",
}

# ─────────────────────────────── Frame rate options ──────────────────────────
FR_MODE = ["Variabile", "Costante"]
FR_CONST_VALUES = ["Nessuno", "23.976", "24", "25", "29.97", "30", "50", "60"]

# ───────────────────────────────────── Audio: opzioni ────────────────────────
AUD_BITRATES = ["Nessuno", "64k", "128k", "192k", "224k", "256k", "320k"]
AUD_GAIN_RANGE = [str(i) for i in range(-15, 16)]
AUD_SAMPLE_RATES = ["Nessuno", "44100", "48000", "96000", "192000"]

AUD_REVERB_LEVELS = [
    "Nessuno",
    "Leggerissimo",
    "Molto Leggero",
    "Leggero",
    "Intermedio",
    "Moderato",
    "Pronunciato",
    "Forte",
]
# === Reverb map (aecho) più evidente ===
# aecho = in_gain : out_gain : delays(ms separati da |) : decays(corrispondenti)
AUD_REVERB_MAP = {
    "Nessuno": None,
    "Leggerissimo": "aecho=0.95:0.95:80:0.20",
    "Molto Leggero": "aecho=0.90:0.97:80|160:0.25|0.15",
    "Leggero": "aecho=0.90:0.98:60|120:0.35|0.20",
    "Intermedio": "aecho=0.85:0.98:60|120|180:0.50|0.35|0.25",
    "Moderato": "aecho=0.80:0.99:60|120|180:0.60|0.40|0.30",
    "Pronunciato": "aecho=0.75:0.99:60|120|180|240:0.65|0.50|0.38|0.28",
    "Forte": "aecho=0.70:1.00:60|120|180|240|300:0.70|0.55|0.40|0.30|0.22",
}

# Valori preimpostati per EQ (dB). "Nessuno" = nessun filtro.
AUD_EQ_DB_CHOICES = ["Nessuno"] + [str(n) for n in range(-18, 19, 1)]

# Preview durata (s): (seconds, label)
AUD_PREVIEW_OPTIONS = [
    (None, "∞"),
    (5, '5"'),
    (10, '10"'),
    (20, '20"'),
    (30, '30"'),
    (60, "1 min."),
    (300, "5 min."),
    (600, "10 min."),
    (900, "15 min."),
    (1200, "20 min."),
    (1800, "30 min."),
]

# ─────────────────────── Preset audio centralizzati (PAN/EQ) ─────────────────
# Downmix 5.1 → 2.0 “dialog-safe”
# NB: nomi canali FFmpeg: FL,FR,FC,LFE,SL,SR
AUD_PAN_PRESETS = {
    # Stereo TV generico: Center robusto, Surround medi, LFE moderato
    "stereo_tv_generic": ("pan=stereo|FL=FL+0.80*FC+0.50*SL+0.25*LFE|FR=FR+0.80*FC+0.50*SR+0.25*LFE"),
    # Samsung HW-R450 (2.1): Center più forte, Surround medi, LFE più basso
    "stereo_samsung_r450": ("pan=stereo|FL=FL+0.90*FC+0.50*SL+0.25*LFE|FR=FR+0.90*FC+0.50*SR+0.25*LFE"),
}

# Dialog Boost: piccolo EQ mirato (non tocca i controlli EQ utente)
# +2 dB a ~2 kHz, Q≈1.2
AUD_DIALOG_BOOST_EQ = "equalizer=f=2000:t=q:w=1.2:g=2"

# Stereo enhancers centralizzati (opzionale)
AUD_STEREO_ENHANCERS = {
    "StereoWiden": "stereowiden=delay=1:feedback=0.5",
    "StereoPan": "pan=stereo|c0=c0+0.3*c1|c1=c1+0.3*c0",
}

# Identificatori profilo audio (per GUI/logic)
PROFILE_SAMSUNG_STEREO_KEY = "samsung_stereo"
PROFILE_SAMSUNG_51_KEY = "samsung_5_1_ac3"

# ───────────────────────────── Estensioni “audio/AV” ─────────────────────────
# includo anche container AV (mkv/mp4/avi) perché l’estrattore li accetta
AUDIO_EXTS = {".ac3", ".aac", ".mp3", ".wav", ".flac", ".m4a", ".mkv", ".mp4", ".avi"}

# ──────────────────────────────── Lingue: nomi estesi ────────────────────────
LANGUAGE_NAMES = {
    "ITA": "Italiano",
    "ENG": "Inglese",
    "FRA": "Francese",
    "SPA": "Spagnolo",
    "GER": "Tedesco",
    "POR": "Portoghese",
    "RUS": "Russo",
    "JPN": "Giapponese",
    "CHN": "Cinese",
    "UNKNOWN": "Lingua sconosciuta",
}

# ──────────────────────── Opzioni container (mux) per FFmpeg ─────────────────
CONTAINER_FFMPEG_OPTS = {
    ".mkv": ["-fflags", "+genpts", "-max_interleave_delta", "0"],
    ".mp4": ["-fflags", "+genpts", "-max_interleave_delta", "0", "-movflags", "+faststart"],
    ".mov": [
        "-fflags",
        "+genpts",
        "-max_interleave_delta",
        "0",
        "-movflags",
        "+faststart",
        "-tag:v",
        "hvc1",
    ],
}

# ────────────────────────────── Info / App / comportamento ───────────────────
ORG_NAME = "LorisPaganiniHomeStudio"
APP_NAME = "HEVC - Video Converter"

# Quante tracce audio convertire in parallelo
# 1 = seriale (consigliato), 2 = semi-parallelo, 99 = “come prima”
MAX_AUDIO_JOBS = 1

# Feature flags
ASPECT_AUTOFIX = True  # autofix aspect quando target 720x576 (v. build_ffmpeg_video_cmd)

# ────────────────────────────── Scope: layout & colori ───────────────────────
CHANNEL_LAYOUTS = {
    "mono": ["M"],
    "stereo": ["L", "R"],
    "5.1": ["L", "R", "C", "LFE", "SL", "SR"],
}
CHANNEL_COLORS = {
    "M": "yellow",
    "L": "yellow",
    "R": "cyan",
    "C": "orange",
    "LFE": "magenta",
    "SL": "green",
    "SR": "pink",
}

# ──────────────────────────── GUI: alias lingua & pattern ────────────────────
AUDIO_LANG_ALIASES = {
    "ita": {"ita", "italiano", "it", "italian"},
    "eng": {"eng", "inglese", "en", "english"},
    "fra": {"fra", "francese", "fr", "french"},
    "spa": {"spa", "spagnolo", "es", "spanish"},
}

# estrae "1" da "Traccia 1 – Italiano – 128k" → poi lo trasformiamo in 0-based
TRACK_TEXT_PATTERN = r"\b(\d+)\b"
