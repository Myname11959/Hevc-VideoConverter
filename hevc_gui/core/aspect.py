from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from math import gcd
from . import constants as C


@dataclass
class AspectInfo:
    w: int
    h: int
    sar: str
    dar: str
    pix_fmt: str

    def sar_tuple(self):  # es. "64:45" → (64,45)
        try:
            n, d = self.sar.split(":")
            return int(n), int(d)
        except Exception:
            return (1, 1)


def probe_aspect(path: str) -> AspectInfo:
    cmd = [
        C.FFPROBE_BIN,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,sample_aspect_ratio,display_aspect_ratio,pix_fmt",
        "-of",
        "json",
        path,
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    st = json.loads(out)["streams"][0]
    return AspectInfo(
        w=st.get("width", 0),
        h=st.get("height", 0),
        sar=st.get("sample_aspect_ratio", "1:1"),
        dar=st.get("display_aspect_ratio", ""),
        pix_fmt=st.get("pix_fmt", ""),
    )


def suggest_vf_tail(
    info: AspectInfo,
    policy: str | None = None,
    width_cap: int | None = None,
) -> str | None:
    """
    Restituisce un pezzetto di -vf da aggiungere IN CODA (solo per AR “sicuro”).
    - policy: "square" | "pal16x9" | "preserve"
    - width_cap: se vuoi limitare la larghezza in modo safe (mantiene DAR)
    """
    policy = policy or C.ASPECT_POLICY_DEFAULT
    vf: list[str] = []
    # Limite di larghezza 'safe' (mantiene il DAR della sorgente)
    if width_cap and info.w and info.w > width_cap:
        vf.append(f"scale='{width_cap}':-2")
    # Regole SAR/DAR
    if policy == "square":
        vf.append("setsar=1")
    elif policy == "pal16x9":
        # Se poi usi 720x576 come target, imposta l'anamorfico corretto
        vf.append(f"setsar={C.PAL_SAR_16_9},setdar=16/9")
    # "preserve": non aggiungo nulla
    return ",".join(vf) if vf else None


# ─────────────────────── Logica "smart" per SD (720x576/480) ───────────────────────


@dataclass
class SmartScale:
    """
    Risultato della scelta aspect:
      - scale: filtro scale completo (con opzioni colore/flags)
      - post : eventuali filtri dopo (pad=... oppure setsar/setdar, oppure None)
    """
    scale: str
    post: str | None


def _parse_ratio(r: str, default: tuple[int, int] = (1, 1)) -> tuple[int, int]:
    """Accetta '64:45' o '64/45'."""
    if not r:
        return default
    for sep in (":", "/"):
        if sep in r:
            a, b = r.split(sep, 1)
            try:
                n = int(a.strip())
                d = int(b.strip())
                return (n, d) if d else default
            except Exception:
                return default
    return default


def _extract_scale_flags(base_scale_opts: str) -> str:
    """
    base_scale_opts è una lista di opzioni scale separata da ':'.
    Qui estraiamo SOLO flags=... per usarle nel pre-scale (per evitare doppie conversioni colore).
    """
    if not base_scale_opts:
        return "flags=lanczos"
    parts = base_scale_opts.split(":")
    for p in parts:
        p = p.strip()
        if p.startswith("flags="):
            return p
    return "flags=lanczos"


def _sd_container_sar(target_w: int, target_h: int) -> tuple[int, int, str]:
    """
    Ritorna (sar_num, sar_den, dar_string) per container 16:9 SD.
    - PAL 720x576 -> SAR 64/45
    - NTSC 720x480 -> SAR 32/27
    """
    if (target_w, target_h) == (720, 576):
        # Usa la costante se esiste, altrimenti fallback sicuro
        sar_s = getattr(C, "PAL_SAR_16_9", "64/45")
        n, d = _parse_ratio(sar_s, default=(64, 45))
        return n, d, "16/9"
    if (target_w, target_h) == (720, 480):
        sar_s = getattr(C, "NTSC_SAR_16_9", "32/27")
        n, d = _parse_ratio(sar_s, default=(32, 27))
        return n, d, "16/9"
    return 1, 1, ""


def smart_sd_scale(
    info: AspectInfo,
    target_w: int,
    target_h: int,
    base_scale_opts: str,
    use_anamorphic: bool = True,
    sd_container_16x9: bool = True,
) -> SmartScale:
    """
    Decide in automatico, per target SD (720x576 / 720x480), se usare:

      • schema vecchio (square, con pad nel frame SD):
          scale=WxH:<base_opts>:force_original_aspect_ratio=decrease
          pad=WxH:(W-iw)/2:(H-ih)/2

      • schema anamorfico "esatto" (preserva DAR sorgente con SAR calcolata):
          scale=WxH:<base_opts>
          setsar=.../...,setdar=.../...

      • schema CONSIGLIATO (container 16:9 SD):
          pre-scale in display domain 16:9 (PAL: 1024x576 | NTSC: 854x480)
          pad per letterbox/pillarbox
          scale finale a 720x576/480
          setsar = 64/45 (PAL) o 32/27 (NTSC), setdar=16/9

    Parametri:
        info              : AspectInfo (idealmente dopo eventuale crop).
        target_w,h        : risoluzione frame di destinazione.
        base_scale_opts   : coda della scale SENZA force_original_aspect_ratio.
                            es: "in_color_matrix=bt709:out_color_matrix=bt470bg:flags=lanczos"
        use_anamorphic    : se False, forza sempre schema vecchio (scale+pad nel frame SD).
        sd_container_16x9 : se True e target è SD, usa il container 16:9 (raccomandato).

    Ritorna:
        SmartScale(scale=..., post=...)
    """
    # Schema vecchio di default (fallback)
    scale_old = f"scale={target_w}:{target_h}:{base_scale_opts}:force_original_aspect_ratio=decrease"
    pad_old = f"pad={target_w}:{target_h}:({target_w}-iw)/2:({target_h}-ih)/2"

    # Se non vogliamo anamorphic, o non è SD classica, esci subito
    if (target_w, target_h) not in {(720, 576), (720, 480)} or not use_anamorphic:
        return SmartScale(scale=scale_old, post=pad_old)

    # Modalità container 16:9 (quella che hai validato coi test: niente filiformi, scope preservato)
    if sd_container_16x9:
        sar_n, sar_d, dar_s = _sd_container_sar(target_w, target_h)

        # Display width in square pixels: W * SAR
        disp_w = int(round(target_w * (sar_n / sar_d))) if sar_d else target_w
        if disp_w % 2:
            disp_w += 1  # safety per 4:2:0

        # Pre-scale: SOLO flags=..., per non fare doppie conversioni colore
        flags_only = _extract_scale_flags(base_scale_opts)

        # 1) pre-scale nel dominio display 16:9 (PAL: 1024x576)
        scale_pre = f"scale={disp_w}:{target_h}:{flags_only}:force_original_aspect_ratio=decrease"
        # 2) pad per letterbox/pillarbox (scope -> bande sopra/sotto)
        pad_pre = f"pad={disp_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:color=black"
        # 3) scale finale nel frame SD, con le opzioni base (color matrix, flags, ecc.)
        scale_final = f"scale={target_w}:{target_h}:{base_scale_opts}"
        # 4) marca il file come SD 16:9 anamorphic
        post = f"{pad_pre},{scale_final},setsar={sar_n}/{sar_d}"
        if dar_s:
            post += f",setdar={dar_s}"

        return SmartScale(scale=scale_pre, post=post)

    # ───────────── Modalità "esatta": preserva DAR sorgente (vecchia logica) ─────────────

    # Se mancano dati sensati, tieniti lo schema vecchio
    if not info.w or not info.h:
        return SmartScale(scale=scale_old, post=pad_old)

    sar_n, sar_d = info.sar_tuple()
    if sar_d == 0:
        sar_d = 1

    # DAR sorgente = (w * SAR) / h
    dar_num = info.w * sar_n
    dar_den = info.h * sar_d
    if dar_den == 0:
        return SmartScale(scale=scale_old, post=pad_old)

    # Riduci ai minimi termini
    g = gcd(dar_num, dar_den) or 1
    dar_num //= g
    dar_den //= g
    dar_f = dar_num / dar_den

    # Rapporto frame target (es. 720/576 = 5/4)
    frame_ratio = target_w / target_h

    # Se il DAR sorgente è già molto vicino al frame target (<3%),
    # non ha senso complicarsi la vita: tieni scale+pad.
    diff = abs(dar_f - frame_ratio) / dar_f
    if diff < 0.03:
        return SmartScale(scale=scale_old, post=pad_old)

    # SAR ideale in uscita:
    #   dar_src = (W * sar_out) / H  =>  sar_out = dar_src / (W/H)
    #   in frazione: sar_out = (dar_num/dar_den) * (target_h/target_w)
    sar_num = dar_num * target_h
    sar_den = dar_den * target_w
    if sar_den == 0:
        return SmartScale(scale=scale_old, post=pad_old)

    g2 = gcd(sar_num, sar_den) or 1
    sar_num //= g2
    sar_den //= g2
    sar_f = sar_num / sar_den

    # Se la SAR risultante è “assurda”, torna al vecchio schema
    if not (0.5 <= sar_f <= 4.0):
        return SmartScale(scale=scale_old, post=pad_old)

    # Tutto ok: usiamo scala piena + setsar/setdar, NIENTE pad.
    scale_new = f"scale={target_w}:{target_h}:{base_scale_opts}"
    post_new = f"setsar={sar_num}/{sar_den},setdar={dar_num}/{dar_den}"

    return SmartScale(scale=scale_new, post=post_new)
