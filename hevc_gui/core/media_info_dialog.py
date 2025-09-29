# -*- coding: utf-8 -*-
"""
Costanti e dizionari condivisi dall’interfaccia HEVC-GUI
"""

from html import escape
from PyQt5.QtGui import QTextDocument
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QHBoxLayout, QPushButton
from PyQt5.QtPrintSupport import QPrinter, QPrintPreviewDialog

import subprocess
import json
from pathlib import Path
import datetime
from datetime import date

# ========================================================================


class MediaInfoDialog(QDialog):
    def __init__(self, filepath, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Info File di Input")
        self.resize(700, 600)

        vbox = QVBoxLayout(self)
        self.txt = QTextEdit(self)
        self.txt.setReadOnly(False)
        vbox.addWidget(self.txt)

        hbtn = QHBoxLayout()
        hbtn.addStretch()
        btn_print = QPushButton("Print", self)
        btn_close = QPushButton("Close", self)
        hbtn.addWidget(btn_print)
        hbtn.addWidget(btn_close)
        vbox.addLayout(hbtn)

        btn_print.clicked.connect(self.on_print)
        btn_close.clicked.connect(self.accept)

        info = self._gather_info(Path(filepath))
        self.txt.setPlainText(info)

    def _gather_info(self, path: Path) -> str:
        """
        Esegue mediainfo --Output=JSON su `path` e restituisce un testo
        strutturato identico al tuo screenshot, con sezioni:
         - Generale
         - Video
         - Audio
         - Sottotitoli
         - Capitoli
         + ASPECT (ffprobe) aggiuntivo all’inizio (Storage/SAR/DAR/PixFmt)
        """
        # 1) invoca mediainfo in JSON
        cmd = ["mediainfo", "--Output=JSON", str(path)]
        data = subprocess.check_output(cmd, text=True)
        js = json.loads(data)
        tracks = js["media"]["track"]

        lines = []
        # Titolo File di Input
        lines.append("Info File di Input:\n")
        lines.append(f"Titolo: {path.name}")

        # ── ASPECT (ffprobe) ────────────────────────────────────────────────
        # Mostra i dati "veri" da ffprobe: Storage (WxH), SAR, DAR, PixFmt
        # Import dentro al metodo per evitare dipendenze circolari.
        try:
            from hevc_gui.core.aspect import probe_aspect

            info = probe_aspect(str(path))
            lines.append("ASPECT (ffprobe)")
            lines.append(f"Storage: {info.w}x{info.h}")
            lines.append(f"SAR: {info.sar}")
            lines.append(f"DAR: {info.dar or 'n/d'}")
            lines.append(f"PixFmt: {info.pix_fmt}")
            lines.append("")
        except Exception:
            # Non blocchiamo il dialog se ffprobe non è disponibile o fallisce
            pass

        # ── GENERAL ─────────────────────────────────────────────────────────
        general = next(t for t in tracks if t["@type"] == "General")
        lines.append("Generale")
        for key, label in [
            ("Format", "Format"),
            ("Format_Version", "Format Version"),
            ("FileSize", "FileSize"),
            ("Duration", "Duration"),
            ("OverallBitRate", "OverallBitRate"),
            ("FrameRate", "FrameRate"),
            ("StreamSize", "StreamSize"),
        ]:
            if key in general:
                val = general[key]
                # unit conversion
                if key == "FileSize":
                    b = int(val)
                    val = f"{b / 1024 / 1024 / 1024:.2f} GB"
                elif key == "Duration":
                    sec = float(val)
                    hhmmss = str(datetime.timedelta(seconds=int(sec)))
                    val = hhmmss
                elif key == "OverallBitRate":
                    b = int(val)
                    val = f"{b / 1000:.2f} kbps"
                lines.append(f"{label}: {val}")
        lines.append("")

        # ── VIDEO ────────────────────────────────────────────────────────────
        for v in [t for t in tracks if t["@type"] == "Video"]:
            lines.append("Video")
            for key, label in [
                ("ID", "ID"),
                ("Format", "Format"),
                ("Format_Profile", "Format Profile"),
                ("CodecID", "CodecID"),
                ("Duration", "Duration"),
                ("BitRate", "BitRate"),
                ("Width", "Width"),
                ("Height", "Height"),
                ("DisplayAspectRatio", "DisplayAspectRatio"),
                ("FrameRate_Mode", "FrameRate Mode"),
                ("FrameRate", "FrameRate"),
                ("ColorSpace", "ColorSpace"),
                ("ChromaSubsampling", "ChromaSubsampling"),
                ("BitDepth", "BitDepth"),
                ("StreamSize", "StreamSize"),
                ("Default", "Default"),
                ("Forced", "Forced"),
            ]:
                if key in v:
                    val = v[key]
                    if key == "Duration":
                        val = val.split(".")[0]
                    elif key == "BitRate":
                        b = int(val)
                        val = f"{b / 1000:.0f} kbps"
                    elif key == "StreamSize":
                        try:
                            b = int(val)
                            val = f"{b / 1024 / 1024:.2f} MB"
                        except Exception:
                            pass
                    elif key in ("Default", "Forced"):
                        val = "Yes" if str(val).lower() in ("yes", "1", "true") else "No"
                    lines.append(f"{label}: {val}")
            lines.append("")

        # ── AUDIO ────────────────────────────────────────────────────────────
        for a in [t for t in tracks if t["@type"] == "Audio"]:
            lines.append("Audio")
            for key, label in [
                ("ID", "ID"),
                ("Format", "Format"),
                ("CodecID", "CodecID"),
                ("Duration", "Duration"),
                ("BitRate", "BitRate"),
                ("ChannelLayout", "ChannelLayout"),
                ("SamplingRate", "SamplingRate"),
                ("FrameRate", "FrameRate"),
                ("Compression_Mode", "Compression Mode"),
                ("StreamSize", "StreamSize"),
                ("Title", "Title"),
                ("Language", "Language"),
                ("Default", "Default"),
                ("Forced", "Forced"),
            ]:
                if key in a:
                    val = a[key]
                    if key == "Duration":
                        val = val.split(".")[0]
                    elif key == "BitRate":
                        b = int(val)
                        val = f"{b / 1000:.0f} kbps"
                    elif key == "StreamSize":
                        try:
                            b = int(val)
                            val = f"{b / 1024 / 1024:.2f} MB"
                        except Exception:
                            pass
                    elif key in ("Default", "Forced"):
                        val = "Yes" if str(val).lower() in ("yes", "1", "true") else "No"
                    lines.append(f"{label}: {val}")
            lines.append("")

        # ── SOTTOTITOLI ──────────────────────────────────────────────────────
        for s in [t for t in tracks if t["@type"] == "Text"]:
            lines.append("Sottotitolo")
            for key, label in [
                ("ID", "ID"),
                ("Format", "Format"),
                ("CodecID", "CodecID"),
                ("Duration", "Duration"),
                ("BitRate", "BitRate"),
                ("FrameRate", "FrameRate"),
                ("StreamSize", "StreamSize"),
                ("Title", "Title"),
                ("Language", "Language"),
                ("Default", "Default"),
                ("Forced", "Forced"),
            ]:
                if key in s:
                    val = s[key]
                    if key in ("Default", "Forced"):
                        val = "Yes" if str(val).lower() in ("yes", "1", "true") else "No"
                    lines.append(f"{label}: {val}")
            lines.append("")

        # ── CAPITOLI ─────────────────────────────────────────────────────────
        for m in [t for t in tracks if t["@type"] == "Menu"]:
            lines.append("Capitoli")
            if "@type" in m:
                lines.append(f"@type: {m['@type']}")
            if "extra" in m:
                lines.append(f"extra: {m['extra']}")
            lines.append("")

        return "\n".join(lines)

    # ── STAMPA ─────────────────────────────────────────────────────────

    def on_print(self):
        printer = QPrinter(QPrinter.HighResolution)
        printer.setPageSize(QPrinter.A4)
        printer.setOrientation(QPrinter.Portrait)
        printer.setFullPage(False)

        preview = QPrintPreviewDialog(printer, self)
        preview.setWindowTitle("Print Preview")
        preview.paintRequested.connect(self._print_document)
        preview.exec_()

    def _print_document(self, printer: QPrinter):
        # 1) Prendo il testo dal QTextEdit
        plain = self.txt.toPlainText()

        # 2) Escape + <br>
        html_body = escape(plain).replace("\n", "<br>")

        # 3) Costruisco HTML con footer
        today = date.today().strftime("%d-%m-%Y")
        html = f"""
        <html>
         <head>
          <style>
            @page {{
              size: A4;
              margin: 2cm;
            }}
            body {{
              column-count: 2;
              column-gap: 1cm;
              margin: 0;
              font-family: monospace;
              font-size: 9pt;
            }}
            .header {{
              column-span: all;
              text-align: center;
              font-weight: bold;
              margin-bottom: 0.5cm;
            }}
            pre {{ white-space: pre-wrap; }}
            .footer {{
              column-span: all;
              text-align: center;
              margin-top: 1cm;
              font-size: 9pt;
            }}
          </style>
         </head>
         <body>
           <div class="header">
             HEVC – Video Converter • Ver. 2.0 • Report Mediainfo
           </div>
           <pre>{html_body}</pre>
           <div class="footer">
             —— Fine Report Mediainfo • Generato il {today} ——
           </div>
         </body>
        </html>
        """

        # 4) Creo e stampo il documento
        doc = QTextDocument()
        doc.setHtml(html)
        doc.print_(printer)
