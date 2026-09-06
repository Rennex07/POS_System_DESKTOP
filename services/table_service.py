import logging
from typing import Any, Dict, List

from database.database import get_connection, transaction
from database.database_setup import ensure_table_management_tables, ensure_transactions_tables

logger = logging.getLogger(__name__)


class TableService:
    def __init__(self):
        ensure_transactions_tables()
        ensure_table_management_tables()

    def list_tables(self) -> List[Dict[str, Any]]:
        with get_connection() as (conn, cur):
            cur.execute(
                """
                SELECT
                    dt.id,
                    dt.table_number,
                    COALESCE(dt.label, '') AS label,
                    oo.id AS open_order_id,
                    oo.created_at AS open_started_at,
                    oo.updated_at,
                    COALESCE(SUM(ooi.quantity), 0) AS item_count,
                    COALESCE(SUM(ooi.quantity * ooi.unit_price), 0) AS total_amount
                FROM dining_tables dt
                LEFT JOIN open_orders oo ON oo.table_id = dt.id AND oo.status = 'open'
                LEFT JOIN open_order_items ooi ON ooi.open_order_id = oo.id
                GROUP BY dt.id, dt.table_number, dt.label, oo.id, oo.updated_at
                ORDER BY CAST(dt.table_number AS INTEGER), dt.table_number
                """
            )
            return [dict(row) for row in cur.fetchall()]

    def create_table(self, table_number: str, label: str = "") -> int:
        table_number = table_number.strip()
        label = label.strip()
        if not table_number:
            raise ValueError("Table number is required.")

        with transaction() as (conn, cur):
            cur.execute(
                """
                INSERT INTO dining_tables (table_number, label, updated_at)
                VALUES (?, ?, datetime('now'))
                """,
                (table_number, label),
            )
            return int(cur.lastrowid)

    def update_table(self, table_id: int, table_number: str, label: str = "") -> None:
        table_number = table_number.strip()
        label = label.strip()
        if not table_number:
            raise ValueError("Table number is required.")

        with transaction() as (conn, cur):
            cur.execute(
                """
                UPDATE dining_tables
                SET table_number = ?, label = ?, updated_at = datetime('now')
                WHERE id = ?
                """,
                (table_number, label, table_id),
            )

    def delete_table(self, table_id: int) -> None:
        with transaction() as (conn, cur):
            cur.execute(
                """
                SELECT COUNT(*)
                FROM open_orders oo
                JOIN open_order_items ooi ON ooi.open_order_id = oo.id
                WHERE oo.table_id = ? AND oo.status = 'open'
                """,
                (table_id,),
            )
            if int(cur.fetchone()[0] or 0) > 0:
                raise ValueError("This table has an open order. Checkout or clear it before deleting.")
            cur.execute("DELETE FROM open_orders WHERE table_id = ?", (table_id,))
            cur.execute("DELETE FROM dining_tables WHERE id = ?", (table_id,))

    def load_open_order_cart(self, table_id: int) -> Dict[str, Dict[str, Any]]:
        with get_connection() as (conn, cur):
            cur.execute(
                """
                SELECT
                    ooi.cart_key,
                    ooi.item_id,
                    ooi.display_name,
                    ooi.quantity,
                    ooi.unit_price,
                    ooi.sugar_level,
                    ooi.ice_level,
                    ooi.size,
                    COALESCE(ooi.note, '') AS note
                FROM open_orders oo
                JOIN open_order_items ooi ON ooi.open_order_id = oo.id
                WHERE oo.table_id = ? AND oo.status = 'open'
                ORDER BY ooi.id ASC
                """,
                (table_id,),
            )
            cart: Dict[str, Dict[str, Any]] = {}
            for row in cur.fetchall():
                cart[row["cart_key"]] = {
                    "id": row["item_id"],
                    "name": row["display_name"],
                    "price": float(row["unit_price"]),
                    "qty": int(row["quantity"]),
                    "sugar_level": row["sugar_level"],
                    "ice_level": row["ice_level"],
                    "size": row["size"],
                    "note": row["note"],
                }
            return cart

    def save_open_order_cart(self, table_id: int, cart: Dict[str, Dict[str, Any]]) -> None:
        with transaction() as (conn, cur):
            if not cart:
                cur.execute("SELECT id FROM open_orders WHERE table_id = ? AND status = 'open'", (table_id,))
                row = cur.fetchone()
                if row:
                    cur.execute("DELETE FROM open_order_items WHERE open_order_id = ?", (row["id"],))
                    cur.execute("DELETE FROM open_orders WHERE id = ?", (row["id"],))
                return

            cur.execute("SELECT id FROM open_orders WHERE table_id = ? AND status = 'open'", (table_id,))
            row = cur.fetchone()
            if row:
                open_order_id = int(row["id"])
                cur.execute("DELETE FROM open_order_items WHERE open_order_id = ?", (open_order_id,))
                cur.execute("UPDATE open_orders SET updated_at = datetime('now') WHERE id = ?", (open_order_id,))
            else:
                cur.execute(
                    "INSERT INTO open_orders (table_id, updated_at) VALUES (?, datetime('now'))",
                    (table_id,),
                )
                open_order_id = int(cur.lastrowid)

            for cart_key, item in cart.items():
                cur.execute(
                    """
                    INSERT INTO open_order_items
                    (open_order_id, cart_key, item_id, display_name, quantity, unit_price, sugar_level, ice_level, size, note)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        open_order_id,
                        cart_key,
                        item["id"],
                        item["name"],
                        item["qty"],
                        item["price"],
                        item.get("sugar_level"),
                        item.get("ice_level"),
                        item.get("size"),
                        item.get("note", ""),
                    ),
                )

    def move_open_order(self, source_table_id: int, target_table_id: int) -> None:
        if source_table_id == target_table_id:
            raise ValueError("Select a different table to move this order.")

        with transaction() as (conn, cur):
            cur.execute(
                """
                SELECT id
                FROM open_orders
                WHERE table_id = ? AND status = 'open'
                """,
                (source_table_id,),
            )
            source_order = cur.fetchone()
            if not source_order:
                raise ValueError("The selected table does not have an open order.")

            cur.execute(
                """
                SELECT id
                FROM open_orders
                WHERE table_id = ? AND status = 'open'
                """,
                (target_table_id,),
            )
            target_order = cur.fetchone()
            if target_order:
                raise ValueError("The destination table already has an open order.")

            cur.execute("SELECT 1 FROM dining_tables WHERE id = ?", (target_table_id,))
            if not cur.fetchone():
                raise ValueError("The destination table no longer exists.")

            cur.execute(
                """
                UPDATE open_orders
                SET table_id = ?, updated_at = datetime('now')
                WHERE id = ?
                """,
                (target_table_id, source_order["id"]),
            )

    def checkout_table(
        self,
        table_id: int,
        cart_items: List[Dict[str, Any]],
        final_total: float | None = None,
        discount_amount: float = 0.0,
        vat_amount: float = 0.0,
    ) -> int:
        if not cart_items:
            raise ValueError("Cart is empty")

        subtotal = sum(item["qty"] * item["price"] for item in cart_items)
        total = float(final_total if final_total is not None else subtotal)

        with transaction() as (conn, cur):
            cur.execute("SELECT table_number FROM dining_tables WHERE id = ?", (table_id,))
            table = cur.fetchone()
            if not table:
                raise ValueError("Table not found.")
            table_number = table["table_number"]

            cur.execute(
                """
                INSERT INTO transactions
                (subtotal_amount, discount_amount, vat_amount, total_amount, table_id, table_number)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (subtotal, discount_amount, vat_amount, total, table_id, table_number),
            )
            txn_id = int(cur.lastrowid)

            for item in cart_items:
                subtotal = item["qty"] * item["price"]
                cur.execute(
                    """
                    INSERT INTO transaction_items
                    (transaction_id, item_id, quantity, unit_price, subtotal, note)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (txn_id, item["id"], item["qty"], item["price"], subtotal, item.get("note", "")),
                )
                cur.execute(
                    """
                    UPDATE inventory_items
                    SET quantity = quantity - ?
                    WHERE id = ? AND quantity >= ?
                    """,
                    (item["qty"], item["id"], item["qty"]),
                )
                if cur.rowcount == 0:
                    raise ValueError(f"Insufficient stock for item: {item['name']}")

            cur.execute("SELECT id FROM open_orders WHERE table_id = ? AND status = 'open'", (table_id,))
            open_order = cur.fetchone()
            if open_order:
                cur.execute("DELETE FROM open_order_items WHERE open_order_id = ?", (open_order["id"],))
                cur.execute("DELETE FROM open_orders WHERE id = ?", (open_order["id"],))

            logger.info("Checked out table %s as transaction #%s", table_number, txn_id)
            return txn_id
