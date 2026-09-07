"""Shared options and analysis results. Analysis never writes final output."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


@dataclass(frozen=True)
class ProcessingOptions:
    save_mail: bool = False
    save_attachments: bool = False
    extract_text: bool = False
    extract_tables: bool = True
    email_tables: bool = True
    docx_tables: bool = True

    @classmethod
    def from_dict(cls, value: object = None) -> ProcessingOptions:
        if value is None:
            return cls()
        allowed = {item.name for item in fields(cls)}
        if not isinstance(value, dict) or set(value) - allowed:
            raise ValueError("처리 옵션이 올바르지 않습니다.")
        if any(type(v) is not bool for v in value.values()):
            raise ValueError("처리 옵션은 선택 또는 해제 값이어야 합니다.")
        options = cls(**value)
        options.validate()
        return options

    def validate(self) -> None:
        if not any((self.save_mail, self.save_attachments, self.extract_text, self.extract_tables)):
            raise ValueError("실행할 기능을 하나 이상 선택해 주세요.")
        if self.extract_tables and not (self.email_tables or self.docx_tables):
            raise ValueError("표 추출 대상을 하나 이상 선택해 주세요: 메일 본문 또는 DOCX.")

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class AttachmentResult:
    name: str
    content_type: str
    size: int
    payload_path: Path | None = None
    text: str | None = None
    text_status: str = "not requested"
    error: str = ""


@dataclass
class MailResult:
    record: dict[str, str]
    body: str = ""
    attachments: list[AttachmentResult] = field(default_factory=list)


@dataclass
class AnalysisResult:
    source_root: Path
    options: ProcessingOptions
    mails: list[MailResult]
    records: list[dict[str, str]]
    columns: list[str]
    success: int
    warnings: int
    failures: int

    @property
    def attachment_count(self) -> int:
        return sum(len(mail.attachments) for mail in self.mails)
