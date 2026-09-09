"""Synthetic EML/DOCX examples shared by desktop and legacy tests."""
from pathlib import Path
from email.message import EmailMessage
from io import BytesIO
import zipfile
from xml.sax.saxutils import escape
from emailtools.extractors import tables as core

def create_demo(folder: Path) -> None:
    """Synthetic mail and DOCX files exercise the real extraction pipeline."""
    examples = [
        ("AI 업무 활용", "김민지", "2026.09.01", "매우 만족", "실습 예제가 유익했습니다.", "서울"),
        ("Python 데이터 분석", "이준호", "2026.09.02", "만족", "실습 시간을 늘려 주세요.", "부산"),
        ("협업 도구 기초", "박서연", "2026.09.03", "", "", ""),
    ]
    for index, (course, teacher, date, rating, comment, location) in enumerate(examples, 1):
        msg = EmailMessage()
        msg["Subject"] = f"[교육 결과] {course}"
        msg["From"] = "training@example.com"
        msg["To"] = "team@example.com"
        msg["Date"] = "Thu, 03 Sep 2026 10:00:00 +0900"
        msg.set_content("기능 확인을 위한 합성 샘플입니다.")
        msg.add_alternative(
            f"<table><tr><td>교육명</td><td>{course}</td></tr>"
            f"<tr><td>강사</td><td>{teacher}</td></tr>"
            f"<tr><td>교육일</td><td>{date}</td></tr></table>", subtype="html")
        if rating:
            rows = [["과정 평가", rating], ["주요 의견", comment], ["교육장", location]]
            if index == 2:
                rows.append(["참석 인원", "24"])
            xml_rows = "".join("<w:tr>" + "".join(
                f"<w:tc><w:p><w:r><w:t>{escape(cell)}</w:t></w:r></w:p></w:tc>"
                for cell in row) + "</w:tr>" for row in rows)
            payload = BytesIO()
            with zipfile.ZipFile(payload, "w") as archive:
                archive.writestr("word/document.xml", f'<w:document xmlns:w="{core.WORD_NS}">'
                                 f"<w:body><w:tbl>{xml_rows}</w:tbl></w:body></w:document>")
            msg.add_attachment(payload.getvalue(), maintype="application",
                               subtype="vnd.openxmlformats-officedocument.wordprocessingml.document",
                               filename=f"교육평가_{index:02d}.docx")
        (folder / f"교육결과_{index:02d}.eml").write_bytes(msg.as_bytes())
