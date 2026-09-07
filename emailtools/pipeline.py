"""Shared, read-only analysis pipeline for GUI and CLI."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from emailtools import reader
from emailtools.extractors import attachments, tables, text
from emailtools.models import AnalysisResult, AttachmentResult, MailResult, ProcessingOptions


def analyze(source: Path, options: ProcessingOptions, spool: Path, logger: logging.Logger,
            progress: Callable[[str], None] | None = None,
            is_cancelled: Callable[[], bool] | None = None) -> AnalysisResult:
    options.validate()
    source_root, files = reader.find_eml_targets(source, is_cancelled)
    if not files:
        raise FileNotFoundError(f"EML 파일을 찾지 못했습니다: {source_root}")
    mails = []
    records = []
    success = warnings = failures = 0
    for index, path in enumerate(files, 1):
        if is_cancelled and is_cancelled():
            raise InterruptedError("분석을 중지했습니다. 결과는 저장하지 않았습니다.")
        source_name = str(path.relative_to(source_root))
        record = {column: "" for column in tables.SYSTEM_COLUMNS}
        record.update(source_eml=source_name, _status="OK")
        mail = MailResult(record)
        try:
            msg = reader.read_message(path)
            sources = attachments.collect(msg)
            if options.extract_tables:
                result = tables.process_message_record(msg, source_name, logger, attachments=sources,
                    include_email=options.email_tables, include_docx=options.docx_tables)
                record.update(result.record)
            else:
                for name in ("subject", "from", "to", "date"):
                    record[name] = tables.header_value(msg, name)
            mail.body = reader.render_mail_text(msg)
            for attachment in sources:
                item = AttachmentResult(attachment.name, attachment.content_type, 0)
                mail.attachments.append(item)
                try:
                    payload = attachment.payload
                    item.size = len(payload)
                    if options.save_attachments:
                        saved = spool / f"mail_{index:06d}" / f"attachment_{attachment.index:06d}.bin"
                        saved.parent.mkdir(parents=True, exist_ok=True)
                        saved.write_bytes(payload)
                        item.payload_path = saved
                    if options.extract_text:
                        item.text, item.text_status = text.extract_content(attachment.name, payload)
                        if item.text_status.startswith("read-error:"):
                            item.error = item.text_status
                except Exception as exc:
                    item.error = f"{type(exc).__name__}: {exc}"
                    logger.exception("ATTACHMENT ERROR: %s / %s", source_name, item.name)
                if item.error:
                    record["_status"] = tables.DUPLICATE_VALUE_SEPARATOR.join(dict.fromkeys(
                        [s for s in record["_status"].split(tables.DUPLICATE_VALUE_SEPARATOR) if s != "OK"]
                        + ["ATTACHMENT ERROR"]))
                    record["_error"] = "; ".join(filter(None, [record["_error"], f"{item.name}: {item.error}"]))
                    logger.warning("%s / %s: %s", source_name, item.name, item.error)
        except Exception as exc:
            record["_status"] = "PARSE ERROR"
            record["_error"] = f"{type(exc).__name__}: {exc}"
            logger.exception("PARSE ERROR: %s", source_name)
        records.append(record)
        mails.append(mail)
        if record["_status"] == "OK":
            success += 1
        elif record["_status"] == "PARSE ERROR":
            failures += 1
        else:
            warnings += 1
        if progress:
            progress(f"[{index}/{len(files)}] {source_name} ... {record['_status']}")
    if is_cancelled and is_cancelled():
        raise InterruptedError("분석을 중지했습니다. 결과는 저장하지 않았습니다.")
    columns = tables.collect_columns(records) if options.extract_tables else []
    return AnalysisResult(source_root, options, mails, records, columns, success, warnings, failures)
