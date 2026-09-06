import csv
import html
import io
import json
import os
import webbrowser
import zipfile
from datetime import datetime
from typing import List, Dict
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget


# export inventory to csv | kw:inventory export csv
def export_inventory_to_csv(inventory_items: List[Dict], parent: QWidget = None) -> bool:
    try:
        filename, _ = QFileDialog.getSaveFileName(
            parent,
            "Export Inventory to CSV",
            f"inventory_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            "CSV Files (*.csv)"
        )
        
        if not filename:
            return False
        
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['ID', 'Name', 'Price', 'Quantity', 'Created', 'Updated'])
            
            for item in inventory_items:
                writer.writerow([
                    item.get('id', ''),
                    item.get('name', ''),
                    f"{item.get('price', 0):.2f}",
                    item.get('quantity', 0),
                    item.get('created_at_str', ''),
                    item.get('updated_at_str', '')
                ])
        
        QMessageBox.information(parent, "Success", f"Exported {len(inventory_items)} items to:\n{filename}")
        return True
    except Exception as e:
        QMessageBox.critical(parent, "Export Error", f"Failed to export: {e}")
        return False

# export inventory to json | kw:inventory export json
def export_inventory_to_json(inventory_items: List[Dict], parent: QWidget = None) -> bool:
    try:
        filename, _ = QFileDialog.getSaveFileName(
            parent,
            "Export Inventory to JSON",
            f"inventory_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            "JSON Files (*.json)"
        )
        
        if not filename:
            return False
        
        export_data = []
        for item in inventory_items:
            export_item = {
                'id': item.get('id'),
                'name': item.get('name'),
                'price': float(item.get('price', 0)),
                'quantity': int(item.get('quantity', 0)),
                'created_at': item.get('created_at_str', ''),
                'updated_at': item.get('updated_at_str', ''),
                'has_image': bool(item.get('image'))
            }
            export_data.append(export_item)
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump({
                'exported_at': datetime.now().isoformat(),
                'item_count': len(export_data),
                'items': export_data
            }, f, indent=2)
        
        QMessageBox.information(parent, "Success", f"Exported {len(inventory_items)} items to:\n{filename}")
        return True
    except Exception as e:
        QMessageBox.critical(parent, "Export Error", f"Failed to export: {e}")
        return False


# transaction export to csv | kw:transaction export csv
def export_transactions_to_csv(transactions: List[tuple], parent: QWidget = None) -> bool:
    try:
        filename, _ = QFileDialog.getSaveFileName(
            parent,
            "Export Transactions to CSV",
            f"transactions_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            "CSV Files (*.csv)"
        )
        
        if not filename:
            return False
        
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Transaction ID', 'Items Count', 'Total Amount', 'Created Date'])
            
            for txn in transactions:
                writer.writerow([
                    txn[0],
                    txn[1],
                    f"{float(txn[2]):.2f}",
                    str(txn[3])
                ])
        
        QMessageBox.information(parent, "Success", f"Exported {len(transactions)} transactions to:\n{filename}")
        return True
    except Exception as e:
        QMessageBox.critical(parent, "Export Error", f"Failed to export: {e}")
        return False


def export_sales_report_html(transactions: List[tuple], parent: QWidget = None) -> bool:
    try:
        filename, _ = QFileDialog.getSaveFileName(
            parent,
            "Save Sales Report",
            f"sales_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html",
            "HTML Files (*.html)"
        )

        if not filename:
            return False
        if not filename.lower().endswith(".html"):
            filename += ".html"

        total_subtotal = sum(float(row[3] or 0) for row in transactions)
        total_discount = sum(float(row[4] or 0) for row in transactions)
        total_vat = sum(float(row[5] or 0) for row in transactions)
        total_sales = sum(float(row[6] or 0) for row in transactions)
        total_items = sum(int(row[2] or 0) for row in transactions)
        avg_sale = total_sales / len(transactions) if transactions else 0

        first_date = str(transactions[-1][7]) if transactions else ""
        last_date = str(transactions[0][7]) if transactions else ""

        item_rows = ""
        try:
            from database import database as db
            ids = [int(row[0]) for row in transactions]
            if ids:
                placeholders = ",".join("?" for _ in ids)
                with db.get_connection() as (conn, cur):
                    cur.execute(
                        f"""
                        SELECT
                            ti.transaction_id,
                            COALESCE(i.name, printf('Item #%d', ti.item_id)) AS name,
                            ti.quantity,
                            ti.unit_price,
                            ti.subtotal
                        FROM transaction_items ti
                        LEFT JOIN inventory_items i ON i.id = ti.item_id
                        WHERE ti.transaction_id IN ({placeholders})
                        ORDER BY ti.transaction_id DESC, ti.id ASC
                        """,
                        ids,
                    )
                    for txn_id, name, qty, unit_price, subtotal in cur.fetchall():
                        item_rows += f"""
                            <tr>
                                <td>#{txn_id}</td>
                                <td>{html.escape(str(name))}</td>
                                <td>{qty}</td>
                                <td>${float(unit_price or 0):,.2f}</td>
                                <td>${float(subtotal or 0):,.2f}</td>
                            </tr>
                        """
        except Exception:
            item_rows = ""

        txn_rows = ""
        for row in transactions:
            txn_id = row[0]
            table_number = row[1] or "-"
            item_count = row[2]
            subtotal = float(row[3] or 0)
            discount = float(row[4] or 0)
            vat = float(row[5] or 0)
            total = float(row[6] or 0)
            created_at = row[7]
            txn_rows += f"""
                <tr>
                    <td>#{txn_id}</td>
                    <td>{html.escape(str(table_number))}</td>
                    <td>{item_count}</td>
                    <td>${subtotal:,.2f}</td>
                    <td>${discount:,.2f}</td>
                    <td>${vat:,.2f}</td>
                    <td><strong>${total:,.2f}</strong></td>
                    <td>{html.escape(str(created_at))}</td>
                </tr>
            """

        report_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Sales Report</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            color: #1E1E2D;
            margin: 32px;
            background: #F5F5F7;
        }}
        .sheet {{
            background: #FFFFFF;
            border: 1px solid #E8E8E8;
            border-radius: 8px;
            padding: 28px;
            max-width: 1180px;
            margin: 0 auto;
        }}
        h1 {{ margin: 0 0 6px; font-size: 26px; }}
        .muted {{ color: #636E72; font-size: 13px; }}
        .summary {{
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 12px;
            margin: 24px 0;
        }}
        .metric {{
            border: 1px solid #E8E8E8;
            border-left: 4px solid #1BAC4B;
            border-radius: 8px;
            padding: 14px;
        }}
        .metric .label {{ color: #636E72; font-size: 12px; }}
        .metric .value {{ font-size: 20px; font-weight: 700; margin-top: 6px; }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 14px;
            font-size: 12px;
        }}
        th {{
            text-align: left;
            color: #636E72;
            border-bottom: 2px solid #E8E8E8;
            padding: 10px 8px;
        }}
        td {{
            border-bottom: 1px solid #F0F0F0;
            padding: 9px 8px;
        }}
        h2 {{ margin-top: 28px; font-size: 17px; }}
        @media print {{
            body {{ margin: 0; background: white; }}
            .sheet {{ border: none; }}
        }}
    </style>
</head>
<body>
    <div class="sheet">
        <h1>Sales Report</h1>
        <div class="muted">Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} | Range: {html.escape(first_date)} to {html.escape(last_date)}</div>

        <div class="summary">
            <div class="metric"><div class="label">Sales</div><div class="value">${total_sales:,.2f}</div></div>
            <div class="metric"><div class="label">Transactions</div><div class="value">{len(transactions):,}</div></div>
            <div class="metric"><div class="label">Items</div><div class="value">{total_items:,}</div></div>
            <div class="metric"><div class="label">Discounts</div><div class="value">${total_discount:,.2f}</div></div>
            <div class="metric"><div class="label">VAT</div><div class="value">${total_vat:,.2f}</div></div>
        </div>

        <div class="muted">Subtotal before discounts and VAT: ${total_subtotal:,.2f} | Average sale: ${avg_sale:,.2f}</div>

        <h2>Transactions</h2>
        <table>
            <thead>
                <tr>
                    <th>ID</th><th>Table</th><th>Items</th><th>Subtotal</th><th>Discount</th><th>VAT</th><th>Total</th><th>Created</th>
                </tr>
            </thead>
            <tbody>{txn_rows}</tbody>
        </table>

        <h2>Items Sold</h2>
        <table>
            <thead>
                <tr><th>Transaction</th><th>Item</th><th>Qty</th><th>Unit</th><th>Subtotal</th></tr>
            </thead>
            <tbody>{item_rows or '<tr><td colspan="5">No item details available.</td></tr>'}</tbody>
        </table>
    </div>
</body>
</html>"""

        with open(filename, "w", encoding="utf-8") as f:
            f.write(report_html)

        webbrowser.open(filename)
        QMessageBox.information(parent, "Report Saved", f"Sales report saved to:\n{filename}")
        return True
    except Exception as e:
        QMessageBox.critical(parent, "Report Error", f"Failed to generate report: {e}")
        return False


def export_sales_report_bundle(transactions: List[tuple], parent: QWidget = None) -> bool:
    try:
        filename, _ = QFileDialog.getSaveFileName(
            parent,
            "Save Sales Report Bundle",
            f"sales_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
            "ZIP Files (*.zip)"
        )
        if not filename:
            return False
        if not filename.lower().endswith(".zip"):
            filename += ".zip"

        def csv_text(headers, rows):
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(headers)
            writer.writerows(rows)
            return buffer.getvalue()

        txn_rows = []
        txn_ids = []
        total_subtotal = 0.0
        total_discount = 0.0
        total_vat = 0.0
        total_sales = 0.0
        total_items = 0
        table_summary = {}

        for row in transactions:
            txn_id = int(row[0])
            table_number = str(row[1] or "-")
            item_count = int(row[2] or 0)
            subtotal = float(row[3] or 0)
            discount = float(row[4] or 0)
            vat = float(row[5] or 0)
            total = float(row[6] or 0)
            created_at = str(row[7] or "")

            txn_ids.append(txn_id)
            total_subtotal += subtotal
            total_discount += discount
            total_vat += vat
            total_sales += total
            total_items += item_count
            table_summary.setdefault(table_number, {"transactions": 0, "items": 0, "sales": 0.0})
            table_summary[table_number]["transactions"] += 1
            table_summary[table_number]["items"] += item_count
            table_summary[table_number]["sales"] += total

            txn_rows.append([
                txn_id,
                table_number,
                item_count,
                f"{subtotal:.2f}",
                f"{discount:.2f}",
                f"{vat:.2f}",
                f"{total:.2f}",
                created_at,
            ])

        item_rows = []
        product_summary = {}
        if txn_ids:
            try:
                from database import database as db
                placeholders = ",".join("?" for _ in txn_ids)
                with db.get_connection() as (conn, cur):
                    cur.execute(
                        f"""
                        SELECT
                            ti.transaction_id,
                            COALESCE(i.name, printf('Item #%d', ti.item_id)) AS name,
                            COALESCE(i.category, '') AS category,
                            ti.quantity,
                            ti.unit_price,
                            ti.subtotal
                        FROM transaction_items ti
                        LEFT JOIN inventory_items i ON i.id = ti.item_id
                        WHERE ti.transaction_id IN ({placeholders})
                        ORDER BY ti.transaction_id DESC, ti.id ASC
                        """,
                        txn_ids,
                    )
                    for txn_id, name, category, qty, unit_price, subtotal in cur.fetchall():
                        qty = int(qty or 0)
                        subtotal = float(subtotal or 0)
                        unit_price = float(unit_price or 0)
                        item_rows.append([
                            txn_id,
                            name,
                            category,
                            qty,
                            f"{unit_price:.2f}",
                            f"{subtotal:.2f}",
                        ])
                        product_summary.setdefault(name, {"category": category, "qty": 0, "revenue": 0.0})
                        product_summary[name]["qty"] += qty
                        product_summary[name]["revenue"] += subtotal
            except Exception:
                item_rows = []

        product_rows = [
            [name, data["category"], data["qty"], f"{data['revenue']:.2f}"]
            for name, data in sorted(product_summary.items(), key=lambda kv: kv[1]["revenue"], reverse=True)
        ]
        table_rows = [
            [table, data["transactions"], data["items"], f"{data['sales']:.2f}"]
            for table, data in sorted(table_summary.items(), key=lambda kv: kv[0])
        ]

        average_sale = total_sales / len(transactions) if transactions else 0.0
        html_rows = "\n".join(
            "<tr>" + "".join(f"<td>{html.escape(str(cell))}</td>" for cell in row) + "</tr>"
            for row in txn_rows
        )
        product_html_rows = "\n".join(
            "<tr>" + "".join(f"<td>{html.escape(str(cell))}</td>" for cell in row) + "</tr>"
            for row in product_rows[:25]
        )

        report_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Sales Report Bundle</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 32px; color: #1E1E2D; }}
        h1 {{ margin-bottom: 4px; }}
        .muted {{ color: #636E72; font-size: 13px; }}
        .grid {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin: 24px 0; }}
        .metric {{ border: 1px solid #E8E8E8; border-left: 4px solid #1BAC4B; border-radius: 8px; padding: 14px; }}
        .label {{ color: #636E72; font-size: 12px; }}
        .value {{ font-size: 20px; font-weight: 700; margin-top: 6px; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 12px; margin-top: 12px; }}
        th, td {{ border-bottom: 1px solid #E8E8E8; padding: 8px; text-align: left; }}
        th {{ color: #636E72; }}
    </style>
</head>
<body>
    <h1>Sales Report</h1>
    <div class="muted">Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>
    <div class="grid">
        <div class="metric"><div class="label">Sales</div><div class="value">${total_sales:,.2f}</div></div>
        <div class="metric"><div class="label">Transactions</div><div class="value">{len(transactions):,}</div></div>
        <div class="metric"><div class="label">Items</div><div class="value">{total_items:,}</div></div>
        <div class="metric"><div class="label">Discounts</div><div class="value">${total_discount:,.2f}</div></div>
        <div class="metric"><div class="label">VAT</div><div class="value">${total_vat:,.2f}</div></div>
    </div>
    <div class="muted">Subtotal: ${total_subtotal:,.2f} | Average sale: ${average_sale:,.2f}</div>
    <h2>Top Products</h2>
    <table><thead><tr><th>Product</th><th>Category</th><th>Qty</th><th>Revenue</th></tr></thead><tbody>{product_html_rows}</tbody></table>
    <h2>Transactions</h2>
    <table><thead><tr><th>ID</th><th>Table</th><th>Items</th><th>Subtotal</th><th>Discount</th><th>VAT</th><th>Total</th><th>Created</th></tr></thead><tbody>{html_rows}</tbody></table>
</body>
</html>"""

        with zipfile.ZipFile(filename, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("sales_report.html", report_html)
            bundle.writestr(
                "transactions.csv",
                csv_text(["Transaction ID", "Table", "Items", "Subtotal", "Discount", "VAT", "Total", "Created"], txn_rows),
            )
            bundle.writestr(
                "item_lines.csv",
                csv_text(["Transaction ID", "Item", "Category", "Quantity", "Unit Price", "Subtotal"], item_rows),
            )
            bundle.writestr(
                "product_summary.csv",
                csv_text(["Item", "Category", "Quantity Sold", "Revenue"], product_rows),
            )
            bundle.writestr(
                "table_summary.csv",
                csv_text(["Table", "Transactions", "Items", "Sales"], table_rows),
            )

        try:
            os.startfile(os.path.dirname(os.path.abspath(filename)))
        except Exception:
            webbrowser.open(os.path.dirname(os.path.abspath(filename)))

        QMessageBox.information(
            parent,
            "Report Bundle Saved",
            "Saved a report bundle with HTML, transactions, item lines, product summary, and table summary.",
        )
        return True
    except Exception as e:
        QMessageBox.critical(parent, "Report Error", f"Failed to generate report bundle: {e}")
        return False


# generate low stock report | kw:low stock report
def generate_low_stock_report(inventory_items: List[Dict], threshold: int = 10, parent: QWidget = None) -> bool:
    try:
        filename, _ = QFileDialog.getSaveFileName(
            parent,
            "Save Low Stock Report",
            f"low_stock_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            "Text Files (*.txt)"
        )
        
        if not filename:
            return False
        
        low_stock_items = [item for item in inventory_items if item.get('quantity', 0) < threshold]
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write("=" * 70 + "\n")
            f.write("LOW STOCK ALERT REPORT\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Threshold: {threshold} units\n")
            f.write("=" * 70 + "\n\n")
            
            if not low_stock_items:
                f.write("✓ All items are adequately stocked!\n")
            else:
                f.write(f"⚠ {len(low_stock_items)} items below threshold:\n\n")
                
                for item in sorted(low_stock_items, key=lambda x: x.get('quantity', 0)):
                    qty = item.get('quantity', 0)
                    status = "OUT OF STOCK" if qty == 0 else f"LOW ({qty} left)"
                    f.write(f"• {item.get('name', 'Unknown'):30s} - {status:15s} - ${item.get('price', 0):.2f}\n")
                
                f.write("\n" + "=" * 70 + "\n")
                f.write(f"RESTOCK RECOMMENDATIONS:\n")
                f.write("=" * 70 + "\n\n")
                
                for item in low_stock_items:
                    recommended = max(50, threshold * 5)
                    needed = recommended - item.get('quantity', 0)
                    cost = needed * float(item.get('price', 0))
                    f.write(f"• {item.get('name', 'Unknown'):30s}: Order {needed:3d} units (Cost: ${cost:,.2f})\n")
        
        QMessageBox.information(
            parent,
            "Success",
            f"Low stock report saved to:\n{filename}\n\n{len(low_stock_items)} items need attention."
        )
        return True
    except Exception as e:
        QMessageBox.critical(parent, "Export Error", f"Failed to generate report: {e}")
        return False
