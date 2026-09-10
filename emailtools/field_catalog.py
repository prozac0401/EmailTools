"""Provenance-preserving table analysis for the native desktop workflow.

Legacy extraction remains available to the existing CLI and browser interface.
No email HTML is rendered. Nested tables have independent physical cell owners.
"""
from __future__ import annotations
import hashlib
import statistics
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from html.parser import HTMLParser
from io import BytesIO
import xml.etree.ElementTree as ET

from emailtools import reader
from emailtools.extractors import tables as core


def stable_id(prefix, value):
    return prefix + hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


@dataclass
class Cell:
    row: int
    column: int
    text: str = ""
    header: bool = False
    rowspan: int = 1
    colspan: int = 1
    continuation: bool = False


@dataclass
class ParsedTable:
    table_id: str
    mail_id: str
    mail_hash: str
    document_id: str
    source_kind: str
    source_name: str
    table_index: int
    cells: list[Cell]
    nested: bool = False
    content_hash: str = ""
    shape: str = "uncertain"
    reasons: str = "항목/값 구조인지 원본 확인이 필요합니다."
    override: str = ""

    def rows(self):
        rows = defaultdict(list)
        for cell in self.cells:
            rows[cell.row].append(cell)
        return [sorted(row, key=lambda c: c.column) for _, row in sorted(rows.items())]

    def pairs(self):
        for row in self.rows():
            for key, value in zip(row[::2], row[1::2]):
                name = core.normalize_key(key.text)
                if name and not core._is_header_pair(name, core.normalize_value(value.text)) and not key.continuation and not value.continuation:
                    yield key, value


class SourceHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self.stack = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "style"):
            self.skip += 1
        if tag == "table":
            if self.stack:
                self.stack[-1]["nested"] = True
            table = dict(cells=[], row=-1, cell=None, occupied=set(), nested=False, head=False)
            self.tables.append(table)
            self.stack.append(table)
        elif self.stack:
            table = self.stack[-1]
            if tag == "thead":
                table["head"] = True
            elif tag == "tr":
                table["row"] += 1
                table["cell"] = None
            elif tag in ("th", "td"):
                row = max(0, table["row"])
                column = 0
                while (row, column) in table["occupied"]:
                    column += 1
                def span(name):
                    try:
                        return max(1, min(1000, int(attrs.get(name, 1))))
                    except ValueError:
                        return 1
                cell = Cell(row, column, header=tag == "th" or table["head"],
                            rowspan=span("rowspan"), colspan=span("colspan"))
                table["cells"].append(cell)
                table["cell"] = cell
                # Reserve columns for merged cells without duplicating their text.
                for r in range(row, row + cell.rowspan):
                    for c in range(column, column + cell.colspan):
                        table["occupied"].add((r, c))
            elif tag == "br" and table["cell"]:
                table["cell"].text += "\n"

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        if not self.stack:
            return
        if tag == "table":
            self.stack.pop()
        elif tag in ("td", "th", "tr"):
            self.stack[-1]["cell"] = None
        elif tag == "thead":
            self.stack[-1]["head"] = False
        elif tag in ("p", "div", "li") and self.stack[-1]["cell"]:
            self.stack[-1]["cell"].text += "\n"

    def handle_data(self, value):
        if not self.skip and self.stack and self.stack[-1]["cell"]:
            self.stack[-1]["cell"].text += value


@dataclass(frozen=True)
class Occurrence:
    field_id: str
    name: str
    value: str
    table_id: str
    mail_id: str
    mail_hash: str
    document_id: str
    source_kind: str
    source_name: str
    key_position: tuple[int, int]
    value_position: tuple[int, int]
    trusted: bool


class FieldCatalog:
    def __init__(self):
        self.tables: list[ParsedTable] = []
        self.occurrences: dict[str, list[Occurrence]] = {}
        self.fields: dict[str, dict] = {}
        self.mails = []
        self._scopes = {}

    def _append(self, mail, digest, document, kind, source, cells, nested=False, content_hash=""):
        index = sum(t.document_id == document for t in self.tables) + 1
        self.tables.append(ParsedTable(stable_id("table:", f"{document}:{index}"), mail, digest,
            document, kind, source, index, cells, nested, content_hash))

    def read_body(self, msg, mail, digest, enabled, logger, record):
        if not enabled:
            return
        try:
            for part in reader.body_parts(msg):
                if part.get_content_type() != "text/html":
                    continue
                parser = SourceHTMLParser()
                parser.feed(reader.payload_text(part))
                parser.close()
                for table in parser.tables:
                    if table["cells"]:
                        self._append(mail, digest, mail + ":body", "email", mail, table["cells"], table["nested"])
        except Exception as exc:
            record["_status"] = "EMAIL TABLE ERROR"
            record["_error"] = f"본문 표: {exc}"
            logger.exception("EMAIL TABLE ERROR: %s", mail)

    def read_docx(self, payload, mail, digest, index, filename):
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > core.MAX_DOCX_XML_BYTES:
                raise ValueError("Word XML 크기 제한을 초과했습니다.")
            root = ET.fromstring(archive.read(info))
        ns = core.WORD_NAMESPACES
        count = 0
        for table in root.iter(f"{{{core.WORD_NS}}}tbl"):
            cells = []
            for r, row in enumerate(table.findall("./w:tr", ns)):
                offset = row.find("./w:trPr/w:gridBefore", ns)
                c = int(offset.get(f"{{{core.WORD_NS}}}val", "0")) if offset is not None else 0
                header = row.find("./w:trPr/w:tblHeader", ns) is not None
                for cell in row.findall("./w:tc", ns):
                    # Reuse existing Word text semantics (content controls,
                    # breaks, tabs, displayed field values), excluding inner tables.
                    text = core._docx_cell_text(cell, include_nested_tables=False)
                    span = cell.find("./w:tcPr/w:gridSpan", ns)
                    width = max(1, min(1000, int(span.get(f"{{{core.WORD_NS}}}val", "1")))) if span is not None else 1
                    merge = cell.find("./w:tcPr/w:vMerge", ns)
                    continuation = merge is not None and merge.get(f"{{{core.WORD_NS}}}val") != "restart"
                    cells.append(Cell(r, c, text, header, 2 if merge is not None else 1, width, continuation))
                    c += width
            if cells:
                self._append(mail, digest, f"{mail}:docx:{index}", "docx", filename, cells,
                    table.find(".//w:tc/w:tbl", ns) is not None, hashlib.sha256(payload).hexdigest())
                count += 1
        return count

    def classify(self):
        for table in self.tables:
            rows = table.rows()
            table.shape, table.reasons = "uncertain", "명확한 항목/값 헤더가 없어 확인이 필요합니다."
            if table.override:
                table.shape, table.reasons = table.override, "사용자가 원본 표를 확인하고 지정했습니다."
            elif rows and any(core._is_header_pair(core.normalize_key(a.text), core.normalize_value(b.text))
                    for a, b in zip(rows[0][::2], rows[0][1::2])):
                table.shape, table.reasons = "key_value", "명시적인 항목/값 머리글을 발견했습니다."
            elif rows and len(rows) >= 2 and (all(c.header for c in rows[0]) or
                    sum(core.normalize_key(c.text) in {"이름", "성명", "부서", "연락처", "이메일", "수량", "단가", "금액", "주문번호"} for c in rows[0]) >= 2):
                table.shape, table.reasons = "records", "머리글 아래에 명단·내역 행이 이어지는 표입니다."
            elif table.nested or not list(table.pairs()):
                table.shape, table.reasons = "layout", "중첩 또는 배치 구조가 포함되어 있습니다."
        # Repeated ordered labels in at least two independent EML originals.
        label_index = defaultdict(list)
        signatures = {}
        for table in self.tables:
            if table.shape in ("uncertain", "key_value"):
                labels = tuple(core.normalize_key(k.text) for k, v in table.pairs()
                               if k.colspan == v.colspan == k.rowspan == v.rowspan == 1)
                signatures[table.table_id] = labels
                for pair in zip(labels, labels[1:]):
                    label_index[pair].append(table)
        for table in self.tables:
            if table.shape != "uncertain" or table.override:
                continue
            labels = signatures[table.table_id]
            for pair in zip(labels, labels[1:]):
                matches = label_index[pair]
                if any(other.mail_hash != table.mail_hash and
                        len(set(labels) & set(signatures[other.table_id])) >= max(2, len(labels) / 2)
                        for other in matches):
                    table.shape, table.reasons = "key_value", "서로 다른 원본 메일 2개 이상에서 항목 양식이 반복됩니다."
                    break

    def finalize(self, mails, cancelled=None, status=None):
        self.mails = mails
        self.classify()
        self.occurrences = {}
        self._scopes = {}
        for i, table in enumerate(self.tables):
            if cancelled and cancelled():
                raise InterruptedError("항목 정리를 중지했습니다.")
            for key, value in table.pairs():
                name = core.normalize_key(key.text)
                fid = stable_id("field:", name)
                trusted = table.shape == "key_value" and all(c.rowspan == c.colspan == 1 for c in (key, value))
                occurrence = Occurrence(fid, name, core.normalize_value(value.text), table.table_id,
                    table.mail_id, table.mail_hash, table.document_id, table.source_kind, table.source_name,
                    (key.row, key.column), (value.row, value.column), trusted)
                self.occurrences.setdefault(fid, []).append(occurrence)
            if status and (i % 50 == 0 or i == len(self.tables) - 1):
                status(dict(phase="항목 정리", completed=i + 1, total=len(self.tables), current=table.source_name, cancellable=True))
        previous_keys = {f["record_key"] for f in self.fields.values()}
        for mail in mails:
            for key in previous_keys:
                mail.record.pop(key, None)
        used = set(core.SYSTEM_COLUMNS)
        self.fields = {}
        for fid, entries in self.occurrences.items():
            name = entries[0].name
            key = core._record_data_key(name)
            while key in used:
                key = "item_" + key
            used.add(key)
            self.fields[fid] = dict(id=fid, name=name, record_key=key)
            by_mail = defaultdict(list)
            for item in entries:
                if item.value and item.value not in by_mail[item.mail_id]:
                    by_mail[item.mail_id].append(item.value)
            for mail in mails:
                mail.record[key] = core.DUPLICATE_VALUE_SEPARATOR.join(by_mail[mail.record["source_eml"]])
        for scope in ("all", "email", "docx"):
            self._scopes[scope] = self._statistics(scope)

    def _statistics(self, scope):
        result = []
        for order, (fid, raw) in enumerate(self.occurrences.items()):
            entries = [o for o in raw if scope == "all" or o.source_kind == scope]
            if not entries:
                continue
            documents = Counter(o.document_id for o in entries)
            representatives = {}
            for o in entries:
                representatives.setdefault(o.mail_hash, o.mail_id)
            effective = [o for o in entries if representatives[o.mail_hash] == o.mail_id]
            effective_docs = Counter(o.document_id for o in effective)
            single = sum(n == 1 for n in documents.values()) / len(documents)
            e_single = sum(n == 1 for n in effective_docs.values()) / len(effective_docs)
            filled = sum(bool(o.value) for o in entries) / len(entries)
            e_filled = sum(bool(o.value) for o in effective) / len(effective)
            values = list(dict.fromkeys(o.value for o in entries if o.value))
            review = any(not o.trusted for o in entries)
            common = len(representatives) >= 2 and e_single >= .8 and e_filled >= .8 and not review
            flags = []
            if common:
                flags.append("common")
            if len(representatives) == 1:
                flags.append("rare")
            if 1 - e_single > .2 + 1e-9:
                flags.append("repeated")
            if review:
                flags.append("review")
            result.append({**self.fields[fid], "mail_count": len({o.mail_id for o in entries}),
                "total_mail_count": len(self.mails), "effective_mail_count": len(representatives),
                "document_count": len(documents), "occurrence_count": len(entries),
                "single_document_ratio": single, "filled_ratio": filled,
                "effective_single_ratio": e_single, "effective_filled_ratio": e_filled,
                "median_occurrences": statistics.median(documents.values()), "max_occurrences": max(documents.values()),
                "distinct_value_count": len(values), "examples": values[:3], "values": values,
                "flags": flags, "first_seen": order, "common": common})
        return result

    def query(self, *, scope="all", query="", search_values=False, category="all", sort="common", selected=(), page=0, page_size=50):
        all_fields = self._scopes.get(scope, [])
        available = [f for f in all_fields if f["id"] not in selected]
        counts = {key: sum(key in f["flags"] for f in available) for key in ("common", "rare", "repeated", "review")}
        needle = query.casefold().strip()
        found = [f for f in available if (category == "all" or category in f["flags"]) and
                 (not needle or needle in f["name"].casefold() or
                  (search_values and any(needle in v.casefold() for v in f["values"])))]
        keys = {
            "common": lambda f: (-f["common"], -f["effective_mail_count"], -f["effective_single_ratio"], -f["effective_filled_ratio"], f["first_seen"]),
            "coverage": lambda f: (-f["effective_mail_count"], f["first_seen"]),
            "repeat": lambda f: (f["median_occurrences"], f["max_occurrences"], -f["mail_count"], f["first_seen"]),
            "first": lambda f: f["first_seen"],
        }
        found.sort(key=keys[sort])
        return dict(fields=found[page * page_size:(page + 1) * page_size], total=len(found), counts=counts,
                    common=[f["id"] for f in available if f["common"]])

    def detail(self, field_id, scope="all"):
        return next((f for f in self._scopes.get(scope, []) if f["id"] == field_id), None)

    def override_table(self, table_id, shape):
        if shape not in ("", "key_value", "records", "layout", "uncertain"):
            raise ValueError("알 수 없는 표 해석입니다.")
        table = next(t for t in self.tables if t.table_id == table_id)
        table.override = shape
        self.finalize(self.mails)
