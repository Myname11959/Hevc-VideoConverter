# -*- coding: utf-8 -*-
from __future__ import annotations

def attach_track_editor(dlg, tr):
    """Editor riga (OK/Annulla) per la lista tracce in SAG/AudioConverter.
    IMPORTANTISSIMO: questo modulino NON deve MAI toccare btn_add.
    """
    if dlg is None:
        return
    if getattr(dlg, "_sag_track_editor_attached", False):
        return
    dlg._sag_track_editor_attached = True
    dlg._sag_tr = tr

    from PyQt5 import QtGui, QtWidgets

    lw = getattr(dlg, "list", None)
    if lw is None or not isinstance(lw, QtWidgets.QListWidget):
        kids = dlg.findChildren(QtWidgets.QListWidget)
        lw = kids[0] if kids else None
    if lw is None:
        return

    def _edit_item(item):
        if item is None:
            return
        try:
            old = item.text()
        except Exception:
            return

        d = QtWidgets.QDialog(dlg)
        d.setWindowTitle(tr("Modifica traccia"))
        d.setModal(True)
        lay = QtWidgets.QVBoxLayout(d)
        lay.addWidget(QtWidgets.QLabel(tr("Modifica la stringa completa e premi OK.")))

        edit = QtWidgets.QPlainTextEdit(d)
        edit.setPlainText(old)
        try:
            edit.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        except Exception:
            pass
        try:
            f = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
            edit.setFont(f)
        except Exception:
            pass
        lay.addWidget(edit)

        box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, parent=d)
        try:
            box.button(QtWidgets.QDialogButtonBox.Ok).setText(tr("OK"))
            box.button(QtWidgets.QDialogButtonBox.Cancel).setText(tr("Annulla"))
        except Exception:
            pass
        box.accepted.connect(d.accept)
        box.rejected.connect(d.reject)
        lay.addWidget(box)

        try:
            edit.setFocus()
            edit.selectAll()
        except Exception:
            pass

        if d.exec_() != QtWidgets.QDialog.Accepted:
            return

        new = edit.toPlainText().rstrip("\n")
        new = " ".join(new.splitlines()).strip()
        if not new or new == old:
            return

        try:
            item.setText(new)
        except Exception:
            pass

        # best-effort: aggiorna eventuali liste interne, senza assumere nomi
        try:
            row = lw.row(item)
            n = lw.count()
        except Exception:
            row = -1
            n = -1

        if row >= 0 and n > 0:
            for k, v in list(getattr(dlg, "__dict__", {}).items()):
                try:
                    if isinstance(v, list) and len(v) == n and row < len(v):
                        if isinstance(v[row], str) and v[row] == old:
                            v[row] = new
                        elif isinstance(v[row], dict):
                            for kk in ("cmd", "line", "text", "value"):
                                if v[row].get(kk) == old:
                                    v[row][kk] = new
                except Exception:
                    pass

        for name in ("refresh","update_preview","update_cmd","update_output","_update_preview","_update_output","_update_buttons","update_buttons"):
            try:
                fn = getattr(dlg, name, None)
                if callable(fn):
                    fn()
            except Exception:
                pass

    try:
        lw.itemClicked.connect(_edit_item)
        lw.itemActivated.connect(_edit_item)
    except Exception:
        pass
