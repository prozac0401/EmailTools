"""Compatibility entry point; implementation lives in emailtools.ui.server."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from emailtools.ui.server import *

if __name__ == "__main__":
    raise SystemExit(main())
