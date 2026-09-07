# EmailTools 구조

## 실행과 의존성

`run.bat → runtime/python/python.exe → main.py`가 유일한 사용자 실행 경로다.
`main.py`는 통합 GUI/CLI 또는 기존 형식 호환 모드로 분기한다.
`emailtools/__init__.py`에서 루트 `vendor/`를 등록한다. 다른 도구의 `app.py`를 경로로
읽거나 동적으로 가져오지 않는다.

## 분석 흐름

1. `models.ProcessingOptions`: 선택한 기능/표 원천을 검증하는 불변 옵션.
2. `reader.find_eml_targets`: 입력 EML 검색, 결과 폴더/링크 제외.
3. `reader.read_message`: 각 원본 EML의 MIME을 한 번 파싱.
4. `extractors.attachments`: 첨부별 payload를 한 번 디코딩하고 필요한 분석기에서 재사용.
5. `extractors.text` / `extractors.tables`: 선택한 내용/표를 분석.
6. `models.AnalysisResult`: 메일, 첨부 목록, 표 레코드와 상태를 보관.

본문과 첨부 EML은 MIME 경계를 지킨다. 첨부 EML의 내용은 부모 메일의 본문/표/첨부 목록에
재귀적으로 혼합하지 않으며, 텍스트 추출을 선택했을 때 첨부 자체의 내용으로 읽는다.

`save_attachments` 선택 시만 원본 첨부 바이트를 비공개 임시 폴더에 보관한다. DOCX 표와
Office 텍스트 분석은 bytes/BytesIO를 사용하므로 첨부 원본 저장이 필수가 아니다.
읽은 원본을 다시 분석/저장하기 위해 불필요하게 MIME을 재파싱하지 않는다.

분석 중지는 폴더 검색 및 메일 사이에서 확인한다. 이미 진행 중인 한 메일의 분석을 강제로
끊지 않고, 중지 시 미완성 AnalysisResult를 게시하지 않는다.

## 화면 상태

`ui.server.Workspace`가 세션별 데이터와 임시 작업 폴더를 소유한다.
분석은 worker thread에서 진행하고 화면은 상태/진행률을 조회한다. 새 데이터와 옵션으로
분석하면 새 dataset ID를 발급한다. 과거 dataset의 조회/저장 요청은 거부한다.

분석에 사용된 옵션은 결과에 고정된다. 화면에서 옵션을 수정하면 저장을 막고 재분석한다.
다시 분석은 같은 입력 요청을 재사용한다. 업로드 데이터는 현재 세션에서만 보관하며
이전 spool은 새 분석을 시작할 때 정리한다.

로컬 HTTP 서버는 loopback에만 바인딩하고 세션별 경로/요청 토큰, Host/Origin 검사와 CSP를
사용한다. 화면에는 메일의 HTML을 실행하지 않고 텍스트 노드로만 표시한다.

## 미리보기와 저장

`table_config`는 열 이름, 원본 매핑, 중복, 최소 한 열 선택을 공통 검증한다.
미리보기는 Excel과 같은 값 보정을 한 번 적용한 25행만 반환한다. Excel은 동일한 열 구성으로
전체 레코드를 보정해 저장한다. 사용자 열 값은 모든 행에 같은 문자열을 넣는다.

`exporters.files.export_results`가 전체 결과 파일을 하나의 staging 폴더에서 만든다.
모두 성공하면 실행 시각+임의 ID의 새 폴더로 이동한다. 실패 시 자신이 만든 staging만 정리하고
입력/기존 출력은 변경하지 않는다. 메일별 폴더에는 순번을 넣고 첨부명 충돌은 개별적으로 회피한다.

GUI는 전체 ZIP 및 선택한 XLSX/로그 다운로드를 제공한다. 다운로드는 파일을 나눠 전송하여
큰 ZIP을 응답용 메모리에 통째로 읽지 않는다. 영구 저장 위치가 비어 있으면 다운로드용 임시
결과만 만들며 세션 종료 시 정리한다.

`.emailtools-job.json`은 작업별 옵션/메일 수를 기록하며, ZIP을 풀어 둔 폴더까지 다음 EML
검색에서 제외하는 표시 역할을 한다.

## 호환 계층

`compat/attachments.py`, `compat/tables.py`는 기존 콘솔의 출력 레이아웃과 API를 유지한다.
EML 읽기/검색, 첨부 처리, 텍스트·표 분석, Excel 생성은 공통 모듈을 사용한다.
기존 폴더의 BAT/Python 파일에는 진입 연결만 남겨 두었다. 통합 GUI/CLI는 호환 계층에
의존하지 않으므로 두 기존 진입 폴더 없이도 실행할 수 있다.

## 기능 확장

새 텍스트 형식은 `extractors/text.py`, 새 표 원천은 `extractors/tables.py`에 추가한다.
새 작업 종류는 `ProcessingOptions`, `pipeline`, 해당 exporter, GUI 옵션 및 CLI 플래그에
명시적으로 연결한다. 분석기는 최종 출력 경로를 쓰지 않는다.

변경 시 최소 검증: 선택하지 않은 기능의 파일이 생성되지 않는지, 미리보기/실제 파일 일치,
일부 분석 오류의 격리, 입력 보존, 기존 BAT 회귀, 이전 도구 폴더 없는 포터블 실행.
