#!/usr/bin/env python3
import re
from pathlib import Path

# Mappatura modulo Python → pacchetto Debian
PYTHON_TO_DEB = {
    "PyQt5": "python3-pyqt5",
    "chardet": "python3-chardet",
    "requests": "python3-requests",
    "PIL": "python3-pil",
    "bs4": "python3-bs4",
    "lxml": "python3-lxml",
    "numpy": "python3-numpy",
    "psutil": "python3-psutil",
    "yaml": "python3-yaml",
    "jinja2": "python3-jinja2",
    "matplotlib": "python3-matplotlib",
    # aggiungine altri se necessario
}


def scan_imports(root_dir: Path) -> set[str]:
    found = set()
    for path in root_dir.rglob("*.py"):
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                m1 = re.match(r"^import (\w+)", line)
                m2 = re.match(r"^from (\w+)", line)
                if m1:
                    found.add(m1.group(1))
                elif m2:
                    found.add(m2.group(1))
    return found


def map_to_debian(modules: set[str]) -> list[str]:
    pkgs = set()
    for mod in modules:
        deb = PYTHON_TO_DEB.get(mod)
        if deb:
            pkgs.add(deb)
    return sorted(pkgs)


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent / "hevc_gui"
    modules = scan_imports(base_dir)
    debian_packages = map_to_debian(modules)

    print("📦 Pacchetti Debian richiesti:")
    print("python3,", ", ".join(debian_packages))
