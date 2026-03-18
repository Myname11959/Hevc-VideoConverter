from __future__ import annotations

import os

from PyQt5.QtCore import QSettings

from hevc_gui.mkv_suite.i18n_en import EN
LANG_KEY = "ui/lang"
LANG_IT = "it"
LANG_EN = "en"

def _embedded_lang_override():
    env = (os.environ.get("HEVC_MKV_EMBEDDED", "") or "").strip().lower()
    if env not in ("1", "true", "yes", "on"):
        return None
    v = (os.environ.get("HEVC_LANG", "") or os.environ.get("MKV_LANG", "") or "").strip().lower()
    if v.startswith("en"):
        return LANG_EN
    if v.startswith("it"):
        return LANG_IT
    return None


def get_lang(settings=None) -> str:
    ov = _embedded_lang_override()
    if ov:
        return ov
    st = settings or QSettings()
    try:
        v = str(st.value(LANG_KEY, LANG_IT))
    except Exception:
        v = LANG_IT
    return v if v in (LANG_IT, LANG_EN) else LANG_IT
def set_lang(lang: str, settings=None) -> None:
    if _embedded_lang_override() is not None:
        return
    st = settings or QSettings()
    st.setValue(LANG_KEY, lang)
def L(s: str) -> str:
    """Traduzione IT->EN basata su QSettings ui/lang. Base language: IT."""
    if get_lang() == LANG_EN:
        try:
            if s in _EN_TRIM_UI_EXTRA:
                return _EN_TRIM_UI_EXTRA[s]
        except Exception:
            pass
        try:
            if s in _EN_CUT_DIALOG_EXTRA:
                return _EN_CUT_DIALOG_EXTRA[s]
        except Exception:
            pass
        return EN.get(s, s)
    return s

def LT(text: str) -> str:
    """Translate longer bodies (e.g. HTML) by replacing known IT keys with EN values."""
    try:
        if get_lang() != LANG_EN:
            return text
        out = text
        # longest keys first to avoid partial replacements
        for k, v in sorted(EN.items(), key=lambda kv: len(kv[0]), reverse=True):
            if k and k in out:
                out = out.replace(k, v)
        return out
    except Exception:
        return text

# --- MKV Tools Suite: full EN translations for Cut dialog ---
_EN_CUT_DIALOG_EXTRA = {
    "Inserisci clip…": "Insert clips…",
    "Inserisci clip": "Insert clips",
    "Inserisci una o più clip nel file selezionato.": "Insert one or more clips into the selected file.",

    "Aiuto": "Help",
    "Aiuto taglio": "Cut help",
    "Apri": "Open",
    "Avanti di 1 frame": "Forward 1 frame",
    "Azzera": "Reset",
    "Cartella output": "Output folder",
    "Chiudi": "Close",
    "Completato": "Completed",
    "Con questi punti non rimane nulla da riprodurre.": "With these points nothing remains to be played.",
    "Conferma": "Confirm",
    "Conferma taglio rapido": "Confirm fast cut",
    "Crea file tagliato": "Create cut file",
    "Crea file senza i tagli": "Create file without cuts",
    "Creazione file tagliato fallita.": "Failed to create cut file.",
    "Creazione file tagliato fallita:": "Failed to create cut file:",
    "Da": "From",
    "Durata": "Duration",
    "Durata:": "Duration:",
    "Errore": "Error",
    "Esempio pratico": "Practical example",
    "File": "File",
    "File sorgente:": "Source file:",
    "File tagliato creato:": "Cut file created:",
    "Finalizzazione…": "Finalizing…",
    "Guida rapida taglio video": "Quick video cut guide",
    "Il file di output esiste già. Vuoi sovrascriverlo?": "The output file already exists. Do you want to overwrite it?",
    "Impossibile aprire la cartella output:": "Unable to open output folder:",
    "Impossibile avviare ffmpeg per il taglio preciso.": "Unable to start ffmpeg for precise cut.",
    "Impossibile avviare ffmpeg per i tagli multipli.": "Unable to start ffmpeg for multiple cuts.",
    "Imposta prima IN e OUT.": "Set IN and OUT first.",
    "Indietro di 1 frame": "Back 1 frame",
    "Info": "Info",
    "Informazioni": "Information",
    "Informazioni sorgente": "Source information",
    "Istruzioni / Manuale": "Instructions / Manual",
    "Istruzioni taglio video": "Video cut instructions",
    "Modalità": "Mode",
    "Modulo precise_cut non disponibile.": "precise_cut module not available.",
    "Nessun segmento utile prodotto.": "No useful segment produced.",
    "Nome file": "File name",
    "OUT deve essere maggiore di IN.": "OUT must be greater than IN.",
    "OUT supera la durata del file.": "OUT exceeds the file duration.",
    "Operazione": "Operation",
    "Output": "Output",
    "Pausa": "Pause",
    "Play": "Play",
    "Preparazione…": "Preparing…",
    "Preparazione taglio preciso…": "Preparing precise cut…",
    "Preparazione tagli multipli…": "Preparing multiple cuts…",
    "Preview": "Preview",
    "Preview del file creato non disponibile, uso la preview simulata.": "Preview of the created file is not available, using simulated preview.",
    "Preview risultato": "Result preview",
    "Preview selezione": "Selection preview",
    "Pronto": "Ready",
    "Questa finestra serve per scegliere visivamente i punti IN e OUT del tratto da tenere o da rimuovere.": "This window lets you visually choose the IN and OUT points of the part to keep or remove.",
    "Questa finestra serve per scegliere i punti del taglio direttamente dal player con audio.": "This window is used to choose cut points directly from the player with audio.",
    "Rimuovi il tratto IN → OUT": "Remove the IN → OUT range",
    "Rimuovi tratto": "Remove range",
    "Scambia IN/OUT": "Swap IN/OUT",
    "Scegli cartella output": "Choose output folder",
    "Se vuoi togliere dal minuto 10 al minuto 15:": "If you want to remove from minute 10 to minute 15:",
    "Segna IN": "Set IN",
    "Segna OUT": "Set OUT",
    "Seleziona prima un taglio dall'elenco.": "Select a cut from the list first.",
    "Sorgente": "Source",
    "Tagli multipli": "Multiple cuts",
    "Tagli multipli…": "Multiple cuts…",
    "Tagli salvati:": "Saved cuts:",
    "Taglio": "Trim",
    "Taglio e modalità": "Cut and mode",
    "Taglio preciso": "Precise cut",
    "Taglio preciso (ricodifica assistita)": "Precise cut (assisted re-encode)",
    "Taglio preciso in corso…": "Precise cut in progress…",
    "Taglio rapido": "Fast cut",
    "Taglio rapido (senza ricodifica)": "Fast cut (without re-encoding)",
    "Taglio rapido in corso…": "Fast cut in progress…",
    "Taglio rapido parte 1…": "Fast cut part 1…",
    "Taglio rapido parte 2…": "Fast cut part 2…",
    "Taglio rapido userà punti reali agganciati ai keyframe.": "Fast cut will use actual points snapped to keyframes.",
    "Taglio selezionato non valido.": "Selected cut is not valid.",
    "Taglio video": "Video trim",
    "Tempo non valido. Usa hh:mm:ss.mmm": "Invalid time. Use hh:mm:ss.mmm",
    "Tieni solo il tratto IN → OUT": "Keep only the IN → OUT range",
    "Tieni tratto": "Keep range",
    "Unione segmenti…": "Joining segments…",
    "Usa posizione corrente → IN": "Use current position → IN",
    "Usa posizione corrente → OUT": "Use current position → OUT",
    "Vai a": "Go to",
    "Vol": "Vol",
    "Volume preview audio": "Preview audio volume",
    "Vuoi continuare con questi punti reali del taglio rapido?": "Do you want to continue with these actual fast-cut points?",
    "Vuoi svuotare l'elenco dei tagli?": "Do you want to clear the cut list?",
    "A": "To",
    "Aggiungi qui i pezzi da togliere dal video.": "Add here the parts to remove from the video.",
    "Aggiungi taglio": "Add cut",
    "Modifica taglio": "Edit cut",
    "Elimina taglio": "Delete cut",
    "Svuota elenco": "Clear list",
    "Anteprima taglio": "Cut preview",
    "Nessun taglio aggiunto": "No cuts added",
    "Nessun taglio valido presente nell'elenco.": "No valid cuts in the list.",
    "Con più tagli viene usato automaticamente il taglio preciso.": "With multiple cuts, precise cut is used automatically.",
    "Per vedere il risultato completo con più tagli, crea prima il file.": "To see the complete result with multiple cuts, create the file first.",
    "Comando eseguito:": "Executed command:",
    "Log finale:": "Final log:",
    "Apri Dettagli per vedere il motivo.": "Open Details to see the reason.",
    "Nessun log disponibile.": "No log available.",
    "Comandi principali": "Main controls",
    "spostamento di 1 secondo": "move by 1 second",
    "spostamento di 100 ms": "move by 100 ms",
    "spostamento di 1 frame": "move by 1 frame",
    "riproduzione reale con audio": "real playback with audio",
    "salto diretto a un tempo preciso": "jump directly to an exact time",
    "Taglio singolo": "Single cut",
    "vai al punto iniziale e imposta IN": "go to the start point and set IN",
    "vai al punto finale e imposta OUT": "go to the end point and set OUT",
    "scegli se tenere solo quel tratto oppure rimuoverlo": "choose whether to keep only that part or remove it",
    "usa Preview selezione o Preview risultato per controllare": "use Selection preview or Result preview to check it",
    "premi Crea file tagliato": "press Create cut file",
    "più veloce e senza ricodifica, ma può agganciarsi ai keyframe e non essere preciso al fotogramma": "faster and without re-encoding, but it may snap to keyframes and not be frame-accurate",
    "più lento, ma rispetta molto meglio i punti scelti e ricrea il file prendendo automaticamente i parametri utili dal sorgente": "slower, but it matches the chosen points much more accurately and recreates the file by automatically taking useful parameters from the source",
    "Se devi togliere più pezzi dallo stesso video, usa il pulsante Tagli multipli…": "If you need to remove multiple parts from the same video, use the Multiple cuts… button.",
    "imposta DA e A per il primo pezzo da togliere": "set FROM and TO for the first part to remove",
    "premi Aggiungi taglio": "press Add cut",
    "ripeti per tutti gli altri pezzi": "repeat for all the other parts",
    "chiudi pure la finestrella: i tagli restano salvati": "you can close the small window: the cuts stay saved",
    "torna alla finestra principale e premi Crea file senza i tagli": "go back to the main window and press Create file without cuts",
    "Anteprime": "Previews",
    "riproduce il tratto scelto tra IN e OUT": "plays the selected part between IN and OUT",
    "mostra il risultato finale; se il file è già stato creato, apre proprio quello": "shows the final result; if the file has already been created, it opens that file itself",
    "Suggerimenti": "Tips",
    "Per la massima precisione usa Taglio preciso": "For maximum precision use Precise cut",
    "Per togliere pubblicità o più spezzoni usa Tagli multipli": "To remove ads or multiple clips use Multiple cuts",
    "Se il file esiste già, verrà chiesta conferma prima di sovrascriverlo": "If the file already exists, confirmation will be requested before overwriting it",
    "mantiene solo il pezzo tra IN e OUT.": "keeps only the part between IN and OUT.",
    "più lento, ma più fedele ai punti scelti.": "slower, but more faithful to the chosen points.",
    "più veloce, senza perdita, ma non sempre preciso al fotogramma.": "faster, lossless, but not always frame-accurate.",
    "seleziona": "select",
    "toglie il pezzo tra IN e OUT e tiene il resto.": "removes the part between IN and OUT and keeps the rest."
}

# --- MKV Tools Suite: generic EN translations for menu/toolbar trim ---
_EN_TRIM_UI_EXTRA = {
    "Taglio": "Trim",
    "Taglio…": "Trim…",
    "Taglio video": "Video trim",
}
