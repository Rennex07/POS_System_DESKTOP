import logging
from . import database as db

logger = logging.getLogger(__name__)


def setup_products_table():
    if db.conn is None or db.cursor is None:
        db.connect()
    conn, cursor = db.conn, db.cursor
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            stock INTEGER NOT NULL DEFAULT 0,
            category TEXT NOT NULL CHECK (category IN ('Coffee', 'Pastry'))
        )
        """
    )
    conn.commit()
    logger.info("products table ensured")


def ensure_inventory_table():
    if db.conn is None or db.cursor is None:
        db.connect()
    conn, cursor = db.conn, db.cursor
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price REAL NOT NULL CHECK (price >= 0),
            quantity INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
            category TEXT NOT NULL DEFAULT 'Mains' 
                CHECK (category IN ('Appetizers', 'Mains', 'Desserts', 'Drinks', 'Casual')),
            image BLOB,
            has_custom_options INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    conn.commit()
    logger.info("inventory_items table ensured")

    try:
        cursor.execute("PRAGMA table_info(inventory_items)")
        columns = [row[1] for row in cursor.fetchall()]
        if 'image' not in columns:
            cursor.execute("ALTER TABLE inventory_items ADD COLUMN image BLOB")
            conn.commit()
            logger.info("Added 'image' column to inventory_items")
        if 'has_custom_options' not in columns and 'has_sugar_level' not in columns:
            cursor.execute("ALTER TABLE inventory_items ADD COLUMN has_custom_options INTEGER NOT NULL DEFAULT 0")
            conn.commit()
            logger.info("Added 'has_custom_options' column to inventory_items")
        elif 'has_sugar_level' in columns and 'has_custom_options' not in columns:
            cursor.execute("ALTER TABLE inventory_items RENAME COLUMN has_sugar_level TO has_custom_options")
            conn.commit()
            logger.info("Renamed 'has_sugar_level' to 'has_custom_options' in inventory_items")
    except Exception as e:
        logger.warning(f"Migration check for inventory_items columns failed: {e}")


def ensure_transactions_tables():
    if db.conn is None or db.cursor is None:
        db.connect()
    conn, cursor = db.conn, db.cursor
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            total_amount REAL NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS transaction_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_id INTEGER NOT NULL,
            item_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL CHECK (quantity >= 0),
            unit_price REAL NOT NULL,
            subtotal REAL NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (transaction_id) REFERENCES transactions(id) ON DELETE CASCADE,
            FOREIGN KEY (item_id) REFERENCES inventory_items(id) ON UPDATE CASCADE
        )
        """
    )
    conn.commit()
    logger.info("transactions and transaction_items tables ensured")


if __name__ == "__main__":
    db.connect()
    setup_products_table()
    ensure_inventory_table()
    ensure_transactions_tables()
    print("All tables are ready!")
