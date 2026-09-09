"""Publish a complete result folder atomically; never overwrite a previous run."""
from __future__ import annotations

import csv
import json
import logging
import secrets
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Callable

from emailtools import __version__
from emailtools.exporters.excel import write_excel
from emailtools.extractors.tables import OUTPUT_FILENAME
from emailtools.models import AnalysisResult
from emailtools.paths import safe_attachment_path, safe_name, write_text
from emailtools.reader import JOB_MARKER
from emailtools.table_config import default_columns, project_records, validate_columns

LOG_FILENAME = "processing.log"
ARCHIVE_FILENAME = "EmailTools_Result.zip"


def csv_literal(value: object) -> str:
    text = str(value)
    return "'" + text if text.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")) else text


def write_csv(path: Path, headers: list[str], rows: list[list], is_cancelled=None) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        for row in rows:
            if is_cancelled and is_cancelled():
                raise InterruptedError("목록 저장을 중지했습니다.")
            writer.writerow([csv_literal(value) for value in row])


def export_results(result: AnalysisResult, destination: Path, logger: logging.Logger,
                   *, columns: object = None, get_log: Callable[[], str] = lambda: "",
                   archive: bool = False, progress=None, is_cancelled=None) -> Path:
    """Stage in destination, then expose one completed run folder on success."""
    specs = []
    def check():
        if is_cancelled and is_cancelled():
            raise InterruptedError("저장을 중지했습니다. 미완성 결과는 정리했습니다.")
    def emit(phase, completed=0, total=None, current="", cancellable=True):
        if progress:
            progress(dict(phase=phase, completed=completed, total=total, current=current, cancellable=cancellable))
    def copy(source, target):
        with source.open("rb") as src, target.open("wb") as dst:
            while chunk := src.read(1024 * 1024):
                check()
                dst.write(chunk)
    check()
    if result.options.extract_tables:
        specs = validate_columns(default_columns(result.columns) if columns is None else columns, result.columns)
    result.options.validate()
    destination = destination.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    job_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + secrets.token_hex(8)
    final = destination / job_id
    staging = Path(tempfile.mkdtemp(prefix=".emailtools-job-", dir=destination)).resolve()
    try:
        # The marker also excludes results unpacked from a ZIP from future scans.
        (staging / JOB_MARKER).write_text(json.dumps({"version": __version__, "job": job_id,
            "options": result.options.as_dict(), "mails": len(result.records)}, ensure_ascii=False), encoding="utf-8")
        summary = []
        attachment_rows = []
        planned_files = sum(int(result.options.save_mail and bool(mail.body)) + sum(
            int(result.options.save_attachments and item.payload_path is not None) +
            int(result.options.extract_text and item.text is not None) for item in mail.attachments) for mail in result.mails)
        completed_files = 0
        if planned_files:
            emit("첨부·본문 저장", 0, planned_files)
        for index, mail in enumerate(result.mails, 1):
            check()
            source = mail.record["source_eml"]
            mail_dir = staging / "mails" / f"{index:06d}_{safe_name(Path(source).stem, 'mail')[:80]}"
            if result.options.save_mail and mail.body:
                write_text(mail_dir / "mail.txt", mail.body)
                completed_files += 1
                emit("첨부·본문 저장", completed_files, planned_files, source)
            for item in mail.attachments:
                check()
                saved_path = text_path = ""
                if result.options.save_attachments and item.payload_path is not None:
                    target = safe_attachment_path(mail_dir / "attachments", item.name, "attachment")
                    copy(item.payload_path, target)
                    saved_path = target.relative_to(staging).as_posix()
                    completed_files += 1
                    emit("첨부·본문 저장", completed_files, planned_files, item.name)
                if result.options.extract_text and item.text is not None:
                    target = safe_attachment_path(mail_dir / "text", item.name + ".txt", "attachment.txt")
                    write_text(target, item.text)
                    text_path = target.relative_to(staging).as_posix()
                    completed_files += 1
                    emit("첨부·본문 저장", completed_files, planned_files, item.name)
                attachment_rows.append([source, item.name, item.size if item.size is not None else "", item.content_type,
                                        saved_path, text_path, item.text_status, item.error])
            summary.append([source, mail.record.get("subject", ""), mail.record.get("from", ""),
                            len(mail.attachments), mail.record["_status"], mail.record["_error"]])
        emit("목록 저장")
        write_csv(staging / "summary.csv", ["source_eml", "subject", "from", "attachments", "status", "error"], summary, is_cancelled)
        write_csv(staging / "attachments.csv", ["source_eml", "attachment_name", "size_bytes", "content_type",
                  "saved_path", "text_path", "text_status", "error"], attachment_rows, is_cancelled)
        def spreadsheet(records, headers, path, phase):
            emit(phase, 0, len(records), path.name)
            write_excel(records, headers, path, logger,
                progress=lambda done, total: emit(phase, done, total, path.name), is_cancelled=is_cancelled)
        if result.options.mail_index:
            headers = ["source_eml", "subject", "from", "to", "date", "attachments", "status", "error"]
            rows = [{**mail.record, "attachments": str(len(mail.attachments)), "status": mail.record["_status"],
                     "error": mail.record["_error"]} for mail in result.mails]
            spreadsheet(rows, headers, staging / "MailList.xlsx", "메일 목록 Excel")
            if result.options.attachment_index:
                headers = ["source_eml", "attachment_name", "size_bytes", "content_type", "saved_path", "text_path", "text_status", "error"]
                rows = [dict(zip(headers, row)) for row in attachment_rows]
                for row, item in zip(rows, (a for m in result.mails for a in m.attachments)):
                    row["table_status"] = item.table_status
                spreadsheet(rows, [*headers, "table_status"],
                            staging / "AttachmentList.xlsx", "첨부 목록 Excel")
        if specs:
            spreadsheet(project_records(result.records, specs), [s["name"] for s in specs],
                        staging / "tables" / OUTPUT_FILENAME, "표 Excel")
        logger.info("Export complete: %d mails -> %s", len(result.records), final)
        write_text(staging / LOG_FILENAME, get_log())
        if archive:
            entries = sorted(p for p in staging.rglob("*") if p.is_file())
            total_bytes = sum(path.stat().st_size for path in entries)
            written = 0
            emit("ZIP 생성", 0, total_bytes, "바이트")
            with zipfile.ZipFile(staging / ARCHIVE_FILENAME, "w", zipfile.ZIP_DEFLATED) as output:
                for path in entries:
                    check()
                    with path.open("rb") as src, output.open(path.relative_to(staging).as_posix(), "w", force_zip64=True) as dst:
                        while chunk := src.read(1024 * 1024):
                            check()
                            dst.write(chunk)
                            written += len(chunk)
                            emit("ZIP 생성", written, total_bytes, path.name)
        check()
        emit("저장 마무리", cancellable=False)
        if final.exists():
            raise FileExistsError(f"결과 폴더가 이미 있습니다: {final}")
        staging.rename(final)
        return final
    except BaseException:
        # Delete only this call's verified staging directory, never destination.
        if (staging.exists() and staging.resolve().parent == destination
                and staging.name.startswith(".emailtools-job-")):
            shutil.rmtree(staging)
        raise
