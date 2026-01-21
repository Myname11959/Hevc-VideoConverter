#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hevc_gui/i18n.py — versione stabile (anti-mesccolamento)

Problema reale che risolve:
- dopo certe azioni (es. scelta file) qualche modulo può cambiare
  QCoreApplication.setOrganizationName()/setApplicationName().
- QSettings() “nudo” inizia a leggere/scrivere su un altro namespace → lingua che “salta”
  e UI mescolata IT/EN.

Soluzione:
- congeliamo ORG/APP usati da QSettings una volta sola (freeze)
- la lingua runtime è una variabile interna (_APP_LANG)
- QSettings serve solo per persistere, sempre nello stesso scope congelato
- HEVC_LANG viene sempre riallineata alla lingua runtime per i subprocess (LDVD/SAG).
"""

from __future__ import annotations

import os
import sys
import html
import inspect
from pathlib import Path
from typing import Dict, Optional
import xml.etree.ElementTree as ET

from PyQt5.QtCore import QCoreApplication, QSettings, QTranslator, QEvent


SUPPORTED = ("it", "en")
DEFAULT_LANG = "it"

_SETTINGS_KEYS_READ = ("ui/lang", "hevc/lang", "i18n/lang")
_SETTINGS_KEYS_WRITE = ("ui/lang", "hevc/lang", "i18n/lang")

_OVERRIDES: Dict[str, Dict[str, str]] = {
    "en": {
        "Lingua": "Language",
        "Nessuno": "None",
        "Azioni": "Actions",
        "Visualizza": "View",
        "Aiuto": "Help",
        "Strumenti": "Tools",
        "Impostazioni": "Settings",
        "Lingua titoli": "Title language",
        "Aspetto...": "Appearance...",
        "Aspetto…": "Appearance…",
        "Informazioni...": "Info...",
        "Informazioni…": "Info…",
        "Informazioni …": "Info…",
        "Agg. traccia": "Add. track",
        # LDVD: QMessageBox Open .srt rimasto IT
        "Non ho trovato nessuna cartella con file .srt collegati.\nAssicurati di aver estratto almeno un VOB e/o completato l'OCR.":
            "No folder with linked .srt files found.\nMake sure you extracted at least one VOB and/or completed the OCR.",
        # variante senza newline (se in qualche punto è su una riga sola)
        "Non ho trovato nessuna cartella con file .srt collegati. Assicurati di aver estratto almeno un VOB e/o completato l'OCR.":
            "No folder with linked .srt files found. Make sure you extracted at least one VOB and/or completed the OCR.",
    }
}

_debug: bool = bool(int(os.environ.get("HEVC_I18N_DEBUG", "0") or "0"))

_qt_translator: Optional[QTranslator] = None
_flat_map: Dict[str, str] = {}

# Single source of truth runtime
_APP_LANG: Optional[str] = None

# QSettings scope “congelato”
_QS_ORG: Optional[str] = None
_QS_APP: Optional[str] = None


def _log(*a):
    if _debug:
        print("[i18n]", *a, file=sys.stderr)


def _translations_dir() -> Path:
    return Path(__file__).resolve().parent / "resources" / "i18n"


def _norm_lang(lang: Optional[str], default: str = DEFAULT_LANG) -> str:
    if not lang:
        return default
    s = str(lang).strip().lower()
    if s.startswith("it"):
        return "it"
    if s.startswith("en"):
        return "en"
    if s in SUPPORTED:
        return s
    return default


def _freeze_qsettings_scope() -> None:
    """
    Congela ORG/APP una sola volta.
    Da qui in poi la lingua legge/scrive SEMPRE nello stesso namespace,
    anche se qualche modulo cambia applicationName/organizationName.
    """
    global _QS_ORG, _QS_APP
    if _QS_ORG and _QS_APP:
        return

    try:
        s = QSettings()
        org = ""
        app = ""
        # in PyQt5 spesso esistono questi metodi
        try:
            org = (s.organizationName() or "").strip()
        except Exception:
            org = ""
        try:
            app = (s.applicationName() or "").strip()
        except Exception:
            app = ""
    except Exception:
        org = ""
        app = ""

    # fallback su QCoreApplication
    try:
        if not org:
            org = (QCoreApplication.organizationName() or "").strip()
        if not app:
            app = (QCoreApplication.applicationName() or "").strip()
    except Exception:
        pass

    # fallback finale
    if not org:
        org = "hevc_gui"
    if not app:
        app = "hevc_gui"

    _QS_ORG, _QS_APP = org, app
    _log("freeze QSettings scope:", _QS_ORG, _QS_APP)


def _qs() -> QSettings:
    _freeze_qsettings_scope()
    # usa SEMPRE lo scope congelato
    return QSettings(_QS_ORG, _QS_APP)


def _read_settings_lang() -> Optional[str]:
    try:
        s = _qs()
        for k in _SETTINGS_KEYS_READ:
            v = (s.value(k, "") or "").strip().lower()
            v = _norm_lang(v, default="")
            if v in SUPPORTED:
                return v
    except Exception:
        return None
    return None


def _write_settings_lang(lang: str) -> None:
    try:
        s = _qs()
        for k in _SETTINGS_KEYS_WRITE:
            s.setValue(k, lang)
        s.sync()
    except Exception:
        pass


def _align_env(lang: str) -> None:
    # Per LDVD/SAG subprocess
    os.environ["HEVC_LANG"] = lang


def get_lang(default: str = DEFAULT_LANG) -> str:
    """
    Fonte runtime:
      - se _APP_LANG è settata → quella
      - altrimenti inizializza UNA VOLTA con:
          1) HEVC_LANG env (se valido)  [solo per bootstrap]
          2) QSettings (scope congelato)
          3) default
    """
    global _APP_LANG

    if _APP_LANG in SUPPORTED:
        return _APP_LANG

    # bootstrap: env esplicita vince SOLO per inizializzazione
    env = _norm_lang(os.environ.get("HEVC_LANG", ""), default="")
    if env in SUPPORTED:
        _APP_LANG = env
        _write_settings_lang(env)   # riallinea persistence
        _align_env(env)
        return env

    st = _read_settings_lang()
    if st in SUPPORTED:
        _APP_LANG = st
        _align_env(st)
        return st

    lang = _norm_lang(default)
    _APP_LANG = lang
    _write_settings_lang(lang)
    _align_env(lang)
    return lang


def set_lang(lang: Optional[str]) -> bool:
    """
    Imposta lingua runtime + persistenza (scope congelato) + env.
    """
    global _APP_LANG
    cur = get_lang()
    if not lang:
        lang = cur
    lang = _norm_lang(lang)

    changed = (cur != lang)
    _APP_LANG = lang
    _write_settings_lang(lang)
    _align_env(lang)
    return changed


def child_env(lang: Optional[str] = None) -> Dict[str, str]:
    e = dict(os.environ)
    e["HEVC_LANG"] = _norm_lang(lang or get_lang())
    return e


def _guess_context() -> str:
    try:
        f = inspect.currentframe()
        if not f:
            return "hevc_gui"
        caller = f.f_back.f_back
        if not caller:
            return "hevc_gui"
        loc = caller.f_locals
        if "self" in loc:
            return type(loc["self"]).__name__
        if "cls" in loc and hasattr(loc["cls"], "__name__"):
            return loc["cls"].__name__
        mod = caller.f_globals.get("__name__", "hevc_gui")
        return mod.split(".")[-1] or "hevc_gui"
    except Exception:
        return "hevc_gui"

def apply_actions_i18n(root_obj) -> None:
    """
    Traduce QAction (menù + toolbar) che spesso NON si aggiornano con QTranslator.
    Applica L() a:
      - action.text()
      - toolTip / statusTip / whatsThis
      - titoli dei QMenu
    """
    try:
        from PyQt5.QtWidgets import QMenu, QMenuBar, QToolBar
    except Exception:
        return

    def _is_human(s: str) -> bool:
        if not s:
            return False
        t = str(s).strip()
        if not t or t in {"—", "…", "..."}:
            return False
        low = t.lower()

        # roba tecnica / scorciatoie / path
        if low.startswith(":/") or "/" in t or "\\" in t:
            return False
        if any(x in t for x in ("Ctrl+", "Alt+", "Shift+")):
            return False
        if (len(t) <= 4 and t.upper().startswith("F") and t[1:].isdigit()):
            return False

        return any(ch.isalpha() for ch in t)

    def _tr_action(a) -> None:
        try:
            tx = a.text()
            if _is_human(tx):
                a.setText(L(tx))
            tt = a.toolTip()
            if _is_human(tt):
                a.setToolTip(L(tt))
            st = a.statusTip()
            if _is_human(st):
                a.setStatusTip(L(st))
            wt = a.whatsThis()
            if _is_human(wt):
                a.setWhatsThis(L(wt))
        except Exception:
            pass

    def _walk_menu(menu: QMenu) -> None:
        try:
            title = menu.title()
            if _is_human(title):
                menu.setTitle(L(title))
        except Exception:
            pass

        for a in menu.actions():
            _tr_action(a)
            try:
                m = a.menu()
                if m is not None:
                    _walk_menu(m)
            except Exception:
                pass

    # menubar
    try:
        if hasattr(root_obj, "menuBar"):
            mb = root_obj.menuBar()
            if isinstance(mb, QMenuBar):
                for a in mb.actions():
                    _tr_action(a)
                    m = a.menu()
                    if m is not None:
                        _walk_menu(m)
    except Exception:
        pass

    # toolbars
    try:
        for tb in root_obj.findChildren(QToolBar):
            for a in tb.actions():
                _tr_action(a)
                m = a.menu()
                if m is not None:
                    _walk_menu(m)
    except Exception:
        pass


def _apply_overrides(lang: str, src: str, out: str) -> str:
    m = _OVERRIDES.get(lang)
    if not m:
        return out
    return m.get(src, out)


def _build_flat_map(lang: str) -> Dict[str, str]:
    base = _translations_dir()
    if not base.exists():
        return {}

    out: Dict[str, str] = {}

    # IMPORTANT: usa SOLO hevc_<lang>.ts per evitare duplicati (hevc_en_tr.ts ecc.)
    # Se il file unico non esiste, fallback al vecchio wildcard.
    ts_main = base / f"hevc_{lang}.ts"
    ts_files = [ts_main] if ts_main.exists() else sorted(base.glob(f"hevc_{lang}*.ts"))

    for ts in ts_files:
        try:
            tree = ET.parse(str(ts))
            root = tree.getroot()
            for ctx in root.findall("context"):
                for msg in ctx.findall("message"):
                    src_el = msg.find("source")
                    tr_el = msg.find("translation")
                    if src_el is None or tr_el is None:
                        continue
                    src = (src_el.text or "").strip()
                    tr = (tr_el.text or "").strip()
                    if not src or not tr:
                        continue
                    if tr_el.get("type") == "unfinished":
                        continue
                    out.setdefault(src, tr)
        except Exception as e:
            _log("skip ts", ts, "->", e)
    return out



def _augment_flat_map(lang: str, fm: Dict[str, str]) -> None:
    if lang != "en":
        return
    fm.setdefault("Annullato.", "Canceled.")
    fm.setdefault("Annullato", "Canceled")
    fm.setdefault("Errore.", "Error.")
    fm.setdefault("Errore", "Error")


def _ensure_sinks_installed() -> None:
    try:
        from .i18n_sinks import install_qt_i18n_sinks
        install_qt_i18n_sinks()
    except Exception as e:
        _log("install_qt_i18n_sinks failed:", e)


def init_qt_i18n(app=None, lang: Optional[str] = None) -> bool:
    """
    Installa QTranslator.
    NOTA: qui congeliamo anche QSettings scope (indirettamente) e fissiamo _APP_LANG.
    """
    global _qt_translator, _flat_map

    if lang is not None:
        set_lang(lang)
    lang = get_lang()

    qapp = app or QCoreApplication.instance()
    if app is not None and not hasattr(app, "installTranslator"):
        qapp = QCoreApplication.instance()

    if qapp is None:
        _log("No QCoreApplication instance; skipping translator install")
        _flat_map = _build_flat_map(lang) if lang != "it" else {}
        _augment_flat_map(lang, _flat_map)
        _ensure_sinks_installed()
        return False

    if _qt_translator is not None:
        try:
            qapp.removeTranslator(_qt_translator)
        except Exception:
            pass
        _qt_translator = None

    ok = False
    if lang != "it":
        tr = QTranslator()
        base = _translations_dir()
        qm_path = base / f"hevc_{lang}.qm"

        if qm_path.exists():
            ok = tr.load(str(qm_path))
        if not ok:
            ok = tr.load(f"hevc_{lang}.qm", str(base))

        _log("load qm", str(qm_path), "ok=", ok, "exists=", qm_path.exists())

        if ok:
            try:
                qapp.installTranslator(tr)
                _qt_translator = tr
            except Exception as e:
                _log("installTranslator failed:", e)
                ok = False

    _flat_map = _build_flat_map(lang) if lang != "it" else {}
    _augment_flat_map(lang, _flat_map)
    _log("flat_map size =", len(_flat_map))

    _ensure_sinks_installed()
    _install_msgbox_i18n_sink()
    
    return ok


def L(text: str, ctx: Optional[str] = None) -> str:
    if text is None:
        return ""
    if not isinstance(text, str):
        return str(text)

    lang = get_lang()

    global _flat_map
    if lang != "it" and not _flat_map:
        _flat_map = _build_flat_map(lang)
        _augment_flat_map(lang, _flat_map)

    if lang in _OVERRIDES and text in _OVERRIDES[lang]:
        return _OVERRIDES[lang][text]

    context = ctx or _guess_context()

    out = QCoreApplication.translate(context, text)
    if out == text:
        for c in ("hevc_gui", "MainWindow", "L", "T"):
            out2 = QCoreApplication.translate(c, text)
            if out2 != text:
                out = out2
                break

    if out == text and lang != "it":
        out = _flat_map.get(text, text)

    out = html.unescape(out)
    return _apply_overrides(lang, text, out)


def T(*args) -> str:
    if not args:
        return ""
    if len(args) == 1:
        return L(str(args[0]))
    return L(str(args[1]), ctx=str(args[0]))


def restart() -> None:
    env = child_env(get_lang())
    exe = sys.executable or "python3"
    argv = [exe] + sys.argv
    _log("restart:", argv[0], argv[1:])
    os.execvpe(exe, argv, env)


# ───────────── compat / refresh ─────────────

def current_lang() -> str:
    return get_lang()

def restart_app() -> None:
    restart()


def apply_i18n_to_widget(widget) -> None:
    if widget is None:
        return
    try:
        from PyQt5.QtWidgets import QWidget
        from PyQt5.QtCore import QObject
    except Exception:
        return
    if not isinstance(widget, QWidget):
        return

    try:
        QCoreApplication.sendEvent(widget, QEvent(QEvent.LanguageChange))
    except Exception:
        pass

    for name in ("retranslateUi", "retranslate_ui", "retranslate", "_retranslate_ui"):
        try:
            fn = getattr(widget, name, None)
            if callable(fn):
                fn()
        except Exception:
            pass

    try:
        ui = getattr(widget, "ui", None)
        if ui is not None:
            fn = getattr(ui, "retranslateUi", None)
            if callable(fn):
                fn(widget)
    except Exception:
        pass

    try:
        for ch in widget.findChildren(QObject):
            try:
                QCoreApplication.sendEvent(ch, QEvent(QEvent.LanguageChange))
            except Exception:
                pass
    except Exception:
        pass


def apply_i18n(*args, **kwargs) -> bool:
    _ = kwargs.pop("ctx", None)
    lang = kwargs.pop("lang", None)
    app = kwargs.pop("app", None)

    obj = args[0] if args else None
    if len(args) >= 2 and lang is None:
        lang = args[1]
    if app is None:
        app = obj

    changed = False
    if lang is not None:
        changed = set_lang(lang)

    init_qt_i18n(app, None)

    try:
        from PyQt5.QtWidgets import QWidget
        if obj is not None and isinstance(obj, QWidget):
            apply_i18n_to_widget(obj)
    except Exception:
        pass

    return changed


def set_app_language(*args, **kwargs):
    app = kwargs.get("app", None)
    lang = kwargs.get("lang", None)

    if len(args) == 1 and lang is None:
        lang = args[0]
    elif len(args) >= 2 and lang is None:
        app = args[0]
        lang = args[1]

    changed = set_lang(lang)
    init_qt_i18n(app, lang)
    return changed


def debug_state(tag: str = "") -> None:
    _freeze_qsettings_scope()
    print(
        "[i18n-state]",
        tag,
        "APP_LANG=", _APP_LANG,
        "get_lang()=", get_lang(),
        "HEVC_LANG=", os.environ.get("HEVC_LANG"),
        "QS_SCOPE=", (_QS_ORG, _QS_APP),
        "QCoreApp=", (QCoreApplication.organizationName(), QCoreApplication.applicationName()),
        file=sys.stderr,
    )

def apply_actions_i18n(root_obj) -> None:
    """
    Applica cose che Qt spesso NON fa da solo sulle QAction:
    - forza icone per voci specifiche (menu)
    - opzionale: setIconVisibleInMenu(True)
    Non tocca altro.
    """
    try:
        from PyQt5.QtWidgets import QMenu, QMenuBar, QToolBar
        from PyQt5.QtGui import QIcon
    except Exception:
        return

    # chiavi normalizzate: niente '&', ellipsis uniformato a "..."
    ICON_BY_TEXT = {
        "passa a hevc": ":/icons/ph_send.png",
        "send to hevc": ":/icons/ph_send.png",

        "manuale utente": ":/icons/ph_user_manual.png",
        "manuale utente...": ":/icons/ph_user_manual.png",
        "user manual": ":/icons/ph_user_manual.png",
        "user manual...": ":/icons/ph_user_manual.png",
    }

    def _norm(t: str) -> str:
        t = (t or "").replace("&", "").strip()
        t = t.replace("…", "...")  # ellipsis “vero” -> "..."
        return t.lower()

    def _maybe_set_icon(a) -> None:
        try:
            if a is None:
                return
            txt = _norm(a.text())
            if not txt:
                return

            icon_path = ICON_BY_TEXT.get(txt)
            if not icon_path:
                return

            # setta solo se non c'è già un'icona
            try:
                if not a.icon().isNull():
                    return
            except Exception:
                pass

            a.setIcon(QIcon(icon_path))
            try:
                a.setIconVisibleInMenu(True)
            except Exception:
                pass
        except Exception:
            pass

    def _walk_menu(menu: QMenu) -> None:
        for a in menu.actions():
            _maybe_set_icon(a)
            try:
                m = a.menu()
                if m is not None:
                    _walk_menu(m)
            except Exception:
                pass

    # menubar
    try:
        if hasattr(root_obj, "menuBar"):
            mb = root_obj.menuBar()
            if isinstance(mb, QMenuBar):
                for a in mb.actions():
                    _maybe_set_icon(a)
                    m = a.menu()
                    if m is not None:
                        _walk_menu(m)
    except Exception:
        pass

    # toolbars (non è il tuo caso, ma già che ci siamo)
    try:
        for tb in root_obj.findChildren(QToolBar):
            for a in tb.actions():
                _maybe_set_icon(a)
                m = a.menu()
                if m is not None:
                    _walk_menu(m)
    except Exception:
        pass

# === I18N-TRACE-WRAP (debug) =========================================
# Attiva con: HEVC_I18N_TRACE=1
try:
    import os as _os, sys as _sys
    def _i18n_trace(tag: str, *info):
        if _os.environ.get("HEVC_I18N_TRACE","0") != "1":
            return
        try:
            import traceback as _tb
            try:
                from PyQt5.QtCore import QCoreApplication
                appn = (QCoreApplication.applicationName() or "").strip()
                orgn = (QCoreApplication.organizationName() or "").strip()
            except Exception:
                appn = orgn = ""
            print(f"[I18N-TRACE] {tag} HEVC_LANG={_os.environ.get('HEVC_LANG')!r} app={appn!r} org={orgn!r} info={info!r}", file=_sys.stderr)
            _tb.print_stack(limit=30, file=_sys.stderr)
        except Exception:
            pass

    # wrap set_lang / set_app_language / apply_i18n se esistono
    if "set_lang" in globals() and callable(globals().get("set_lang")):
        _orig_set_lang = set_lang
        def set_lang(*a, **k):
            _i18n_trace("set_lang", *a)
            return _orig_set_lang(*a, **k)

    if "set_app_language" in globals() and callable(globals().get("set_app_language")):
        _orig_set_app_language = set_app_language
        def set_app_language(*a, **k):
            _i18n_trace("set_app_language", *a)
            return _orig_set_app_language(*a, **k)

    if "apply_i18n" in globals() and callable(globals().get("apply_i18n")):
        _orig_apply_i18n = apply_i18n
        def apply_i18n(*a, **k):
            _i18n_trace("apply_i18n", *a)
            return _orig_apply_i18n(*a, **k)

except Exception:
    pass
# =====================================================================


# === APPLY_I18N_LANG_CTX_FIX ==========================================
# Problema: apply_i18n(self, "scripts.string_audio_generator") veniva
# interpretato come lang="scripts..." -> _norm_lang() -> "it" -> lingua ribaltata.
# Fix: tratta come lang SOLO token tipo it/en/it_IT/en_US. Altrimenti è ctx (ignorato).
def _i18n__looks_like_lang(x) -> bool:
    try:
        s = str(x).strip().lower()
    except Exception:
        return False
    return s in ("it", "en") or s.startswith("it_") or s.startswith("en_") or s.startswith("it-") or s.startswith("en-")

try:
    _apply_i18n_orig = apply_i18n  # salva se esiste
except Exception:
    _apply_i18n_orig = None

def apply_i18n(*args, **kwargs) -> bool:
    """
    Compat robusta:
      - apply_i18n(obj)
      - apply_i18n(obj, "en")                     -> cambia lingua
      - apply_i18n(obj, "scripts.modulo")         -> ctx (NON cambia lingua)
      - apply_i18n(obj, ctx="scripts.modulo")     -> ctx (NON cambia lingua)
      - apply_i18n(obj, lang="en")                -> cambia lingua
    """
    _ = kwargs.pop("ctx", None)  # ctx ignorato (serve solo per vecchie firme)
    lang = kwargs.pop("lang", None)
    app = kwargs.pop("app", None)

    obj = args[0] if args else None
    extra = list(args[1:])

    # se lang non è dato esplicitamente, prova a dedurlo dal 1° extra posizionale
    if lang is None and extra:
        if _i18n__looks_like_lang(extra[0]):
            lang = extra[0]
        else:
            # era un ctx posizionale (tipo "scripts.string_audio_generator"): NON cambiare lingua
            lang = None

    if app is None:
        app = obj

    changed = False
    if lang is not None:
        try:
            changed = set_lang(lang)
        except Exception:
            changed = False

    # applica traduttore per la lingua corrente (non cambia se lang=None)
    try:
        init_qt_i18n(app, None)
    except Exception:
        try:
            init_qt_i18n(None, None)
        except Exception:
            pass

    # refresh widget se possibile
    try:
        from PyQt5.QtWidgets import QWidget
        if obj is not None and isinstance(obj, QWidget):
            fn = globals().get("apply_i18n_to_widget")
            if callable(fn):
                fn(obj)
            fn2 = globals().get("apply_actions_i18n")
            if callable(fn2):
                fn2(obj)
    except Exception:
        pass

    return changed
# =====================================================================


# === PRESET_TOKEN_BYPASS =============================================
# I preset x264/x265 sono token tecnici e NON devono mai essere tradotti.
try:
    _orig_L__preset_bypass = L
    _PRESET_TOKENS = {
        "ultrafast","superfast","veryfast","faster","fast","medium",
        "slow","slower","veryslow","placebo"
    }
    def L(text, ctx=None):  # type: ignore
        try:
            if isinstance(text, str) and text in _PRESET_TOKENS:
                return text
        except Exception:
            pass
        return _orig_L__preset_bypass(text, ctx)
except Exception:
    pass
# =====================================================================
# ─────────────────────────────────────────────────────────────
# AUTO: traduci automaticamente i QMessageBox (titolo + testo)
# ─────────────────────────────────────────────────────────────
_MSGBOX_I18N_PATCHED = False

def _install_msgbox_i18n_sink() -> None:
    global _MSGBOX_I18N_PATCHED
    if _MSGBOX_I18N_PATCHED:
        return

    try:
        from PyQt5.QtWidgets import QMessageBox
    except Exception:
        return

    def _wrap(fn):
        def _w(parent, title, text, *args, **kwargs):
            try:
                if isinstance(title, str):
                    title = L(title)
            except Exception:
                pass
            try:
                if isinstance(text, str):
                    text = L(text)
            except Exception:
                pass
            return fn(parent, title, text, *args, **kwargs)
        return _w

    # patch dei metodi statici più usati
    try:
        QMessageBox.information = _wrap(QMessageBox.information)
        QMessageBox.warning     = _wrap(QMessageBox.warning)
        QMessageBox.critical    = _wrap(QMessageBox.critical)
        QMessageBox.question    = _wrap(QMessageBox.question)
    except Exception:
        return

    _MSGBOX_I18N_PATCHED = True

# === HEVC_I18N_HARDLOCK_BEGIN ===
# snapshot della apply_i18n originale: evita NameError quando hardlock è attivo
if "_HEVC_HARDLOCK_ORIG_APPLY_I18N" not in globals():
    _HEVC_HARDLOCK_ORIG_APPLY_I18N = apply_i18n


# Hard-lock definitivo per evitare “mix”:
# - dopo bootstrap della GUI principale, apply_i18n() chiamato da moduli secondari NON può cambiare lingua/scope
# - consente override solo dal core (main.py / hevc_gui/gui/*) oppure con force=True / owner=...
import os as _os
import inspect as _inspect

def lock_i18n(owner: str = "main") -> None:
    _os.environ["HEVC_I18N_LOCKED"] = "1"
    _os.environ["HEVC_I18N_OWNER"] = owner
    # se esiste, congela anche lo scope QSettings in modo coerente
    try:
        freeze_qsettings_scope()  # type: ignore[name-defined]
    except Exception:
        pass

def unlock_i18n() -> None:
    _os.environ.pop("HEVC_I18N_LOCKED", None)
    _os.environ.pop("HEVC_I18N_OWNER", None)

def _caller_is_core() -> bool:
    # core: tutto hevc_gui/* tranne dvd_ripper; + main.py
    for fr in _inspect.stack():
        fn = fr.filename.replace('\\', '/')
        if fn.endswith('/main.py'):
            return True
        if '/hevc_gui/' in fn and '/hevc_gui/dvd_ripper/' not in fn:
            return True
    return False

def apply_i18n(*args, **kwargs):  # type: ignore[override]
    """
    Wrapper finale (in fondo al file): non può essere sovrascritto da definizioni successive.
    - Se locked e chiamante non-core → NO-OP (ritorna True, non modifica lingua/scope/translator)
    - Se force=True o owner coincide o chiamante core → passa all'implementazione originale
    """
    if _os.environ.get("HEVC_I18N_LOCKED") == "1":
        owner = kwargs.get("owner", None)
        if kwargs.get("force") or (owner is not None and str(owner) == _os.environ.get("HEVC_I18N_OWNER")) or _caller_is_core():
            return _HEVC_HARDLOCK_ORIG_APPLY_I18N(*args, **kwargs)
        # NO-OP “sicuro” (signature compat): non cambia nulla
        return True
    return _HEVC_HARDLOCK_ORIG_APPLY_I18N(*args, **kwargs)
# === HEVC_I18N_HARDLOCK_END ===

