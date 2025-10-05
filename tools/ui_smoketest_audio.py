#!/usr/bin/env python3
import sys
import os
import argparse
from PyQt5.QtWidgets import QApplication, QPushButton, QComboBox, QCheckBox


def main():
    ap = argparse.ArgumentParser(description="Smoke test UI String Audio Generator (HEVC-GUI)")
    ap.add_argument("src", help="file audio/video di test (es. tests/assets/mono.wav)")
    ap.add_argument("--sb51", action="store_true", help="attiva profilo Samsung — 5.1 AC-3")
    args = ap.parse_args()

    # importa sia come package sia con import “piatti”
    sys.path[:0] = [os.getcwd(), os.path.join(os.getcwd(), "scripts")]
    from scripts.string_audio_generator import AudioConverter

    _ = QApplication(sys.argv)
    w = AudioConverter(auto=args.src)

    # 1) Titolo/Footer
    title_ok = w.windowTitle() == "String Audio Generator"
    footer = [getattr(w, "btn_cancel").text(), getattr(w, "btn_ok").text()]
    footer_ok = footer == ["Annulla", "OK / Esci"]
    print("TITLE:", w.windowTitle(), "->", "OK" if title_ok else "KO")
    print("FOOTER:", footer, "->", "OK" if footer_ok else "KO")

    # 2) Profilo 5.1 (opzionale)
    prof = getattr(w, "_soundbar_profile", None)
    if args.sb51:
        # trova la checkbox Samsung 5.1
        target = None
        for name in ("chk_samsung_51", "chk_sb_51", "chk_samsung_ac3_51", "chk_soundbar_51"):
            cb = getattr(w, name, None)
            if cb:
                target = cb
                break
        if target is None:
            for cb in w.findChildren(QCheckBox):
                t = (cb.text() or "").lower()
                if "samsung" in t and ("5.1" in t or "ac-3" in t or "ac3" in t):
                    target = cb
                    break
        if target:
            target.setChecked(True)
            rf = getattr(w, "_refresh_filter_availability", None)
            if callable(rf):
                try:
                    rf()
                except Exception:
                    pass
        prof = getattr(w, "_soundbar_profile", None)
    print("PROFILE:", prof, "->", "OK" if (not args.sb51 or prof == "samsung_5_1_ac3") else "KO")

    # 3) Preview motif: bottone “Preview” e combo “Durata” stessa altezza (±2 px)
    btn_prev = None
    for b in w.findChildren(QPushButton):
        if (b.text() or "").strip().lower() == "preview":
            btn_prev = b
            break
    combos = w.findChildren(QComboBox)

    # combo più vicina verticalmente al bottone
    def closest_combo_to(widget, combos):
        if not widget or not combos:
            return None
        wy = widget.mapToGlobal(widget.rect().topLeft()).y()
        best = None
        best_dy = 1e9
        for c in combos:
            cy = c.mapToGlobal(c.rect().topLeft()).y()
            dy = abs(cy - wy)
            if dy < best_dy:
                best, best_dy = c, dy
        return best

    cmb_prev = closest_combo_to(btn_prev, combos)
    motif_ok = False
    if btn_prev and cmb_prev:
        dh = abs(btn_prev.height() - cmb_prev.height())
        motif_ok = dh <= 2
        print(f"PREVIEW: H(btn)={btn_prev.height()} H(cmb)={cmb_prev.height()} -> {'OK' if motif_ok else 'KO'}")
    else:
        print("PREVIEW: controlli non trovati -> KO")

    ok = title_ok and footer_ok and (not args.sb51 or prof == "samsung_5_1_ac3") and motif_ok
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
