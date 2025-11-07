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
# Livelli più graduali per sharpening e smoothing.
# unsharp: formati accettati
#   unsharp=lx:ly:la[:cx:cy:ca]  (luma/chroma kernel e amount)
SHARPNESS_LEVELS = {
    "Nessuno": "",
    "Minimo":                 "unsharp=3:3:0.25",
    "Leggerissimo":           "unsharp=3:3:0.35",
    "Leggero":                "unsharp=3:3:0.50",
    "Leggero-Moderato":       "unsharp=3:3:0.75:3:3:0.50",
    "Intermedio":             "unsharp=5:5:0.90:5:5:0.60",
    "Moderato":               "unsharp=5:5:1.00:5:5:0.70",
    "Moderato+":              "unsharp=5:5:1.20:5:5:0.80",
    "Alto-Moderato":          "unsharp=7:7:1.50:7:7:1.00",
    "Alto":                   "unsharp=7:7:2.00:7:7:1.30",
    "Alto+":                  "unsharp=7:7:2.30:7:7:1.60",
    "Massimo-":               "unsharp=9:9:2.70:9:9:2.00",
    "Massimo":                "unsharp=9:9:3.00:9:9:2.20",
}

SMOOTHNESS_LEVELS = {
    "Nessuno": "",
    "Minimo":                 "boxblur=1:1",
    "Molto Leggero":          "boxblur=2:1",
    "Leggero":                "boxblur=3:2",
    "Leggero+":               "boxblur=4:2",
    "Intermedio-":            "boxblur=5:3",
    "Intermedio":             "boxblur=6:3",
    "Intermedio+":            "boxblur=7:4",
    "Moderato-":              "boxblur=8:4",
    "Moderato":               "boxblur=9:5",
    "Moderato+":              "boxblur=10:6",
    "Alto":                   "boxblur=12:7",
    "Alto+":                  "boxblur=14:8",
    "Massimo":                "boxblur=16:9",
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

# Livelli riverbero più fitti (progressione dolce)
AUD_REVERB_LEVELS = [
    "Nessuno",
    "Minimo",
    "Leggerissimo",
    "Molto Leggero",
    "Leggero",
    "Leggero+",
    "Intermedio-",
    "Intermedio",
    "Intermedio+",
    "Moderato-",
    "Moderato",
    "Moderato+",
    "Pronunciato",
    "Forte",
]

# === Reverb map (aecho) con passi più graduali ===
# aecho = in_gain : out_gain : delays(ms separati da |) : decays(corrispondenti)
AUD_REVERB_MAP = {
    "Nessuno":         None,

    # Sfumature leggerissime (single/dual tap)
    "Minimo":          "aecho=0.97:0.97:70:0.15",
    "Leggerissimo":    "aecho=0.95:0.95:80:0.20",
    "Molto Leggero":   "aecho=0.92:0.97:80|160:0.22|0.14",

    # Leggeri (iniziano i triple tap ma con decay bassi)
    "Leggero":         "aecho=0.90:0.98:60|120:0.30|0.18",
    "Leggero+":        "aecho=0.88:0.98:60|120|180:0.38|0.24|0.16",

    # Intermedi (triplo / quadruplo con crescita morbida)
    "Intermedio-":     "aecho=0.87:0.99:60|120|180:0.45|0.32|0.22",
    "Intermedio":      "aecho=0.85:0.99:60|120|180:0.50|0.35|0.25",
    "Intermedio+":     "aecho=0.83:0.99:60|120|180|240:0.55|0.40|0.28|0.20",

    # Moderati (tail più presente ma con headroom su in/out)
    "Moderato-":       "aecho=0.82:0.99:60|120|180|240:0.58|0.42|0.30|0.22",
    "Moderato":        "aecho=0.80:0.99:60|120|180:0.60|0.40|0.30",
    "Moderato+":       "aecho=0.78:0.99:60|120|180|240:0.62|0.45|0.33|0.24",

    # Alti (come i tuoi “Pronunciato/Forte”)
    "Pronunciato":     "aecho=0.75:0.99:60|120|180|240:0.65|0.50|0.38|0.28",
    "Forte":           "aecho=0.70:1.00:60|120|180|240|300:0.70|0.55|0.40|0.30|0.22",
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
# Elenco ufficiale per UI e metadata (ISO 639-2 a 3 lettere, minuscolo)
LANG_CHOICES = [
    ("ita", "Italiano"),
    ("eng", "Inglese"),
    ("fra", "Francese"),
    ("spa", "Spagnolo"),
    ("deu", "Tedesco"),
    ("por", "Portoghese"),
    ("rus", "Russo"),
    ("jpn", "Giapponese"),
    ("zho", "Cinese"),
]

AUDIO_LANG_ALIASES = {
    "ita": {"ita", "italiano", "it", "italian"},
    "eng": {"eng", "inglese", "en", "english"},
    "fra": {"fra", "francese", "fr", "french"},
    "spa": {"spa", "spagnolo", "es", "spanish"},
}
# Alias ampliati (accetta 2 lettere e varianti storiche)
AUDIO_LANG_ALIASES.update(
    {
        "deu": {"deu", "ger", "tedesco", "de", "german"},
        "por": {"por", "pt", "portuguese", "portoghese", "br"},
        "rus": {"rus", "ru", "russian", "russo"},
        "jpn": {"jpn", "ja", "japanese", "giapponese"},
        "zho": {"zho", "chi", "zh", "cinese", "chinese", "zh-cn", "zh-tw"},
    }
)

# estrae "1" da "Traccia 1 – Italiano – 128k" → poi lo trasformiamo in 0-based
TRACK_TEXT_PATTERN = r"\b(\d+)\b"

# === Limiti CPU quando si elabora in GUI ===
CPU_LIMITS_ENABLE = True  # disattiva qui se non li vuoi in GUI
CPU_NICE = 10  # nice(10) → priorità più bassa
CPU_IONICE_CLASS = 2  # 2 = best-effort
CPU_IONICE_N = 5  # priorità 0..7 (più alto = meno prioritario)
CPU_TASKSET = ""  # es. "0-1" per pinnare ai core 0-1; "" = disattivo
CPU_CPULIMIT = 85  # percentuale (cpulimit); 0/None = disattivo

# === Limiti interni ffmpeg (ribaditi anche in GUI)
FFMPEG_VIDEO_THREADS = 2
FFMPEG_X265_POOLS = "2"
FFMPEG_X265_FRAME_THREADS = "1"
FFMPEG_AUDIO_THREADS = 1
FFMPEG_FILTER_THREADS = 1

# URL donazioni (usato da GUI e README)
DONATE_URL = "https://paypal.me/loris1159"
