import logging
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass
from datetime import datetime

from database.database import get_connection, transaction
from database.database_setup import ensure_transactions_tables

logger = logging.getLogger(__name__)


@dataclass
class CartItem:
    """Represents an item in the shopping cart."""
    item_id: int
    name: str
    price: float
    quantity: int
    
    @property
    def subtotal(self) -> float:
        return self.price * self.quantity


@dataclass  
class TransactionSummary:
    """Summary of a completed transaction."""
    id: int
    total_amount: float
    item_count: int
    created_at: str


class TransactionService:
    """
    Service class for transaction operations.
    
    Handles order processing, checkout, and transaction history.
    
    Example:
        service = TransactionService()
        cart = [CartItem(1, "Coffee", 4.99, 2)]
        txn_id = service.checkout(cart)
    """
    
    def checkout(self, cart_items: List[Dict[str, Any]]) -> int:
        """
        Process checkout: create transaction and adjust inventory.
        
        This operation is atomic - either all items are processed
        or none are (transaction rollback on failure).
        
        Args:
            cart_items: List of dicts with keys: id, name, price, qty
            
        Returns:
            The new transaction ID.
            
        Raises:
            ValueError: If cart is empty or has invalid items.
            Exception: If inventory is insufficient.
        """
        if not cart_items:
            raise ValueError("Cart is empty")
        ensure_transactions_tables()
        
        total = sum(item['qty'] * item['price'] for item in cart_items)
        
        with transaction() as (conn, cur):
            # Create transaction record
            cur.execute(
                "INSERT INTO transactions (total_amount) VALUES (?)",
                (total,)
            )
            txn_id = cur.lastrowid
            
            # Process each item
            for item in cart_items:
                subtotal = item['qty'] * item['price']
                
                # Insert transaction item
                cur.execute("""
                    INSERT INTO transaction_items 
                    (transaction_id, item_id, quantity, unit_price, subtotal, note) 
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (txn_id, item['id'], item['qty'], item['price'], subtotal, item.get("note", "")))
                
                # Decrease inventory
                cur.execute("""
                    UPDATE inventory_items 
                    SET quantity = quantity - ? 
                    WHERE id = ? AND quantity >= ?
                """, (item['qty'], item['id'], item['qty']))
                
                if cur.rowcount == 0:
                    raise ValueError(f"Insufficient stock for item: {item['name']}")
            
            logger.info(f"Checkout complete: Transaction #{txn_id}, Total: ${total:.2f}")
            return txn_id
    
    def get_all_transactions(self) -> List[Dict[str, Any]]:
        """
        Get all transactions with item counts.
        
        Returns:
            List of transaction summaries ordered by newest first.
        """
        with get_connection() as (conn, cur):
            cur.execute("""
                SELECT 
                    t.id,
                    COUNT(ti.id) as item_count,
                    t.total_amount,
                    t.created_at
                FROM transactions t
                LEFT JOIN transaction_items ti ON ti.transaction_id = t.id
                GROUP BY t.id
                ORDER BY t.id DESC
            """)
            return [
                {
                    'id': row[0],
                    'item_count': row[1],
                    'total_amount': float(row[2]),
                    'created_at': row[3]
                }
                for row in cur.fetchall()
            ]
    
    def get_transaction_details(self, txn_id: int) -> List[Dict[str, Any]]:
        """
        Get line items for a specific transaction.
        
        Args:
            txn_id: Transaction ID.
            
        Returns:
            List of transaction items with product details.
        """
        with get_connection() as (conn, cur):
            cur.execute("""
                SELECT 
                    ti.item_id, 
                    i.name, 
                    ti.quantity, 
                    ti.unit_price, 
                    ti.subtotal,
                    COALESCE(ti.note, '') AS note
                FROM transaction_items ti
                LEFT JOIN inventory_items i ON i.id = ti.item_id
                WHERE ti.transaction_id = ?
                ORDER BY ti.id ASC
            """, (txn_id,))
            return [
                {
                    'item_id': row[0],
                    'name': row[1] or 'Unknown',
                    'quantity': row[2],
                    'unit_price': float(row[3]),
                    'subtotal': float(row[4]),
                    'note': row[5],
                }
                for row in cur.fetchall()
            ]
    
    def delete_transaction(
        self, 
        txn_id: int, 
        restore_inventory: bool = False
    ) -> Tuple[bool, int]:
        """
        Delete a transaction, optionally restoring inventory.
        
        Args:
            txn_id: Transaction ID to delete.
            restore_inventory: If True, add quantities back to inventory.
            
        Returns:
            Tuple of (success, items_restored_count).
        """
        with transaction() as (conn, cur):
            restored_count = 0
            
            if restore_inventory:
                # Get items to restore
                cur.execute("""
                    SELECT item_id, quantity 
                    FROM transaction_items 
                    WHERE transaction_id = ?
                """, (txn_id,))
                items = cur.fetchall()
                
                for item_id, qty in items:
                    cur.execute("""
                        UPDATE inventory_items 
                        SET quantity = quantity + ? 
                        WHERE id = ?
                    """, (qty, item_id))
                    restored_count += 1
            
            # Delete transaction items first (foreign key)
            cur.execute(
                "DELETE FROM transaction_items WHERE transaction_id = ?", 
                (txn_id,)
            )
            
            # Delete transaction
            cur.execute("DELETE FROM transactions WHERE id = ?", (txn_id,))
            deleted = cur.rowcount > 0
            
            if deleted:
                logger.info(
                    f"Deleted transaction #{txn_id}" + 
                    (f", restored {restored_count} items" if restore_inventory else "")
                )
            
            return deleted, restored_count
    
    def clear_all_transactions(
        self, 
        restore_inventory: bool = False
    ) -> Tuple[int, int]:
        """
        Delete all transactions.
        
        Args:
            restore_inventory: If True, restore all inventory quantities.
            
        Returns:
            Tuple of (transactions_deleted, items_restored).
        """
        with transaction() as (conn, cur):
            restored_count = 0
            
            if restore_inventory:
                cur.execute("""
                    SELECT item_id, SUM(quantity) as total_qty
                    FROM transaction_items
                    GROUP BY item_id
                """)
                for item_id, total_qty in cur.fetchall():
                    cur.execute("""
                        UPDATE inventory_items 
                        SET quantity = quantity + ? 
                        WHERE id = ?
                    """, (total_qty, item_id))
                    restored_count += 1
            
            # Get count before delete
            cur.execute("SELECT COUNT(*) FROM transactions")
            txn_count = cur.fetchone()[0]
            
            # Delete all
            cur.execute("DELETE FROM transaction_items")
            cur.execute("DELETE FROM transactions")
            
            logger.info(
                f"Cleared {txn_count} transactions" +
                (f", restored {restored_count} item types" if restore_inventory else "")
            )
            
            return txn_count, restored_count
    
    def get_transaction_count(self) -> int:
        """Get total number of transactions."""
        with get_connection() as (conn, cur):
            cur.execute("SELECT COUNT(*) FROM transactions")
            return cur.fetchone()[0]
