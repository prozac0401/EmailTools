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

# Load pure-Python third-party modules from this portable folder only.
APP_DIR = Path(__file__).resolve().parent
VENDOR_DIR = APP_DIR / "vendor"
if VENDOR_DIR.is_dir():
    sys.path.insert(0, str(VENDOR_DIR))

APP_NAME = "EML Attachment Tool"
APP_VERSION = "1.0.0"
OUTPUT_DIR_NAME = "_EML_OUTPUT"
TEXT_DIR_NAME = "_TEXT"

TEXT_EXTS = {
    ".txt", ".csv", ".tsv", ".json", ".xml", ".html", ".htm", ".md",
    ".log", ".ini", ".yaml", ".yml", ".sql", ".py", ".js", ".css",
}

INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in {"script", "style"}:
            self.skip_depth += 1
        if not self.skip_depth and tag in {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style"} and self.skip_depth:
            self.skip_depth -= 1
        if not self.skip_depth and tag in {"p", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)

    def text(self) -> str:
        value = "".join(self.parts)
        value = re.sub(r"[ \t]+", " ", value)
        value = re.sub(r"\n[ \t]+", "\n", value)
        value = re.sub(r"\n{3,}", "\n\n", value)
        return value.strip()


def html_to_text(value: str) -> str:
    parser = HTMLTextExtractor()
    try:
        parser.feed(value)
        parser.close()
        return parser.text()
    except Exception:
        return re.sub(r"<[^>]+>", " ", html.unescape(value)).strip()


def safe_name(name: str | None, fallback: str = "attachment") -> str:
    if not name:
        name = fallback
    # Attachment names are untrusted.  Drop both POSIX and Windows path
    # components before applying the Windows filename character rules.
    # Path(name).name alone is not sufficient when this code is tested or run
    # on a platform whose native separator differs from the supplied name.
    name = re.split(r"[\\/]+", name)[-1] or fallback
    name = INVALID_FILENAME_CHARS.sub("_", name)
    name = name.strip().rstrip(".")
    if name in {"", ".", ".."}:
        name = fallback
    # Avoid Windows reserved device names.
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    stem = Path(name).stem.upper()
    if stem in reserved:
        name = "_" + name
    return name[:240]


def safe_attachment_path(directory: Path, name: str | None, fallback: str) -> Path:
    """Return a unique direct child of *directory* for an untrusted name."""
    directory.mkdir(parents=True, exist_ok=True)
    target = unique_path(directory / safe_name(name, fallback))
    if target.resolve().parent != directory.resolve():
        raise ValueError("첨부파일 저장 경로가 출력 폴더를 벗어났습니다.")
    return target


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for i in range(1, 10000):
        candidate = path.with_name(f"{stem} ({i}){suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"동일 이름 파일이 너무 많습니다: {path}")


def decode_bytes(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr", "utf-16", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8-sig", errors="replace")


def xml_texts(root: ET.Element, local_tag: str) -> Iterable[str]:
    suffix = "}" + local_tag
    for elem in root.iter():
        if elem.tag == local_tag or elem.tag.endswith(suffix):
            if elem.text:
                yield elem.text


def extract_docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        names = ["word/document.xml"]
        names += sorted(n for n in zf.namelist() if re.fullmatch(r"word/(header|footer)\d+\.xml", n))
        output: list[str] = []
        for name in names:
            if name not in zf.namelist():
                continue
            root = ET.fromstring(zf.read(name))
            current: list[str] = []
            for elem in root.iter():
                local = elem.tag.rsplit("}", 1)[-1]
                if local == "t" and elem.text:
                    current.append(elem.text)
                elif local in {"tab"}:
                    current.append("\t")
                elif local in {"br", "cr"}:
                    current.append("\n")
                elif local in {"p", "tr"} and current:
                    line = "".join(current).strip()
                    if line:
                        output.append(line)
                    current = []
            if current:
                line = "".join(current).strip()
                if line:
                    output.append(line)
        return "\n".join(output).strip()


def natural_key(value: str):
    return [int(x) if x.isdigit() else x.lower() for x in re.split(r"(\d+)", value)]


def extract_pptx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        slides = sorted(
            (n for n in zf.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
            key=natural_key,
        )
        out: list[str] = []
        for i, name in enumerate(slides, 1):
            root = ET.fromstring(zf.read(name))
            texts = [t.strip() for t in xml_texts(root, "t") if t.strip()]
            out.append(f"[Slide {i}]")
            out.extend(texts)
            out.append("")
        return "\n".join(out).strip()


def cell_col(ref: str) -> int:
    m = re.match(r"([A-Z]+)", ref.upper())
    if not m:
        return 0
    n = 0
    for ch in m.group(1):
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def extract_xlsx_text(path: Path) -> str:
    ns_main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    ns_rel_doc = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    ns_rel_pkg = "http://schemas.openxmlformats.org/package/2006/relationships"

    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall(f"{{{ns_main}}}si"):
                shared.append("".join(xml_texts(si, "t")))

        rel_map: dict[str, str] = {}
        if "xl/_rels/workbook.xml.rels" in names:
            relroot = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
            for rel in relroot.findall(f"{{{ns_rel_pkg}}}Relationship"):
                rid = rel.attrib.get("Id", "")
                target = rel.attrib.get("Target", "")
                if target.startswith("/"):
                    target = target.lstrip("/")
                elif not target.startswith("xl/"):
                    target = "xl/" + target.lstrip("./")
                rel_map[rid] = target

        sheets: list[tuple[str, str]] = []
        if "xl/workbook.xml" in names:
            wbroot = ET.fromstring(zf.read("xl/workbook.xml"))
            for sheet in wbroot.findall(f".//{{{ns_main}}}sheet"):
                name = sheet.attrib.get("name", "Sheet")
                rid = sheet.attrib.get(f"{{{ns_rel_doc}}}id", "")
                target = rel_map.get(rid, "")
                if target in names:
                    sheets.append((name, target))

        if not sheets:
            fallback = sorted((n for n in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)), key=natural_key)
            sheets = [(Path(n).stem, n) for n in fallback]

        out: list[str] = []
        for sheet_name, xml_name in sheets:
            out.append(f"[Sheet: {sheet_name}]")
            root = ET.fromstring(zf.read(xml_name))
            for row in root.findall(f".//{{{ns_main}}}row"):
                cells: dict[int, str] = {}
                max_col = -1
                for c in row.findall(f"{{{ns_main}}}c"):
                    ref = c.attrib.get("r", "")
                    col = cell_col(ref)
                    max_col = max(max_col, col)
                    ctype = c.attrib.get("t", "")
                    value = ""
                    if ctype == "inlineStr":
                        value = "".join(xml_texts(c, "t"))
                    else:
                        v = c.find(f"{{{ns_main}}}v")
                        raw = v.text if v is not None and v.text is not None else ""
                        if ctype == "s" and raw.isdigit():
                            idx = int(raw)
                            value = shared[idx] if 0 <= idx < len(shared) else raw
                        elif ctype == "b":
                            value = "TRUE" if raw == "1" else "FALSE"
                        else:
                            value = raw
                    cells[col] = value
                if max_col >= 0:
                    row_values = [cells.get(i, "") for i in range(max_col + 1)]
                    if any(v != "" for v in row_values):
                        out.append("\t".join(row_values))
            out.append("")
        return "\n".join(out).strip()


def extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("bundled pypdf module is missing") from exc

    reader = PdfReader(str(path))
    if reader.is_encrypted:
        # Empty-password PDFs are fairly common; try them without prompting.
        try:
            unlocked = reader.decrypt("")
        except Exception:
            unlocked = 0
        if not unlocked:
            raise RuntimeError("encrypted PDF (password required or unsupported encryption)")

    out: list[str] = []
    for i, page in enumerate(reader.pages, 1):
        out.append(f"[Page {i}]")
        try:
            out.append((page.extract_text() or "").strip())
        except Exception as exc:
            out.append(f"[text extraction error: {type(exc).__name__}: {exc}]")
        out.append("")
    return "\n".join(out).strip()


def extract_readable_text(path: Path) -> tuple[str | None, str]:
    ext = path.suffix.lower()
    try:
        if ext in TEXT_EXTS:
            raw = path.read_bytes()
            text = decode_bytes(raw)
            if ext in {".html", ".htm"}:
                text = html_to_text(text)
            return text, "text"
        if ext == ".docx":
            return extract_docx_text(path), "docx"
        if ext == ".pptx":
            return extract_pptx_text(path), "pptx"
        if ext == ".xlsx":
            return extract_xlsx_text(path), "xlsx"
        if ext == ".eml":
            with path.open("rb") as f:
                msg = BytesParser(policy=policy.default).parse(f)
            return render_mail_text(msg), "eml"
        if ext == ".pdf":
            return extract_pdf_text(path), "pdf"
        return None, "unsupported"
    except Exception as exc:
        return None, f"read-error: {type(exc).__name__}: {exc}"


def payload_text(part: Message) -> str:
    try:
        content = part.get_content()
        if isinstance(content, str):
            return content
    except Exception:
        pass
    data = part.get_payload(decode=True)
    if isinstance(data, bytes):
        return decode_bytes(data)
    raw = part.get_payload()
    return raw if isinstance(raw, str) else ""


def get_mail_body(msg: Message) -> tuple[str, str]:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.is_multipart():
                continue
            disp = (part.get_content_disposition() or "").lower()
            if disp == "attachment" or part.get_filename():
                continue
            ctype = part.get_content_type().lower()
            if ctype == "text/plain":
                plain_parts.append(payload_text(part))
            elif ctype == "text/html":
                html_parts.append(payload_text(part))
    else:
        ctype = msg.get_content_type().lower()
        if ctype == "text/plain":
            plain_parts.append(payload_text(msg))
        elif ctype == "text/html":
            html_parts.append(payload_text(msg))

    plain = "\n\n".join(p.strip() for p in plain_parts if p.strip()).strip()
    html_text = "\n\n".join(html_to_text(p) for p in html_parts if p.strip()).strip()
    return plain or html_text, "plain" if plain else ("html" if html_text else "none")


def render_mail_text(msg: Message) -> str:
    body, body_kind = get_mail_body(msg)
    fields = [
        ("Subject", str(msg.get("Subject", ""))),
        ("From", str(msg.get("From", ""))),
        ("To", str(msg.get("To", ""))),
        ("Cc", str(msg.get("Cc", ""))),
        ("Date", str(msg.get("Date", ""))),
        ("Message-ID", str(msg.get("Message-ID", ""))),
    ]
    lines = [f"{key}: {value}" for key, value in fields]
    lines += ["", f"[Body: {body_kind}]", body]
    return "\n".join(lines).strip() + "\n"


def attachment_parts(msg: Message) -> Iterable[Message]:
    for part in msg.walk():
        if part is msg:
            continue
        # message/rfc822 attachments may report is_multipart() == True.
        if part.is_multipart() and part.get_content_type().lower() != "message/rfc822":
            continue
        disp = (part.get_content_disposition() or "").lower()
        filename = part.get_filename()
        if disp == "attachment" or filename:
            yield part


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

    if part.get_content_type().lower() == "message/rfc822":
        payload = part.get_payload()
        data = b""
        if isinstance(payload, list) and payload:
            nested = payload[0]
            cte = (part.get("Content-Transfer-Encoding", "") or "").lower().strip()
            # Some producers encode an RFC822 attachment as base64 and the email
            # parser represents the encoded block as a headerless nested message.
            if not list(nested.items()) and isinstance(nested.get_payload(), str) and cte in {"base64", "quoted-printable"}:
                raw = nested.get_payload().encode("ascii", errors="ignore")
                if cte == "base64":
                    try:
                        data = base64.b64decode(raw, validate=False)
                    except Exception:
                        data = raw
                else:
                    data = quopri.decodestring(raw)
            else:
                data = nested.as_bytes(policy=policy.default)
        else:
            data = part.get_payload(decode=True) or b""
        if target.suffix.lower() != ".eml":
            target = unique_path(target.with_suffix(target.suffix + ".eml" if target.suffix else ".eml"))
    else:
        data = part.get_payload(decode=True)
        if data is None:
            raw = part.get_payload()
            data = raw.encode("utf-8", errors="replace") if isinstance(raw, str) else b""

    target.write_bytes(data)
    return target


def process_eml(eml_path: Path, source_root: Path, output_root: Path) -> tuple[int, list[AttachmentRecord], str | None]:
    try:
        with eml_path.open("rb") as f:
            msg = BytesParser(policy=policy.default).parse(f)
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
    if target.is_file():
        if target.suffix.lower() != ".eml":
            raise ValueError("EML 파일 또는 EML 파일이 들어 있는 폴더를 지정해 주세요.")
        return target.parent, [target]
    if target.is_dir():
        files = sorted(
            (p for p in target.rglob("*.eml") if OUTPUT_DIR_NAME not in p.parts),
            key=lambda p: str(p).lower(),
        )
        return target, files
    raise FileNotFoundError(f"경로를 찾을 수 없습니다: {target}")


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
