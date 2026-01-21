#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Entry-point leggero per installare i "sinks" i18n Qt (QMessageBox, dialog, ecc).

Scopo:
- NON importare PyQt5 a import-time (evita side effects)
- Chiamare in modo robusto gli installer reali presenti nel progetto
- Non rompere l'avvio se un sink fallisce
"""

from __future__ import annotations

from typing import Optional
import os
import importlib


def install_qt_i18n_sinks(debug: Optional[bool] = None) -> None:
    """
    Installazione best-effort dei sinks.

    main.py fa:
        from hevc_gui.i18n_sinks import install_qt_i18n_sinks
        install_qt_i18n_sinks()
    """
    if debug is None:
        debug = (os.environ.get("HEVC_I18N_DEBUG") or "").strip() not in ("", "0", "false", "False")

    def log(*a):
        if debug:
            print("[i18n_sinks]", *a)

    # Lista moduli sink “canonici” (aggiungine altri se ne nascono)
    modules = (
        "hevc_gui.i18n_sinks_msgbox",
    )

    # Funzioni possibili dentro i moduli sink (proviamo in ordine)
    entrypoints = (
        "install_all_sinks",
        "install_all",
        "install",
        "install_qt_i18n_sinks",
        "install_qmessagebox_i18n",
    )

    for modname in modules:
        try:
            mod = importlib.import_module(modname)
        except Exception as e:
            log("IMPORT FAIL", modname, "->", repr(e))
            continue

        installed = False
        for fn_name in entrypoints:
            fn = getattr(mod, fn_name, None)
            if callable(fn):
                try:
                    fn()
                    log("OK", modname, fn_name)
                    installed = True
                except Exception as e:
                    log("FAIL", modname, fn_name, "->", repr(e))
                break

        if not installed:
            log("WARN", modname, "nessun entrypoint trovato tra:", ", ".join(entrypoints))


__all__ = ["install_qt_i18n_sinks"]
