"""Build and smoke-test an offline Windows distribution from the unified tree."""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from emailtools import __version__
from emailtools.ui.server import create_demo

INCLUDE = ("run.bat", "main.py", "setup_runtime.bat", "requirements.txt", "README.md",
           "runtime/python", "vendor", "THIRD_PARTY_LICENSES", "emailtools", "docs", "tests",
           "tools/build_portable.py", "eml_attachment_tool", "eml_table_to_excel")


def files_to_package() -> list[Path]:
    selected = set()
    for relative in INCLUDE:
        path = ROOT / relative
        if not path.exists():
            raise FileNotFoundError(f"배포에 필요한 파일/폴더가 없습니다: {relative}")
        candidates = [path] if path.is_file() else path.rglob("*")
        for file in candidates:
            if file.is_file() and not file.is_symlink() and "__pycache__" not in file.parts and file.suffix != ".pyc":
                # Never package an old backup runtime or old vendor copies.
                parts = file.relative_to(ROOT).parts
                if parts[0] in {"eml_attachment_tool", "eml_table_to_excel"} and len(parts) > 2:
                    continue
                selected.add(file)
    return sorted(selected, key=lambda p: p.relative_to(ROOT).as_posix())


def verify_package(archive_path: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="EmailTools_package_test_") as temp:
        temporary = Path(temp)
        with zipfile.ZipFile(archive_path) as archive:
            if archive.testzip() is not None:
                raise RuntimeError("ZIP 무결성 검사 실패")
            for item in archive.infolist():
                if not (temporary / item.filename).resolve().is_relative_to(temporary.resolve()):
                    raise RuntimeError("ZIP 경로 검사 실패")
            archive.extractall(temporary)
        program = temporary / "EmailTools"
        source = temporary / "sample"
        source.mkdir()
        create_demo(source)
        output = temporary / "results"
        command = f'cmd.exe /d /c call "{program / "run.bat"}" --cli "{source}" --all --output "{output}"'
        result = subprocess.run(command, cwd=temporary, env={**os.environ, "EMAILTOOLS_NO_PAUSE": "1"},
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise RuntimeError(f"배포본 BAT 실행 검사 실패:\n{result.stdout}\n{result.stderr}")
        job, = output.iterdir()
        if (len(list(job.rglob("mail.txt"))) != 3 or len(list(job.glob("mails/*/attachments/*.docx"))) != 2
                or len(list(job.glob("mails/*/text/*.txt"))) != 2
                or not (job / "tables/EML_Table_Result.xlsx").is_file()):
            raise RuntimeError("배포본 결과 구성 검사 실패")


def main() -> int:
    if os.name != "nt":
        raise RuntimeError("Windows에서 배포본을 생성하고 BAT 실행을 검증해 주세요.")
    if not (ROOT / "runtime/python/python.exe").is_file():
        raise FileNotFoundError("먼저 setup_runtime.bat으로 내장 Python을 준비해 주세요.")
    output = ROOT / "packages" / f"EmailTools_v{__version__}_portable.zip"
    output.parent.mkdir(exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".EmailTools_", suffix=".zip", dir=output.parent)
    os.close(descriptor)
    staging = Path(name)
    try:
        files = files_to_package()
        with zipfile.ZipFile(staging, "w", zipfile.ZIP_DEFLATED) as archive:
            for file in files:
                archive.write(file, "EmailTools/" + file.relative_to(ROOT).as_posix())
        verify_package(staging)
        staging.replace(output)
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        output.with_suffix(".zip.sha256").write_text(f"{digest}  {output.name}\n", encoding="ascii")
        print(f"Verified portable package: {output}\nFiles: {len(files)}\nSHA256: {digest}")
        return 0
    finally:
        if staging.exists():
            staging.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
