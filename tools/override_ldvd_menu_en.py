#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

TS = Path("hevc_gui/resources/i18n/hevc_en.ts")

MAP = {
    "&Azioni": "&Actions",
    "&Visualizza": "&View",
    "&Aiuto": "&Help",
    # "&File" lo lasciamo com'è, ma lo metto per completezza:
    "&File": "&File",
}

def main() -> int:
    tree = ET.parse(TS)
    root = tree.getroot()
    hits = 0

    for ctx in root.findall("context"):
        for msg in ctx.findall("message"):
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
