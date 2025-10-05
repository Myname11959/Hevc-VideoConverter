# -*- coding: utf-8 -*-
# hevc_gui/core/dblclick.py

from __future__ import annotations

from PyQt5.QtCore import QObject, QEvent
from PyQt5.QtWidgets import (
    QWidget,
    QDialog,
    QComboBox,
    QListWidget,
    QTreeWidget,
    QTableWidget,
    QListView,
    QTreeView,
    QTableView,
)


# -------------------------
# 1) QComboBox: doppio clic = chiudi popup (+ callback opzionale)
# -------------------------
class _ComboDblConfirm(QObject):
    """
    Aggancia il doppio click su una QComboBox:
      - chiude il popup
      - chiama on_confirm (se fornita)
    """

    def __init__(self, combo: QComboBox, on_confirm=None):
        super().__init__(combo)
        self.combo = combo
        self.on_confirm = on_confirm

        # ascolta sia sul viewport della lista interna che sulla combo
        try:
            view = combo.view()
        except Exception:
            view = None
        if view is not None:
            try:
                view.viewport().installEventFilter(self)
            except Exception:
                pass
        combo.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.MouseButtonDblClick:
            try:
                self.combo.hidePopup()
            except Exception:
                pass
            if callable(self.on_confirm):
                try:
                    self.on_confirm(self.combo.currentIndex())
                except TypeError:
                    # tollera on_confirm() senza argomenti
                    self.on_confirm()
            return True
        return False


def enable_doubleclick_confirm(combo: QComboBox, on_confirm=None) -> None:
    """
    Abilita 'doppio clic = conferma' su una singola QComboBox.
    Evita duplicati tenendo una ref sull'oggetto filtro.
    """
    if getattr(combo, "_dbl_listener", None) is None:
        filt = _ComboDblConfirm(combo, on_confirm)
        # salva una ref sull'istanza per evitare il GC e doppi attach
        combo._dbl_listener = filt  # type: ignore[attr-defined]


def enable_doubleclick_on_children(widget: QWidget, overrides: dict | None = None) -> None:
    """
    Abilita il doppio clic su TUTTE le QComboBox figlie di 'widget'.
    overrides: dict {objectName: on_confirm_callable}
    """
    for cb in widget.findChildren(QComboBox):
        name = cb.objectName() or ""
        cbfunc = overrides.get(name) if overrides else None
        enable_doubleclick_confirm(cb, cbfunc)


# -------------------------
# 2) Liste/Tree/Table: doppio clic = dialog.accept()
#     (usato per la scelta sottotitoli)
# -------------------------
def _find_parent_dialog(w: QWidget) -> QDialog | None:
    p = w
    while p is not None:
        if isinstance(p, QDialog):
            return p
        p = p.parent()
    return None


def enable_list_doubleclick_accept(container: QWidget) -> None:
    """
    In qualsiasi QList*/QTree*/QTable* (widget o view) figlio di 'container',
    il doppio clic equivale a premere OK (dialog.accept()).

    Da usare nel costruttore del dialog di scelta sottotitoli,
    subito dopo aver creato e popolato i widget di lista.
    """
    def _connect_accept(emitter: QWidget, signal_name: str) -> None:
        dlg = _find_parent_dialog(emitter)
        if not dlg:
            return
        sig = getattr(emitter, signal_name, None)
        if sig is None:
            return
        # evita doppi collegamenti
        if getattr(emitter, "_dbl_accept_connected", False):
            return
        try:
            sig.connect(lambda *_, d=dlg: d.accept())
            setattr(emitter, "_dbl_accept_connected", True)
        except Exception:
            pass

    # Widget "convenience" (item-based)
    for w in container.findChildren(QListWidget):
        _connect_accept(w, "itemDoubleClicked")
    for w in container.findChildren(QTreeWidget):
        _connect_accept(w, "itemDoubleClicked")
    for w in container.findChildren(QTableWidget):
        _connect_accept(w, "cellDoubleClicked")

    # View model-based
    for v in container.findChildren(QListView):
        _connect_accept(v, "doubleClicked")
    for v in container.findChildren(QTreeView):
        _connect_accept(v, "doubleClicked")
    for v in container.findChildren(QTableView):
        _connect_accept(v, "doubleClicked")
