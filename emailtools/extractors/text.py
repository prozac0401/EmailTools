from __future__ import annotations
import re
import zipfile
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Iterable
import xml.etree.ElementTree as ET

from io import BytesIO
from emailtools.reader import decode_bytes, html_to_text, render_mail_text

TEXT_EXTS = {
    ".txt", ".csv", ".tsv", ".json", ".xml", ".html", ".htm", ".md",
    ".log", ".ini", ".yaml", ".yml", ".sql", ".py", ".js", ".css",
}

MAX_OFFICE_XML_BYTES = 32 * 1024 * 1024


def read_xml(archive: zipfile.ZipFile, name: str) -> ET.Element:
    info = archive.getinfo(name)
    if info.file_size > MAX_OFFICE_XML_BYTES:
        raise ValueError(f"Office XML exceeds {MAX_OFFICE_XML_BYTES} bytes: {name}")
    return ET.fromstring(archive.read(info))

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
            root = read_xml(zf, name)
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
            root = read_xml(zf, name)
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
            root = read_xml(zf, "xl/sharedStrings.xml")
            for si in root.findall(f"{{{ns_main}}}si"):
                shared.append("".join(xml_texts(si, "t")))

        rel_map: dict[str, str] = {}
        if "xl/_rels/workbook.xml.rels" in names:
            relroot = read_xml(zf, "xl/_rels/workbook.xml.rels")
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
            wbroot = read_xml(zf, "xl/workbook.xml")
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
            root = read_xml(zf, xml_name)
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

    reader = PdfReader(str(path) if isinstance(path, Path) else path)
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
    try:
        return extract_content(path.name, path.read_bytes())
    except Exception as exc:
        return None, f"read-error: {type(exc).__name__}: {exc}"


def extract_content(name: str, payload: bytes) -> tuple[str | None, str]:
    """Analyze bytes directly, without saving an attachment just to read it."""
    ext = Path(name).suffix.lower()
    try:
        if ext in TEXT_EXTS:
            raw = payload
            text = decode_bytes(raw)
            if ext in {".html", ".htm"}:
                text = html_to_text(text)
            return text, "text"
        if ext == ".docx":
            return extract_docx_text(BytesIO(payload)), "docx"
        if ext == ".pptx":
            return extract_pptx_text(BytesIO(payload)), "pptx"
        if ext == ".xlsx":
            return extract_xlsx_text(BytesIO(payload)), "xlsx"
        if ext == ".eml":
            msg = BytesParser(policy=policy.default).parsebytes(payload)
            return render_mail_text(msg), "eml"
        if ext == ".pdf":
            return extract_pdf_text(BytesIO(payload)), "pdf"
        return None, "unsupported"
    except Exception as exc:
        return None, f"read-error: {type(exc).__name__}: {exc}"
