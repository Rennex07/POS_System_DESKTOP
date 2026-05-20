import os
import sys
import signal
import threading
import logging
import atexit

logger = logging.getLogger(__name__)

try:
    import ctypes
    from ctypes import wintypes
    HAS_CTYPES = True
except ImportError:
    HAS_CTYPES = False

from . import database as db


def cleanup(exit_code=None):
    logger.debug("Starting cleanup...")
    try:
        if hasattr(db, 'cursor') and db.cursor is not None:
            try:
                db.cursor.close()
                logger.debug("Database cursor closed")
            except Exception as e:
                logger.debug(f"Error closing cursor: {e}")
        
        if hasattr(db, 'conn') and db.conn is not None:
            try:
                db.conn.close()
                logger.info("Database connection closed")
            except Exception as e:
                logger.debug(f"Error closing connection: {e}")
                
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")

    if exit_code is not None and threading.current_thread() is threading.main_thread():
        try:
            sys.exit(exit_code)
        except SystemExit:
            os._exit(exit_code)


def setup():
    if HAS_CTYPES and sys.platform == 'win32':
        try:
            kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
            SetConsoleCtrlHandler = kernel32.SetConsoleCtrlHandler
            SetConsoleCtrlHandler.argtypes = (ctypes.c_void_p, wintypes.BOOL)
            SetConsoleCtrlHandler.restype = wintypes.BOOL

            @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
            def console_ctrl_handler(ctrl_type):
                if ctrl_type == 0:
                    cleanup()
                    return True
                return False

            SetConsoleCtrlHandler(console_ctrl_handler, True)
            logger.debug("Windows console handler registered")

        except Exception as e:
            logger.warning(f"Could not set up Windows close handler: {e}")

    def signal_handler(sig, frame):
        logger.debug(f"Received signal {sig}")
        cleanup()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    atexit.register(cleanup)
    logger.debug("Lifecycle handlers registered")
