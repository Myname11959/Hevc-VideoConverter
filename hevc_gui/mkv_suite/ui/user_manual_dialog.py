#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from html import escape

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextBrowser,
    QListWidget, QListWidgetItem, QFileDialog, QMessageBox, QSplitter
)
from PyQt5.QtPrintSupport import QPrinter, QPrintDialog

from hevc_gui.mkv_suite.i18n import L, LT, get_lang, LANG_EN


class UserManualDialog(QDialog):
    """
    Mini manuale interno MKV Tools Suite.
    Semplice, leggibile e stampabile / esportabile in PDF.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(L("User manual"))
        try:
            self.setModal(False)
        except Exception:
            pass
        try:
            self.resize(920, 780)
            self.setMinimumSize(700, 560)
        except Exception:
            pass

        self._sections = self._build_sections()
        self._build_ui()
        self._load_manual()
        self._select_first_section()

    # -------------------- language / content --------------------

    def _lang_pref(self) -> str:
        # 1) override env (MKV_LANG/HEVC_LANG), 2) current app lang
        v = (os.environ.get("MKV_LANG") or os.environ.get("HEVC_LANG") or "").strip().lower()
        if v.startswith("en"):
            return "en"
        if v.startswith("it"):
            return "it"
        return "en" if get_lang() == LANG_EN else "it"

    def _build_sections(self):
        return self._sections_en() if self._lang_pref() == "en" else self._sections_it()

    def _sections_it(self):
        return [
            (
                "intro",
                "Cos'è MKV Tools Suite",
                """
                <p><b>MKV Tools Suite</b> è una raccolta di strumenti per lavorare sui file MKV in modo pratico,
                cercando di evitare ricodifiche inutili quando non servono.</p>

                <p>La suite permette, a seconda del tool usato, di:</p>
                <ul>
                  <li>vedere e selezionare tracce video, audio e sottotitoli</li>
                  <li>creare un nuovo MKV con le tracce desiderate</li>
                  <li>estrarre tracce o capitoli</li>
                  <li>applicare tag e capitoli</li>
                  <li>unire episodi</li>
                  <li>tagliare una porzione precisa di un file già pronto</li>
                  <li>inserire una clip dentro un file principale mantenendo il risultato il più coerente possibile</li>
                </ul>

                <div class="note">
                <b>Idea semplice:</b> scegli il tool giusto, apri il file, controlli l'anteprima o le informazioni,
                poi lanci l'operazione.
                </div>
                """
            ),
            (
                "where_tools",
                "Dove trovi i tool",
                """
                <p>Nella GUI principale della suite i tool <b>Trim</b> e <b>Insert Clip</b> sono richiamabili da
                <b>toolbar</b> e <b>menubar</b>.</p>

                <p>I vecchi pulsanti laterali dedicati a Trim e Insert Clip sono stati rimossi.</p>

                <p><b>Importante:</b> questi due tool restano disponibili anche se la lista file della finestra
                principale è vuota.</p>
                """
            ),
            (
                "workflow",
                "Uso rapido",
                """
                <ol>
                  <li><b>Apri il tool corretto</b> dalla finestra principale.</li>
                  <li><b>Seleziona il file</b> nella GUI principale oppure direttamente dentro il dialog del tool.</li>
                  <li><b>Controlla</b> tracce, capitoli, preview o informazioni file.</li>
                  <li><b>Scegli la cartella di output</b> se richiesta.</li>
                  <li><b>Lancia l'operazione</b> e controlla il log o il file creato.</li>
                </ol>

                <p>Se non sei sicuro, fermati sempre prima e verifica:</p>
                <ul>
                  <li>file sorgente giusto</li>
                  <li>cartella output giusta</li>
                  <li>preview o info file</li>
                  <li>tracce selezionate corrette</li>
                </ul>
                """
            ),
            (
                "tracks",
                "Scheda Tracce",
                """
                <p>Nella scheda <b>Tracce</b> vedi le tracce presenti nel file: video, audio e sottotitoli.</p>
                <ul>
                  <li>puoi scegliere quali tracce includere</li>
                  <li>puoi controllare lingua, nome e alcuni flag</li>
                  <li>puoi preparare un nuovo MKV con solo ciò che ti serve</li>
                </ul>

                <p><b>Uso tipico:</b> tenere solo audio ITA + sottotitoli forzati, oppure pulire un file da tracce inutili.</p>
                """
            ),
            (
                "chapters",
                "Scheda Capitoli",
                """
                <p>Nella scheda <b>Capitoli</b> puoi gestire i capitoli del file.</p>
                <ul>
                  <li>se il file ha già capitoli embedded, la suite lo segnala</li>
                  <li>puoi usare un file capitoli esterno</li>
                  <li>puoi generare capitoli automaticamente nei flussi previsti</li>
                </ul>

                <p><b>Nota pratica:</b> la schermata serve a controllare e preparare il risultato finale;
                non basta vedere i capitoli a schermo per modificarli davvero, devi poi eseguire l'azione prevista.</p>
                """
            ),
            (
                "remux",
                "Crea MKV",
                """
                <p><b>Crea MKV</b> genera un nuovo file MKV usando le tracce, i capitoli e i tag scelti.</p>

                <p>È il comando giusto quando vuoi:</p>
                <ul>
                  <li>tenere solo alcune tracce</li>
                  <li>cambiare nomi, lingue o flag</li>
                  <li>aggiungere o sostituire capitoli</li>
                  <li>produrre un nuovo MKV pulito senza toccare l'originale</li>
                </ul>

                <div class="note">
                In generale questo è il comando “sicuro” quando vuoi ottenere un <b>nuovo file finale</b>.
                </div>
                """
            ),
            (
                "tags",
                "Applica Tag",
                """
                <p><b>Applica Tag</b> scrive i tag secondo il flusso previsto dal tool corrente.</p>

                <p>Se invece vuoi creare un file nuovo senza toccare l'originale, in genere devi usare <b>Crea MKV</b>.</p>

                <p><b>Promemoria semplice:</b></p>
                <ul>
                  <li><b>Applica Tag</b> = scrivi/metti a posto i tag</li>
                  <li><b>Crea MKV</b> = produci un nuovo file</li>
                </ul>
                """
            ),
            (
                "concat_auto",
                "Unisci episodi - Automatico",
                """
                <p>Usa questa modalità quando i file sono già ordinati bene e coerenti.</p>
                <ol>
                  <li>Aggiungi i file.</li>
                  <li>Lascia <b>Modalità = Automatico</b>.</li>
                  <li>Imposta quante puntate devono finire in ogni file finale.</li>
                  <li>Prepara l'anteprima.</li>
                  <li>Controlla nomi e gruppi.</li>
                  <li>Premi <b>Unisci</b>.</li>
                </ol>

                <p><b>Esempio:</b> con 7 episodi e valore 2 ottieni gruppi 1+2, 3+4, 5+6, 7.</p>
                """
            ),
            (
                "concat_manual",
                "Unisci episodi - Gruppi manuali",
                """
                <p>Usa questa modalità quando vuoi decidere tu i gruppi in modo preciso.</p>
                <ol>
                  <li>Seleziona <b>Modalità = Gruppi manuali</b>.</li>
                  <li>Assegna i file ai gruppi desiderati.</li>
                  <li>Prepara l'anteprima.</li>
                  <li>Controlla bene il risultato previsto.</li>
                  <li>Premi <b>Unisci</b>.</li>
                </ol>

                <p>È la scelta giusta quando i nomi episodio sono strani, l'ordine non è pulito,
                oppure vuoi accorpare i file in modo non standard.</p>
                """
            ),
            (
                "trim",
                "Tool Trim",
                """
                <p><b>Trim</b> serve a tagliare una porzione precisa del file sorgente e creare un nuovo file.</p>

                <p>Il tool ora è <b>autonomo</b>:</p>
                <ul>
                  <li>si può aprire anche senza file selezionato nella GUI principale</li>
                  <li>ha un pulsante <b>Apri…</b> per scegliere il file direttamente dal dialog</li>
                </ul>

                <p>Comportamento attuale importante:</p>
                <ul>
                  <li>la finestra è <b>ridimensionabile</b></li>
                  <li>la dimensione viene <b>ricordata</b> al riavvio</li>
                  <li>ha dimensione minima circa <b>700x800</b></li>
                  <li>la cartella output all'avvio è <b>vuota</b></li>
                  <li>il campo output ha il <b>clear button</b></li>
                  <li><b>Apri cartella output</b> mostra un avviso se il campo output è vuoto</li>
                  <li>il pulsante <b>Info</b> apre una mini-finestra tipo <b>MediaInfo</b> del file sorgente</li>
                </ul>

                <p>Uso consigliato:</p>
                <ol>
                  <li>Apri il tool Trim.</li>
                  <li>Se necessario premi <b>Apri…</b> e scegli il file sorgente.</li>
                  <li>Imposta la porzione da mantenere.</li>
                  <li>Scegli la cartella output.</li>
                  <li>Controlla le informazioni del file con <b>Info</b> se hai dubbi.</li>
                  <li>Lancia il trim.</li>
                </ol>

                <div class="note">
                Se la cartella output è vuota, prima impostala: il pulsante per aprirla non può fare miracoli.
                </div>
                """
            ),
            (
                "insert_clip",
                "Tool Insert Clip",
                """
                <p><b>Insert Clip</b> serve a inserire una clip dentro un file principale
                producendo un risultato locale coerente e verificabile.</p>

                <p>Anche questo tool ora è <b>autonomo</b>:</p>
                <ul>
                  <li>si apre anche senza file già selezionato nella GUI principale</li>
                  <li>permette di scegliere il file direttamente dal dialog con <b>Apri…</b></li>
                </ul>

                <p>Comportamento attuale importante:</p>
                <ul>
                  <li>player sistemato</li>
                  <li>preview clip funzionante</li>
                  <li>preview del risultato locale funzionante</li>
                  <li>fix <b>SAR/DAR</b> riuscito: la clip inserita non deve risultare schiacciata</li>
                  <li>cartella output inizialmente <b>vuota</b></li>
                  <li>campo output con <b>clear button</b></li>
                  <li><b>Apri cartella output</b> con avviso se il campo è vuoto</li>
                  <li>pulsante <b>Info</b> con finestra tipo mini-MediaInfo del file sorgente</li>
                </ul>

                <p>Modalità audio disponibili:</p>
                <ul>
                  <li><b>Contesto vicino</b></li>
                  <li><b>Media film</b></li>
                </ul>

                <p>Uso consigliato:</p>
                <ol>
                  <li>Apri Insert Clip.</li>
                  <li>Carica o conferma il file principale.</li>
                  <li>Carica la clip da inserire.</li>
                  <li>Definisci il punto o l'intervallo di inserimento previsto dal tool.</li>
                  <li>Scegli la modalità audio desiderata.</li>
                  <li>Controlla la preview della clip e poi la preview del risultato locale.</li>
                  <li>Imposta la cartella output.</li>
                  <li>Lancia la creazione del risultato finale.</li>
                </ol>

                <div class="note">
                Se il risultato ti sembra strano, controlla prima la preview locale: serve proprio a evitare errori stupidi
                su sync, aspect ratio o posizione dell'inserimento.
                </div>
                """
            ),
            (
                "info_output",
                "Info file e cartella output",
                """
                <p>Nei tool che lo prevedono:</p>
                <ul>
                  <li>il pulsante <b>Info</b> apre una finestra rapida con le informazioni del file sorgente</li>
                  <li>la cartella output può partire vuota</li>
                  <li>il relativo campo testo può essere pulito rapidamente col <b>clear button</b></li>
                  <li>se premi <b>Apri cartella output</b> con campo vuoto, compare un messaggio di avviso</li>
                </ul>

                <p><b>Regola semplice:</b> prima scegli dove salvare, poi prova ad aprire la cartella.</p>
                """
            ),
            (
                "view_menu",
                "Menu Visualizza",
                """
                <p>Il menu <b>Visualizza</b> non elabora file: serve solo a cambiare come vedi la GUI.</p>
                <ul>
                  <li>mostra o nasconde la toolbar</li>
                  <li>aiuta a ripristinare un layout leggibile</li>
                  <li>permette di andare rapidamente a certe schede o aree della suite, se previsto</li>
                </ul>
                """
            ),
            (
                "common",
                "Problemi comuni",
                """
                <ul>
                  <li><b>Il tool si apre ma non c'è un file caricato:</b> usa il pulsante <b>Apri…</b> dentro il dialog.</li>
                  <li><b>Non si apre la cartella output:</b> probabilmente il campo output è vuoto.</li>
                  <li><b>La clip inserita sembra deformata:</b> ricontrolla la preview locale; il fix SAR/DAR è pensato proprio per evitare questo problema.</li>
                  <li><b>Non sai cosa uscirà:</b> guarda prima preview, info file e log.</li>
                  <li><b>Dubbi tra tagliare e inserire:</b> usa <b>Trim</b> per togliere o isolare una porzione; usa <b>Insert Clip</b> per mettere una clip dentro un altro file.</li>
                </ul>
                """
            ),
            (
                "pdf",
                "Stampa o salva in PDF",
                """
                <p>Puoi usare i pulsanti in basso:</p>
                <ul>
                  <li><b>Stampa…</b> apre il dialog di stampa del sistema</li>
                  <li><b>Esporta PDF…</b> salva direttamente questo manuale in un file PDF</li>
                </ul>
                """
            ),
        ]

    def _sections_en(self):
        return [
            (
                "intro",
                "What MKV Tools Suite is",
                """
                <p><b>MKV Tools Suite</b> is a collection of tools to work on MKV files in a practical way,
                trying to avoid unnecessary re-encoding whenever possible.</p>

                <p>Depending on the tool, the suite can:</p>
                <ul>
                  <li>inspect and select video, audio and subtitle tracks</li>
                  <li>create a new MKV with the desired tracks</li>
                  <li>extract tracks or chapters</li>
                  <li>apply tags and chapters</li>
                  <li>merge episodes</li>
                  <li>trim an exact portion of an already prepared file</li>
                  <li>insert a clip into a main file while keeping the result as coherent as possible</li>
                </ul>
                """
            ),
            (
                "where_tools",
                "Where to find the tools",
                """
                <p>In the main suite window, <b>Trim</b> and <b>Insert Clip</b> are available from the
                <b>toolbar</b> and the <b>menubar</b>.</p>

                <p>The old side buttons for Trim and Insert Clip have been removed.</p>

                <p><b>Important:</b> both tools stay available even when the main file list is empty.</p>
                """
            ),
            (
                "workflow",
                "Quick usage",
                """
                <ol>
                  <li><b>Open the correct tool</b> from the main window.</li>
                  <li><b>Select the file</b> in the main GUI or directly inside the tool dialog.</li>
                  <li><b>Check</b> tracks, chapters, preview or file information.</li>
                  <li><b>Choose the output folder</b> if needed.</li>
                  <li><b>Run the operation</b> and check the log or the created file.</li>
                </ol>
                """
            ),
            (
                "tracks",
                "Tracks tab",
                """
                <p>The <b>Tracks</b> tab shows video, audio and subtitle tracks found in the file.</p>
                <ul>
                  <li>you can choose which tracks to include</li>
                  <li>you can inspect language, name and some flags</li>
                  <li>you can prepare a new MKV with only what you need</li>
                </ul>
                """
            ),
            (
                "chapters",
                "Chapters tab",
                """
                <p>The <b>Chapters</b> tab lets you manage chapter data.</p>
                <ul>
                  <li>if embedded chapters already exist, the suite reports them</li>
                  <li>you can use an external chapters file</li>
                  <li>you can generate chapters where supported by the workflow</li>
                </ul>
                """
            ),
            (
                "remux",
                "Remux",
                """
                <p><b>Remux</b> creates a new MKV using the selected tracks, chapters and tags.</p>

                <p>Use it when you want to:</p>
                <ul>
                  <li>keep only some tracks</li>
                  <li>change names, languages or flags</li>
                  <li>add or replace chapters</li>
                  <li>produce a clean new MKV without touching the original file</li>
                </ul>
                """
            ),
            (
                "tags",
                "Apply Tags",
                """
                <p><b>Apply Tags</b> writes tags according to the current workflow.</p>

                <p>If you want a brand new output file without touching the original one,
                you usually want <b>Remux</b> instead.</p>
                """
            ),
            (
                "concat_auto",
                "Merge Episodes - Automatic",
                """
                <p>Use this mode when files are already ordered and coherent.</p>
                <ol>
                  <li>Add the files.</li>
                  <li>Keep <b>Mode = Automatic</b>.</li>
                  <li>Set how many episodes must go into each output file.</li>
                  <li>Prepare the preview.</li>
                  <li>Check names and groups.</li>
                  <li>Press <b>Merge</b>.</li>
                </ol>
                """
            ),
            (
                "concat_manual",
                "Merge Episodes - Manual groups",
                """
                <p>Use this mode when you want full control over grouping.</p>
                <ol>
                  <li>Select <b>Mode = Manual groups</b>.</li>
                  <li>Assign files to the desired groups.</li>
                  <li>Prepare the preview.</li>
                  <li>Check the planned result carefully.</li>
                  <li>Press <b>Merge</b>.</li>
                </ol>
                """
            ),
            (
                "trim",
                "Trim tool",
                """
                <p><b>Trim</b> is used to cut an exact portion of the source file and create a new output file.</p>

                <p>The tool is now <b>standalone</b>:</p>
                <ul>
                  <li>it can open even if no file is selected in the main GUI</li>
                  <li>it provides an <b>Open…</b> button to choose the source file directly inside the dialog</li>
                </ul>

                <p>Current important behavior:</p>
                <ul>
                  <li>the window is <b>resizable</b></li>
                  <li>its size is <b>persistent</b> between runs</li>
                  <li>minimum size is about <b>700x800</b></li>
                  <li>the output folder is initially <b>empty</b></li>
                  <li>the output textbox has an active <b>clear button</b></li>
                  <li><b>Open output folder</b> shows a warning if the output field is empty</li>
                  <li>the <b>Info</b> button opens a quick mini-<b>MediaInfo</b>-style dialog for the source file</li>
                </ul>
                """
            ),
            (
                "insert_clip",
                "Insert Clip tool",
                """
                <p><b>Insert Clip</b> inserts a clip into a main file and lets you verify the local result before final output.</p>

                <p>This tool is also <b>standalone</b>:</p>
                <ul>
                  <li>it can open even without a file already selected in the main GUI</li>
                  <li>you can choose the file directly from the dialog with <b>Open…</b></li>
                </ul>

                <p>Current important behavior:</p>
                <ul>
                  <li>player fixed</li>
                  <li>clip preview working</li>
                  <li>local result preview working</li>
                  <li><b>SAR/DAR</b> fix applied, so the inserted clip should no longer look squashed</li>
                  <li>output folder initially <b>empty</b></li>
                  <li>output textbox with <b>clear button</b></li>
                  <li><b>Open output folder</b> warns if the field is empty</li>
                  <li><b>Info</b> opens a mini-MediaInfo-style window for the source file</li>
                </ul>

                <p>Available audio modes:</p>
                <ul>
                  <li><b>Near context</b></li>
                  <li><b>Movie average</b></li>
                </ul>
                """
            ),
            (
                "info_output",
                "File info and output folder",
                """
                <p>In the tools that support it:</p>
                <ul>
                  <li>the <b>Info</b> button opens a quick source-file information window</li>
                  <li>the output folder may start empty</li>
                  <li>the textbox can be cleared quickly with the built-in <b>clear button</b></li>
                  <li>if you press <b>Open output folder</b> while the field is empty, a warning is shown</li>
                </ul>
                """
            ),
            (
                "view_menu",
                "View menu",
                """
                <p>The <b>View</b> menu does not process files. It only changes how the GUI is displayed.</p>
                <ul>
                  <li>show or hide the toolbar</li>
                  <li>restore a readable layout</li>
                  <li>jump quickly to supported tabs or areas</li>
                </ul>
                """
            ),
            (
                "common",
                "Common issues",
                """
                <ul>
                  <li><b>The tool opens but no file is loaded:</b> use the internal <b>Open…</b> button.</li>
                  <li><b>The output folder does not open:</b> the output field is probably empty.</li>
                  <li><b>The inserted clip looks deformed:</b> check the local preview first; that is exactly what the SAR/DAR fix and preview are for.</li>
                  <li><b>You do not know what will be created:</b> check preview, file info and log before running the final operation.</li>
                  <li><b>Not sure whether to trim or insert:</b> use <b>Trim</b> to keep/remove a portion, use <b>Insert Clip</b> to place one clip inside another file.</li>
                </ul>
                """
            ),
            (
                "pdf",
                "Print or export PDF",
                """
                <p>You can use the buttons below:</p>
                <ul>
                  <li><b>Print…</b> opens the system print dialog</li>
                  <li><b>Export PDF…</b> saves this manual directly to a PDF file</li>
                </ul>
                """
            ),
        ]

    def _manual_html(self) -> str:
        title = escape("MKV Tools Suite - User manual" if self._lang_pref() == "en" else "MKV Tools Suite - Manuale utente")

        parts = ["""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
body {
  font-family: sans-serif;
  font-size: 11pt;
  line-height: 1.38;
  color: #222;
  margin: 14px;
}
h1 {
  font-size: 18pt;
  margin: 0 0 8px 0;
}
h2 {
  font-size: 13pt;
  margin-top: 18px;
  margin-bottom: 6px;
  padding: 6px 8px;
  border-left: 4px solid #4a89dc;
  background: #f3f7ff;
}
p, li {
  margin-top: 4px;
  margin-bottom: 4px;
}
.note {
  border: 1px solid #e2c28a;
  background: #fff8e8;
  padding: 8px 10px;
  border-radius: 6px;
  margin-top: 8px;
}
small.muted {
  color: #666;
}
a {
  text-decoration: none;
}
</style>
</head>
<body>
"""]

        parts.append(f"<h1>{title}</h1>")

        sub = (
            "Quick internal guide. Simple wording, practical use."
            if self._lang_pref() == "en"
            else "Guida interna rapida. Testi semplici, uso pratico."
        )
        parts.append(f"<p><small class='muted'>{escape(sub)}</small></p>")

        idx = "Index" if self._lang_pref() == "en" else "Indice"
        back = "Back to index" if self._lang_pref() == "en" else "Torna all’indice"

        parts.append(f"<h2 id='index'>{escape(idx)}</h2><ul>")
        for anchor, section_title, _html in self._sections:
            parts.append(f"<li><a href='#{escape(anchor)}'>{escape(section_title)}</a></li>")
        parts.append("</ul>")

        for anchor, section_title, html in self._sections:
            parts.append(f"<h2 id='{escape(anchor)}'>{escape(section_title)}</h2>")
            parts.append(html)
            parts.append(f"<p><small class='muted'><a href='#index'>{escape(back)}</a></small></p>")

        parts.append("</body></html>")
        return "".join(parts)

    # -------------------- ui --------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        top_txt = (
            "Internal mini manual for MKV Tools Suite (simple explanations + print/export PDF)."
            if self._lang_pref() == "en"
            else "Mini manuale interno di MKV Tools Suite (spiegazioni semplici + stampa/esporta PDF)."
        )
        self.lbl_info = QLabel(top_txt)
        self.lbl_info.setWordWrap(True)
        root.addWidget(self.lbl_info)

        self.splitter = QSplitter(Qt.Horizontal, self)

        self.list_sections = QListWidget(self)
        self.list_sections.setMinimumWidth(240)
        self.list_sections.setAlternatingRowColors(True)
        for anchor, title, _html in self._sections:
            item = QListWidgetItem(title)
            item.setData(Qt.UserRole, anchor)
            self.list_sections.addItem(item)
        self.splitter.addWidget(self.list_sections)

        self.browser = QTextBrowser(self)
        self.browser.setOpenExternalLinks(False)
        self.browser.setOpenLinks(True)
        self.splitter.addWidget(self.browser)

        try:
            self.splitter.setStretchFactor(0, 0)
            self.splitter.setStretchFactor(1, 1)
            self.splitter.setSizes([280, 640])
        except Exception:
            pass

        root.addWidget(self.splitter, 1)

        btns = QHBoxLayout()
        btns.setSpacing(6)

        self.btn_print = QPushButton("Print…" if self._lang_pref() == "en" else "Stampa…")
        self.btn_pdf = QPushButton("Export PDF…" if self._lang_pref() == "en" else "Esporta PDF…")
        self.btn_close = QPushButton("Close" if self._lang_pref() == "en" else "Chiudi")

        self.btn_print.setToolTip(
            "Open the print dialog (you can also use a system PDF printer)."
            if self._lang_pref() == "en"
            else "Apre il dialog di stampa (puoi usare anche una stampante PDF di sistema)."
        )
        self.btn_pdf.setToolTip(
            "Save the manual directly to a PDF file."
            if self._lang_pref() == "en"
            else "Salva direttamente il manuale in un file PDF."
        )
        self.btn_close.setToolTip(
            "Close the mini manual."
            if self._lang_pref() == "en"
            else "Chiude il mini manuale."
        )

        btns.addWidget(self.btn_print)
        btns.addWidget(self.btn_pdf)
        btns.addStretch(1)
        btns.addWidget(self.btn_close)
        root.addLayout(btns)

        self.list_sections.currentItemChanged.connect(self._on_section_changed)
        self.btn_print.clicked.connect(self.on_print)
        self.btn_pdf.clicked.connect(self.on_export_pdf)
        self.btn_close.clicked.connect(self.close)

    def _load_manual(self):
        self.browser.setHtml(LT(self._manual_html()))

    def _select_first_section(self):
        if self.list_sections.count() > 0:
            self.list_sections.setCurrentRow(0)

    def _on_section_changed(self, current, _previous):
        if current is None:
            return
        anchor = current.data(Qt.UserRole)
        if anchor:
            try:
                self.browser.scrollToAnchor(str(anchor))
            except Exception:
                pass

    # -------------------- print / pdf --------------------

    def on_print(self):
        try:
            printer = QPrinter(QPrinter.HighResolution)
            dlg = QPrintDialog(printer, self)
            dlg.setWindowTitle("Print manual" if self._lang_pref() == "en" else "Stampa manuale")
            if dlg.exec_() == QDialog.Accepted:
                self.browser.document().print_(printer)
        except Exception as e:
            QMessageBox.warning(
                self,
                "Error" if self._lang_pref() == "en" else "Errore",
                (
                    "Printing is not available: {e}"
                    if self._lang_pref() == "en"
                    else "Stampa non disponibile: {e}"
                ).format(e=str(e))
            )

    def on_export_pdf(self):
        try:
            default_name = "mkv_tools_suite_user_manual.pdf" if self._lang_pref() == "en" else "mkv_tools_suite_manuale_utente.pdf"
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Export PDF" if self._lang_pref() == "en" else "Esporta PDF",
                default_name,
                "PDF (*.pdf)"
            )
            if not path:
                return
            if not path.lower().endswith(".pdf"):
                path += ".pdf"

            printer = QPrinter(QPrinter.HighResolution)
            printer.setOutputFormat(QPrinter.PdfFormat)
            printer.setOutputFileName(path)
            self.browser.document().print_(printer)

            QMessageBox.information(
                self,
                "Export PDF" if self._lang_pref() == "en" else "Esporta PDF",
                (
                    "Manual saved as PDF:\\n{path}"
                    if self._lang_pref() == "en"
                    else "Manuale salvato in PDF:\\n{path}"
                ).format(path=path)
            )
        except Exception as e:
            QMessageBox.warning(
                self,
                "Error" if self._lang_pref() == "en" else "Errore",
                (
                    "PDF export failed: {e}"
                    if self._lang_pref() == "en"
                    else "Esportazione PDF non riuscita: {e}"
                ).format(e=str(e))
            )
