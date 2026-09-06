import logging
from typing import Dict, Any, List
from dataclasses import dataclass
from datetime import datetime, timedelta

from database.database import get_connection

logger = logging.getLogger(__name__)


@dataclass
class SalesMetrics:
    """Key sales metrics for dashboard."""
    total_sales: float
    transaction_count: int
    items_sold: int
    average_transaction: float
    inventory_value: float
    low_stock_count: int


@dataclass
class TopSellingItem:
    """Top selling item data."""
    name: str
    quantity_sold: int
    revenue: float
    transaction_count: int


class StatsService:
    """
    Service class for analytics and statistics.
    
    Provides aggregated data for dashboards and reports.
    
    Example:
        service = StatsService()
        metrics = service.get_key_metrics()
        top_items = service.get_top_selling_items(limit=10)
    """
    
    def get_key_metrics(self) -> Dict[str, Any]:
        """
        Get key business metrics.
        
        Returns:
            Dictionary with sales, transaction, and inventory metrics.
        """
        with get_connection() as (conn, cur):
            metrics = {}
            
            # Transaction totals
            cur.execute("""
                SELECT COUNT(*), COALESCE(SUM(total_amount), 0) 
                FROM transactions
            """)
            txn_count, total_sales = cur.fetchone()
            metrics['transaction_count'] = txn_count or 0
            metrics['total_sales'] = float(total_sales or 0)
            
            # Average transaction
            metrics['average_transaction'] = (
                metrics['total_sales'] / metrics['transaction_count'] 
                if metrics['transaction_count'] > 0 else 0
            )
            
            # Items sold
            cur.execute("SELECT COALESCE(SUM(quantity), 0) FROM transaction_items")
            metrics['items_sold'] = int(cur.fetchone()[0] or 0)
            
            # Inventory value
            cur.execute("""
                SELECT COALESCE(SUM(price * quantity), 0) 
                FROM inventory_items
            """)
            metrics['inventory_value'] = float(cur.fetchone()[0] or 0)
            
            # Low stock count
            cur.execute("""
                SELECT COUNT(*) FROM inventory_items WHERE quantity < 10
            """)
            metrics['low_stock_count'] = int(cur.fetchone()[0] or 0)
            
            # Total inventory items
            cur.execute("SELECT COUNT(*) FROM inventory_items")
            metrics['total_items'] = int(cur.fetchone()[0] or 0)
            
            return metrics
    
    def get_top_selling_items(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get top selling items by quantity.
        
        Args:
            limit: Maximum number of items to return.
            
        Returns:
            List of top selling items with sales data.
        """
        with get_connection() as (conn, cur):
            cur.execute("""
                SELECT 
                    i.name,
                    SUM(ti.quantity) as qty_sold,
                    SUM(ti.subtotal) as revenue,
                    COUNT(DISTINCT ti.transaction_id) as txn_count
                FROM transaction_items ti
                LEFT JOIN inventory_items i ON i.id = ti.item_id
                GROUP BY ti.item_id, i.name
                ORDER BY qty_sold DESC
                LIMIT ?
            """, (limit,))
            
            return [
                {
                    'name': row[0] or 'Unknown',
                    'quantity_sold': int(row[1] or 0),
                    'revenue': float(row[2] or 0),
                    'transaction_count': int(row[3] or 0)
                }
                for row in cur.fetchall()
            ]
    
    def get_recent_transactions(self, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Get most recent transactions.
        
        Args:
            limit: Maximum number of transactions to return.
            
        Returns:
            List of recent transactions.
        """
        with get_connection() as (conn, cur):
            cur.execute("""
                SELECT id, total_amount, created_at
                FROM transactions
                ORDER BY id DESC
                LIMIT ?
            """, (limit,))
            
            return [
                {
                    'id': row[0],
                    'total_amount': float(row[1]),
                    'created_at': row[2]
                }
                for row in cur.fetchall()
            ]
    
    def get_sales_by_category(self) -> List[Dict[str, Any]]:
        """
        Get sales breakdown by category.
        
        Returns:
            List of categories with their sales data.
        """
        with get_connection() as (conn, cur):
            cur.execute("""
                SELECT 
                    i.category,
                    SUM(ti.quantity) as qty_sold,
                    SUM(ti.subtotal) as revenue
                FROM transaction_items ti
                LEFT JOIN inventory_items i ON i.id = ti.item_id
                WHERE i.category IS NOT NULL
                GROUP BY i.category
                ORDER BY revenue DESC
            """)
            
            return [
                {
                    'category': row[0] or 'Uncategorized',
                    'quantity_sold': int(row[1] or 0),
                    'revenue': float(row[2] or 0)
                }
                for row in cur.fetchall()
            ]
    
    def get_daily_sales(self, days: int = 7) -> List[Dict[str, Any]]:
        """
        Get sales data for the last N days.
        
        Args:
            days: Number of days to look back.
            
        Returns:
            List of daily sales summaries.
        """
        with get_connection() as (conn, cur):
            cur.execute("""
                SELECT 
                    DATE(created_at) as sale_date,
                    COUNT(*) as transactions,
                    SUM(total_amount) as revenue
                FROM transactions
                WHERE DATE(created_at) >= DATE('now', ?)
                GROUP BY DATE(created_at)
                ORDER BY sale_date DESC
            """, (f'-{days} days',))
            
            return [
                {
                    'date': row[0],
                    'transactions': int(row[1] or 0),
                    'revenue': float(row[2] or 0)
                }
                for row in cur.fetchall()
            ]
    
    def get_inventory_summary(self) -> Dict[str, Any]:
        """
        Get inventory summary statistics.
        
        Returns:
            Dictionary with inventory metrics by category.
        """
        with get_connection() as (conn, cur):
            # By category
            cur.execute("""
                SELECT 
                    category,
                    COUNT(*) as item_count,
                    SUM(quantity) as total_quantity,
                    SUM(price * quantity) as total_value
                FROM inventory_items
                GROUP BY category
                ORDER BY total_value DESC
            """)
            
            categories = [
                {
                    'category': row[0] or 'Uncategorized',
                    'item_count': int(row[1] or 0),
                    'total_quantity': int(row[2] or 0),
                    'total_value': float(row[3] or 0)
                }
                for row in cur.fetchall()
            ]
            
            # Overall
            cur.execute("""
                SELECT 
                    COUNT(*),
                    SUM(quantity),
                    SUM(price * quantity),
                    AVG(price)
                FROM inventory_items
            """)
            row = cur.fetchone()
            
            return {
                'by_category': categories,
                'total_items': int(row[0] or 0),
                'total_quantity': int(row[1] or 0),
                'total_value': float(row[2] or 0),
                'average_price': float(row[3] or 0)
            }
    
    def generate_report(self) -> str:
        """
        Generate a text report of all statistics.
        
        Returns:
            Formatted text report.
        """
        metrics = self.get_key_metrics()
        top_items = self.get_top_selling_items(10)
        recent = self.get_recent_transactions(5)
        
        lines = [
            "=" * 70,
            "SALES & INVENTORY ANALYTICS REPORT",
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 70,
            "",
            "KEY METRICS",
            "-" * 70,
            f"{'Total Sales:':<25} ${metrics['total_sales']:,.2f}",
            f"{'Transactions:':<25} {metrics['transaction_count']:,}",
            f"{'Items Sold:':<25} {metrics['items_sold']:,}",
            f"{'Avg Transaction:':<25} ${metrics['average_transaction']:,.2f}",
            f"{'Inventory Value:':<25} ${metrics['inventory_value']:,.2f}",
            f"{'Low Stock Items:':<25} {metrics['low_stock_count']}",
            "",
            "TOP SELLING ITEMS",
            "-" * 70,
        ]
        
        for i, item in enumerate(top_items, 1):
            lines.append(
                f"{i}. {item['name']:<30} "
                f"Qty: {item['quantity_sold']:<6} "
                f"Revenue: ${item['revenue']:,.2f}"
            )
        
        lines.extend([
            "",
            "RECENT TRANSACTIONS",
            "-" * 70,
        ])
        
        for txn in recent:
            lines.append(
                f"#{txn['id']:<8} ${txn['total_amount']:>10,.2f}   {txn['created_at']}"
            )
        
        return "\n".join(lines)
