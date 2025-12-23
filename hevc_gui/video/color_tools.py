#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hevc_gui/video/color_tools.py

Gestione globale delle impostazioni colore:

- brightness (luminosità)  → -0.5 .. +0.5 (0 = neutro)
- contrast (contrasto)     → 0.5 .. 1.5   (1 = neutro)
- saturation (saturazione) → 0.0 .. 2.0   (1 = neutro)
- gamma                    → 0.5 .. 2.0   (1 = neutro)
- enabled                  → bool

Il filtro ffmpeg usato è "eq", es:
    eq=brightness=0.05:contrast=1.10:saturation=1.20:gamma=0.95
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from PyQt5.QtCore import QSettings


@dataclass
class ColorSpec:
    brightness: float = 0.0
    contrast: float = 1.0
    saturation: float = 1.0
    gamma: float = 1.0
    enabled: bool = False


_GROUP = "color"


def _settings() -> QSettings:
    # Usa le stesse impostazioni globali dell'app
    return QSettings()


def load_color_settings() -> ColorSpec:
    s = _settings()
    s.beginGroup(_GROUP)
    try:
        brightness = float(s.value("brightness", 0.0))
    except Exception:
        brightness = 0.0
    try:
        contrast = float(s.value("contrast", 1.0))
    except Exception:
        contrast = 1.0
    try:
        saturation = float(s.value("saturation", 1.0))
    except Exception:
        saturation = 1.0
    try:
        gamma = float(s.value("gamma", 1.0))
    except Exception:
        gamma = 1.0
    enabled = bool(s.value("enabled", False, type=bool))
    s.endGroup()
    return ColorSpec(
        brightness=brightness,
        contrast=contrast,
        saturation=saturation,
        gamma=gamma,
        enabled=enabled,
    )


def save_color_settings(spec: Optional[ColorSpec] = None, **kwargs) -> None:
    """
    Salva le impostazioni colore.

    Compatibile con:
      - save_color_settings(ColorSpec(...))
      - save_color_settings(brightness=..., contrast=..., saturation=..., gamma=..., enabled=...)
    """
    # Se arrivano i singoli campi via kwargs, costruisci un ColorSpec
    if spec is None:
        spec = ColorSpec(
            brightness=float(kwargs.get("brightness", 0.0)),
            contrast=float(kwargs.get("contrast", 1.0)),
            saturation=float(kwargs.get("saturation", 1.0)),
            gamma=float(kwargs.get("gamma", 1.0)),
            enabled=bool(kwargs.get("enabled", False)),
        )

    s = _settings()
    s.beginGroup(_GROUP)
    s.setValue("brightness", spec.brightness)
    s.setValue("contrast", spec.contrast)
    s.setValue("saturation", spec.saturation)
    s.setValue("gamma", spec.gamma)
    s.setValue("enabled", spec.enabled)
    s.endGroup()


def clear_color_settings(disable_only: bool = False) -> None:
    """
    Reset neutro delle impostazioni colore.

    - disable_only=False (default): cancella tutte le chiavi del gruppo "color"
      → al prossimo avvio torni ai valori di default e colore disabilitato.
    - disable_only=True: lascia i valori correnti in QSettings ma forza enabled=False.
    """
    s = _settings()
    s.beginGroup(_GROUP)
    if disable_only:
        # Non tocchiamo gli altri valori, spegniamo solo il flag enabled.
        s.setValue("enabled", False)
    else:
        # Cancella completamente il gruppo.
        s.remove("")
    s.endGroup()


def build_color_eq_filter(consume: bool = False) -> str:
    """
    Ritorna la stringa ffmpeg per il filtro eq, oppure "" se disabilitato
    o se tutti i parametri sono neutri.

    Se consume=True, il flag "enabled" viene automaticamente azzerato
    dopo aver costruito il filtro → comportamento one-shot:
    usi il colore una volta, poi gli encode tornano neutri finché non lo riattivi.
    """
    spec = load_color_settings()
    if not spec.enabled:
        return ""

    eps = 1e-3
    parts = []

    if abs(spec.brightness) > eps:
        parts.append(f"brightness={spec.brightness:.3f}")
    if abs(spec.contrast - 1.0) > eps:
        parts.append(f"contrast={spec.contrast:.3f}")
    if abs(spec.saturation - 1.0) > eps:
        parts.append(f"saturation={spec.saturation:.3f}")
    if abs(spec.gamma - 1.0) > eps:
        parts.append(f"gamma={spec.gamma:.3f}")

    # Anche se non ci sono parti (tutto neutro), se consume=True disarmiamo comunque
    # il flag enabled, così non resta "armato" per gli encode successivi.
    if not parts:
        if consume and spec.enabled:
            spec.enabled = False
            save_color_settings(spec)
        return ""

    eq_str = "eq=" + ":".join(parts)

    if consume and spec.enabled:
        spec.enabled = False
        save_color_settings(spec)

    return eq_str
