from __future__ import annotations
import base64
import hashlib
import html
import os
import quopri
import re
from email import policy
from email.message import Message
from email.parser import BytesParser
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterable

from emailtools.paths import safe_name

JOB_MARKER = ".emailtools-job.json"


def find_eml_targets(target: Path, is_cancelled: Callable[[], bool] | None = None) -> tuple[Path, list[Path]]:
    """Search once, pruning old/new output folders and directory links."""
    target = target.expanduser().resolve()
    if target.is_file() and target.suffix.lower() == ".eml":
        return target.parent, [target]
    if not target.is_dir():
        raise FileNotFoundError(f"EML 파일 또는 폴더를 찾을 수 없습니다: {target}")
    result = []
    def on_error(error: OSError) -> None:
        raise error
    for current, directories, filenames in os.walk(target, followlinks=False, onerror=on_error):
        if is_cancelled and is_cancelled():
            raise InterruptedError("분석을 중지했습니다. 결과는 저장하지 않았습니다.")
        folder = Path(current)
        if (folder / JOB_MARKER).is_file():
            directories[:] = []
            continue
        directories[:] = [name for name in sorted(directories, key=str.casefold)
                          if name.casefold() != "_eml_output"
                          and not name.startswith(".emailtools-job-")
                          and not (folder / name).is_symlink()
                          and not getattr(folder / name, "is_junction", lambda: False)()]
        result.extend(folder / name for name in filenames
                      if name.lower().endswith(".eml") and not (folder / name).is_symlink())
    return target, sorted(result, key=lambda p: str(p.relative_to(target)).casefold())


def read_message(path: Path) -> Message:
    data = path.read_bytes()
    msg = BytesParser(policy=policy.default).parsebytes(data)
    msg._emailtools_hash = hashlib.sha256(data).hexdigest()
    return msg


def body_parts(msg: Message) -> Iterable[Message]:
    """Only this mail's body; never descend into an attachment's MIME tree."""
    if msg.get_content_disposition() == "attachment" or msg.get_filename():
        return
    if msg.get_content_type().lower() == "message/rfc822":
        return
    if msg.is_multipart():
        for child in msg.get_payload():
            yield from body_parts(child)
    else:
        yield msg

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


def decode_bytes(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr", "utf-16", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


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
        for part in body_parts(msg):
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
    if not msg.is_multipart():
        return
    for part in msg.get_payload():
        disp = (part.get_content_disposition() or "").lower()
        filename = part.get_filename()
        if disp == "attachment" or filename:
            yield part
        elif part.get_content_type().lower() != "message/rfc822":
            yield from attachment_parts(part)


def attachment_bytes(part: Message) -> bytes:
    """Decode an attachment payload without writing it to disk."""
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
        return data

    data = part.get_payload(decode=True)
    if data is not None:
        return data
    raw = part.get_payload()
    return raw.encode("utf-8", errors="replace") if isinstance(raw, str) else b""
