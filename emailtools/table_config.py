"""Column validation and projection shared by preview, GUI export and CLI."""
from __future__ import annotations
import logging
from emailtools.extractors import tables
from emailtools.exporters import excel


def validate_columns(specs: object, available: list[str]) -> list[dict]:
    if not isinstance(specs, list) or len(specs) > 16384:
        raise ValueError("열 설정이 올바르지 않습니다. 최대 16,384열까지 가능합니다.")
    result, names, sources = [], set(), set()
    for spec in specs:
        if not isinstance(spec, dict) or type(spec.get("enabled")) is not bool:
            raise ValueError("열 설정이 올바르지 않습니다.")
        if not spec["enabled"]:
            continue
        name, source, value = spec.get("name"), spec.get("source"), spec.get("value", "")
        if not isinstance(name, str) or not isinstance(value, str):
            raise ValueError("열 이름과 기본값은 문자열이어야 합니다.")
        name = tables.normalize_value(name).strip()
        if not name or len(name) > 120 or "\n" in name or tables.ILLEGAL_XML_CHARS.search(name):
            raise ValueError("열 이름은 줄바꿈 없는 1~120자로 입력해 주세요.")
        if name.casefold() in names:
            raise ValueError(f"중복된 열 이름입니다: {name}")
        if source is not None:
            if not isinstance(source, str) or source not in available or source in sources:
                raise ValueError("원본 열 설정이 올바르지 않습니다.")
            sources.add(source)
        names.add(name.casefold())
        result.append({"source": source, "name": name, "value": value})
    if not result:
        raise ValueError("저장할 열을 하나 이상 선택해 주세요.")
    return result


def default_columns(columns: list[str]) -> list[dict]:
    return [{"source": name, "name": name, "value": "", "enabled": True} for name in columns]


def project_records(records: list[dict], specs: list[dict], logger: logging.Logger | None = None) -> list[dict]:
    """Project raw export data, or sanitize once for the on-screen Excel preview."""
    def value_for(record, spec):
        value = record.get(spec["source"], "") if spec["source"] is not None else spec["value"]
        return excel.safe_excel_value(value, logger, f"{record.get('source_eml', '')} / {spec['name']}") if logger is not None else value
    return [{spec["name"]: value_for(record, spec) for spec in specs} for record in records]
