#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# hevc_gui/gui/appearance_dialog.py
from hevc_gui.i18n import L, restart_app, get_lang
import os
from PyQt5.QtWidgets import (
    QMessageBox,
    QDialog,
    QVBoxLayout,
    QLabel,
    QComboBox,
    QSpinBox,
    QRadioButton,
    QGroupBox,
    QHBoxLayout,
    QPushButton,
    QFontComboBox,
    QStyleFactory,
    QApplication,
    QStyledItemDelegate,
)
from PyQt5.QtCore import QModelIndex, Qt
from PyQt5.QtGui import QFont

from hevc_gui.gui.appearance_settings import (
    load_appearance,
    save_appearance,
    apply_appearance,
    reset_to_defaults,
)



# ─────────────────────────────────────────────────────────────────────
# Combo helpers: testo mostrato tradotto, valore interno stabile (UserRole)
# ─────────────────────────────────────────────────────────────────────
_ICON_THEME_ITEMS = [
    "Hevc - Video Converter (richiede riavvio)",
    "Numix",
    "Mint-Y",
    "Tango",
    "ubuntu-mono",
]

def _combo_add_src(cb: QComboBox, items):
    cb.clear()
    for s in items:
        cb.addItem(L(s), s)  # testo tradotto, data=source

def _combo_current_src(cb: QComboBox) -> str:
    d = cb.currentData()
    return d if d is not None else cb.currentText()

def _combo_set_src(cb: QComboBox, value: str) -> None:
    for i in range(cb.count()):
        if cb.itemData(i) == value:
            cb.setCurrentIndex(i)
            return
    cb.setCurrentText(value)

# ─────────────────────────────────────────────────────────────────────
# Delegate per “font preview”: ogni voce è disegnata col proprio font
# ─────────────────────────────────────────────────────────────────────
class FontPreviewDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index: QModelIndex):
        font_name = index.data()
        if font_name:
            # usa il font stesso per disegnare il suo nome
            option.font = QFont(font_name, option.font.pointSize())
        super().paint(painter, option, index)


class AppearanceDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(L("Impostazioni Aspetto"))

        # Carica le impostazioni attuali
        self.original = load_appearance()  # (style, font_family, font_size, theme_mode, icon_theme, button_style)
        self.preview = None  # snapshot ultimo "Applica"

        self.create_widgets()
        self.create_layout()
        self.create_connections()

        self.set_values(*self.original)

    # ─────────────────────────────────────────────────────────────────
    # UI
    # ─────────────────────────────────────────────────────────────────
    def create_widgets(self):
        # Stili Qt
        self.combo_style = QComboBox()
        self.combo_style.addItems(QStyleFactory.keys())

        # Font + delegate di preview
        self.combo_font = QFontComboBox()
        self.combo_font.setItemDelegate(FontPreviewDelegate(self.combo_font))

        # Dimensione font
        self.spin_font_size = QSpinBox()
        self.spin_font_size.setRange(6, 32)

        # Tema chiaro/scuro
        self.radio_light = QRadioButton(L("Chiaro"))
        self.radio_dark = QRadioButton(L("Scuro"))

        # Tema icone
        self.combo_icon_theme = QComboBox()
        _combo_add_src(self.combo_icon_theme, _ICON_THEME_ITEMS)
        # Stile pulsanti
        self.combo_button_style = QComboBox()
        self.combo_button_style.addItems([L("Predefinito"), L("Flat"), L("Icon Only"), L("Text Only")])

        # Pulsanti
        self.btn_reset = QPushButton(L("Ripristina predefiniti"))
        self.btn_apply = QPushButton(L("Applica"))
        self.btn_undo = QPushButton(L("Annulla Mod."))
        self.btn_ok = QPushButton(L("OK"))
        self.btn_cancel = QPushButton(L("Annulla"))

    def create_layout(self):
        layout = QVBoxLayout()

        layout.addWidget(QLabel(L("Temi:")))
        layout.addWidget(self.combo_style)

        layout.addWidget(QLabel(L("Font:")))
        layout.addWidget(self.combo_font)

        layout.addWidget(QLabel(L("Dimensione font:")))
        layout.addWidget(self.spin_font_size)

        theme_group = QGroupBox(L("Modalità tema"))
        theme_layout = QHBoxLayout()
        theme_layout.addWidget(self.radio_light)
        theme_layout.addWidget(self.radio_dark)
        theme_group.setLayout(theme_layout)
        layout.addWidget(theme_group)

        layout.addWidget(QLabel(L("Tema icone:")))
        layout.addWidget(self.combo_icon_theme)

        layout.addWidget(QLabel(L("Stile pulsanti:")))
        layout.addWidget(self.combo_button_style)

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.btn_reset)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_apply)
        btn_layout.addWidget(self.btn_undo)
        btn_layout.addWidget(self.btn_ok)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)

        self.setLayout(layout)

    def create_connections(self):
        self.btn_ok.clicked.connect(self.on_ok)
        self.btn_apply.clicked.connect(self.on_apply)
        self.btn_undo.clicked.connect(self.on_undo)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_reset.clicked.connect(self.on_reset)

    # ─────────────────────────────────────────────────────────────────
    # Stato <-> UI
    # ─────────────────────────────────────────────────────────────────
    def get_values(self):
        style = self.combo_style.currentText()
        font_family = self.combo_font.currentFont().family()
        font_size = self.spin_font_size.value()
        theme_mode = "dark" if self.radio_dark.isChecked() else "light"
        icon_theme = _combo_current_src(self.combo_icon_theme)
        button_style = self.combo_button_style.currentIndex()
        return style, font_family, font_size, theme_mode, icon_theme, button_style

    def set_values(self, style, font_family, font_size, theme_mode, icon_theme, button_style):
        self.combo_style.setCurrentText(style)
        self.combo_font.setCurrentFont(QFont(font_family))
        self.spin_font_size.setValue(font_size)

        if theme_mode == "dark":
            self.radio_dark.setChecked(True)
        else:
            self.radio_light.setChecked(True)
        _combo_set_src(self.combo_icon_theme, icon_theme)
        self.combo_button_style.setCurrentIndex(button_style)

    # ─────────────────────────────────────────────────────────────────
    # Azioni
    # ─────────────────────────────────────────────────────────────────
    def _refresh_icons(self):
        win = self.parent()
        if not win:
            return
        # refresh centralizzato menubar/toolbar
        try:
            from hevc_gui.gui.menubar import refresh_icons as _refresh_icons
            _refresh_icons(win)
        except Exception:
            pass
        # fallback: se il parent espone refresh_icons, chiamalo
        try:
            fn = getattr(win, 'refresh_icons', None)
            if callable(fn):
                fn()
        except Exception:
            pass

    def _appearance_restart_needed(self, values) -> bool:
        """
        Riavvio richiesto se cambiano elementi di aspetto globale:
          0 = style
          3 = theme_mode
          4 = icon_theme
        """
        try:
            old = self.original
        except Exception:
            old = load_appearance()

        try:
            old_style = str(old[0] or "").strip()
            old_theme_mode = str(old[3] or "").strip()
            old_icon_theme = str(old[4] or "").strip()

            new_style = str(values[0] or "").strip()
            new_theme_mode = str(values[3] or "").strip()
            new_icon_theme = str(values[4] or "").strip()

            return (
                old_style != new_style
                or old_theme_mode != new_theme_mode
                or old_icon_theme != new_icon_theme
            )
        except Exception:
            return False

    def _is_en_ui(self) -> bool:
        try:
            v = str(get_lang() or "").strip().lower()
            if v:
                return v.startswith("en")
        except Exception:
            pass
        return (os.environ.get("HEVC_LANG", "") or "").strip().lower().startswith("en")

    def _restart_notice_title(self) -> str:
        return "Restart required" if self._is_en_ui() else "Riavvio necessario"

    def _restart_notice_text(self) -> str:
        if self._is_en_ui():
            return "Appearance changes will be applied after restarting the app.\n\nRestart now…"
        return "Le modifiche di aspetto verranno applicate dopo il riavvio dell'app.\n\nRiavvio ora…"

    def on_ok(self):
        values = self.get_values()

        save_appearance(*values)

        if self._appearance_restart_needed(values):
            QMessageBox.information(
                self,
                self._restart_notice_title(),
                self._restart_notice_text()
            )
            restart_app()
            return

        apply_appearance(QApplication.instance())
        try:
            if self.parent() and hasattr(self.parent(), 'refresh_icons'):
                self.parent().refresh_icons()
        except Exception:
            pass

        self.accept()


    def on_apply(self):
        values = self.get_values()
        # apply con anteprima (senza persistere subito)
        apply_appearance(QApplication.instance(), *values)
        self.preview = values
        self._refresh_icons()
    def on_undo(self):
        if self.preview:
            # torna allo stato salvato originale (non l’ultimo apply)
            self.set_values(*self.original)
            apply_appearance(QApplication.instance())
            self._refresh_icons()
            self.preview = None

    def on_reset(self):
        reset_to_defaults()
        self.set_values(*load_appearance())
        apply_appearance(QApplication.instance())
        self._refresh_icons()
