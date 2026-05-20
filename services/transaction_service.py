import logging
from typing import List, Dict
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class CartItem:
    name: str
    qty: int
    price: float


class TransactionService:
    def checkout(self, cart_items: List[Dict]) -> int:
        try:
            from database.database import get_connection, transaction
            
            total_amount = sum(item["qty"] * item["price"] for item in cart_items)
            
            with transaction() as (conn, cur):
                cur.execute(
                    "INSERT INTO transactions (total_amount) VALUES (?)",
                    (total_amount,)
                )
                txn_id = cur.lastrowid
                
                for item in cart_items:
                    cur.execute(
                        """INSERT INTO transaction_items 
                           (transaction_id, item_id, quantity, unit_price, subtotal)
                           VALUES (?, ?, ?, ?, ?)""",
                        (
                            txn_id,
                            item.get("id"),
                            item["qty"],
                            item["price"],
                            item["qty"] * item["price"]
                        )
                    )
                    
                    cur.execute(
                        "UPDATE inventory_items SET quantity = quantity - ? WHERE id = ?",
                        (item["qty"], item.get("id"))
                    )
            
            logger.info(f"Transaction {txn_id} completed with total ${total_amount:.2f}")
            return txn_id
            
        except Exception as e:
            logger.error(f"Checkout failed: {e}")
            raise
