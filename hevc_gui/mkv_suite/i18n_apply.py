from __future__ import annotations

from PyQt5.QtCore import QObject, QEvent
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QWidget,
    QLabel,
    QAbstractButton,
    QGroupBox,
    QLineEdit,
    QTabWidget,
    QTableWidget,
    QTreeWidget,
    QComboBox,
    QTextBrowser,
    QTextEdit,
)

from hevc_gui.mkv_suite.i18n import L, LT, get_lang, LANG_EN


def _tr(s: str) -> str:
    if not isinstance(s, str) or not s:
        return s
    return L(s)


def _set_if_changed(getter, setter, keep_amp: bool = True) -> None:
    try:
        s = getter()
    except Exception:
        return
    if not isinstance(s, str) or not s:
        return

    base = s.replace("&", "") if keep_amp else s
    t = _tr(base)

    # ripristina & (buono abbastanza) se c'era
    if keep_amp and "&" in s and t == base:
        t = "&" + t

    if t != s:
        try:
            setter(t)
        except Exception:
            pass


def apply_to_widget_tree(root: QObject) -> None:
    # traduci solo in EN
    try:
        if get_lang() != LANG_EN:
            return
    except Exception:
        return

    # QAction (menu/toolbar)
    try:
        for act in root.findChildren(QAction):
            _set_if_changed(act.text, act.setText, keep_amp=True)
            _set_if_changed(act.toolTip, act.setToolTip, keep_amp=False)
            _set_if_changed(act.statusTip, act.setStatusTip, keep_amp=False)
            _set_if_changed(act.whatsThis, act.setWhatsThis, keep_amp=False)
    except Exception:
        pass

    # Widgets
    try:
        for w in root.findChildren(QWidget):
            _set_if_changed(w.windowTitle, w.setWindowTitle, keep_amp=True)
            _set_if_changed(w.toolTip, w.setToolTip, keep_amp=False)
            _set_if_changed(w.statusTip, w.setStatusTip, keep_amp=False)
            _set_if_changed(w.whatsThis, w.setWhatsThis, keep_amp=False)

            if isinstance(w, QLabel):
                _set_if_changed(w.text, w.setText, keep_amp=False)

            if isinstance(w, QAbstractButton):
                _set_if_changed(w.text, w.setText, keep_amp=True)

            if isinstance(w, QGroupBox):
                _set_if_changed(w.title, w.setTitle, keep_amp=False)

            if isinstance(w, QLineEdit):
                _set_if_changed(w.placeholderText, w.setPlaceholderText, keep_amp=False)

            if isinstance(w, QTabWidget):
                try:
                    for i in range(w.count()):
                        s = w.tabText(i)
                        base = s.replace("&", "")
                        t = _tr(base)
                        if "&" in s and t == base:
                            t = "&" + t
                        if t != s:
                            w.setTabText(i, t)
                except Exception:
                    pass

            if isinstance(w, QComboBox):
                try:
                    for i in range(w.count()):
                        s = w.itemText(i)
                        t = _tr(s)
                        if t != s:
                            w.setItemText(i, t)
                except Exception:
                    pass

            if isinstance(w, QTableWidget):
                try:
                    for i in range(w.columnCount()):
                        it = w.horizontalHeaderItem(i)
                        if it:
                            s = it.text()
                            t = _tr(s)
                            if t != s:
                                it.setText(t)
                    for i in range(w.rowCount()):
                        it = w.verticalHeaderItem(i)
                        if it:
                            s = it.text()
                            t = _tr(s)
                            if t != s:
                                it.setText(t)
                except Exception:
                    pass

            if isinstance(w, QTreeWidget):
                try:
                    hi = w.headerItem()
                    if hi:
                        for i in range(hi.columnCount()):
                            s = hi.text(i)
                            t = _tr(s)
                            if t != s:
                                hi.setText(i, t)
                except Exception:
                    pass

            # Manuale HTML (QTextBrowser/QTextEdit)
            if isinstance(w, (QTextBrowser, QTextEdit)):
                try:
                    html = w.toHtml()
                    new_html = LT(html)
                    if new_html != html:
                        w.setHtml(new_html)
                except Exception:
                    pass
    except Exception:
        pass


class _I18nEventFilter(QObject):
    def eventFilter(self, obj: QObject, ev: QEvent) -> bool:
        try:
            if ev.type() in (QEvent.Show, QEvent.Polish, QEvent.ShowToParent):
                if isinstance(obj, QWidget):
                    apply_to_widget_tree(obj)
        except Exception:
            pass
        return False


def install_auto_translator(app: QApplication) -> None:
    try:
        if get_lang() != LANG_EN:
            return
    except Exception:
        return

    f = _I18nEventFilter(app)
    app.installEventFilter(f)
    app._i18n_filter = f  # type: ignore[attr-defined]
