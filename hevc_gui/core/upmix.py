# hevc_gui/core/upmix.py
# -*- coding: utf-8 -*-
"""
Upmix 'soft' non invasivi.
- mono_to_stereo_haas: stereo percepito da mono (Haas + micro EQ differenziale)
- mono_to_51_soft: 5.1 gentile da mono (C forte, SL/SR deboli, LFE filtrato)
- stereo_to_51_soft: 5.1 sobrio da stereo (FC da somma, LFE filtrato, SL/SR discreti)
"""


def mono_to_stereo_haas(delay_ms: int = 12) -> str:
    return (
        "asplit=2[L][R];"
        "[L]equalizer=f=3000:t=q:w=1.2:g=0.8,volume=0.98[L1];"
        f"[R]adelay={delay_ms},equalizer=f=180:t=q:w=1.0:g=-0.8,volume=0.98[R1];"
        "[L1][R1]amerge=inputs=2,aformat=channel_layouts=stereo"
    )


def mono_to_51_soft(delay_lr_ms: int = 12, delay_sur_ms: int = 20) -> str:
    return (
        "asplit=6[L][R][C][LFE][SL][SR];"
        f"[R]adelay={delay_lr_ms}[R1];"
        f"[SL]adelay={delay_sur_ms}[SL1];"
        f"[SR]adelay={delay_sur_ms}[SR1];"
        "[LFE]lowpass=f=120,volume=0.80[LFE1];"
        "[L]volume=0.85[L1];"
        "[R1]volume=0.85[R2];"
        "[C]volume=1.00[C1];"
        "[SL1]volume=0.35[SL2];"
        "[SR1]volume=0.35[SR2];"
        "[L1][R2][C1][LFE1][SL2][SR2]join=inputs=6:channel_layout=5.1"
    )


def stereo_to_51_soft() -> str:
    """
    5.1 prudente da stereo (senza ritardi per restare semplici/robusti):
      FL/FR ~0.9, FC = 0.7*(L+R), LFE = 0.6*(L+R) lowpass 120Hz, SL/SR = 0.35*L/R.
    """
    # Ingresso stereo → pan 5.1
    return "pan=5.1|FL=0.90*FL|FR=0.90*FR|FC=0.70*FL+0.70*FR|LFE=0.60*FL+0.60*FR|SL=0.35*FL|SR=0.35*FR"
