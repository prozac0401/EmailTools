"""Compatibility entry point; implementation lives in emailtools.compat.attachments."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from emailtools.compat.attachments import *

if __name__ == "__main__":
    raise SystemExit(main())
