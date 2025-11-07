#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Inspector interno per catena audio (simula scelte GUI).
Stampa un JSON racchiuso tra:
  ### AUDIO_CMDS_JSON_BEGIN ###
  [ { "cmd": [...], "cmd_line": "..." } ]
  ### AUDIO_CMDS_JSON_END ###

Opzioni:
  --input FILE               (obbligatorio)
  --map-index N              (opz.)
  --reverb Nessuno|Intermedio
  --external-af STRING
  --profile samsung_stereo | samsung_51 | none
"""
import argparse, json, shlex

def build_af(args):
    # Base resampler
    base = "aresample=resampler=soxr"

    if args.external_af:
        return args.external_af

    # Profili Samsung
    if args.profile == "samsung_stereo":
        # Downmix 5.1 -> 2.0 con crossfeed leggero (FC/SL/SR/LFE nel L/R)
        # Mappa canali: FL=c0, FR=c1, FC=c2, LFE=c3, SL=c4, SR=c5
        pan = ("pan=stereo"
               "|FL=0.95*FL+0.06*FC+0.04*SL+0.02*LFE"
               "|FR=0.95*FR+0.06*FC+0.04*SR+0.02*LFE")
        return f"{base},{pan}"

    if args.profile == "samsung_51":
        # Garantisce layout 5.1 + SR 48000
        # aresample: ocl=5.1 (out channel layout), osr=48000
        return "aresample=resampler=soxr:ocl=5.1:osr=48000"

    # Reverb/default
    if args.reverb and args.reverb.lower() != "nessuno":
        # Preset “Intermedio”
        return f"{base},aecho=0.85:0.99:60|120|180:0.50|0.35|0.25"
    else:
        # Default: dynaudnorm
        return f"{base},dynaudnorm=f=250:g=31:p=0.95:m=50"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--map-index", default="0")
    ap.add_argument("--reverb", default="Nessuno")
    ap.add_argument("--external-af", dest="external_af", default=None)
    ap.add_argument("--profile", choices=["samsung_stereo","samsung_51","none"], default="none")
    args = ap.parse_args()

    af = build_af(args)

    # Codec/format in base al profilo
    if args.profile == "samsung_51":
        codec = "ac3"; fmt = "ac3"; extra = []
        out_file = "/dev/shm/hevc_gui/sessions/af_inspect/out.ac3"
        # Nota: -ar/-ac NON inclusi qui; li forza la suite quando esegue realmente ffmpeg
    else:
        codec = "aac"; fmt = "ipod"; extra = ["-movflags", "+faststart"]
        out_file = "/dev/shm/hevc_gui/sessions/af_inspect/out.m4a"

    cmd = [
        "ffmpeg", "-y", "-nostdin",
        "-i", args.input,
        "-vn",
    ]
    if af:
        cmd += ["-af", af]
    cmd += ["-c:a", codec, "-f", fmt] + extra + ["-filter_threads", "1", "-threads", "1", out_file]

    print("### AUDIO_CMDS_JSON_BEGIN ###")
    print(json.dumps([{"cmd": cmd, "cmd_line": " ".join(shlex.quote(x) for x in cmd)}]))
    print("### AUDIO_CMDS_JSON_END ###")

if __name__ == "__main__":
    main()
