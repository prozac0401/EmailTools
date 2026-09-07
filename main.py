"""The single Python entry point, also usable with Windows Embedded Python."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    old_argv = sys.argv
    try:
        if args and args[0] in {"--legacy-attachments", "--legacy-tables"}:
            if args[0] == "--legacy-attachments":
                from emailtools.compat.attachments import main as launch
            else:
                from emailtools.compat.tables import main as launch
            args.pop(0)
        elif "--cli" in args:
            args.remove("--cli")
            from emailtools.cli import main as launch
        elif args == ["--version"]:
            from emailtools import __version__
            print(f"EmailTools {__version__}")
            return 0
        else:
            from emailtools.ui.server import main as launch
        sys.argv = [str(ROOT / "main.py"), *args]
        return launch()
    finally:
        sys.argv = old_argv


if __name__ == "__main__":
    raise SystemExit(main())
