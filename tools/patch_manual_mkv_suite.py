#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
import re
from pathlib import Path
from datetime import datetime

VERSION = "2.2.0.0"
YEAR = "2026"

IT_MKV_SUITE_SECTION = f"""
    <section>
      </section><h2 id="mkv-suite">12. MKV Suite (Tools → “Strumenti MKV”)</h2>

      <p>
        <b>MKV Suite</b> è il modulo integrato per lavorare sui file MKV <b>senza ricodificare</b>:
        estrazione tracce, tagging, creazione MKV (remux) e unione episodi.
        Lo trovi in <b>Tools → Strumenti MKV</b>.
      </p>

      <div class="note">
        <b>Prerequisiti (obbligatori per usare bene MKV Suite):</b>
        <ul>
          <li><b>MKVToolNix</b> (servono i comandi <code>mkvmerge</code>, <code>mkvextract</code>, <code>mkvpropedit</code>).</li>
          <li><b>gnome-subtitles</b> (Linux) per ottenere una <b>modifica corretta dei sottotitoli</b> dall’editor integrato.</li>
        </ul>
        <pre>sudo apt install mkvtoolnix mkvtoolnix-gui gnome-subtitles</pre>
      </div>

      <h3>12.1 Regola d’oro: cartella output = “job dir”</h3>
      <ul>
        <li>MKV Suite <b>non</b> usa una cartella di default: alla prima operazione ti chiede dove salvare.</li>
        <li>La cartella che scegli diventa la <b>cartella di lavoro</b> (job dir) e dentro crea automaticamente queste sottocartelle:</li>
      </ul>
      <pre>JOB_DIR/
  extract/
  chapters/
  remux/</pre>
      <div class="warn">
        <b>Consiglio da “dummy”:</b> usa una cartella output <b>vuota</b> per ogni film/episodi.
        Se riusi sempre la stessa, ti ritrovi i file mescolati e poi non capisci più niente.
      </div>

      <h3>12.2 Workflow “a prova di imbecille” (ordine consigliato)</h3>
      <ol>
        <li>Apri <b>Tools → Strumenti MKV</b>.</li>
        <li>Imposta la <b>cartella output</b> (job dir).</li>
        <li>Aggiungi una sorgente MKV (o più episodi) nella lista a sinistra.</li>
        <li>Vai su <b>Tracce</b> e controlla lingue/flag/nome tracce.</li>
        <li>Usa una funzione alla volta: <b>Estrai</b> oppure <b>Applica Tag</b> oppure <b>Crea MKV</b> oppure <b>Unisci episodi</b>.</li>
        <li>Se tocchi capitoli o sottotitoli: fai prima <b>Estrai</b>, poi modifica, poi <b>Crea MKV</b>.</li>
      </ol>

      <h3>12.3 Estrai</h3>
      <ul>
        <li>Estrae tracce selezionate e/o info dal MKV <b>senza conversioni</b>.</li>
        <li>Output in <code>extract/</code>.</li>
        <li>Video: viene estratto come MKV con suffisso <code>_e.mkv</code>.</li>
        <li>Audio/Sottotitoli: vengono estratti nel loro formato “naturale” con suffisso <code>_e</code> nel nome file.</li>
      </ul>

      <h3>12.4 Applica Tag</h3>
      <ul>
        <li>Serve per impostare <b>lingua</b>, <b>nome traccia</b>, flag <b>default/forced</b>, ecc. (quello che poi vedi bene anche in VLC).</li>
        <li>Non ricodifica: applica metadati/flag tramite tool di MKVToolNix.</li>
      </ul>
      <div class="warn">
        <b>Se vuoi zero rischi:</b> lavora su una copia del MKV (così non tocchi l’originale).
      </div>

      <h3>12.5 Crea MKV (Remux)</h3>
      <ul>
        <li>Crea un nuovo MKV riassemblando le tracce selezionate (<b>senza ricodificare</b>).</li>
        <li>Output in <code>remux/</code>.</li>
        <li>Capitoli: gestiscili dal tab <b>Capitoli</b> (i file capitoli <b>non</b> vanno aggiunti come “sorgenti”).</li>
        <li>Se usi capitoli esterni, MKV Suite evita duplicati (niente capitoli doppi).</li>
      </ul>

      <h3>12.6 Unisci episodi (Merge Episodes)</h3>
      <ul>
        <li>Seleziona più episodi e uniscili in un unico MKV (ordine = ordine lista).</li>
        <li>Output in <code>remux/</code>.</li>
        <li>È pensato per serie/mini-episodi: prima controlla sempre audio/lingue.</li>
      </ul>

      <h3>12.7 Capitoli (tab Capitoli)</h3>
      <ul>
        <li>Puoi <b>estrarre</b> capitoli esistenti oppure <b>generarli</b> (scene detect o intervallo fisso) e salvarli in <code>chapters/</code>.</li>
        <li>Per usarli nel remux: genera/salva → poi <b>Crea MKV</b> usando quei capitoli.</li>
      </ul>

      <h3>12.8 Editor sottotitoli (richiede gnome-subtitles)</h3>
      <ul>
        <li>Se vuoi correggere un SRT (sync, refusi, caratteri), installa <b>gnome-subtitles</b>.</li>
        <li>Flusso consigliato: <b>Estrai</b> sottotitolo → modifica in editor → <b>Crea MKV</b> includendo il SRT corretto.</li>
      </ul>

      <h3>12.9 Differenze IT / EN (nomi interfaccia)</h3>
      <table>
        <tr><th>Italiano</th><th>English</th></tr>
        <tr><td>Tools → <b>Strumenti MKV</b></td><td>Tools → <b>MKV Tools</b></td></tr>
        <tr><td><b>Crea MKV</b></td><td><b>Remux</b></td></tr>
        <tr><td><b>Unisci episodi</b></td><td><b>Merge Episodes</b></td></tr>
        <tr><td><b>Applica Tag</b></td><td><b>Apply Tags</b></td></tr>
        <tr><td><b>Estrai</b></td><td><b>Extract</b></td></tr>
      </table>
"""

EN_MKV_SUITE_SECTION = f"""
    <section>
      </section><h2 id="en-mkv-suite">7. MKV Suite (Tools → “MKV Tools”)</h2>

      <p>
        <b>MKV Suite</b> is the integrated module to work on MKV files <b>without re-encoding</b>:
        track extraction, tagging, remux, and episode merging.
        Open it from <b>Tools → MKV Tools</b>.
      </p>

      <div class="note">
        <b>Prerequisites (needed for MKV Suite):</b>
        <ul>
          <li><b>MKVToolNix</b> (CLI tools: <code>mkvmerge</code>, <code>mkvextract</code>, <code>mkvpropedit</code>).</li>
          <li><b>gnome-subtitles</b> (Linux) for reliable subtitle editing from the integrated editor workflow.</li>
        </ul>
        <pre>sudo apt install mkvtoolnix mkvtoolnix-gui gnome-subtitles</pre>
      </div>

      <h3>7.1 Key concept: output folder = “job dir”</h3>
      <pre>JOB_DIR/
  extract/
  chapters/
  remux/</pre>

      <h3>7.2 Beginner-proof workflow</h3>
      <ol>
        <li>Open <b>Tools → MKV Tools</b>.</li>
        <li>Pick an <b>output folder</b> (job dir).</li>
        <li>Add your MKV source(s) on the left.</li>
        <li>Check <b>Tracks</b> (languages/flags/names).</li>
        <li>Use one action at a time: <b>Extract</b> / <b>Apply Tags</b> / <b>Remux</b> / <b>Merge Episodes</b>.</li>
        <li>If you edit chapters/subtitles: Extract → edit → Remux.</li>
      </ol>

      <h3>7.3 Extract</h3>
      <ul>
        <li>No conversion: files keep their natural formats.</li>
        <li>Output goes to <code>extract/</code>.</li>
      </ul>

      <h3>7.4 Apply Tags</h3>
      <ul>
        <li>Set language, track name, default/forced flags, etc. (VLC-friendly naming).</li>
        <li>No re-encoding.</li>
      </ul>

      <h3>7.5 Remux</h3>
      <ul>
        <li>Create a new MKV by reassembling selected tracks (no re-encode).</li>
        <li>Output goes to <code>remux/</code>.</li>
        <li>Chapters are handled from the <b>Chapters</b> tab (don’t add chapter files as “sources”).</li>
      </ul>

      <h3>7.6 Merge Episodes</h3>
      <ul>
        <li>Merge multiple episodes into one MKV (order = left list order).</li>
        <li>Output goes to <code>remux/</code>.</li>
      </ul>

      <h3>7.7 Subtitle editor (requires gnome-subtitles)</h3>
      <ul>
        <li>Recommended: Extract → edit SRT → Remux with the fixed subtitles.</li>
      </ul>
"""

def sub_or_die(text: str, pattern: str, repl: str, *, count: int = 0, desc: str = "") -> str:
    new, n = re.subn(pattern, repl, text, count=count, flags=re.S)
    if n == 0:
        raise SystemExit(f"[FAIL] Pattern not found for: {desc or pattern}")
    return new

def insert_before_or_die(text: str, marker: str, insertion: str, *, desc: str = "") -> str:
    pos = text.find(marker)
    if pos < 0:
        raise SystemExit(f"[FAIL] Marker not found for insert: {desc or marker}")
    return text[:pos] + insertion + "\n\n" + text[pos:]

def insert_into_first_ul_after(text: str, heading_marker: str, li_block: str, *, desc: str = "") -> str:
    hpos = text.find(heading_marker)
    if hpos < 0:
        raise SystemExit(f"[FAIL] Heading marker not found: {desc or heading_marker}")
    ul_start = text.find("<ul>", hpos)
    ul_end = text.find("</ul>", ul_start)
    if ul_start < 0 or ul_end < 0:
        raise SystemExit(f"[FAIL] UL not found after heading: {desc or heading_marker}")
    return text[:ul_end] + li_block + text[ul_end:]

def replace_nav_and_setlang(text: str) -> str:
    # Replace nav block
    nav_start = text.find('<nav class="no-print">')
    if nav_start < 0:
        raise SystemExit("[FAIL] nav start not found")
    nav_end = text.find("</nav>", nav_start)
    if nav_end < 0:
        raise SystemExit("[FAIL] nav end not found")
    nav_end += len("</nav>")

    new_nav = """
  <nav id="nav-it" class="no-print">
    <a href="#introduzione">Introduzione</a>
    <a href="#requisiti">Requisiti</a>
    <a href="#installazione">Installazione</a>
    <a href="#interfaccia">Interfaccia</a>
    <a href="#uso">Come Usare</a>
    <a href="#ricette">Ricette pronte</a>
    <a href="#strumenti">Strumenti Video</a>
    <a href="#audio">Audio</a>
    <a href="#subs">Sottotitoli</a>
    <a href="#capitoli">Capitoli</a>
    <a href="#coda">Coda</a>
    <a href="#mkv-suite">MKV Suite</a>
    <a href="#ldvd">LDVD Ripper</a>
    <a href="#subtitle-edit">Subtitle Edit (fallback)</a>
    <a href="#troubleshoot">Problemi comuni</a>
    <a href="#faq">FAQ</a>
    <a href="#info">Info</a>
    <a href="#note-legali">Note Legali</a>
  </nav>

  <nav id="nav-en" class="no-print" style="display:none">
    <a href="#en-intro">Introduction</a>
    <a href="#en-req">Requirements</a>
    <a href="#en-install">Install &amp; Run</a>
    <a href="#en-ui">UI Overview</a>
    <a href="#en-encode">How to Encode</a>
    <a href="#en-recipes">Recipes</a>
    <a href="#en-mkv-suite">MKV Suite</a>
    <a href="#en-subs">Subtitles</a>
    <a href="#en-ldvd">LDVD Ripper</a>
    <a href="#en-subtitle-edit">Subtitle Edit</a>
    <a href="#en-troubleshoot">Troubleshooting</a>
    <a href="#en-info">Project Info</a>
  </nav>
""".strip("\n")

    text = text[:nav_start] + new_nav + text[nav_end:]

    # Replace setLang function to toggle nav too
    text = sub_or_die(
        text,
        r"function setLang\(which\)\{.*?\n\s*\}\s*<\/script>",
        """function setLang(which){
      var it = document.getElementById('lang-it');
      var en = document.getElementById('lang-en');
      var navIt = document.getElementById('nav-it');
      var navEn = document.getElementById('nav-en');
      if(which === 'en'){
        en.classList.add('active'); it.classList.remove('active');
        if(navEn) navEn.style.display = 'block';
        if(navIt) navIt.style.display = 'none';
        document.documentElement.lang = 'en';
        document.title = 'HEVC-Video Converter — User Manual';
        location.hash = '#en-intro';
      }else{
        it.classList.add('active'); en.classList.remove('active');
        if(navIt) navIt.style.display = 'block';
        if(navEn) navEn.style.display = 'none';
        document.documentElement.lang = 'it';
        document.title = 'HEVC-Video Converter — Manuale Utente';
        location.hash = '#introduzione';
      }
    }
  </script>""",
        desc="setLang() function block"
    )
    return text

def main():
    import sys
    if len(sys.argv) < 2:
        raise SystemExit("Usage: patch_manual_mkv_suite.py /path/to/video_converter_user_manual.html")

    src = Path(sys.argv[1]).expanduser().resolve()
    if not src.is_file():
        raise SystemExit(f"[FAIL] File not found: {src}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = src.with_suffix(src.suffix + f".{stamp}.bak")
    out = src.with_name(src.stem + "_MKVSuite" + src.suffix)

    html = src.read_text(encoding="utf-8")

    # 1) Header badge: add version + year
    html = sub_or_die(
        html,
        r"<h1>HEVC-Video Converter\s*<span class=\"badge\">2025<\/span><\/h1>",
        f"<h1>HEVC-Video Converter <span class=\"badge\">v{VERSION}</span> <span class=\"badge\">{YEAR}</span></h1>",
        count=1,
        desc="Header h1 badge"
    )

    # 2) Year updates
    html = html.replace("© 2025", f"© {YEAR}")
    html = html.replace(" — 2025", f" — {YEAR}")
    html = html.replace("progetto 2025", f"progetto {YEAR}")

    # 3) Replace nav + improve setLang() to toggle nav
    html = replace_nav_and_setlang(html)

    # 4) Intro highlights: IT
    html = sub_or_die(
        html,
        r"(<div class=\"note\">\s*<b>Novità principali \(versione attuale\):<\/b>\s*<ul>)(.*?)(<\/ul>\s*<\/div>)",
        rf"""\1
          <li><b>MKV Suite integrata</b> (Tools → <b>Strumenti MKV</b>): Estrai / Applica Tag / Crea MKV / Unisci episodi.</li>
          <li><b>Toolbar icon-only</b> (pulsanti = icone PNG, stile LDVD).</li>
          <li>Voce <b>File → Riavvia…</b> per riavvio “pulito” dell’app (reset stato in RAM).</li>
          <li>Modulo integrato <b>LDVD Ripper</b>: DVD → file locale + (opzionale) OCR sottotitoli in SRT + handoff a HEVC.</li>
          <li>Risorse icone Qt: path standard <code>:/icons/...</code> (generate durante il build del <code>.deb</code>).</li>
          <li>Scelta lingua (IT/EN).</li>
        \3""",
        count=1,
        desc="IT highlights block"
    )

    # 5) Intro highlights: EN
    html = sub_or_die(
        html,
        r"(<div class=\"note\">\s*<b>Main highlights \(current version\):<\/b>\s*<ul>)(.*?)(<\/ul>\s*<\/div>)",
        rf"""\1
          <li><b>Integrated MKV Suite</b> (Tools → <b>MKV Tools</b>): Extract / Apply Tags / Remux / Merge Episodes.</li>
          <li><b>Icon-only toolbar</b> (buttons are PNG icons, LDVD-style).</li>
          <li><b>File → Restart…</b> menu entry to restart the app cleanly (RAM state reset).</li>
          <li>Integrated <b>LDVD Ripper</b>: DVD → local files + (optional) subtitle OCR to SRT + handoff to HEVC.</li>
          <li>Qt resources use <code>:/icons/...</code> (generated during <code>.deb</code> packaging).</li>
        \3""",
        count=1,
        desc="EN highlights block"
    )

    # 6) Requirements optional tools: IT
    html = insert_into_first_ul_after(
        html,
        "<h3>2.3 Tool opzionali",
        """
          <li><b>MKVToolNix</b> (mkvmerge/mkvextract/mkvpropedit) se usi <b>MKV Suite</b>.</li>
          <li><b>gnome-subtitles</b> per ottenere una <b>corretta modifica dei sottotitoli</b> dall’editor (Linux).</li>
""",
        desc="IT optional tools"
    )

    # 7) Requirements optional tools: EN
    html = insert_into_first_ul_after(
        html,
        "<h3>2.3 Optional tools",
        """
          <li><b>MKVToolNix</b> (mkvmerge/mkvextract/mkvpropedit) for <b>MKV Suite</b>.<br></li>
          <li><b>gnome-subtitles</b> for reliable subtitle editing from the integrated workflow (Linux).<br></li>
""",
        desc="EN optional tools"
    )

    # 8) UI overview bullet: IT
    html = sub_or_die(
        html,
        r"(<h2 id=\"interfaccia\">4\.\s*Panoramica Interfaccia<\/h2>\s*<ul>.*?<li><strong>Strumenti:<\/strong>.*?<\/li>)",
        r"""\1
        <li><strong>Strumenti MKV:</strong> <em>Estrai</em>, <em>Applica Tag</em>, <em>Crea MKV</em>, <em>Unisci episodi</em>.</li>""",
        desc="IT UI overview insert"
    )

    # 9) UI overview bullet: EN
    html = sub_or_die(
        html,
        r"(<h2>4\.\s*User Interface Overview<\/h2>\s*<ul>.*?<li><strong>Tools<\/strong>:.*?<\/li>)",
        r"""\1
        <li><strong>MKV Tools</strong>: Extract, Apply Tags, Remux, Merge Episodes.<br></li>""",
        desc="EN UI overview insert"
    )

    # 10) Insert IT MKV Suite section before LDVD section + renumber IT sections after Coda
    html = insert_before_or_die(html, '<h2 id="ldvd">12. LDVD Ripper', IT_MKV_SUITE_SECTION, desc="Insert IT MKV Suite section")

    # Renumber IT: LDVD 12->13, Subtitle Edit 13->14, Troubleshoot 14->15, FAQ 15->16, Info 16->17, Legal 17->18
    html = sub_or_die(html, r'(<h2 id="ldvd">)\s*12\.', r"\1 13.", count=1, desc="IT LDVD h2 12->13")
    html = re.sub(r'(<h3>)\s*12\.', r"\1 13.", html)  # LDVD subheadings
    html = sub_or_die(html, r'(<h2 id="subtitle-edit">)\s*13\.', r"\1 14.", count=1, desc="IT subtitle-edit h2 13->14")
    html = re.sub(r'(<h3>)\s*13\.', r"\1 14.", html)  # subtitle-edit subheadings
    html = sub_or_die(html, r'(<h2 id="troubleshoot">)\s*14\.', r"\1 15.", count=1, desc="IT troubleshoot h2 14->15")
    html = re.sub(r'(<h3>)\s*14\.', r"\1 15.", html)  # troubleshoot subheadings
    html = sub_or_die(html, r'(<h2 id="faq">)\s*15\.', r"\1 16.", count=1, desc="IT FAQ h2 15->16")
    html = sub_or_die(html, r'(<h2 id="info">)\s*16\.', r"\1 17.", count=1, desc="IT info h2 16->17")
    html = sub_or_die(html, r'(<h2 id="note-legali">)\s*17\.', r"\1 18.", count=1, desc="IT legal h2 17->18")

    # 11) English IDs + insert EN MKV Suite section + renumber EN sections after recipes
    html = html.replace("<h2>2. Requirements</h2>", '<h2 id="en-req">2. Requirements</h2>')
    html = html.replace("<h2>3. Install &amp; Run (Linux / macOS / Windows)</h2>", '<h2 id="en-install">3. Install &amp; Run (Linux / macOS / Windows)</h2>')
    html = html.replace("<h2>4. User Interface Overview</h2>", '<h2 id="en-ui">4. User Interface Overview</h2>')
    html = html.replace("<h2>5. How to Encode (step-by-step)</h2>", '<h2 id="en-encode">5. How to Encode (step-by-step)</h2>')
    html = html.replace("<h2>6. Ready-made recipes (quick results)</h2>", '<h2 id="en-recipes">6. Ready-made recipes (quick results)</h2>')

    # Insert EN MKV Suite before Subtitles section (which is currently 7)
    html = insert_before_or_die(html, "<h2>7. Subtitles", EN_MKV_SUITE_SECTION, desc="Insert EN MKV Suite section")

    # Renumber EN: 7 Subtitles -> 8, 8 LDVD -> 9, 9 Subtitle Edit -> 10, 10 Troubleshooting -> 11, 11 Project Info -> 12
    html = html.replace("<h2>7. Subtitles (embedded / external / from DVD)</h2>", '<h2 id="en-subs">8. Subtitles (embedded / external / from DVD)</h2>')
    html = html.replace("<h2>8. LDVD Ripper (DVD → local files + OCR + handoff)</h2>", '<h2 id="en-ldvd">9. LDVD Ripper (DVD → local files + OCR + handoff)</h2>')
    html = html.replace('<h2 id="en-subtitle-edit">9. Subtitle Edit (fallback when OCR fails)</h2>', '<h2 id="en-subtitle-edit">10. Subtitle Edit (fallback when OCR fails)</h2>')
    html = html.replace("<h3>9.1 Beginner-friendly workflow</h3>", "<h3>10.1 Beginner-friendly workflow</h3>")
    html = html.replace("<h3>9.2 If Subtitle Edit cannot find subtitles</h3>", "<h3>10.2 If Subtitle Edit cannot find subtitles</h3>")
    html = html.replace("<h2>10. Troubleshooting</h2>", '<h2 id="en-troubleshoot">11. Troubleshooting</h2>')
    html = html.replace("<h2>11. Project Info / Contact</h2>", '<h2 id="en-info">12. Project Info / Contact</h2>')

    # Add a troubleshooting note for MKV Suite (EN) at the end of EN troubleshooting section (simple insert)
    html = insert_before_or_die(
        html,
        '<section>\n      </section><h2 id="en-info">',
        """
      <h3>MKV Suite: “mkvmerge not found” / subtitle editor missing</h3>
      <div class="warn">
        Install prerequisites:
        <pre>sudo apt install mkvtoolnix mkvtoolnix-gui gnome-subtitles</pre>
      </div>
""".strip("\n"),
        desc="EN troubleshoot MKV note"
    )

    # Add a troubleshooting note for MKV Suite (IT) at end of IT troubleshooting section
    html = insert_before_or_die(
        html,
        '<h2 id="faq">',
        """
      <h3>15.6 MKV Suite: “mkvmerge non trovato” / editor sottotitoli mancante</h3>
      <div class="warn">
        Installa i prerequisiti:
        <pre>sudo apt install mkvtoolnix mkvtoolnix-gui gnome-subtitles</pre>
      </div>
""".strip("\n"),
        desc="IT troubleshoot MKV note"
    )

    # Write backup + output
    backup.write_text(html, encoding="utf-8")
    out.write_text(html, encoding="utf-8")
    print(f"[OK] Backup written: {backup}")
    print(f"[OK] Updated manual: {out}")

if __name__ == "__main__":
    main()

