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

try:
    from hevc_gui.i18n import L
except Exception:
    def L(s: str) -> str:
        return s


class UserManualDialog(QDialog):
    """
    Mini manuale interno MKV Suite (semplice e stampabile in PDF).
    Modulo esterno per non gonfiare embedded_app/main_widget.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(L("User manual"))
        try:
            self.setModal(False)
        except Exception:
            pass
        try:
            self.resize(880, 760)
            self.setMinimumSize(680, 520)
        except Exception:
            pass

        self._sections = self._build_sections()
        self._build_ui()
        self._load_manual()
        self._select_first_section()

    # -------------------- language / content --------------------

    def _lang_pref(self) -> str:
        # Preferisce HEVC_LANG se presente; fallback semplice.
        v = (os.environ.get("HEVC_LANG") or "").strip().lower()
        if v.startswith("en"):
            return "en"
        return "it"

    def _build_sections(self):
        lang = self._lang_pref()
        if lang == "en":
            return self._sections_en()
        return self._sections_it()

    def _sections_it(self):
        return [
            ("intro", L("Cos'è MKV Suite"), """
            <p><b>MKV Suite</b> ti aiuta a lavorare con file MKV senza ricodificare
            (quando non serve): estrazione, rimux, capitoli, tag e unione episodi.</p>
            <p><b>In parole semplici:</b> scegli un file, guardi cosa contiene, poi decidi
            se estrarre, rimuxare, unire episodi o sistemare capitoli/tag.</p>
            """),
            ("workflow", L("Uso rapido (3 passi)"), """
            <ol>
              <li><b>Apri un file MKV</b> (o più file, se usi <i>Unisci episodi</i>).</li>
              <li><b>Controlla Tracce / Capitoli / Tag</b>.</li>
              <li><b>Esegui l'azione</b>: Crea MKV, Estrai, Applica Tag, Unisci.</li>
            </ol>
            <p>Se non sei sicuro, guarda sempre prima l'<b>anteprima</b> e il <b>log</b>.</p>
            """),
            ("tracks", L("Scheda Tracce"), """
            <p>Qui vedi video, audio e sottotitoli presenti nel file.</p>
            <ul>
              <li>Puoi selezionare quali tracce usare.</li>
              <li>Puoi modificare alcuni nomi/tag delle tracce.</li>
              <li>Per i sottotitoli, se configurato, puoi aprire l'editor esterno.</li>
            </ul>
            <p><b>Consiglio:</b> se devi solo cambiare nomi/lingue/flag, controlla bene prima di rimuxare.</p>
            """),
            ("chapters", L("Scheda Capitoli"), """
            <p>Qui gestisci i capitoli del video.</p>
            <ul>
              <li>Se il video ha già capitoli embedded, la schermata lo segnala e mostra quanti sono.</li>
              <li>Puoi usare un <b>file capitoli esterno</b> (es. .xml / .txt).</li>
              <li>Oppure puoi <b>generare</b> capitoli automaticamente.</li>
            </ul>
            <p><b>Importante:</b> la scritta dei capitoli nel video è solo informativa; non modifica nulla da sola.</p>
            """),
            ("concat_auto", L("Unisci episodi - Automatico"), """
            <p>Usa questa modalità quando i file hanno tag/nomi coerenti (episodi ordinati bene).</p>
            <ol>
              <li>Aggiungi i file MKV.</li>
              <li>Lascia <b>Modalità = Automatico</b>.</li>
              <li>Imposta <b>Quante puntate per file</b> (es. 2).</li>
              <li>Scrivi il <b>Nome serie / prefisso</b>.</li>
              <li>Premi <b>Prepara anteprima</b>.</li>
              <li>Controlla i nomi output e poi premi <b>Unisci</b>.</li>
            </ol>
            <p>Esempio: con 7 episodi e valore 2 → crea gruppi 1+2, 3+4, 5+6, 7.</p>
            """),
            ("concat_manual", L("Unisci episodi - Gruppi manuali"), """
            <p>Usa questa modalità se vuoi decidere tu i gruppi (es. 1+2 ; 3+4 ; 5+6+7).</p>
            <ol>
              <li>Imposta <b>Modalità = Gruppi manuali</b>.</li>
              <li>Assegna i gruppi nella tabella (seguendo l'ordine originale).</li>
              <li>Scrivi il <b>Nome serie / prefisso</b>.</li>
              <li>Premi <b>Prepara anteprima</b>.</li>
              <li>Controlla l'anteprima e poi <b>Unisci</b>.</li>
            </ol>
            <p><b>Regola pratica:</b> se l'automatico ti avvisa di tag incoerenti, passa al manuale.</p>
            """),
            ("remux", L("Crea MKV"), """
            <p><b>Crea MKV</b> crea un nuovo MKV con le tracce/capitoli/tag scelti,
            senza ricodificare il video (salvo casi speciali fuori da questa schermata).</p>
            <p>È la scelta giusta quando vuoi:</p>
            <ul>
              <li>tenere solo alcune tracce</li>
              <li>cambiare nomi/lingue/flag tracce</li>
              <li>aggiungere/sostituire capitoli</li>
              <li>usare sottotitoli esterni modificati</li>
            </ul>
            """),
            ("tags", L("Applica Tag"), """
            <p><b>Applica Tag</b> scrive i tag nel <b>file originale</b> (se previsto dal flusso corrente).</p>
            <p>Se invece vuoi creare un file nuovo senza toccare l'originale, usa <b>Crea MKV</b>.</p>
            <p><b>Promemoria semplice:</b> Premi “Applica Tag” per scrivere nel file originale, oppure “Crea MKV” per creare un nuovo file.</p>
            """),
            ("view_menu", L("Menu Visualizza"), """
            <p>Il menu <b>Visualizza</b> serve a cambiare <i>come vedi</i> la schermata, non a elaborare file.</p>
            <ul>
              <li><b>Barra strumenti</b>: mostra/nasconde la toolbar.</li>
              <li><b>Ripristina layout</b>: rimette gli splitter in posizione leggibile.</li>
              <li><b>Vai alla scheda</b>: scorciatoia per Tracce / Capitoli / Unisci episodi.</li>
            </ul>
            """),
            ("common", L("Problemi comuni"), """
            <ul>
              <li><b>La finestra è troppo stretta/larga:</b> ridimensionala e usa “Visualizza → Ripristina layout”.</li>
              <li><b>Non parte un editor esterno sottotitoli:</b> verifica che sia installato nel sistema.</li>
              <li><b>Capitoli assenti:</b> usa un file capitoli esterno oppure genera i capitoli.</li>
              <li><b>Dubbi su cosa verrà creato:</b> controlla sempre anteprima + log prima di lanciare.</li>
            </ul>
            """),
            ("pdf", L("Stampa o salva in PDF"), """
            <p>Puoi usare i pulsanti in basso:</p>
            <ul>
              <li><b>Stampa…</b> → apre il dialog di stampa (puoi scegliere anche stampante PDF di sistema).</li>
              <li><b>Esporta PDF…</b> → salva direttamente questo manuale in un file .pdf.</li>
            </ul>
            """),
        ]

    def _sections_en(self):
        return [
            ("intro", L("What MKV Suite is"), """
            <p><b>MKV Suite</b> helps you work with MKV files without re-encoding
            (when not needed): extraction, remux, chapters, tags and episode merging.</p>
            """),
            ("workflow", L("Quick usage (3 steps)"), """
            <ol>
              <li>Open an MKV file (or more files for episode merge).</li>
              <li>Check Tracks / Chapters / Tags.</li>
              <li>Run the action: Remux, Extract, Apply Tags, Merge.</li>
            </ol>
            """),
            ("tracks", L("Tracks tab"), "<p>View and choose video/audio/subtitle tracks.</p>"),
            ("chapters", L("Chapters tab"), "<p>Check embedded chapters, use an external chapters file, or generate chapters.</p>"),
            ("concat_auto", L("Merge episodes - Automatic"), "<p>Use when episode tags/order are consistent.</p>"),
            ("concat_manual", L("Merge episodes - Manual groups"), "<p>Use when you want to decide groups manually (e.g. 1+2; 3+4; 5+6+7).</p>"),
            ("remux", L("Crea MKV"), "<p>Create a new MKV with selected tracks/chapters/tags, normally without re-encoding video.</p>"),
            ("tags", L("Apply Tags"), "<p>Writes tags to the original file (current workflow).</p>"),
            ("view_menu", L("View menu"), "<p>Changes how the interface is displayed (layout/toolbar/tabs), not file processing.</p>"),
            ("common", L("Common issues"), "<p>Check preview and log first when in doubt.</p>"),
            ("pdf", L("Print or export PDF"), "<p>Use the buttons below to print or save this manual as PDF.</p>"),
        ]

    def _manual_html(self) -> str:
        title = escape(L("MKV Suite - User manual"))
        parts = ["""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
body {
  font-family: sans-serif;
  font-size: 11pt;
  line-height: 1.35;
  color: #222;
  margin: 14px;
}
h1 { font-size: 18pt; margin: 0 0 8px 0; }
h2 {
  font-size: 13pt;
  margin-top: 18px;
  margin-bottom: 6px;
  padding: 6px 8px;
  border-left: 4px solid #4a89dc;
  background: #f3f7ff;
}
p, li { margin-top: 4px; margin-bottom: 4px; }
.code {
  font-family: monospace;
  background: #f1f1f1;
  border: 1px solid #ddd;
  padding: 6px;
  border-radius: 4px;
}
.note {
  border: 1px solid #e2c28a;
  background: #fff8e8;
  padding: 8px 10px;
  border-radius: 6px;
  margin-top: 8px;
}
small.muted { color: #666; }
</style>
</head>
<body>
"""]
        parts.append(f"<h1>{title}</h1>")
        parts.append(f"<p><small class='muted'>{escape(L('Guida rapida interna. Testi semplici, esempi pratici.'))}</small></p>")

        # indice
        parts.append(f"<h2 id='index'>{escape(L('Indice'))}</h2><ul>")
        for anchor, section_title, _html in self._sections:
            parts.append(f"<li><a href='#{escape(anchor)}'>{escape(section_title)}</a></li>")
        parts.append("</ul>")

        # sezioni
        for anchor, section_title, html in self._sections:
            parts.append(f"<h2 id='{escape(anchor)}'>{escape(section_title)}</h2>")
            parts.append(html)
            parts.append(f"<p><small class='muted'><a href='#index'>{escape(L('Torna all’indice'))}</a></small></p>")

        parts.append("</body></html>")
        return "".join(parts)

    # -------------------- ui --------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        self.lbl_info = QLabel(
            L("Mini manuale interno di MKV Suite (spiegazioni semplici + stampa/esporta PDF).")
        )
        self.lbl_info.setWordWrap(True)
        root.addWidget(self.lbl_info)

        self.splitter = QSplitter(Qt.Horizontal, self)

        self.list_sections = QListWidget(self)
        self.list_sections.setMinimumWidth(220)
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
            self.splitter.setSizes([260, 620])
        except Exception:
            pass

        root.addWidget(self.splitter, 1)

        btns = QHBoxLayout()
        btns.setSpacing(6)

        self.btn_print = QPushButton(L("Stampa…"))
        self.btn_pdf = QPushButton(L("Esporta PDF…"))
        self.btn_close = QPushButton(L("Chiudi"))

        self.btn_print.setToolTip(L("Apre il dialog di stampa (puoi usare anche una stampante PDF di sistema)."))
        self.btn_pdf.setToolTip(L("Salva direttamente il manuale in un file PDF."))
        self.btn_close.setToolTip(L("Chiude il mini manuale."))

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
        self.browser.setHtml(self._manual_html())

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
            dlg.setWindowTitle(L("Stampa manuale"))
            if dlg.exec_() == QDialog.Accepted:
                self.browser.document().print_(printer)
        except Exception as e:
            QMessageBox.warning(self, L("Errore"), L("Stampa non disponibile: {e}").format(e=str(e)))

    def on_export_pdf(self):
        try:
            default_name = "mkv_suite_user_manual.pdf" if self._lang_pref() == "en" else "mkv_suite_manuale_utente.pdf"
            path, _ = QFileDialog.getSaveFileName(
                self,
                L("Esporta PDF"),
                default_name,
                L("PDF (*.pdf)")
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
                L("Esporta PDF"),
                L("Manuale salvato in PDF:\\n{path}").format(path=path)
            )
        except Exception as e:
            QMessageBox.warning(self, L("Errore"), L("Esportazione PDF non riuscita: {e}").format(e=str(e)))
