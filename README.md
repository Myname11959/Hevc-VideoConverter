![UI Smoketest](https://github.com/Myname11959/Hevc-VideoConverter/actions/workflows/ui-smoketest.yml/badge.svg)


README – IT

HEVC Video Converter è un’app con interfaccia Qt per convertire video in HEVC/x265, offrendo pieno controllo sia sulla catena video sia su quella audio.
Video: preset/CRF o bitrate, mapping stream, filtri comuni (crop/scale/denoise/sharpen), framerate, copia tracce quando serve.
Audio: profili (es. Samsung 5.1 AC-3), denoise→gain, EQ, reverb/stereo/compressione, Dynamic Audio Normalizer + Dialog Boost, mantenimento MONO, evita clipping, preview e downmix stereo.
Modulo dedicato: string_audio_generator non esegue conversioni; genera in modo coerente la stringa di argomenti ffmpeg da passare all’orchestratore.
Extra: gestione tracce/sottotitoli/chapters, anteprime, coda lavori (dove previsto).
Stato: WIP (work in progress).

README – EN

HEVC Video Converter is a Qt-based app to encode videos to HEVC/x265, giving you full control over both the video and audio pipelines.
Video: presets/CRF or bitrate, stream mapping, common filters (crop/scale/denoise/sharpen), frame rate control, copy-through when appropriate.
Audio: profiles (e.g., Samsung 5.1 AC-3), denoise→gain, EQ, reverb/stereo/compression, Dynamic Audio Normalizer + Dialog Boost, keep MONO, clip avoidance, preview, stereo downmix.
Dedicated module: string_audio_generator doesn’t convert; it reliably builds the ffmpeg argument string for audio to feed the orchestrator.
Extras: tracks/subtitles/chapters handling and previews, job queue where applicable.
Status: WIP.
