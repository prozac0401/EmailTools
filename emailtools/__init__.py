"""Shared application package and bundled dependency path."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIR = ROOT / "vendor"
if str(VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(VENDOR_DIR))
DESKTOP_DIR = ROOT / "runtime" / "desktop"
if DESKTOP_DIR.is_dir() and str(DESKTOP_DIR) not in sys.path:
    sys.path.insert(0, str(DESKTOP_DIR))
__version__ = "2.1.1"
