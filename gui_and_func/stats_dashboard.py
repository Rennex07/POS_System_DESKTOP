import logging
import threading
import csv
from datetime import datetime, timedelta, timezone
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGridLayout, QGroupBox, QTableWidget, QTableWidgetItem,
    QMessageBox, QFrame, QWidget, QComboBox, QFileDialog
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont

logger = logging.getLogger(__name__)
try:
    from database import database as db
except ModuleNotFoundError:
    import os, sys
    root = os.path.dirname(os.path.dirname(__file__))
    if root not in sys.path:
        sys.path.insert(0, root)
    import database as db

from .pdf_generator import PDFGenerator, export_monthly_report_csv


def _ensure_db():
    if getattr(db, "conn", None) is None:
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
            return dt_val.replace(tzinfo=timezone.utc).astimezone(tz7).strftime("%Y-%m-%d %H:%M:%S")
        return dt_val.astimezone(tz7).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(dt_val or "")


class StatsDashboard(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📊 Sales & Inventory Analytics")
        self.setModal(False)
        self.resize(1300, 650)
    
        layout = QVBoxLayout(self)

        title = QLabel("Analytics Dashboard")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        filter_layout = QHBoxLayout()
        filter_label = QLabel("Show:")
        self.period_filter_combo = QComboBox()
        self.period_filter_combo.addItem("All Time", "all_time")
        self.period_filter_combo.addItem("Yearly", "yearly")
        self.period_filter_combo.addItem("Monthly", "monthly")
        self.period_filter_combo.addItem("Weekly", "weekly")
        self.period_filter_combo.addItem("Daily", "daily")
        self.period_filter_combo.currentIndexChanged.connect(self.load_stats)
        filter_layout.addStretch()
        filter_layout.addWidget(filter_label)
        filter_layout.addWidget(self.period_filter_combo)
        layout.addLayout(filter_layout)
        
        metrics_box = QGroupBox("Key Metrics")
        metrics_layout = QGridLayout(metrics_box)
        
        self.total_sales_label = self._create_metric_label("Total Sales", "Loading...")
        self.total_transactions_label = self._create_metric_label("Transactions", "Loading...")
        self.total_items_sold_label = self._create_metric_label("Items Sold", "Loading...")
        self.avg_transaction_label = self._create_metric_label("Avg Transaction", "Loading...")
        self.inventory_value_label = self._create_metric_label("Inventory Value", "Loading...")
        self.low_stock_label = self._create_metric_label("Low Stock Items", "Loading...")
        
        metrics_layout.addWidget(self.total_sales_label, 0, 0)
        metrics_layout.addWidget(self.total_transactions_label, 0, 1)
        metrics_layout.addWidget(self.total_items_sold_label, 0, 2)
        metrics_layout.addWidget(self.avg_transaction_label, 1, 0)
        metrics_layout.addWidget(self.inventory_value_label, 1, 1)
        metrics_layout.addWidget(self.low_stock_label, 1, 2)
        
        layout.addWidget(metrics_box)

        charts_row = QHBoxLayout()
        charts_row.setSpacing(20)

        top_items_box = QGroupBox("Top 5 Selling Items")
        top_items_box.setMinimumWidth(512)
        top_items_layout = QVBoxLayout(top_items_box)
        self.top_items_table = QTableWidget(0, 4)
        self.top_items_table.setHorizontalHeaderLabels(["Item", "Quantity Sold", "Revenue", "Transactions"])
        self.top_items_table.verticalHeader().setVisible(False)
        self.top_items_table.setMinimumHeight(400)
        self.top_items_table.setColumnWidth(0, 150)
        self.top_items_table.setColumnWidth(1, 100)
        self.top_items_table.setColumnWidth(2, 90)
        self.top_items_table.setColumnWidth(3, 100)
        self.top_items_table.horizontalHeader().setStretchLastSection(True)
        top_items_layout.addWidget(self.top_items_table)
        charts_row.addWidget(top_items_box, 4)

        recent_box = QGroupBox("Recent 5 Transactions")
        recent_layout = QVBoxLayout(recent_box)
        self.recent_table = QTableWidget(0, 3)
        self.recent_table.setHorizontalHeaderLabels(["Transaction ID", "Amount", "Date"])
        self.recent_table.verticalHeader().setVisible(False)
        self.recent_table.setMinimumHeight(400)
        self.recent_table.setColumnWidth(2, 180)
        recent_layout.addWidget(self.recent_table)
        charts_row.addWidget(recent_box, 5)

        layout.addLayout(charts_row)
        
        btn_layout = QHBoxLayout()
        self.refresh_btn = QPushButton("🔄 Refresh")
        self.export_btn = QPushButton("📥 Export Report")
        self.monthly_report_btn = QPushButton("📅 Monthly Report")
        self.close_btn = QPushButton("Close")
        
        self.refresh_btn.clicked.connect(self.load_stats)
        self.export_btn.clicked.connect(self.export_report)
        self.monthly_report_btn.clicked.connect(self.export_monthly_report)
        self.close_btn.clicked.connect(self.close)
        
        btn_layout.addWidget(self.refresh_btn)
        btn_layout.addWidget(self.export_btn)
        btn_layout.addWidget(self.monthly_report_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self.close_btn)
        layout.addLayout(btn_layout)
        
        self.load_stats()
    
    def _create_metric_label(self, title, value):
        frame = QFrame()
        frame.setFrameStyle(QFrame.Box | QFrame.Raised)
        frame.setLineWidth(2)
        
        layout = QVBoxLayout(frame)
        
        title_label = QLabel(title)
        title_font = QFont()
        title_font.setPointSize(9)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        value_label = QLabel(value)
        value_font = QFont()
        value_font.setPointSize(16)
        value_font.setBold(True)
        value_label.setFont(value_font)
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value_label.setObjectName("metric_value")
        
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        
        return frame
    
    def _update_metric(self, metric_frame, value):
        value_label = metric_frame.findChild(QLabel, "metric_value")
        if value_label:
            value_label.setText(str(value))

    def _get_period_filter(self, period):
        now = datetime.now()
        if period == "daily":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
        elif period == "weekly":
            start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=7)
        elif period == "monthly":
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            if start.month == 12:
                end = start.replace(year=start.year + 1, month=1)
            else:
                end = start.replace(month=start.month + 1)
        elif period == "yearly":
            start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            end = start.replace(year=start.year + 1)
        else:
            return "", ()

        return " WHERE created_at >= ? AND created_at < ?", (
            start.strftime("%Y-%m-%d %H:%M:%S"),
            end.strftime("%Y-%m-%d %H:%M:%S")
        )
    
    def load_stats(self):
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setText("Loading...")
        period = self.period_filter_combo.currentData() if hasattr(self, "period_filter_combo") else "all_time"
        
        done = threading.Event()
        result = {"data": None, "err": None}
        
        def worker():
            conn = None
            cur = None
            try:
                _ensure_db()
                conn = db.get_pooled_connection()
                cur = conn.cursor()
                data = {}
                transaction_where, transaction_params = self._get_period_filter(period)
                transaction_join_filter = transaction_where.replace("created_at", "t.created_at")
                item_join_filter = transaction_where.replace("created_at", "t.created_at")

                cur.execute(
                    f"SELECT COUNT(*), COALESCE(SUM(total_amount), 0) FROM transactions{transaction_where}",
                    transaction_params
                )
                txn_count, total_sales = cur.fetchone()
                data["txn_count"] = txn_count or 0
                data["total_sales"] = float(total_sales or 0)
                
                data["avg_transaction"] = data["total_sales"] / data["txn_count"] if data["txn_count"] > 0 else 0
                
                cur.execute(f"""
                    SELECT COALESCE(SUM(ti.quantity), 0)
                    FROM transaction_items ti
                    JOIN transactions t ON t.id = ti.transaction_id
                    {transaction_join_filter}
                """, transaction_params)
                items_sold = cur.fetchone()[0]
                data["items_sold"] = int(items_sold or 0)

                cur.execute("SELECT COALESCE(SUM(price * quantity), 0) FROM inventory_items")
                inv_value = cur.fetchone()[0]
                data["inv_value"] = float(inv_value or 0)
                
                cur.execute("SELECT COUNT(*) FROM inventory_items WHERE quantity < 10")
                low_stock = cur.fetchone()[0]
                data["low_stock"] = int(low_stock or 0)
                
                cur.execute("""
                    SELECT i.name, 
                           SUM(ti.quantity) as qty_sold,
                           SUM(ti.subtotal) as revenue,
                           COUNT(DISTINCT ti.transaction_id) as txn_count
                    FROM transaction_items ti
                    JOIN transactions t ON t.id = ti.transaction_id
                    LEFT JOIN inventory_items i ON i.id = ti.item_id
                    {where_clause}
                    GROUP BY ti.item_id, i.name
                    ORDER BY qty_sold DESC
                    LIMIT 10
                """.format(where_clause=item_join_filter), transaction_params)
                data["top_items"] = cur.fetchall()
                
                cur.execute(f"""
                    SELECT id, total_amount, created_at
                    FROM transactions
                    {transaction_where}
                    ORDER BY id DESC
                    LIMIT 5
                """, transaction_params)
                data["recent_txns"] = cur.fetchall()
                
                result["data"] = data
            except Exception as e:
                result["err"] = e
            finally:
                try:
                    if cur:
                        cur.close()
                    if conn:
                        conn.close()
                except Exception as e:
                    logger.debug(f"Cleanup failed in _load_stats: {e}")
                done.set()
        
        threading.Thread(target=worker, daemon=True).start()
        
        def poll():
            if not done.is_set():
                return
            timer.stop()
            self.refresh_btn.setEnabled(True)
            self.refresh_btn.setText("🔄 Refresh")
            
            if result["err"]:
                QMessageBox.critical(self, "Error", f"Failed to load stats: {result['err']}")
                return
            
            data = result["data"]
            if not data:
                QMessageBox.warning(self, "No Data", "No statistics data was loaded. Database may be empty.")
                return
            self._update_metric(self.total_sales_label, f"${data['total_sales']:,.2f}")
            self._update_metric(self.total_transactions_label, f"{data['txn_count']:,}")
            self._update_metric(self.total_items_sold_label, f"{data['items_sold']:,}")
            self._update_metric(self.avg_transaction_label, f"${data['avg_transaction']:,.2f}")
            self._update_metric(self.inventory_value_label, f"${data['inv_value']:,.2f}")
            self._update_metric(self.low_stock_label, f"{data['low_stock']} items")
            
            self.top_items_table.setRowCount(0)
            for name, qty, revenue, txns in data["top_items"]:
                r = self.top_items_table.rowCount()
                self.top_items_table.insertRow(r)
                self.top_items_table.setItem(r, 0, QTableWidgetItem(str(name or "Unknown")))
                self.top_items_table.setItem(r, 1, QTableWidgetItem(str(qty)))
                self.top_items_table.setItem(r, 2, QTableWidgetItem(f"${float(revenue):,.2f}"))
                self.top_items_table.setItem(r, 3, QTableWidgetItem(str(txns)))
            
            self.recent_table.setRowCount(0)
            for txn_id, amount, created in data["recent_txns"]:
                r = self.recent_table.rowCount()
                self.recent_table.insertRow(r)
                self.recent_table.setItem(r, 0, QTableWidgetItem(f"#{txn_id}"))
                self.recent_table.setItem(r, 1, QTableWidgetItem(f"${float(amount):,.2f}"))
                self.recent_table.setItem(r, 2, QTableWidgetItem(_to_gmt7_str(created)))
        
        timer = QTimer(self)
        timer.timeout.connect(poll)
        timer.start(100)
    
    def export_monthly_report(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Export Monthly Report")
        dialog.setMinimumWidth(350)
        
        layout = QVBoxLayout(dialog)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)
        
        month_layout = QHBoxLayout()
        month_label = QLabel("Month:")
        month_combo = QComboBox()
        months = ["January", "February", "March", "April", "May", "June",
                  "July", "August", "September", "October", "November", "December"]
        month_combo.addItems(months)
        month_combo.setCurrentIndex(datetime.now().month - 1)
        month_layout.addWidget(month_label)
        month_layout.addWidget(month_combo, 1)
        layout.addLayout(month_layout)
        
        year_layout = QHBoxLayout()
        year_label = QLabel("Year:")
        year_combo = QComboBox()
        current_year = datetime.now().year
        for year in range(current_year - 5, current_year + 1):
            year_combo.addItem(str(year), year)
        year_combo.setCurrentIndex(year_combo.count() - 1)
        year_layout.addWidget(year_label)
        year_layout.addWidget(year_combo, 1)
        layout.addLayout(year_layout)
        
        format_layout = QHBoxLayout()
        format_label = QLabel("Format:")
        pdf_btn = QPushButton("📄 PDF Report")
        csv_btn = QPushButton("📊 CSV Data")
        format_layout.addWidget(format_label)
        format_layout.addWidget(pdf_btn)
        format_layout.addWidget(csv_btn)
        layout.addLayout(format_layout)
        
        status_label = QLabel("")
        status_label.setStyleSheet("color: #666; font-size: 12px;")
        layout.addWidget(status_label)
        
        def do_export_pdf():
            month = month_combo.currentIndex() + 1
            year = year_combo.currentData()
            status_label.setText("Loading data...")
            dialog.setEnabled(False)
            
            def worker():
                try:
                    transactions, summary = self._get_monthly_data(month, year)
                    if not transactions:
                        return {"success": False, "error": "No transactions found for selected month."}
                    
                    filepath = PDFGenerator.generate_monthly_report(
                        month, year, transactions, summary, auto_open=True
                    )
                    return {"success": True, "filepath": filepath}
                except Exception as e:
                    return {"success": False, "error": str(e)}
            
            def on_done(result):
                dialog.setEnabled(True)
                if result["success"]:
                    status_label.setText(f"Report generated: {result['filepath']}")
                    QMessageBox.information(dialog, "Success", "Monthly report generated successfully!")
                    dialog.accept()
                else:
                    status_label.setText(f"Error: {result['error']}")
                    QMessageBox.warning(dialog, "Export Failed", result["error"])
            
            self._run_async(worker, on_done)
        
        def do_export_csv():
            month = month_combo.currentIndex() + 1
            year = year_combo.currentData()
            filename, _ = QFileDialog.getSaveFileName(
                dialog,
                "Save Monthly Report",
                f"monthly_report_{year}_{month:02d}.csv",
                "CSV Files (*.csv)"
            )
            if not filename:
                status_label.setText("Export cancelled.")
                return
            status_label.setText("Loading data...")
            dialog.setEnabled(False)
            
            def worker():
                try:
                    transactions, _ = self._get_monthly_data(month, year)
                    if not transactions:
                        return {"success": False, "error": "No transactions found for selected month."}

                    if export_monthly_report_csv(month, year, transactions, filename):
                        return {"success": True, "filepath": filename}
                    else:
                        return {"success": False, "error": "Failed to write CSV file."}
                        
                except Exception as e:
                    return {"success": False, "error": str(e)}
            
            def on_done(result):
                dialog.setEnabled(True)
                if result["success"]:
                    status_label.setText(f"CSV exported: {result['filepath']}")
                    QMessageBox.information(dialog, "Success", "Monthly report exported to CSV!")
                    dialog.accept()
                else:
                    status_label.setText(f"Error: {result['error']}")
                    if "cancelled" not in result["error"].lower():
                        QMessageBox.warning(dialog, "Export Failed", result["error"])
            
            self._run_async(worker, on_done)
        
        pdf_btn.clicked.connect(do_export_pdf)
        csv_btn.clicked.connect(do_export_csv)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dialog.reject)
        layout.addWidget(cancel_btn)
        
        dialog.exec()
    
    def _get_monthly_data(self, month: int, year: int):
        _ensure_db()
        conn = db.get_pooled_connection()
        cur = conn.cursor()
        
        try:
            cur.execute("""
                SELECT id, total_amount, created_at,
                       (SELECT COUNT(*) FROM transaction_items WHERE transaction_id = transactions.id) as item_count
                FROM transactions
                WHERE strftime('%Y', created_at) = ? AND strftime('%m', created_at) = ?
                ORDER BY id DESC
            """, (str(year), f"{month:02d}"))
            
            transactions = []
            for row in cur.fetchall():
                transactions.append({
                    'id': row[0],
                    'total_amount': float(row[1]),
                    'created_at': _to_gmt7_str(row[2]),
                    'item_count': row[3]
                })
            
            cur.execute("""
                SELECT 
                    COUNT(*) as txn_count,
                    COALESCE(SUM(total_amount), 0) as total_sales
                FROM transactions
                WHERE strftime('%Y', created_at) = ? AND strftime('%m', created_at) = ?
            """, (str(year), f"{month:02d}"))
            
            txn_count, total_sales = cur.fetchone()
            summary = {
                'transaction_count': txn_count or 0,
                'total_sales': float(total_sales or 0)
            }
            
            return transactions, summary
        finally:
            cur.close()
            conn.close()
    
    def _run_async(self, worker_func, callback_func):
        done = threading.Event()
        result = {"value": None}
        
        def worker():
            try:
                result["value"] = worker_func()
            except Exception as e:
                result["value"] = {"success": False, "error": str(e)}
            finally:
                done.set()
        
        threading.Thread(target=worker, daemon=True).start()
        
        def poll():
            if done.is_set():
                timer.stop()
                callback_func(result["value"])
        
        timer = QTimer(self)
        timer.timeout.connect(poll)
        timer.start(100)
    
    def export_report(self):
        try:
            from datetime import datetime
            filename = f"sales_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            
            with open(filename, 'w', encoding='utf-8') as f:
                f.write("=" * 60 + "\n")
                f.write("SALES & INVENTORY ANALYTICS REPORT\n")
                f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 60 + "\n\n")
                
                f.write("KEY METRICS\n")
                f.write("-" * 60 + "\n")
                for label, frame in [
                    ("Total Sales", self.total_sales_label),
                    ("Transactions", self.total_transactions_label),
                    ("Items Sold", self.total_items_sold_label),
                    ("Avg Transaction", self.avg_transaction_label),
                    ("Inventory Value", self.inventory_value_label),
                    ("Low Stock Items", self.low_stock_label)
                ]:
                    value_label = frame.findChild(QLabel, "metric_value")
                    if value_label:
                        f.write(f"{label:20s}: {value_label.text()}\n")
                
                f.write("\n\nTOP SELLING ITEMS\n")
                f.write("-" * 60 + "\n")
                for row in range(self.top_items_table.rowCount()):
                    name = self.top_items_table.item(row, 0).text()
                    qty = self.top_items_table.item(row, 1).text()
                    revenue = self.top_items_table.item(row, 2).text()
                    f.write(f"{row+1}. {name} - Qty: {qty}, Revenue: {revenue}\n")
                
                f.write("\n\nRECENT TRANSACTIONS\n")
                f.write("-" * 60 + "\n")
                for row in range(self.recent_table.rowCount()):
                    txn_id = self.recent_table.item(row, 0).text()
                    amount = self.recent_table.item(row, 1).text()
                    date = self.recent_table.item(row, 2).text()
                    f.write(f"{txn_id} - {amount} - {date}\n")
            
            QMessageBox.information(self, "Success", f"Report exported to:\n{filename}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export: {e}")


def show_stats_dashboard():
    dlg = StatsDashboard()
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()


class StatsDashboardWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        self.setStyleSheet("background-color: #F5F5F7;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel("Analytics Dashboard")
        title.setStyleSheet("font-size: 22px; font-weight: 700; color: #1E1E2D; background: transparent;")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        self._dialog = StatsDashboard(self)
        self._dialog.setWindowFlags(Qt.Widget)
        self._dialog.setModal(False)

        if hasattr(self._dialog, 'close_btn'):
            self._dialog.close_btn.hide()

        layout.addWidget(self._dialog)

    def refresh(self):
        if hasattr(self._dialog, 'load_stats'):
            self._dialog.load_stats()
