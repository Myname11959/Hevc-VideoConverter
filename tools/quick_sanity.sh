#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SUITE="$HERE/media_e2e_suite.sh"
OUT_DIR="/dev/shm/media_e2e"

[[ -x "$SUITE" ]] || chmod +x "$SUITE"

echo "== [QS] 1) synth =="
SUITE_STRICT=1 SUITE_DEBUG=0 "$SUITE" synth

# Sorgente con AUDIO ORIGINALE
echo "== [QS] 2) preparo src_with_a =="
ffmpeg -hide_banner -y \
  -i "$OUT_DIR/out_V3.mp4" \
  -i "$OUT_DIR/in_stereo.wav" \
  -map 0:v:0 -map 1:a:0 -c:v copy -c:a aac -b:a 128k -ar 48000 \
  "$OUT_DIR/src_with_a.mp4" >/dev/null 2>&1

echo "== [QS] 3) on-file — S2 replace =="
SUITE_STRICT=1 SUITE_DEBUG=0 "$SUITE" on-file "$OUT_DIR/out_V3.mp4" --ext-audio "$OUT_DIR/in_stereo.wav" --profile S2 --mux replace --lang ita

echo "== [QS] 4) on-file — S_51 replace =="
SUITE_STRICT=1 SUITE_DEBUG=0 "$SUITE" on-file "$OUT_DIR/out_V3.mp4" --ext-audio "$OUT_DIR/in_51.wav" --profile S_51 --mux replace --lang ita

echo "== [QS] 5) on-file — S_DOWN add (mantiene originale) =="
SUITE_STRICT=1 SUITE_DEBUG=0 "$SUITE" on-file "$OUT_DIR/src_with_a.mp4" --ext-audio "$OUT_DIR/in_51.wav" --profile S_DOWN --mux add --lang ita

echo "== [QS] 6) probe finale =="
ffprobe -v error -select_streams a \
  -show_entries stream=index,codec_name,channels,sample_rate:stream_tags=language:stream_disposition=default \
  -of csv=p=0 "$OUT_DIR/out_ONFILE_S_DOWN_add_src_with_a.mp4" || true

echo "✅ quick_sanity OK"

