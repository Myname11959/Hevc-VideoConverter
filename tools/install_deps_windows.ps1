# Esegui con tasto destro "Esegui con PowerShell" oppure:
#   powershell -ExecutionPolicy Bypass -File tools\install_deps_windows.ps1
$ErrorActionPreference = "Stop"

# Verifica Python
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  Write-Host "Python non trovato. Installa Python 3.10+ dal sito ufficiale (spunta 'Add to PATH')." -ForegroundColor Yellow
  exit 1
}

# Aggiorna pip e pacchetti Python
python -m pip install --upgrade pip
python -m pip install PyQt5 pyqtgraph numpy psutil chardet

# FFmpeg (solo check, non scarico)
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
  Write-Host "ATTENZIONE: FFmpeg non trovato." -ForegroundColor Yellow
  Write-Host "Scarica una build (es. Gyan.dev/BtbN) e aggiungi 'bin' al PATH, oppure metti ffmpeg.exe accanto all'exe."
} else {
  Write-Host "FFmpeg OK."
}

Write-Host "✔ Dipendenze installate. Avvia con:  python main.py"
