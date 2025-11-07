HEVC – Video Converter

[UI Smoketest badge]
https://github.com/Myname11959/Hevc-VideoConverter/actions/workflows/ui-smoketest.yml/badge.svg

[Ruff badge]
https://github.com/Myname11959/Hevc-VideoConverter/actions/workflows/ruff.yml/badge.svg

[Donate]
https://paypal.me/loris1159

Languages / Lingue: English — Italian

──────────────────────────────────────────────────────────────────────────────
TL;DR / Quick copy-paste
──────────────────────────────────────────────────────────────────────────────

Linux Mint / Ubuntu
  sudo apt update
  sudo apt install -y \
    python3 python3-pyqt5 python3-pyqt5.qtmultimedia python3-pyqtgraph \
    python3-numpy python3-psutil python3-chardet ffmpeg
  git clone https://github.com/Myname11959/Hevc-VideoConverter.git
  cd Hevc-VideoConverter
  python3 main.py

macOS 10.15+ (Intel/Apple Silicon)
  # Requires Homebrew
  brew install python@3.11 ffmpeg
  python3 -m pip install -U pip setuptools wheel
  python3 -m pip install PyQt5 pyqtgraph numpy psutil chardet
  git clone https://github.com/Myname11959/Hevc-VideoConverter.git
  cd Hevc-VideoConverter
  python3 main.py

macOS High Sierra 10.13 (Intel)
  # Suggest Python 3.8/3.9. Wheels may be older; if build fails, try another version.
  /usr/bin/python3 -m pip install -U pip setuptools wheel
  /usr/bin/python3 -m pip install "PyQt5<5.16" pyqtgraph numpy psutil chardet
  git clone https://github.com/Myname11959/Hevc-VideoConverter.git
  cd Hevc-VideoConverter
  /usr/bin/python3 main.py

Windows 10/11
  # Install Python 3.10/3.11 (check “Add to PATH”)
  py -m pip install --upgrade pip
  py -m pip install PyQt5 pyqtgraph numpy psutil chardet
  # Download ffmpeg ZIP, extract, add ...\ffmpeg\bin to PATH
  git clone https://github.com/Myname11959/Hevc-VideoConverter.git
  cd Hevc-VideoConverter
  py main.py

──────────────────────────────────────────────────────────────────────────────
README — EN
──────────────────────────────────────────────────────────────────────────────

HEVC Video Converter is a Qt application to convert videos to HEVC/x265, with fine-grained control over video and audio. Primary target: Linux. It outputs clear, reproducible ffmpeg command lines.

Highlights
• Video: CRF/preset or constant bitrate; stream mapping; copy-pass where safe; crop/scale/denoise/sharpen; CFR/VFR; prefers temp on /dev/shm (automatic disk fallback).
• Audio: ready profiles (Samsung 5.1 AC-3 48 kHz, Samsung Stereo, 5.1→2.0 “Samsung”); effect chain = denoise → gain → EQ → reverb/stereo/compressor; Dynamic Audio Normalizer + Dialog Boost; options Keep MONO / Avoid clipping / Stereo downmix; Preview mirrors the GUI.
• String builder: scripts/string_audio_generator.py does not convert; it builds the ffmpeg argument string for the GUI/queue.

Supported OS
• Linux Mint 21.3 / Ubuntu 22.04+ (primary)
• macOS High Sierra 10.13 (Intel) via older compatible wheels
• macOS 10.15+ (Intel/Apple Silicon) via Homebrew
• Windows 10/11 (Python + ffmpeg in PATH)

Install & Run — Linux (Mint/Ubuntu)
  sudo apt update
  sudo apt install -y \
    python3 python3-pyqt5 python3-pyqt5.qtmultimedia python3-pyqtgraph \
    python3-numpy python3-psutil python3-chardet ffmpeg
  git clone https://github.com/Myname11959/Hevc-VideoConverter.git
  cd Hevc-VideoConverter
  python3 main.py
  # or:
  python3 -m hevc_gui.gui.main_window

Install & Run — macOS High Sierra (Intel)
  /usr/bin/python3 -m pip install -U pip setuptools wheel
  /usr/bin/python3 -m pip install "PyQt5<5.16" pyqtgraph numpy psutil chardet
  # Install ffmpeg (e.g. static binary) and ensure it’s in PATH
  git clone https://github.com/Myname11959/Hevc-VideoConverter.git
  cd Hevc-VideoConverter
  /usr/bin/python3 main.py
  Notes: HS works best with Python 3.8/3.9. If pip lacks wheels, it may try to build from source.

Install & Run — macOS 10.15+ (Intel/Apple Silicon)
  brew install python@3.11 ffmpeg
  python3 -m pip install -U pip setuptools wheel
  python3 -m pip install PyQt5 pyqtgraph numpy psutil chardet
  git clone https://github.com/Myname11959/Hevc-VideoConverter.git
  cd Hevc-VideoConverter
  python3 main.py

Install & Run — Windows 10/11
  py -m pip install --upgrade pip
  py -m pip install PyQt5 pyqtgraph numpy psutil chardet
  # Get ffmpeg and add its bin folder to PATH
  git clone https://github.com/Myname11959/Hevc-VideoConverter.git
  cd Hevc-VideoConverter
  py main.py

Build a .deb (Ubuntu/Mint) — Option A: read dependencies then build
  python3 tools/scan_deps.py
  # (If you have a pack script) tools/make_deb.sh

Build a .deb — Option B: manual skeleton
  rm -rf build/deb && mkdir -p build/deb/DEBIAN build/deb/opt/hevc_gui
  rsync -a --exclude 'build' --exclude '.git' ./ build/deb/opt/hevc_gui/
  # control file:
  cat > build/deb/DEBIAN/control <<'EOF'
  Package: hevc-video-converter
  Version: 2.0.0
  Section: utils
  Priority: optional
  Architecture: all
  Depends: python3, python3-pyqt5, python3-pyqt5.qtmultimedia, python3-pyqtgraph, python3-numpy, python3-psutil, python3-chardet, ffmpeg
  Maintainer: Loris <loris.paganini@gmail.com>
  Description: HEVC Video Converter (Qt/ffmpeg)
   Qt app that builds reproducible ffmpeg commands for HEVC/x265.
  EOF
  dpkg-deb --build build/deb .
  # → ./hevc-video-converter_2.0.0_all.deb

Troubleshooting
• “ffmpeg not found” → install ffmpeg and ensure it’s in PATH.
• “No module named PyQt5.QtMultimedia” → install python3-pyqt5.qtmultimedia (Debian/Ubuntu) or add Qt multimedia plugins on other OSes.
• Qt “xcb” error (Linux) → install missing X11 libs (e.g. libxcb-xinerama0), or run under X11.
• Permissions → chmod +x tools/*.sh

Donations
If you find this project useful, you can support it:
https://paypal.me/loris1159

License
Released under CC BY-NC 4.0 (Attribution-NonCommercial). See LICENSE.

──────────────────────────────────────────────────────────────────────────────
README — IT
──────────────────────────────────────────────────────────────────────────────

HEVC Video Converter è un’app Qt per convertire in HEVC/x265, con controllo fine su video e audio. Target principale: Linux. Produce comandi ffmpeg chiari e ripetibili.

Punti chiave
• Video: CRF/preset o bitrate costante; stream mapping; copy-pass quando sicuro; crop/scale/denoise/sharpen; CFR/VFR; temporanei su /dev/shm (fallback automatico su disco).
• Audio: profili pronti (Samsung 5.1 AC-3 48 kHz, Samsung Stereo, downmix 5.1→2.0 “Samsung”); catena = denoise → gain → EQ → riverbero/stereo/compressore; Dynamic Audio Normalizer + Dialog Boost; opzioni Mantieni MONO / Evita clipping / Downmix stereo; Preview identica alla GUI.
• String builder: scripts/string_audio_generator.py non converte; costruisce la stringa di argomenti ffmpeg per GUI/coda.

Sistemi supportati
• Linux Mint 21.3 / Ubuntu 22.04+
• macOS High Sierra 10.13 (Intel) con ruote compatibili più vecchie
• macOS 10.15+ (Intel/Apple Silicon) via Homebrew
• Windows 10/11 (Python + ffmpeg nel PATH)

Installazione & Avvio — Linux (Mint/Ubuntu)
  sudo apt update
  sudo apt install -y \
    python3 python3-pyqt5 python3-pyqt5.qtmultimedia python3-pyqtgraph \
    python3-numpy python3-psutil python3-chardet ffmpeg
  git clone https://github.com/Myname11959/Hevc-VideoConverter.git
  cd Hevc-VideoConverter
  python3 main.py
  # oppure:
  python3 -m hevc_gui.gui.main_window

Installazione & Avvio — macOS High Sierra (Intel)
  /usr/bin/python3 -m pip install -U pip setuptools wheel
  /usr/bin/python3 -m pip install "PyQt5<5.16" pyqtgraph numpy psutil chardet
  # Installa ffmpeg (ad es. binario statico) e assicurati che sia nel PATH
  git clone https://github.com/Myname11959/Hevc-VideoConverter.git
  cd Hevc-VideoConverter
  /usr/bin/python3 main.py
  Note: su HS è preferibile Python 3.8/3.9. Se pip non trova ruote, potrebbe compilare.

Installazione & Avvio — macOS 10.15+ (Intel/Apple Silicon)
  brew install python@3.11 ffmpeg
  python3 -m pip install -U pip setuptools wheel
  python3 -m pip install PyQt5 pyqtgraph numpy psutil chardet
  git clone https://github.com/Myname11959/Hevc-VideoConverter.git
  cd Hevc-VideoConverter
  python3 main.py

Installazione & Avvio — Windows 10/11
  py -m pip install --upgrade pip
  py -m pip install PyQt5 pyqtgraph numpy psutil chardet
  # Scarica ffmpeg e aggiungi la cartella bin al PATH
  git clone https://github.com/Myname11959/Hevc-VideoConverter.git
  cd Hevc-VideoConverter
  py main.py

Creare un pacchetto .deb (Ubuntu/Mint) — Opzione A
  python3 tools/scan_deps.py
  # (Se hai lo script) tools/make_deb.sh

Creare un pacchetto .deb — Opzione B (manuale)
  rm -rf build/deb && mkdir -p build/deb/DEBIAN build/deb/opt/hevc_gui
  rsync -a --exclude 'build' --exclude '.git' ./ build/deb/opt/hevc_gui/
  # file control:
  cat > build/deb/DEBIAN/control <<'EOF'
  Package: hevc-video-converter
  Version: 2.0.0
  Section: utils
  Priority: optional
  Architecture: all
  Depends: python3, python3-pyqt5, python3-pyqt5.qtmultimedia, python3-pyqtgraph, python3-numpy, python3-psutil, python3-chardet, ffmpeg
  Maintainer: Loris <loris.paganini@gmail.com>
  Description: HEVC Video Converter (Qt/ffmpeg)
   App Qt che genera comandi ffmpeg riproducibili per HEVC/x265.
  EOF
  dpkg-deb --build build/deb .
  # → ./hevc-video-converter_2.0.0_all.deb

Problemi comuni
• “ffmpeg non trovato” → installa ffmpeg e verifica con ffmpeg -version.
• “Manca PyQt5.QtMultimedia” → sudo apt install python3-pyqt5.qtmultimedia (Debian/Ubuntu) o aggiungi i plugin multimediali su altri OS.
• Errore Qt “xcb” (Linux) → installa librerie X11 mancanti (es. libxcb-xinerama0) o esegui sotto X11.
• Permessi → chmod +x tools/*.sh

Donazioni
Se il progetto ti è utile, puoi supportarlo:
https://paypal.me/loris1159

Licenza
Distribuito con CC BY-NC 4.0 (Attribuzione-NonCommerciale). Vedi LICENSE.

