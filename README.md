# HEVC – Video Converter v2.1.0.0 (deb: 2.1.0.0-1)

**Languages / Lingue:** Italiano — English  
**Repo:** https://github.com/Myname11959/Hevc-VideoConverter  
**Donate:** https://paypal.me/loris1159

## IT — Novità principali
- **Interfaccia bilingue (IT + EN)**: integrazione i18n estesa al progetto, `.ts/.qm` aggiornati, traduzioni più coerenti.
- **Sinks i18n per log e QMessageBox**: messaggi “sotto il cofano” più consistenti e traducibili.
- **Versione dinamica in UI/About**: niente più versione hardcoded; la UI legge la versione dal file di progetto.
- **Risorse Qt consolidate**: `icons.qrc` e icone aggiornate.
- **Repo ripulito**: rimossi/spostati fuori repo vecchi `.bak/.BROKEN/.TRASH` senza rompere build/packaging.

## EN — Highlights
- **Bilingual UI (IT + EN)**: project-wide i18n integration, updated `.ts/.qm`, more consistent translations.
- **i18n sinks for logs and QMessageBox**: better “under-the-hood” messages and translations.
- **Dynamic version in UI/About**: no more hard-coded version strings; UI reads version from the project version file.
- **Consolidated Qt resources**: `icons.qrc` + refreshed icons.
- **Repository cleanup**: removed/moved `.bak/.BROKEN/.TRASH` artifacts out of the repo without breaking build/packaging.

## Download / Download
- **Linux (.deb)**: vedi “Assets” di questa release.
- **Source (.tar.gz)**: vedi “Assets” di questa release (per macOS/Windows e altri OS).

## Supported OS / Sistemi supportati
- Linux Mint / Ubuntu (primary / primario)
- macOS 10.15+ (Intel/Apple Silicon, incl. M4) via Homebrew + Python deps
- macOS High Sierra 10.13 (Intel) via older compatible wheels
- Windows 10/11 (Python + ffmpeg in PATH)

## Quick run from sources / Avvio rapido da sorgenti

### Linux Mint / Ubuntu
```bash
sudo apt update
sudo apt install -y \
  python3 python3-pyqt5 python3-pyqt5.qtmultimedia python3-pyqtgraph \
  python3-numpy python3-psutil python3-chardet ffmpeg git

git clone https://github.com/Myname11959/Hevc-VideoConverter.git
cd Hevc-VideoConverter
python3 main.py

macOS 10.15+ (Intel / Apple Silicon incl. M4)
brew install python@3.11 ffmpeg pyqt@5 git

python3 -m pip install -U pip setuptools wheel
python3 -m pip install PyQt5 pyqtgraph numpy psutil chardet

git clone https://github.com/Myname11959/Hevc-VideoConverter.git
cd Hevc-VideoConverter
python3 main.py

Windows 10/11
py -m pip install --upgrade pip
py -m pip install PyQt5 pyqtgraph numpy psutil chardet

REM Install ffmpeg and add ...\ffmpeg\bin to PATH

git clone https://github.com/Myname11959/Hevc-VideoConverter.git
cd Hevc-VideoConverter
py main.py

IMPORTANTISSIMO / VERY IMPORTANT — Subtitle Edit (snap)

Se usi Subtitle Edit installato come snap e devi lavorare con VOB/IFO su dischi esterni o sotto /mnt, esegui una volta sola:

sudo snap connect subtitle-edit:alsa :alsa
sudo snap connect subtitle-edit:removable-media :removable-media
sudo snap connect subtitle-edit:mount-observe :mount-observe
