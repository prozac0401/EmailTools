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


def write_csv(path: Path, headers: list[str], rows: list[list]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        for row in rows:
            writer.writerow([csv_literal(value) for value in row])


def export_results(result: AnalysisResult, destination: Path, logger: logging.Logger,
                   *, columns: object = None, get_log: Callable[[], str] = lambda: "",
                   archive: bool = False) -> Path:
    """Stage in destination, then expose one completed run folder on success."""
    specs = []
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
        for index, mail in enumerate(result.mails, 1):
            source = mail.record["source_eml"]
            mail_dir = staging / "mails" / f"{index:06d}_{safe_name(Path(source).stem, 'mail')[:80]}"
            if result.options.save_mail and mail.body:
                write_text(mail_dir / "mail.txt", mail.body)
            for item in mail.attachments:
                saved_path = text_path = ""
                if result.options.save_attachments and item.payload_path is not None:
                    target = safe_attachment_path(mail_dir / "attachments", item.name, "attachment")
                    shutil.copyfile(item.payload_path, target)
                    saved_path = target.relative_to(staging).as_posix()
                if result.options.extract_text and item.text is not None:
                    target = safe_attachment_path(mail_dir / "text", item.name + ".txt", "attachment.txt")
                    write_text(target, item.text)
                    text_path = target.relative_to(staging).as_posix()
                attachment_rows.append([source, item.name, item.size, item.content_type,
                                        saved_path, text_path, item.text_status, item.error])
            summary.append([source, mail.record.get("subject", ""), mail.record.get("from", ""),
                            len(mail.attachments), mail.record["_status"], mail.record["_error"]])
        write_csv(staging / "summary.csv", ["source_eml", "subject", "from", "attachments", "status", "error"], summary)
        write_csv(staging / "attachments.csv", ["source_eml", "attachment_name", "size_bytes", "content_type",
                  "saved_path", "text_path", "text_status", "error"], attachment_rows)
        if specs:
            write_excel(project_records(result.records, specs), [s["name"] for s in specs],
                        staging / "tables" / OUTPUT_FILENAME, logger)
        logger.info("Export complete: %d mails -> %s", len(result.records), final)
        write_text(staging / LOG_FILENAME, get_log())
        if archive:
            entries = sorted(p for p in staging.rglob("*") if p.is_file())
            with zipfile.ZipFile(staging / ARCHIVE_FILENAME, "w", zipfile.ZIP_DEFLATED) as output:
                for path in entries:
                    output.write(path, path.relative_to(staging).as_posix())
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
