# -*- coding: utf-8 -*-
# hevc_gui/core/dblclick.py

from PyQt5.QtCore import QObject, QEvent
from PyQt5.QtWidgets import QComboBox, QWidget


class _ComboDblConfirm(QObject):
    """Aggancia il doppio click su una QComboBox: chiude il popup e chiama on_confirm (se dato)."""

    def __init__(self, combo: QComboBox, on_confirm=None):
        super().__init__(combo)
        self.combo = combo
        self.on_confirm = on_confirm
        # ascolta sia sul view-port della lista che sulla combo stessa
        try:
            view = combo.view()
            if view is not None:
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
                    self.on_confirm()
            return True
        return False


def enable_doubleclick_confirm(combo: QComboBox, on_confirm=None) -> None:
    """Abilita 'doppio click = conferma' su una singola combo."""
    _ComboDblConfirm(combo, on_confirm)


def enable_doubleclick_on_children(widget: QWidget, overrides: dict | None = None) -> None:
    """
    Abilita il doppio click su TUTTE le QComboBox figlie di widget.
    overrides: dict {objectName: on_confirm_callable} per associare callback a combo specifiche.
    """
    for cb in widget.findChildren(QComboBox):
        cbname = cb.objectName() or ""
        cbfunc = overrides.get(cbname) if overrides else None
        enable_doubleclick_confirm(cb, cbfunc)
