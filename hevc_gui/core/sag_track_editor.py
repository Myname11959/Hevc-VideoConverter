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

    from PyQt5 import QtCore, QtGui, QtWidgets

    lw = getattr(dlg, "list", None)
    if lw is None or not isinstance(lw, QtWidgets.QListWidget):
        kids = dlg.findChildren(QtWidgets.QListWidget)
        lw = kids[0] if kids else None
    if lw is None:
        return


    # ───────────────────────────────────────────────────────────────
    # HEVC_SAG_EDITOR_DELETE_EMPTY_V1
    # - Se l'editor viene salvato vuoto => elimina la riga (come 'Elimina selezionate')
    # - Menu tasto destro sulla lista: Modifica… / Elimina
    # ───────────────────────────────────────────────────────────────
    def _delete_rows(rows):
        if not rows:
            return
        try:
            rows = sorted(set(int(r) for r in rows), reverse=True)
        except Exception:
            return

        for r in rows:
            # n prima della cancellazione (serve per poppare liste interne)
            try:
                n = int(lw.count())
            except Exception:
                n = -1

            try:
                it = lw.item(r)
                old_txt = it.text() if it is not None else ""
            except Exception:
                old_txt = ""

            # rimuovi dalla UI
            try:
                lw.takeItem(r)
            except Exception:
                pass

            # caso principale: batch.items
            try:
                batch = getattr(dlg, "batch", None)
                items = getattr(batch, "items", None) if batch is not None else None
                if isinstance(items, list) and n > 0 and len(items) == n and 0 <= r < len(items):
                    items.pop(r)
            except Exception:
                pass

            # best-effort: altre liste interne allineate alla QListWidget
            try:
                dct = getattr(dlg, "__dict__", {}) or {}
                for k, v in list(dct.items()):
                    try:
                        if isinstance(v, list) and n > 0 and len(v) == n and 0 <= r < len(v):
                            cur = v[r]
                            if isinstance(cur, str):
                                if cur == old_txt:
                                    v.pop(r)
                            elif isinstance(cur, dict):
                                for kk in ("cmd", "line", "text", "value"):
                                    if cur.get(kk) == old_txt:
                                        v.pop(r)
                                        break
                    except Exception:
                        continue
            except Exception:
                pass

        # refresh best-effort
        for name in ("refresh","update_preview","update_cmd","update_output","_update_preview","_update_output","_update_buttons","update_buttons"):
            try:
                fn = getattr(dlg, name, None)
                if callable(fn):
                    fn()
            except Exception:
                pass

    def _delete_item(item):
        if item is None:
            return
        try:
            r = lw.row(item)
        except Exception:
            return
        if r < 0:
            return
        _delete_rows([r])

    def _on_ctx_menu(pos):
        try:
            it = lw.itemAt(pos)
        except Exception:
            it = None

        # click destro su riga non selezionata => selezionala
        try:
            if it is not None and not it.isSelected():
                lw.clearSelection()
                it.setSelected(True)
                lw.setCurrentItem(it)
        except Exception:
            pass

        menu = QtWidgets.QMenu(lw)
        act_edit = menu.addAction(tr("Modifica…"))
        act_del = menu.addAction(tr("Elimina"))
        act_del.setEnabled(bool(lw.selectedItems()) or it is not None)

        chosen = menu.exec_(lw.mapToGlobal(pos))
        if chosen == act_edit:
            _edit_item(it or lw.currentItem())
        elif chosen == act_del:
            try:
                sel = lw.selectedItems()
                if sel:
                    _delete_rows([lw.row(x) for x in sel])
                else:
                    _delete_item(it)
            except Exception:
                pass

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

        # se l'utente 'sbianca' => elimina la riga
        if not new:
            try:
                _delete_item(item)
            except Exception:
                pass
            return

        if new == old:
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
        lw.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        lw.customContextMenuRequested.connect(_on_ctx_menu)
    except Exception:
        pass
