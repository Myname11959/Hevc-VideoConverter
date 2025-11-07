# hevc_gui/core/chapter_worker.py

from PyQt5.QtCore import QThread, pyqtSignal
from pathlib import Path

# usa la funzione di generazione capitoli dal core
from ..core.chapter import auto_generate_chapter_file


class ChapterWorker(QThread):
    """
    Worker per generare capitoli in background, evitando di bloccare la UI.

    Signals:
        finished(str, int): percorso del file metadata, numero di capitoli
        error(str): messaggio di errore
    """

    finished = pyqtSignal(str, int)
    error = pyqtSignal(str)

    def __init__(self, input_file: Path, threshold: float):
        super().__init__()
        self.input_file = input_file
        self.threshold = threshold

    def run(self):
        try:
            # genera il file di capitoli
            meta_path = auto_generate_chapter_file(str(self.input_file), self.threshold)
            # conta sezioni [CHAPTER]
            text = Path(meta_path).read_text(encoding="utf-8")
            count = text.count("[CHAPTER]")
            self.finished.emit(meta_path, count)
        except Exception as e:
            self.error.emit(str(e))
