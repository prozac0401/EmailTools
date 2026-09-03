# EML Table to Excel

여러 EML의 HTML 본문 표와 DOCX 첨부파일 내부 표를 읽고, 각 표의 항목명을
자동으로 Excel 컬럼에 매핑하여 하나의 Worksheet로 통합하는 전용 도구입니다.

## 실행

`run.bat`을 실행하고 EML 파일이 있는 폴더를 입력합니다.

```text
run.bat
```

또는 EML 폴더를 `run.bat`에 Drag & Drop합니다. 지정한 폴더의 하위 폴더도
재귀적으로 검색합니다.

## Python과 의존성

- 시스템 Python이나 PATH의 `python`, `py`를 사용하지 않습니다.
- 기존 EML Attachment Tool의 `..\eml_attachment_tool\python\python.exe`를
  공유합니다.
- 런타임이 없으면 기존 `setup_embedded_python.bat`을 호출하여 Python
  3.13.15 x64 Windows Embedded를 구성합니다.
- Excel 생성에는 `vendor\`에 포함된 `openpyxl 3.1.5`와
  `et_xmlfile 2.0.0`을 사용합니다.
- 사용자가 `pip install`을 실행할 필요가 없습니다.

## 처리 방식

1. 입력 폴더에서 `.eml` 파일을 재귀 검색합니다.
2. Python 표준 `email` parser로 MIME 메시지를 읽습니다.
3. HTML 본문의 모든 `<table>`에서 2열 또는 4열 이상의 `항목/값` 쌍을 읽습니다.
4. DOCX 첨부파일 bytes의 `word/document.xml`을 직접 읽어 `w:tbl`, `w:tr`,
   `w:tc`, `w:t` 구조를 분석합니다. DOCX를 디스크에 추출하지 않습니다.
5. 각 EML을 한 행으로 만들고, 처음 발견된 항목 순서대로 Excel 컬럼을 만듭니다.

## 항목과 값 병합 정책

- 항목명의 앞뒤 공백, CR/LF, tab, NBSP와 앞뒤 `:` 등은 정리합니다.
- 내부 연속 공백은 하나로 줄입니다.
- 실제 데이터에 근거하지 않은 fuzzy matching이나 alias는 적용하지 않습니다.
- 같은 항목의 같은 값은 한 번만 유지합니다.
- 같은 항목의 서로 다른 값은 `값1 | 값2` 형태로 모두 보존합니다.
- EML과 DOCX 양쪽에 같은 항목이 있어도 동일한 정책으로 병합합니다.
- 시스템 컬럼명과 같은 항목은 `item_` 접두사를 붙여 시스템 값을 보호합니다.

## 결과

입력 폴더에 다음 두 파일을 만듭니다.

```text
EML_Table_Result.xlsx
EML_Table_Result_errors.log
```

Worksheet는 `Result` 하나입니다. 기본 시스템 컬럼은 다음 순서입니다.

```text
source_eml
_status
_error
subject
from
to
date
docx_filename
```

그 뒤에 EML/DOCX 표에서 처음 발견된 항목들이 자동으로 추가됩니다. 한 EML에
없는 항목의 Cell은 빈 값으로 유지됩니다.

Excel에는 Header 서식, Auto Filter, `A2` Freeze Panes, 열 너비 제한(10~50),
긴 텍스트 Wrap 및 Top 정렬을 적용합니다. Excel Cell 제한을 넘는 문자열은
오류 로그에 기록하고 안전하게 잘라냅니다. `=`로 시작하는 외부 값도 Excel
수식으로 실행되지 않도록 명시적인 문자열 Cell로 저장합니다.

## 상태

- `OK`: EML 표와 DOCX 표를 정상 처리
- `NO DOCX`: DOCX 첨부파일 없음
- `NO EMAIL TABLE`: HTML 본문에서 표를 찾지 못함
- `NO DOCX TABLE`: DOCX에서 표를 찾지 못함
- `EMAIL TABLE ERROR`: 본문 표 처리 오류
- `DOCX PARSE ERROR`: DOCX 압축/XML 처리 오류
- `PARSE ERROR`: EML 처리 실패

한 EML에서 오류가 발생해도 나머지 EML 처리는 계속됩니다. 상세 오류와 stack
trace는 화면 대신 `EML_Table_Result_errors.log`에 기록합니다.

## 원본 보존

원본 EML과 DOCX는 읽기 전용으로 처리합니다. 원본을 수정, 이동 또는 삭제하지
않으며 DOCX 첨부파일을 실행하거나 디스크에 별도로 저장하지 않습니다.
