import logging
from PySide6.QtWidgets import QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, QPushButton, QHBoxLayout, QLabel, QMessageBox, QLineEdit, QApplication, QWidget
from PySide6.QtCore import Qt, QTimer, QObject, QEvent
from PySide6.QtGui import QShortcut, QKeySequence

logger = logging.getLogger(__name__)

class SilentMessageBox(QMessageBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        
    def event(self, e):
        if e.type() == QEvent.Type.ApplicationActivate:
            e.accept()
            return True
        return super().event(e)

def show_message(parent, title, message, icon=QMessageBox.Icon.Information, buttons=QMessageBox.StandardButton.Ok):
    msg = SilentMessageBox()
    msg.setWindowTitle(title)
    msg.setText(message)
    msg.setIcon(icon)
    msg.setStandardButtons(buttons)
    msg.setWindowModality(Qt.WindowModality.WindowModal)
    return msg.exec()
from datetime import datetime, timedelta, timezone
import threading

try:
    from .export_utils import export_transactions_to_csv
except ImportError:
    export_transactions_to_csv = None

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


def _ensure_db():
    if getattr(db, "conn", None) is None or getattr(db, "cursor", None) is None:
        db.connect()


def _to_gmt7_str(dt_val) -> str:
    try:
        if dt_val is None:
            return ""
        tz7 = timezone(timedelta(hours=7))
        if isinstance(dt_val, str):
            raw = dt_val.strip()
            if not raw:
                return ""
            for fmt in (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M:%S.%f",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M:%S.%f",
            ):
                try:
                    parsed = datetime.strptime(raw, fmt)
                    return parsed.replace(tzinfo=timezone.utc).astimezone(tz7).strftime("%Y-%m-%d %H:%M:%S")
                except ValueError:
                    continue
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(tz7).strftime("%Y-%m-%d %H:%M:%S")
        if dt_val.tzinfo is None:
            return (dt_val.replace(tzinfo=timezone.utc).astimezone(tz7)).strftime("%Y-%m-%d %H:%M:%S")
        return dt_val.astimezone(tz7).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(dt_val or "")


class TransactionsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Transactions")
        self.setModal(False)
        self.resize(1400, 600)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search by Transaction ID...")
        self.search_edit.textChanged.connect(self._on_search_changed)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["ID", "Items", "Total", "Created (GMT+7)"])
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._on_txn_selected)
        
        self.table.setColumnWidth(0, 80)
        self.table.setColumnWidth(1, 100)
        self.table.setColumnWidth(2, 120)
        self.table.setColumnWidth(3, 200)

        self.details_table = QTableWidget(0, 5)
        self.details_table.setHorizontalHeaderLabels(["Item ID", "Name", "Qty", "Unit Price", "Subtotal"])
        self.details_table.verticalHeader().setVisible(False)

        self.details_table.setColumnWidth(0, 100)
        self.details_table.setColumnWidth(1, 300)
        self.details_table.setColumnWidth(2, 80)
        self.details_table.setColumnWidth(3, 120)
        self.details_table.setColumnWidth(4, 120)
        self.details_label = QLabel("Transaction Items")

        self.refresh_btn = QPushButton("🔄 Refresh")
        self.export_btn = QPushButton("📊 Export CSV")
        self.delete_btn = QPushButton("❌ Delete Selected")
        self.clear_all_btn = QPushButton("🗑️ Clear All History")
        self.close_btn = QPushButton("Close")
        
        self.refresh_btn.clicked.connect(self.refresh_async)
        self.export_btn.clicked.connect(self._export_csv)
        self.delete_btn.clicked.connect(self._delete_selected_transaction)
        self.clear_all_btn.clicked.connect(self._clear_all_history)
        self.close_btn.clicked.connect(self.close)
        
        self.delete_btn.setStyleSheet("""
            QPushButton {
                background-color: #e67e22;
                color: white;
                font-weight: bold;
                padding: 8px 15px;
                border: none;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #d35400;
            }
        """)
        
        self.clear_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #e74c3c;
                color: white;
                font-weight: bold;
                padding: 8px 15px;
                border: none;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #c0392b;
            }
        """)

        btns = QHBoxLayout()
        btns.addWidget(self.refresh_btn)
        btns.addWidget(self.export_btn)
        btns.addWidget(self.delete_btn)
        btns.addWidget(self.clear_all_btn)
        btns.addStretch()
        btns.addWidget(self.close_btn)
        
        QShortcut(QKeySequence("F5"), self).activated.connect(self.refresh_async)
        QShortcut(QKeySequence("Ctrl+S"), self).activated.connect(self._export_csv)
        QShortcut(QKeySequence("Esc"), self).activated.connect(self.close)
        
        shortcuts_label = QLabel("💡 Shortcuts: F5=Refresh | Ctrl+S=Export | Esc=Close")
        shortcuts_label.setStyleSheet("color: gray; font-size: 10px;")

        layout = QVBoxLayout(self)
        layout.addWidget(self.search_edit)
        layout.addWidget(self.table)
        layout.addWidget(self.details_label)
        layout.addWidget(self.details_table)
        layout.addLayout(btns)
        layout.addWidget(shortcuts_label)

        self._rows = []
        self._filtered_rows = []
        self._details_cache = {}
        self.refresh_async()

    def refresh_async(self):
        try:
            _ensure_db()
        except Exception as e:
            error_msg = str(e)
            if "2002" in error_msg or "Can't connect" in error_msg:
                show_message(
                    self,
                    "Connection Error",
                    "❌ Cannot connect to database server.\n\n"
                    "The server may be down or your internet connection is unstable.\n\n"
                    "Please check your connection and try again.",
                    QMessageBox.Icon.Critical
                )
            else:
                show_message(self, "Database Error", f"Error: {error_msg}", QMessageBox.Icon.Critical)
            return
        self.refresh_btn.setEnabled(False)
        done = threading.Event()
        result = {"rows": [], "err": None}

        def worker():
            conn = None
            cur = None
            try:
                conn = db.get_pooled_connection()
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT t.id, COALESCE(COUNT(ti.id),0) AS items, t.total_amount, t.created_at
                    FROM transactions t
                    LEFT JOIN transaction_items ti ON ti.transaction_id = t.id
                    GROUP BY t.id, t.total_amount, t.created_at
                    ORDER BY t.id DESC
                    """
                )
                rows = cur.fetchall()
                result["rows"] = rows
            except Exception as e:
                result["err"] = e
            finally:
                try:
                    if cur:
                        cur.close()
                    if conn:
                        conn.close()
                except Exception as e:
                    logger.debug(f"Cleanup failed in _load_transactions: {e}")
                done.set()

        threading.Thread(target=worker, daemon=True).start()

        def poll():
            if not done.is_set():
                return
            timer.stop()
            self.refresh_btn.setEnabled(True)
            if result["err"] is not None:
                show_message(self, "Load failed", str(result["err"]), QMessageBox.Icon.Critical)
                return
            self._rows = result["rows"]
            self._apply_filter_and_rebuild()

        timer = QTimer(self)
        timer.timeout.connect(poll)
        timer.start(100)

    def _apply_filter_and_rebuild(self):
        text = (self.search_edit.text() or "").strip()
        rows = self._rows
        if text:
            rows = [r for r in rows if text in str(r[0])]
        self._filtered_rows = rows
        self.table.setRowCount(0)
        for rid, items, total, created_at in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(str(rid)))
            self.table.setItem(r, 1, QTableWidgetItem(str(items)))
            self.table.setItem(r, 2, QTableWidgetItem(f"{float(total):.2f}"))
            self.table.setItem(r, 3, QTableWidgetItem(_to_gmt7_str(created_at)))
        self.details_table.setRowCount(0)

    def _on_search_changed(self, _text: str):
        self._apply_filter_and_rebuild()

    def _on_txn_selected(self):
        sel = self.table.selectedItems()
        if not sel:
            return
        row = sel[0].row()
        id_item = self.table.item(row, 0)
        if not id_item:
            return
        txn_id = int(id_item.text())
        if txn_id in self._details_cache:
            self._populate_details(self._details_cache[txn_id])
            return
        self._load_details_async(txn_id)

    def _populate_details(self, rows):
        self.details_table.setRowCount(0)
        for item_id, name, qty, unit_price, subtotal in rows:
            r = self.details_table.rowCount()
            self.details_table.insertRow(r)
            self.details_table.setItem(r, 0, QTableWidgetItem(str(item_id)))
            self.details_table.setItem(r, 1, QTableWidgetItem(str(name)))
            self.details_table.setItem(r, 2, QTableWidgetItem(str(qty)))
            self.details_table.setItem(r, 3, QTableWidgetItem(f"{float(unit_price):.2f}"))
            self.details_table.setItem(r, 4, QTableWidgetItem(f"{float(subtotal):.2f}"))

    def _load_details_async(self, txn_id: int):
        done = threading.Event()
        result = {"rows": [], "err": None}

        def worker():
            conn = None
            cur = None
            try:
                conn = db.get_pooled_connection()
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT ti.item_id, i.name, ti.quantity, ti.unit_price, ti.subtotal
                    FROM transaction_items ti
                    LEFT JOIN inventory_items i ON i.id = ti.item_id
                    WHERE ti.transaction_id = ?
                    ORDER BY ti.id ASC
                    """,
                    (txn_id,)
                )
                rows = cur.fetchall()
                result["rows"] = rows
            except Exception as e:
                result["err"] = e
            finally:
                try:
                    if cur:
                        cur.close()
                    if conn:
                        conn.close()
                except Exception as e:
                    logger.debug(f"Cleanup failed in _load_details_async: {e}")
                done.set()

        threading.Thread(target=worker, daemon=True).start()

        def poll():
            if not done.is_set():
                return
            timer.stop()
            if result["err"] is not None:
                show_message(self, "Load details failed", str(result["err"]), QMessageBox.Icon.Critical)
                return
            self._details_cache[txn_id] = result["rows"]
            self._populate_details(result["rows"])

        timer = QTimer(self)
        timer.timeout.connect(poll)
        timer.start(100)
    
    def _export_csv(self):
        if export_transactions_to_csv and self._filtered_rows:
            export_transactions_to_csv(self._filtered_rows, self)
        elif not self._filtered_rows:
            show_message(self, "No Data", "No transactions to export", QMessageBox.Icon.Information)
        else:
            show_message(self, "Not Available", "Export functionality not available", QMessageBox.Icon.Warning)
    
    def _delete_selected_transaction(self):
        sel = self.table.selectedItems()
        if not sel:
            show_message(self, "No Selection", "Please select a transaction to delete.", QMessageBox.Icon.Information)
            return
        
        row = sel[0].row()
        txn_id = int(self.table.item(row, 0).text())
        txn_total = self.table.item(row, 2).text()
        
        restore_msg = QMessageBox(self)
        restore_msg.setIcon(QMessageBox.Question)
        restore_msg.setWindowTitle("Delete Transaction")
        restore_msg.setText(f"Delete transaction #{txn_id} (${txn_total})?")
        restore_msg.setInformativeText(
            "Do you want to restore inventory quantities?\n\n"
            "✅ Yes - Add sold items back to inventory\n"
            "❌ No - Just delete the transaction record\n"
            "⏹️ Cancel - Don't delete anything"
        )
        yes_btn = restore_msg.addButton("Yes, Restore Inventory", QMessageBox.YesRole)
        no_btn = restore_msg.addButton("No, Just Delete Record", QMessageBox.NoRole)
        cancel_btn = restore_msg.addButton("Cancel", QMessageBox.RejectRole)
        restore_msg.setDefaultButton(yes_btn)
        
        restore_msg.exec()
        clicked = restore_msg.clickedButton()
        
        if clicked == cancel_btn:
            return
        
        restore_inventory = (clicked == yes_btn)
        
        self.delete_btn.setEnabled(False)
        self.delete_btn.setText("Deleting...")
        
        done = threading.Event()
        result = {"success": False, "err": None}
        
        def worker():
            conn = None
            cur = None
            try:
                _ensure_db()
                conn = db.get_pooled_connection()
                cur = conn.cursor()
                
                if restore_inventory:
                    cur.execute(
                        "SELECT item_id, quantity FROM transaction_items WHERE transaction_id = ?",
                        (txn_id,)
                    )
                    items = cur.fetchall()
                    items = [dict(item) for item in items]

                    for item in items:
                        cur.execute(
                            "UPDATE inventory_items SET quantity = quantity + ? WHERE id = ?",
                            (item['quantity'], item['item_id'])
                        )
                
                try:
                    cur.execute("""
                        SELECT t.id, COUNT(ti.id) as item_count 
                        FROM transactions t
                        LEFT JOIN transaction_items ti ON t.id = ti.transaction_id
                        WHERE t.id = ?
                        GROUP BY t.id
                    """, (txn_id,))
                    
                    txn_data = cur.fetchone()
                    if not txn_data:
                        result["err"] = f"Transaction #{txn_id} not found in database"
                        result["deleted_count"] = 0
                        return
                    
                    txn_data = dict(txn_data)
                    result["item_count"] = txn_data["item_count"]
                    try:
                        cur.execute("DELETE FROM transaction_items WHERE transaction_id = ?", (txn_id,))
                        items_deleted = cur.rowcount
                        result["items_deleted"] = items_deleted
                        
                        item_count = txn_data[1] if isinstance(txn_data, tuple) else txn_data["item_count"]
                        if items_deleted != item_count:
                            conn.rollback()
                            result["err"] = f"Mismatch in item deletion. Expected {item_count} items, deleted {items_deleted}"
                            return
                            
                    except Exception as e:
                        conn.rollback()
                        result["err"] = f"Failed to delete transaction items: {str(e)}"
                        return
                    
                    try:
                        cur.execute("DELETE FROM transactions WHERE id = ?", (txn_id,))
                        txn_deleted = cur.rowcount
                        result["deleted_count"] = txn_deleted
                        
                        if txn_deleted == 0:
                            conn.rollback()
                            result["err"] = "No rows were deleted from transactions table"
                            return
                            
                    except Exception as e:
                        conn.rollback()
                        result["err"] = f"Failed to delete transaction: {str(e)}"
                        return

                    conn.commit()
                    result["success"] = True
                
                except Exception as e:
                    if conn:
                        conn.rollback()
                    result["err"] = f"Database error: {str(e)}"
                    result["success"] = False
                    result["error_code"] = e.errno
                except Exception as e:
                    if conn:
                        conn.rollback()
                    result["err"] = f"Error: {str(e)}"
                    result["success"] = False
                finally:
                    try:
                        if cur:
                            cur.close()
                        if conn:
                            conn.close()
                    except Exception as e:
                        logger.debug(f"Cleanup failed in _delete_transaction: {e}")
                
            except Exception as e:
                result["err"] = e
                try:
                    if conn:
                        conn.rollback()
                        conn.close()
                except Exception as cleanup_err:
                    logger.debug(f"Rollback/close failed in _delete_transaction: {cleanup_err}")
            finally:
                done.set()
        
        threading.Thread(target=worker, daemon=True).start()
        
        def poll():
            if not done.is_set():
                return
            timer.stop()
            
            self.delete_btn.setEnabled(True)
            self.delete_btn.setText("❌ Delete Selected")
            
            if result.get("err"):
                error_msg = f"Failed to delete transaction {txn_id}:\n{result['err']}"
                if result.get("error_code"):
                    error_msg += f"\n\nError code: {result['error_code']}"
                QMessageBox.critical(
                    self,
                    "Delete Failed",
                    error_msg
                )
            else:
                if result.get("deleted_count", 0) == 0:
                    show_message(
                        self,
                        "Not Found",
                        f"Transaction #{txn_id} not found or already deleted.",
                        QMessageBox.Icon.Warning
                    )
                else:
                    restore_text = " and inventory restored" if restore_inventory else ""
                    show_message(
                        self,
                        "✅ Deleted",
                        f"Transaction #{txn_id} deleted{restore_text}!",
                        QMessageBox.Icon.Information
                    )
                    self.refresh_async()
        
        timer = QTimer(self)
        timer.timeout.connect(poll)
        timer.start(100)
    
    def _clear_all_history(self):
        total_count = len(self._rows) if hasattr(self, '_rows') else 0
        
        if total_count == 0:
            show_message(self, "No Data", "There are no transactions to delete.", QMessageBox.Icon.Information)
            return
        
        msg = SilentMessageBox(self)
        msg.setWindowTitle("Clear All History")
        msg.setText(f"Delete ALL {total_count} transactions?")
        msg.setInformativeText(
            "Do you want to restore inventory quantities?\n\n"
            "✅ Yes - Add all sold items back to inventory\n"
            "❌ No - Just delete transaction records\n"
            "⏹️ Cancel - Don't delete anything"
        )
        msg.setIcon(QMessageBox.Icon.Question)
        yes_btn = msg.addButton("Yes, Restore All", QMessageBox.ButtonRole.YesRole)
        no_btn = msg.addButton("No, Just Delete", QMessageBox.ButtonRole.NoRole)
        cancel_btn = msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        msg.setDefaultButton(cancel_btn)
        
        msg.exec()
        clicked = msg.clickedButton()
        
        if clicked == cancel_btn:
            return
        
        restore_inventory = (clicked == yes_btn)
        
        reply2 = show_message(
            self,
            "⚠️ FINAL WARNING",
            f"Last chance! Delete {total_count} transactions permanently?\n\n"
            f"Inventory will {'be restored' if restore_inventory else 'NOT be affected'}.",
            QMessageBox.Icon.Warning,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply2 != QMessageBox.StandardButton.Yes:
            return
        
        self.clear_all_btn.setEnabled(False)
        self.clear_all_btn.setText("Deleting...")
        
        done = threading.Event()
        result = {"success": False, "err": None, "deleted": 0}
        
        def worker():
            conn = None
            cur = None
            try:
                _ensure_db()
                conn = db.get_pooled_connection()
                cur = conn.cursor()
                
                cur.execute("SELECT COUNT(*) as count FROM transactions")
                count_result = cur.fetchone()
                count = dict(count_result)['count'] if count_result else 0
                
                if count == 0:
                    result["deleted"] = 0
                    result["success"] = True
                    return

                if restore_inventory:
                    cur.execute(
                        "SELECT item_id, SUM(quantity) as total_qty "
                        "FROM transaction_items "
                        "GROUP BY item_id"
                    )
                    items = cur.fetchall()
                    items = [dict(item) for item in items]
                    
                    for item in items:
                        cur.execute(
                            "UPDATE inventory_items SET quantity = quantity + ? WHERE id = ?",
                            (item['total_qty'], item['item_id'])
                        )
                
                try:
                    cur.execute("DELETE FROM transaction_items")
                    cur.execute("DELETE FROM transactions")
                    conn.commit()
                    result["deleted"] = count
                    result["success"] = True
                    
                except Exception as e:
                    if conn:
                        conn.rollback()
                    raise e
                finally:
                    if cur:
                        cur.close()
                
            except Exception as e:
                error_msg = str(e)
                if hasattr(e, 'errno'):
                    error_msg = f"Error {e.errno}: {error_msg}"
                if hasattr(e, 'sqlstate'):
                    error_msg = f"{error_msg} (SQL State: {e.sqlstate})"
                
                result["err"] = error_msg
                try:
                    if conn and conn.is_connected():
                        conn.rollback()
                except Exception as rollback_err:
                    result["err"] = f"{error_msg}\n(Additional error during rollback: {str(rollback_err)})"
            finally:
                try:
                    if conn:
                        conn.close()
                except Exception as e:
                    logger.debug(f"Cleanup failed in _clear_all_history: {e}")
                done.set()
        
        threading.Thread(target=worker, daemon=True).start()
        
        def poll():
            if not done.is_set():
                return
            timer.stop()
            
            self.clear_all_btn.setEnabled(True)
            self.clear_all_btn.setText("🗑️ Clear All History")
            
            if result.get("err"):
                show_message(
                    self,
                    "Delete Failed",
                    f"Failed to delete transactions:\n{result['err']}\n\nData has been rolled back.",
                    QMessageBox.Icon.Critical
                )
            elif result.get("deleted", 0) == 0 and not result.get("success"):
                show_message(
                    self,
                    "Deletion Failed",
                    "No transactions were deleted. The transaction list may be empty or already cleared.",
                    QMessageBox.Icon.Warning
                )
            else:
                show_message(
                    self,
                    "✅ Success",
                    f"Successfully deleted {result['deleted']} transactions!",
                    QMessageBox.Icon.Information
                )
                self.refresh_async()
        
        timer = QTimer(self)
        timer.timeout.connect(poll)
        timer.start(100)


def view_transactions():
    from PySide6.QtWidgets import QApplication
    dlg = TransactionsDialog(QApplication.activeWindow())
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()


class TransactionsWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        from .theme_manager import BG_MAIN, TEXT_PRIMARY, GREEN, GREEN_DARK

        self.setStyleSheet(f"background-color: {BG_MAIN};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel("Transaction History")
        title.setStyleSheet(f"font-size: 22px; font-weight: 700; color: {TEXT_PRIMARY}; background: transparent;")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        self._dialog = TransactionsDialog(self)
        self._dialog.setWindowFlags(Qt.Widget)
        self._dialog.setModal(False)

        if hasattr(self._dialog, 'close_btn'):
            self._dialog.close_btn.hide()

        layout.addWidget(self._dialog)

    def refresh(self):
        if hasattr(self._dialog, 'refresh_async'):
            self._dialog.refresh_async()
