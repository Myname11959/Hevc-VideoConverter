from pathlib import Path

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QFrame


class InputDropFrame(QFrame):
    filesDropped = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        md = event.mimeData()
        if md and md.hasUrls() and any(url.isLocalFile() for url in md.urls()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event):
        md = event.mimeData()
        if md and md.hasUrls() and any(url.isLocalFile() for url in md.urls()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event):
        md = event.mimeData()
        if not md or not md.hasUrls():
            event.ignore()
            return

        paths = []
        for url in md.urls():
            if not url.isLocalFile():
                continue
            p = Path(url.toLocalFile())
            if p.exists():
                paths.append(str(p))

        if not paths:
            event.ignore()
            return

        event.acceptProposedAction()
        self.filesDropped.emit(paths)
