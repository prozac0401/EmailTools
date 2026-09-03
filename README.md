# EmailTools

Windows 환경에서 이메일 파일을 처리하기 위한 유틸리티 모음입니다.

## Tools

### EML Attachment Tool

`eml_attachment_tool/`에 포함된 Windows 포터블 도구입니다.

- EML 메일 정보 및 본문 추출
- 첨부파일 원본 저장
- DOCX / XLSX / PPTX 내용 추출
- PDF 텍스트 추출
- 첨부 EML 분석
- 단일 파일 및 폴더 일괄 처리(하위 폴더 포함)
- 동일한 첨부파일명 충돌 회피
- 시스템 Python 설치 불필요
- Windows Embedded Python 기반 포터블 실행

### 실행 방법

`eml_attachment_tool` 폴더의 다음 파일을 실행합니다.

```text
run.bat
```

또는 EML 파일이나 EML 파일이 들어 있는 폴더를 `run.bat`에 Drag & Drop합니다.
자세한 사용법은 [`eml_attachment_tool/README.md`](eml_attachment_tool/README.md)를 참고하세요.

### Python 구조

이 도구는 시스템에 설치된 Python이나 PATH의 `python`, `py` 명령을 사용하지 않습니다.
항상 프로그램 폴더 내부의 다음 런타임만 사용합니다.

```text
.\python\python.exe
```

런타임이 없으면 `setup_embedded_python.bat`이 Python.org의 Python 3.13.15 x64
Windows Embeddable Package를 자동 구성합니다. 오프라인에서는
`python-3.13.15-embed-amd64.zip`을 `eml_attachment_tool` 폴더에 미리 둘 수 있습니다.
PDF 처리를 위한 `pypdf 5.9.0`은 `vendor/`에 포함되어 있어 사용자에게 별도
`pip install`을 요구하지 않습니다.

### 주의

암호화, DRM 또는 암호가 적용된 EML이나 첨부파일은 원본 추출이 가능하더라도
본문 또는 첨부파일 내용 분석이 제한될 수 있습니다. 추출된 실행 파일이나
스크립트는 실행하지 않으며 데이터로만 저장합니다.

### EML Table to Excel

`eml_table_to_excel/`은 여러 EML의 메일 본문 표와 DOCX 첨부파일 내부 표를
읽고, 항목명을 자동으로 Excel 컬럼으로 매핑하여 하나의 Worksheet로 통합하는
전용 도구입니다.

- 하나의 EML을 Excel의 한 행으로 변환
- HTML 메일 표와 DOCX 표의 `항목명 → 값` 자동 추출
- 새로운 항목을 최초 등장 순서대로 새 컬럼에 자동 추가
- 중복되거나 충돌하는 값은 덮어쓰지 않고 함께 보존
- 결과: `EML_Table_Result.xlsx`, Worksheet `Result`
- 기존 Windows Embedded Python을 공유하고 bundled `openpyxl` 사용

실행:

```text
eml_table_to_excel\run.bat
```

EML 폴더를 `run.bat`에 Drag & Drop할 수도 있습니다. 자세한 내용은
[`eml_table_to_excel/README.md`](eml_table_to_excel/README.md)를 참고하세요.

## Portable package

자동 구성 가능한 포터블 배포본은
`packages/EML_Attachment_Tool_v1.0_portable.zip`에 보관합니다.

## 테스트

테스트는 실제 개인 메일을 사용하지 않고 실행 시 임시 폴더에 합성 EML과
DOCX / XLSX / PPTX / PDF 데이터를 생성합니다. EML Table to Excel 테스트도
합성 HTML 표와 DOCX 표만 사용합니다.

```powershell
python -m unittest discover -s .\tests -v
```

위 명령의 시스템 Python은 개발 테스트에만 사용합니다. 일반 사용자의 프로그램
실행 경로는 계속 `run.bat`과 `.\python\python.exe`로 제한됩니다. Embedded
Python 구성이 끝난 뒤에는 다음 명령으로 같은 테스트를 실행할 수도 있습니다.

```powershell
.\eml_attachment_tool\python\python.exe -X utf8 .\tests\test_app.py -v
.\eml_attachment_tool\python\python.exe -X utf8 .\tests\test_table_to_excel.py -v
```
