import logging
import math
import threading
from typing import Dict, List
from datetime import datetime
from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, QPushButton,
    QLabel, QSpinBox, QMessageBox, QLineEdit, QScrollArea, QWidget, QGridLayout, QFrame, QButtonGroup,
    QAbstractItemView, QAbstractSpinBox, QSizePolicy, QHeaderView
)
from PySide6.QtGui import QPixmap, QImage, QShortcut, QKeySequence
from PySide6.QtCore import Qt, QTimer, QSize, QBuffer
from services.transaction_service import TransactionService, CartItem
from .pdf_generator import PDFGenerator, ReceiptData, ReceiptItem

logger = logging.getLogger(__name__)

try:
    from database import database as db
    from database.database_setup import ensure_transactions_tables
except ModuleNotFoundError:
    import os, sys
    root = os.path.dirname(os.path.dirname(__file__))
    if root not in sys.path:
        sys.path.insert(0, root)
    import database as db
    from database_setup import ensure_transactions_tables

from .inventory_menu import (
    _make_thumbnail_pixmap,
    _fetch_all_items,
    _prepare_row_for_display,
    _get_item_by_id,
)
from .theme_manager import (
    GREEN, GREEN_DARK, GREEN_LIGHT, GREEN_PALE,
    BG_MAIN, BG_WHITE, BG_CARD, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED,
    BORDER, BORDER_LIGHT, RED, ORANGE
)


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
        border: 1.5px solid {BORDER};
        border-radius: 12px;
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
        self.setMinimumSize(450, 480)
        self.resize(480, 520)
        self.setStyleSheet(f"background-color: {BG_WHITE};")
        self.total_usd = total_usd
        self.accepted_payment = False
        self.payment_method = "cash"

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

        total_title = QLabel("Total Amount")
        total_title.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px; background: transparent;")
        total_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        total_layout.addWidget(total_title)

        total_usd_label = QLabel(f"${self.total_usd:.2f}")
        total_usd_label.setStyleSheet(f"color: {GREEN}; font-size: 34px; font-weight: 700; background: transparent;")
        total_usd_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        total_layout.addWidget(total_usd_label)

        layout.addWidget(total_frame)
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
        QTimer.singleShot(100, lambda: self.amount_input.setFocus())

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

        layout.addLayout(change_layout)
        layout.addStretch()

        return widget

    def _calculate_change(self):
        try:
            amount_text = self.amount_input.text().replace(",", "").strip()
            if not amount_text:
                self.change_usd_label.setText("$0.00")
                self.confirm_btn.setEnabled(False)
                return

            amount = float(amount_text)
            change_usd = round(amount - self.total_usd, 6)

            if change_usd >= 0:
                self.change_usd_label.setText(f"${change_usd:.2f}")
                self.change_usd_label.setStyleSheet(f"color: {GREEN}; font-size: 32px; font-weight: 700; background: transparent;")
                self.confirm_btn.setEnabled(True)
            else:
                self.change_usd_label.setText(f"-${abs(change_usd):.2f}")
                self.change_usd_label.setStyleSheet(f"color: {RED}; font-size: 32px; font-weight: 700; background: transparent;")
                self.confirm_btn.setEnabled(False)

        except ValueError:
            self.change_usd_label.setText("Invalid")
            self.change_usd_label.setStyleSheet(f"color: {RED}; font-size: 32px; font-weight: 700; background: transparent;")
            self.confirm_btn.setEnabled(False)

    def _confirm_payment(self):
        self.accepted_payment = True
        self.accept()


def _ensure_db():
    if getattr(db, "conn", None) is None or getattr(db, "cursor", None) is None:
        db.connect()

class OrderingWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._grid_columns = 3
        self._cart: Dict[str, Dict] = {}
        self._all_rows: List[Dict] = []
        self._view_rows: List[Dict] = []
        self._current_category = "All"
        self._is_loading = False
        self._initialized = False
        self._setup_ui()

    def _setup_ui(self):
        self.setStyleSheet(f"background-color: {BG_MAIN};")
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        left_panel = QWidget()
        left_panel.setStyleSheet(f"background-color: {BG_MAIN};")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(20, 18, 10, 18)
        left_layout.setSpacing(14)

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
        right_panel.setFixedWidth(340)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(18, 18, 18, 18)
        right_layout.setSpacing(12)

        order_title = QLabel("Order Summary")
        order_title.setStyleSheet(f"font-size: 17px; font-weight: 700; color: {TEXT_PRIMARY}; background: transparent;")
        right_layout.addWidget(order_title)

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
        tax_lbl = QLabel("Tax 0%")
        tax_lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 13px; background: transparent;")
        self.tax_value = QLabel("$0.00")
        self.tax_value.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px; font-weight: 600; background: transparent;")
        self.tax_value.setAlignment(Qt.AlignRight)
        tax_row.addWidget(tax_lbl)
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

        self.checkout_btn = QPushButton("Place Order")
        self.checkout_btn.setMinimumHeight(50)
        self.checkout_btn.setStyleSheet(CHECKOUT_BTN_STYLE)
        self.checkout_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.checkout_btn.clicked.connect(self._on_checkout)
        right_layout.addWidget(self.checkout_btn)

        main_layout.addWidget(left_panel, 1)
        main_layout.addWidget(right_panel)

        self._grid_timer = QTimer(self)
        self._grid_timer.setInterval(10)
        self._grid_timer.timeout.connect(self._build_grid_chunk)
        self._grid_cursor = 0

        QTimer.singleShot(100, self._initial_load)

    def _initial_load(self):
        if not self._initialized:
            self._initialized = True
            self._populate_inventory_when_ready()

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
        for i in range(9):
            card = QFrame()
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
        self._clear_inventory_grid()
        self.item_widgets.clear()
        self._grid_cursor = 0
        if not self._grid_timer.isActive():
            self._grid_timer.start()

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
            self.item_widgets[item['id']] = card
            self._grid_cursor += 1
        if self._grid_cursor >= len(self._view_rows):
            self._grid_timer.stop()

    def _create_item_card(self, item):
        card = QFrame()
        card.setObjectName("itemCard")
        card.setStyleSheet(CARD_STYLE)
        card.setFixedWidth(200)
        card.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Minimum)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(6)

        if item.get('image'):
            thumb = _make_thumbnail_pixmap(item['image'], (90, 90))
            if thumb:
                img = QLabel()
                img.setPixmap(thumb)
                img.setAlignment(Qt.AlignCenter)
                img.setStyleSheet("background: transparent;")
                layout.addWidget(img, alignment=Qt.AlignHCenter)

        name = QLabel(item['name'])
        name.setStyleSheet(f"color: {TEXT_PRIMARY}; font-weight: 600; font-size: 13px; background: transparent;")
        name.setWordWrap(True)
        layout.addWidget(name)

        price = QLabel(f"${float(item['price']):.2f}")
        price.setStyleSheet(f"color: {GREEN}; font-weight: 700; font-size: 14px; background: transparent;")
        layout.addWidget(price)

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
            layout.addWidget(cat_label, alignment=Qt.AlignLeft)

        stock = QLabel(f"Stock: {item['quantity']}")
        stock_color = TEXT_MUTED if item['quantity'] >= 10 else RED
        stock.setStyleSheet(f"color: {stock_color}; font-size: 11px; background: transparent;")
        layout.addWidget(stock)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        spin = QSpinBox()
        spin.setRange(1, max(1, min(99, item['quantity'])))
        spin.setValue(1)
        spin.setFixedWidth(55)
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
        add_btn = QPushButton("Add to Cart")
        add_btn.setStyleSheet(ADD_BTN_STYLE)
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setFixedHeight(30)
        add_btn.clicked.connect(lambda _, i=item, s=spin: self._on_add_item(i, s.value()))
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

    def _on_add_item(self, item, qty):
        if qty <= 0 or qty > item["quantity"]:
            if qty > item["quantity"]:
                QMessageBox.warning(self, "Insufficient stock", f"Only {item['quantity']} available.")
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
                "sugar_level": sugar_level,
                "ice_level": ice_level,
                "size": size,
            }
        self._refresh_order_panel()

    def _refresh_order_panel(self):
        while self.order_items_layout.count():
            child = self.order_items_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

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
            detail_row.addStretch()
            info_layout.addLayout(detail_row)
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

        self.order_items_layout.addStretch()

        self.subtotal_value.setText(f"${total:.2f}")
        self.tax_value.setText("$0.00")
        self.total_label.setText(f"${total:.2f}")

    def _change_qty(self, item_id, delta):
        if item_id in self._cart:
            if delta > 0:
                current_item_id = self._cart[item_id]["id"]
                available_qty = self._get_available_quantity(current_item_id)
                used_qty = self._get_cart_quantity_for_item(current_item_id)
                if used_qty >= available_qty:
                    QMessageBox.warning(self, "Insufficient stock", f"Only {available_qty} available.")
                    return
            self._cart[item_id]["qty"] += delta
            if self._cart[item_id]["qty"] <= 0:
                del self._cart[item_id]
            self._refresh_order_panel()

    def _on_checkout(self):
        if not self._cart:
            return
        total = sum(it["qty"] * it["price"] for it in self._cart.values())

        dlg = PaymentDialog(total, self)
        if dlg.exec() != QDialog.Accepted or not dlg.accepted_payment:
            return

        self.checkout_btn.setEnabled(False)
        cart_snapshot = list(self._cart.values())

        done = threading.Event()
        err = {"e": None}
        txn_id_result = {"id": None}

        def worker():
            try:
                txn_id = TransactionService().checkout(cart_snapshot)
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
            self._populate_inventory_when_ready()
            
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
                    self._generate_receipt(txn_id, cart_snapshot)
            
            QMessageBox.information(self, "Success", "Transaction completed.")
            self.checkout_btn.setEnabled(True)

        timer = QTimer(self)
        timer.timeout.connect(poll)
        timer.start(100)

    def _generate_receipt(self, txn_id: int, cart_items: list):
        """Generate PDF receipt for transaction."""
        try:
            items = []
            for item in cart_items:
                items.append(ReceiptItem(
                    name=item.get("name", "Unknown"),
                    quantity=item.get("qty", 0),
                    unit_price=item.get("price", 0.0),
                    subtotal=item.get("qty", 0) * item.get("price", 0.0)
                ))
            
            total = sum(it.subtotal for it in items)
            
            receipt_data = ReceiptData(
                transaction_id=txn_id,
                date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                items=items,
                total=total,
                currency="USD"
            )
            
            filepath = PDFGenerator.generate_receipt(receipt_data, auto_open=True)
            logger.info(f"Receipt generated: {filepath}")
            
        except Exception as e:
            logger.error(f"Failed to generate receipt: {e}")
            QMessageBox.warning(self, "Receipt Error", f"Could not generate receipt: {e}")
        self._populate_inventory_when_ready()
