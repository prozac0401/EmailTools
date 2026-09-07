"""Unified CLI using the same options, analysis and export as the GUI."""
from __future__ import annotations
import argparse
import json
import logging
import tempfile
from io import StringIO
from pathlib import Path

from emailtools.exporters.files import export_results
from emailtools.models import ProcessingOptions
from emailtools.pipeline import analyze


def main() -> int:
    parser = argparse.ArgumentParser(description="EmailTools · 통합 일괄 처리")
    parser.add_argument("source", help="EML 파일 또는 폴더")
    parser.add_argument("--output", type=Path, help="결과 폴더 (기본: 입력 위치/_EML_OUTPUT)")
    parser.add_argument("--mail", action="store_true", help="메일 정보와 본문 저장")
    parser.add_argument("--attachments", action="store_true", help="첨부 원본 저장")
    parser.add_argument("--text", action="store_true", help="첨부 텍스트 추출")
    parser.add_argument("--tables", action="store_true", help="표 추출 및 Excel 저장 (옵션 생략 시 기본)")
    parser.add_argument("--all", action="store_true", help="네 가지 기능 모두 실행")
    parser.add_argument("--table-source", choices=["both", "email", "docx"], default="both")
    parser.add_argument("--columns-file", type=Path, help="열 설정 JSON 파일 (GUI와 같은 배열 형식)")
    args = parser.parse_args()
    explicit = any((args.mail, args.attachments, args.text, args.tables, args.all))
    options = ProcessingOptions(save_mail=args.mail or args.all, save_attachments=args.attachments or args.all,
        extract_text=args.text or args.all, extract_tables=args.tables or args.all or not explicit,
        email_tables=args.table_source != "docx", docx_tables=args.table_source != "email")
    log = StringIO()
    logger = logging.Logger("emailtools.cli", logging.INFO)
    handler = logging.StreamHandler(log)
    logger.addHandler(handler)
    try:
        options.validate()
        if args.columns_file and not options.extract_tables:
            raise ValueError("--columns-file은 표 추출과 함께 사용해 주세요.")
        columns = json.loads(args.columns_file.read_text(encoding="utf-8-sig")) if args.columns_file else None
        with tempfile.TemporaryDirectory(prefix="EmailTools_cli_") as working:
            result = analyze(Path(args.source), options, Path(working), logger, print)
            folder = export_results(result, args.output or result.source_root / "_EML_OUTPUT", logger,
                                    columns=columns, get_log=log.getvalue)
            print(f"전체 {len(result.records)} / 정상 {result.success} / 확인 {result.warnings} / 실패 {result.failures}")
            print(f"결과: {folder}")
            return 2 if any(record["_error"] for record in result.records) else 0
    except KeyboardInterrupt:
        print("작업을 중지했습니다.")
        return 130
    except Exception as exc:
        print(f"[오류] {exc}")
        return 1
    finally:
        handler.close()
        logger.removeHandler(handler)
