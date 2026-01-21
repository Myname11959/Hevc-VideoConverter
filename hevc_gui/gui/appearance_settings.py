#!/usr/bin/env python3
# hevc_gui/gui/appearance_settings.py

import os
from configparser import ConfigParser
from PyQt5.QtGui import QFont, QIcon, QPalette, QColor
from PyQt5.QtWidgets import QApplication, QStyleFactory, QWidget, QMainWindow, QDialog

CONFIG_PATH = os.path.expanduser("~/.config/LorisPaganiniHomeStudio/HEVC VideoConverter.conf")

DEFAULTS = {
    "style": "Fusion",
    "font_family": "Roboto",
    "font_size": 10,
    "theme_mode": "light",
    "icon_theme": "Numix",
    "button_style": 0,
}


def ensure_config_exists():
    if not os.path.exists(CONFIG_PATH):
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        config = ConfigParser()
        config["appearance"] = DEFAULTS
        with open(CONFIG_PATH, "w") as f:
            config.write(f)


def load_appearance():
    ensure_config_exists()
    config = ConfigParser()
    config.read(CONFIG_PATH)

    if not config.has_section("appearance"):
        config["appearance"] = DEFAULTS

    section = config["appearance"]

    style = section.get("style", DEFAULTS["style"])
    font_family = section.get("font_family", DEFAULTS["font_family"])
    font_size = section.getint("font_size", DEFAULTS["font_size"])
    theme_mode = section.get("theme_mode", DEFAULTS["theme_mode"])
    icon_theme = section.get("icon_theme", DEFAULTS["icon_theme"])
    button_style = section.getint("button_style", DEFAULTS["button_style"])

    return style, font_family, font_size, theme_mode, icon_theme, button_style


def save_appearance(style, font_family, font_size, theme_mode, icon_theme, button_style):
    config = ConfigParser()
    config["appearance"] = {
        "style": style,
        "font_family": font_family,
        "font_size": str(font_size),
        "theme_mode": theme_mode,
        "icon_theme": icon_theme,
        "button_style": str(button_style),
    }
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        config.write(f)


def apply_appearance(app: QApplication, *custom_values) -> QFont:
    """
    Applica stile, font, palette e icone. Se non vengono forniti parametri,
    li carica dal file di configurazione. Valido sia per l'avvio che per
    anteprime 'Applica'.
    """
    if custom_values and len(custom_values) == 6:
        style, font_family, font_size, theme_mode, icon_theme, button_style = custom_values
    else:
        style, font_family, font_size, theme_mode, icon_theme, button_style = load_appearance()

    # 1) Style Qt
    if style in QStyleFactory.keys():
        app.setStyle(QStyleFactory.create(style))
    else:
        app.setStyle("Fusion")
    # 2) Icon theme
    icon_theme = (icon_theme or "").strip()
    # Modalità: pack interno HEVC (QRC), non è un themeName Qt
    if icon_theme.lower().startswith("hevc - video converter"):
        os.environ["HEVC_ICON_PACK"] = "qrc"
        QIcon.setThemeName("fallback-only")
    else:
        os.environ["HEVC_ICON_PACK"] = "theme"
        QIcon.setThemeName(icon_theme or "fallback-only")
    # 3) Font globale
    font = QFont(font_family, font_size)
    app.setFont(font)

    # 4) Palette
    if theme_mode == "dark":
        pal = QPalette()
        pal.setColor(QPalette.Window, QColor("#2d2d2d"))
        pal.setColor(QPalette.WindowText, QColor("#f0f0f0"))
        pal.setColor(QPalette.Base, QColor("#3c3c3c"))
        pal.setColor(QPalette.Text, QColor("#ffffff"))
        pal.setColor(QPalette.Button, QColor("#3c3c3c"))
        pal.setColor(QPalette.ButtonText, QColor("#ffffff"))
        pal.setColor(QPalette.Highlight, QColor("#448aff"))
        pal.setColor(QPalette.HighlightedText, QColor("#000000"))
        app.setPalette(pal)
    else:
        app.setPalette(app.style().standardPalette())

    # 5) Aggiorna ogni widget visibile
    for w in app.allWidgets():
        w.setPalette(app.palette())
        w.setFont(font)
        w.update()

    # 6) Ridimensiona finestre top-level
    for w in app.topLevelWidgets():
        if isinstance(w, (QMainWindow, QDialog, QWidget)):
            w.adjustSize()
            w.resize(w.sizeHint())

    return font


def reset_to_defaults():
    save_appearance(**DEFAULTS)
