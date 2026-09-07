from __future__ import annotations

import base64
import csv
import html
import quopri
import re
import sys
import traceback
import zipfile
from dataclasses import dataclass
from email import policy
from email.message import Message
from email.parser import BytesParser
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
import xml.etree.ElementTree as ET

APP_NAME = "EML Attachment Tool"
APP_VERSION = "1.0.0"
OUTPUT_DIR_NAME = "_EML_OUTPUT"
TEXT_DIR_NAME = "_TEXT"


from emailtools.paths import *
from emailtools.reader import *
from emailtools import reader as eml_reader
from emailtools.extractors.text import *

@dataclass
class AttachmentRecord:
    source_eml: str
    attachment_name: str
    saved_path: str
    size: int
    content_type: str
    text_status: str
    text_path: str


def save_attachment(part: Message, attachments_dir: Path, index: int) -> Path:
    target = safe_attachment_path(
        attachments_dir,
        part.get_filename(),
        f"attachment_{index:03d}",
    )

    data = attachment_bytes(part)
    if part.get_content_type().lower() == "message/rfc822":
        if target.suffix.lower() != ".eml":
            target = unique_path(target.with_suffix(target.suffix + ".eml" if target.suffix else ".eml"))

    target.write_bytes(data)
    return target


def process_eml(eml_path: Path, source_root: Path, output_root: Path) -> tuple[int, list[AttachmentRecord], str | None]:
    try:
        msg = eml_reader.read_message(eml_path)
    except Exception as exc:
        return 0, [], f"EML parse error: {type(exc).__name__}: {exc}"

    try:
        rel_parent = eml_path.parent.relative_to(source_root)
    except ValueError:
        rel_parent = Path()

    folder_name = safe_name(eml_path.stem, "mail")
    mail_dir = output_root / rel_parent / folder_name
    attachments_dir = mail_dir / "attachments"
    text_dir = mail_dir / TEXT_DIR_NAME
    mail_dir.mkdir(parents=True, exist_ok=True)

    write_text(mail_dir / "_mail.txt", render_mail_text(msg))

    records: list[AttachmentRecord] = []
    errors: list[str] = []
    for idx, part in enumerate(attachment_parts(msg), 1):
        try:
            saved = save_attachment(part, attachments_dir, idx)
            readable, status = extract_readable_text(saved)
            text_path = ""
            if readable is not None:
                text_target = text_dir / f"{saved.name}.txt"
                write_text(text_target, readable)
                text_path = str(text_target)
            records.append(
                AttachmentRecord(
                    source_eml=str(eml_path),
                    attachment_name=saved.name,
                    saved_path=str(saved),
                    size=saved.stat().st_size,
                    content_type=part.get_content_type(),
                    text_status=status,
                    text_path=text_path,
                )
            )
        except Exception as exc:
            errors.append(f"attachment #{idx}: {type(exc).__name__}: {exc}")

    index_lines = [
        f"EML: {eml_path}",
        f"Attachments: {len(records)}",
        "",
    ]
    for i, r in enumerate(records, 1):
        index_lines.extend([
            f"[{i}] {r.attachment_name}",
            f"  Type: {r.content_type}",
            f"  Size: {r.size} bytes",
            f"  Saved: {r.saved_path}",
            f"  Read status: {r.text_status}",
            f"  Text: {r.text_path or '-'}",
            "",
        ])
    if errors:
        index_lines.append("[Errors]")
        index_lines.extend(errors)
    write_text(mail_dir / "_attachments_index.txt", "\n".join(index_lines))
    return len(records), records, "; ".join(errors) if errors else None


def find_eml_targets(target: Path) -> tuple[Path, list[Path]]:
    return eml_reader.find_eml_targets(target)


def choose_target_from_console() -> Path:
    print()
    print("EML 파일 또는 EML 폴더 경로를 입력하세요.")
    print("예: D:\\Mail\\Export")
    raw = input("> ").strip().strip('"')
    if not raw:
        raise ValueError("경로가 입력되지 않았습니다.")
    return Path(raw)


def main() -> int:
    print("=" * 70)
    print(f"{APP_NAME} v{APP_VERSION}")
    print("Local Embedded Python only")
    print("=" * 70)

    try:
        target = Path(sys.argv[1].strip('"')) if len(sys.argv) > 1 else choose_target_from_console()
        target = target.expanduser().resolve()
        source_root, eml_files = find_eml_targets(target)
        if not eml_files:
            print(f"\n[알림] EML 파일을 찾지 못했습니다: {target}")
            return 2

        output_root = source_root / OUTPUT_DIR_NAME
        output_root.mkdir(parents=True, exist_ok=True)

        print(f"\n대상: {target}")
        print(f"EML: {len(eml_files)}개")
        print(f"출력: {output_root}")
        print()

        all_records: list[AttachmentRecord] = []
        failures: list[tuple[str, str]] = []
        total_attachments = 0

        width = len(str(len(eml_files)))
        for i, eml_path in enumerate(eml_files, 1):
            print(f"[{i:>{width}}/{len(eml_files)}] {eml_path.name}", end=" ... ", flush=True)
            count, records, error = process_eml(eml_path, source_root, output_root)
            total_attachments += count
            all_records.extend(records)
            if error:
                failures.append((str(eml_path), error))
                print(f"완료 ({count}개 첨부, 일부 오류)")
            else:
                print(f"완료 ({count}개 첨부)")

        summary_csv = output_root / "_summary.csv"
        with summary_csv.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["source_eml", "attachment_name", "saved_path", "size_bytes", "content_type", "text_status", "text_path"])
            for r in all_records:
                writer.writerow([r.source_eml, r.attachment_name, r.saved_path, r.size, r.content_type, r.text_status, r.text_path])

        summary_lines = [
            f"{APP_NAME} v{APP_VERSION}",
            f"EML files: {len(eml_files)}",
            f"Attachments: {total_attachments}",
            f"Failures/partial: {len(failures)}",
            f"Output: {output_root}",
            "",
            "Readable without additional packages:",
            "- TXT/CSV/TSV/JSON/XML/HTML/MD and common text files",
            "- DOCX",
            "- XLSX (cell values)",
            "- PPTX (slide text)",
            "- PDF (text layer; password/DRM PDFs may be unreadable)",
            "- attached EML",
            "",
            "Extract-only:",
            "- images, ZIP and other binary formats",
        ]
        if failures:
            summary_lines += ["", "[Errors]"]
            summary_lines.extend(f"{p}: {e}" for p, e in failures)
        write_text(output_root / "_summary.txt", "\n".join(summary_lines))

        print("\n" + "-" * 70)
        print(f"완료: EML {len(eml_files)}개 / 첨부파일 {total_attachments}개")
        print(f"결과 폴더: {output_root}")
        print(f"요약 CSV: {summary_csv}")
        if failures:
            print(f"주의: {len(failures)}개 EML에서 일부 오류가 발생했습니다. _summary.txt를 확인하세요.")
        return 0

    except Exception as exc:
        print(f"\n[오류] {type(exc).__name__}: {exc}")
        print("\n상세:")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
