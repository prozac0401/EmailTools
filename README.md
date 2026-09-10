# EmailTools 2.1.1 · Windows Desktop

EML 목록, 첨부 정리와 표 분석을 하나의 Windows 앱에서 처리합니다.
**run.bat을 더블클릭하면 내장 Python으로 독립된 데스크톱 창이 열립니다.**
기본 실행은 브라우저·웹 서버·시스템 Python·pip 없이 동작합니다.

![Windows 앱](docs/desktop-images/01-start.png)

## 시작하기

1. [포터블 ZIP](packages/EmailTools_v2.1.1_portable.zip)을 모두 압축 해제합니다.
2. 프로그램 폴더의 **run.bat**을 실행합니다.
3. 작업을 고르고 EML 파일·폴더를 선택합니다.
4. **목록 만들기 / 표까지 분석하기**를 누릅니다.
5. 분석 완료 후 자동으로 열린 결과 검토 화면에서 저장 구성 확인 → 결과 저장 순서로 진행합니다.

Windows 10/11 x64용입니다. 배포본에는 Python 3.13.15 Embedded와 PySide6 Essentials 6.10.2를 포함합니다.
기본 글꼴은 본문·표 13px, 입력 14px, 구역 제목 16px, 화면 제목 22px입니다.
**글자 크게 / 글자 기본**으로 조절할 수 있습니다. Windows 화면 배율을 따릅니다.

파일·폴더를 앱 입력 영역이나 BAT에 끌어 놓을 수 있습니다. 여러 EML 선택과 하위 폴더 검색을 지원합니다.
**샘플로 체험하기**는 합성 메일 3개를 준비합니다. 분석 버튼을 눌러 실제 처리를 시작합니다.

## 세 가지 작업

| 작업 | 기본 결과 | 읽는 내용 |
|---|---|---|
| 메일 목록만 | MailList.xlsx | 헤더·MIME 메타데이터 |
| 목록과 첨부 정리 | 메일/첨부 목록 Excel + 첨부 원본 | 메타데이터와 첨부 바이트 |
| 목록·첨부·표 분석 | 목록 + 첨부 + 선택한 표 Excel | 메일 HTML 본문과 첨부 DOCX 표 |

목록만 작업은 본문 렌더링·첨부 디코딩을 하지 않습니다. 첨부 크기는 **확인 안 함**으로 표시합니다.
세부 설정에서 본문 TXT, 첨부 내용 TXT, 원본·목록, 표 대상을 조합합니다. **표만 취합**도 제공합니다.
PDF/XLSX/PPTX는 텍스트 추출 대상이며 구조화된 표 추출이나 OCR은 지원하지 않습니다.

## 표 항목 검토

- 위쪽은 선택한 열, 아래쪽은 남은 후보입니다. 자동 줄바꿈과 목록 내부 스크롤을 사용합니다.
- 기본 정보 source_eml, subject를 유지하고 추출 항목은 사용자가 선택합니다.
- 후보 이름으로 추가, ×로 제외합니다. 드래그로 추가·제외·순서를 바꿀 수 있습니다.
- Alt+방향키, Alt+Home/End, 이동 버튼을 지원합니다. 직전 변경은 되돌릴 수 있습니다.
- 공통 후보 추가는 현재 출처 전체의 공통 후보를 추가합니다. 검색·분류 조건과 관계없는 동작입니다.
- 검색·값 검색·출처·분류·정렬은 조회에만 적용하며 저장 열과 순서를 바꾸지 않습니다.
- ⓘ 또는 F1으로 통계·전체 값·원본 위치·격자를 확인합니다. 원본 표 버튼은 후보 없는 표도 보여줍니다.
- 표 해석을 직접 지정하거나 자동 판정으로 되돌릴 수 있습니다.
- 사용자 열은 모든 행에 같은 값을 넣습니다. 이름과 값을 편집할 수 있습니다.
- 미리보기는 25행씩, Excel은 전체 메일을 저장합니다. 머리글 드래그도 같은 순서를 바꿉니다.

같은 EML을 여러 경로로 입력하면 출력 행을 유지하고 추천 통계만 바이트 해시로 중복을 구분합니다.
같은 값의 반복도 원본 등장 기록에 보존하며 Excel 값에서만 중복을 제거합니다.

![항목 검토](docs/desktop-images/02-field-review.png)

## 저장·중지

저장 확인에서 위치와 산출물을 선택합니다. 준비한 산출물은 재분석 없이 제외할 수 있습니다.
항목 미선택 시 **표 Excel 없이 목록·첨부만 저장**을 선택할 수 있습니다.

실행마다 새 결과 폴더를 만들며 기존 결과를 덮어쓰지 않습니다.

- MailList.xlsx: 전체 메일 목록
- AttachmentList.xlsx: 선택한 첨부 상세 목록
- mails/: 선택한 본문·첨부·텍스트
- tables/EML_Table_Result.xlsx: 선택한 열의 표
- summary.csv, attachments.csv, processing.log, .emailtools-job.json
- EmailTools_Result.zip: ZIP 생성을 선택한 경우

분석·저장은 별도 스레드에서 실행합니다. 미확정 단계에는 수치 없는 진행을,
확정 단계에는 실제 메일·행·파일·ZIP 바이트 수 기반의 현재 단계 진행률을 표시합니다.
중지는 안전한 처리 경계에서 확정합니다. 실패·중지 시 이번 미완성 결과만 정리합니다.

재분석 성공 전까지 이전 결과·선택을 유지합니다. 같은 입력의 재분석 성공 시 남아 있는 항목·사용자 열·순서·이름을 복원합니다.
창을 닫으면 실행 중인 처리를 정리한 뒤 종료합니다.

## 소스 실행과 런타임

Git에는 큰 Python·Qt 바이너리를 넣지 않습니다. 소스에서 최초 실행하면 필요한 런타임을 준비합니다.

```bat
setup_desktop.bat
run.bat
```

setup_runtime.bat은 기존 내장 Python 또는 루트의 python-3.13.15-embed-amd64.zip을 사용합니다.
없으면 Python.org에서 받습니다. setup_desktop.bat은 고정된 두 Qt wheel의 SHA256과 실행을 확인한 뒤 설치합니다.

오프라인 소스 준비는 Python ZIP을 루트에, requirements-desktop.lock.json의 두 wheel을 runtime/wheels/에 둡니다.
**포터블 ZIP은 이미 런타임을 포함하므로 준비·다운로드가 필요 없습니다.**

Qt 참고: [공식 설치 안내](https://doc.qt.io/qtforpython-6/gettingstarted.html).
타사 고지는 THIRD_PARTY_LICENSES, vendor의 dist-info, runtime/python/LICENSE.txt에 있습니다.

## CLI·호환

```bat
run.bat --cli "D:\Mail" --mode list --output "D:\Results"
run.bat --cli "D:\Mail" --mode archive
run.bat --cli "D:\Mail" --mode analyze
run.bat --cli "D:\Mail" --all
run.bat --cli "D:\Mail" --tables --table-source docx
run.bat --cli "D:\Mail" --text --tables --columns-file columns.json
```

--mode와 기존 개별 처리 플래그는 함께 사용할 수 없습니다.
기존 CLI 옵션 생략은 표 추출, --all은 본문·첨부·텍스트·표 네 기능을 유지합니다.
기존 도구 폴더의 콘솔 진입점도 유지합니다.

이전 웹 화면은 run.bat --web에서 명시적으로 실행합니다. --no-browser도 호환 테스트용으로 유지합니다.
이전 HTML·PowerPoint 설명서는 2.0 웹 UI 자료입니다. 현재 앱은 [데스크톱 안내](docs/desktop-guide.md)를 참고하세요.

## 검증·배포

```bat
runtime\python\python.exe -X utf8 -m unittest discover -s tests -v
run.bat --desktop-smoke .desktop-test
runtime\python\python.exe -X utf8 tools\benchmark_desktop.py
runtime\python\python.exe -X utf8 tools\build_portable.py
```

빌드는 별도 압축 해제 경로에서 내장 런타임으로 CLI·Qt 앱·실제 Excel 저장을 검증하고 ZIP·SHA256을 만듭니다.
[검증 기록](docs/testing.md) · [구조](docs/architecture.md) · [계획 적용 범위](docs/desktop-implementation.md).
