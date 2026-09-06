import logging
import math
import threading
from typing import Dict, List
from datetime import datetime
from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, QPushButton,
    QLabel, QSpinBox, QMessageBox, QLineEdit, QScrollArea, QWidget, QGridLayout, QFrame, QButtonGroup,
    QAbstractItemView, QAbstractSpinBox, QSizePolicy, QHeaderView, QInputDialog, QGraphicsOpacityEffect,
    QMenu
)
from PySide6.QtGui import QPixmap, QImage, QShortcut, QKeySequence
from PySide6.QtCore import (
    Qt, QTimer, QSize, QBuffer, QPropertyAnimation, QEasingCurve, QParallelAnimationGroup,
    QRect, QPoint, QEvent, Signal,
)
from services.transaction_service import TransactionService, CartItem
from services.table_service import TableService
from .pdf_generator import PDFGenerator, ReceiptData, ReceiptItem

try:
    from shiboken6 import isValid as _qt_is_valid
except ImportError:
    def _qt_is_valid(obj):
        return obj is not None

logger = logging.getLogger(__name__)

LOW_STOCK_THRESHOLD = 10
STOCK_OUT_BORDER = "#D50000"
STOCK_OUT_BG = "#FFE1E1"
STOCK_LOW_BORDER = "#FF9800"
STOCK_LOW_BG = "#FFF6CC"

try:
    from database import database as db
    from database.database_setup import ensure_transactions_tables, ensure_settings_table, ensure_table_management_tables
except ModuleNotFoundError:
    import os, sys
    root = os.path.dirname(os.path.dirname(__file__))
    if root not in sys.path:
        sys.path.insert(0, root)
    import database as db
    from database_setup import ensure_transactions_tables, ensure_settings_table, ensure_table_management_tables

from .inventory_menu import (
    _make_thumbnail_pixmap,
    _fetch_all_items,
    _prepare_row_for_display,
    _get_item_by_id,
    _sort_stock_alerts_first,
)
from .theme_manager import (
    GREEN, GREEN_DARK, GREEN_LIGHT, GREEN_PALE,
    BG_MAIN, BG_WHITE, BG_CARD, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED,
    BORDER, BORDER_LIGHT, RED, ORANGE
)


def get_exchange_rate():
    try:
        from database.database import get_exchange_rate as db_get_rate
        return db_get_rate()
    except Exception:
        return 4100


def get_vat_settings():
    try:
        enabled = str(db.get_setting("vat_enabled", "0")) == "1"
        rate = float(db.get_setting("vat_rate", "0") or 0)
        return enabled, max(0.0, rate)
    except Exception:
        return False, 0.0


def round_up_khr(amount: float) -> int:
    amount = round(float(amount or 0), 6)
    if amount <= 0:
        return 0
    return int(math.ceil(amount / 100.0) * 100)


CATEGORY_PILL_STYLE = f"""
    QPushButton {{
        background-color: {BG_WHITE};
        color: {TEXT_SECONDARY};
        border: 1.5px solid {BORDER};
        border-radius: 18px;
        padding: 8px 18px;
        font-size: 13px;
        font-weight: 500;
    }}
    QPushButton:hover {{
        background-color: {GREEN_LIGHT};
        border-color: {GREEN};
        color: {GREEN};
    }}
    QPushButton:checked {{
        background-color: {GREEN};
        color: white;
        border-color: {GREEN};
        font-weight: 600;
    }}
"""

ORDER_PANEL_STYLE = f"""
    QFrame#orderPanel {{
        background-color: {BG_WHITE};
        border: 1px solid {BORDER};
        border-radius: 14px;
    }}
"""

CARD_STYLE = f"""
    QFrame#itemCard {{
        background-color: {BG_WHITE};
        border: 1px solid {BORDER};
        border-radius: 10px;
    }}
    QFrame#itemCard:hover {{
        border-color: {GREEN};
    }}
"""

ADD_BTN_STYLE = f"""
    QPushButton {{
        background-color: {GREEN};
        color: white;
        border: none;
        border-radius: 8px;
        padding: 6px 14px;
        font-size: 12px;
        font-weight: 600;
    }}
    QPushButton:hover {{
        background-color: {GREEN_DARK};
    }}
    QPushButton:disabled {{
        background-color: #E8E8E8;
        color: {TEXT_MUTED};
    }}
"""

CHECKOUT_BTN_STYLE = f"""
    QPushButton {{
        background-color: {GREEN};
        color: white;
        border: none;
        border-radius: 12px;
        padding: 14px;
        font-size: 15px;
        font-weight: 700;
    }}
    QPushButton:hover {{
        background-color: {GREEN_DARK};
    }}
    QPushButton:disabled {{
        background-color: #C8E6C9;
        color: #A5D6A7;
    }}
"""


class TableCardFrame(QFrame):
    leftClicked = Signal(object)
    rightClicked = Signal(object, QPoint)
    hovered = Signal(object)
    hoverLeft = Signal(object)

    def __init__(self, table, parent=None):
        super().__init__(parent)
        self._table = table
        self.setMouseTracking(True)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.leftClicked.emit(self._table)
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton:
            self.rightClicked.emit(self._table, event.globalPosition().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def enterEvent(self, event):
        self.hovered.emit(self._table)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hoverLeft.emit(self._table)
        super().leaveEvent(event)


class DrinkCustomizationDialog(QDialog):
    LEVEL_PRESETS = [0, 25, 50, 75, 100]
    SUGAR_PRESETS = LEVEL_PRESETS
    ICE_PRESETS = LEVEL_PRESETS
    SIZE_OPTIONS = ["S", "M", "L"]

    COFFEE = "#6F4E37"
    COFFEE_DARK = "#5A3D2B"
    COFFEE_LIGHT = "#F5E6DC"
    COFFEE_PALE = "#FAF0E6"

    _PILL_NORMAL = f"""
        QPushButton {{
            background-color: #FFFFFF;
            color: #6F4E37;
            border: 1.5px solid #D4C4B5;
            border-radius: 18px;
            padding: 4px 14px;
            font-size: 12px;
            font-weight: 600;
            min-width: 36px;
            min-height: 36px;
            max-height: 36px;
        }}
        QPushButton:hover {{
            background-color: #F5E6DC;
            border-color: #6F4E37;
        }}
    """
    _PILL_SELECTED = f"""
        QPushButton {{
            background-color: #FFFFFF;
            color: #6F4E37;
            border: 2px solid #6F4E37;
            border-radius: 18px;
            padding: 4px 14px;
            font-size: 12px;
            font-weight: 700;
            min-width: 36px;
            min-height: 36px;
            max-height: 36px;
        }}
        QPushButton:hover {{
            background-color: #F5E6DC;
        }}
    """

    def __init__(self, item_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Customize Drink")
        self.setFixedSize(400, 460)
        self.setStyleSheet(f"background-color: #FFFFFF;")

        self.selected_sugar: int | None = None
        self.selected_ice: int | None = None
        self.selected_size: str | None = None

        self._sugar_btns: list[QPushButton] = []
        self._ice_btns: list[QPushButton] = []
        self._size_btns: list[QPushButton] = []

        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(28, 28, 28, 28)

        title = QLabel(f"Customize — {item_name}")
        title.setStyleSheet(f"color: #2D2D2D; font-size: 18px; font-weight: 700; background: transparent;")
        title.setWordWrap(True)
        layout.addWidget(title)

        layout.addLayout(self._build_section("Size", self.SIZE_OPTIONS, self._size_btns, self._on_size))
        layout.addLayout(self._build_section("Sugar Level", [f"{p}%" for p in self.SUGAR_PRESETS], self._sugar_btns, self._on_sugar))
        layout.addLayout(self._build_section("Ice Level", [f"{p}%" for p in self.ICE_PRESETS], self._ice_btns, self._on_ice))

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setMinimumHeight(44)
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #F5F5F5;
                color: #6F4E37;
                border: 1.5px solid #E0D5CD;
                border-radius: 12px;
                font-size: 14px;
                font-weight: 600;
            }}
            QPushButton:hover {{ background-color: #E8E8E8; }}
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        self.confirm_btn = QPushButton("Add to Cart")
        self.confirm_btn.setMinimumHeight(44)
        self.confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm_btn.setEnabled(False)
        self.confirm_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #6F4E37;
                color: white;
                border: none;
                border-radius: 12px;
                font-size: 14px;
                font-weight: 700;
                padding: 0 28px;
            }}
            QPushButton:hover {{ background-color: #5A3D2B; }}
            QPushButton:disabled {{
                background-color: #D4C4B5;
                color: #A09080;
            }}
        """)
        self.confirm_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.confirm_btn, 1)

        layout.addLayout(btn_row)

        self._select_defaults()

    def _build_section(self, label: str, options: list[str], btn_list: list, callback) -> QVBoxLayout:
        section = QVBoxLayout()
        section.setSpacing(10)

        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: #8B7355; font-size: 12px; font-weight: 600; background: transparent; letter-spacing: 0.5px;")
        section.addWidget(lbl)

        row = QHBoxLayout()
        row.setSpacing(10)
        for i, opt in enumerate(options):
            btn = QPushButton(opt)
            btn.setFixedHeight(36)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(self._PILL_NORMAL)
            btn.clicked.connect(lambda _, idx=i: callback(idx))
            btn_list.append(btn)
            row.addWidget(btn)
        row.addStretch()
        section.addLayout(row)
        return section

    def _select_defaults(self):
        self._on_size(1)
        self._on_sugar(4)
        self._on_ice(4)

    def _highlight(self, btn_list: list[QPushButton], active_idx: int):
        for i, btn in enumerate(btn_list):
            btn.setStyleSheet(self._PILL_SELECTED if i == active_idx else self._PILL_NORMAL)

    def _on_size(self, idx: int):
        self.selected_size = self.SIZE_OPTIONS[idx]
        self._highlight(self._size_btns, idx)
        self._check_ready()

    def _on_sugar(self, idx: int):
        self.selected_sugar = self.SUGAR_PRESETS[idx]
        self._highlight(self._sugar_btns, idx)
        self._check_ready()

    def _on_ice(self, idx: int):
        self.selected_ice = self.ICE_PRESETS[idx]
        self._highlight(self._ice_btns, idx)
        self._check_ready()

    def _check_ready(self):
        ready = self.selected_sugar is not None and self.selected_ice is not None and self.selected_size is not None
        self.confirm_btn.setEnabled(ready)


class PaymentDialog(QDialog):
    def __init__(self, total_usd: float, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Payment")
        self.setMinimumSize(470, 620)
        self.resize(500, 680)
        self.setStyleSheet(f"background-color: {BG_WHITE};")
        self.subtotal_usd = float(total_usd or 0)
        self.exchange_rate = get_exchange_rate()
        self.vat_enabled, self.vat_rate = get_vat_settings()
        self.discount_mode = "percent"
        self.discount_amount_usd = 0.0
        self.vat_amount_usd = 0.0
        self.final_total_usd = self.subtotal_usd
        self.total_khr = round_up_khr(self.final_total_usd * self.exchange_rate)
        self.accepted_payment = False
        self.payment_method = "cash"
        self.is_khr = False

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(28, 28, 28, 28)

        total_frame = QFrame()
        total_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {GREEN_LIGHT};
                border-radius: 12px;
            }}
        """)
        total_layout = QVBoxLayout(total_frame)
        total_layout.setSpacing(4)
        total_layout.setContentsMargins(20, 18, 20, 18)

        total_title = QLabel("Payment Total")
        total_title.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px; background: transparent;")
        total_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        total_layout.addWidget(total_title)

        self.total_usd_label = QLabel("$0.00")
        self.total_usd_label.setStyleSheet(f"color: {GREEN}; font-size: 34px; font-weight: 700; background: transparent;")
        self.total_usd_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        total_layout.addWidget(self.total_usd_label)

        total_khr_label = QLabel(f"៛ {self.total_khr:,.0f} KHR")
        total_khr_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 14px; background: transparent;")
        total_khr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        total_layout.addWidget(total_khr_label)
        self.total_khr_label = total_khr_label

        self.total_breakdown_label = QLabel("")
        self.total_breakdown_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; background: transparent;")
        self.total_breakdown_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.total_breakdown_label.setWordWrap(True)
        total_layout.addWidget(self.total_breakdown_label)

        layout.addWidget(total_frame)
        layout.addWidget(self._create_discount_widget())
        layout.addWidget(self._create_cash_widget())

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setMinimumHeight(48)
        cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {BG_MAIN};
                color: {TEXT_SECONDARY};
                border: 1px solid {BORDER};
                border-radius: 10px;
                font-size: 14px;
                font-weight: 600;
                padding: 0 28px;
            }}
            QPushButton:hover {{ background-color: #E8E8E8; }}
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        self.confirm_btn = QPushButton("Confirm Payment")
        self.confirm_btn.setMinimumHeight(48)
        self.confirm_btn.setEnabled(False)
        self.confirm_btn.setStyleSheet(CHECKOUT_BTN_STYLE)
        self.confirm_btn.clicked.connect(self._confirm_payment)
        btn_layout.addWidget(self.confirm_btn, 1)

        layout.addLayout(btn_layout)
        self._calculate_totals()
        QTimer.singleShot(100, lambda: self.amount_input.setFocus())

    def _create_discount_widget(self):
        frame = QFrame()
        frame.setStyleSheet(f"background-color: {BG_MAIN}; border-radius: 10px;")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        label = QLabel("Discount")
        label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px; font-weight: 600; background: transparent;")
        layout.addWidget(label)

        row = QHBoxLayout()
        row.setSpacing(8)

        self.discount_input = QLineEdit()
        self.discount_input.setPlaceholderText("0")
        self.discount_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {BG_WHITE};
                color: {TEXT_PRIMARY};
                border: 1.5px solid {BORDER};
                border-radius: 10px;
                padding: 10px;
                font-size: 15px;
                font-weight: 600;
            }}
            QLineEdit:focus {{ border-color: {GREEN}; }}
        """)
        self.discount_input.textChanged.connect(self._calculate_totals)
        row.addWidget(self.discount_input, 1)

        self.discount_mode_btn = QPushButton("%")
        self.discount_mode_btn.setMinimumWidth(70)
        self.discount_mode_btn.setMinimumHeight(42)
        self.discount_mode_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.discount_mode_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {GREEN_LIGHT};
                color: {GREEN};
                border: 1.5px solid {GREEN};
                border-radius: 10px;
                font-size: 13px;
                font-weight: 700;
            }}
            QPushButton:hover {{ background-color: {GREEN_PALE}; }}
        """)
        self.discount_mode_btn.clicked.connect(self._cycle_discount_mode)
        row.addWidget(self.discount_mode_btn)

        layout.addLayout(row)

        self.vat_hint_label = QLabel("")
        self.vat_hint_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px; background: transparent;")
        layout.addWidget(self.vat_hint_label)
        return frame

    def _cycle_discount_mode(self):
        modes = ["percent", "usd", "khr"]
        idx = modes.index(self.discount_mode)
        self.discount_mode = modes[(idx + 1) % len(modes)]
        self.discount_mode_btn.setText({"percent": "%", "usd": "USD", "khr": "KHR"}[self.discount_mode])
        self._calculate_totals()

    def _calculate_totals(self):
        try:
            raw_text = self.discount_input.text().replace(",", "").strip()
            raw_discount = float(raw_text) if raw_text else 0.0
        except ValueError:
            raw_discount = 0.0

        raw_discount = max(0.0, raw_discount)
        if self.discount_mode == "percent":
            self.discount_amount_usd = self.subtotal_usd * min(raw_discount, 100.0) / 100.0
        elif self.discount_mode == "khr":
            self.discount_amount_usd = raw_discount / self.exchange_rate
        else:
            self.discount_amount_usd = raw_discount

        self.discount_amount_usd = min(self.discount_amount_usd, self.subtotal_usd)
        taxable_amount = max(0.0, self.subtotal_usd - self.discount_amount_usd)
        self.vat_amount_usd = taxable_amount * self.vat_rate / 100.0 if self.vat_enabled else 0.0
        self.final_total_usd = taxable_amount + self.vat_amount_usd
        self.total_khr = round_up_khr(self.final_total_usd * self.exchange_rate)

        self.total_usd_label.setText(f"${self.final_total_usd:.2f}")
        self.total_khr_label.setText(f"៛ {self.total_khr:,.0f} KHR")
        self.total_breakdown_label.setText(
            f"Subtotal ${self.subtotal_usd:.2f} | Discount -${self.discount_amount_usd:.2f} | "
            f"VAT ${self.vat_amount_usd:.2f}"
        )
        self.vat_hint_label.setText(
            f"Auto VAT is on: {self.vat_rate:.2f}%" if self.vat_enabled else "Auto VAT is off"
        )
        self._calculate_change()

    def _create_cash_widget(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(14)

        input_frame = QFrame()
        input_frame.setStyleSheet(f"background-color: {BG_MAIN}; border-radius: 10px;")
        input_layout = QVBoxLayout(input_frame)
        input_layout.setContentsMargins(16, 14, 16, 14)
        input_layout.setSpacing(8)

        input_title = QLabel("Customer Gives:")
        input_title.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px; font-weight: 500; background: transparent;")
        input_layout.addWidget(input_title)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)

        self.amount_input = QLineEdit()
        self.amount_input.setPlaceholderText("Enter amount...")
        self.amount_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {BG_WHITE};
                color: {TEXT_PRIMARY};
                border: 2px solid {GREEN};
                border-radius: 10px;
                padding: 12px;
                font-size: 18px;
                font-weight: 700;
            }}
            QLineEdit:focus {{ border-color: {GREEN_DARK}; }}
        """)
        self.amount_input.textChanged.connect(self._calculate_change)
        input_row.addWidget(self.amount_input, 1)

        self.currency_btn = QPushButton("USD")
        self.currency_btn.setMinimumWidth(65)
        self.currency_btn.setMinimumHeight(48)
        self.currency_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {GREEN};
                color: white;
                border: none;
                border-radius: 10px;
                font-size: 14px;
                font-weight: 700;
            }}
            QPushButton:hover {{ background-color: {GREEN_DARK}; }}
        """)
        self.currency_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.currency_btn.clicked.connect(self._toggle_currency)
        self.is_khr = False
        input_row.addWidget(self.currency_btn)

        input_layout.addLayout(input_row)
        layout.addWidget(input_frame)

        change_layout = QVBoxLayout()
        change_layout.setContentsMargins(0, 12, 0, 0)
        change_layout.setSpacing(4)

        change_title = QLabel("Change to Give Back:")
        change_title.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px; font-weight: 600; background: transparent;")
        change_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        change_layout.addWidget(change_title)

        self.change_usd_label = QLabel("$0.00")
        self.change_usd_label.setStyleSheet(f"color: {GREEN}; font-size: 32px; font-weight: 700; background: transparent;")
        self.change_usd_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        change_layout.addWidget(self.change_usd_label)

        self.change_khr_label = QLabel("៛ 0 KHR")
        self.change_khr_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 14px; background: transparent;")
        self.change_khr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        change_layout.addWidget(self.change_khr_label)

        layout.addLayout(change_layout)
        layout.addStretch()

        return widget

    def _toggle_currency(self):
        self.is_khr = not self.is_khr
        if self.is_khr:
            self.currency_btn.setText("KHR")
            self.currency_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: #3498db;
                    color: white;
                    border: none;
                    border-radius: 10px;
                    font-size: 14px;
                    font-weight: 700;
                }}
                QPushButton:hover {{ background-color: #2980b9; }}
            """)
        else:
            self.currency_btn.setText("USD")
            self.currency_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {GREEN};
                    color: white;
                    border: none;
                    border-radius: 10px;
                    font-size: 14px;
                    font-weight: 700;
                }}
                QPushButton:hover {{ background-color: {GREEN_DARK}; }}
            """)
        self._calculate_change()

    def _calculate_change(self):
        try:
            amount_text = self.amount_input.text().replace(",", "").strip()
            if not amount_text:
                self.change_usd_label.setText("$0.00")
                self.change_khr_label.setText("៛ 0 KHR")
                self.confirm_btn.setEnabled(False)
                return

            amount = float(amount_text)
            if self.is_khr:
                raw_change_khr = round(amount - self.total_khr, 6)
                if raw_change_khr >= 0:
                    change_khr = round_up_khr(raw_change_khr)
                    change_usd = change_khr / self.exchange_rate
                    self.change_usd_label.setText(f"${change_usd:.2f}")
                    self.change_khr_label.setText(f"៛ {change_khr:,.0f} KHR")
                    self.change_usd_label.setStyleSheet(f"color: {GREEN}; font-size: 32px; font-weight: 700; background: transparent;")
                    self.confirm_btn.setEnabled(True)
                else:
                    self.change_usd_label.setText(f"-${abs(raw_change_khr / self.exchange_rate):.2f}")
                    self.change_khr_label.setText("Insufficient amount")
                    self.change_usd_label.setStyleSheet(f"color: {RED}; font-size: 32px; font-weight: 700; background: transparent;")
                    self.confirm_btn.setEnabled(False)
            else:
                change_usd = round(amount - self.final_total_usd, 6)
                change_khr = round_up_khr(change_usd * self.exchange_rate)

                if change_usd >= 0:
                    self.change_usd_label.setText(f"${change_usd:.2f}")
                    self.change_khr_label.setText(f"៛ {change_khr:,.0f} KHR")
                    self.change_usd_label.setStyleSheet(f"color: {GREEN}; font-size: 32px; font-weight: 700; background: transparent;")
                    self.confirm_btn.setEnabled(True)
                else:
                    self.change_usd_label.setText(f"-${abs(change_usd):.2f}")
                    self.change_khr_label.setText("Insufficient amount")
                    self.change_usd_label.setStyleSheet(f"color: {RED}; font-size: 32px; font-weight: 700; background: transparent;")
                    self.confirm_btn.setEnabled(False)

        except ValueError:
            self.change_usd_label.setText("Invalid")
            self.change_khr_label.setText("")
            self.change_usd_label.setStyleSheet(f"color: {RED}; font-size: 32px; font-weight: 700; background: transparent;")
            self.confirm_btn.setEnabled(False)

    def _confirm_payment(self):
        self.accepted_payment = True
        self.accept()


def _ensure_db():
    if getattr(db, "conn", None) is None or getattr(db, "cursor", None) is None:
        db.connect()
    try:
        ensure_settings_table()
        ensure_transactions_tables()
        ensure_table_management_tables()
    except Exception:
        pass


class TableManagementDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage Tables")
        self.setMinimumSize(560, 420)
        self.setStyleSheet(f"background-color: {BG_WHITE};")
        self.service = TableService()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(14)

        title = QLabel("Tables")
        title.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {TEXT_PRIMARY}; background: transparent;")
        layout.addWidget(title)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["ID", "Table", "Label", "Status"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setColumnHidden(0, True)
        layout.addWidget(self.table, 1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        add_btn = QPushButton("Add Table")
        edit_btn = QPushButton("Edit")
        delete_btn = QPushButton("Delete")
        close_btn = QPushButton("Close")

        for btn in (add_btn, edit_btn, delete_btn):
            btn.setMinimumHeight(40)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(CHECKOUT_BTN_STYLE)

        close_btn.setMinimumHeight(40)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {BG_MAIN};
                color: {TEXT_SECONDARY};
                border: 1px solid {BORDER};
                border-radius: 10px;
                padding: 8px 18px;
                font-size: 13px;
                font-weight: 600;
            }}
            QPushButton:hover {{ background-color: #E8E8E8; }}
        """)

        add_btn.clicked.connect(self._add_table)
        edit_btn.clicked.connect(self._edit_table)
        delete_btn.clicked.connect(self._delete_table)
        close_btn.clicked.connect(self.accept)

        btn_row.addWidget(add_btn)
        btn_row.addWidget(edit_btn)
        btn_row.addWidget(delete_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self.refresh()

    def refresh(self):
        try:
            rows = self.service.list_tables()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
            rows = []
        self.table.setRowCount(0)
        for table in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            status = "Open" if int(table.get("item_count") or 0) > 0 else "Empty"
            active_time = _elapsed_active_time(table.get("open_started_at"))
            status_text = f"{status} - {active_time}" if active_time else status
            values = [
                str(table["id"]),
                str(table["table_number"]),
                str(table.get("label") or ""),
                f"{status_text} - ${float(table.get('total_amount') or 0):.2f}" if status == "Open" else status_text,
            ]
            for col, value in enumerate(values):
                self.table.setItem(r, col, QTableWidgetItem(value))

    def _selected_table_id(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        id_item = self.table.item(row, 0)
        return int(id_item.text()) if id_item else None

    def _add_table(self):
        table_number, ok = QInputDialog.getText(self, "Add Table", "Table number:")
        if not ok:
            return
        label, ok = QInputDialog.getText(self, "Add Table", "Optional label:")
        if not ok:
            label = ""
        try:
            self.service.create_table(table_number, label)
            self.refresh()
        except Exception as e:
            QMessageBox.NoIcon(self, "Could not add table", str(e))

    def _edit_table(self):
        table_id = self._selected_table_id()
        if table_id is None:
            QMessageBox.information(self, "No Selection", "Select a table first.")
            return
        row = self.table.currentRow()
        current_number = self.table.item(row, 1).text() if self.table.item(row, 1) else ""
        current_label = self.table.item(row, 2).text() if self.table.item(row, 2) else ""

        table_number, ok = QInputDialog.getText(self, "Edit Table", "Table number:", text=current_number)
        if not ok:
            return
        label, ok = QInputDialog.getText(self, "Edit Table", "Optional label:", text=current_label)
        if not ok:
            label = current_label
        try:
            self.service.update_table(table_id, table_number, label)
            self.refresh()
        except Exception as e:
            QMessageBox.NoIcon(self, "Could not update table", str(e))

    def _delete_table(self):
        table_id = self._selected_table_id()
        if table_id is None:
            QMessageBox.information(self, "No Selection", "Select a table first.")
            return
        row = self.table.currentRow()
        table_number = self.table.item(row, 1).text() if self.table.item(row, 1) else str(table_id)
        reply = QMessageBox.question(
            self,
            "Delete Table",
            f"Delete table {table_number}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self.service.delete_table(table_id)
            self.refresh()
        except Exception as e:
            QMessageBox.NoIcon(self, "Could not delete table", str(e))


def _elapsed_active_time(started_at) -> str:
    if not started_at:
        return ""
    try:
        started = datetime.fromisoformat(str(started_at).replace(" ", "T"))
        elapsed = datetime.utcnow() - started
        total_minutes = max(0, int(elapsed.total_seconds() // 60))
        hours, minutes = divmod(total_minutes, 60)
        if hours:
            return f"{hours}h {minutes}m"
        if minutes:
            return f"{minutes}m"
        return "<1m"
    except Exception:
        return ""

# basically the whole ui stuff relating to ordering menu. UI build part.
class OrderingWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        _ensure_db()
        self.table_service = TableService()
        self._grid_columns = 3
        self._grid_card_width = 168
        self._cart: Dict[str, Dict] = {}
        self._selected_table = None
        self._tables: List[Dict] = []
        self._all_rows: List[Dict] = []
        self._view_rows: List[Dict] = []
        self._current_category = "All"
        self._is_loading = False
        self._initialized = False
        self._animations = []
        self._table_visual_state: Dict[int, tuple] = {}
        self._table_cards: Dict[int, TableCardFrame] = {}
        self._last_added_cart_key: str | None = None
        self._pending_fly_cart_key: str | None = None
        self._cart_row_widgets: Dict[str, QFrame] = {}
        self._move_source_table_id: int | None = None
        self._move_hover_table_id: int | None = None
        self._move_filter_active = False
        self._setup_ui()

    def _setup_ui(self):
        self.setStyleSheet(f"background-color: {BG_MAIN};")
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        table_panel = QFrame()
        table_panel.setObjectName("orderPanel")
        table_panel.setStyleSheet(ORDER_PANEL_STYLE)
        table_panel.setFixedWidth(210)
        table_layout = QVBoxLayout(table_panel)
        table_layout.setContentsMargins(14, 18, 14, 18)
        table_layout.setSpacing(10)

        table_header = QHBoxLayout()
        table_title = QLabel("Tables")
        table_title.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {TEXT_PRIMARY}; background: transparent;")
        table_header.addWidget(table_title)
        table_header.addStretch()

        manage_btn = QPushButton("Manage")
        manage_btn.setMinimumHeight(34)
        manage_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        manage_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {GREEN_LIGHT};
                color: {GREEN};
                border: 1px solid {GREEN};
                border-radius: 8px;
                padding: 6px 12px;
                font-size: 12px;
                font-weight: 700;
            }}
            QPushButton:hover {{ background-color: {GREEN_PALE}; }}
        """)
        manage_btn.clicked.connect(self._open_table_management)
        table_header.addWidget(manage_btn)
        table_layout.addLayout(table_header)

        self.table_hint = QLabel("Select a table to start or continue an order.")
        self.table_hint.setWordWrap(True)
        self.table_hint.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; background: transparent;")
        table_layout.addWidget(self.table_hint)

        self.table_scroll = QScrollArea()
        self.table_scroll.setWidgetResizable(True)
        self.table_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.table_container = QWidget()
        self.table_container.setStyleSheet("background: transparent;")
        self.table_list_layout = QVBoxLayout(self.table_container)
        self.table_list_layout.setContentsMargins(0, 0, 0, 0)
        self.table_list_layout.setSpacing(8)
        self.table_list_layout.addStretch()
        self.table_scroll.setWidget(self.table_container)
        table_layout.addWidget(self.table_scroll, 1)

        left_panel = QWidget()
        left_panel.setStyleSheet(f"background-color: {BG_MAIN};")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(16, 18, 8, 18)
        left_layout.setSpacing(0)

        search_row = QHBoxLayout()
        search_row.setSpacing(10)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search Product here...")
        self.search_edit.setMinimumHeight(42)
        self.search_edit.setStyleSheet(f"""
            QLineEdit {{
                background-color: {BG_WHITE};
                border: 1.5px solid {BORDER};
                border-radius: 12px;
                padding: 8px 16px;
                font-size: 14px;
                color: {TEXT_PRIMARY};
            }}
            QLineEdit:focus {{
                border-color: {GREEN};
            }}
        """)
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self._on_search_changed)
        self.search_edit.textChanged.connect(self._on_search_text_changed)
        search_row.addWidget(self.search_edit)
        left_layout.addLayout(search_row)

        cat_scroll = QScrollArea()
        cat_scroll.setWidgetResizable(True)
        cat_scroll.setFixedHeight(50)
        cat_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        cat_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        cat_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        cat_container = QWidget()
        cat_container.setStyleSheet("background: transparent;")
        self.category_layout = QHBoxLayout(cat_container)
        self.category_layout.setContentsMargins(0, 0, 0, 0)
        self.category_layout.setSpacing(8)

        self.category_buttons = QButtonGroup(self)
        all_btn = QPushButton("All")
        all_btn.setCheckable(True)
        all_btn.setChecked(True)
        all_btn.setStyleSheet(CATEGORY_PILL_STYLE)
        all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.category_buttons.addButton(all_btn, 0)
        self.category_layout.addWidget(all_btn)
        self.category_buttons.buttonClicked.connect(self._on_category_changed)
        self.category_layout.addStretch()

        cat_scroll.setWidget(cat_container)
        left_layout.addWidget(cat_scroll)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.inventory_container = QWidget()
        self.inventory_container.setStyleSheet("background: transparent;")
        self.inventory_grid = QGridLayout(self.inventory_container)
        self.inventory_grid.setSpacing(14)
        self.inventory_grid.setContentsMargins(2, 2, 2, 2)
        self.inventory_grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.scroll_area.setWidget(self.inventory_container)
        self.item_widgets = {}

        left_layout.addWidget(self.scroll_area, 1)

        right_panel = QFrame()
        right_panel.setObjectName("orderPanel")
        right_panel.setStyleSheet(ORDER_PANEL_STYLE)
        right_panel.setFixedWidth(300)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(16, 18, 16, 18)
        right_layout.setSpacing(12)

        order_title = QLabel("Order Summary")
        order_title.setStyleSheet(f"font-size: 17px; font-weight: 700; color: {TEXT_PRIMARY}; background: transparent;")
        right_layout.addWidget(order_title)

        self.selected_table_label = QLabel("No table selected")
        self.selected_table_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; background: transparent;")
        right_layout.addWidget(self.selected_table_label)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {BORDER};")
        right_layout.addWidget(sep)

        self.order_items_area = QScrollArea()
        self.order_items_area.setWidgetResizable(True)
        self.order_items_area.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.order_items_container = QWidget()
        self.order_items_container.setStyleSheet("background: transparent;")
        self.order_items_layout = QVBoxLayout(self.order_items_container)
        self.order_items_layout.setContentsMargins(0, 0, 0, 0)
        self.order_items_layout.setSpacing(8)
        self.order_items_layout.addStretch()
        self.order_items_area.setWidget(self.order_items_container)
        right_layout.addWidget(self.order_items_area, 1)

        sep2 = QFrame()
        sep2.setFixedHeight(1)
        sep2.setStyleSheet(f"background-color: {BORDER};")
        right_layout.addWidget(sep2)

        totals_layout = QVBoxLayout()
        totals_layout.setSpacing(6)


        sub_row = QHBoxLayout()
        sub_lbl = QLabel("Sub Total")
        sub_lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 13px; background: transparent;")
        self.subtotal_value = QLabel("$0.00")
        self.subtotal_value.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px; font-weight: 600; background: transparent;")
        self.subtotal_value.setAlignment(Qt.AlignRight)
        sub_row.addWidget(sub_lbl)
        sub_row.addStretch()
        sub_row.addWidget(self.subtotal_value)
        totals_layout.addLayout(sub_row)

        tax_row = QHBoxLayout()
        self.tax_label = QLabel("VAT")
        self.tax_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 13px; background: transparent;")
        self.tax_value = QLabel("$0.00")
        self.tax_value.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px; font-weight: 600; background: transparent;")
        self.tax_value.setAlignment(Qt.AlignRight)
        tax_row.addWidget(self.tax_label)
        tax_row.addStretch()
        tax_row.addWidget(self.tax_value)
        totals_layout.addLayout(tax_row)

        total_sep = QFrame()
        total_sep.setFixedHeight(1)
        total_sep.setStyleSheet(f"background-color: {BORDER};")
        totals_layout.addWidget(total_sep)

        total_row = QHBoxLayout()
        total_lbl = QLabel("Total Amount")
        total_lbl.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 16px; font-weight: 700; background: transparent;")
        self.total_label = QLabel("$0.00")
        self.total_label.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 18px; font-weight: 700; background: transparent;")
        self.total_label.setAlignment(Qt.AlignRight)
        total_row.addWidget(total_lbl)
        total_row.addStretch()
        total_row.addWidget(self.total_label)
        totals_layout.addLayout(total_row)

        right_layout.addLayout(totals_layout)

        payment_row = QHBoxLayout()
        payment_row.setSpacing(10)
        cash_btn = QPushButton("Cash")
        cash_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {GREEN_LIGHT};
                color: {GREEN};
                border: 1.5px solid {GREEN};
                border-radius: 10px;
                padding: 10px 16px;
                font-size: 13px;
                font-weight: 600;
            }}
        """)
        cash_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        payment_row.addWidget(cash_btn)
        payment_row.addStretch()
        right_layout.addLayout(payment_row)

        self.checkout_btn = QPushButton("Checkout")
        self.checkout_btn.setMinimumHeight(46)
        self.checkout_btn.setStyleSheet(CHECKOUT_BTN_STYLE)
        self.checkout_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.checkout_btn.clicked.connect(self._on_checkout)
        right_layout.addWidget(self.checkout_btn)

        main_layout.addWidget(table_panel)
        main_layout.addWidget(left_panel, 1)
        main_layout.addWidget(right_panel)

        self._grid_timer = QTimer(self)
        self._grid_timer.setInterval(10)
        self._grid_timer.timeout.connect(self._build_grid_chunk)
        self._grid_cursor = 0

        QTimer.singleShot(100, self._initial_load)
        QTimer.singleShot(150, self._refresh_tables)

        self.table_timer = QTimer(self)
        self.table_timer.timeout.connect(self._refresh_tables)
        self.table_timer.start(60000)

    def _initial_load(self):
        if not self._initialized:
            self._initialized = True
            self._populate_inventory_when_ready()

    def _remember_animation(self, animation):
        self._animations.append(animation)
        animation.finished.connect(lambda: self._animations.remove(animation) if animation in self._animations else None)

    def _is_qt_alive(self, obj) -> bool:
        try:
            return obj is not None and _qt_is_valid(obj)
        except RuntimeError:
            return False

    def _animate_widget_entry(self, widget, delay: int = 0, grow: bool = False):
        if not self._is_qt_alive(widget):
            return

        effect = QGraphicsOpacityEffect(widget)
        effect.setOpacity(0.0)
        widget.setGraphicsEffect(effect)

        group = QParallelAnimationGroup(self)

        opacity = QPropertyAnimation(effect, b"opacity", group)
        opacity.setDuration(220)
        opacity.setStartValue(0.0)
        opacity.setEndValue(1.0)
        opacity.setEasingCurve(QEasingCurve.Type.OutCubic)
        group.addAnimation(opacity)

        if grow:
            target_height = max(1, widget.sizeHint().height())
            widget.setMaximumHeight(0)
            height = QPropertyAnimation(widget, b"maximumHeight", group)
            height.setDuration(260)
            height.setStartValue(0)
            height.setEndValue(target_height)
            height.setEasingCurve(QEasingCurve.Type.OutBack)
            group.addAnimation(height)

        def finish():
            try:
                if not self._is_qt_alive(widget):
                    return
                widget.setGraphicsEffect(None)
                if grow:
                    widget.setMaximumHeight(16777215)
            except RuntimeError:
                pass

        group.finished.connect(finish)
        self._remember_animation(group)
        def start_group():
            try:
                if not self._is_qt_alive(widget) or not self._is_qt_alive(effect):
                    if group in self._animations:
                        self._animations.remove(group)
                    group.deleteLater()
                    return
                group.start()
            except RuntimeError:
                if group in self._animations:
                    self._animations.remove(group)
                try:
                    group.deleteLater()
                except RuntimeError:
                    pass
        if delay:
            QTimer.singleShot(delay, start_group)
        else:
            start_group()

    def _open_table_management(self):
        self._cancel_move_mode()
        dlg = TableManagementDialog(self)
        dlg.exec()
        self._refresh_tables()

    def _clear_table_list(self):
        self._table_cards.clear()
        while self.table_list_layout.count():
            child = self.table_list_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def _update_table_hint(self):
        if self._move_source_table_id is not None:
            source = next((table for table in self._tables if int(table.get("id")) == self._move_source_table_id), None)
            table_number = source.get("table_number") if source else "?"
            self.table_hint.setText(
                f"Move mode for table {table_number}. Click a destination table, or click anywhere else to cancel."
            )
            self.table_hint.setStyleSheet(f"color: #2F5B9A; font-size: 12px; font-weight: 700; background: transparent;")
            return
        if self._selected_table:
            self.table_hint.setText("Right-click the selected table to move its current order.")
            self.table_hint.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; background: transparent;")
            return
        self.table_hint.setText("Select a table to start or continue an order.")
        self.table_hint.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; background: transparent;")

    def _table_card_style(self, table, is_selected: bool, is_hovered_target: bool) -> str:
        is_open = int(table.get("item_count") or 0) > 0
        is_move_source = self._move_source_table_id == int(table.get("id"))

        if is_hovered_target:
            bg_color = "#D8E5FF"
            border_color = "#2F5B9A"
        elif is_move_source:
            bg_color = "#EAF3FF"
            border_color = "#2F5B9A"
        elif is_selected:
            bg_color = GREEN_LIGHT
            border_color = GREEN
        else:
            bg_color = BG_WHITE
            border_color = ORANGE if is_open else BORDER

        return f"""
            QFrame {{
                background-color: {bg_color};
                border: 1.5px solid {border_color};
                border-radius: 12px;
            }}
        """

    def _refresh_table_card_styles(self):
        for table in self._tables:
            table_id = int(table.get("id"))
            card = self._table_cards.get(table_id)
            if not self._is_qt_alive(card):
                continue
            is_selected = bool(self._selected_table and self._selected_table.get("id") == table_id)
            is_hovered_target = (
                self._move_source_table_id is not None
                and table_id != self._move_source_table_id
                and self._move_hover_table_id == table_id
            )
            card.setStyleSheet(self._table_card_style(table, is_selected, is_hovered_target))

    def _table_card_from_widget(self, widget):
        current = widget
        while current is not None:
            if isinstance(current, TableCardFrame):
                return current
            current = current.parentWidget()
        return None

    def _show_table_move_menu(self, table, global_pos: QPoint):
        if not self._selected_table or self._selected_table.get("id") != table.get("id"):
            return
        if not self._cart:
            QMessageBox.information(self, "No Active Order", "This table does not have an order to move.")
            return

        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {BG_WHITE};
                border: 1px solid {BORDER};
                border-radius: 10px;
                padding: 6px;
            }}
            QMenu::item {{
                padding: 8px 22px;
                border-radius: 8px;
                color: {TEXT_PRIMARY};
                font-size: 12px;
                font-weight: 700;
            }}
            QMenu::item:selected {{
                background-color: #D8E5FF;
                color: #2F5B9A;
            }}
        """)
        move_action = menu.addAction("Move To")
        chosen = menu.exec(global_pos)
        if chosen == move_action:
            self._start_move_mode(table)

    def _start_move_mode(self, table):
        if not self._selected_table or self._selected_table.get("id") != table.get("id"):
            return
        if not self._cart:
            QMessageBox.information(self, "No Active Order", "This table does not have an order to move.")
            return
        if not self._save_current_order(show_message=False):
            return

        self._move_source_table_id = int(table["id"])
        self._move_hover_table_id = None
        app = QApplication.instance()
        if app and not self._move_filter_active:
            app.installEventFilter(self)
            self._move_filter_active = True
        self._update_table_hint()
        self._refresh_table_card_styles()

    def _cancel_move_mode(self):
        self._move_source_table_id = None
        self._move_hover_table_id = None
        app = QApplication.instance()
        if app and self._move_filter_active:
            app.removeEventFilter(self)
        self._move_filter_active = False
        self._update_table_hint()
        self._refresh_table_card_styles()

    def _handle_table_card_hover(self, table):
        if self._move_source_table_id is None:
            return
        table_id = int(table.get("id"))
        hover_id = None if table_id == self._move_source_table_id else table_id
        if hover_id == self._move_hover_table_id:
            return
        self._move_hover_table_id = hover_id
        self._refresh_table_card_styles()

    def _handle_table_card_leave(self, table):
        if self._move_source_table_id is None:
            return
        if self._move_hover_table_id != int(table.get("id")):
            return
        self._move_hover_table_id = None
        self._refresh_table_card_styles()

    def _move_selected_order(self, target_table):
        if self._move_source_table_id is None:
            return

        target_table_id = int(target_table["id"])
        if target_table_id == self._move_source_table_id:
            return
        if int(target_table.get("item_count") or 0) > 0:
            QMessageBox.NoIcon(
                self,
                "Table Occupied",
                f"Table {target_table['table_number']} already has an open order. Pick an empty table.",
            )
            return

        source_table = next(
            (table for table in self._tables if int(table.get("id")) == self._move_source_table_id),
            self._selected_table,
        )
        if not source_table:
            self._cancel_move_mode()
            return

        reply = QMessageBox.question(
            self,
            "Move Order",
            (
                f"Move the full order from table {source_table['table_number']} "
                f"to table {target_table['table_number']}?\n\n"
                "The table timer and all order items will move with it."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            self.table_service.move_open_order(self._move_source_table_id, target_table_id)
            self._refresh_tables()
            moved_table = next((table for table in self._tables if int(table.get("id")) == target_table_id), None)
            self._selected_table = moved_table
            self._cart = self.table_service.load_open_order_cart(target_table_id) if moved_table else {}
            self._refresh_order_panel()
            self._refresh_tables()
        except Exception as e:
            QMessageBox.NoIcon(self, "Could not move order", str(e))
            return
        finally:
            self._cancel_move_mode()

    def _handle_table_card_click(self, table):
        if self._move_source_table_id is not None:
            self._move_selected_order(table)
            return
        self._select_table(table)

    def eventFilter(self, obj, event):
        if self._move_source_table_id is not None:
            if QApplication.activeModalWidget() is not None:
                return super().eventFilter(obj, event)
            if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
                self._cancel_move_mode()
                return True
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
                    card = self._table_card_from_widget(QApplication.widgetAt(event.globalPosition().toPoint()))
                    if card is None:
                        self._cancel_move_mode()
        return super().eventFilter(obj, event)

    def _refresh_tables(self):
        self._clear_table_list()
        try:
            self._tables = self.table_service.list_tables()
        except Exception as e:
            error = QLabel(f"Failed to load tables: {e}")
            error.setWordWrap(True)
            error.setStyleSheet(f"color: {RED}; font-size: 12px; background: transparent;")
            self.table_list_layout.addWidget(error)
            self.table_list_layout.addStretch()
            return

        if not self._tables:
            empty = QLabel("No tables yet. Use Manage to create tables before taking orders.")
            empty.setWordWrap(True)
            empty.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; background: transparent;")
            self.table_list_layout.addWidget(empty)
            self.table_list_layout.addStretch()
            self._selected_table = None
            self._table_visual_state.clear()
            self._cart.clear()
            self._refresh_order_panel()
            self._update_selected_table_label()
            self._update_table_hint()
            return

        selected_id = self._selected_table.get("id") if self._selected_table else None
        if selected_id and not any(t["id"] == selected_id for t in self._tables):
            self._selected_table = None
            self._cart.clear()
            self._refresh_order_panel()
        if self._move_source_table_id and not any(int(t["id"]) == self._move_source_table_id for t in self._tables):
            self._cancel_move_mode()

        new_visual_state = {}
        for table in self._tables:
            table_id = int(table.get("id"))
            visual_state = (
                int(table.get("item_count") or 0) > 0,
                bool(self._selected_table and self._selected_table.get("id") == table.get("id")),
                int(table.get("item_count") or 0),
            )
            new_visual_state[table_id] = visual_state
            card = self._create_table_card(table)
            self._table_cards[table_id] = card
            self.table_list_layout.addWidget(card)
        self._table_visual_state = new_visual_state
        self.table_list_layout.addStretch()
        self._update_selected_table_label()
        self._update_table_hint()
        self._refresh_table_card_styles()

    def _create_table_card(self, table):
        is_selected = self._selected_table and self._selected_table.get("id") == table.get("id")
        item_count = int(table.get("item_count") or 0)
        total_amount = float(table.get("total_amount") or 0)
        active_time = _elapsed_active_time(table.get("open_started_at"))
        is_open = item_count > 0
        status_text = "Open" if is_open else "Empty"
        if is_open and active_time:
            status_text = active_time
        status_color = ORANGE if is_open else TEXT_MUTED

        card = TableCardFrame(table)
        card.setStyleSheet(self._table_card_style(table, bool(is_selected), False))
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        top = QHBoxLayout()
        number = QLabel(f"Table {table['table_number']}")
        number.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 15px; font-weight: 700; background: transparent;")
        top.addWidget(number)
        top.addStretch()
        status = QLabel(status_text)
        status.setStyleSheet(f"color: {status_color}; font-size: 12px; font-weight: 700; background: transparent;")
        top.addWidget(status)
        layout.addLayout(top)

        label = str(table.get("label") or "").strip()
        if label:
            label_widget = QLabel(label)
            label_widget.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px; background: transparent;")
            label_widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            layout.addWidget(label_widget)

        detail = QLabel(f"{item_count} items - ${total_amount:.2f}" if is_open else "Ready for a new order")
        detail.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; background: transparent;")
        number.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        status.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        detail.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(detail)

        card.leftClicked.connect(self._handle_table_card_click)
        card.rightClicked.connect(self._show_table_move_menu)
        card.hovered.connect(self._handle_table_card_hover)
        card.hoverLeft.connect(self._handle_table_card_leave)
        return card

    def _select_table(self, table):
        if self._move_source_table_id is not None:
            return
        if self._selected_table and self._selected_table.get("id") != table.get("id") and self._cart:
            try:
                self.table_service.save_open_order_cart(self._selected_table["id"], self._cart)
            except Exception as e:
                QMessageBox.NoIcon(self, "Could not save order", str(e))
                return
        self._selected_table = table
        try:
            self._cart = self.table_service.load_open_order_cart(table["id"])
        except Exception as e:
            self._cart = {}
            QMessageBox.NoIcon(self, "Could not load order", str(e))
        self._refresh_order_panel()
        self._refresh_tables()

    def _update_selected_table_label(self):
        if self._selected_table:
            self.selected_table_label.setText(f"Table {self._selected_table['table_number']}")
            self.selected_table_label.setStyleSheet(f"color: {GREEN}; font-size: 12px; font-weight: 700; background: transparent;")
        else:
            self.selected_table_label.setText("No table selected")
            self.selected_table_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; background: transparent;")
        self._update_table_hint()

    def _save_current_order(self, show_message: bool = True):
        if not self._selected_table:
            QMessageBox.information(self, "Select Table", "Select a table before saving an order.")
            return False
        try:
            self.table_service.save_open_order_cart(self._selected_table["id"], self._cart)
            self._refresh_tables()
            if show_message:
                QMessageBox.information(self, "Order Held", f"Order held for table {self._selected_table['table_number']}.")
            return True
        except Exception as e:
            QMessageBox.critical(self, "Could not save order", str(e))
            return False

    def _on_search_text_changed(self):
        self.search_timer.start(300)

    def _on_search_changed(self):
        self._apply_filter_and_rebuild()

    def _on_category_changed(self, btn):
        self._current_category = btn.text()
        self._apply_filter_and_rebuild()

    def _populate_inventory_when_ready(self):
        if self._is_loading:
            return
        self._is_loading = True
        self._show_loading_skeleton()
        result = {"rows": [], "err": None}
        done = threading.Event()

        def worker():
            try:
                rows = _fetch_all_items()
                result["rows"] = [_prepare_row_for_display(r) for r in rows]
            except Exception as e:
                result["err"] = e
            finally:
                done.set()

        threading.Thread(target=worker, daemon=True).start()

        self._inv_poll = QTimer(self)
        self._inv_poll.setInterval(100)

        def _poll():
            if not done.is_set():
                return
            self._inv_poll.stop()
            if hasattr(self, '_skeleton_timer'):
                self._skeleton_timer.stop()
            if result["err"]:
                self._clear_inventory_grid()
                label = QLabel("Failed to load inventory.")
                label.setStyleSheet(f"color: {RED}; font-size: 14px; background: transparent;")
                label.setAlignment(Qt.AlignCenter)
                self.inventory_grid.addWidget(label, 0, 0)
                self._is_loading = False
                return
            self._all_rows = result["rows"]
            self._rebuild_category_buttons()
            self._apply_filter_and_rebuild()
            self._is_loading = False

        self._inv_poll.timeout.connect(_poll)
        self._inv_poll.start()

    def _show_loading_skeleton(self):
        self._clear_inventory_grid()
        if hasattr(self, "scroll_area"):
            self._grid_columns, self._grid_card_width = self._calculate_grid_metrics(self.scroll_area.viewport().width())
        for i in range(9):
            card = QFrame()
            card.setFixedWidth(self._grid_card_width)
            card.setStyleSheet(f"""
                QFrame {{
                    background-color: {BG_WHITE};
                    border: 1px solid {BORDER};
                    border-radius: 12px;
                    min-height: 140px;
                }}
            """)
            skel_layout = QVBoxLayout(card)
            img_ph = QLabel()
            img_ph.setFixedSize(80, 80)
            img_ph.setStyleSheet(f"background: {BG_MAIN}; border-radius: 8px;")
            img_ph.setAlignment(Qt.AlignCenter)
            skel_layout.addWidget(img_ph, alignment=Qt.AlignHCenter)
            name_ph = QLabel()
            name_ph.setFixedHeight(14)
            name_ph.setStyleSheet(f"background: {BG_MAIN}; border-radius: 4px;")
            skel_layout.addWidget(name_ph)
            price_ph = QLabel()
            price_ph.setFixedHeight(12)
            price_ph.setStyleSheet(f"background: {BORDER}; border-radius: 4px;")
            skel_layout.addWidget(price_ph)
            self.inventory_grid.addWidget(card, i // 3, i % 3)

        self._skeleton_timer = QTimer(self)
        self._skeleton_offset = 0
        def _animate():
            self._skeleton_offset = (self._skeleton_offset + 8) % 200
        self._skeleton_timer.timeout.connect(_animate)
        self._skeleton_timer.start(50)

    def _clear_inventory_grid(self):
        if self._grid_timer.isActive():
            self._grid_timer.stop()
        for i in reversed(range(self.inventory_grid.count())):
            w = self.inventory_grid.itemAt(i).widget()
            if w:
                w.setParent(None)
                w.deleteLater()

    def _rebuild_category_buttons(self):
        cats = set()
        for row in self._all_rows:
            c = row.get('category')
            if c:
                cats.add(c)
        for btn in list(self.category_buttons.buttons()):
            if btn.text() != "All":
                self.category_buttons.removeButton(btn)
                btn.deleteLater()
        for cat in sorted(cats):
            btn = QPushButton(cat)
            btn.setCheckable(True)
            btn.setStyleSheet(CATEGORY_PILL_STYLE)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.category_buttons.addButton(btn)
            self.category_layout.insertWidget(self.category_layout.count() - 1, btn)

    def _apply_filter_and_rebuild(self):
        if hasattr(self, "scroll_area"):
            self._grid_columns, self._grid_card_width = self._calculate_grid_metrics(self.scroll_area.viewport().width())
        search = self.search_edit.text().strip().lower()
        cat = self._current_category
        self._view_rows = []
        for row in self._all_rows:
            if cat != "All" and row.get('category') != cat:
                continue
            if search:
                if search not in str(row.get('id', '')).lower() and search not in row.get('name', '').lower():
                    continue
            self._view_rows.append(row)
        self._view_rows = _sort_stock_alerts_first(self._view_rows)
        self._clear_inventory_grid()
        self.item_widgets.clear()
        self._grid_cursor = 0
        if not self._grid_timer.isActive():
            self._grid_timer.start()

    def _calculate_grid_metrics(self, viewport_width: int) -> tuple[int, int]:
        min_card_width = 160
        max_card_width = 310
        spacing = self.inventory_grid.horizontalSpacing()
        margins = self.inventory_grid.contentsMargins()
        usable_width = max(0, viewport_width - margins.left() - margins.right() - 18)
        columns = max(2, min(3, (usable_width + spacing) // (min_card_width + spacing)))
        card_width = max(min_card_width, min(max_card_width, (usable_width - (spacing * (columns - 1))) // columns))
        return columns, card_width

    def _stock_tone(self, quantity: int) -> tuple[str, str, str]:
        qty = int(quantity or 0)
        if qty <= 0:
            return STOCK_OUT_BORDER, STOCK_OUT_BG, "Out of stock"
        if qty < LOW_STOCK_THRESHOLD:
            return STOCK_LOW_BORDER, STOCK_LOW_BG, f"Low stock: {qty}"
        return BORDER, BG_WHITE, f"Stock: {qty}"

    def _item_card_style(self, quantity: int) -> str:
        border_color, bg_color, _ = self._stock_tone(quantity)
        hover_color = GREEN if border_color == BORDER else border_color
        return f"""
            QFrame#itemCard {{
                background-color: {bg_color};
                border: {2 if border_color != BORDER else 1}px solid {border_color};
                border-radius: 10px;
            }}
            QFrame#itemCard:hover {{
                border-color: {hover_color};
            }}
        """

    def _apply_card_width_to_existing(self):
        for card in self.item_widgets.values():
            card.setFixedWidth(self._grid_card_width)
        for i in range(self.inventory_grid.count()):
            widget = self.inventory_grid.itemAt(i).widget()
            if widget:
                widget.setFixedWidth(self._grid_card_width)

    def _build_grid_chunk(self):
        if not self._view_rows or self._grid_cursor >= len(self._view_rows):
            self._grid_timer.stop()
            return
        cols = self._grid_columns
        for _ in range(10):
            if self._grid_cursor >= len(self._view_rows):
                break
            item = self._view_rows[self._grid_cursor]
            row = self._grid_cursor // cols
            col = self._grid_cursor % cols
            card = self._create_item_card(item)
            self.inventory_grid.addWidget(card, row, col)
            self._animate_widget_entry(card, delay=min(col * 35, 120), grow=False)
            self.item_widgets[item['id']] = card
            self._grid_cursor += 1
        if self._grid_cursor >= len(self._view_rows):
            self._grid_timer.stop()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, "scroll_area"):
            return
        viewport_width = self.scroll_area.viewport().width()
        old_card_width = self._grid_card_width
        columns, card_width = self._calculate_grid_metrics(viewport_width)
        width_changed = abs(card_width - old_card_width) > 12
        layout_mode_changed = (old_card_width >= 220) != (card_width >= 220)
        self._grid_card_width = card_width
        columns_changed = columns != self._grid_columns
        if columns_changed:
            self._grid_columns = columns
        if columns_changed or layout_mode_changed or width_changed:
            if self._view_rows and not self._is_loading:
                self._apply_filter_and_rebuild()
            else:
                self._apply_card_width_to_existing()

    def _create_item_card(self, item):
        card = QFrame()
        card.setObjectName("itemCard")
        quantity = int(item.get('quantity') or 0)
        card.setProperty("quantity", quantity)
        card.setStyleSheet(self._item_card_style(quantity))
        card.setFixedWidth(self._grid_card_width)
        card.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Minimum)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        content_row = QHBoxLayout()
        content_row.setSpacing(12)
        use_side_by_side = self._grid_card_width >= 220
        image_size = max(78, min(108 if use_side_by_side else 92, self._grid_card_width // (3 if use_side_by_side else 2)))

        if item.get('image'):
            thumb = _make_thumbnail_pixmap(item['image'], (image_size, image_size))
            if thumb:
                img = QLabel()
                img.setPixmap(thumb)
                img.setAlignment(Qt.AlignCenter)
                img.setStyleSheet("background: transparent;")
                if use_side_by_side:
                    img.setFixedSize(image_size, image_size)
                    content_row.addWidget(img, alignment=Qt.AlignTop)
                else:
                    layout.addWidget(img, alignment=Qt.AlignHCenter)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(5)
        name = QLabel(item['name'])
        name.setStyleSheet(f"color: {TEXT_PRIMARY}; font-weight: 600; font-size: 13px; background: transparent;")
        name.setWordWrap(True)
        info_layout.addWidget(name)

        price = QLabel(f"${float(item['price']):.2f}")
        price.setStyleSheet(f"color: {GREEN}; font-weight: 700; font-size: 14px; background: transparent;")
        info_layout.addWidget(price)

        cat_text = str(item.get('category', '') or '')
        if cat_text:
            cat_label = QLabel(cat_text)
            cat_label.setStyleSheet(f"""
                color: {TEXT_MUTED};
                font-size: 11px;
                background-color: {BG_MAIN};
                border-radius: 4px;
                padding: 2px 6px;
            """)
            info_layout.addWidget(cat_label, alignment=Qt.AlignLeft)

        stock_color, _, stock_text = self._stock_tone(quantity)
        if stock_color == BORDER:
            stock_color = TEXT_MUTED
        stock = QLabel(stock_text)
        stock.setStyleSheet(f"color: {stock_color}; font-size: 11px; background: transparent;")
        info_layout.addWidget(stock)

        if use_side_by_side:
            info_layout.addStretch()
            content_row.addLayout(info_layout, 1)
            layout.addLayout(content_row)
        else:
            layout.addLayout(info_layout)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        spin = QSpinBox()
        if quantity <= 0:
            spin.setRange(0, 0)
            spin.setValue(0)
        else:
            spin.setRange(1, max(1, min(99, quantity)))
            spin.setValue(1)
        spin.setFixedWidth(44)
        spin.setFixedHeight(30)
        spin.setStyleSheet(f"""
            QSpinBox {{
                background: {BG_MAIN};
                border: 1px solid {BORDER};
                border-radius: 6px;
                padding: 2px 4px;
                font-size: 12px;
                color: {TEXT_PRIMARY};
            }}
        """)
        add_btn = QPushButton("Add")
        add_btn.setStyleSheet(ADD_BTN_STYLE)
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setFixedHeight(30)
        add_btn.setMinimumWidth(74)
        add_btn.setEnabled(quantity > 0)
        if quantity <= 0:
            add_btn.setText("Out")
        add_btn.clicked.connect(lambda _, i=item, s=spin, c=card, b=add_btn: self._on_add_item(i, s.value(), c, b))
        btn_row.addWidget(spin)
        btn_row.addWidget(add_btn, 1)
        layout.addLayout(btn_row)

        return card

    def _get_available_quantity(self, item_id: int) -> int:
        for row in self._all_rows:
            if row.get("id") == item_id:
                return int(row.get("quantity", 0))
        item = _get_item_by_id(item_id)
        return int(item["quantity"]) if item else 0

    def _get_cart_quantity_for_item(self, item_id: int, exclude_key: str | None = None) -> int:
        total_qty = 0
        for cart_key, cart_item in self._cart.items():
            if exclude_key is not None and cart_key == exclude_key:
                continue
            if cart_item.get("id") == item_id:
                total_qty += int(cart_item.get("qty", 0))
        return total_qty

    def _play_add_feedback(self, card, button, cart_key: str | None = None):
        fly_started = self._play_fly_to_cart(card, cart_key)
        if not fly_started and cart_key:
            self._reveal_cart_arrival(cart_key)
        if button:
            old_text = button.text()
            button.setText("Added")
            def restore_button():
                try:
                    button.setText(old_text)
                except RuntimeError:
                    pass
            QTimer.singleShot(650, restore_button)
        if card and not fly_started:
            card.setStyleSheet(f"""
                QFrame#itemCard {{
                    background-color: {GREEN_LIGHT};
                    border: 1px solid {GREEN};
                    border-radius: 10px;
                }}
            """)
            quantity = int(card.property("quantity") or 0)
            def restore_card():
                try:
                    if not self._is_qt_alive(card):
                        return
                    card.setStyleSheet(self._item_card_style(quantity))
                except RuntimeError:
                    pass
            QTimer.singleShot(260, restore_card)

    def _play_fly_to_cart(self, card, cart_key: str | None = None) -> bool:
        target_row = self._cart_row_widgets.get(cart_key) if cart_key else None
        if not self._is_qt_alive(card) or not self._is_qt_alive(target_row):
            return False
        if not hasattr(self, "order_items_area"):
            return False
        try:
            pixmap = card.grab()
        except RuntimeError:
            return False
        if pixmap.isNull():
            return False

        root = self.window() or self
        QApplication.processEvents()
        max_width = 165
        if pixmap.width() > max_width:
            pixmap = pixmap.scaledToWidth(max_width, Qt.TransformationMode.SmoothTransformation)

        clone = QLabel(root)
        clone.setPixmap(pixmap)
        clone.setScaledContents(True)
        clone.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        clone.setStyleSheet("background: transparent; border: none;")

        start_center = root.mapFromGlobal(card.mapToGlobal(card.rect().center()))
        target_center = root.mapFromGlobal(target_row.mapToGlobal(target_row.rect().center()))

        start_size = pixmap.size()
        target_width = max(58, min(target_row.width(), 180))
        end_width = min(target_width, max(58, int(start_size.width() * 0.52)))
        end_height = max(36, int(start_size.height() * (end_width / max(1, start_size.width()))))

        def centered_rect(center, width, height):
            return QRect(
                int(center.x() - width / 2),
                int(center.y() - height / 2),
                int(width),
                int(height),
            )

        dx = target_center.x() - start_center.x()
        arc_lift = max(70, min(150, abs(dx) // 3))
        def mix_point(a, b, t):
            return QPoint(
                int(a.x() + (b.x() - a.x()) * t),
                int(a.y() + (b.y() - a.y()) * t),
            )

        mid1_center = mix_point(start_center, target_center, 0.34)
        mid1_center.setY(min(start_center.y(), target_center.y()) - arc_lift)
        mid2_center = mix_point(start_center, target_center, 0.72)
        mid2_center.setY(target_center.y() - 24)
        bounce_center = mix_point(target_center, QPoint(
            target_center.x() + (target_center.x() - mid2_center.x()),
            target_center.y() + (target_center.y() - mid2_center.y()),
        ), 0.12)

        start_rect = centered_rect(start_center, start_size.width(), start_size.height())
        mid1_rect = centered_rect(mid1_center, start_size.width() * 0.92, start_size.height() * 0.92)
        mid2_rect = centered_rect(mid2_center, end_width * 1.28, end_height * 1.28)
        bounce_rect = centered_rect(bounce_center, end_width * 0.92, end_height * 0.92)
        end_rect = centered_rect(target_center, end_width, end_height)

        clone.setGeometry(start_rect)
        clone.show()
        clone.raise_()

        source_effect = QGraphicsOpacityEffect(card)
        source_effect.setOpacity(0.0)
        card.setGraphicsEffect(source_effect)

        effect = QGraphicsOpacityEffect(clone)
        effect.setOpacity(1.0)
        clone.setGraphicsEffect(effect)

        group = QParallelAnimationGroup(self)

        motion = QPropertyAnimation(clone, b"geometry", group)
        motion.setDuration(760)
        motion.setStartValue(start_rect)
        motion.setKeyValueAt(0.34, mid1_rect)
        motion.setKeyValueAt(0.72, mid2_rect)
        motion.setKeyValueAt(0.88, bounce_rect)
        motion.setEndValue(end_rect)
        motion.setEasingCurve(QEasingCurve.Type.OutCubic)
        group.addAnimation(motion)

        opacity = QPropertyAnimation(effect, b"opacity", group)
        opacity.setDuration(760)
        opacity.setStartValue(1.0)
        opacity.setKeyValueAt(0.78, 1.0)
        opacity.setEndValue(0.0)
        group.addAnimation(opacity)

        old_area_style = self.order_items_area.styleSheet()

        def restore_area_style():
            try:
                self.order_items_area.setStyleSheet(old_area_style)
            except RuntimeError:
                pass

        def finish():
            try:
                clone.deleteLater()
                self._reveal_cart_arrival(cart_key)
                self._soft_restore_source_card(card)
                if self._is_qt_alive(self.order_items_area):
                    self.order_items_area.setStyleSheet(f"""
                        QScrollArea {{
                            border: 2px solid {GREEN};
                            border-radius: 10px;
                            background: transparent;
                        }}
                    """)
                    QTimer.singleShot(180, restore_area_style)
            except RuntimeError:
                pass

        group.finished.connect(finish)
        self._remember_animation(group)
        group.start()
        return True

    def _soft_restore_source_card(self, card):
        if not self._is_qt_alive(card):
            return
        quantity = int(card.property("quantity") or 0)
        try:
            card.setStyleSheet(self._item_card_style(quantity))
            effect = QGraphicsOpacityEffect(card)
            effect.setOpacity(0.0)
            card.setGraphicsEffect(effect)
        except RuntimeError:
            return

        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(240)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutBack)

        def finish():
            try:
                if self._is_qt_alive(card):
                    card.setGraphicsEffect(None)
            except RuntimeError:
                pass

        anim.finished.connect(finish)
        self._remember_animation(anim)
        anim.start()

    def _reveal_cart_arrival(self, cart_key: str | None):
        row = self._cart_row_widgets.get(cart_key) if cart_key else None
        if not self._is_qt_alive(row):
            self._pending_fly_cart_key = None
            return
        self._pending_fly_cart_key = None
        self._animate_widget_entry(row, grow=False)

    def _on_add_item(self, item, qty, card=None, button=None):
        if not self._selected_table:
            QMessageBox.information(self, "Select Table", "Select a table before adding items.")
            return
        if qty <= 0 or qty > item["quantity"]:
            if qty > item["quantity"]:
                QMessageBox.NoIcon(self, "Insufficient stock", f"Only {item['quantity']} available.")
            return

        sugar_level = None
        ice_level = None
        size = None

        if item.get("has_custom_options"):
            dlg = DrinkCustomizationDialog(item["name"], self)
            if dlg.exec() != QDialog.Accepted:
                return
            sugar_level = dlg.selected_sugar
            ice_level = dlg.selected_ice
            size = dlg.selected_size

        item_id = item["id"]
        if sugar_level is not None:
            cart_key = f"{item_id}_z{size}_s{sugar_level}_i{ice_level}"
            parts = []
            if size:
                parts.append(size)
            parts.append(f"{sugar_level}% sugar")
            parts.append(f"{ice_level}% ice")
            display_name = f"{item['name']} ({' · '.join(parts)})"
        else:
            cart_key = str(item_id)
            display_name = item["name"]

        existing_qty = self._get_cart_quantity_for_item(item_id)
        available_qty = int(item.get("quantity", 0))
        remaining_qty = max(0, available_qty - existing_qty)
        if qty > remaining_qty:
            QMessageBox.warning(self, "Insufficient stock", f"Only {remaining_qty} more available.")
            return

        if cart_key in self._cart:
            self._cart[cart_key]["qty"] += qty
        else:
            self._cart[cart_key] = {
                "id": item_id,
                "name": display_name,
                "price": float(item["price"]),
                "qty": qty,
                "note": "",
                "sugar_level": sugar_level,
                "ice_level": ice_level,
                "size": size,
            }
        self._last_added_cart_key = cart_key
        if card:
            card.setProperty("quantity", int(item.get("quantity", 0)))
        self._pending_fly_cart_key = cart_key
        self._refresh_order_panel()
        self._play_add_feedback(card, button, cart_key)
        self._save_current_order(show_message=False)

    def _refresh_order_panel(self):
        while self.order_items_layout.count():
            child = self.order_items_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        self._cart_row_widgets = {}
        pending_key = self._pending_fly_cart_key
        total = 0.0
        for cart_key, it in self._cart.items():
            item_total = it["qty"] * it["price"]
            total += item_total

            row_frame = QFrame()
            row_frame.setStyleSheet(f"""
                QFrame {{
                    background-color: {BG_MAIN};
                    border-radius: 10px;
                }}
            """)
            row_layout = QHBoxLayout(row_frame)
            row_layout.setContentsMargins(12, 10, 12, 10)
            row_layout.setSpacing(10)

            info_layout = QVBoxLayout()
            info_layout.setSpacing(2)
            name_lbl = QLabel(it["name"])
            name_lbl.setStyleSheet(f"color: {TEXT_PRIMARY}; font-weight: 600; font-size: 13px; background: transparent;")
            name_lbl.setWordWrap(True)
            info_layout.addWidget(name_lbl)

            detail_row = QHBoxLayout()
            detail_row.setSpacing(8)
            price_lbl = QLabel(f"${it['price']:.2f}")
            price_lbl.setStyleSheet(f"color: {GREEN}; font-size: 12px; font-weight: 500; background: transparent;")
            detail_row.addWidget(price_lbl)
            qty_lbl = QLabel(f"x{it['qty']}")
            qty_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; background: transparent;")
            detail_row.addWidget(qty_lbl)

            note_btn = QPushButton("Edit note" if it.get("note") else "Note")
            note_btn.setMinimumHeight(24)
            note_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            note_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {BG_WHITE};
                    color: {GREEN};
                    border: 1px solid {BORDER};
                    border-radius: 8px;
                    padding: 2px 8px;
                    font-size: 11px;
                    font-weight: 600;
                }}
                QPushButton:hover {{
                    background-color: {GREEN_LIGHT};
                    border-color: {GREEN};
                }}
            """)
            note_btn.clicked.connect(lambda _, ck=cart_key: self._edit_cart_note(ck))
            detail_row.addWidget(note_btn)
            detail_row.addStretch()
            info_layout.addLayout(detail_row)

            note = str(it.get("note") or "").strip()
            if note:
                note_lbl = QLabel(f"Note: {note}")
                note_lbl.setWordWrap(True)
                note_lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px; background: transparent;")
                info_layout.addWidget(note_lbl)
            row_layout.addLayout(info_layout, 1)

            item_total_lbl = QLabel(f"${item_total:.2f}")
            item_total_lbl.setStyleSheet(f"color: {TEXT_PRIMARY}; font-weight: 700; font-size: 13px; background: transparent;")
            item_total_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row_layout.addWidget(item_total_lbl)

            qty_controls = QVBoxLayout()
            qty_controls.setSpacing(2)

            plus_btn = QPushButton("+")
            plus_btn.setFixedSize(24, 24)
            plus_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {GREEN};
                    color: white;
                    border: none;
                    border-radius: 12px;
                    font-size: 14px;
                    font-weight: 700;
                }}
                QPushButton:hover {{ background-color: {GREEN_DARK}; }}
            """)
            plus_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            plus_btn.clicked.connect(lambda _, ck=cart_key: self._change_qty(ck, 1))
            qty_controls.addWidget(plus_btn)

            minus_btn = QPushButton("\u2212")
            minus_btn.setFixedSize(24, 24)
            minus_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {BG_WHITE};
                    color: {RED};
                    border: 1px solid {BORDER};
                    border-radius: 12px;
                    font-size: 14px;
                    font-weight: 700;
                }}
                QPushButton:hover {{ background-color: #FDEDEC; }}
            """)
            minus_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            minus_btn.clicked.connect(lambda _, ck=cart_key: self._change_qty(ck, -1))
            qty_controls.addWidget(minus_btn)

            row_layout.addLayout(qty_controls)

            self.order_items_layout.addWidget(row_frame)
            self._cart_row_widgets[cart_key] = row_frame
            if cart_key == pending_key:
                effect = QGraphicsOpacityEffect(row_frame)
                effect.setOpacity(0.0)
                row_frame.setGraphicsEffect(effect)

        self.order_items_layout.addStretch()
        self._last_added_cart_key = None

        vat_enabled, vat_rate = get_vat_settings()
        vat_amount = total * vat_rate / 100.0 if vat_enabled else 0.0
        grand_total = total + vat_amount
        self.subtotal_value.setText(f"${total:.2f}")
        self.tax_label.setText(f"VAT {vat_rate:.2f}%" if vat_enabled else "VAT Off")
        self.tax_value.setText(f"${vat_amount:.2f}")
        self.total_label.setText(f"${grand_total:.2f}")

    def _edit_cart_note(self, cart_key: str):
        if cart_key not in self._cart:
            return
        item = self._cart[cart_key]
        current_note = str(item.get("note") or "")
        note, ok = QInputDialog.getMultiLineText(
            self,
            "Item Note",
            f"Note for {item['name']}:",
            current_note,
        )
        if not ok:
            return
        item["note"] = note.strip()
        self._refresh_order_panel()
        self._save_current_order(show_message=False)

    def _change_qty(self, item_id, delta):
        if item_id in self._cart:
            if delta > 0:
                current_item_id = self._cart[item_id]["id"]
                available_qty = self._get_available_quantity(current_item_id)
                used_qty = self._get_cart_quantity_for_item(current_item_id)
                if used_qty >= available_qty:
                    QMessageBox.NoIcon(self, "Insufficient stock", f"Only {available_qty} available.")
                    return
            self._cart[item_id]["qty"] += delta
            if self._cart[item_id]["qty"] <= 0:
                del self._cart[item_id]
            self._refresh_order_panel()
            self._save_current_order(show_message=False)

    def _on_checkout(self):
        if not self._selected_table:
            QMessageBox.information(self, "Select Table", "Select a table before checkout.")
            return
        if not self._cart:
            return
        total = sum(it["qty"] * it["price"] for it in self._cart.values())

        dlg = PaymentDialog(total, self)
        if dlg.exec() != QDialog.Accepted or not dlg.accepted_payment:
            return

        self.checkout_btn.setEnabled(False)
        cart_snapshot = list(self._cart.values())
        table_id = self._selected_table["id"]

        done = threading.Event()
        err = {"e": None}
        txn_id_result = {"id": None}

        def worker():
            try:
                txn_id = self.table_service.checkout_table(
                    table_id,
                    cart_snapshot,
                    final_total=dlg.final_total_usd,
                    discount_amount=dlg.discount_amount_usd,
                    vat_amount=dlg.vat_amount_usd,
                )
                txn_id_result["id"] = txn_id
            except Exception as e:
                err["e"] = e
            finally:
                done.set()

        threading.Thread(target=worker, daemon=True).start()

        def poll():
            if not done.is_set():
                return
            timer.stop()
            if err["e"]:
                self.checkout_btn.setEnabled(True)
                self._populate_inventory_when_ready()
                QMessageBox.critical(self, "Error", str(err["e"]))
                return
            self._cart.clear()
            self._refresh_order_panel()
            self._refresh_tables()
            self._populate_inventory_when_ready()
            
            # Ask if user wants to print receipt
            txn_id = txn_id_result.get("id")
            if txn_id:
                reply = QMessageBox.question(
                    self, 
                    "Transaction Complete",
                    f"Transaction #{txn_id} completed successfully.\n\nPrint receipt?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes
                )
                if reply == QMessageBox.StandardButton.Yes:
                    self._generate_receipt(txn_id, cart_snapshot, dlg.final_total_usd)
            
            QMessageBox.information(self, "Success", "Transaction completed.")
            self.checkout_btn.setEnabled(True)

        timer = QTimer(self)
        timer.timeout.connect(poll)
        timer.start(100)

    def _generate_receipt(self, txn_id: int, cart_items: list, total_override: float | None = None):
        """Generate PDF receipt for transaction."""
        try:
            from database.database import get_exchange_rate
            
            # Build receipt items
            items = []
            for item in cart_items:
                items.append(ReceiptItem(
                    name=item.get("name", "Unknown"),
                    quantity=item.get("qty", 0),
                    unit_price=item.get("price", 0.0),
                    subtotal=item.get("qty", 0) * item.get("price", 0.0),
                    note=str(item.get("note") or ""),
                ))
            
            total = float(total_override) if total_override is not None else sum(it.subtotal for it in items)
            
            # Create receipt data
            receipt_data = ReceiptData(
                transaction_id=txn_id,
                date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                items=items,
                total=total,
                currency="USD",
                exchange_rate=get_exchange_rate()
            )
            
            # Generate and open PDF
            filepath = PDFGenerator.generate_receipt(receipt_data, auto_open=True)
            logger.info(f"Receipt generated: {filepath}")
            
        except Exception as e:
            logger.error(f"Failed to generate receipt: {e}")
            QMessageBox.NoIcon(self, "Receipt Error", f"Could not generate receipt: {e}")
        self._populate_inventory_when_ready()

    def refresh(self):
        self._refresh_tables()
        self._populate_inventory_when_ready()
