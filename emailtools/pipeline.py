"""Shared, read-only analysis pipeline for GUI and CLI."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Callable

from emailtools import reader
from emailtools.extractors import attachments, tables, text
from emailtools.models import AnalysisResult, AttachmentResult, MailResult, ProcessingOptions


def analyze(source: Path, options: ProcessingOptions, spool: Path, logger: logging.Logger,
            progress: Callable[[str], None] | None = None,
            is_cancelled: Callable[[], bool] | None = None,
            *, sources: list[Path] | None = None, status: Callable[[dict], None] | None = None) -> AnalysisResult:
    options.validate()
    def emit(phase, completed=0, total=None, current=""):
        if status:
            status(dict(phase=phase, completed=completed, total=total, current=current, cancellable=True))
    emit("파일 찾기")
    if sources:
        found = []
        roots = []
        for entry in sources:
            root, targets = reader.find_eml_targets(entry, is_cancelled)
            roots.append(root)
            found.extend(targets)
            emit("파일 찾기", len(found), current=str(entry))
        files = list(dict.fromkeys(found))
        try:
            source_root = Path(os.path.commonpath(roots))
        except ValueError:
            source_root = roots[0]
    else:
        source_root, files = reader.find_eml_targets(source, is_cancelled)
    if not files:
        raise FileNotFoundError(f"EML 파일을 찾지 못했습니다: {source_root}")
    mails = []
    records = []
    success = warnings = failures = 0
    catalog = None
    if options.mail_index and options.extract_tables:
        from emailtools.field_catalog import FieldCatalog
        catalog = FieldCatalog()
    for index, path in enumerate(files, 1):
        if is_cancelled and is_cancelled():
            raise InterruptedError("분석을 중지했습니다. 결과는 저장하지 않았습니다.")
        emit("메일·표 읽기" if options.extract_tables else "메일 정보 읽기", index - 1, len(files), path.name)
        source_name = str(path.relative_to(source_root)) if path.is_relative_to(source_root) else str(path)
        record = {column: "" for column in tables.SYSTEM_COLUMNS}
        record.update(source_eml=source_name, _status="OK")
        mail = MailResult(record, source_path=path)
        try:
            msg = reader.read_message(path)
            mail.content_hash = getattr(msg, "_emailtools_hash", source_name)
            attachment_sources = attachments.collect(msg)
            if options.extract_tables and catalog is None:
                result = tables.process_message_record(msg, source_name, logger, attachments=attachment_sources,
                    include_email=options.email_tables, include_docx=options.docx_tables)
                record.update(result.record)
            else:
                for name in ("subject", "from", "to", "date"):
                    record[name] = tables.header_value(msg, name)
            if options.save_mail or not options.mail_index:
                mail.body = reader.render_mail_text(msg)
            if catalog is not None:
                catalog.read_body(msg, source_name, mail.content_hash, options.email_tables, logger, record)
            for attachment in attachment_sources:
                item = AttachmentResult(attachment.name, attachment.content_type, None)
                mail.attachments.append(item)
                try:
                    is_docx = Path(item.name).suffix.lower() == ".docx" or item.content_type in tables.DOCX_CONTENT_TYPES
                    if catalog is not None and is_docx:
                        tables.merge_key_value(record, "docx_filename", item.name)
                    if options.extract_tables:
                        item.table_status = "표 대상 아님" if not is_docx else ("분석 대상 제외" if not options.docx_tables else "표 없음")
                    if options.mail_index and not (options.save_attachments or options.extract_text or
                            (options.extract_tables and options.docx_tables and is_docx)):
                        continue
                    emit("메일·표 읽기" if options.extract_tables else "메일·첨부 준비", index - 1,
                         len(files), f"{path.name} / {item.name}")
                    payload = attachment.payload
                    item.size = len(payload)
                    if catalog is not None and options.docx_tables and is_docx:
                        try:
                            count = catalog.read_docx(payload, source_name, mail.content_hash, attachment.index, item.name)
                            item.table_status = f"표 {count}개" if count else "표 없음"
                        except Exception as exc:
                            item.error = f"Word 표: {type(exc).__name__}: {exc}"
                            item.table_status = "읽기 실패"
                            logger.exception("DOCX TABLE ERROR: %s / %s", source_name, item.name)
                    if options.save_attachments:
                        saved = spool / f"mail_{index:06d}" / f"attachment_{attachment.index:06d}.bin"
                        saved.parent.mkdir(parents=True, exist_ok=True)
                        saved.write_bytes(payload)
                        item.payload_path = saved
                    if options.extract_text:
                        item.text, item.text_status = text.extract_content(attachment.name, payload)
                        if item.text_status.startswith("read-error:"):
                            item.error = "; ".join(filter(None, [item.error, item.text_status]))
                except Exception as exc:
                    item.error = "; ".join(filter(None, [item.error, f"{type(exc).__name__}: {exc}"]))
                    item.table_status = "읽기 실패" if options.extract_tables else "not requested"
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
        emit("메일 처리", index, len(files), source_name)
    if is_cancelled and is_cancelled():
        raise InterruptedError("분석을 중지했습니다. 결과는 저장하지 않았습니다.")
    if catalog is not None:
        emit("항목 정리")
        catalog.finalize(mails, is_cancelled, status)
    columns = tables.collect_columns(records) if options.extract_tables else []
    emit("결과 준비")
    return AnalysisResult(source_root, options, mails, records, columns, success, warnings, failures, catalog)
