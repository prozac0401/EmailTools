from __future__ import annotations

import html
import importlib.util
import logging
import math
import os
import re
import sys
import tempfile
import traceback
import zipfile
from dataclasses import dataclass
from email import policy
from email.message import Message
from email.parser import BytesParser
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Callable, Iterable
import xml.etree.ElementTree as ET


from emailtools.extractors.tables import *
from emailtools.extractors.tables import _relative_source_name
from emailtools import reader as eml_reader
from emailtools.exporters.excel import *

@dataclass
class ScanResult:
    records: list[dict[str, str]]
    columns: list[str]
    success: int
    warnings: int
    failures: int


def scan_source(
    source_root: Path,
    logger: logging.Logger,
    progress: Callable[[str], None] | None = None,
) -> ScanResult:
    """Read EML data without writing a workbook or changing the input folder."""
    source_root = source_root.expanduser().resolve()
    if source_root.is_file() and source_root.suffix.lower() == ".eml":
        eml_files = [source_root]
        source_root = source_root.parent
    elif source_root.is_dir():
        eml_files = find_eml_files(source_root)
    else:
        raise FileNotFoundError(f"EML 파일 또는 폴더를 찾을 수 없습니다: {source_root}")
    if not eml_files:
        raise FileNotFoundError(f"EML 파일을 찾지 못했습니다: {source_root}")
    records: list[dict[str, str]] = []
    success = warning_count = failures = 0
    logger.info("Start: %s (%d EML files)", source_root, len(eml_files))
    for index, eml_path in enumerate(eml_files, 1):
        try:
            result = process_eml_record(eml_path, source_root, logger)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            logger.exception("UNEXPECTED ERROR: %s", eml_path)
            record = {column: "" for column in SYSTEM_COLUMNS}
            record.update(source_eml=_relative_source_name(eml_path, source_root),
                          _status="PARSE ERROR", _error=error)
            result = ProcessResult(record, "PARSE ERROR", [error])
        records.append(result.record)
        if result.status == "OK":
            success += 1
        elif result.status == "PARSE ERROR":
            failures += 1
        else:
            warning_count += 1
        if progress:
            progress(f"[{index}/{len(eml_files)}] {eml_path.name} ... {result.status}")
    return ScanResult(records, collect_columns(records), success, warning_count, failures)


@dataclass
class BatchResult:
    output_path: Path
    log_path: Path
    total: int
    success: int
    warnings: int
    failures: int
    columns: list[str]
    records: list[dict[str, str]]


def find_eml_files(source_root: Path) -> list[Path]:
    return eml_reader.find_eml_targets(source_root)[1]


def configure_logger(log_path: Path) -> logging.Logger:
    logger = logging.getLogger("emailtools.eml_table_to_excel")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(log_path, mode="w", encoding="utf-8-sig")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger


def close_logger(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)


def run_batch(
    source_root: Path,
    progress: Callable[[str], None] | None = None,
) -> BatchResult:
    source_root = source_root.expanduser().resolve()
    if not source_root.is_dir():
        raise NotADirectoryError(f"EML 폴더를 찾을 수 없습니다: {source_root}")

    output_path = source_root / OUTPUT_FILENAME
    log_path = source_root / ERROR_LOG_FILENAME
    logger = configure_logger(log_path)
    try:
        scan = scan_source(source_root, logger, progress)
        write_excel(scan.records, scan.columns, output_path, logger)
        logger.info(
            "Complete: total=%d success=%d warnings=%d failures=%d output=%s",
            len(scan.records),
            scan.success,
            scan.warnings,
            scan.failures,
            output_path,
        )
    finally:
        close_logger(logger)

    return BatchResult(
        output_path=output_path,
        log_path=log_path,
        total=len(scan.records),
        success=scan.success,
        warnings=scan.warnings,
        failures=scan.failures,
        columns=scan.columns,
        records=scan.records,
    )


def choose_source_folder() -> Path:
    print()
    print("EML 파일이 있는 폴더를 입력하세요.")
    print("예: D:\\Mail\\Training")
    raw = input("> ").strip().strip('"')
    if not raw:
        raise ValueError("폴더 경로가 입력되지 않았습니다.")
    return Path(raw)


def main() -> int:
    print("=" * 72)
    print(f"{APP_NAME} v{APP_VERSION}")
    print("Shared Windows Embedded Python / bundled openpyxl")
    print("=" * 72)
    try:
        source_root = Path(sys.argv[1].strip('"')) if len(sys.argv) > 1 else choose_source_folder()
        result = run_batch(source_root, print)
        print()
        print("=" * 72)
        print("처리 완료")
        print(f"전체: {result.total}")
        print(f"성공: {result.success}")
        print(f"경고: {result.warnings}")
        print(f"실패: {result.failures}")
        print()
        print(f"결과: {result.output_path}")
        print(f"로그: {result.log_path}")
        print("=" * 72)
        return 0
    except Exception as exc:
        print(f"\n[오류] {type(exc).__name__}: {exc}")
        print(f"상세 로그를 생성할 수 있는 입력 폴더인지 확인해 주세요.")
        if os.environ.get("EMAILTOOLS_DEBUG") == "1":
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
