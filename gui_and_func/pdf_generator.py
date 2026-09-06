import os
import math
import tempfile
import webbrowser
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from html import escape


@dataclass
class ReceiptItem:
    name: str
    quantity: int
    unit_price: float
    subtotal: float
    note: str = ""


@dataclass
class ReceiptData:
    transaction_id: int
    date: str
    items: List[ReceiptItem]
    total: float
    currency: str = "USD"
    exchange_rate: float = 4100.0 # default exchange rate

# round up to the next 100 KHR
def round_up_khr(amount: float) -> int:
    amount = round(float(amount or 0), 6)
    if amount <= 0:
        return 0
    return int(math.ceil(amount / 100.0) * 100)


class PDFGenerator:
    @staticmethod
    def generate_receipt(data: ReceiptData, auto_open: bool = True) -> str:
        html_content = PDFGenerator._create_receipt_html(data)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"receipt_{data.transaction_id}_{timestamp}.html"
        filepath = os.path.join(tempfile.gettempdir(), filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        # auto open the file to default web browser
        if auto_open:
            webbrowser.open(f"file://{filepath}")
        
        return filepath
    
    @staticmethod
    def _create_receipt_html(data: ReceiptData) -> str:
        items_html = ""
        for item in data.items:
            item_name = escape(item.name)
            note = escape(str(item.note or "").strip())
            note_html = f'<div class="item-note">Note: {note}</div>' if note else ""
            items_html += f"""
                <tr>
                    <td class="item-name">{item_name}{note_html}</td>
                    <td class="qty">{item.quantity}</td>
                    <td class="price">${item.unit_price:.2f}</td>
                    <td class="subtotal">${item.subtotal:.2f}</td>
                </tr>
            """
        
        khr_total = round_up_khr(data.total * data.exchange_rate)
        
        # HTML Format for receipt | kw:receipt html
        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Receipt #{data.transaction_id}</title>
    <style>
        @page {{
            size: 80mm auto;
            margin: 5mm;
        }}
        body {{
            font-family: 'Courier New', monospace;
            font-size: 12px;
            width: 72mm;
            margin: 0 auto;
            padding: 5mm;
            background: white;
        }}
        .header {{
            text-align: center;
            border-bottom: 1px dashed #333;
            padding-bottom: 10px;
            margin-bottom: 10px;
        }}
        .store-name {{
            font-size: 16px;
            font-weight: bold;
        }}
        .receipt-title {{
            font-size: 14px;
            margin: 5px 0;
        }}
        .info {{
            margin: 10px 0;
        }}
        .info-row {{
            display: flex;
            justify-content: space-between;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 10px 0;
        }}
        th {{
            text-align: left;
            border-top: 1px solid #333;
            border-bottom: 1px solid #333;
            padding: 3px 0;
        }}
        td {{
            padding: 3px 0;
        }}
        .item-name {{
            max-width: 30mm;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        .item-note {{
            color: #666;
            font-size: 10px;
            margin-top: 2px;
        }}
        .qty, .price, .subtotal {{
            text-align: right;
        }}
        .total-section {{
            border-top: 1px solid #333;
            margin-top: 10px;
            padding-top: 10px;
        }}
        .total-row {{
            display: flex;
            justify-content: space-between;
            font-weight: bold;
            font-size: 14px;
        }}
        .khr-total {{
            text-align: center;
            font-size: 11px;
            color: #666;
            margin-top: 5px;
        }}
        .footer {{
            text-align: center;
            margin-top: 20px;
            padding-top: 10px;
            border-top: 1px dashed #333;
            font-size: 10px;
        }}
        @media print {{
            body {{
                width: 100%;
            }}
            .no-print {{
                display: none;
            }}
        }}
    </style>
</head>
<body>
    <div class="header">
        <div class="store-name">POS SYSTEM</div>
        <div class="receipt-title">RECEIPT</div>
    </div>
    
    <div class="info">
        <div class="info-row">
            <span>Transaction #:</span>
            <span>{data.transaction_id}</span>
        </div>
        <div class="info-row">
            <span>Date:</span>
            <span>{data.date}</span>
        </div>
    </div>
    
    <table>
        <thead>
            <tr>
                <th>Item</th>
                <th class="qty">Qty</th>
                <th class="price">Price</th>
                <th class="subtotal">Total</th>
            </tr>
        </thead>
        <tbody>
            {items_html}
        </tbody>
    </table>
    
    <div class="total-section">
        <div class="total-row">
            <span>TOTAL:</span>
            <span>${data.total:.2f} {data.currency}</span>
        </div>
        <div class="khr-total">
            ({khr_total:,.0f} KHR)
        </div>
    </div>
    
    <div class="footer">
        Thank you for your business!<br>
        Please come again
    </div>
    
    <div class="no-print" style="margin-top: 30px; text-align: center;">
        <button onclick="window.print()" style="padding: 10px 20px; font-size: 14px;">
            Print Receipt
        </button>
        <button onclick="window.close()" style="padding: 10px 20px; font-size: 14px; margin-left: 10px;">
            Close
        </button>
    </div>
</body>
</html>"""
    
    @staticmethod
    def generate_monthly_report(
        month: int,
        year: int,
        transactions: List[Dict[str, Any]],
        summary: Dict[str, Any],
        auto_open: bool = True
    ) -> str:
        html_content = PDFGenerator._create_report_html(month, year, transactions, summary)
        
        month_name = datetime(year, month, 1).strftime("%B_%Y")
        filename = f"monthly_report_{month_name}.html"
        filepath = os.path.join(tempfile.gettempdir(), filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        if auto_open:
            webbrowser.open(f"file://{filepath}")
        
        return filepath
    
    @staticmethod
    def _create_report_html(
        month: int,
        year: int,
        transactions: List[Dict[str, Any]],
        summary: Dict[str, Any]
    ) -> str:
        month_name = datetime(year, month, 1).strftime("%B %Y")
        
        # monthly sale report html content | kw:monthly report html
        txn_rows = ""
        for txn in transactions:
            txn_rows += f"""
                <tr>
                    <td>#{txn.get('id', 'N/A')}</td>
                    <td>{txn.get('created_at', 'N/A')}</td>
                    <td>{txn.get('item_count', 0)}</td>
                    <td class="amount">${float(txn.get('total_amount', 0)):.2f}</td>
                </tr>
            """
        
        total_sales = summary.get('total_sales', 0)
        txn_count = summary.get('transaction_count', 0)
        avg_transaction = total_sales / txn_count if txn_count > 0 else 0
        
        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Monthly Report - {month_name}</title>
    <style>
        @page {{
            size: A4;
            margin: 15mm;
        }}
        body {{
            font-family: Arial, sans-serif;
            font-size: 12px;
            line-height: 1.5;
            color: #333;
            max-width: 210mm;
            margin: 0 auto;
            padding: 20px;
            background: white;
        }}
        .header {{
            text-align: center;
            border-bottom: 2px solid #27ae60;
            padding-bottom: 20px;
            margin-bottom: 30px;
        }}
        .store-name {{
            font-size: 24px;
            font-weight: bold;
            color: #2c3e50;
        }}
        .report-title {{
            font-size: 18px;
            color: #27ae60;
            margin: 10px 0;
        }}
        .generated-date {{
            color: #7f8c8d;
            font-size: 11px;
        }}
        .summary-grid {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 15px;
            margin-bottom: 30px;
        }}
        .summary-card {{
            background: #f8f9fa;
            border-left: 4px solid #27ae60;
            padding: 15px;
            border-radius: 4px;
        }}
        .summary-label {{
            font-size: 11px;
            color: #7f8c8d;
            text-transform: uppercase;
        }}
        .summary-value {{
            font-size: 20px;
            font-weight: bold;
            color: #2c3e50;
            margin-top: 5px;
        }}
        .section {{
            margin-top: 30px;
        }}
        .section-title {{
            font-size: 14px;
            font-weight: bold;
            color: #2c3e50;
            border-bottom: 1px solid #e0e0e0;
            padding-bottom: 8px;
            margin-bottom: 15px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 11px;
        }}
        th {{
            background: #f8f9fa;
            text-align: left;
            padding: 10px;
            font-weight: bold;
            border-bottom: 2px solid #e0e0e0;
        }}
        td {{
            padding: 10px;
            border-bottom: 1px solid #e0e0e0;
        }}
        tr:nth-child(even) {{
            background: #fafafa;
        }}
        .amount {{
            text-align: right;
        }}
        .footer {{
            margin-top: 40px;
            text-align: center;
            font-size: 10px;
            color: #7f8c8d;
            border-top: 1px solid #e0e0e0;
            padding-top: 20px;
        }}
        .no-print {{
            margin-top: 30px;
            text-align: center;
        }}
        .btn {{
            padding: 12px 24px;
            font-size: 14px;
            background: #27ae60;
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            margin: 5px;
        }}
        .btn:hover {{
            background: #219a52;
        }}
        @media print {{
            .no-print {{ display: none; }}
            body {{ padding: 0; }}
        }}
    </style>
</head>
<body>
    <div class="header">
        <div class="store-name">POS SYSTEM</div>
        <div class="report-title">Monthly Sales Report</div>
        <div class="generated-date">{month_name} | Generated: {datetime.now().strftime("%Y-%m-%d %H:%M")}</div>
    </div>
    
    <div class="summary-grid">
        <div class="summary-card">
            <div class="summary-label">Total Sales</div>
            <div class="summary-value">${total_sales:,.2f}</div>
        </div>
        <div class="summary-card">
            <div class="summary-label">Transactions</div>
            <div class="summary-value">{txn_count:,}</div>
        </div>
        <div class="summary-card">
            <div class="summary-label">Average Transaction</div>
            <div class="summary-value">${avg_transaction:,.2f}</div>
        </div>
    </div>
    
    <div class="section">
        <div class="section-title">Transaction Details</div>
        <table>
            <thead>
                <tr>
                    <th>Transaction ID</th>
                    <th>Date</th>
                    <th>Items</th>
                    <th class="amount">Amount</th>
                </tr>
            </thead>
            <tbody>
                {txn_rows}
            </tbody>
        </table>
    </div>
    
    <div class="footer">
        POS System - Monthly Report<br>
        This report is generated automatically from transaction data.
    </div>
    
    <div class="no-print">
        <button class="btn" onclick="window.print()">Print Report</button>
        <button class="btn" onclick="window.close()">Close</button>
    </div>
</body>
</html>"""


def export_monthly_report_csv(
    month: int,
    year: int,
    transactions: List[Dict[str, Any]],
    filepath: str
) -> bool:
    import csv
    
    try:
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Transaction ID', 'Date', 'Item Count', 'Total Amount', 'Month', 'Year'
            ])
            
            for txn in transactions:
                writer.writerow([
                    txn.get('id', ''),
                    txn.get('created_at', ''),
                    txn.get('item_count', 0),
                    f"{float(txn.get('total_amount', 0)):.2f}",
                    month,
                    year
                ])
        return True
    except Exception as e:
        print(f"Error exporting CSV: {e}")
        return False
