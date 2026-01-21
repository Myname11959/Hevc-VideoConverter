#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

TS = Path("hevc_gui/resources/i18n/hevc_en.ts")
JSON_OVR = Path("hevc_gui/resources/i18n/overrides_en.json")

PH_RE = re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}")

def placeholders(s: str) -> set[str]:
    return set(PH_RE.findall(s or ""))

def main() -> int:
    if not TS.exists():
        print("ERROR: TS not found:", TS, file=sys.stderr)
        return 2
    if not JSON_OVR.exists():
        print("ERROR: overrides JSON not found:", JSON_OVR, file=sys.stderr)
        return 3

    overrides = json.loads(JSON_OVR.read_text(encoding="utf-8"))
    if not isinstance(overrides, dict):
        print("ERROR: overrides JSON must be an object {source: translation}", file=sys.stderr)
        return 4

    tree = ET.parse(TS)
    root = tree.getroot()

    # indicizza source -> list(message)
    idx = {}
    for ctx in root.findall("context"):
        for msg in ctx.findall("message"):
            src = (msg.findtext("source") or "").strip()
            if not src:
                continue
            idx.setdefault(src, []).append(msg)

    changed = 0
    missing = []
    bad_placeholders = []

    for src, trtxt in overrides.items():
        msgs = idx.get(src)
        if not msgs:
            missing.append(src)
            continue

        # placeholder safety: devono coincidere
        ps = placeholders(src)
        pt = placeholders(trtxt)
        if ps != pt:
            bad_placeholders.append((src, ps, trtxt, pt))
            continue

        for msg in msgs:
            tr = msg.find("translation")
            if tr is None:
                tr = ET.SubElement(msg, "translation")
            cur = (tr.text or "").strip() if tr.text else ""
            ttype = tr.get("type")

            if cur != trtxt or ttype == "unfinished":
                tr.text = trtxt
                if "type" in tr.attrib:
                    del tr.attrib["type"]
                changed += 1

    # write preserving DOCTYPE
    raw = TS.read_text(encoding="utf-8", errors="replace")
    tmp = TS.with_suffix(".tmpwrite")
    tree.write(tmp, encoding="utf-8", xml_declaration=True)
    out = tmp.read_text(encoding="utf-8", errors="replace")
    if "<!DOCTYPE TS>" in raw and "<!DOCTYPE TS>" not in out:
        out = out.replace("?>\n", "?>\n<!DOCTYPE TS>\n", 1)
        tmp.write_text(out, encoding="utf-8")
    tmp.replace(TS)

    print(f"OK: overrides applied. changed={changed}")

    if bad_placeholders:
        print("\nERROR: placeholder mismatch (NON applicate):", file=sys.stderr)
        for src, ps, trtxt, pt in bad_placeholders:
            print(" - SRC:", src, file=sys.stderr)
            print("   SRC placeholders:", sorted(ps), file=sys.stderr)
            print("   TR :", trtxt, file=sys.stderr)
            print("   TR placeholders:", sorted(pt), file=sys.stderr)
        return 5

    if missing:
        print("\nNOTE: sources not found in TS (non applicate):")
        for m in missing:
            print(" -", m)

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
