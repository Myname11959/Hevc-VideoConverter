# hevc_gui/core/aspect.py
from __future__ import annotations
import json
import subprocess
from dataclasses import dataclass
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


def suggest_vf_tail(info: AspectInfo, policy: str | None = None, width_cap: int | None = None) -> str | None:
    """
    Restituisce un pezzetto di -vf da aggiungere IN CODA (solo per AR “sicuro”).
    - policy: "square" | "pal16x9" | "preserve"
    - width_cap: se vuoi limitare la larghezza in modo safe (mantiene DAR)
    """
    policy = policy or C.ASPECT_POLICY_DEFAULT
    vf = []
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
