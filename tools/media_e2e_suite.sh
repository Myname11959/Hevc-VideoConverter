#!/usr/bin/env bash
# media_e2e_suite.sh — v7.2
# - synth: usa 5.1(side) per SL/SR
# - on-file: NUOVO → niente "-c:a copy" globale; in ADD setta esplicitamente -c:a:<i> copy
set -euo pipefail

OUT_DIR="/dev/shm/media_e2e"
mkdir -p "$OUT_DIR"

CPU_V_OPTS=(-threads 2 -x265-params pools=2:frame-threads=1)
CPU_A_OPTS=(-filter_threads 1 -threads 1)
AAC_BR="192k"
AC3_BR="448k"
STRICT="${SUITE_STRICT:-0}"
DEBUG="${SUITE_DEBUG:-0}"

have(){ command -v "$1" >/dev/null 2>&1; }
die(){ echo "❌ $*" >&2; exit 1; }
msg(){ echo -e "$*"; }
logfile(){ local bn="$1"; echo "$OUT_DIR/${bn}.log"; }

ffp(){ # file sel key
  local f="$1" sel="$2" key="$3"
  ffprobe -v error -select_streams "$sel" -show_entries "stream=$key" -of csv=p=0 "$f" | head -n1
}

run_ffmpeg(){
  if (( DEBUG )); then
    printf 'FFmpeg cmd: ' >&2; printf '%q ' "$@"; echo >&2
    "$@" 2> >(tee "$(logfile ffmpeg_run)" >&2)
  else
    "$@" >/dev/null 2>&1
  fi
}

af_samsung_stereo(){ echo "pan=stereo|c0=0.95*c0+0.25*c1|c1=0.95*c1+0.25*c0,aformat=channel_layouts=stereo"; }
af_downmix_51_to_20(){ echo "pan=stereo|c0=0.90*c0+0.70*c2+0.20*c4|c1=0.90*c1+0.70*c2+0.20*c5,aformat=channel_layouts=stereo"; }

do_synth(){
  msg "== Generazione input sintetici in $OUT_DIR =="
  local IN_MONO="$OUT_DIR/in_mono.wav"
  local IN_STEREO="$OUT_DIR/in_stereo.wav"
  local IN_51="$OUT_DIR/in_51.wav"

  run_ffmpeg ffmpeg -hide_banner -y \
    -f lavfi -i "sine=frequency=440:duration=3" -ac 1 -ar 44100 "$IN_MONO"

  run_ffmpeg ffmpeg -hide_banner -y \
    -f lavfi -i "sine=frequency=440:duration=3" \
    -f lavfi -i "sine=frequency=880:duration=3" \
    -filter_complex "amerge=inputs=2" -ac 2 -ar 48000 "$IN_STEREO"

  # 5.1(side) → SL/SR presenti
  run_ffmpeg ffmpeg -hide_banner -y \
    -f lavfi -i "sine=frequency=330:duration=3" \
    -f lavfi -i "sine=frequency=660:duration=3" \
    -f lavfi -i "sine=frequency=990:duration=3" \
    -f lavfi -i "sine=frequency=120:duration=3" \
    -f lavfi -i "sine=frequency=550:duration=3" \
    -f lavfi -i "sine=frequency=770:duration=3" \
    -filter_complex "amerge=inputs=6,pan=5.1(side)|FL=c0|FR=c1|FC=c2|LFE=c3|SL=c4|SR=c5" \
    -ac 6 -ar 48000 -f wav -write_channel_mask 0 "$IN_51"

  # A
  msg "\n== [AUDIO] A =="; local OUT_A="$OUT_DIR/out_A.m4a"; local AF_A="aresample=resampler=soxr,dynaudnorm=f=250:g=31:p=0.95:m=50"
  msg "[AUDIO] AF: $AF_A"; msg "[AUDIO] ffmpeg → $OUT_A"
  run_ffmpeg ffmpeg -hide_banner -y -i "$IN_MONO" -af "$AF_A" "${CPU_A_OPTS[@]}" -c:a aac -b:a "$AAC_BR" -ar 44100 "$OUT_A"
  [[ "$(ffp "$OUT_A" a:0 codec_name)" == "aac" && "$(ffp "$OUT_A" a:0 channels)" == "1" && "$(ffp "$OUT_A" a:0 sample_rate)" == "44100" ]] \
    && msg "✅ [AUDIO A] OK — $AF_A | aac | ch=1 | SR=44100" || die "[A] Verifica fallita"

  # B
  msg "\n== [AUDIO] B =="; local OUT_B="$OUT_DIR/out_B.m4a"; local AF_B="aresample=resampler=soxr,aecho=0.85:0.99:60|120|180:0.50|0.35|0.25"
  msg "[AUDIO] AF: $AF_B"; msg "[AUDIO] ffmpeg → $OUT_B"
  run_ffmpeg ffmpeg -hide_banner -y -i "$IN_MONO" -af "$AF_B" "${CPU_A_OPTS[@]}" -c:a aac -b:a "$AAC_BR" -ar 44100 "$OUT_B"
  [[ "$(ffp "$OUT_B" a:0 codec_name)" == "aac" && "$(ffp "$OUT_B" a:0 channels)" == "1" && "$(ffp "$OUT_B" a:0 sample_rate)" == "44100" ]] \
    && msg "✅ [AUDIO B] OK — $AF_B | aac | ch=1 | SR=44100" || die "[B] Verifica fallita"

  # C
  msg "\n== [AUDIO] C =="; local OUT_C="$OUT_DIR/out_C.m4a"; local AF_C="loudnorm=I=-23:TP=-2:LRA=11"
  msg "[AUDIO] AF: $AF_C"; msg "[AUDIO] ffmpeg → $OUT_C"
  run_ffmpeg ffmpeg -hide_banner -y -i "$IN_MONO" -af "$AF_C" "${CPU_A_OPTS[@]}" -c:a aac -b:a "$AAC_BR" -ar 96000 "$OUT_C"
  [[ "$(ffp "$OUT_C" a:0 codec_name)" == "aac" && "$(ffp "$OUT_C" a:0 channels)" == "1" && "$(ffp "$OUT_C" a:0 sample_rate)" == "96000" ]] \
    && msg "✅ [AUDIO C] OK — $AF_C | aac | ch=1 | SR=96000" || die "[C] Verifica fallita"

  # S2
  msg "\n== [AUDIO] S2_SAMSUNG_STEREO =="; local OUT_S2="$OUT_DIR/out_S2_SAMSUNG_STEREO.m4a"; local AF_S2="$(af_samsung_stereo)"
  msg "[AUDIO] SRC: $IN_STEREO"; msg "[AUDIO] AF:  $AF_S2"
  run_ffmpeg ffmpeg -hide_banner -y -i "$IN_STEREO" -af "$AF_S2" "${CPU_A_OPTS[@]}" -c:a aac -b:a "$AAC_BR" -ar 48000 -ac 2 "$OUT_S2"
  [[ "$(ffp "$OUT_S2" a:0 codec_name)" == "aac" && "$(ffp "$OUT_S2" a:0 channels)" == "2" && "$(ffp "$OUT_S2" a:0 sample_rate)" == "48000" ]] \
    && msg "✅ [AUDIO S2_SAMSUNG_STEREO] — aac | ch=2 | SR=48000" || die "[S2] Verifica fallita"

  # S_DOWN
  msg "\n== [AUDIO] S_DOWN_51_TO_20_SAMSUNG =="; local OUT_SD="$OUT_DIR/out_S_DOWN_51_TO_20_SAMSUNG.m4a"; local AF_SD="$(af_downmix_51_to_20)"
  msg "[AUDIO] SRC: $IN_51"; msg "[AUDIO] AF:  $AF_SD"
  run_ffmpeg ffmpeg -hide_banner -y -i "$IN_51" -af "$AF_SD" "${CPU_A_OPTS[@]}" -c:a aac -b:a "$AAC_BR" -ar 48000 -ac 2 "$OUT_SD"
  [[ "$(ffp "$OUT_SD" a:0 codec_name)" == "aac" && "$(ffp "$OUT_SD" a:0 channels)" == "2" && "$(ffp "$OUT_SD" a:0 sample_rate)" == "48000" ]] \
    && msg "✅ [AUDIO S_DOWN_51_TO_20_SAMSUNG] — aac | ch=2 | SR=48000" || die "[S_DOWN] Verifica fallita"

  # S_51
  msg "\n== [AUDIO] S_51_AC3_48K =="; local OUT_S51="$OUT_DIR/out_S_51_AC3_48K.ac3"
  msg "[AUDIO] SRC: $IN_51"; msg "[AUDIO] AF:  anull"
  run_ffmpeg ffmpeg -hide_banner -y -i "$IN_51" -af anull "${CPU_A_OPTS[@]}" -c:a ac3 -b:a "$AC3_BR" -ar 48000 -ac 6 "$OUT_S51"
  msg "✅ [AUDIO S_51_AC3_48K] — ac3 | ch=6 | SR=48000"

  # VIDEO
  local V_IN="$OUT_DIR/in_360p.mkv"
  run_ffmpeg ffmpeg -hide_banner -y -f lavfi -i "testsrc2=size=640x360:rate=25:duration=3" -pix_fmt yuv420p "$V_IN"

  msg "\n== [VIDEO] V1 =="; run_ffmpeg ffmpeg -hide_banner -y -i "$V_IN" -vf "scale=720:576,setsar=45/1" -c:v libx265 -crf 28 -preset medium "${CPU_V_OPTS[@]}" -an "$OUT_DIR/out_V1.mp4"; msg "✅ [VIDEO V1] OK — hevc | 720x576 | SAR 45:1 | DAR 225:4 | FPS 25/1"
  msg "\n== [VIDEO] V2 =="; run_ffmpeg ffmpeg -hide_banner -y -i "$V_IN" -vf "scale=720:576,setsar=15/1" -c:v libx265 -crf 28 -preset medium "${CPU_V_OPTS[@]}" -an "$OUT_DIR/out_V2.mp4"; msg "✅ [VIDEO V2] OK — hevc | 720x576 | SAR 15:1 | DAR 75:4 | FPS 25/1"
  msg "\n== [VIDEO] V3 =="; run_ffmpeg ffmpeg -hide_banner -y -i "$V_IN" -vf "scale=640:360,setsar=1/1" -c:v libx265 -crf 28 -preset medium "${CPU_V_OPTS[@]}" -an "$OUT_DIR/out_V3.mp4"; msg "✅ [VIDEO V3] OK — hevc | 640x360 | SAR 1:1 | DAR 16:9 | FPS 25/1"

  msg "\n✅ SUITE synth COMPLETATA"
  ls -lh "$OUT_DIR"/out_*.m4a "$OUT_DIR"/out_*.ac3 "$OUT_DIR"/out_V*.mp4 | sed 's/^/- /'
}

do_onfile(){
  local VIDEO_IN="" EXT_AUDIO="" PROFILE="" MUX_MODE="replace" LANG_TAG="" OUT_FILE=""
  [[ $# -ge 1 ]] || die "Uso: $0 on-file <video_in> --ext-audio <audio_in> --profile <S2|S_DOWN|S_51> [--mux replace|add] [--lang ita] [--out file]"
  VIDEO_IN="$1"; shift
  while (( "$#" )); do
    case "$1" in
      --ext-audio) EXT_AUDIO="${2:-}"; shift 2;;
      --profile)   PROFILE="${2:-}"; shift 2;;
      --mux)       MUX_MODE="${2:-}"; shift 2;;
      --lang)      LANG_TAG="${2:-}"; shift 2;;
      --out)       OUT_FILE="${2:-}"; shift 2;;
      *) die "Argomento sconosciuto: $1";;
    esac
  done
  [[ -f "$VIDEO_IN" ]] || die "Video non trovato: $VIDEO_IN"
  [[ -n "$EXT_AUDIO" && -f "$EXT_AUDIO" ]] || die "--ext-audio mancante o non valido"
  [[ "$PROFILE" =~ ^(S2|S_DOWN|S_51)$ ]] || die "--profile deve essere S2 | S_DOWN | S_51"
  [[ "$MUX_MODE" =~ ^(replace|add)$ ]] || die "--mux deve essere replace | add"
  have ffmpeg || die "ffmpeg non trovato"; have ffprobe || die "ffprobe non trovato"

  local AIN_CH="$(ffp "$EXT_AUDIO" a:0 channels || echo "")"
  local AIN_SR="$(ffp "$EXT_AUDIO" a:0 sample_rate || echo "")"
  [[ -n "$AIN_CH" && -n "$AIN_SR" ]] || die "Non leggo canali/SR dall'audio esterno"

  (( DEBUG )) && {
    msg "Input video: $VIDEO_IN"
    msg "Input audio: $EXT_AUDIO (ch=$AIN_CH sr=$AIN_SR)"
    msg "Profilo: $PROFILE — Mux: $MUX_MODE — Lingua: ${LANG_TAG:-<none>}"
  }

  local AF="" TARGET_CH="" TARGET_SR="" A0_OPTS=()
  case "$PROFILE" in
    S2)
      AF="$(af_samsung_stereo)"; A0_OPTS=( -c:a:0 aac -b:a:0 "$AAC_BR" -ar:0 48000 -ac:0 2 ); TARGET_CH="2"; TARGET_SR="48000";;
    S_DOWN)
      if (( AIN_CH >= 6 )); then AF="$(af_downmix_51_to_20)"; else
        (( STRICT )) && die "S_DOWN richiede 5.1; trovato ${AIN_CH}ch"
        AF="$(af_samsung_stereo)"
      fi
      A0_OPTS=( -c:a:0 aac -b:a:0 "$AAC_BR" -ar:0 48000 -ac:0 2 ); TARGET_CH="2"; TARGET_SR="48000";;
    S_51)
      if (( AIN_CH == 6 )); then AF="anull"; A0_OPTS=( -c:a:0 ac3 -b:a:0 "$AC3_BR" -ar:0 48000 -ac:0 6 ); TARGET_CH="6"; TARGET_SR="48000"
      else (( STRICT )) && die "S_51 richiede 6 canali; trovato ${AIN_CH}ch"; die "Niente upmix: usa S2 o S_DOWN."
      fi;;
  esac

  if [[ -z "$OUT_FILE" ]]; then
    local bn="$(basename "$VIDEO_IN")"; local tag="${PROFILE}_${MUX_MODE}"
    OUT_FILE="$OUT_DIR/out_ONFILE_${tag}_$(echo "$bn" | sed 's/[[:space:]]\+/_/g')"
    [[ "$PROFILE" == "S_51" ]] && OUT_FILE="${OUT_FILE%.*}.mkv" || OUT_FILE="${OUT_FILE%.*}.mp4"
  fi

  # Mapping
  local MAPS=()
  if [[ "$MUX_MODE" == "replace" ]]; then
    MAPS=( -map 0:v:0 -map 1:a:0 )
  else
    MAPS=( -map 0:v:0 -map 1:a:0 -map 0:a? )
  fi

  # Lingua nuova traccia
  local META=(); [[ -n "$LANG_TAG" ]] && META=( -metadata:s:a:0 language="$LANG_TAG" )

  # Disposition: nuova default, originali non-default
  local DISP=( -disposition:a:0 default )
  local ORIG_A_CNT=0
  if [[ "$MUX_MODE" == "add" ]]; then
    ORIG_A_CNT="$(ffprobe -v error -select_streams a -show_entries stream=index -of csv=p=0 "$VIDEO_IN" | wc -l)"
    for ((i=1; i<=ORIG_A_CNT; i++)); do DISP+=( -disposition:a:$i 0 ); done
  fi

  # Codec per stream (niente -c:a copy globale → niente warning)
  local CODECS=( "${A0_OPTS[@]}" )
  if [[ "$MUX_MODE" == "add" ]]; then
    for ((i=1; i<=ORIG_A_CNT; i++)); do CODECS+=( -c:a:$i copy ); done
  fi

  local MOVFLAGS=(); [[ "$OUT_FILE" =~ \.mp4$ ]] && MOVFLAGS=( -movflags +faststart )

  local CMD=( ffmpeg -hide_banner -y
              -i "$VIDEO_IN" -i "$EXT_AUDIO"
              "${MAPS[@]}"
              -c:v copy
              -filter:a:0 "$AF"
              "${CPU_A_OPTS[@]}"
              "${CODECS[@]}"
              "${META[@]}" "${DISP[@]}"
              "${MOVFLAGS[@]}"
              -shortest "$OUT_FILE" )
  (( DEBUG )) && { printf 'FFmpeg cmd:\n'; printf '%q ' "${CMD[@]}"; echo; }

  msg "== MUX ${PROFILE} (${MUX_MODE}) → $OUT_FILE =="
  "${CMD[@]}"

  local OCODEC="$(ffp "$OUT_FILE" a:0 codec_name || echo "")"
  local OCH="$(ffp "$OUT_FILE" a:0 channels || echo "")"
  local OSR="$(ffp "$OUT_FILE" a:0 sample_rate || echo "")"

  local OK=1
  [[ -n "$TARGET_CH" && "$OCH" != "$TARGET_CH" ]] && { msg "⚠️ canali attesi: $TARGET_CH, trovati: $OCH"; OK=0; }
  [[ -n "$TARGET_SR" && "$OSR" != "$TARGET_SR"   ]] && { msg "⚠️ SR atteso: $TARGET_SR, trovato: $OSR"; OK=0; }
  case "$PROFILE" in
    S2|S_DOWN) [[ "$OCODEC" == "aac" ]] || { msg "⚠️ codec atteso: aac, trovato: $OCODEC"; OK=0; } ;;
    S_51)      [[ "$OCODEC" == "ac3" ]] || { msg "⚠️ codec atteso: ac3, trovato: $OCODEC"; OK=0; } ;;
  esac

  if (( OK )); then msg "✅ OK — ${PROFILE} | codec=${OCODEC} | ch=${OCH} | SR=${OSR} → $(realpath "$OUT_FILE")"
  else (( STRICT )) && die "Verifica fallita in modalità STRICT"; msg "⚠️ Output creato ma verifica non perfetta: $(realpath "$OUT_FILE")"; fi
}

have ffmpeg || die "ffmpeg non trovato"
have ffprobe || die "ffprobe non trovato"

case "${1:-}" in
  synth) shift; do_synth "$@";;
  on-file) shift; do_onfile "$@";;
  -h|--help|"")
    cat <<'USO'
Uso:
  tools/media_e2e_suite.sh synth
  tools/media_e2e_suite.sh on-file <video_in> --ext-audio <audio_in> --profile <S2|S_DOWN|S_51>
                                   [--mux <replace|add>] [--lang <ita|eng|...>] [--out <file_out>]

Env:
  SUITE_STRICT=1  → fallisci su mismatch profili (es. S_51 senza 6ch)
  SUITE_DEBUG=1   → stampa comandi e salva log in /dev/shm/media_e2e

Note:
  - S_51: AC-3 5.1 @48 kHz → default MKV se non specifichi --out.
  - S2/S_DOWN: AAC stereo @48 kHz → default MP4 con +faststart.
USO
    ;;
  *) die "Comando sconosciuto: $1 (usa --help)";;
esac

