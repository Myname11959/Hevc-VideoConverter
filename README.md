Legacy / Versione precedente (solo IT)

La versione precedente “solo Italiano” resta disponibile nelle release/tag storiche (non viene rimossa).


---

## 2) README.md completo (incolla nel file README.md e fai commit)

```md
# HEVC – Video Converter

[![UI Smoketest](https://github.com/Myname11959/Hevc-VideoConverter/actions/workflows/ui-smoketest.yml/badge.svg)](https://github.com/Myname11959/Hevc-VideoConverter/actions/workflows/ui-smoketest.yml)
[![Ruff](https://github.com/Myname11959/Hevc-VideoConverter/actions/workflows/ruff.yml/badge.svg)](https://github.com/Myname11959/Hevc-VideoConverter/actions/workflows/ruff.yml)

**Donate:** https://paypal.me/loris1159  
**Languages / Lingue:** English — Italian

---

## IT — Cos’è

HEVC – Video Converter è un’app **Qt/PyQt5** che genera comandi **ffmpeg** chiari e ripetibili per convertire video in **HEVC/x265**, con controllo fine su video e audio.  
Target principale: **Linux**. Su macOS/Windows gira da sorgenti se hai Python + dipendenze.

### Novità (v2.1.0.0)
- **Interfaccia bilingue (IT + EN)**: integrazione i18n estesa, `.ts/.qm` aggiornati.
- **Sinks i18n per log e QMessageBox**: messaggi più consistenti e traducibili.
- **Versione dinamica in UI/About**: niente più versione hardcoded.
- **Risorse Qt consolidate**: `icons.qrc` + icone aggiornate.
- **Repo ripulito**: rimossi/spostati fuori repo `.bak/.BROKEN/.TRASH` senza rompere build.

---

## EN — What it is

HEVC – Video Converter is a **Qt/PyQt5** app that generates clear, reproducible **ffmpeg** command lines to convert videos to **HEVC/x265**, with fine-grained control over video and audio.  
Primary target: **Linux**. On macOS/Windows it runs from sources with Python + dependencies.

### What’s new (v2.1.0.0)
- **Bilingual UI (IT + EN)**: project-wide i18n integration, updated `.ts/.qm`.
- **i18n sinks for logs and QMessageBox**: more consistent translations.
- **Dynamic version in UI/About**: no more hard-coded version strings.
- **Consolidated Qt resources**: `icons.qrc` + refreshed icons.
- **Repo cleanup**: `.bak/.BROKEN/.TRASH` artifacts removed/moved out without breaking builds.

---

# TL;DR / Quick copy-paste

## Linux Mint / Ubuntu (run from sources)
```bash
sudo apt update
sudo apt install -y \
  python3 python3-pyqt5 python3-pyqt5.qtmultimedia python3-pyqtgraph \
  python3-numpy python3-psutil python3-chardet ffmpeg git

git clone https://github.com/Myname11959/Hevc-VideoConverter.git
cd Hevc-VideoConverter
python3 main.py


Alternative entrypoint / Avvio alternativo:

python3 -m hevc_gui.gui.main_window

macOS 10.15+ (Intel / Apple Silicon incl. M4) — run from sources

Requires Homebrew / Richiede Homebrew:

brew install python@3.11 ffmpeg pyqt@5 git

python3 -m pip install -U pip setuptools wheel
python3 -m pip install PyQt5 pyqtgraph numpy psutil chardet

git clone https://github.com/Myname11959/Hevc-VideoConverter.git
cd Hevc-VideoConverter
python3 main.py

macOS High Sierra 10.13 (Intel) — run from sources

Note: best with Python 3.8/3.9; wheels may be older.
Nota: meglio con Python 3.8/3.9; se mancano wheel, pip può provare a compilare.

/usr/bin/python3 -m pip install -U pip setuptools wheel
/usr/bin/python3 -m pip install "PyQt5<5.16" pyqtgraph numpy psutil chardet

git clone https://github.com/Myname11959/Hevc-VideoConverter.git
cd Hevc-VideoConverter
/usr/bin/python3 main.py

Windows 10/11 — run from sources
py -m pip install --upgrade pip
py -m pip install PyQt5 pyqtgraph numpy psutil chardet

REM Install ffmpeg and add ...\ffmpeg\bin to PATH

git clone https://github.com/Myname11959/Hevc-VideoConverter.git
cd Hevc-VideoConverter
py main.py

Build .deb (Ubuntu/Mint)
bash tools/make_deb.sh

Source tar.gz

Puoi usare il tar.gz delle release (Assets) oppure creare un tarball da git:

APPV="2.1.0.0"
mkdir -p dist
git archive --format=tar.gz --prefix="hevc-video-converter_${APPV}/" \
  -o "dist/hevc-video-converter_${APPV}.tar.gz" HEAD

IMPORTANTISSIMO / VERY IMPORTANT — Subtitle Edit (snap)

Se usi Subtitle Edit installato come snap e devi lavorare con VOB/IFO su dischi esterni o sotto /mnt, esegui una volta sola:

sudo snap connect subtitle-edit:alsa :alsa
sudo snap connect subtitle-edit:removable-media :removable-media
sudo snap connect subtitle-edit:mount-observe :mount-observe

Troubleshooting / Problemi comuni

ffmpeg not found / ffmpeg non trovato → installa ffmpeg e verifica con ffmpeg -version.

No module named PyQt5.QtMultimedia → su Ubuntu: sudo apt install python3-pyqt5.qtmultimedia.

Qt xcb error (Linux) → installa librerie X11 mancanti (es. libxcb-xinerama0) o avvia sotto X11.

License / Licenza

CC BY-NC 4.0 (Attribution-NonCommercial). Vedi LICENSE.

Legacy / Versione precedente (solo IT)

Le versioni precedenti restano disponibili nelle release/tag storiche (non vengono rimosse).


---

Se vuoi, nel prossimo step ti dico **esattamente** dove incollare cosa su GitHub **senza perdere gli asset** (Publish vs Save draft) e come tenere “ufficiale” la release (tag su `main`, release notes pulite, ecc.).
::contentReference[oaicite:0]{index=0}
