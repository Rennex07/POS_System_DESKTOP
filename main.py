import logging
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

def setup_logging():
    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s: %(message)s"
    )

setup_logging()
logger = logging.getLogger(__name__)

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QStackedWidget, QFrame, QDialog, QProgressBar, QMessageBox,
    QGridLayout, QSizePolicy, QGraphicsOpacityEffect
)
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QColor, QFont, QPen, QBrush, QLinearGradient

from database import database as db, handlers
from gui_and_func.inventory_menu import get_cache_stats, _get_low_stock_items
from gui_and_func.theme_manager import (
    apply_theme, GREEN, GREEN_DARK, GREEN_LIGHT,
    BG_MAIN, BG_WHITE, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED, BORDER
)
from gui_and_func.ordering_menu import OrderingWidget
from gui_and_func.transactions_menu import TransactionsWidget
from gui_and_func.stats_dashboard import StatsDashboardWidget
from gui_and_func.inventory_menu import InventoryWidget


class SimpleBarChart(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = []
        self.max_value = 10
        self.bar_color = QColor(GREEN)
        self.setMinimumHeight(200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_data(self, data: list):
        self.data = data if data else [("No Data", 0)]
        self.max_value = max([v for _, v in self.data] + [10]) * 1.1
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        width = self.width()
        height = self.height()
        margin_left = 50
        margin_bottom = 30
        margin_top = 20
        margin_right = 20

        chart_width = width - margin_left - margin_right
        chart_height = height - margin_bottom - margin_top

        pen = QPen(QColor(BORDER))
        pen.setWidth(1)
        painter.setPen(pen)

        grid_lines = 5
        for i in range(grid_lines + 1):
            y = margin_top + chart_height - (i * chart_height / grid_lines)
            painter.drawLine(margin_left, int(y), width - margin_right, int(y))

        painter.setPen(QColor(TEXT_MUTED))
        painter.setFont(QFont("Segoe UI", 9))
        for i in range(grid_lines + 1):
            value = i * self.max_value / grid_lines
            y = margin_top + chart_height - (i * chart_height / grid_lines)
            label = f"{value:.0f}"
            painter.drawText(0, int(y) - 8, margin_left - 8, 16,
                           Qt.AlignRight | Qt.AlignVCenter, label)

        if not self.data:
            return

        bar_count = len(self.data)
        bar_width = min(60, (chart_width / bar_count) * 0.7)
        spacing = (chart_width - (bar_width * bar_count)) / (bar_count + 1)

        gradient = QLinearGradient(0, 0, 0, chart_height)
        gradient.setColorAt(0, self.bar_color.lighter(110))
        gradient.setColorAt(1, self.bar_color)

        for i, (label, value) in enumerate(self.data):
            bar_height = (value / self.max_value) * chart_height if self.max_value > 0 else 0
            x = margin_left + spacing + i * (bar_width + spacing)
            y = margin_top + chart_height - bar_height

            painter.fillRect(int(x), int(y), int(bar_width), int(bar_height),
                           QBrush(gradient))

            pen = QPen(self.bar_color.darker(110))
            pen.setWidth(1)
            painter.setPen(pen)
            painter.drawRect(int(x), int(y), int(bar_width), int(bar_height))

            painter.setPen(QColor(TEXT_MUTED))
            painter.drawText(int(x) - 10, height - margin_bottom + 5,
                           int(bar_width) + 20, 20,
                           Qt.AlignCenter | Qt.AlignTop, label)


_executor = None

def get_executor():
    return _executor


NAV_BTN_STYLE = f"""
    QPushButton {{
        background-color: transparent;
        color: {TEXT_SECONDARY};
        border: none;
        border-radius: 10px;
        padding: 12px 18px;
        text-align: left;
        font-size: 14px;
        font-weight: 500;
    }}
    QPushButton:hover {{
        background-color: {GREEN_LIGHT};
        color: {GREEN};
    }}
    QPushButton:checked {{
        background-color: {GREEN};
        color: white;
        font-weight: 600;
    }}
"""

SIDEBAR_STYLE = f"""
    QFrame#sidebar {{
        background-color: {BG_WHITE};
        border-right: 1px solid {BORDER};
    }}
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("POS System")

        screen = QApplication.primaryScreen()
        screen_geometry = screen.availableGeometry()
        width = int(screen_geometry.width() * 0.92)
        height = int(screen_geometry.height() * 0.9)
        self.resize(width, height)

        x = (screen_geometry.width() - width) // 2
        y = (screen_geometry.height() - height) // 2
        self.move(x, y)

        self.setMinimumSize(1000, 700)

        optimal_workers = max(4, min(8, (os.cpu_count() or 4) * 2))
        global _executor
        _executor = ThreadPoolExecutor(
            max_workers=optimal_workers,
            thread_name_prefix="POS-Worker"
        )
        self.executor = _executor
        self.optimal_workers = optimal_workers
        self._opening_animation = None
        self._page_animation = None
        self._page_transition_overlay = None

        self._connect_with_dialog()

        self.central = QWidget()
        self.central.setStyleSheet(f"background-color: {BG_MAIN};")
        self.setCentralWidget(self.central)
        self.main_layout = QHBoxLayout(self.central)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self._create_sidebar()

        self.content_stack = QStackedWidget()
        self.content_stack.setStyleSheet(f"background-color: {BG_MAIN};")
        self.main_layout.addWidget(self.content_stack, 1)

        self._create_views()

        self.show_home()

        self._create_status_bar()

        self.cache_timer = QTimer(self)
        self.cache_timer.timeout.connect(self.update_cache_stats)
        self.cache_timer.start(5000)

        QTimer.singleShot(2000, self.check_low_stock)

    def play_opening_animation(self):
        self._fade_content_overlay(duration=160, start_opacity=0.85, store_as_opening=True)

    def _fade_content_overlay(self, duration=140, start_opacity=0.65, store_as_opening=False):
        if self._page_animation:
            self._page_animation.stop()
        if self._page_transition_overlay:
            self._page_transition_overlay.deleteLater()
            self._page_transition_overlay = None

        overlay = QFrame(self.content_stack)
        overlay.setStyleSheet(f"background-color: {BG_MAIN}; border: none;")
        overlay.setGeometry(self.content_stack.rect())
        overlay.raise_()
        overlay.show()

        effect = QGraphicsOpacityEffect(overlay)
        effect.setOpacity(start_opacity)
        overlay.setGraphicsEffect(effect)

        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(duration)
        animation.setStartValue(start_opacity)
        animation.setEndValue(0.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        def cleanup():
            overlay.deleteLater()
            self._page_animation = None
            self._page_transition_overlay = None
            if store_as_opening:
                self._opening_animation = None

        animation.finished.connect(cleanup)
        self._page_transition_overlay = overlay
        self._page_animation = animation
        if store_as_opening:
            self._opening_animation = animation
        animation.start()

    def _animate_current_page(self):
        self._fade_content_overlay(duration=130, start_opacity=0.55)

    def _switch_page(self, widget, active_index):
        current_index = self.content_stack.currentIndex()
        target_index = self.content_stack.indexOf(widget)
        if target_index < 0:
            return

        if current_index == target_index:
            self._update_nav_buttons(active_index)
            return

        self.content_stack.setCurrentWidget(widget)
        self._update_nav_buttons(active_index)
        self._animate_current_page()

    def _exec_dialog_with_animation(self, dialog):
        return dialog.exec()

    def _create_sidebar(self):
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setStyleSheet(SIDEBAR_STYLE)
        sidebar.setFixedWidth(210)

        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(12, 20, 12, 20)
        sidebar_layout.setSpacing(4)

        logo_row = QHBoxLayout()
        logo_row.setSpacing(8)
        logo_icon = QLabel("●")
        logo_icon.setStyleSheet(f"color: {GREEN}; font-size: 22px;")
        logo_icon.setFixedWidth(28)
        logo_text = QLabel("POS System")
        logo_text.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 17px; font-weight: 700;")
        logo_row.addWidget(logo_icon)
        logo_row.addWidget(logo_text)
        logo_row.addStretch()
        sidebar_layout.addLayout(logo_row)

        sidebar_layout.addSpacing(24)

        self.nav_buttons = []
        nav_items = [
            ("🏠  Menu", self.show_home),
            ("🛒  Ordering", self.show_ordering),
            ("📦  Inventory", self.show_inventory),
            ("📋  Transactions", self.show_transactions),
            ("📊  Analytics", self.show_analytics),
        ]

        for text, handler in nav_items:
            btn = QPushButton(text)
            btn.setStyleSheet(NAV_BTN_STYLE)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(handler)
            btn.setMinimumHeight(42)
            sidebar_layout.addWidget(btn)
            self.nav_buttons.append(btn)

        sidebar_layout.addStretch()

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {BORDER};")
        sidebar_layout.addWidget(sep)
        sidebar_layout.addSpacing(8)

        exit_btn = QPushButton("🚪  Exit")
        exit_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: #E74C3C;
                border: none;
                border-radius: 10px;
                padding: 12px 18px;
                text-align: left;
                font-size: 14px;
                font-weight: 500;
            }}
            QPushButton:hover {{ background-color: #FDEDEC; }}
        """)
        exit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        exit_btn.clicked.connect(self.close_application)
        exit_btn.setMinimumHeight(42)
        sidebar_layout.addWidget(exit_btn)

        self.main_layout.addWidget(sidebar)

    def _create_views(self):
        self.home_widget = self._create_home_view()
        self.content_stack.addWidget(self.home_widget)

        self.ordering_widget = OrderingWidget(self)
        self.content_stack.addWidget(self.ordering_widget)

        self.inventory_widget = InventoryWidget(self)
        self.content_stack.addWidget(self.inventory_widget)

        self.transactions_widget = TransactionsWidget(self)
        self.content_stack.addWidget(self.transactions_widget)

        self.analytics_widget = StatsDashboardWidget(self)
        self.content_stack.addWidget(self.analytics_widget)

    def _create_home_view(self):
        widget = QWidget()
        widget.setStyleSheet(f"background-color: {BG_MAIN};")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(30, 25, 30, 25)
        layout.setSpacing(20)

        header = QHBoxLayout()
        title = QLabel("Dashboard")
        title.setStyleSheet(f"font-size: 26px; font-weight: 700; color: {TEXT_PRIMARY}; background: transparent;")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(16)

        self.stat_cards = {}
        stat_configs = [
            ("total_sales", "Total Sales", "$0.00", GREEN),
            ("transactions", "Transactions", "0", "#3498db"),
            ("items_sold", "Items Sold", "0", "#F39C12"),
            ("low_stock", "Low Stock", "0", "#E74C3C"),
        ]

        for key, label, default, color in stat_configs:
            card = self._create_stat_card(label, default, color)
            self.stat_cards[key] = card
            stats_row.addWidget(card)

        layout.addLayout(stats_row)

        charts_row = QHBoxLayout()
        charts_row.setSpacing(20)

        self.recent_txn_widget = self._create_recent_transactions_widget()
        charts_row.addWidget(self.recent_txn_widget, 2)

        self.top_items_widget = self._create_top_items_widget()
        charts_row.addWidget(self.top_items_widget, 1)

        layout.addLayout(charts_row)

        actions_label = QLabel("Quick Actions")
        actions_label.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {TEXT_SECONDARY}; margin-top: 5px; background: transparent;")
        layout.addWidget(actions_label)

        actions_row = QHBoxLayout()
        actions_row.setSpacing(12)

        action_btns = [
            ("New Order", GREEN, self.show_ordering),
            ("Inventory", "#3498db", self.show_inventory),
            ("History", "#9b59b6", self.show_transactions),
            ("Analytics", "#F39C12", self.show_analytics),
        ]

        for text, color, handler in action_btns:
            btn = QPushButton(text)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {color};
                    color: white;
                    border: none;
                    border-radius: 10px;
                    padding: 14px 24px;
                    font-size: 13px;
                    font-weight: 600;
                }}
                QPushButton:hover {{ background-color: {color}dd; }}
            """)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(handler)
            actions_row.addWidget(btn)

        layout.addLayout(actions_row)
        layout.addStretch()

        QTimer.singleShot(500, self._refresh_dashboard_stats)

        return widget

    def _create_stat_card(self, title: str, value: str, color: str):
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {BG_WHITE};
                border: 1px solid {BORDER};
                border-left: 4px solid {color};
                border-radius: 12px;
                padding: 18px;
            }}
        """)

        layout = QVBoxLayout(card)
        layout.setSpacing(6)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f"font-size: 12px; color: {TEXT_MUTED}; font-weight: 500; background: transparent;")
        layout.addWidget(title_lbl)

        value_lbl = QLabel(value)
        value_lbl.setObjectName("value")
        value_lbl.setStyleSheet(f"font-size: 24px; font-weight: 700; color: {color}; background: transparent;")
        layout.addWidget(value_lbl)

        return card

    def _create_recent_transactions_widget(self):
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {BG_WHITE};
                border: 1px solid {BORDER};
                border-radius: 12px;
                padding: 15px;
            }}
        """)

        layout = QVBoxLayout(frame)
        layout.setSpacing(10)

        title = QLabel("Recent Transactions")
        title.setStyleSheet(f"font-size: 14px; font-weight: 600; color: {TEXT_PRIMARY}; background: transparent;")
        layout.addWidget(title)

        self.recent_txn_list = QVBoxLayout()
        self.recent_txn_list.setSpacing(8)
        layout.addLayout(self.recent_txn_list)

        layout.addStretch()
        return frame

    def _create_top_items_widget(self):
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {BG_WHITE};
                border: 1px solid {BORDER};
                border-radius: 12px;
                padding: 18px;
            }}
        """)

        layout = QVBoxLayout(frame)

        title = QLabel("Top Sellers")
        title.setStyleSheet(f"font-size: 14px; font-weight: 600; color: {TEXT_PRIMARY}; background: transparent;")
        layout.addWidget(title)

        self.top_items_list = QVBoxLayout()
        self.top_items_list.setSpacing(8)
        layout.addLayout(self.top_items_list)

        layout.addStretch()
        return frame

    def _refresh_dashboard_stats(self):
        try:
            from PySide6.QtWidgets import QApplication
            from database.database import get_connection

            with get_connection() as (conn, cur):
                cur.execute("SELECT COUNT(*), COALESCE(SUM(total_amount), 0) FROM transactions")
                txn_count, total_sales = cur.fetchone()

                cur.execute("SELECT COALESCE(SUM(quantity), 0) FROM transaction_items")
                items_sold = cur.fetchone()[0]

                cur.execute("SELECT COUNT(*) FROM inventory_items WHERE quantity < 10")
                low_stock = cur.fetchone()[0]

                cur.execute("""
                    SELECT
                        t.id,
                        t.total_amount,
                        t.created_at,
                        COALESCE(
                            GROUP_CONCAT(
                                COALESCE(i.name, printf('Item #%d', ti.item_id)) || ' (' || ti.quantity || 'x)',
                                ', '
                            ),
                            'No items'
                        ) AS items
                    FROM transactions t
                    LEFT JOIN transaction_items ti ON ti.transaction_id = t.id
                    LEFT JOIN inventory_items i ON i.id = ti.item_id
                    GROUP BY t.id, t.total_amount, t.created_at
                    ORDER BY t.id DESC LIMIT 5
                """)
                recent_sales_raw = cur.fetchall()

                cur.execute("""
                    SELECT COALESCE(i.name, printf('Item #%d', ti.item_id)) AS name, SUM(ti.quantity) as qty
                    FROM transaction_items ti
                    LEFT JOIN inventory_items i ON i.id = ti.item_id
                    GROUP BY ti.item_id, name
                    ORDER BY qty DESC
                    LIMIT 5
                """)
                top_items = cur.fetchall()

                self._update_stat_card("total_sales", f"${float(total_sales or 0):,.2f}")
                self._update_stat_card("transactions", f"{txn_count or 0:,}")
                self._update_stat_card("items_sold", f"{items_sold or 0:,}")
                self._update_stat_card("low_stock", f"{low_stock or 0}")

                while self.recent_txn_list.count():
                    item = self.recent_txn_list.takeAt(0)
                    if item.widget():
                        item.widget().deleteLater()

                if recent_sales_raw:
                    for row in recent_sales_raw[:5]:
                        txn_id = row['id']
                        amount = row['total_amount']
                        items = row['items']
                        created_at = row['created_at']
                        item_lbl = QLabel(f"{items} - ${float(amount or 0):.2f}")
                        item_lbl.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px; background: transparent; padding: 4px;")
                        item_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
                        item_lbl.setProperty("txn_id", txn_id)
                        class ClickableLabel(QLabel):
                            def __init__(self, parent_window, txn_id, *args, **kwargs):
                                super().__init__(*args, **kwargs)
                                self.parent_window = parent_window
                                self.txn_id = txn_id
                            def mousePressEvent(self, e):
                                self.parent_window._show_transaction_details(self.txn_id)
                        clickable_lbl = ClickableLabel(self, txn_id, f"{items} - ${float(amount or 0):.2f}")
                        clickable_lbl.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px; background: transparent; padding: 4px;")
                        clickable_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
                        self.recent_txn_list.addWidget(clickable_lbl)
                else:
                    no_data = QLabel("No recent transactions")
                    no_data.setStyleSheet(f"color: {TEXT_MUTED}; font-style: italic; background: transparent; padding: 4px;")
                    self.recent_txn_list.addWidget(no_data)

                while self.top_items_list.count():
                    item = self.top_items_list.takeAt(0)
                    if item.widget():
                        item.widget().deleteLater()

                if top_items:
                    for row in top_items[:3]:
                        name = row['name']
                        qty = row['qty']
                        display_name = name if name else "Unknown Item"
                        item_lbl = QLabel(f"• {display_name}: {qty} sold")
                        item_lbl.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px; background: transparent; padding: 4px;")
                        self.top_items_list.addWidget(item_lbl)
                else:
                    no_data = QLabel("No sales yet")
                    no_data.setStyleSheet(f"color: {TEXT_MUTED}; font-style: italic; background: transparent; padding: 4px;")
                    self.top_items_list.addWidget(no_data)

        except Exception as e:
            logger.error(f"Dashboard refresh error: {e}")

    def _show_transaction_details(self, txn_id):
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton
        from database.database import get_connection
        from datetime import datetime, timezone, timedelta

        def to_gmt7_str(dt_val):
            try:
                if dt_val is None:
                    return ""
                if isinstance(dt_val, str):
                    dt = datetime.fromisoformat(dt_val.replace(' ', 'T'))
                    tz7 = timezone(timedelta(hours=7))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return dt.astimezone(tz7).strftime("%Y-%m-%d %H:%M:%S")
                tz7 = timezone(timedelta(hours=7))
                if dt_val.tzinfo is None:
                    return (dt_val.replace(tzinfo=timezone.utc).astimezone(tz7)).strftime("%Y-%m-%d %H:%M:%S")
                return dt_val.astimezone(tz7).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                return str(dt_val or "")

        dialog = QDialog(self)
        dialog.setWindowTitle("Transaction Details")
        dialog.setMinimumWidth(400)

        layout = QVBoxLayout(dialog)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)

        try:
            with get_connection() as (conn, cur):
                cur.execute("""
                    SELECT t.id, t.total_amount, t.created_at,
                           GROUP_CONCAT(i.name || ' (' || ti.quantity || 'x)', ', ') as items
                    FROM transactions t
                    LEFT JOIN transaction_items ti ON ti.transaction_id = t.id
                    LEFT JOIN inventory_items i ON i.id = ti.item_id
                    WHERE t.id = ?
                    GROUP BY t.id
                """, (txn_id,))
                txn = cur.fetchone()

                if txn:
                    title = QLabel(f"Transaction #{txn['id']}")
                    title.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {TEXT_PRIMARY}; background: transparent;")
                    layout.addWidget(title)

                    items_label = QLabel(txn['items'] or "No items")
                    items_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 14px; background: transparent;")
                    layout.addWidget(items_label)

                    amount_label = QLabel(f"Total: ${float(txn['total_amount'] or 0):.2f}")
                    amount_label.setStyleSheet(f"color: {GREEN}; font-size: 18px; font-weight: bold; background: transparent;")
                    layout.addWidget(amount_label)

                    date_str = to_gmt7_str(txn['created_at'])
                    date_label = QLabel(f"Date: {date_str or 'Unknown'}")
                    date_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; background: transparent;")
                    layout.addWidget(date_label)
        except Exception as e:
            error_label = QLabel(f"Error loading details: {e}")
            error_label.setStyleSheet("color: #E74C3C; background: transparent;")
            layout.addWidget(error_label)

        layout.addStretch()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)

        self._exec_dialog_with_animation(dialog)

    def _update_stat_card(self, key: str, value: str):
        if key in self.stat_cards:
            card = self.stat_cards[key]
            value_lbl = card.findChild(QLabel, "value")
            if value_lbl:
                value_lbl.setText(value)

    def _create_status_bar(self):
        status_bar = self.statusBar()
        self.status_label = QLabel("Connected")
        status_bar.addWidget(self.status_label)
        status_bar.addPermanentWidget(QLabel("  "))
        self.cache_label = QLabel("Cache: 0 MB")
        status_bar.addPermanentWidget(self.cache_label)

    def _update_nav_buttons(self, active_index: int):
        for i, btn in enumerate(self.nav_buttons):
            btn.setChecked(i == active_index)

    def show_home(self):
        self._switch_page(self.home_widget, 0)
        self._refresh_dashboard_stats()

    def show_ordering(self):
        self._switch_page(self.ordering_widget, 1)
        if hasattr(self.ordering_widget, 'refresh'):
            self.ordering_widget.refresh()

    def show_inventory(self):
        self._switch_page(self.inventory_widget, 2)
        if hasattr(self.inventory_widget, 'refresh'):
            self.inventory_widget.refresh()

    def show_transactions(self):
        self._switch_page(self.transactions_widget, 3)
        if hasattr(self.transactions_widget, 'refresh'):
            self.transactions_widget.refresh()

    def show_analytics(self):
        self._switch_page(self.analytics_widget, 4)
        if hasattr(self.analytics_widget, 'refresh'):
            self.analytics_widget.refresh()

    def update_cache_stats(self):
        try:
            stats = get_cache_stats()
            size_mb = stats["total_size_mb"]
            count = stats["thumbs_count"] + stats["previews_count"]
            self.cache_label.setText(f"Cache: {size_mb:.1f} MB ({count} items)")
            if size_mb > 40:
                self.cache_label.setStyleSheet("color: #E74C3C; font-weight: bold;")
            else:
                self.cache_label.setStyleSheet("")
        except Exception:
            pass

    def check_low_stock(self):
        try:
            LOW_STOCK_THRESHOLD = 10
            low_stock_items = _get_low_stock_items(LOW_STOCK_THRESHOLD)
            if low_stock_items:
                items_list = "\n".join([f"{item['name']}: {item.get('quantity', 0)} left" for item in low_stock_items[:5]])
                more_text = f"\n... and {len(low_stock_items) - 5} more" if len(low_stock_items) > 5 else ""
                msg_box = QMessageBox(self)
                msg_box.setIcon(QMessageBox.Warning)
                msg_box.setWindowTitle("Low Stock Alert")
                msg_box.setText(f"{len(low_stock_items)} items are running low!")
                msg_box.setInformativeText(f"{items_list}{more_text}\n\nConsider restocking soon.")
                msg_box.setStandardButtons(QMessageBox.Ok)
                msg_box.exec()
        except Exception:
            pass

    def close_application(self):
        if self.executor:
            self.executor.shutdown(wait=False)
        handlers.cleanup()
        self.close()

    def _connect_with_dialog(self):
        class ConnectingDialog(QDialog):
            def __init__(self, parent=None):
                super().__init__(parent)
                self.setWindowTitle("Starting POS System...")
                self.setStyleSheet(f"background-color: {BG_WHITE};")
                layout = QVBoxLayout(self)
                self.lbl = QLabel("Connecting to database...")
                self.lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.lbl.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 14px; background: transparent;")
                bar = QProgressBar()
                bar.setRange(0, 0)
                layout.addWidget(self.lbl)
                layout.addWidget(bar)
                self.setModal(True)
                self.resize(360, 120)

        done = threading.Event()
        err = {"value": None}

        def worker():
            try:
                db.connect()
                from database import database_setup
                database_setup.setup_products_table()
                database_setup.ensure_inventory_table()
                database_setup.ensure_transactions_tables()
                err["value"] = None
            except Exception as e:
                err["value"] = e
            finally:
                done.set()

        threading.Thread(target=worker, daemon=True).start()
        dlg = ConnectingDialog(self)

        def poll():
            if done.is_set():
                dlg.accept()

        timer = QTimer(dlg)
        timer.timeout.connect(poll)
        timer.start(100)
        dlg.exec()
        timer.stop()

        if err["value"] is not None or getattr(db, "conn", None) is None:
            error_msg = str(err["value"]) if err["value"] else "Unknown connection error"
            user_msg = f"Could not connect to database.\n\nError: {error_msg}\n\nThe application will now close."
            QMessageBox.critical(self, "Database Connection Failed", user_msg, QMessageBox.StandardButton.Ok)
            sys.exit(1)
        else:
            handlers.setup()


if __name__ == "__main__":
    app = QApplication([])
    app.setStyle('Fusion')
    apply_theme("light")
    window = MainWindow()
    window.show()
    QTimer.singleShot(0, window.play_opening_animation)
    sys.exit(app.exec())
