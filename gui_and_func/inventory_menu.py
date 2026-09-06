import os
import logging
from typing import Optional
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QDoubleSpinBox,
    QComboBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QHeaderView,
    QAbstractItemView,
    QInputDialog,
    QProgressDialog,
    QStyledItemDelegate,
    QWidget,
)
from PySide6.QtGui import QIcon, QPixmap, QCursor, QShortcut, QKeySequence, QColor, QBrush, QPen, QPainter, QFont
from PySide6.QtCore import Qt, QEvent, QTimer
import threading

try:
    from .export_utils import export_inventory_to_csv, export_inventory_to_json
except ImportError:
    export_inventory_to_csv = None
    export_inventory_to_json = None

try:
    from database import database as db
    from database.database_setup import ensure_inventory_table
except ModuleNotFoundError:
    import sys as _sys
    _root = os.path.dirname(os.path.dirname(__file__))
    if _root not in _sys.path:
        _sys.path.insert(0, _root)
    try:
        import database as db
        from database_setup import ensure_inventory_table
    except ModuleNotFoundError:
        db = None
        def ensure_inventory_table():
            pass

try:
    from .theme_manager import TEXT_PRIMARY
except ImportError:
    from gui_and_func.theme_manager import TEXT_PRIMARY

LOW_STOCK_THRESHOLD = 10
STOCK_OUT_BORDER = "#D50000"
STOCK_OUT_BG = "#FFE1E1"
STOCK_LOW_BORDER = "#FF9800"
STOCK_LOW_BG = "#FFF6CC"
STOCK_ALERT_ROLE = Qt.ItemDataRole.UserRole + 20

_view_dialog = None
_MAX_IMAGE_BYTES = 5 * 1024 * 1024

_PIXMAP_CACHE = {
    "thumbs": {},
    "previews": {},
    "size_bytes": 0,
    "access_order": []
}
_MAX_CACHE_BYTES = 50 * 1024 * 1024
_MAX_CACHED_PIXMAPS = 500


def _stock_priority(quantity: int) -> int:
    qty = int(quantity or 0)
    if qty <= 0:
        return 0
    if qty < LOW_STOCK_THRESHOLD:
        return 1
    return 2


def _sort_stock_alerts_first(rows: list) -> list:
    def _key(row):
        qty = int(row.get("quantity") or 0)
        priority = _stock_priority(qty)
        return (priority, qty if priority < 2 else 0, -int(row.get("id") or 0))

    return sorted(rows, key=_key)


def _stock_alert_state(quantity: int) -> str:
    qty = int(quantity or 0)
    if qty <= 0:
        return "out"
    if qty < LOW_STOCK_THRESHOLD:
        return "low"
    return "ok"


def _stock_alert_text(quantity: int) -> str:
    qty = int(quantity or 0)
    if qty <= 0:
        return "Out of stock"
    if qty < LOW_STOCK_THRESHOLD:
        return f"Low stock: {qty}"
    return f"Stock: {qty}"


class StockAlertRowDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        state = index.data(STOCK_ALERT_ROLE)
        if state not in ("out", "low"):
            return

        color = STOCK_OUT_BORDER if state == "out" else STOCK_LOW_BORDER
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(QPen(QColor(color), 2))
        rect = option.rect.adjusted(1, 1, -1, -1)
        painter.drawLine(rect.topLeft(), rect.topRight())
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        if index.column() == 0:
            painter.drawLine(rect.topLeft(), rect.bottomLeft())
        if index.column() == index.model().columnCount() - 1:
            painter.drawLine(rect.topRight(), rect.bottomRight())
        painter.restore()


class StockBadgeButton(QPushButton):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self._badge = QLabel()
        self._badge.setParent(self)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._badge.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._badge.hide()
        self._badge_host = None

    def update_badge(self, count: int):
        count = int(count or 0)
        if count <= 0:
            self._badge.hide()
            self.setToolTip("No low stock items")
            return

        text = "99+" if count > 99 else str(count)
        width = 18 if len(text) <= 2 else 24
        height = 18
        self._sync_badge_host()
        self._badge.setText(text)
        self._badge.setFixedSize(width, height)
        self._badge.setStyleSheet(f"""
            QLabel {{
                background-color: {STOCK_OUT_BORDER};
                color: white;
                border: 1.5px solid white;
                border-radius: {height // 2}px;
                font-size: 9px;
                font-weight: 800;
            }}
        """)
        self._badge.show()
        self.setToolTip(f"{count} item{'s' if count != 1 else ''} need stock attention")
        self._position_badge()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_badge_host()
        self._position_badge()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_badge()

    def moveEvent(self, event):
        super().moveEvent(event)
        self._position_badge()

    def eventFilter(self, obj, event):
        if obj is self._badge_host and event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.Move,
            QEvent.Type.Show,
            QEvent.Type.LayoutRequest,
        ):
            self._position_badge()
        return super().eventFilter(obj, event)

    def _sync_badge_host(self):
        host = self.parentWidget() or self
        if host is self._badge_host:
            return
        if self._badge_host is not None:
            try:
                self._badge_host.removeEventFilter(self)
            except Exception:
                pass
        self._badge_host = host
        self._badge.setParent(host)
        try:
            host.installEventFilter(self)
        except Exception:
            pass

    def _position_badge(self):
        if self._badge.isHidden():
            return
        host = self._badge_host or self.parentWidget() or self
        top_left = self.mapTo(host, self.rect().topLeft())
        x = top_left.x() + self.width() - self._badge.width() + 5
        y = top_left.y() - 7
        self._badge.move(int(x), int(y))
        self._badge.raise_()


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(__file__))

def _ensure_db():
    if db is None:
        raise RuntimeError("Database module not available")
    if getattr(db, "conn", None) is None or getattr(db, "cursor", None) is None:
        db.connect()


def _tz_now_str() -> str:
    tz = timezone(timedelta(hours=7))
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")


def _to_gmt7_str(dt_val) -> str:
    try:
        if dt_val is None:
            return ""
        if isinstance(dt_val, str):
            return dt_val
        tz7 = timezone(timedelta(hours=7))
        if dt_val.tzinfo is None:
            return (dt_val.replace(tzinfo=timezone.utc).astimezone(tz7)).strftime("%Y-%m-%d %H:%M:%S")
        return dt_val.astimezone(tz7).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(dt_val or "")


def _prepare_row_for_display(row) -> dict:
    if not isinstance(row, dict):
        row = dict(row)
    row["_thumb_icon"] = None
    row["_preview_pix"] = None
    row["updated_at_str"] = _to_gmt7_str(row.get("updated_at"))
    row["created_at_str"] = _to_gmt7_str(row.get("created_at"))
    return row


def _estimate_pixmap_size(pixmap):
    if pixmap is None:
        return 0
    return pixmap.width() * pixmap.height() * 4


def _evict_from_cache(cache_type, required_bytes):
    freed = 0
    cache = _PIXMAP_CACHE[cache_type]
    
    while freed < required_bytes and cache:
        for key in list(_PIXMAP_CACHE["access_order"]):
            if key in cache:
                pixmap = cache.pop(key)
                size = _estimate_pixmap_size(pixmap)
                freed += size
                _PIXMAP_CACHE["size_bytes"] -= size
                _PIXMAP_CACHE["access_order"].remove(key)
                break
        else:
            break
    
    return freed


def _make_thumbnail_pixmap(image_bytes: bytes, size=(48, 48)):
    if not image_bytes:
        return None
    
    cache_key = hash(image_bytes)
    
    if cache_key in _PIXMAP_CACHE["thumbs"]:
        if cache_key in _PIXMAP_CACHE["access_order"]:
            _PIXMAP_CACHE["access_order"].remove(cache_key)
        _PIXMAP_CACHE["access_order"].append(cache_key)
        return _PIXMAP_CACHE["thumbs"][cache_key]

    from PySide6.QtGui import QImage
    image = QImage.fromData(image_bytes)
    if image.isNull():
        return None
    pixmap = QPixmap.fromImage(image).scaled(size[0], size[1], Qt.KeepAspectRatio, Qt.SmoothTransformation)

    pixmap_size = _estimate_pixmap_size(pixmap)

    if _PIXMAP_CACHE["size_bytes"] + pixmap_size > _MAX_CACHE_BYTES:
        _evict_from_cache("thumbs", pixmap_size)

    if len(_PIXMAP_CACHE["thumbs"]) >= _MAX_CACHED_PIXMAPS:
        _evict_from_cache("thumbs", pixmap_size)
    
    _PIXMAP_CACHE["thumbs"][cache_key] = pixmap
    _PIXMAP_CACHE["size_bytes"] += pixmap_size
    _PIXMAP_CACHE["access_order"].append(cache_key)
    
    return pixmap


def _make_preview_pixmap(image_bytes: bytes, size=(320, 320)):
    if not image_bytes:
        return None
    
    cache_key = hash(image_bytes)

    if cache_key in _PIXMAP_CACHE["previews"]:
        if cache_key in _PIXMAP_CACHE["access_order"]:
            _PIXMAP_CACHE["access_order"].remove(cache_key)
        _PIXMAP_CACHE["access_order"].append(cache_key)
        return _PIXMAP_CACHE["previews"][cache_key]
    
    from PySide6.QtGui import QImage
    image = QImage.fromData(image_bytes)
    if image.isNull():
        return None
    pixmap = QPixmap.fromImage(image).scaled(size[0], size[1], Qt.KeepAspectRatio, Qt.SmoothTransformation)

    pixmap_size = _estimate_pixmap_size(pixmap)
    
    if _PIXMAP_CACHE["size_bytes"] + pixmap_size > _MAX_CACHE_BYTES:
        _evict_from_cache("previews", pixmap_size)
    
    if len(_PIXMAP_CACHE["previews"]) >= _MAX_CACHED_PIXMAPS:
        _evict_from_cache("previews", pixmap_size)
    
    _PIXMAP_CACHE["previews"][cache_key] = pixmap
    _PIXMAP_CACHE["size_bytes"] += pixmap_size
    _PIXMAP_CACHE["access_order"].append(cache_key)
    
    return pixmap


def get_cache_stats():
    size_mb = _PIXMAP_CACHE["size_bytes"] / (1024 * 1024)
    return {
        "thumbs_count": len(_PIXMAP_CACHE["thumbs"]),
        "previews_count": len(_PIXMAP_CACHE["previews"]),
        "total_size_mb": size_mb,
        "max_size_mb": _MAX_CACHE_BYTES / (1024 * 1024)
    }


def _get_all_categories() -> list:
    _ensure_db()
    conn = None
    cur = None
    try:
        conn = db.get_pooled_connection()
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT category FROM inventory_items WHERE category IS NOT NULL AND category != '' ORDER BY category")
        return [row[0] for row in cur.fetchall()]
    finally:
        try:
            if cur:
                cur.close()
            if conn:
                conn.close()
        except Exception as e:
            logger.debug(f"Cleanup failed in _get_all_categories: {e}")


def _get_low_stock_items(threshold: int = 10) -> list:
    _ensure_db()
    conn = None
    cur = None
    try:
        conn = db.get_pooled_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, price, quantity, category FROM inventory_items WHERE quantity < ? ORDER BY quantity ASC",
            (threshold,)
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        try:
            if cur:
                cur.close()
            if conn:
                conn.close()
        except Exception as e:
            logger.debug(f"Cleanup failed in _get_low_stock_items: {e}")


def _fetch_all_items():
    _ensure_db()
    conn = None
    cur = None
    try:
        conn = db.get_pooled_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, price, quantity, image, category, created_at, updated_at, COALESCE(has_custom_options, 0) as has_custom_options FROM inventory_items ORDER BY id DESC"
        )
        rows = cur.fetchall()
        return [dict(row) for row in rows]
    finally:
        try:
            if cur is not None:
                cur.close()
        except Exception:
            pass
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass


def _get_item_by_id(item_id: int):
    _ensure_db()
    conn = None
    cur = None
    try:
        conn = db.get_pooled_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, price, quantity, image, category, created_at, updated_at, COALESCE(has_custom_options, 0) as has_custom_options FROM inventory_items WHERE id = ?",
            (item_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        try:
            if cur is not None:
                cur.close()
        except Exception:
            pass
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass


def _insert_item(name: str, price: float, quantity: int, image_src: Optional[str], category: str = "Mains", has_custom_options: bool = False) -> int:
    _ensure_db()
    image_bytes = None
    if image_src:
        with open(image_src, 'rb') as f:
            image_bytes = f.read()
    conn = None
    cur = None
    try:
        conn = db.get_pooled_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO inventory_items (name, price, quantity, image, category, has_custom_options) VALUES (?, ?, ?, ?, ?, ?)",
            (name, price, quantity, image_bytes, category, 1 if has_custom_options else 0),
        )
        conn.commit()
        new_id = cur.lastrowid
        return new_id
    finally:
        try:
            if cur:
                cur.close()
            if conn:
                conn.close()
        except Exception as e:
            logger.debug(f"Cleanup failed in _insert_item: {e}")


def _update_item(item_id: int, name: str, price: float, quantity: int, image_src: Optional[str], current_image_bytes: Optional[bytes], category: str, has_custom_options: bool = False):
    _ensure_db()
    image_bytes = current_image_bytes
    if image_src:
        with open(image_src, 'rb') as f:
            image_bytes = f.read()
    conn = None
    cur = None
    try:
        conn = db.get_pooled_connection()
        cur = conn.cursor()
        cur.execute(
            "UPDATE inventory_items SET name=?, price=?, quantity=?, image=?, category=?, has_custom_options=? WHERE id=?",
            (name, price, quantity, image_bytes, category, 1 if has_custom_options else 0, item_id),
        )
        conn.commit()
    finally:
        try:
            if cur:
                cur.close()
            if conn:
                conn.close()
        except Exception as e:
            logger.debug(f"Cleanup failed in _update_item: {e}")


def _delete_item(item_id: int):
    _ensure_db()
    conn = None
    cur = None
    try:
        conn = db.get_pooled_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM inventory_items WHERE id=?", (item_id,))
        conn.commit()
    finally:
        try:
            if cur:
                cur.close()
            if conn:
                conn.close()
        except Exception as e:
            logger.debug(f"Cleanup failed in _delete_item: {e}")

class AddItemDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Inventory Item")
        self.setModal(True)
        self.resize(800, 480)

        self.name_edit = QLineEdit()
        self.price_spin = QDoubleSpinBox()
        self.price_spin.setRange(0.0, 10_000_000.0)
        self.price_spin.setDecimals(2)
        self.price_spin.setSingleStep(0.10)
        self.qty_spin = QSpinBox()
        self.qty_spin.setRange(0, 1_000_000)
        
        self.category_combo = QComboBox()
        self.category_combo.addItems(["Casual", "Mains", "Appetizers", "Drinks", "Desserts"])
        self.category_combo.setCurrentText("Casual")
        try:
            existing = _get_all_categories()
            for c in existing:
                if c and self.category_combo.findText(c) == -1:
                    self.category_combo.addItem(c)
        except Exception:
            pass

        self.custom_check = QCheckBox("Has drink customization (sugar / ice / size)")
        self.custom_check.setChecked(False)

        self.image_path = None
        self.image_label = QLabel("No image selected")
        self.image_btn = QPushButton("Choose Image")
        self.image_btn.clicked.connect(self.choose_image)

        form = QFormLayout()
        form.addRow("Name", self.name_edit)
        form.addRow("Price", self.price_spin)
        form.addRow("Quantity", self.qty_spin)
        form.addRow("Category", self.category_combo)
        form.addRow("Customization", self.custom_check)
        form.addRow("Image", self.image_btn)
        form.addRow("", self.image_label)

        buttons = QHBoxLayout()
        self.add_btn = QPushButton("Add")
        self.cancel_btn = QPushButton("Cancel")
        self.add_btn.clicked.connect(self.on_add)
        self.cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(self.add_btn)
        buttons.addWidget(self.cancel_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(buttons)

    def choose_image(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Image", "", "Images (*.png *.jpg *.jpeg)")
        if file_path:
            self.image_path = file_path
            self.image_label.setText(os.path.basename(file_path))

    def on_add(self):
        name = self.name_edit.text().strip()
        price = float(self.price_spin.value())
        qty = int(self.qty_spin.value())

        if not name:
            QMessageBox.NoIcon(self, "Validation", "Name is required.")
            return
        if price < 0 or qty < 0:
            QMessageBox.NoIcon(self, "Validation", "Price and Quantity must be non-negative.")
            return

        price = self.price_spin.value()
        qty = self.qty_spin.value()
        category = self.category_combo.currentText()
        
        self.setEnabled(False)
        self.add_btn.setText("Adding...")
        
        self._result = {"success": False, "msg": "Unknown error"}
        
        def worker():
            try:
                _ensure_db()
                item_id = _insert_item(name, price, qty, self.image_path, category, self.custom_check.isChecked())
                if item_id:
                    self._result = {"success": True, "msg": "Item added successfully!"}
                else:
                    self._result = {"success": False, "msg": "Failed to add item"}
            except Exception as e:
                import traceback
                traceback.print_exc()
                self._result = {"success": False, "msg": f"Error: {str(e)}"}
        
        self._progress = QProgressDialog("Adding item...", None, 0, 0, self)
        self._progress.setWindowModality(Qt.WindowModal)
        self._progress.show()
        
        self._worker = threading.Thread(target=worker)
        self._worker.daemon = True
        self._worker.start()
        
        def poll():
            if not self._worker.is_alive():
                self._progress.accept()
                if self._result["success"]:
                    QMessageBox.information(self, "Success", self._result["msg"])
                    self.accept()
                else:
                    QMessageBox.critical(self, "Error", self._result["msg"])
                    self.setEnabled(True)
                    self.add_btn.setText("Add")
                return
            QTimer.singleShot(100, poll)
        
        QTimer.singleShot(100, poll)


class EditItemDialog(QDialog):
    def __init__(self, item: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Edit Item #{item['id']}")
        self.setModal(True)
        self.resize(800, 480)
        self.item = item

        self.name_edit = QLineEdit(item["name"])
        self.price_spin = QDoubleSpinBox()
        self.price_spin.setRange(0.0, 10_000_000.0)
        self.price_spin.setDecimals(2)
        self.price_spin.setSingleStep(0.10)
        self.price_spin.setValue(float(item["price"]))
        self.qty_spin = QSpinBox()
        self.qty_spin.setRange(0, 1_000_000)
        self.qty_spin.setValue(int(item["quantity"]))

        self.category_combo = QComboBox()
        self.category_combo.addItems(["Casual", "Mains", "Appetizers", "Drinks", "Desserts"])
        try:
            existing = _get_all_categories()
            for c in existing:
                if c and self.category_combo.findText(c) == -1:
                    self.category_combo.addItem(c)
        except Exception:
            pass
        try:
            current_cat = str(item.get("category") or "Mains")
            if self.category_combo.findText(current_cat) == -1:
                self.category_combo.addItem(current_cat)
            self.category_combo.setCurrentText(current_cat)
        except Exception:
            self.category_combo.setCurrentText("Mains")

        self.custom_check = QCheckBox("Has drink customization (sugar / ice / size)")
        self.custom_check.setChecked(bool(item.get("has_custom_options", 0)))

        self.new_image_path = None
        self.image_label = QLabel("Change image (optional)")
        self.image_btn = QPushButton("Change Image")
        self.image_btn.clicked.connect(self.choose_image)

        form = QFormLayout()
        form.addRow("Name", self.name_edit)
        form.addRow("Price", self.price_spin)
        form.addRow("Quantity", self.qty_spin)
        form.addRow("Category", self.category_combo)
        form.addRow("Customization", self.custom_check)
        form.addRow("Image", self.image_btn)
        form.addRow("", self.image_label)

        buttons = QHBoxLayout()
        self.save_btn = QPushButton("Save")
        self.cancel_btn = QPushButton("Cancel")
        self.save_btn.clicked.connect(self.on_save)
        self.cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(self.save_btn)
        buttons.addWidget(self.cancel_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(buttons)

    def choose_image(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Image", "", "Images (*.png *.jpg *.jpeg)")
        if file_path:
            try:
                if os.path.getsize(file_path) > _MAX_IMAGE_BYTES:
                    QMessageBox.NoIcon(self, "Image too large", "Please choose an image smaller than 5 MB.")
                    return
            except Exception:
                pass
            self.new_image_path = file_path
            self.image_label.setText(os.path.basename(file_path))

    def on_save(self):
        name = self.name_edit.text().strip()
        price = float(self.price_spin.value())
        qty = int(self.qty_spin.value())
        category = self.category_combo.currentText()
        if not name:
            QMessageBox.NoIcon(self, "Validation", "Name is required.")
            return
        if price < 0 or qty < 0:
            QMessageBox.NoIcon(self, "Validation", "Price and Quantity must be non-negative.")
            return
        self.save_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.save_btn.setText("Saving...")

        done = threading.Event()
        result = {"err": None}

        def worker():
            try:
                _update_item(self.item["id"], name, price, qty, self.new_image_path, self.item.get("image"), category, self.custom_check.isChecked())
            except Exception as e:
                result["err"] = e
            finally:
                done.set()

        threading.Thread(target=worker, daemon=True).start()

        def poll():
            if not done.is_set():
                return
            timer.stop()
            if result["err"] is not None:
                self.save_btn.setEnabled(True)
                self.cancel_btn.setEnabled(True)
                self.save_btn.setText("Save")
                QMessageBox.critical(self, "Error", f"Failed to update item: {result['err']}")
                return
            QMessageBox.information(self, "Success", "Item updated.")
            self.accept()

        timer = QTimer(self)
        timer.timeout.connect(poll)
        timer.start(100)


class ViewItemsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Inventory Items")
        self.setModal(False)

        from PySide6.QtWidgets import QLineEdit
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search by ID or Name...")
        self.search_edit.textChanged.connect(self._on_search_changed)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["ID", "Thumb", "Name", "Quantity", "Price", "Updated"]) 
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(self.table.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(self.table.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setMouseTracking(True)
        self.table.setItemDelegate(StockAlertRowDelegate(self.table))
        self.table.cellEntered.connect(self._on_cell_entered)

        self.resize(1200, 550)

        self.preview_label = QLabel(self)
        self.preview_label.setWindowFlag(Qt.ToolTip)
        self.preview_label.hide()
        self.table.viewport().installEventFilter(self)

        self._icon_timer = QTimer(self)
        self._icon_timer.setInterval(10)
        self._icon_timer.timeout.connect(self._build_icon_chunk)
        self._icon_cursor = 0

        btn_layout = QHBoxLayout()
        self.refresh_btn = QPushButton("🔄 Refresh")
        self.edit_btn = QPushButton("✏ Edit")
        self.delete_btn = QPushButton("🗑 Delete")
        self.export_csv_btn = QPushButton("📊 Export CSV")
        self.export_json_btn = QPushButton("📄 Export JSON")
        self.low_stock_btn = StockBadgeButton("Stock Alerts")
        self.close_btn = QPushButton("Close")
        
        self.refresh_btn.clicked.connect(self.refresh_async)
        self.edit_btn.clicked.connect(self._on_edit)
        self.delete_btn.clicked.connect(self._on_delete)
        self.export_csv_btn.clicked.connect(self._export_csv)
        self.export_json_btn.clicked.connect(self._export_json)
        self.low_stock_btn.clicked.connect(self._show_stock_alerts)
        self.close_btn.clicked.connect(self.close)
        
        for b in (self.refresh_btn, self.edit_btn, self.delete_btn):
            btn_layout.addWidget(b)
        btn_layout.addStretch()
        for b in (self.export_csv_btn, self.export_json_btn, self.low_stock_btn, self.close_btn):
            btn_layout.addWidget(b)
        
        QShortcut(QKeySequence("F5"), self).activated.connect(self.refresh_async)
        QShortcut(QKeySequence("Ctrl+E"), self).activated.connect(self._on_edit)
        QShortcut(QKeySequence("Del"), self).activated.connect(self._on_delete)
        QShortcut(QKeySequence("Ctrl+S"), self).activated.connect(self._export_csv)
        QShortcut(QKeySequence("Esc"), self).activated.connect(self.close)

        shortcuts_label = QLabel("Shortcuts: F5=Refresh | Ctrl+E=Edit | Del=Delete | Ctrl+S=Export | Esc=Close")
        shortcuts_label.setStyleSheet("color: gray; font-size: 10px;")
        
        layout = QVBoxLayout(self)
        layout.addWidget(self.search_edit)
        layout.addWidget(self.table)
        layout.addLayout(btn_layout)
        layout.addWidget(shortcuts_label)

        self._all_rows = []
        self.low_stock_btn.update_badge(0)
        self.refresh_async()

    def refresh_table(self):
        rows = _fetch_all_items()
        self._all_rows = [_prepare_row_for_display(r) for r in rows]
        self._apply_filter_and_rebuild()

    def _apply_filter_and_rebuild(self):
        text = (self.search_edit.text() or "").strip().lower()
        rows = self._all_rows if hasattr(self, '_all_rows') else []
        if text:
            def _match(r):
                try:
                    return (text in str(r["id"]).lower()) or (text in str(r["name"]).lower())
                except Exception:
                    return False
            rows = [r for r in rows if _match(r)]
        self._view_rows = _sort_stock_alerts_first(rows)
        self.table.setRowCount(0)
        for row in self._view_rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(str(row["id"])) )
            thumb_item = QTableWidgetItem()
            thumb_item.setFlags(thumb_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if row.get("_thumb_icon"):
                thumb_item.setIcon(row["_thumb_icon"])
            self.table.setItem(r, 1, thumb_item)
            self.table.setItem(r, 2, QTableWidgetItem(row["name"]))
            self.table.setItem(r, 3, QTableWidgetItem(str(row["quantity"])) )
            self.table.setItem(r, 4, QTableWidgetItem(f"{row['price']:.2f}") )
            self.table.setItem(r, 5, QTableWidgetItem(row.get("updated_at_str") or ""))
            self._style_stock_row(r, int(row.get("quantity") or 0))

        self._update_stock_alert_badge()
        self._icon_cursor = 0
        if not self._icon_timer.isActive():
            self._icon_timer.start()

    def _style_stock_row(self, row_index: int, quantity: int):
        state = _stock_alert_state(quantity)
        if state == "out":
            accent = STOCK_OUT_BORDER
            background = STOCK_OUT_BG
            tooltip = "Out of stock"
        elif state == "low":
            accent = STOCK_LOW_BORDER
            background = STOCK_LOW_BG
            tooltip = f"Low stock: {quantity}"
        else:
            accent = TEXT_PRIMARY
            background = None
            tooltip = f"Stock: {quantity}"

        for col in range(self.table.columnCount()):
            item = self.table.item(row_index, col)
            if not item:
                continue
            if background:
                item.setBackground(QBrush(QColor(background)))
            item.setForeground(QBrush(QColor(accent if col == 3 else TEXT_PRIMARY)))
            item.setToolTip(tooltip)
            item.setData(STOCK_ALERT_ROLE, state)
            if state in ("out", "low"):
                font = item.font()
                font.setWeight(QFont.Weight.DemiBold)
                item.setFont(font)

        qty_item = self.table.item(row_index, 3)
        if qty_item and quantity < LOW_STOCK_THRESHOLD:
            qty_item.setText(f"{quantity}  {tooltip}")

    def _update_stock_alert_badge(self):
        rows = getattr(self, "_all_rows", [])
        count = sum(1 for row in rows if int(row.get("quantity") or 0) < LOW_STOCK_THRESHOLD)
        self.low_stock_btn.update_badge(count)

    def _on_search_changed(self, _text: str):
        self._apply_filter_and_rebuild()

    def refresh_async(self):
        self.refresh_btn.setEnabled(False)
        done = threading.Event()
        result = {"rows": [], "err": None}

        def worker():
            try:
                _ensure_db()
                rows = _fetch_all_items()
                result["rows"] = [_prepare_row_for_display(r) for r in rows]
            except Exception as e:
                result["err"] = e
            finally:
                done.set()

        threading.Thread(target=worker, daemon=True).start()

        def poll():
            if not done.is_set():
                return
            timer.stop()
            self.refresh_btn.setEnabled(True)
            if result["err"] is not None:
                QMessageBox.critical(self, "Refresh failed", str(result["err"]))
                return
            self._all_rows = result["rows"]
            self._apply_filter_and_rebuild()

        timer = QTimer(self)
        timer.timeout.connect(poll)
        timer.start(100)

    def _build_icon_chunk(self):
        if not hasattr(self, '_view_rows'):
            self._icon_timer.stop()
            return
        rows = self._view_rows
        chunk = 20
        processed = 0
        while self._icon_cursor < len(rows) and processed < chunk:
            idx = self._icon_cursor
            row = rows[idx]
            if row.get("_thumb_icon") is None and row.get("image"):
                thumb_pix = _make_thumbnail_pixmap(row["image"], (48, 48))
                if thumb_pix:
                    row["_thumb_icon"] = QIcon(thumb_pix)
                    row["_preview_pix"] = _make_preview_pixmap(row["image"], (320, 320))
                    item = self.table.item(idx, 1)
                    if item is not None:
                        item.setIcon(row["_thumb_icon"])
            self._icon_cursor += 1
            processed += 1
        if self._icon_cursor >= len(rows):
            self._icon_timer.stop()

    def eventFilter(self, obj, event):
        if obj is self.table.viewport() and event.type() == QEvent.Leave:
            self.preview_label.hide()
        return super().eventFilter(obj, event)

    def _on_cell_entered(self, row: int, column: int):
        if column != 1 or not hasattr(self, '_view_rows') or row < 0 or row >= len(self._view_rows):
            self.preview_label.hide()
            return
            
        item = self._view_rows[row]
        if not item.get('_preview_pix') and item.get('image'):
            item['_preview_pix'] = _make_preview_pixmap(item['image'], (320, 320))
            
        if not item.get('_preview_pix'):
            self.preview_label.hide()
            return
            
        cursor_pos = self.table.viewport().mapToGlobal(self.table.visualItemRect(self.table.item(row, column)).center())
        screen = QApplication.screenAt(cursor_pos) or QApplication.primaryScreen()
        screen_rect = screen.availableGeometry()
        
        preview_size = item['_preview_pix'].size()
        preview_width = min(preview_size.width(), 400)
        preview_height = min(preview_size.height(), 400)

        padding = 20
        y_pos = cursor_pos.y() + 20
        
        if y_pos + preview_height + padding > screen_rect.bottom():
            y_pos = cursor_pos.y() - preview_height - 20
            
        x_pos = cursor_pos.x() + 20
        if x_pos + preview_width > screen_rect.right() - padding:
            x_pos = screen_rect.right() - preview_width - padding
        x_pos = max(x_pos, screen_rect.left() + padding)
        
        self.preview_label.setPixmap(item['_preview_pix'].scaled(
            preview_width, preview_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        ))
        self.preview_label.move(int(x_pos), int(y_pos))
        self.preview_label.show()

    def _selected_item_id(self) -> Optional[int]:
        selected = self.table.selectedItems()
        if not selected:
            return None
        row = selected[0].row()
        id_item = self.table.item(row, 0)
        try:
            return int(id_item.text()) if id_item else None
        except Exception:
            return None

    def _on_edit(self):
        item_id = self._selected_item_id()
        if item_id is None:
            QMessageBox.information(self, "Select", "Please select a row to edit.")
            return
        on_edit(item_id)
        self.refresh_table()

    def _on_delete(self):
        item_id = self._selected_item_id()
        if item_id is None:
            QMessageBox.information(self, "Select", "Please select a row to delete.")
            return
        on_delete(item_id)
        self.refresh_table()
    
    def _export_csv(self):

        if export_inventory_to_csv:
            export_inventory_to_csv(self._view_rows if hasattr(self, '_view_rows') else self._all_rows, self)
        else:
            QMessageBox.NoIcon(self, "Not Available", "Export functionality not available")
    
    def _export_json(self):
        if export_inventory_to_json:
            export_inventory_to_json(self._view_rows if hasattr(self, '_view_rows') else self._all_rows, self)
        else:
            QMessageBox.NoIcon(self, "Not Available", "Export functionality not available")
    
    def _show_stock_alerts(self):
        rows = [
            row for row in getattr(self, "_all_rows", [])
            if int(row.get("quantity") or 0) < LOW_STOCK_THRESHOLD
        ]
        if not rows:
            QMessageBox.information(self, "Stock Alerts", "All items are stocked above the low-stock threshold.")
            return
        dlg = StockAlertsDialog(_sort_stock_alerts_first(rows), LOW_STOCK_THRESHOLD, self)
        dlg.exec()


class StockAlertsDialog(QDialog):
    def __init__(self, rows: list, threshold: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Stock Alerts")
        self.setModal(True)
        self.resize(760, 440)

        out_count = sum(1 for row in rows if int(row.get("quantity") or 0) <= 0)
        low_count = sum(1 for row in rows if 0 < int(row.get("quantity") or 0) < threshold)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("Stock Alerts")
        title.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 20px; font-weight: 800; background: transparent;")
        layout.addWidget(title)

        summary = QLabel(f"{out_count} out of stock  |  {low_count} low stock below {threshold}")
        summary.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px; font-weight: 600; background: transparent;")
        layout.addWidget(summary)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["ID", "Name", "Category", "Quantity", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setItemDelegate(StockAlertRowDelegate(self.table))
        layout.addWidget(self.table, 1)

        for row in rows:
            self._add_row(row)

        close_btn = QPushButton("Close")
        close_btn.setMinimumHeight(38)
        close_btn.clicked.connect(self.accept)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _add_row(self, row: dict):
        r = self.table.rowCount()
        self.table.insertRow(r)
        qty = int(row.get("quantity") or 0)
        state = _stock_alert_state(qty)
        background = STOCK_OUT_BG if state == "out" else STOCK_LOW_BG
        accent = STOCK_OUT_BORDER if state == "out" else STOCK_LOW_BORDER
        status = _stock_alert_text(qty)
        values = [
            str(row.get("id", "")),
            str(row.get("name", "")),
            str(row.get("category") or ""),
            str(qty),
            status,
        ]
        for col, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setData(STOCK_ALERT_ROLE, state)
            item.setBackground(QBrush(QColor(background)))
            item.setForeground(QBrush(QColor(accent if col in (3, 4) else TEXT_PRIMARY)))
            item.setToolTip(status)
            font = item.font()
            font.setWeight(QFont.Weight.DemiBold)
            item.setFont(font)
            self.table.setItem(r, col, item)

def on_view():
    global _view_dialog
    try:
        _ensure_db()
    except Exception as e:
        QMessageBox.critical(QApplication.activeWindow(), "Error", str(e))
        return
    if _view_dialog is None or not _view_dialog.isVisible():
        _view_dialog = ViewItemsDialog(QApplication.activeWindow())
        _view_dialog.show()
        _view_dialog.raise_()
        _view_dialog.activateWindow()
    else:
        _view_dialog.refresh_async()
        _view_dialog.raise_()
        _view_dialog.activateWindow()


def on_add():
    try:
        _ensure_db()
    except Exception as e:
        QMessageBox.critical(QApplication.activeWindow(), "Error", str(e))
        return
    dlg = AddItemDialog(QApplication.activeWindow())
    if dlg.exec() == QDialog.Accepted:
        if _view_dialog and _view_dialog.isVisible():
            _view_dialog.refresh_async()


def on_edit(item_id: Optional[int] = None):
    try:
        _ensure_db()
    except Exception as e:
        QMessageBox.critical(QApplication.activeWindow(), "Error", str(e))
        return
    if item_id is None:
        on_view()
        QMessageBox.information(QApplication.activeWindow(), "Select Item", "Select a row in the list and click Edit.")
        return
    item = _get_item_by_id(int(item_id))
    if not item:
        QMessageBox.information(QApplication.activeWindow(), "Not found", f"Item #{item_id} not found.")
        return
    dlg = EditItemDialog(item, QApplication.activeWindow())
    if dlg.exec() == QDialog.Accepted:
        if _view_dialog and _view_dialog.isVisible():
            _view_dialog.refresh_async()


def on_delete(item_id: Optional[int] = None):
    try:
        _ensure_db()
    except Exception as e:
        QMessageBox.critical(QApplication.activeWindow(), "Error", str(e))
        return
    if item_id is None:
        on_view()
        QMessageBox.information(QApplication.activeWindow(), "Select Item", "Select a row in the list and click Delete.")
        return
    item = _get_item_by_id(int(item_id))
    if not item:
        QMessageBox.information(QApplication.activeWindow(), "Not found", f"Item #{item_id} not found.")
        return
    confirm = QMessageBox.question(
        QApplication.activeWindow(),
        "Confirm Delete",
        f"Delete item #{item['id']} ({item['name']})?",
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No,
    )
    if confirm == QMessageBox.Yes:
        done = threading.Event()
        err = {"e": None}

        def worker():
            try:
                _delete_item(item["id"])
            except Exception as e:
                err["e"] = e
            finally:
                done.set()

        threading.Thread(target=worker, daemon=True).start()

        def poll():
            if not done.is_set():
                return
            timer.stop()
            if err["e"] is not None:
                QMessageBox.critical(QApplication.activeWindow(), "Error", f"Failed to delete: {err['e']}")
            else:
                QMessageBox.information(QApplication.activeWindow(), "Deleted", "Item deleted.")
            if _view_dialog and _view_dialog.isVisible():
                _view_dialog.refresh_async()

        timer = QTimer(QApplication.activeWindow())
        timer.timeout.connect(poll)
        timer.start(100)


class InventoryWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        from .theme_manager import GREEN, GREEN_DARK, BG_MAIN, BG_WHITE, TEXT_PRIMARY, BORDER

        self.setStyleSheet(f"background-color: {BG_MAIN};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        header = QHBoxLayout()

        title = QLabel("Inventory Management")
        title.setStyleSheet(f"font-size: 22px; font-weight: 700; color: {TEXT_PRIMARY}; background: transparent;")
        header.addWidget(title)

        header.addStretch()

        self.add_btn = QPushButton("+ Add Item")
        self.add_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {GREEN};
                color: white;
                border: none;
                border-radius: 10px;
                padding: 10px 22px;
                font-weight: 600;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {GREEN_DARK};
            }}
        """)
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_btn.clicked.connect(self._on_add)
        header.addWidget(self.add_btn)

        layout.addLayout(header)

        self._view_dialog = ViewItemsDialog(self)
        self._view_dialog.setWindowFlags(Qt.Widget)
        self._view_dialog.setModal(False)

        if hasattr(self._view_dialog, 'close_btn'):
            self._view_dialog.close_btn.hide()

        layout.addWidget(self._view_dialog)

    def _on_add(self):
        dlg = AddItemDialog(self)
        if dlg.exec() == QDialog.Accepted:
            self._view_dialog.refresh_async()

    def refresh(self):
        if hasattr(self._view_dialog, 'refresh_async'):
            self._view_dialog.refresh_async()
