# -*- coding: utf-8 -*-
from __future__ import annotations
from .constants import TMP_DIR
import json
import hashlib

QUEUE_FILE = TMP_DIR / "queue.json"


# ── utilità interna ---------------------------------------------------------
def _digest(cmd: list[str]) -> str:
    """Hash SHA-1 del comando per confronto rapido."""
    # Uniamo gli argomenti con uno spazio e calcoliamo SHA-1 in UTF-8
    return hashlib.sha1(" ".join(cmd).encode("utf-8")).hexdigest()


# ── API pubblica ------------------------------------------------------------


def load() -> list[list[str]]:
    """Carica la coda da file JSON, restituisce lista di comandi."""
    if not QUEUE_FILE.exists():
        return []
    try:
        # Lettura e parsing JSON con protezione da errori I/O
        data = QUEUE_FILE.read_text(encoding="utf-8")
        return json.loads(data)
    except (json.JSONDecodeError, OSError):
        # Se JSON malformato o errore I/O, restituisco lista vuota
        return []


def save(queue: list[list[str]]) -> None:
    """Salva la coda su file JSON in modo atomico."""
    # Assicuriamoci che la directory esista
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Scriviamo su file temporaneo e poi sostituiamo
    temp_file = QUEUE_FILE.with_suffix(".json.tmp")
    with temp_file.open("w", encoding="utf-8") as f:
        json.dump(queue, f, indent=2, ensure_ascii=False)
    temp_file.replace(QUEUE_FILE)


def add(cmd: list[str]) -> bool:
    """
    Aggiunge *cmd* alla coda.
    Ritorna True se è stato aggiunto (non duplicato),
    False se già presente.
    """
    # Assicuriamoci che tutti gli elementi siano stringhe
    cmd = [str(x) for x in cmd]
    queue = load()
    existing = {_digest(c) for c in queue}
    d = _digest(cmd)
    if d in existing:
        return False
    queue.append(cmd)
    save(queue)
    return True


def remove(cmd: list[str]) -> bool:
    """
    Rimuove *cmd* dalla coda se presente.
    Ritorna True se rimosso, False se non trovato.
    """
    queue = load()
    d = _digest([str(x) for x in cmd])
    new_q = [c for c in queue if _digest(c) != d]
    if len(new_q) == len(queue):
        return False
    save(new_q)
    return True


def clear() -> None:
    """Cancella completamente il file di coda."""
    try:
        QUEUE_FILE.unlink()
    except FileNotFoundError:
        pass
