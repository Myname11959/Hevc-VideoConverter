# settings.py
from PyQt5.QtCore import QSettings

SETTINGS = QSettings("LorisPaganiniHomeStudio", "HEVC VideoConverter")


def save_appearance(style: str, font_family: str, font_size: int, icon_theme: str):
    SETTINGS.setValue("appearance/style", style)
    SETTINGS.setValue("appearance/font_family", font_family)
    SETTINGS.setValue("appearance/font_size", font_size)
    SETTINGS.setValue("appearance/icon_theme", icon_theme)


def load_appearance():
    style = SETTINGS.value("appearance/style", type=str) or "Fusion"
    family = SETTINGS.value("appearance/font_family", type=str) or "Roboto"
    size = SETTINGS.value("appearance/font_size", type=int) or 10
    icon_theme = SETTINGS.value("appearance/icon_theme", type=str) or "Numix"
    return style, family, size, icon_theme


def save_window_size(width: int, height: int):
    SETTINGS.setValue("window/width", width)
    SETTINGS.setValue("window/height", height)


def load_window_size() -> tuple[int, int]:
    width = SETTINGS.value("window/width", 800, type=int)
    height = SETTINGS.value("window/height", 600, type=int)
    return width, height
