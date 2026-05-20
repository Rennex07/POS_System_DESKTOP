from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPalette, QColor
from PySide6.QtCore import Qt

GREEN = "#1BAC4B"
GREEN_DARK = "#158f3e"
GREEN_LIGHT = "#E8F5E9"
GREEN_PALE = "#F1F8E9"
BG_MAIN = "#F5F5F7"
BG_WHITE = "#FFFFFF"
BG_CARD = "#FFFFFF"
TEXT_PRIMARY = "#1E1E2D"
TEXT_SECONDARY = "#636E72"
TEXT_MUTED = "#A4A4A4"
BORDER = "#E8E8E8"
BORDER_LIGHT = "#F0F0F0"
RED = "#E74C3C"
ORANGE = "#F39C12"


def apply_theme(theme_name: str = "light") -> None:
    app = QApplication.instance()
    if not app:
        return

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(BG_MAIN))
    palette.setColor(QPalette.WindowText, QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.Base, QColor(BG_WHITE))
    palette.setColor(QPalette.AlternateBase, QColor("#FAFAFA"))
    palette.setColor(QPalette.ToolTipBase, QColor(BG_WHITE))
    palette.setColor(QPalette.ToolTipText, QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.Text, QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.Button, QColor(BG_WHITE))
    palette.setColor(QPalette.ButtonText, QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.BrightText, QColor(RED))
    palette.setColor(QPalette.Link, QColor(GREEN))
    palette.setColor(QPalette.Highlight, QColor(GREEN))
    palette.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    palette.setColor(QPalette.Disabled, QPalette.WindowText, QColor(TEXT_MUTED))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor(TEXT_MUTED))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(TEXT_MUTED))
    app.setPalette(palette)

    app.setStyleSheet(f"""
        QMainWindow, QDialog {{
            background-color: {BG_MAIN};
            color: {TEXT_PRIMARY};
            font-family: "Segoe UI", "Arial", sans-serif;
        }}
        QWidget {{
            font-family: "Segoe UI", "Arial", sans-serif;
        }}
        QTableWidget {{
            background-color: {BG_WHITE};
            border: 1px solid {BORDER};
            border-radius: 8px;
            gridline-color: {BORDER_LIGHT};
            selection-background-color: {GREEN_LIGHT};
            selection-color: {TEXT_PRIMARY};
            font-size: 13px;
        }}
        QTableWidget::item {{
            padding: 6px 10px;
            border-bottom: 1px solid {BORDER_LIGHT};
        }}
        QHeaderView::section {{
            background-color: {BG_MAIN};
            color: {TEXT_SECONDARY};
            padding: 8px 10px;
            border: none;
            border-bottom: 2px solid {BORDER};
            font-weight: 600;
            font-size: 12px;
        }}
        QScrollBar:vertical {{
            background: transparent;
            width: 8px;
            margin: 4px 2px;
        }}
        QScrollBar::handle:vertical {{
            background: #D0D0D0;
            border-radius: 4px;
            min-height: 30px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: #B0B0B0;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        QScrollBar:horizontal {{
            background: transparent;
            height: 8px;
            margin: 2px 4px;
        }}
        QScrollBar::handle:horizontal {{
            background: #D0D0D0;
            border-radius: 4px;
            min-width: 30px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background: #B0B0B0;
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0px;
        }}
        QScrollArea {{
            border: none;
            background: transparent;
        }}
        QLineEdit {{
            background-color: {BG_WHITE};
            border: 1.5px solid {BORDER};
            padding: 8px 12px;
            border-radius: 10px;
            font-size: 13px;
            color: {TEXT_PRIMARY};
        }}
        QLineEdit:focus {{
            border: 1.5px solid {GREEN};
        }}
        QLineEdit::placeholder {{
            color: {TEXT_MUTED};
        }}
        QSpinBox, QDoubleSpinBox {{
            background-color: {BG_WHITE};
            border: 1.5px solid {BORDER};
            padding: 6px 10px;
            border-radius: 8px;
            font-size: 13px;
            color: {TEXT_PRIMARY};
        }}
        QSpinBox:focus, QDoubleSpinBox:focus {{
            border: 1.5px solid {GREEN};
        }}
        QComboBox {{
            background-color: {BG_WHITE};
            border: 1.5px solid {BORDER};
            padding: 6px 12px;
            border-radius: 8px;
            font-size: 13px;
            color: {TEXT_PRIMARY};
        }}
        QComboBox:focus {{
            border: 1.5px solid {GREEN};
        }}
        QComboBox::drop-down {{
            border: none;
            padding-right: 8px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {BG_WHITE};
            border: 1px solid {BORDER};
            border-radius: 6px;
            selection-background-color: {GREEN_LIGHT};
            selection-color: {TEXT_PRIMARY};
        }}
        QMessageBox {{
            background-color: {BG_WHITE};
        }}
        QMessageBox QLabel {{
            color: {TEXT_PRIMARY};
            font-size: 13px;
        }}
        QMessageBox QPushButton {{
            background-color: {GREEN};
            color: {TEXT_PRIMARY};
            border: 2px solid {GREEN};
            border-radius: 8px;
            padding: 10px 24px;
            font-weight: 600;
            font-size: 13px;
            min-width: 90px;
            min-height: 32px;
        }}
        QMessageBox QPushButton:hover {{
            background-color: {GREEN_DARK};
            border-color: {GREEN_DARK};
        }}
        QMessageBox QPushButton:pressed {{
            background-color: {GREEN_DARK};
        }}
        QMessageBox QPushButton[text="Cancel"], 
        QMessageBox QPushButton[text="No"] {{
            background-color: {BG_MAIN};
            color: {TEXT_PRIMARY};
            border: 2px solid {BORDER};
        }}
        QMessageBox QPushButton[text="Cancel"]:hover,
        QMessageBox QPushButton[text="No"]:hover {{
            background-color: #E8E8E8;
            border-color: {TEXT_MUTED};
        }}
        QDialogButtonBox QPushButton {{
            background-color: {GREEN};
            color: {TEXT_PRIMARY};
            border: 2px solid {GREEN};
            border-radius: 8px;
            padding: 10px 24px;
            font-weight: 600;
            font-size: 13px;
            min-width: 90px;
            min-height: 32px;
        }}
        QDialogButtonBox QPushButton:hover {{
            background-color: {GREEN_DARK};
            border-color: {GREEN_DARK};
        }}
        QDialogButtonBox QPushButton:pressed {{
            background-color: {GREEN_DARK};
        }}
        QProgressBar {{
            border: none;
            border-radius: 6px;
            background-color: {BORDER_LIGHT};
            text-align: center;
            font-size: 11px;
        }}
        QProgressBar::chunk {{
            background-color: {GREEN};
            border-radius: 6px;
        }}
        QGroupBox {{
            background-color: {BG_WHITE};
            border: 1px solid {BORDER};
            border-radius: 10px;
            margin-top: 14px;
            padding: 20px 15px 15px 15px;
            font-weight: 600;
            font-size: 13px;
            color: {TEXT_PRIMARY};
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 15px;
            padding: 0 8px;
            color: {TEXT_PRIMARY};
        }}
        QToolTip {{
            background-color: {BG_WHITE};
            color: {TEXT_PRIMARY};
            border: 1px solid {BORDER};
            border-radius: 6px;
            padding: 6px 10px;
            font-size: 12px;
        }}
        QStatusBar {{
            background-color: {BG_WHITE};
            border-top: 1px solid {BORDER};
            color: {TEXT_SECONDARY};
            font-size: 12px;
            padding: 2px 10px;
        }}
    """)
