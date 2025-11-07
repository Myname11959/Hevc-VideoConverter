#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scansione dei moduli Python del progetto e rilevazione di file non raggiunti
a partire dagli entry-point (default: main.py).

- Analizza import assoluti e relativi via AST.
- Risolve i relativi in base al modulo corrente (p.es. from .menubar import ...).
- Considera "scripts/" come top-level importabile (come fa main_window.py).
- Esclude cartelle: backup/, tests/, __pycache__/, logs/, .git, .github

Uso:
  python3 tools/find_unused_modules.py
  python3 tools/find_unused_modules.py --start main.py hevc_gui/gui/test_standalone.py
"""
from __future__ import annotations
import argparse, ast, sys
from pathlib import Path

EXCLUDE_DIRS = {"backup", "tests", "__pycache__", "logs", ".git", ".github"}
PROJECT_ROOT = Path(__file__).resolve().parent.parent

PKG_DIRS = ["hevc_gui", "scripts"]  # scope di analisi

def is_excluded(p: Path) -> bool:
    parts = set(p.parts)
    return bool(parts & EXCLUDE_DIRS)

def py_files_under(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if not is_excluded(p)]

def dotted_module_name(p: Path) -> str | None:
    """Converte un path file in nome-modulo puntato (p.es. hevc_gui.core.helpers)."""
    rel = p.relative_to(PROJECT_ROOT)
    if rel.parts[0] not in ("hevc_gui", "scripts"):
        # fuori scope (p.es. main.py rimane 'main')
        if rel.name == "main.py":
            return "main"
        return None
    parts = list(rel.parts)
    parts[-1] = parts[-1].removesuffix(".py")
    return ".".join(parts)

def resolve_relative(curr_mod: str, level: int, module: str | None) -> str | None:
    """
    Risolve import relativo: in curr_mod='hevc_gui.gui.main_window',
    level=1, module='menubar' -> 'hevc_gui.gui.menubar'
    """
    base_parts = curr_mod.split(".")
    if level > len(base_parts):
        return None
    pkg = base_parts[: len(base_parts) - level]
    if module:
        return ".".join(pkg + module.split("."))
    return ".".join(pkg) if pkg else None

def parse_imports(py: Path, curr_mod: str) -> set[str]:
    txt = py.read_text(encoding="utf-8", errors="ignore")
    try:
        tree = ast.parse(txt, filename=str(py))
    except SyntaxError:
        return set()
    seen: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                seen.add(alias.name)  # es. 'hevc_gui.core.helpers' o 'string_audio_generator'
        elif isinstance(node, ast.ImportFrom):
            # node.module può essere None (from . import x)
            if node.level and (curr_mod is not None):
                base = resolve_relative(curr_mod, node.level, node.module)
                if base:
                    seen.add(base)
                # from . import x,y → aggiungi ciascuno come base.x
                if base and node.names and node.module is None:
                    for a in node.names:
                        seen.add(base + "." + a.name)
            else:
                if node.module:
                    seen.add(node.module)
    return seen

def build_index():
    all_files = []
    for d in PKG_DIRS:
        root = PROJECT_ROOT / d
        if root.is_dir():
            all_files.extend(py_files_under(root))
    # aggiungi main.py (entry point)
    mp = PROJECT_ROOT / "main.py"
    if mp.exists():
        all_files.append(mp)

    module_by_file = {}
    file_by_module = {}
    # mappa extra per "scripts": modulo nudo → file (es. 'string_audio_generator' -> scripts/string_audio_generator.py)
    bare_to_file = {}

    for f in all_files:
        mod = dotted_module_name(f)
        if mod:
            module_by_file[f] = mod
            file_by_module[mod] = f
            # se è in scripts/, aggiungi anche la chiave "nuda"
            if f.parts[0] == "scripts" or (len(f.parts) > 1 and f.parts[0] != "hevc_gui" and f.parts[1:2] == ["scripts"]):
                bare_to_file[f.stem] = f

    return file_by_module, module_by_file, bare_to_file

def normalize_to_known(mod: str, known: set[str], bare_map: dict[str, Path]) -> str | None:
    """Restituisce il modulo noto più vicino (stessa radice/prefix) o None."""
    # Match esatto
    if mod in known:
        return mod
    # Prova progressivamente a ridurre 'a.b.c' -> 'a.b'
    parts = mod.split(".")
    while len(parts) > 1:
        parts = parts[:-1]
        mk = ".".join(parts)
        if mk in known:
            return mk
    # Se è un modulo nudo e c'è in scripts/
    if mod in bare_map:
        # es. 'string_audio_generator' → 'scripts.string_audio_generator'
        return "scripts." + mod
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", nargs="*", default=["main.py"], help="entry points (file .py o moduli puntati)")
    args = ap.parse_args()

    file_by_module, module_by_file, bare_map = build_index()
    known_modules = set(file_by_module.keys())

    # Entry modules
    entry_mods: set[str] = set()
    for s in args.start:
        if s.endswith(".py"):
            p = (PROJECT_ROOT / s).resolve()
            mod = dotted_module_name(p) if p.exists() else None
        else:
            mod = s
        if mod and mod in known_modules:
            entry_mods.add(mod)
        elif mod == "main" and (PROJECT_ROOT / "main.py").exists():
            entry_mods.add("main")

    # Build import graph
    deps: dict[str, set[str]] = {m: set() for m in known_modules}
    for f, curr_mod in module_by_file.items():
        imps = parse_imports(f, curr_mod)
        for raw in imps:
            nm = normalize_to_known(raw, known_modules, bare_map)
            if nm:
                deps[curr_mod].add(nm)

    # Reachability (DFS)
    reachable = set()

    def dfs(m: str):
        if m in reachable:
            return
        reachable.add(m)
        for dep in deps.get(m, ()):
            dfs(dep)

    for m in entry_mods or {"main"}:
        dfs(m)

    unused = sorted(known_modules - reachable)

    # Heuristica: filtra __init__.py dai "non usati" se il pacchetto ha altri file usati
    filtered = []
    for m in unused:
        p = file_by_module[m]
        if p.name == "__init__.py":
            # se nello stesso pacchetto c'è roba usata, ignora
            pkg = p.parent
            if any((file_by_module.get(dotted_module_name(x) or "") in reachable) for x in pkg.glob("*.py")):
                continue
        filtered.append(m)

    print("== Unused (probabili) ==")
    for m in filtered:
        print(" -", file_by_module[m].relative_to(PROJECT_ROOT))

    # Segnala dinamici per prudenza
    dyn_hits = []
    for f in module_by_file:
        t = f.read_text(encoding="utf-8", errors="ignore")
        if any(k in t for k in ("importlib.import_module", "__import__(", "sys.path.insert(", "QPluginLoader(")):
            dyn_hits.append(f.relative_to(PROJECT_ROOT))
    if dyn_hits:
        print("\n== Avviso: import dinamici rilevati in ==")
        for p in dyn_hits:
            print(" -", p)

if __name__ == "__main__":
    sys.exit(main())
