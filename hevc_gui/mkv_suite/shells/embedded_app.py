#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sys

from PyQt5.QtCore import Qt, QSize, QSettings, QTimer
from PyQt5.QtGui import QPixmap, QIcon
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QAction, QToolBar, QStyle, QMessageBox,
    QTabWidget, QSplitter, QDialog, QLabel, QHBoxLayout, QVBoxLayout, QDialogButtonBox
)

try:
    import hevc_gui.resources.icons_rc  # noqa: F401
except Exception:
    pass

try:
    from hevc_gui.i18n import L, get_lang
except Exception:
    def L(s: str) -> str:
        return s
    def get_lang(*a, **k) -> str:
        return os.environ.get("HEVC_LANG", "it")

_APPLY_APPEARANCE = None
try:
    from hevc_gui.gui.appearance_settings import apply_appearance as _apply_appearance  # type: ignore
    _APPLY_APPEARANCE = _apply_appearance
except Exception:
    _APPLY_APPEARANCE = None


# --- MKV Suite EN fallback (solo chiavi mancanti nel catalogo) ---
def _install_mkv_en_fallbacks() -> None:
    try:
        import hevc_gui.i18n as _i18n  # type: ignore
    except Exception:
        return

    if getattr(_i18n, "_MKV_EN_FALLBACKS_PATCHED", False):
        return

    _orig_L = getattr(_i18n, "L", None)
    if not callable(_orig_L):
        return

    _MAP_EN = {
        "Strumenti MKV": "MKV Tools",
        "Crea MKV": "Remux",
        "Unisci episodi": "Merge Episodes",
        "Cos'è MKV Suite": "What MKV Suite is",
        "Mini manuale interno di MKV Suite (spiegazioni semplici + stampa/esporta PDF).": "Built-in MKV Suite mini manual (simple explanations + print/export PDF).",
    }


    # --- MKV fallback extra batch 1 (labels + manual) ---
    _MAP_EN.update({
        # shells/embedded_app.py (menu/toolbar/main window)
        "Strumenti MKV": "MKV Tools",
        "Estrae le tracce selezionate nella cartella extract/.": "Extracts selected tracks into the extract/ folder.",
        "Cartella output…": "Output folder…",
        "Apri cartella output": "Open output folder",
        "Applica Tag": "Apply Tags",
        "Estrai tracce…": "Extract tracks…",
        "Crea MKV": "Remux",
        "Stop": "Stop",
        "User manual": "User manual",
        "Barra strumenti": "Toolbar",
        "Ripristina layout": "Reset layout",
        "Log": "Log",
        "Vai a Tracce": "Go to Tracks",
        "Vai a Capitoli": "Go to Chapters",
        "Vai a Unisci episodi": "Go to Merge Episodes",
        "File": "File",
        "Operazioni": "Actions",
        "Vai alla scheda": "Go to tab",
        "Pannello log non trovato in questa schermata.": "Log panel not found in this view.",
        "Log ": "Log ",
        "mostrato": "shown",
        "nascosto": "hidden",
        "Layout ripristinato (solo aspetto).": "Layout restored (appearance only).",
        "Layout ripristinato (toolbar/log).": "Layout restored (toolbar/log).",
        "Schede non trovate in questa schermata.": "Tabs not found in this view.",
        "Scheda attivata: ": "Tab activated: ",
        "Scheda non disponibile in questa schermata.": "Tab not available in this view.",
        "Impossibile caricare il manuale interno: {e}": "Unable to load the built-in manual: {e}",
        "Impossibile aprire il manuale interno: {e}": "Unable to open the built-in manual: {e}",
        "Versione embedded": "Embedded version",
        "Suite interna per estrazione, rimux, capitoli e strumenti MKV.": "Internal suite for extraction, remux, chapters and MKV tools.",

        # ui/main_widget.py (label principali / pulsanti / tab / messaggi base)
        "Sorgenti (Crea MKV) / File (Estrai)": "Sources (Remux) / Files (Extract)",
        "ID": "ID",
        "Includi": "Include",
        "Sorgente": "Source",
        "Tipo": "Type",
        "Default": "Default",
        "Forced": "Forced",
        "Nome traccia": "Track name",
        "Tracce": "Tracks",
        "Capitoli nel video: nessun MKV selezionato.": "Chapters in video: no MKV selected.",
        "File capitoli esterno (opzionale: .xml / .txt)": "External chapters file (optional: .xml / .txt)",
        "Nessun file capitoli esterno selezionato": "No external chapters file selected",
        "Genera": "Generate",
        "Unisci episodi": "Merge Episodes",
        "Titolo e output": "Title and output",
        "Anno": "Year",
        "Titolo": "Title",
        "Nome file": "File name",
        "Titolo media": "Media title",
        "Apri": "Open",
        "Cartella output": "Output folder",
        "Operazioni": "Actions",
        "Tutti i file (*.*);;Capitoli (*.xml *.txt)": "All files (*.*);;Chapters (*.xml *.txt)",
        "Seleziona capitoli": "Select chapters",
        "Capitoli nel video: assenti. Puoi usare un file capitoli esterno (.xml/.txt) oppure generarli.": "Chapters in video: none. You can use an external chapters file (.xml/.txt) or generate them.",
        "Capitoli nel video: presenti (1 capitolo).": "Chapters in video: present (1 chapter).",
        "Capitoli nel video: presenti ({n} capitoli).": "Chapters in video: present ({n} chapters).",
        "Aggiungi o seleziona un MKV per generare i capitoli.": "Add or select an MKV to generate chapters.",
        "Info": "Info",
        "Il file contiene già capitoli.\nVuoi generarli comunque?": "The file already contains chapters.\nDo you want to generate them anyway?",
        "Genera capitoli": "Generate chapters",
        "Metodo:": "Method:",
        "Intervallo fisso (minuti)": "Fixed interval (minutes)",
        "Scene (auto)": "Scenes (auto)",
        "Intervallo fisso": "Fixed interval",
        "Ogni quanti minuti?": "Every how many minutes?",
        "Scene threshold": "Scene threshold",
        "Soglia (0.0–1.0):": "Threshold (0.0–1.0):",
        "Impossibile aprire la cartella output:": "Unable to open output folder:",
        "Scegli cartella output": "Choose output folder",
        "Tutti i file (*.*);;Video (*.mkv *.mp4 *.m4v *.mov *.avi *.ts *.m2ts);;Audio (*.aac *.ac3 *.eac3 *.dts *.flac *.mp3 *.m4a *.wav *.ogg *.opus *.truehd *.mka);;Sottotitoli (*.srt *.ass *.ssa *.vtt *.sup *.idx *.sub);;Capitoli (*.xml *.txt)": "All files (*.*);;Video (*.mkv *.mp4 *.m4v *.mov *.avi *.ts *.m2ts);;Audio (*.aac *.ac3 *.eac3 *.dts *.flac *.mp3 *.m4a *.wav *.ogg *.opus *.truehd *.mka);;Subtitles (*.srt *.ass *.ssa *.vtt *.sup *.idx *.sub);;Chapters (*.xml *.txt)",
        "Aggiungi file": "Add files",
        "Hai selezionato un file capitoli.\nSelezionalo dalla scheda 'Capitoli'.\n\nFile ignorati:": "You selected a chapters file.\nSelect it from the 'Chapters' tab.\n\nIgnored files:",
        "Impossibile aprire l'editor sottotitoli:": "Unable to open subtitle editor:",
        "Scrive subito nel file MKV originale i metadati (titolo, nomi tracce, lingue, default/forced). Non fa remux e non crea un nuovo file.": "Writes metadata (title, track names, languages, default/forced) directly to the original MKV file. It does not remux and does not create a new file.",
        "Premi 'Applica Tag' per scrivere nel file originale, oppure 'Crea MKV' per creare un nuovo file.": "Click 'Apply Tags' to write to the original file, or 'Remux' to create a new file.",
        "Interrompe l'operazione in corso.": "Stops the current operation.",
        "Aggiunge file sorgenti alla lista.": "Adds source files to the list.",
        "Rimuove il file selezionato dalla lista (non dal disco).": "Removes the selected file from the list (not from disk).",
        "Apre la cartella output della sessione.": "Opens the session output folder.",
        "Campo di testo.": "Text field.",
        "Seleziona un valore dall'elenco.": "Select a value from the list.",
        "Imposta un valore.": "Set a value.",
        "Tabella dati. Doppio click per modifiche dove supportato.": "Data table. Double-click to edit where supported.",
        "Seleziona (o aggiungi) almeno un file MKV per Applica Tag.": "Select (or add) at least one MKV file for Apply Tags.",
        "Inserisci almeno un Titolo (e opzionalmente l’Anno).": "Enter at least a Title (and optionally the Year).",
        "Seleziona (o aggiungi) un file MKV per Estrai.": "Select (or add) an MKV file for Extract.",
        "[OK] Estrazione completata.": "[OK] Extraction completed.",
        "Operazione in corso. Premi Stop o attendi.": "Operation in progress. Press Stop or wait.",
        "Vuoi annullare e pulire tutto?\n(I dati non salvati andranno persi)": "Do you want to cancel and clean everything?\n(Unsaved data will be lost)",
        "Vuoi davvero uscire da Strumenti MKV?": "Do you really want to exit MKV Tools?",
        "C'è un'operazione in corso.\nVuoi uscire comunque?": "There is an operation in progress.\nDo you still want to exit?",

        # ui/concat_batch_tab.py (label principali)
        "Questo strumento si apre in una finestra separata, così hai più spazio per lavorare (file, gruppi, anteprima e log).": "This tool opens in a separate window, so you have more space to work (files, groups, preview and log).",
        "Usa la finestra dedicata per unire più MKV in sequenza senza ricodifica, in automatico oppure con Gruppi manuali.": "Use the dedicated window to merge multiple MKVs in sequence without re-encoding, automatically or with Manual groups.",
        "Apri finestra Unisci episodi": "Open Merge Episodes window",
        "Apre lo strumento completo in una finestra separata.": "Opens the full tool in a separate window.",
        "Suggerimento: lascia aperta la finestra dedicata mentre lavori, così qui la scheda resta pulita e semplice.": "Tip: keep the dedicated window open while working, so this tab stays clean and simple.",
        "Impossibile aprire la finestra 'Unisci episodi'.": "Unable to open the 'Merge Episodes' window.",

        # ui/concat_batch_dialog.py (label principali / colonne / pulsanti)
        "Manuale: scrivi tu il numero Gruppo in ogni riga (stesso numero = stesso file finale).": "Manual: write the Group number for each row (same number = same final file).",
        "Automatico: usa i tag/nomi episodio. Se incoerenti, controlla l'anteprima o passa a Manuale.": "Automatic: uses episode tags/names. If inconsistent, check the preview or switch to Manual.",
        "Modalità Manuale attiva: nessun raggruppamento automatico.": "Manual mode active: no automatic grouping.",
        "Automatico (default): aggiungi file e vedrai qui eventuali avvisi sui tag episodio.": "Automatic (default): add files and you will see any episode-tag warnings here.",
        "Automatico: tag episodio letti correttamente. Controlla comunque l'anteprima prima di unire.": "Automatic: episode tags read correctly. Still check the preview before merging.",
        "episodi non letti": "episodes not read",
        "episodi duplicati": "duplicate episodes",
        "stagione non uniforme": "non-uniform season",
        "sequenza non continua": "non-continuous sequence",
        "tag incoerenti": "inconsistent tags",
        "Avviso automatico: ": "Automatic warning: ",
        "Controlla l'anteprima oppure usa Gruppi manuali.": "Check the preview or use Manual groups.",
        "Unisci più MKV in sequenza senza ricodifica.": "Merge multiple MKVs in sequence without re-encoding.",
        "Aggiungi MKV…": "Add MKV…",
        "Svuota": "Clear",
        "Ordina": "Sort",
        "Modalità": "Mode",
        "Automatico": "Automatic",
        "Gruppi manuali": "Manual groups",
        "Automatico (default) oppure Gruppi manuali.": "Automatic (default) or Manual groups.",
        "Quante puntate per file": "Episodes per file",
        "Usato solo in Automatico. Esempio: 2 crea 1+2, 3+4, 5+6...": "Used only in Automatic mode. Example: 2 creates 1+2, 3+4, 5+6...",
        "Nome serie / prefisso": "Series name / prefix",
        "es. La Freccia Nera": "e.g. The Black Arrow",
        "Nome base dei file finali (es. La Freccia Nera).": "Base name for final files (e.g. The Black Arrow).",
        "Prepara anteprima": "Prepare preview",
        "Aggiorna l'anteprima dei file finali che verranno creati.": "Refreshes the preview of the final files that will be created.",
        "Elenco episodi / file sorgenti": "Episode list / source files",
        "#": "#",
        "Compat": "Compat",
        "Durata": "Duration",
        "Ep": "Ep",
        "Gruppo": "Group",
        "S": "S",
        "Titolo tag": "Tag title",
        "Anteprima output (nomi dei file che verranno creati).": "Output preview (names of files that will be created).",
        "N file": "N files",
        "Output (anteprima)": "Output (preview)",
        "Range": "Range",
        "Unisci gruppo selezionato": "Merge selected group",
        "Unisci tutti": "Merge all",

        # ui/user_manual_dialog.py (label + manual headings + pulsanti)
        "Cos'è MKV Suite": "What MKV Suite is",
        "Uso rapido (3 passi)": "Quick usage (3 steps)",
        "Scheda Tracce": "Tracks tab",
        "Scheda Capitoli": "Chapters tab",
        "Unisci episodi - Automatico": "Merge Episodes - Automatic",
        "Unisci episodi - Gruppi manuali": "Merge Episodes - Manual groups",
        "Menu Visualizza": "View menu",
        "Problemi comuni": "Common issues",
        "Stampa o salva in PDF": "Print or save as PDF",
        "MKV Suite - User manual": "MKV Suite - User manual",
        "Guida rapida interna. Testi semplici, esempi pratici.": "Built-in quick guide. Simple text, practical examples.",
        "Indice": "Index",
        "Torna all’indice": "Back to index",
        "Stampa…": "Print…",
        "Esporta PDF…": "Export PDF…",
        "Apre il dialog di stampa (puoi usare anche una stampante PDF di sistema).": "Opens the print dialog (you can also use a system PDF printer).",
        "Salva direttamente il manuale in un file PDF.": "Saves the manual directly to a PDF file.",
        "Chiude il mini manuale.": "Closes the mini manual.",
        "Stampa manuale": "Print manual",
        "Stampa non disponibile: {e}": "Printing not available: {e}",
        "Esporta PDF": "Export PDF",
        "PDF (*.pdf)": "PDF (*.pdf)",
        "Manuale salvato in PDF:\n{path}": "Manual saved as PDF:\n{path}",
        "Esportazione PDF non riuscita: {e}": "PDF export failed: {e}",
    })
    # --- end MKV fallback extra batch 1 ---

    # --- MKV fallback extra batch 2 (warnings + notifications) ---
    _MAP_EN.update({
        # embedded_app notifications / view navigation / log
        "Pannello log non trovato in questa schermata.": "Log panel not found in this view.",
        "Vai alla scheda": "Go to tab",
        "Log ": "Log ",
        "Layout ripristinato (toolbar/log).": "Layout restored (toolbar/log).",
        "Schede non trovate in questa schermata.": "Tabs not found in this view.",
        "Scheda attivata: ": "Tab activated: ",
        "Scheda non disponibile in questa schermata.": "Tab not available in this view.",
        "Impossibile caricare il manuale interno: {e}": "Unable to load the built-in manual: {e}",
        "Impossibile aprire il manuale interno: {e}": "Unable to open the built-in manual: {e}",

        # concat_batch_dialog warnings / info / tooltip/help
        "Manuale: scrivi tu il numero Gruppo in ogni riga (stesso numero = stesso file finale).": "Manual: write the Group number for each row (same number = same final file).",
        "Automatico: usa i tag/nomi episodio. Se incoerenti, controlla l'anteprima o passa a Manuale.": "Automatic: use episode tags/names. If inconsistent, check the preview or switch to Manual.",
        "Modalità Manuale attiva: nessun raggruppamento automatico.": "Manual mode active: no automatic grouping.",
        "episodi non letti": "episodes not read",
        "stagione non uniforme": "non-uniform season",
        "sequenza non continua": "non-continuous sequence",
        "Unisci gruppo selezionato": "Merge selected group",
        "Log": "Log",
        "Rimuove dalla lista i file selezionati (non cancella i file dal disco).": "Removes selected files from the list (does not delete files from disk).",
        "Seleziona la modalità di raggruppamento: Automatico oppure Gruppi manuali.": "Select grouping mode: Automatic or Manual groups.",
        "Suggerimenti rapidi sulla modalità selezionata.": "Quick tips for the selected mode.",
        "Elenco gruppi da creare. Puoi selezionare un gruppo e modificare il nome file di output nella colonna anteprima.": "List of groups to create. You can select a group and edit the output filename in the preview column.",
        "Avvia l'unione del solo gruppo selezionato nell'anteprima.": "Starts merging only the selected group in the preview.",
        "Interrompe l'operazione di unione in corso.": "Stops the current merge operation.",
        "Progressione dell'operazione di unione corrente (0-100%).": "Progress of the current merge operation (0-100%).",
        "Log operativo della finestra 'Unisci episodi'.": "Operational log for the 'Merge Episodes' window.",
        "Numero gruppo manuale. Stesso numero = stesso file finale (usato solo in 'Gruppi manuali').": "Manual group number. Same number = same final file (used only in 'Manual groups').",
        "Indice gruppo (o ID manuale in modalità manuale).": "Group index (or manual ID in manual mode).",
        "Stato dell'operazione (in attesa, in corso, ok, errore, saltato...).": "Operation status (waiting, running, ok, error, skipped...).",
        "Manuale: stesso numero = stesso file finale (es. 1,1,2,2,3,3,3).": "Manual: same number = same final file (e.g. 1,1,2,2,3,3,3).",
        "Info": "Info",
        "Seleziona un gruppo da unire.": "Select a group to merge.",
        "Prepara prima l'anteprima (gruppi).": "Prepare the preview first (groups).",
        "Attendi": "Please wait",
        "La MKV Suite sta già eseguendo un'operazione (Estrai/Crea MKV).": "MKV Suite is already running an operation (Extract/Remux).",
        "[INFO] Alcuni gruppi con 1 solo file sono stati saltati.": "[INFO] Some groups with only 1 file were skipped.",
        "Non ci sono gruppi validi da unire (servono almeno 2 file per gruppo).": "There are no valid groups to merge (at least 2 files per group are required).",

        # concat_batch_tab
        "Questo strumento si apre in una finestra separata, così hai più spazio per lavorare (file, gruppi, anteprima e log).": "This tool opens in a separate window, so you have more room to work (files, groups, preview and log).",
        "Suggerimento: lascia aperta la finestra dedicata mentre lavori, così qui la scheda resta pulita e semplice.": "Tip: keep the dedicated window open while you work, so this tab stays clean and simple.",
        "Impossibile aprire la finestra 'Unisci episodi'.": "Unable to open the 'Merge Episodes' window.",

        # main_widget warnings / dialogs / tooltips
        "Capitoli nel video: nessun MKV selezionato.": "Chapters in video: no MKV selected.",
        "Nessun file capitoli esterno selezionato": "No external chapters file selected",
        "Cartella output": "Output folder",
        "Seleziona capitoli": "Select chapters",
        "Aggiungi o seleziona un MKV per generare i capitoli.": "Add or select an MKV to generate chapters.",
        "Il file contiene già capitoli.\nVuoi generarli comunque?": "The file already contains chapters.\nDo you want to generate them anyway?",
        "Impossibile aprire la cartella output:": "Unable to open output folder:",
        "Scegli cartella output": "Choose output folder",
        "Hai selezionato un file capitoli.\nSelezionalo dalla scheda 'Capitoli'.\n\nFile ignorati:": "You selected a chapters file.\nSelect it from the 'Chapters' tab.\n\nIgnored files:",
        "Impossibile aprire l'editor sottotitoli:": "Unable to open the subtitle editor:",
        "Scrive subito nel file MKV originale i metadati (titolo, nomi tracce, lingue, default/forced). Non fa remux e non crea un nuovo file.": "Writes metadata (title, track names, languages, default/forced) directly into the original MKV file. It does not remux and does not create a new file.",
        "Estrae le tracce selezionate nella cartella extract/.": "Extracts selected tracks into the extract/ folder.",
        "Interrompe l'operazione in corso.": "Stops the current operation.",
        "Rimuove il file selezionato dalla lista (non dal disco).": "Removes the selected file from the list (not from disk).",
        "Apre la cartella output della sessione.": "Opens the session output folder.",
        "Seleziona un valore dall'elenco.": "Select a value from the list.",
        "Seleziona (o aggiungi) almeno un file MKV per Applica Tag.": "Select (or add) at least one MKV file for Apply Tags.",
        "Seleziona (o aggiungi) un file MKV per Estrai.": "Select (or add) an MKV file for Extract.",
        "[OK] Estrazione completata.": "[OK] Extraction completed.",
        "Operazione in corso. Premi Stop o attendi.": "Operation in progress. Press Stop or wait.",
        "Vuoi annullare e pulire tutto?\n(I dati non salvati andranno persi)": "Do you want to cancel and clean everything?\n(Unsaved data will be lost)",
        "Vuoi davvero uscire da Strumenti MKV?": "Do you really want to exit MKV Tools?",
        "C'è un'operazione in corso.\nVuoi uscire comunque?": "There is an operation in progress.\nDo you want to exit anyway?",

        # user_manual_dialog remaining runtime strings
        "Scheda Tracce": "Tracks tab",
        "Scheda Capitoli": "Chapters tab",
        "Mini manuale interno di MKV Suite (spiegazioni semplici + stampa/esporta PDF).": "Built-in MKV Suite mini manual (simple explanations + print/export PDF).",
        "Apre il dialog di stampa (puoi usare anche una stampante PDF di sistema).": "Opens the print dialog (you can also use a system PDF printer).",
        "Salva direttamente il manuale in un file PDF.": "Saves the manual directly to a PDF file.",
        "Chiude il mini manuale.": "Closes the mini manual.",
        "Stampa manuale": "Print manual",
        "Stampa non disponibile: {e}": "Printing not available: {e}",
        "Manuale salvato in PDF:\n{path}": "Manual saved to PDF:\n{path}",
        "Esportazione PDF non riuscita: {e}": "PDF export failed: {e}",
    })
    # --- end MKV fallback extra batch 2 ---

    # --- MKV fallback extra batch 3 (merge tooltips) ---
    _MAP_EN.update({
        "serie": "series",

        # popup / info merge
        "Prepara prima l'anteprima (gruppi).": "Prepare the preview first (groups).",

        # concat_batch_dialog tooltip/help rimasti
        "Unisce episodi MKV in sequenza senza ricodifica video/audio.": "Merges MKV episodes in sequence without re-encoding video/audio.",
        "Aggiunge uno o più file MKV alla lista sorgente.": "Adds one or more MKV files to the source list.",
        "Svuota la lista file, l'anteprima gruppi e lo stato della progressione.": "Clears the file list, group preview and progress state.",
        "Ordina i file per stagione/episodio e poi per nome file.": "Sorts files by season/episode and then by file name.",
        "Numero di episodi da unire in ogni file finale (solo modalità Automatico).": "Number of episodes to merge into each final file (Automatic mode only).",
        "Usato solo in Automatico. Esempio: 2 crea gruppi 1+2, 3+4, 5+6...": "Used only in Automatic mode. Example: 2 creates groups 1+2, 3+4, 5+6...",
        "Prefisso/nome serie usato per generare i nomi dei file finali in anteprima.": "Series prefix/name used to generate preview output filenames.",
        "Aggiorna l'anteprima dei gruppi e dei nomi output in base alle impostazioni correnti.": "Updates the groups and output filename preview based on current settings.",
        "Diagnostica automatica sui tag episodio per aiutare il raggruppamento.": "Automatic diagnostics on episode tags to help grouping.",
        "Elenco file sorgenti. In 'Gruppi manuali' puoi modificare la colonna Gruppo per decidere quali episodi finiscono nello stesso file.": "Source file list. In 'Manual groups' you can edit the Group column to decide which episodes end up in the same file.",
        "Anteprima dei file output che verranno creati dall'unione.": "Preview of output files that will be created by the merge.",
        "Avvia l'unione di tutti i gruppi validi mostrati in anteprima.": "Starts merging all valid groups shown in the preview.",
        "Posizione corrente del file nella lista.": "Current position of the file in the list.",
        "Stagione rilevata dai tag/nome file (se disponibile).": "Season detected from tags/file name (if available).",
        "Numero episodio rilevato dai tag/nome file (se disponibile).": "Episode number detected from tags/file name (if available).",
        "Nome del file sorgente MKV.": "Name of the source MKV file.",
        "Titolo embedded rilevato nel file MKV (se presente).": "Embedded title detected in the MKV file (if present).",
        "Durata del file sorgente.": "Duration of the source file.",
        "Compatibilità append rispetto al primo file (OK/MIX).": "Append compatibility compared to the first file (OK/MIX).",
        "Intervallo episodi del gruppo (range).": "Group episode interval (range).",
        "Numero di file contenuti nel gruppo.": "Number of files in the group.",
        "Nome file di output in anteprima (modificabile).": "Preview output filename (editable).",
        "Compatibilità complessiva del gruppo (OK/MIX).": "Overall group compatibility (OK/MIX).",
        "Layout tracce differente dal primo file (mkvmerge potrebbe rifiutare l'append).": "Track layout differs from the first file (mkvmerge may refuse append).",
        "Ignorato in Automatico. Passa a 'Gruppi manuali' per usarlo.": "Ignored in Automatic mode. Switch to 'Manual groups' to use it.",
        "Colonna ignorata in modalità Automatico. Passa a 'Gruppi manuali' per usarla.": "Column ignored in Automatic mode. Switch to 'Manual groups' to use it.",
        "Elenco file sorgenti. In modalità Automatico la colonna Gruppo è ignorata.": "Source file list. In Automatic mode the Group column is ignored.",
        "Aggiungi file MKV da unire": "Add MKV files to merge",
        "Aggiungi prima dei file MKV.": "Add MKV files first.",
        "La MKV Suite sta già eseguendo un'operazione (Estrai/Crea MKV).": "MKV Suite is already running an operation (Extract/Remux).",
        "saltato (1 file)": "skipped (1 file)",
    })
    # --- end MKV fallback extra batch 3 ---
    def _L_mkv_fallback(s, *args, **kwargs):
        out = _orig_L(s, *args, **kwargs)
        try:
            try:
                lang = (_i18n.get_lang() or "").lower()
            except Exception:
                lang = (os.environ.get("HEVC_LANG", "") or "").lower()
            if lang.startswith("en") and isinstance(s, str) and isinstance(out, str):
                # Applica fallback SOLO se il catalogo non ha tradotto (out == sorgente IT)
                if out == s and s in _MAP_EN:
                    return _MAP_EN[s]
        except Exception:
            pass
        return out

    try:
        _i18n.L = _L_mkv_fallback
        globals()["L"] = _L_mkv_fallback
        _i18n._MKV_EN_FALLBACKS_PATCHED = True
    except Exception:
        pass

_install_mkv_en_fallbacks()
# --- end MKV Suite EN fallback ---

from hevc_gui.mkv_suite.ui.main_widget import MainWidget


def _require_embedded_flag(argv: list[str]) -> None:
    if "--embedded" not in argv:
        print("[MKV Suite] Avviabile solo da HEVC (manca --embedded).", file=sys.stderr)
        raise SystemExit(2)


class EmbeddedWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(L("Strumenti MKV"))
        self.setMinimumSize(1100, 650)

        self.w = MainWidget(self)
        self.setCentralWidget(self.w)

        self._build_actions()
        # collega controlli interni del widget alle QAction (menu/toolbar)
        self.w.bind_actions({
            "add": self.actAdd,
            "remove": self.actRemove,
            "outdir": self.actOutDir,
            "tag": self.actTag,
            "extract": self.actExtract,
            "remux": self.actRemux,
            "stop": self.actStop,
        })
        self._build_menus()
        self._build_toolbar()
        self._unlock_resize_limits()

        try:
            _btn_extract = getattr(self.w, "btn_extract", None)
            _tt_extract = (_btn_extract.toolTip() if _btn_extract is not None else "") or L("Estrae le tracce selezionate nella cartella extract/.")
            self.actExtract.setToolTip(_tt_extract)
            self.actExtract.setStatusTip(_tt_extract)
            self.actExtract.setWhatsThis(_tt_extract)
        except Exception:
            pass
        try:
            self._sync_view_menu_state()
        except Exception:
            pass

    # --- geometry persistence (auto patch) ---
    def _restore_window_geometry_prefs(self) -> None:
        try:
            st = QSettings("HEVC-GUI", "MKVSuiteEmbedded")
            geo = st.value("main/geometry")
            if geo:
                self.restoreGeometry(geo)
            win_state = st.value("main/windowState")
            if win_state:
                self.restoreState(win_state)
        except Exception:
            pass

    def _save_window_geometry_prefs(self) -> None:
        try:
            st = QSettings("HEVC-GUI", "MKVSuiteEmbedded")
            st.setValue("main/geometry", self.saveGeometry())
            st.setValue("main/windowState", self.saveState())
        except Exception:
            pass

    # --- resize unlock (auto patch) ---
    def _unlock_resize_limits(self) -> None:
        """Sblocca eventuali vincoli residui su larghezza/altezza."""
        try:
            self.setMinimumSize(640, 420)
            self.setMaximumSize(16777215, 16777215)
        except Exception:
            pass
        try:
            cw = self.centralWidget()
            if cw is not None:
                cw.setMinimumSize(1, 1)
                cw.setMaximumSize(16777215, 16777215)
        except Exception:
            pass

    def _build_actions(self) -> None:
        s = self.style()

        self.actAdd = QAction(s.standardIcon(QStyle.SP_DialogOpenButton), L("Aggiungi file…"), self)
        self.actAdd.triggered.connect(self.w.on_add_files)

        self.actRemove = QAction(s.standardIcon(QStyle.SP_TrashIcon), L("Rimuovi selezionati"), self)
        self.actRemove.triggered.connect(self.w.on_remove_selected)

        self.actOutDir = QAction(s.standardIcon(QStyle.SP_DirOpenIcon), L("Cartella output…"), self)
        self.actOutDir.triggered.connect(self.w.on_choose_outdir)


        self.actOpenOutDir = QAction(


            s.standardIcon(QStyle.SP_ComputerIcon),


            L("Apri cartella output"),


            self


        )


        self.actOpenOutDir.triggered.connect(self.w.open_output_folder)
        self.actTag = QAction(s.standardIcon(QStyle.SP_FileDialogDetailedView), L("Applica Tag"), self)
        self.actTag.triggered.connect(self.w.apply_tags)

        self.actExtract = QAction(s.standardIcon(QStyle.SP_ArrowDown), L("Estrai tracce…"), self)
        self.actExtract.triggered.connect(self.w.extract_selected)

        self.actRemux = QAction(s.standardIcon(QStyle.SP_BrowserReload), L("Crea MKV"), self)
        self.actRemux.triggered.connect(self.w.remux_selected)

        self.actStop = QAction(s.standardIcon(QStyle.SP_BrowserStop), L("Stop"), self)
        self.actStop.triggered.connect(self.w.stop_jobs)

        self.actExit = QAction(L("Esci"), self)
        self.actExit.triggered.connect(self.close)

        self.actAbout = QAction(L("Informazioni…"), self)
        self.actAbout.triggered.connect(self._about)

        # Aiuto
        self.actUserManual = QAction(L("User manual"), self)
        self.actUserManual.triggered.connect(self._user_manual)

        try:
            _ic_manual = QIcon(":/icons/ph_user_manual.png")
            if _ic_manual.isNull():
                _ic_manual = QIcon(":/icons/ph_help.png")
            self.actUserManual.setIcon(_ic_manual)
        except Exception:
            pass
        self.actUserManual.setIcon(QIcon(":/icons/ph_user_manual.png"))

        # Visualizza
        self.actViewToolbar = QAction(L("Barra strumenti"), self)
        self.actViewToolbar.setCheckable(True)
        self.actViewToolbar.setChecked(True)
        self.actViewToolbar.triggered.connect(self._toggle_toolbar_visible)

        self.actViewResetLayout = QAction(L("Ripristina layout"), self)
        self.actViewResetLayout.triggered.connect(self._restore_default_view_layout)

        self.actViewLog = QAction(L("Log"), self)
        self.actViewLog.setCheckable(True)
        self.actViewLog.setChecked(True)
        self.actViewLog.triggered.connect(self._toggle_log_visible)

        self.actViewGoTracks = QAction(L("Vai a Tracce"), self)
        self.actViewGoTracks.triggered.connect(
            lambda: self._goto_tab_by_names(["tracce", "tracks"])
        )

        self.actViewGoChapters = QAction(L("Vai a Capitoli"), self)
        self.actViewGoChapters.triggered.connect(
            lambda: self._goto_tab_by_names(["capitoli", "chapters"])
        )

        self.actViewGoConcat = QAction(L("Vai a Unisci episodi"), self)
        self.actViewGoConcat.triggered.connect(
            lambda: self._goto_tab_by_names([
                "unisci episodi", "merge episodes", "merge", "concat", "batch", "episodi"
            ])
        )

        # --- icone QAction (menu + toolbar) ---
        def _set_icon(action, res_path: str) -> None:
            try:
                if action is None:
                    return
                ic = QIcon(res_path)
                if not ic.isNull():
                    action.setIcon(ic)
            except Exception:
                pass

        # File
        _set_icon(self.actAdd, ":/icons/ph_list-add.png")
        _set_icon(self.actRemove, ":/icons/ph_list-remove.png")
        _set_icon(self.actOpenOutDir, ":/icons/ph_out_folder.png")
        _set_icon(self.actOutDir, ":/icons/ph_folder-open.png")
        _set_icon(self.actExit, ":/icons/ph_exit.png")

        # Operazioni
        _set_icon(self.actTag, ":/icons/ph_edit_queue.png")
        _set_icon(self.actExtract, ":/icons/ph_send.png")
        _set_icon(self.actRemux, ":/icons/ph_view-refresh.png")
        _set_icon(self.actStop, ":/icons/ph_process-stop.png")

        # Visualizza
        _set_icon(self.actViewToolbar, ":/icons/ph_open.png")
        _set_icon(self.actViewLog, ":/icons/ph_minfo.png")
        self.actViewToolbar.setIconVisibleInMenu(False)
        self.actViewLog.setIconVisibleInMenu(False)
        _set_icon(self.actViewResetLayout, ":/icons/ph_view-refresh.png")
        _set_icon(self.actViewGoTracks, ":/icons/ph_go-next.png")
        _set_icon(self.actViewGoChapters, ":/icons/ph_chapters.png")
        _set_icon(self.actViewGoConcat, ":/icons/ph_mkv.png")

        # Aiuto
        _set_icon(self.actUserManual, ":/icons/ph_user_manual.png")
        _set_icon(self.actAbout, ":/icons/ph_info.png")

    def _build_menus(self) -> None:
        mb = self.menuBar()

        m_file = mb.addMenu(L("File"))
        m_file.addAction(self.actAdd)
        m_file.addAction(self.actRemove)
        m_file.addSeparator()
        m_file.addAction(self.actOutDir)
        m_file.addAction(self.actOpenOutDir)
        m_file.addSeparator()
        m_file.addAction(self.actExit)

        m_ops = mb.addMenu(L("Operazioni"))
        m_ops.addAction(self.actTag)
        m_ops.addAction(self.actExtract)
        m_ops.addAction(self.actRemux)
        m_ops.addSeparator()
        m_ops.addAction(self.actStop)

        m_view = mb.addMenu(L("Visualizza"))
        m_view.addAction(self.actViewToolbar)
        m_view.addAction(self.actViewLog)
        m_view.addAction(self.actViewResetLayout)
        m_view.addSeparator()
        m_view_tabs = m_view.addMenu(L("Vai alla scheda"))
        m_view_tabs.addAction(self.actViewGoTracks)
        m_view_tabs.addAction(self.actViewGoChapters)
        m_view_tabs.addAction(self.actViewGoConcat)

        m_help = mb.addMenu(L("Aiuto"))
        m_help.addAction(self.actUserManual)
        try:
            _um_icon = QIcon(":/icons/ph_user_manual.png")
            if _um_icon.isNull():
                _um_icon = QIcon(":/icons/ph_help.png")
            self.actUserManual.setIcon(_um_icon)
            self.actUserManual.setIconVisibleInMenu(True)
        except Exception:
            pass
        m_help.addSeparator()
        m_help.addAction(self.actAbout)

    def _build_toolbar(self) -> None:
        tb = QToolBar(L("Azioni rapide"), self)
        tb.setMovable(False)
        tb.setIconSize(QSize(40, 40))
        self.addToolBar(Qt.TopToolBarArea, tb)

        tb.addAction(self.actAdd)
        tb.addAction(self.actRemove)
        tb.addAction(self.actOutDir)
        tb.addAction(self.actOpenOutDir)
        tb.addSeparator()
        tb.addAction(self.actTag)
        tb.addAction(self.actExtract)
        tb.addAction(self.actRemux)
        tb.addSeparator()
        tb.addAction(self.actStop)


    def _sync_view_menu_state(self) -> None:
        # Nota: all'avvio, prima dello show(), isVisible() può risultare False anche se
        # la toolbar è destinata a essere visibile. Usiamo isHidden() per uno stato più affidabile.
        try:
            tbs = self.findChildren(QToolBar)
            vis = any(not tb.isHidden() for tb in tbs) if tbs else True
        except Exception:
            vis = True
        try:
            self.actViewToolbar.setChecked(bool(vis))
        except Exception:
            pass

        try:
            if hasattr(self, "actViewLog"):
                self.actViewLog.setChecked(bool(self._is_log_visible()))
        except Exception:
            pass

    def _toggle_toolbar_visible(self, checked: bool) -> None:
        v = bool(checked)
        for tb in self.findChildren(QToolBar):
            try:
                tb.setVisible(v)
            except Exception:
                pass
        self._sync_view_menu_state()

    def _find_log_widget(self):
        try:
            w = getattr(self, "w", None)
            if w is None:
                return None
            # MainWidget ha self.log (QTextEdit)
            lw = getattr(w, "log", None)
            if lw is not None:
                return lw
        except Exception:
            pass
        return None

    def _find_log_container(self):
        lw = self._find_log_widget()
        if lw is None:
            return None
        try:
            p = lw.parentWidget()  # tipicamente QGroupBox "Log"
            if p is not None:
                return p
        except Exception:
            pass
        return lw

    def _is_log_visible(self) -> bool:
        box = self._find_log_container()
        if box is None:
            return False
        try:
            return not box.isHidden()
        except Exception:
            try:
                return box.isVisible()
            except Exception:
                return False

    def _toggle_log_visible(self, checked: bool) -> None:
        box = self._find_log_container()
        if box is None:
            QMessageBox.information(self, L("Visualizza"), L("Pannello log non trovato in questa schermata."))
            try:
                self._sync_view_menu_state()
            except Exception:
                pass
            return
        try:
            box.setVisible(bool(checked))
        except Exception:
            pass
        try:
            self._sync_view_menu_state()
        except Exception:
            pass
        try:
            self._log_view_info(L("Log ") + (L("mostrato") if checked else L("nascosto")))
        except Exception:
            pass

    def _restore_default_view_layout(self) -> None:
        # Ripristina SOLO l'aspetto della GUI (non tocca dati/file/tab corrente)
        restored = 0

        # 0) Riporta visibili toolbar e log (aspetto di avvio)
        try:
            self._toggle_toolbar_visible(True)
        except Exception:
            pass

        try:
            if hasattr(self, "actViewLog"):
                self._toggle_log_visible(True)
        except Exception:
            pass

        try:
            rootw = getattr(self, "w", None)
        except Exception:
            rootw = None

        # 1) Splitter dentro il widget centrale principale
        try:
            splitters = rootw.findChildren(QSplitter) if rootw is not None else []
        except Exception:
            splitters = []

        # 2) Fallback: cerca su tutta la finestra
        if not splitters:
            try:
                splitters = self.findChildren(QSplitter)
            except Exception:
                splitters = []

        # Prima quelli principali
        try:
            splitters = sorted(splitters, key=lambda sp: int(sp.count()), reverse=True)
        except Exception:
            pass

        for sp in splitters:
            try:
                count = int(sp.count())
            except Exception:
                continue

            try:
                if count == 3:
                    # Layout principale MainWidget (lista sorgenti / area centrale / pannello dx)
                    sp.setSizes([320, 860, 360])
                    restored += 1
                elif count == 2:
                    # Splitter secondari (anteprime/tabelle/log ecc.)
                    sp.setSizes([520, 380])
                    restored += 1
            except Exception:
                pass

        # 3) Ritocco visivo tabelle (solo estetica)
        try:
            from PyQt5.QtWidgets import QTableWidget
            tables = rootw.findChildren(QTableWidget) if rootw is not None else []
            for t in tables:
                try:
                    t.resizeColumnsToContents()
                except Exception:
                    pass
        except Exception:
            pass

        # 4) Refresh grafico
        try:
            if rootw is not None:
                rootw.updateGeometry()
                rootw.update()
                rootw.repaint()
        except Exception:
            pass

        # 5) Sincronizza i check del menu Visualizza
        try:
            self._sync_view_menu_state()
        except Exception:
            pass

        try:
            if restored > 0:
                self._log_view_info(L("Layout ripristinato (solo aspetto)."))
            else:
                self._log_view_info(L("Layout ripristinato (toolbar/log)."))
        except Exception:
            pass

    def _log_view_info(self, msg: str) -> None:
        try:
            if hasattr(self, "w") and hasattr(self.w, "_log") and callable(self.w._log):
                self.w._log("[UI] " + msg)
        except Exception:
            pass

    def _find_main_tabwidget(self):
        try:
            tabs = self.w.findChildren(QTabWidget)
        except Exception:
            tabs = []
        if not tabs:
            return None
        # prende quello più "ricco" (quasi sempre il tab centrale principale)
        try:
            tabs = sorted(tabs, key=lambda t: getattr(t, "count", lambda: 0)(), reverse=True)
        except Exception:
            pass
        return tabs[0]

    def _goto_tab_by_names(self, names) -> None:
        tw = self._find_main_tabwidget()
        if tw is None:
            QMessageBox.information(self, L("Visualizza"), L("Schede non trovate in questa schermata."))
            return

        wanted = [str(x).strip().lower() for x in (names or []) if str(x).strip()]
        for i in range(tw.count()):
            try:
                label = (tw.tabText(i) or "").strip().lower()
            except Exception:
                label = ""
            if any(k in label for k in wanted):
                tw.setCurrentIndex(i)
                try:
                    self._log_view_info(L("Scheda attivata: ") + tw.tabText(i))
                except Exception:
                    pass
                return

        QMessageBox.information(
            self,
            L("Visualizza"),
            L("Scheda non disponibile in questa schermata.")
        )

    def _user_manual(self) -> None:
        try:
            from hevc_gui.mkv_suite.ui.user_manual_dialog import UserManualDialog
        except Exception as e:
            QMessageBox.warning(
                self,
                L("User manual"),
                L("Impossibile caricare il manuale interno: {e}").format(e=str(e))
            )
            return

        dlg = getattr(self, "_user_manual_dlg", None)
        if dlg is None:
            try:
                dlg = UserManualDialog(self)
            except Exception as e:
                QMessageBox.warning(
                    self,
                    L("User manual"),
                    L("Impossibile aprire il manuale interno: {e}").format(e=str(e))
                )
                return
            self._user_manual_dlg = dlg
            try:
                dlg.destroyed.connect(self._on_user_manual_destroyed)
            except Exception:
                pass

        try:
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
        except Exception:
            pass

    def _on_user_manual_destroyed(self, *_args) -> None:
        self._user_manual_dlg = None

    def showEvent(self, e):
        try:
            super().showEvent(e)
        except Exception:
            try:
                QMainWindow.showEvent(self, e)
            except Exception:
                pass
        try:
            self._sync_view_menu_state()
        except Exception:
            pass

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if getattr(self, "_geom_restored_once", False):
            return
        self._geom_restored_once = True
        try:
            QTimer.singleShot(0, self._restore_window_geometry_prefs)
        except Exception:
            pass

    def closeEvent(self, event) -> None:
        try:
            self._save_window_geometry_prefs()
        except Exception:
            pass
        super().closeEvent(event)

    def _about(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle(L("Informazioni"))
        dlg.setModal(True)
        dlg.resize(400, 300)

        root = QVBoxLayout(dlg)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        # icona in alto centrata
        lbl_icon = QLabel(dlg)
        lbl_icon.setFixedSize(120, 120)
        lbl_icon.setAlignment(Qt.AlignCenter)
        pm = QPixmap(":/icons/ph_mkv.png")
        if not pm.isNull():
            lbl_icon.setPixmap(pm.scaled(120, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        root.addWidget(lbl_icon, 0, Qt.AlignHCenter)

        # testo
        lbl_title = QLabel("<b>" + L("Strumenti MKV") + "</b>", dlg)
        lbl_title.setAlignment(Qt.AlignHCenter)

        lbl_sub = QLabel(L("Versione embedded"), dlg)
        lbl_sub.setAlignment(Qt.AlignHCenter)

        lbl_msg = QLabel(L("Suite interna per estrazione, rimux, capitoli e strumenti MKV."), dlg)
        lbl_msg.setWordWrap(True)
        lbl_msg.setAlignment(Qt.AlignHCenter)

        root.addWidget(lbl_title)
        root.addWidget(lbl_sub)
        root.addWidget(lbl_msg)
        root.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok, parent=dlg)
        buttons.accepted.connect(dlg.accept)
        root.addWidget(buttons, 0, Qt.AlignHCenter)

        dlg.exec_()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    _require_embedded_flag(argv)

    try:
        get_lang()
    except Exception:
        pass

    app = QApplication(argv)

    if _APPLY_APPEARANCE is not None:
        try:
            _APPLY_APPEARANCE(app)
        except TypeError:
            try:
                _APPLY_APPEARANCE()
            except Exception:
                pass
        except Exception:
            pass

    w = EmbeddedWindow()
    w.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
