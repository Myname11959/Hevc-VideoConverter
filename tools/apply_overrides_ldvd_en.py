#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

TS = Path("hevc_gui/resources/i18n/hevc_en.ts")

# Mappa ITA -> ENG (solo messaggi umani/sink)
MAP = {
    # QMessageBox titoli
    "Apri .srt": "Open .srt",
    "Errore": "Error",
    "Estrazione": "Extraction",
    "Estrazione (segmenti VTS)": "Extraction (VTS segments)",
    "Passa a HEVC": "Send to HEVC",
    "Uscita": "Exit",
    "Operazione in corso": "Operation in progress",
    "Annullato": "Canceled",
    "Info": "Info",

    # QMessageBox testi
    "Il file selezionato non esiste più sul disco.": "The selected file no longer exists on disk.",
    "Impossibile aprire il file:\n{0}": "Unable to open the file:\n{0}",
    "Impossibile aprire la cartella:\n{0}": "Unable to open the folder:\n{0}",
    "Errore avviando Subtitle Edit:\n{0}": "Error starting Subtitle Edit:\n{0}",
    'Il comando "eject" non è disponibile.': '"eject" command is not available.',
    "Impossibile {0} il cassetto: {1}": "Unable to {0} the tray: {1}",
    "La coda è vuota. Aggiungi uno o più .vob.": "The queue is empty. Add one or more .vob files.",
    "Nessun VOB in coda.": "No VOBs in queue.",
    "Non riesco a determinare il mount del DVD.": "I can't determine the DVD mount point.",
    "Non riesco a capire il VTS (VTS_01, VTS_02...).": "I can't determine the VTS (VTS_01, VTS_02...).",
    "Impossibile creare:\n{0}\n{1}": "Unable to create:\n{0}\n{1}",
    "Nessun file VTS valido in coda (solo .vob/.ifo/.bup).": "No valid VTS files in queue (only .vob/.ifo/.bup).",
    "Staging fallito.": "Staging failed.",
    "Segmenti staging OK ma lista VOB vuota.": "Staging succeeded but VOB list is empty.",
    "Percorso output mancante.": "Missing output path.",
    "Sidecar non generati: {0}": "Sidecar files not generated: {0}",
    "Estrazione fallita.": "Extraction failed.",
    "Estrazione completata.": "Extraction completed.",
    "Fallback richiesto ma non ho un percorso di output valido.": "Fallback requested but I don't have a valid output path.",
    "Fallback: non riesco a determinare il mount del DVD.": "Fallback: I can't determine the DVD mount point.",
    "Fallback: non riesco a capire il VTS (VTS_01, VTS_02...).": "Fallback: I can't determine the VTS (VTS_01, VTS_02...).",
    "Fallback: impossibile creare:\n{0}\n{1}": "Fallback: unable to create:\n{0}\n{1}",
    "Fallback: nessun file VTS valido in coda (solo .vob/.ifo/.bup).": "Fallback: no valid VTS files in queue (only .vob/.ifo/.bup).",
    "Nessun VOB disponibile. Estrai prima un titolo.": "No VOB available. Extract a title first.",
    "Estrazione annullata.": "Extraction canceled.",
    "Operazione annullata.": "Operation canceled.",
    "Questo job non supporta annullamento.": "This job does not support cancel.",
    "Nessun job in corso.": "No job running.",
    "Attendi la fine dell'operazione o annulla.": "Wait for the operation to finish or cancel it.",
    "Impossibile pulire mentre un'operazione è in corso.": "Can't clean up while an operation is running.",

    # status/progress (controller + gui)
    "Pronto": "Ready",
    "Pronto.": "Ready.",
    "Annullato": "Canceled",
    "Pulito. Pronto.": "Cleaned. Ready.",
    "Nessun titolo": "No title",
    "Nessun lettore DVD trovato (/dev/sr0, /dev/dvd, /dev/cdrom).": "No DVD drive found (/dev/sr0, /dev/dvd, /dev/cdrom).",
    "VLC è già in esecuzione.": "VLC is already running.",
    "Avvio VLC su {0}…": "Starting VLC on {0}…",
    "Errore avvio VLC: {0}": "Error starting VLC: {0}",
    "Apro .srt: {0}": "Opening .srt: {0}",
    "Apro cartella VOB/.srt: {0}": "Opening VOB/.srt folder: {0}",
    "Aperto Subtitle Edit (cartella: {0})": "Subtitle Edit opened (folder: {0})",
    "Sorgente non disponibile: root impostata a {0}": "Source not available: root set to {0}",
    "DVD espulso. Root: {0}": "DVD ejected. Root: {0}",
    "Root DVD: {0}": "DVD root: {0}",
    "Errore mount: {0}": "Mount error: {0}",
    "Mount richiesto; attendo il disco…": "Mount required; waiting for disc…",
    "Mount non riuscito.": "Mount failed.",
    "udisksctl non disponibile (sudo apt install udisks2).": "udisksctl not available (sudo apt install udisks2).",
    "DVD non montato (inserisci il disco e riprova).": "DVD not mounted (insert the disc and try again).",
    "Cassetto: {0} OK": "Tray: {0} OK",
    "Dir: {0}": "Dir: {0}",
    "Preparazione segmenti (vobcopy -O) su disco…": "Preparing segments (vobcopy -O) to disk…",
    "Estrazione in corso…": "Extraction in progress…",
    "Copia VOB → file unico .vob": "Copying VOB → single .vob file",
    "Creo fileone .vob (concat locale)…": "Creating single .vob (local concat)…",
    "Copia segmenti locali → fileone .vob": "Copying local segments → single .vob",
    "Analisi DVD (lsdvd)…": "Analyzing DVD (lsdvd)…",
    "Scrittura finale…": "Final write…",
    "Postprocess fallito.": "Postprocess failed.",
    "Completato.": "Done.",
    "Completato": "Done",
    "Vobcopy …": "Vobcopy …",
}

def norm(s: str) -> str:
    return (s or "").replace("\r\n", "\n").replace("\r", "\n").strip()

def main() -> int:
    if not TS.exists():
        raise SystemExit(f"TS non trovato: {TS}")

    tree = ET.parse(TS)
    root = tree.getroot()

    hits = 0
    for ctx in root.findall("context"):
        for msg in ctx.findall("message"):
            src = norm(msg.findtext("source"))
            if not src:
                continue
            if src not in MAP:
                continue
            tr = msg.find("translation")
            if tr is None:
                tr = ET.SubElement(msg, "translation")
            tr.text = MAP[src]
            if "type" in tr.attrib:
                del tr.attrib["type"]
            hits += 1

    tree.write(TS, encoding="utf-8", xml_declaration=True)
    print(f"Overrides applied: {hits}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
