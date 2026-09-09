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
        elif "--web" in args or "--no-browser" in args:
            if "--web" in args:
                args.remove("--web")
            from emailtools.ui.server import main as launch
        else:
            from emailtools.desktop.app import main as launch
        sys.argv = [str(ROOT / "main.py"), *args]
        return launch()
    finally:
        sys.argv = old_argv


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        import traceback
        import tempfile
        error = traceback.format_exc()
        log = Path(tempfile.gettempdir()) / "EmailTools-startup.log"
        log.write_text(error, encoding="utf-8")
        if sys.stderr is not None:
            print(error, file=sys.stderr)
        elif sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,
                f"프로그램을 시작하지 못했습니다. setup_desktop.bat을 실행한 뒤 다시 시도해 주세요.\n\n오류 기록: {log}",
                "EmailTools", 0x10)
        raise SystemExit(1)
