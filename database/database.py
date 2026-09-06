import sqlite3
import threading
import os
import sys
import logging
from contextlib import contextmanager
from typing import Optional, Tuple, Generator, Any

logger = logging.getLogger(__name__)

DB_FILE = "storage.db"

conn: Optional[sqlite3.Connection] = None
cursor: Optional[sqlite3.Cursor] = None
_lock = threading.Lock()


def get_db_search_paths() -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    bases = []
    if sys.argv:
        bases.append(os.path.dirname(os.path.abspath(sys.argv[0])))
    bases.append(os.getcwd())
    bases.append(os.path.dirname(os.path.dirname(__file__)))

    for base in bases:
        if not base:
            continue
        candidate = os.path.abspath(os.path.join(base, DB_FILE))
        normalized = os.path.normcase(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        candidates.append(candidate)

    return candidates


def get_db_path() -> str:
    candidates = get_db_search_paths()
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    if candidates:
        return candidates[0]
    return os.path.abspath(DB_FILE)


def get_pooled_connection() -> sqlite3.Connection:
    db_path = get_db_path()
    connection = sqlite3.connect(db_path, check_same_thread=False, timeout=30.0)
    connection.row_factory = sqlite3.Row
    return connection


@contextmanager
def get_connection() -> Generator[Tuple[sqlite3.Connection, sqlite3.Cursor], None, None]:
    connection = None
    cur = None
    try:
        connection = get_pooled_connection()
        cur = connection.cursor()
        cur.execute("PRAGMA foreign_keys = ON")
        yield connection, cur
    except sqlite3.Error as e:
        if connection:
            try:
                connection.rollback()
            except Exception as rollback_err:
                logger.debug(f"Rollback failed: {rollback_err}")
        raise
    finally:
        if cur:
            try:
                cur.close()
            except Exception as e:
                logger.debug(f"Cursor close failed: {e}")
        if connection:
            try:
                connection.close()
            except Exception as e:
                logger.debug(f"Connection close failed: {e}")


@contextmanager  
def transaction() -> Generator[Tuple[sqlite3.Connection, sqlite3.Cursor], None, None]:
    connection = None
    cur = None
    try:
        connection = get_pooled_connection()
        cur = connection.cursor()
        cur.execute("PRAGMA foreign_keys = ON")
        yield connection, cur
        connection.commit()
    except Exception as e:
        if connection:
            try:
                connection.rollback()
            except Exception as rollback_err:
                logger.debug(f"Rollback failed: {rollback_err}")
        raise
    finally:
        if cur:
            try:
                cur.close()
            except Exception as e:
                logger.debug(f"Cursor close failed: {e}")
        if connection:
            try:
                connection.close()
            except Exception as e:
                logger.debug(f"Connection close failed: {e}")


def connect() -> Tuple[sqlite3.Connection, sqlite3.Cursor]:
    global conn, cursor
    
    with _lock:
        try:
            db_path = get_db_path()
            
            if not os.path.exists(db_path):
                searched_paths = "\n".join(f"- {path}" for path in get_db_search_paths())
                raise FileNotFoundError(
                    f"Database file not found: {db_path}\n\n"
                    f"Searched locations:\n{searched_paths}\n\n"
                    "Please ensure storage.db exists next to the executable or in the project root."
                )
            
            conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30.0)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute("PRAGMA journal_mode = DELETE")
            
            logger.info(f"Database connected: {db_path}")
            return conn, cursor
            
        except Exception as err:
            logger.error(f"Database connection failed: {err}")
            raise ConnectionError(f"Database connection failed: {str(err)}")


def ensure_connection() -> None:
    global conn, cursor
    with _lock:
        try:
            if conn is None:
                connect()
            else:
                cursor.execute("SELECT 1")
        except Exception as e:
            logger.debug(f"Connection test failed, reconnecting: {e}")
            try:
                connect()
            except Exception as reconnect_err:
                logger.warning(f"Reconnect failed: {reconnect_err}")


def get_setting(key: str, default: str = "") -> str:
    try:
        with get_connection() as (conn, cur):
            cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cur.fetchone()
            return row[0] if row else default
    except Exception as e:
        msg = str(e).lower()
        if "no such table: settings" in msg:
            ensure_settings = None
            try:
                from .database_setup import ensure_settings_table as _ensure_settings
                ensure_settings = _ensure_settings
            except Exception:
                try:
                    from database_setup import ensure_settings_table as _ensure_settings
                    ensure_settings = _ensure_settings
                except Exception:
                    ensure_settings = None
            if ensure_settings is not None:
                try:
                    ensure_settings()
                except Exception as create_err:
                    logger.warning(f"Failed to create settings table: {create_err}")
            return default
        logger.warning(f"Failed to get setting '{key}': {e}")
        return default


def set_setting(key: str, value: str) -> bool:
    try:
        with transaction() as (conn, cur):
            cur.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, str(value))
            )
        return True
    except Exception as e:
        logger.error(f"Failed to set setting '{key}': {e}")
        return False


def get_exchange_rate() -> int:
    return int(get_setting("exchange_rate", "4100"))


def set_exchange_rate(rate: int) -> bool:
    return set_setting("exchange_rate", str(rate))


def execute_with_retry(query, params=None, retries=3):
    global conn, cursor
    
    if params is None:
        params = ()
        
    for attempt in range(retries):
        try:
            ensure_connection()
            cursor.execute(query, params)
            return cursor
        except sqlite3.Error as e:
            error_msg = f"SQLite Error: {str(e)}"
            
            if conn:
                try:
                    conn.rollback()
                except Exception as rollback_err:
                    logger.debug(f"Rollback failed: {rollback_err}")
            
            if attempt == retries - 1:
                raise Exception(f"Failed after {retries} attempts. {error_msg}")
            
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except Exception as rollback_err:
                    logger.debug(f"Rollback failed: {rollback_err}")
            raise Exception(f"Unexpected error: {str(e)}")
