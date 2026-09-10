from __future__ import annotations
import html
import logging
import re
import zipfile
from dataclasses import dataclass
from email.message import Message
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Iterable
import xml.etree.ElementTree as ET

APP_NAME = "EML Table to Excel"
APP_VERSION = "1.0.0"
OUTPUT_FILENAME = "EML_Table_Result.xlsx"
ERROR_LOG_FILENAME = "EML_Table_Result_errors.log"
WORKSHEET_NAME = "Result"

SYSTEM_COLUMNS = [
    "source_eml",
    "_status",
    "_error",
    "subject",
    "from",
    "to",
    "date",
    "docx_filename",
]

# Intentionally empty for v1.  Real aliases can be added later without changing
# the parsing pipeline after they have been confirmed against actual data.
COLUMN_ALIASES: dict[str, str] = {}

DUPLICATE_VALUE_SEPARATOR = " | "
MAX_EXCEL_CELL_CHARS = 32767
MAX_DOCX_XML_BYTES = 32 * 1024 * 1024
ILLEGAL_XML_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
KEY_EDGE_CHARS = " \t\r\n:：;；|·•※*#"
DOCX_CONTENT_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
HEADER_KEYS = {"항목", "항목명", "구분", "key", "field", "item"}
HEADER_VALUES = {"값", "내용", "value", "description"}



from emailtools import reader as EML_SUPPORT

def normalize_key(text: object) -> str:
    value = html.unescape(str(text or "")).replace("\xa0", " ")
    value = re.sub(r"[\r\n\t]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip(KEY_EDGE_CHARS)
    value = re.sub(r"\s+", " ", value).strip()
    return COLUMN_ALIASES.get(value, value)


def normalize_value(text: object) -> str:
    value = html.unescape(str(text or "")).replace("\xa0", " ")
    value = value.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    lines = [re.sub(r"[ \f\v]+", " ", line).strip() for line in value.split("\n")]
    compact: list[str] = []
    for line in lines:
        if line:
            compact.append(line)
        elif compact and compact[-1] != "":
            compact.append("")
    while compact and compact[-1] == "":
        compact.pop()
    return "\n".join(compact)


def merge_key_value(target: dict[str, str], key: object, value: object) -> None:
    normalized_key = normalize_key(key)
    if not normalized_key:
        return
    normalized_value = normalize_value(value)
    if normalized_key not in target:
        target[normalized_key] = normalized_value
        return
    current = target[normalized_key]
    if not normalized_value or normalized_value == current:
        return
    if not current:
        target[normalized_key] = normalized_value
        return
    existing_values = [part.strip() for part in current.split(DUPLICATE_VALUE_SEPARATOR)]
    if normalized_value not in existing_values:
        target[normalized_key] = current + DUPLICATE_VALUE_SEPARATOR + normalized_value


def _is_header_pair(key: str, value: str) -> bool:
    return key.casefold() in HEADER_KEYS and value.casefold() in HEADER_VALUES


def table_to_key_value_dict(table: Iterable[Iterable[object]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in table:
        cells = [normalize_value(cell) for cell in row]
        for index in range(0, len(cells) - 1, 2):
            key = normalize_key(cells[index])
            value = normalize_value(cells[index + 1])
            if not key or _is_header_pair(key, value):
                continue
            merge_key_value(result, key, value)
    return result


class HTMLTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._table_depth = 0
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        del attrs
        tag = tag.lower()
        if tag == "table":
            self._table_depth += 1
            if self._table_depth == 1:
                self._table = []
            return
        if self._table_depth != 1:
            return
        if tag == "tr":
            self._finish_row()
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._finish_cell()
            self._cell_parts = []
        elif tag == "br" and self._cell_parts is not None:
            self._cell_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "table":
            if self._table_depth == 1:
                self._finish_row()
                if self._table:
                    self.tables.append(self._table)
                self._table = None
            self._table_depth = max(0, self._table_depth - 1)
            return
        if self._table_depth != 1:
            return
        if tag in {"td", "th"}:
            self._finish_cell()
        elif tag == "tr":
            self._finish_row()
        elif tag in {"p", "div", "li"} and self._cell_parts is not None:
            self._cell_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._cell_parts is not None:
            self._cell_parts.append(data)

    def close(self) -> None:
        super().close()
        if self._table_depth:
            self._finish_row()
            if self._table:
                self.tables.append(self._table)
            self._table = None
            self._table_depth = 0

    def _finish_cell(self) -> None:
        if self._cell_parts is None:
            return
        if self._row is not None:
            self._row.append(normalize_value("".join(self._cell_parts)))
        self._cell_parts = None

    def _finish_row(self) -> None:
        self._finish_cell()
        if self._row is not None and self._table is not None:
            if any(normalize_value(cell) for cell in self._row):
                self._table.append(self._row)
        self._row = None


def parse_html_tables(html_text: str) -> list[list[list[str]]]:
    parser = HTMLTableParser()
    parser.feed(html_text)
    parser.close()
    return parser.tables


def extract_email_table_values(msg: Message) -> tuple[dict[str, str], int]:
    values: dict[str, str] = {}
    table_count = 0
    for part in EML_SUPPORT.body_parts(msg):
        if part.is_multipart():
            continue
        disposition = (part.get_content_disposition() or "").lower()
        if disposition == "attachment" or part.get_filename():
            continue
        if part.get_content_type().lower() != "text/html":
            continue
        html_text = EML_SUPPORT.payload_text(part)
        tables = parse_html_tables(html_text)
        table_count += len(tables)
        for table in tables:
            for key, value in table_to_key_value_dict(table).items():
                merge_key_value(values, key, value)
    return values, table_count


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WORD_NAMESPACES = {"w": WORD_NS}


def _docx_cell_text(cell: ET.Element, *, include_nested_tables: bool = True) -> str:
    def owned_paragraphs(element):
        # Word content controls and custom XML may wrap a cell's paragraphs.
        # Inner table cells have their own provenance in the native catalog.
        for child in element:
            if child.tag == f"{{{WORD_NS}}}tbl":
                continue
            if child.tag == f"{{{WORD_NS}}}p":
                yield child
            else:
                yield from owned_paragraphs(child)

    paragraphs: list[str] = []
    elements = cell.findall(".//w:p", WORD_NAMESPACES) if include_nested_tables else owned_paragraphs(cell)
    for paragraph in elements:
        parts: list[str] = []
        for element in paragraph.iter():
            local = element.tag.rsplit("}", 1)[-1]
            if local == "t" and element.text:
                parts.append(element.text)
            elif local == "tab":
                parts.append("\t")
            elif local in {"br", "cr"}:
                parts.append("\n")
        paragraph_text = normalize_value("".join(parts))
        if paragraph_text:
            paragraphs.append(paragraph_text)
    return normalize_value("\n".join(paragraphs))


def parse_docx_tables(docx_bytes: bytes) -> list[list[list[str]]]:
    with zipfile.ZipFile(BytesIO(docx_bytes)) as archive:
        info = archive.getinfo("word/document.xml")
        if info.file_size > MAX_DOCX_XML_BYTES:
            raise ValueError(
                f"word/document.xml is too large ({info.file_size} bytes; "
                f"limit {MAX_DOCX_XML_BYTES})"
            )
        root = ET.fromstring(archive.read(info))

    tables: list[list[list[str]]] = []
    for table_element in root.iter(f"{{{WORD_NS}}}tbl"):
        table: list[list[str]] = []
        for row_element in table_element.findall("./w:tr", WORD_NAMESPACES):
            row = [
                _docx_cell_text(cell)
                for cell in row_element.findall("./w:tc", WORD_NAMESPACES)
            ]
            if any(row):
                table.append(row)
        if table:
            tables.append(table)
    return tables


def header_value(msg: Message, name: str) -> str:
    return DUPLICATE_VALUE_SEPARATOR.join(
        normalize_value(str(value)) for value in msg.get_all(name, []) if str(value)
    )


def _record_data_key(key: str) -> str:
    if key in SYSTEM_COLUMNS:
        return f"item_{key}"
    return key


def _relative_source_name(eml_path: Path, source_root: Path) -> str:
    try:
        return str(eml_path.relative_to(source_root))
    except ValueError:
        return eml_path.name


@dataclass
class ProcessResult:
    record: dict[str, str]
    status: str
    errors: list[str]


def process_eml_record(
    eml_path: Path,
    source_root: Path,
    logger: logging.Logger,
) -> ProcessResult:
    source_name = _relative_source_name(eml_path, source_root)
    base_record = {column: "" for column in SYSTEM_COLUMNS}
    base_record["source_eml"] = source_name

    try:
        msg = EML_SUPPORT.read_message(eml_path)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        base_record["_status"] = "PARSE ERROR"
        base_record["_error"] = error
        logger.exception("PARSE ERROR: %s", eml_path)
        return ProcessResult(base_record, "PARSE ERROR", [error])

    return process_message_record(msg, source_name, logger)


def process_message_record(
    msg: Message,
    source_name: str,
    logger: logging.Logger,
    *,
    attachments=None,
    include_email: bool = True,
    include_docx: bool = True,
) -> ProcessResult:
    from emailtools.extractors.attachments import collect
    base_record = {column: "" for column in SYSTEM_COLUMNS}
    base_record["source_eml"] = source_name
    base_record.update(
        {
            "subject": header_value(msg, "Subject"),
            "from": header_value(msg, "From"),
            "to": header_value(msg, "To"),
            "date": header_value(msg, "Date"),
        }
    )

    warnings: list[str] = []
    errors: list[str] = []
    dynamic_values: dict[str, str] = {}

    try:
        email_values, email_table_count = extract_email_table_values(msg) if include_email else ({}, 0)
        if include_email and (not email_table_count or not email_values):
            warnings.append("NO EMAIL TABLE")
        for key, value in email_values.items():
            merge_key_value(dynamic_values, _record_data_key(key), value)
    except Exception as exc:
        message = f"email table: {type(exc).__name__}: {exc}"
        errors.append(message)
        warnings.append("EMAIL TABLE ERROR")
        logger.exception("EMAIL TABLE ERROR: %s", source_name)

    docx_names: list[str] = []
    docx_table_count = 0
    docx_parse_errors = 0
    sources = attachments if attachments is not None else collect(msg)
    for index, source in enumerate(sources if include_docx else [], 1):
        filename = source.name
        content_type = source.content_type
        if Path(filename).suffix.lower() != ".docx" and content_type not in DOCX_CONTENT_TYPES:
            continue
        display_name = EML_SUPPORT.safe_name(filename, f"attachment_{index:03d}.docx")
        docx_names.append(display_name)
        try:
            payload = source.payload
            tables = parse_docx_tables(payload)
            docx_table_count += len(tables)
            for table in tables:
                for key, value in table_to_key_value_dict(table).items():
                    merge_key_value(dynamic_values, _record_data_key(key), value)
        except Exception as exc:
            docx_parse_errors += 1
            message = f"{display_name}: {type(exc).__name__}: {exc}"
            errors.append(message)
            logger.exception("DOCX PARSE ERROR: %s / %s", source_name, display_name)

    for name in docx_names:
        merge_key_value(base_record, "docx_filename", name)

    if include_docx and not docx_names:
        warnings.append("NO DOCX")
    elif docx_parse_errors:
        warnings.append("DOCX PARSE ERROR")
    elif include_docx and not docx_table_count:
        warnings.append("NO DOCX TABLE")

    status = DUPLICATE_VALUE_SEPARATOR.join(dict.fromkeys(warnings)) or "OK"
    base_record["_status"] = status
    base_record["_error"] = "; ".join(errors)
    base_record.update(dynamic_values)

    if status != "OK":
        logger.warning("%s: %s%s", source_name, status, f"; {base_record['_error']}" if errors else "")
    return ProcessResult(base_record, status, errors)


def collect_columns(records: Iterable[dict[str, str]]) -> list[str]:
    columns = list(SYSTEM_COLUMNS)
    seen = set(columns)
    for record in records:
        for key in record:
            if key not in seen:
                columns.append(key)
                seen.add(key)
    return columns
