#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scan_deps.py — Scanner dipendenze per packaging .deb (v2)

Novità:
- Rileva i sotto-moduli PyQt5 (QtMultimedia/QtSvg/QtOpenGL/QtWebEngine) e li
  mappa ai pacchetti Debian python3-pyqt5.<subpkg> se usati.
- Mantiene il report umano, JSON e le righe per debian/control.

Esempi:
  python3 tools/scan_deps.py
  python3 tools/scan_deps.py --control
  python3 tools/scan_deps.py --control --recommends
  python3 tools/scan_deps.py --json
"""
import ast
import json
import shutil
import sys
from pathlib import Path

# ────────────────────────────────────────────────────────────────────────
# Config
# ────────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
SCAN_PATHS = [REPO_ROOT / "hevc_gui", REPO_ROOT / "scripts", REPO_ROOT / "main.py"]

# Moduli Python (root) → pacchetti Debian
PY_TO_DEB = {
    # GUI / Qt (root)
    "PyQt5": "python3-pyqt5",
    "pyqtgraph": "python3-pyqtgraph",

    # Numerics / utils
    "numpy": "python3-numpy",
    "psutil": "python3-psutil",
    "chardet": "python3-chardet",
    "requests": "python3-requests",

    # Altri comuni (aggiungi se servono nel tuo progetto)
    "PIL": "python3-pil",
    "bs4": "python3-bs4",
    "lxml": "python3-lxml",
    "yaml": "python3-yaml",
    "jinja2": "python3-jinja2",
    "matplotlib": "python3-matplotlib",
    "opencv": "python3-opencv",   # se mai userai cv2
    "cv2": "python3-opencv",
}

# Sotto-moduli PyQt5 → pacchetti Debian specifici
PYQT5_SUBMODULES_TO_DEB = {
    "PyQt5.QtMultimedia": "python3-pyqt5.qtmultimedia",
    "PyQt5.QtSvg": "python3-pyqt5.qtsvg",
    "PyQt5.QtOpenGL": "python3-pyqt5.qtopengl",
    "PyQt5.QtWebEngineWidgets": "python3-pyqt5.qtwebengine",
    # aggiungi qui eventuali altri sotto-moduli se li userai
}

# Binari di sistema richiesti (Depends)
REQUIRED_BINS = {
    "ffmpeg": ("ffmpeg", "ffmpeg"),
    "ffprobe": ("ffprobe", "ffmpeg"),
    "ffplay": ("ffplay", "ffmpeg"),
}

# Binari consigliati (Recommends)
RECOMMENDED_BINS = {
    "gnome-terminal": ("gnome-terminal", "gnome-terminal"),
    "cpulimit": ("cpulimit", "cpulimit"),
    "ionice": ("ionice", "util-linux"),
    "nice": ("nice", "coreutils"),
}

# ────────────────────────────────────────────────────────────────────────
# Util
# ────────────────────────────────────────────────────────────────────────

def is_stdlib(mod: str) -> bool:
    try:
        std = sys.stdlib_module_names  # py>=3.10
        return mod in std
    except Exception:
        return mod in {
            "sys","os","re","json","pathlib","shutil","subprocess","logging","time","signal",
            "threading","queue","math","itertools","functools","typing","dataclasses","ast",
            "argparse","textwrap","tempfile","datetime",
        }

def discover_python_files(paths) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        p = Path(p)
        if p.is_file() and p.suffix == ".py":
            files.append(p)
        elif p.is_dir():
            files += [f for f in p.rglob("*.py")]
    return files

def root_name(module: str) -> str:
    return module.split(".", 1)[0]

def is_local_module(modname: str, repo_root: Path) -> bool:
    if is_stdlib(modname):
        return False
    # Se esiste file o package nel repo, lo consideriamo "locale"
    pat_file = list(repo_root.rglob(f"{modname}.py"))
    pat_pkg = list(repo_root.rglob(f"{modname}/__init__.py"))
    return bool(pat_file or pat_pkg)

def discover_imports(paths) -> tuple[set[str], set[str]]:
    """
    Ritorna (mods_root, mods_full):
      - mods_root: 'numpy', 'PyQt5', ...
      - mods_full: 'PyQt5.QtMultimedia', 'pyqtgraph', ...
    """
    mods_root: set[str] = set()
    mods_full: set[str] = set()

    for py in discover_python_files(paths):
        try:
            src = py.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(src, filename=str(py))
        except Exception:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mods_full.add(alias.name)
                    mods_root.add(root_name(alias.name))
            elif isinstance(node, ast.ImportFrom):
                if getattr(node, "level", 0):
                    continue  # ignore relativi
                if node.module:
                    mods_full.add(node.module)
                    mods_root.add(root_name(node.module))
    return mods_root, mods_full

def map_python_to_deb(mods_root: set[str], mods_full: set[str]) -> tuple[list[str], list[str]]:
    """
    Mappa moduli terze parti a pacchetti Debian.
    - Gestisce sia mapping 'root' (PyQt5 → python3-pyqt5) sia sotto-moduli Qt
      (PyQt5.QtMultimedia → python3-pyqt5.qtmultimedia).
    Ritorna (pacchetti_mappati, moduli_ignoti_terze_parti).
    """
    pkgs: set[str] = set()
    unknown: set[str] = set()

    # Filtra stdlib e locali sul set root
    third_party_roots = {m for m in mods_root if not is_stdlib(m) and not is_local_module(m, REPO_ROOT)}

    # 1) mapping root
    for m in third_party_roots:
        deb = PY_TO_DEB.get(m)
        if deb:
            pkgs.add(deb)
        else:
            # potrebbe essere terza parte non mappata
            unknown.add(m)

    # 2) mapping sotto-moduli PyQt5 (lavoriamo sul set "full")
    for fm in mods_full:
        if fm.startswith("PyQt5.") and fm in PYQT5_SUBMODULES_TO_DEB:
            pkgs.add(PYQT5_SUBMODULES_TO_DEB[fm])

    # Se un root è 'PyQt5' e abbiamo trovato anche un sotto-modulo, entrambe
    # le dipendenze verranno riportate (base + subpkg).
    return sorted(pkgs), sorted(unknown)

def check_bins(bins_map: dict[str, tuple[str, str]]) -> list[tuple[str, str, bool]]:
    out = []
    for disp, (bin_name, deb_pkg) in bins_map.items():
        present = shutil.which(bin_name) is not None
        out.append((disp, deb_pkg, present))
    return out

def print_text_report(py_roots: set[str],
                      deb_pkgs: list[str],
                      unknown_mods: list[str],
                      req_bins: list[tuple[str, str, bool]],
                      rec_bins: list[tuple[str, str, bool]]) -> None:
    print("=== Dipendenze Python (moduli importati, escludendo stdlib e moduli locali) ===")
    if deb_pkgs:
        print("  " + ", ".join(sorted(set(deb_pkgs))))
    else:
        print("  (nessuna terza parte individuata)")

    if unknown_mods:
        print("\n=== Moduli Python non mappati → valuta se sono terze parti da aggiungere a PY_TO_DEB ===")
        for m in unknown_mods:
            print(f"  - {m}")

    def _fmt_bins(bins):
        return "\n".join([f"  - {name:15s} [{deb}]  → {'OK' if ok else 'MANCANTE'}" for name, deb, ok in bins])

    print("\n=== Strumenti di sistema (Depends) ===")
    print(_fmt_bins(req_bins))

    print("\n=== Strumenti consigliati (Recommends) ===")
    print(_fmt_bins(rec_bins))

    # Comandi apt suggeriti
    apt_py = " ".join(sorted(set(deb_pkgs)))
    apt_req = " ".join(sorted({deb for _, deb, _ in req_bins}))
    rec_missing = [deb for _, deb, ok in rec_bins if not ok]
    apt_rec = " ".join(sorted(set(rec_missing)))

    print("\nSuggerimento installazione (minimo):")
    base_cmd = "sudo apt update && sudo apt install -y python3"
    if apt_py:
        base_cmd += f" {apt_py}"
    if apt_req:
        base_cmd += f" {apt_req}"
    print("  " + base_cmd)

    if apt_rec:
        print("\nSuggerimento (consigliati, se non presenti):")
        print("  sudo apt install -y " + apt_rec)

def print_control_lines(deb_pkgs: list[str],
                        req_bins: list[tuple[str, str, bool]],
                        rec_bins: list[tuple[str, str, bool]],
                        include_recommends: bool = False) -> None:
    depends = ["python3", *sorted(set(deb_pkgs)), *sorted({deb for _, deb, _ in req_bins})]
    print("Depends: " + ", ".join(depends))
    if include_recommends:
        rec = sorted({deb for _, deb, _ in rec_bins})
        if rec:
            print("Recommends: " + ", ".join(rec))

def main():
    import argparse
    ap = argparse.ArgumentParser(description="Scanner dipendenze per packaging .deb (v2)")
    ap.add_argument("--json", action="store_true", help="Output in JSON")
    ap.add_argument("--control", action="store_true", help="Stampa righe per debian/control")
    ap.add_argument("--recommends", action="store_true", help="Includi anche Recommends (solo con --control)")
    args = ap.parse_args()

    mods_root, mods_full = discover_imports(SCAN_PATHS)
    deb_pkgs, unknown_mods = map_python_to_deb(mods_root, mods_full)
    req_bins = check_bins(REQUIRED_BINS)
    rec_bins = check_bins(RECOMMENDED_BINS)

    if args.json:
        data = {
            "python_root_modules": sorted(mods_root),
            "python_full_modules": sorted(mods_full),
            "python_debian_packages": sorted(set(deb_pkgs)),
            "python_unknown_modules": unknown_mods,
            "required_binaries": [{"name": n, "deb": d, "present": ok} for (n, d, ok) in req_bins],
            "recommended_binaries": [{"name": n, "deb": d, "present": ok} for (n, d, ok) in rec_bins],
            "depends_line": {
                "Depends": ["python3", *sorted(set(deb_pkgs)), *sorted({deb for _, deb, _ in req_bins})],
                "Recommends": sorted({deb for _, deb, _ in rec_bins}),
            },
        }
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return

    if args.control:
        print_control_lines(deb_pkgs, req_bins, rec_bins, include_recommends=args.recommends)
        return

    print_text_report(mods_root, deb_pkgs, unknown_mods, req_bins, rec_bins)

if __name__ == "__main__":
    main()
