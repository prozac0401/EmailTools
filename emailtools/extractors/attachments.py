"""One decoded payload per MIME attachment, reused by selected extractors."""
from __future__ import annotations

from dataclasses import dataclass
from email.message import Message
from functools import cached_property
from pathlib import Path

from emailtools import reader
from emailtools.paths import safe_name


@dataclass
class AttachmentSource:
    part: Message
    index: int

    @property
    def name(self) -> str:
        name = safe_name(self.part.get_filename(), f"attachment_{self.index:03d}")
        if self.content_type == "message/rfc822" and Path(name).suffix.lower() != ".eml":
            name += ".eml"
        return name

    @property
    def content_type(self) -> str:
        return self.part.get_content_type().lower()

    @cached_property
    def payload(self) -> bytes:
        return reader.attachment_bytes(self.part)


def collect(msg: Message) -> list[AttachmentSource]:
    return [AttachmentSource(part, i) for i, part in enumerate(reader.attachment_parts(msg), 1)]
