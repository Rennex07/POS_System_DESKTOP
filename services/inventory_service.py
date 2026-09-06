import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from datetime import datetime

from database.database import get_connection, transaction

logger = logging.getLogger(__name__)


@dataclass
class InventoryItem:
    """Data class representing an inventory item."""
    id: int
    name: str
    price: float
    quantity: int
    category: str
    image: Optional[bytes] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    
    @classmethod
    def from_row(cls, row) -> 'InventoryItem':
        """Create InventoryItem from database row."""
        return cls(
            id=row['id'],
            name=row['name'],
            price=float(row['price']),
            quantity=int(row['quantity']),
            category=row['category'] or 'Mains',
            image=row['image'] if 'image' in row.keys() else None,
            created_at=str(row['created_at']) if row['created_at'] else None,
            updated_at=str(row['updated_at']) if row['updated_at'] else None,
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for UI consumption."""
        return {
            'id': self.id,
            'name': self.name,
            'price': self.price,
            'quantity': self.quantity,
            'category': self.category,
            'image': self.image,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }


class InventoryService:
    """
    Service class for inventory operations.
    
    Provides a clean API for inventory CRUD operations,
    with proper error handling and logging.
    
    Example:
        service = InventoryService()
        items = service.get_all_items()
        new_id = service.create_item("Coffee", 4.99, 100, "Drinks")
    """
    
    def get_all_items(self) -> List[Dict[str, Any]]:
        """
        Fetch all inventory items.
        
        Returns:
            List of item dictionaries ordered by ID descending.
        """
        with get_connection() as (conn, cur):
            cur.execute("""
                SELECT id, name, price, quantity, image, category, created_at, updated_at 
                FROM inventory_items 
                ORDER BY id DESC
            """)
            rows = cur.fetchall()
            return [dict(row) for row in rows]
    
    def get_item_by_id(self, item_id: int) -> Optional[Dict[str, Any]]:
        """
        Fetch a single item by ID.
        
        Args:
            item_id: The item's database ID.
            
        Returns:
            Item dictionary or None if not found.
        """
        with get_connection() as (conn, cur):
            cur.execute("""
                SELECT id, name, price, quantity, image, category, created_at, updated_at 
                FROM inventory_items 
                WHERE id = ?
            """, (item_id,))
            row = cur.fetchone()
            return dict(row) if row else None
    
    def get_categories(self) -> List[str]:
        """
        Get all unique categories from inventory.
        
        Returns:
            List of category names, sorted alphabetically.
        """
        with get_connection() as (conn, cur):
            cur.execute("""
                SELECT DISTINCT category 
                FROM inventory_items 
                WHERE category IS NOT NULL AND category != '' 
                ORDER BY category
            """)
            return [row[0] for row in cur.fetchall()]
    
    def get_low_stock_items(self, threshold: int = 10) -> List[Dict[str, Any]]:
        """
        Get items with quantity below threshold.
        
        Args:
            threshold: Quantity threshold (default 10).
            
        Returns:
            List of low-stock items ordered by quantity ascending.
        """
        with get_connection() as (conn, cur):
            cur.execute("""
                SELECT id, name, price, quantity, category 
                FROM inventory_items 
                WHERE quantity < ? 
                ORDER BY quantity ASC
            """, (threshold,))
            return [dict(row) for row in cur.fetchall()]
    
    def create_item(
        self, 
        name: str, 
        price: float, 
        quantity: int, 
        category: str = "Mains",
        image_bytes: Optional[bytes] = None
    ) -> int:
        """
        Create a new inventory item.
        
        Args:
            name: Item name.
            price: Item price (must be >= 0).
            quantity: Initial quantity (must be >= 0).
            category: Item category.
            image_bytes: Optional image data.
            
        Returns:
            The new item's ID.
            
        Raises:
            ValueError: If name is empty or price/quantity negative.
        """
        if not name or not name.strip():
            raise ValueError("Item name is required")
        if price < 0:
            raise ValueError("Price cannot be negative")
        if quantity < 0:
            raise ValueError("Quantity cannot be negative")
        
        with transaction() as (conn, cur):
            cur.execute("""
                INSERT INTO inventory_items (name, price, quantity, image, category) 
                VALUES (?, ?, ?, ?, ?)
            """, (name.strip(), price, quantity, image_bytes, category))
            new_id = cur.lastrowid
            logger.info(f"Created inventory item: {name} (ID: {new_id})")
            return new_id
    
    def update_item(
        self,
        item_id: int,
        name: str,
        price: float,
        quantity: int,
        category: str,
        image_bytes: Optional[bytes] = None
    ) -> bool:
        """
        Update an existing inventory item.
        
        Args:
            item_id: ID of item to update.
            name: New name.
            price: New price.
            quantity: New quantity.
            category: New category.
            image_bytes: New image (None keeps existing).
            
        Returns:
            True if item was updated, False if not found.
        """
        if not name or not name.strip():
            raise ValueError("Item name is required")
        if price < 0:
            raise ValueError("Price cannot be negative")
        if quantity < 0:
            raise ValueError("Quantity cannot be negative")
        
        with transaction() as (conn, cur):
            if image_bytes is not None:
                cur.execute("""
                    UPDATE inventory_items 
                    SET name=?, price=?, quantity=?, image=?, category=? 
                    WHERE id=?
                """, (name.strip(), price, quantity, image_bytes, category, item_id))
            else:
                cur.execute("""
                    UPDATE inventory_items 
                    SET name=?, price=?, quantity=?, category=? 
                    WHERE id=?
                """, (name.strip(), price, quantity, category, item_id))
            
            updated = cur.rowcount > 0
            if updated:
                logger.info(f"Updated inventory item ID: {item_id}")
            return updated
    
    def delete_item(self, item_id: int) -> bool:
        """
        Delete an inventory item.
        
        Args:
            item_id: ID of item to delete.
            
        Returns:
            True if item was deleted, False if not found.
        """
        with transaction() as (conn, cur):
            cur.execute("DELETE FROM inventory_items WHERE id=?", (item_id,))
            deleted = cur.rowcount > 0
            if deleted:
                logger.info(f"Deleted inventory item ID: {item_id}")
            return deleted
    
    def update_quantity(self, item_id: int, delta: int) -> bool:
        """
        Adjust item quantity by a delta value.
        
        Args:
            item_id: ID of item to update.
            delta: Amount to add (positive) or subtract (negative).
            
        Returns:
            True if successful, False if item not found or would go negative.
        """
        with transaction() as (conn, cur):
            # Check current quantity first
            cur.execute("SELECT quantity FROM inventory_items WHERE id=?", (item_id,))
            row = cur.fetchone()
            if not row:
                return False
            
            new_qty = row['quantity'] + delta
            if new_qty < 0:
                raise ValueError(f"Insufficient stock. Current: {row['quantity']}, requested: {-delta}")
            
            cur.execute(
                "UPDATE inventory_items SET quantity = ? WHERE id = ?",
                (new_qty, item_id)
            )
            logger.debug(f"Updated quantity for item {item_id}: {row['quantity']} -> {new_qty}")
            return True
    
    def get_inventory_value(self) -> float:
        """
        Calculate total inventory value (sum of price * quantity).
        
        Returns:
            Total inventory value.
        """
        with get_connection() as (conn, cur):
            cur.execute("SELECT COALESCE(SUM(price * quantity), 0) FROM inventory_items")
            return float(cur.fetchone()[0])
