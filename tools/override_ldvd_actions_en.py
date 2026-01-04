#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
import xml.etree.ElementTree as ET

TS = Path("hevc_gui/resources/i18n/hevc_en.ts")

MAP = {
    # menu
    "Aggiungi a coda": "Add to queue",
    "Aggiungi file…": "Add file…",
    "Apri cartella…": "Open folder…",
    "Apri sottotitoli .srt": "Open .srt subtitles",
    "Apri in VLC": "Open in VLC",
    "Apri/Refresh DVD": "Open/Refresh DVD",
    "Chiudi cassetto": "Close tray",
    "Eject (apri cassetto)": "Eject (open tray)",
    "Genera SRT": "Generate SRT",
    "Informazioni…": "Info…",
    "Estrai": "Extract",
    "Annulla": "Cancel",
    "Esci": "Exit",
    "Passa a HEVC": "Send to HEVC",

    # footer / status
    "Titolo DVD:": "DVD title:",
    "Titolo film:": "Movie title:",
    "Pronto": "Ready",
    "Completato.": "Done.",
    "Completato": "Done",
    "Errore": "Error",

    # varianti puntini
    "Apri cartella...": "Open folder...",
    "Aggiungi file...": "Add file...",
}

def main() -> int:
    if not TS.exists():
        print("TS non trovato:", TS)
        return 2

    tree = ET.parse(TS)
    root = tree.getroot()

    hits = 0
    for msg in root.findall(".//message"):
        src = (msg.findtext("source") or "").strip()
        if src not in MAP:
            continue
        tr = msg.find("translation")
        if tr is None:
            tr = ET.SubElement(msg, "translation")
        tr.text = MAP[src]
        tr.attrib.pop("type", None)
        hits += 1

    tree.write(TS, encoding="utf-8", xml_declaration=True)
    print("Overrides applied:", hits)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
