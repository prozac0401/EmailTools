"""Prepare verified Qt wheels without pip or a system Python installation."""
from __future__ import annotations
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    lock = json.loads((ROOT / "requirements-desktop.lock.json").read_text(encoding="utf-8"))
    runtime = ROOT / "runtime"
    target = runtime / "desktop"
    marker = target / ".emailtools-qt.json"
    if marker.exists() and json.loads(marker.read_text()) == lock:
        print("[OK] Desktop runtime already prepared.")
        return 0
    guard = runtime / ".desktop-setup-lock"
    guard.mkdir()  # Exclusive ownership; never race another setup.
    try:
        with tempfile.TemporaryDirectory(prefix=".desktop-setup-", dir=runtime) as temporary:
            work = Path(temporary)
            stage = work / "desktop"
            stage.mkdir()
            for wheel in lock["wheels"]:
                local = ROOT / "runtime" / "wheels" / wheel["name"]
                archive = work / wheel["name"]
                if local.exists():
                    shutil.copyfile(local, archive)
                else:
                    print(f"[Download] {wheel['name']}", flush=True)
                    with urllib.request.urlopen(wheel["url"], timeout=60) as response, archive.open("wb") as out:
                        shutil.copyfileobj(response, out)
                if hashlib.sha256(archive.read_bytes()).hexdigest() != wheel["sha256"]:
                    raise ValueError(f"SHA256 mismatch: {wheel['name']}")
                with zipfile.ZipFile(archive) as package:
                    for entry in package.infolist():
                        if not (stage / entry.filename).resolve().is_relative_to(stage.resolve()):
                            raise ValueError("Unsafe wheel path")
                    package.extractall(stage)
            subprocess.run([sys.executable, "-I", "-c",
                "import sys; sys.path.insert(0,sys.argv[1]); from PySide6.QtWidgets import QApplication; "
                "a=QApplication([]); print('[OK] Qt',a.platformName())", str(stage)],
                check=True, env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
            (stage / marker.name).write_text(json.dumps(lock), encoding="utf-8")
            backup = work / "previous"
            if target.exists():
                target.rename(backup)
            try:
                stage.rename(target)
            except BaseException:
                if backup.exists():
                    backup.rename(target)
                raise
        print("[OK] Desktop runtime ready.")
        return 0
    finally:
        guard.rmdir()


if __name__ == "__main__":
    raise SystemExit(main())
