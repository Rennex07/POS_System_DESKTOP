import csv
import json
from datetime import datetime
from typing import List, Dict
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget


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
