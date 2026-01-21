# -*- coding: utf-8 -*-
"""
Sinks Qt per traduzione automatica dei dialog.
- Non richiede modifiche ai call-site.
- Traduce titolo/testo passando sempre da L(...) al momento della chiamata.
"""
from __future__ import annotations

def install_msgbox_sinks() -> None:
    try:
        try:
            from PyQt5 import QtWidgets
        except Exception:
            from PySide6 import QtWidgets  # type: ignore
    except Exception:
        return

    if getattr(QtWidgets.QMessageBox, "_hevc_i18n_patched", False):
        return

    # Import ritardati per evitare dipendenze in fase di bootstrap
    def _L(x):
        try:
            from hevc_gui.i18n import L
            return L(str(x))
        except Exception:
            return str(x)

    # Prova a inizializzare i18n se l'app esiste già (idempotente)
    try:
        from hevc_gui.i18n import init_qt_i18n
        app = QtWidgets.QApplication.instance()
        if app is not None:
            init_qt_i18n(app)
    except Exception:
        pass

    # --- patch static methods QMessageBox ---
    _orig = {
        "information": QtWidgets.QMessageBox.information,
        "warning": QtWidgets.QMessageBox.warning,
        "critical": QtWidgets.QMessageBox.critical,
        "question": QtWidgets.QMessageBox.question,
        "about": QtWidgets.QMessageBox.about,
    }

    def _wrap_static(name):
        fn = _orig[name]
        def wrapped(parent, title, text, *args, **kwargs):
            return fn(parent, _L(title), _L(text), *args, **kwargs)
        return wrapped

    for name in ("information", "warning", "critical", "question", "about"):
        setattr(QtWidgets.QMessageBox, name, _wrap_static(name))

    # --- patch instance methods (copre QMessageBox() + setText ecc.) ---
    _orig_setText = QtWidgets.QMessageBox.setText
    _orig_setInfo = getattr(QtWidgets.QMessageBox, "setInformativeText", None)
    _orig_setDet = getattr(QtWidgets.QMessageBox, "setDetailedText", None)
    _orig_setTitle = QtWidgets.QMessageBox.setWindowTitle

    def setText(self, text):
        return _orig_setText(self, _L(text))

    def setWindowTitle(self, title):
        return _orig_setTitle(self, _L(title))

    QtWidgets.QMessageBox.setText = setText
    QtWidgets.QMessageBox.setWindowTitle = setWindowTitle

    if _orig_setInfo:
        def setInformativeText(self, text):
            return _orig_setInfo(self, _L(text))
        QtWidgets.QMessageBox.setInformativeText = setInformativeText

    if _orig_setDet:
        def setDetailedText(self, text):
            return _orig_setDet(self, _L(text))
        QtWidgets.QMessageBox.setDetailedText = setDetailedText

    # --- patch QInputDialog (titolo/label) ---
    try:
        _in_getText = QtWidgets.QInputDialog.getText
        _in_getInt = QtWidgets.QInputDialog.getInt
        _in_getDouble = QtWidgets.QInputDialog.getDouble
        _in_getItem = QtWidgets.QInputDialog.getItem

        def getText(parent, title, label, *args, **kwargs):
            return _in_getText(parent, _L(title), _L(label), *args, **kwargs)

        def getInt(parent, title, label, *args, **kwargs):
            return _in_getInt(parent, _L(title), _L(label), *args, **kwargs)

        def getDouble(parent, title, label, *args, **kwargs):
            return _in_getDouble(parent, _L(title), _L(label), *args, **kwargs)

        def getItem(parent, title, label, *args, **kwargs):
            return _in_getItem(parent, _L(title), _L(label), *args, **kwargs)

        QtWidgets.QInputDialog.getText = getText
        QtWidgets.QInputDialog.getInt = getInt
        QtWidgets.QInputDialog.getDouble = getDouble
        QtWidgets.QInputDialog.getItem = getItem
    except Exception:
        pass

    QtWidgets.QMessageBox._hevc_i18n_patched = True


# AUTO: cancel msgbox translate+dedupe
# Obiettivo: 1) mostrare subito nella lingua attiva 2) evitare doppio box (ITA poi EN).
import time as _hevc__time

_hevc__last_cancel = {"t": 0.0}

def _hevc__is_en_active() -> bool:
    try:
        from hevc_gui.i18n import L
        v = L("Pronto.")
        return bool(v and v != "Pronto.")
    except Exception:
        import os
        return os.environ.get("HEVC_LANG","").lower().startswith("en")

def _hevc__norm_cancel_key(title: str, text: str) -> str | None:
    t = (text or "").strip()
    # Varianti IT/EN tipiche
    if t in ("Annullato.", "Annullato", "Operazione annullata.", "Operazione annullata",
             "Estrazione annullata.", "Estrazione annullata",
             "Canceled.", "Canceled", "Operation canceled.", "Operation canceled",
             "Extraction canceled.", "Extraction canceled"):
        return "CANCEL"
    return None

def _hevc__translate_cancel_text(text: str) -> str:
    t = (text or "").strip()
    m = {
        "Annullato.": "Canceled.",
        "Annullato": "Canceled",
        "Operazione annullata.": "Operation canceled.",
        "Operazione annullata": "Operation canceled",
        "Estrazione annullata.": "Extraction canceled.",
        "Estrazione annullata": "Extraction canceled",
    }
    return m.get(t, text)

def _hevc__wrap_msgbox_static():
    try:
        try:
            from PyQt5.QtWidgets import QMessageBox
        except Exception:
            from PySide6.QtWidgets import QMessageBox  # type: ignore
    except Exception:
        return

    def _wrap(orig):
        if getattr(orig, "_hevc_cancel_wrapped", False):
            return orig

        def _wrapped(parent, title, text, *args, **kwargs):
            key = _hevc__norm_cancel_key(title, text)
            if key == "CANCEL":
                now = _hevc__time.monotonic()
                # dedupe: se ne hai appena mostrato uno, non mostrarne un altro subito dopo
                if now - _hevc__last_cancel["t"] < 2.0:
                    try:
                        return int(QMessageBox.Ok)
                    except Exception:
                        return 0
                _hevc__last_cancel["t"] = now

                # traduci SUBITO se EN è attivo (così non vedi più l'ITA)
                if _hevc__is_en_active():
                    text = _hevc__translate_cancel_text(text)

            return orig(parent, title, text, *args, **kwargs)

        _wrapped._hevc_cancel_wrapped = True
        return _wrapped

    # wrappa solo i metodi statici più comuni
    for name in ("information", "warning", "critical"):
        try:
            orig = getattr(QMessageBox, name)
            setattr(QMessageBox, name, _wrap(orig))
        except Exception:
            pass

_hevc__wrap_msgbox_static()


# AUTO: cancel msgbox dedupe v2 (instance exec)
# Copre QMessageBox creati come istanza + exec/exec_ (oltre ai static già wrappati).

import time as _hevc__time2

try:
    _hevc__last_cancel_v2
except Exception:
    _hevc__last_cancel_v2 = {"t": 0.0, "key": None}

def _hevc__is_en_active_v2() -> bool:
    try:
        from hevc_gui.i18n import L
        v = L("Pronto.")
        return bool(v and v != "Pronto.")
    except Exception:
        import os
        return os.environ.get("HEVC_LANG","").lower().startswith("en")

def _hevc__norm_cancel_key_v2(title: str, text: str) -> str | None:
    t = (text or "").strip()
    if t in (
        "Annullato.", "Annullato",
        "Operazione annullata.", "Operazione annullata",
        "Estrazione annullata.", "Estrazione annullata",
        "Canceled.", "Canceled",
        "Operation canceled.", "Operation canceled",
        "Extraction canceled.", "Extraction canceled",
    ):
        return "CANCEL"
    return None

def _hevc__translate_cancel_text_v2(text: str) -> str:
    t = (text or "").strip()
    m = {
        "Annullato.": "Canceled.",
        "Annullato": "Canceled",
        "Operazione annullata.": "Operation canceled.",
        "Operazione annullata": "Operation canceled",
        "Estrazione annullata.": "Extraction canceled.",
        "Estrazione annullata": "Extraction canceled",
    }
    return m.get(t, text)

def _hevc__wrap_msgbox_instance_exec_v2():
    try:
        try:
            from PyQt5.QtWidgets import QMessageBox
        except Exception:
            from PySide6.QtWidgets import QMessageBox  # type: ignore
    except Exception:
        return

    def _wrap_exec(orig):
        if getattr(orig, "_hevc_cancel_exec_wrapped_v2", False):
            return orig

        def _wrapped(self, *a, **k):
            try:
                title = self.windowTitle() or ""
            except Exception:
                title = ""
            try:
                text = self.text() or ""
            except Exception:
                text = ""

            key = _hevc__norm_cancel_key_v2(title, text)
            if key == "CANCEL":
                now = _hevc__time2.monotonic()
                # dedupe: blocca il secondo box ravvicinato
                if now - _hevc__last_cancel_v2["t"] < 3.0:
                    try:
                        return int(QMessageBox.Ok)
                    except Exception:
                        return 0
                _hevc__last_cancel_v2["t"] = now
                _hevc__last_cancel_v2["key"] = key

                # traduci SUBITO se EN attivo
                if _hevc__is_en_active_v2():
                    try:
                        self.setText(_hevc__translate_cancel_text_v2(text))
                    except Exception:
                        pass
                    # anche informativeText se usato
                    try:
                        it2 = self.informativeText()
                        if it2:
                            self.setInformativeText(_hevc__translate_cancel_text_v2(it2))
                    except Exception:
                        pass

            return orig(self, *a, **k)

        _wrapped._hevc_cancel_exec_wrapped_v2 = True
        return _wrapped

    # Qt5: exec_ ; Qt6/PySide6: exec
    for name in ("exec_", "exec"):
        try:
            orig = getattr(QMessageBox, name)
            if callable(orig):
                setattr(QMessageBox, name, _wrap_exec(orig))
        except Exception:
            pass

_hevc__wrap_msgbox_instance_exec_v2()


# AUTO: cancel msgbox dedupe v3 (substring + all texts)
# - prende text/informative/detailed
# - matcha per sottostringa: "annull" / "cancel"
# - dedupe 6s
import time as _hevc__t_v3

try:
    _hevc__cancel_seen_v3
except Exception:
    _hevc__cancel_seen_v3 = {"t": 0.0}

def _hevc__en_active_v3() -> bool:
    try:
        from hevc_gui.i18n import L
        v = L("Pronto.")
        return bool(v and v != "Pronto.")
    except Exception:
        import os
        return os.environ.get("HEVC_LANG","").lower().startswith("en")

def _hevc__is_cancel_like_v3(*texts) -> bool:
    blob = " ".join([str(x or "") for x in texts]).strip().lower()
    if not blob:
        return False
    return ("annull" in blob) or ("cancel" in blob)

def _hevc__translate_cancel_blob_v3(t: str) -> str:
    if not t:
        return t
    # traduci le forme IT più comuni (anche se compaiono dentro frasi più lunghe)
    rep = [
        ("Annullato.", "Canceled."),
        ("Annullato", "Canceled"),
        ("Operazione annullata.", "Operation canceled."),
        ("Operazione annullata", "Operation canceled"),
        ("Estrazione annullata.", "Extraction canceled."),
        ("Estrazione annullata", "Extraction canceled"),
    ]
    for it, en in rep:
        t = t.replace(it, en)
    return t

def _hevc__wrap_msgbox_v3():
    try:
        try:
            from PyQt5.QtWidgets import QMessageBox
        except Exception:
            from PySide6.QtWidgets import QMessageBox  # type: ignore
    except Exception:
        return

    # --- static ---
    def _wrap_static(orig):
        if getattr(orig, "_hevc_wrapped_v3", False):
            return orig
        def _wrapped(parent, title, text, *a, **k):
            if _hevc__is_cancel_like_v3(title, text):
                now = _hevc__t_v3.monotonic()
                if now - _hevc__cancel_seen_v3["t"] < 6.0:
                    try:
                        return int(QMessageBox.Ok)
                    except Exception:
                        return 0
                _hevc__cancel_seen_v3["t"] = now
                if _hevc__en_active_v3():
                    text = _hevc__translate_cancel_blob_v3(text)
            return orig(parent, title, text, *a, **k)
        _wrapped._hevc_wrapped_v3 = True
        return _wrapped

    for name in ("information", "warning", "critical"):
        try:
            o = getattr(QMessageBox, name)
            setattr(QMessageBox, name, _wrap_static(o))
        except Exception:
            pass

    # --- instance exec / exec_ ---
    def _wrap_exec(orig):
        if getattr(orig, "_hevc_exec_wrapped_v3", False):
            return orig
        def _wrapped(self, *a, **k):
            try:
                title = self.windowTitle() or ""
            except Exception:
                title = ""
            try:
                text = self.text() or ""
            except Exception:
                text = ""
            try:
                itxt = self.informativeText() or ""
            except Exception:
                itxt = ""
            try:
                dtxt = self.detailedText() or ""
            except Exception:
                dtxt = ""

            if _hevc__is_cancel_like_v3(title, text, itxt, dtxt):
                now = _hevc__t_v3.monotonic()
                if now - _hevc__cancel_seen_v3["t"] < 6.0:
                    try:
                        return int(QMessageBox.Ok)
                    except Exception:
                        return 0
                _hevc__cancel_seen_v3["t"] = now

                if _hevc__en_active_v3():
                    try:
                        self.setText(_hevc__translate_cancel_blob_v3(text))
                    except Exception:
                        pass
                    try:
                        if itxt:
                            self.setInformativeText(_hevc__translate_cancel_blob_v3(itxt))
                    except Exception:
                        pass
                    try:
                        if dtxt:
                            self.setDetailedText(_hevc__translate_cancel_blob_v3(dtxt))
                    except Exception:
                        pass

            return orig(self, *a, **k)
        _wrapped._hevc_exec_wrapped_v3 = True
        return _wrapped

    for name in ("exec_", "exec"):
        try:
            o = getattr(QMessageBox, name)
            if callable(o):
                setattr(QMessageBox, name, _wrap_exec(o))
        except Exception:
            pass

_hevc__wrap_msgbox_v3()

