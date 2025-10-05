# -*- coding: utf-8 -*-
from __future__ import annotations
from PyQt5.QtWidgets import QProgressBar, QStyleOptionProgressBar, QStyle
from PyQt5.QtGui import QPainter


class ProgressBarNoZeroChunk(QProgressBar):
    """
    ProgressBar che non rimane “vuota” (0 %) quando c’è un avanzamento minimo:
    disegna sempre almeno 1px di chunk se value > 0.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

    def paintEvent(self, event):
        # 1. Prepara le opzioni standard
        opt = QStyleOptionProgressBar()
        self.initStyleOption(opt)

        painter = QPainter(self)

        # 2. Disegna l'intera barra (sfondo + chunk, se value>0)
        self.style().drawControl(QStyle.CE_ProgressBar, opt, painter, self)

        # 3. Se value>0 ma il chunk non è visibile, disegna un pixel minimo
        if 0 < self.value() < self.maximum() and self.value() * (self.width() - 2) // self.maximum() < 1:
            # Calcola il rettangolo di "contents" (il chunk)
            chunk_rect = self.style().subControlRect(QStyle.CC_ProgressBar, opt, QStyle.SC_ProgressBarContents, self)
            # Assicura almeno 1px di larghezza
            chunk_rect.setWidth(1)
            # Riempi con il colore di highlight (come farebbe il tema)
            painter.fillRect(chunk_rect, opt.palette.highlight())

        painter.end()
