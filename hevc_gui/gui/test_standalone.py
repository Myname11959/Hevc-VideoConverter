from hevc_gui.i18n import L
import sys
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QSpinBox,
    QDialogButtonBox,
    QPushButton,
)
from PyQt5.QtGui import QFontDatabase, QFont
from PyQt5.QtCore import QModelIndex
from PyQt5.QtWidgets import QStyledItemDelegate
from PyQt5.QtWidgets import QStyleFactory


class FontPreviewDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index: QModelIndex):
        font_name = index.data()
        font = QFont(font_name, option.font.pointSize())
        option.font = font
        super().paint(painter, option, index)


def apply_appearance(style, family, size, icon_theme, main_window=None):
    app = QApplication.instance()
    if not app:
        print("[apply_appearance] No QApplication instance")
        return
    print(f"[apply_appearance] style={style}, family={family}, size={size}, icon_theme={icon_theme}")
    font = QFont(family, size)
    app.setFont(font)
    # Per semplicità non applica stile reale


class AppearanceDialog(QDialog):
    DEFAULT_STYLE = "Fusion"
    DEFAULT_FONT_FAMILY = "Roboto"
    DEFAULT_FONT_SIZE = 10
    DEFAULT_ICON_THEME = "Numix"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(L("Impostazioni Aspetto"))

        cur_style = self.DEFAULT_STYLE
        cur_family = self.DEFAULT_FONT_FAMILY
        cur_size = self.DEFAULT_FONT_SIZE
        cur_icon_theme = self.DEFAULT_ICON_THEME

        print(f"[DEBUG INIT] inizializzo con: style={cur_style}, family={cur_family}, size={cur_size}, icon_theme={cur_icon_theme}")

        self.base_style = cur_style
        self.base_family = cur_family
        self.base_size = cur_size
        self.base_icon_theme = cur_icon_theme

        self.prev_base_style = cur_style
        self.prev_base_family = cur_family
        self.prev_base_size = cur_size
        self.prev_base_icon_theme = cur_icon_theme

        layout = QVBoxLayout(self)

        hstyle = QHBoxLayout()
        hstyle.addWidget(QLabel(L("Stile Qt:")))
        self.style_cb = QComboBox()
        self.style_cb.addItems(sorted(QStyleFactory.keys()))
        self.style_cb.setCurrentText(cur_style)
        hstyle.addWidget(self.style_cb)
        layout.addLayout(hstyle)

        hfont = QHBoxLayout()
        hfont.addWidget(QLabel(L("Font:")))
        families = QFontDatabase().families()
        self.font_cb = QComboBox()
        self.font_cb.addItems(families)
        self.font_cb.setCurrentText(cur_family)
        hfont.addWidget(self.font_cb)

        hfont.addWidget(QLabel(L("Dimensione:")))
        self.size_sb = QSpinBox()
        self.size_sb.setRange(6, 48)
        self.size_sb.setValue(cur_size)
        hfont.addWidget(self.size_sb)
        layout.addLayout(hfont)

        hicon = QHBoxLayout()
        hicon.addWidget(QLabel(L("Tema Icone:")))
        icon_themes = ["Numix", "Breeze", "Adwaita", "Papirus", "Faenza"]
        self.icon_theme_cb = QComboBox()
        self.icon_theme_cb.addItems(icon_themes)
        self.icon_theme_cb.setCurrentText(cur_icon_theme)
        hicon.addWidget(self.icon_theme_cb)
        layout.addLayout(hicon)

        self.buttons = QDialogButtonBox()
        self.ok_button = self.buttons.addButton(QDialogButtonBox.Ok)
        self.ok_button.setText(L("OK"))

        self.cancel_button = self.buttons.addButton(QDialogButtonBox.Cancel)
        self.cancel_button.setText(L("Cancel"))

        self.apply_button = QPushButton(L("Applica"))
        self.reset_button = QPushButton(L("Reset"))
        self.annulla_mod_button = QPushButton(L("Annulla Mod."))

        self.buttons.addButton(self.apply_button, QDialogButtonBox.ActionRole)
        self.buttons.addButton(self.reset_button, QDialogButtonBox.ActionRole)
        self.buttons.addButton(self.annulla_mod_button, QDialogButtonBox.ActionRole)

        layout.addWidget(self.buttons)

        self.ok_button.clicked.connect(self.on_ok)
        self.cancel_button.clicked.connect(self.reject)
        self.apply_button.clicked.connect(self.on_apply)
        self.reset_button.clicked.connect(self.on_reset)
        self.annulla_mod_button.clicked.connect(self.on_annulla_mod)

    def on_apply(self):
        style = self.style_cb.currentText()
        family = self.font_cb.currentText()
        size = self.size_sb.value()
        icon_theme = self.icon_theme_cb.currentText()

        print(f"[DEBUG] on_apply called with: style={style}, family={family}, size={size}, icon_theme={icon_theme}")
        apply_appearance(style, family, size, icon_theme)

        # Salva stato precedente prima di aggiornare base
        print(
            f"[DEBUG] Saving prev_base: style={self.base_style}, family={self.base_family}, size={self.base_size}, icon_theme={self.base_icon_theme}"
        )
        self.prev_base_style = self.base_style
        self.prev_base_family = self.base_family
        self.prev_base_size = self.base_size
        self.prev_base_icon_theme = self.base_icon_theme

        # Aggiorna stato base all’ultimo confermato
        print(f"[DEBUG] Updating base to: style={style}, family={family}, size={size}, icon_theme={icon_theme}")
        self.base_style = style
        self.base_family = family
        self.base_size = size
        self.base_icon_theme = icon_theme

    def on_annulla_mod(self):
        print(
            f"[DEBUG] on_annulla_mod called. Restoring to prev_base: style={self.prev_base_style}, family={self.prev_base_family}, size={self.prev_base_size}, icon_theme={self.prev_base_icon_theme}"
        )

        style = self.prev_base_style or self.DEFAULT_STYLE
        family = self.prev_base_family or self.DEFAULT_FONT_FAMILY
        size = self.prev_base_size or self.DEFAULT_FONT_SIZE
        icon_theme = self.prev_base_icon_theme or self.DEFAULT_ICON_THEME

        self.style_cb.setCurrentText(style)
        self.font_cb.setCurrentText(family)
        self.size_sb.setValue(size)
        self.icon_theme_cb.setCurrentText(icon_theme)

        QApplication.processEvents()
        apply_appearance(style, family, size, icon_theme)

        # Aggiorna base anche qui per mantenere coerenza
        print("[DEBUG] on_annulla_mod updating base to prev_base")
        self.base_style = style
        self.base_family = family
        self.base_size = size
        self.base_icon_theme = icon_theme

    def on_reset(self):
        print("[DEBUG] on_reset called")
        self.style_cb.setCurrentText(self.DEFAULT_STYLE)
        self.font_cb.setCurrentText(self.DEFAULT_FONT_FAMILY)
        self.size_sb.setValue(self.DEFAULT_FONT_SIZE)
        self.icon_theme_cb.setCurrentText(self.DEFAULT_ICON_THEME)
        QApplication.processEvents()
        apply_appearance(
            self.DEFAULT_STYLE,
            self.DEFAULT_FONT_FAMILY,
            self.DEFAULT_FONT_SIZE,
            self.DEFAULT_ICON_THEME,
        )

    def on_ok(self):
        print("[DEBUG] on_ok called")
        self.on_apply()
        self.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    dlg = AppearanceDialog()
    dlg.show()
    sys.exit(app.exec_())
