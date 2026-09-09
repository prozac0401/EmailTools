# EmailTools 2.1 구조

기본 경로는 run.bat → runtime/python/pythonw.exe → main.py → emailtools.desktop.app이다.
CLI·호환 테스트는 같은 런타임의 python.exe를 사용한다. 웹 서버는 --web/--no-browser에서만 가져온다.
Qt는 runtime/desktop, 기존 Python 라이브러리는 vendor에 둔다.

## 처리

- ProcessingOptions: 기존 불변 옵션에 mail_index, attachment_index를 확장했다. 기존 기본값은 유지한다.
- plans.options_for_mode: list/archive/analyze를 명시적인 옵션으로 변환한다.
- ExportPlan: 준비한 데이터 범위에서 저장할 산출물을 검증한다.
- pipeline.analyze: 여러 입력을 검색·경로 중복 제거한 뒤 EML당 한 번 읽고 해시를 계산한다.
- AttachmentSource.payload: 필요한 첨부만 한 번 디코딩한다. 목록만은 접근하지 않고 표만은 DOCX만 접근한다.
- MailResult: 메타데이터·원본 경로·해시, 필요한 경우에만 본문과 원본 첨부 spool을 보관한다.
- AnalysisResult: 완성 결과와 FieldCatalog를 소유한다.

첨부 EML의 본문·표를 부모 메일에 섞지 않는다. 명시적인 본문 읽기는 원본 해시 변경을 확인한다.

## 출처와 항목

FieldCatalog는 ParsedTable → Occurrence → 출처별 통계 → 저장 레코드 순서다.
HTML/Word 물리 셀, 병합·헤더·중첩, 메일·문서·표 ID를 보존한다.
Word 외부 셀에 내부 표 텍스트를 중복 합산하지 않는다.
동일 EML의 출력 행은 유지하고 추천 통계에서만 해시 그룹 대표를 사용한다.

명시적인 항목/값 헤더, 명단 구조, 중첩 배치, 반복 양식을 구분한다.
구조 확인 후보를 숨기지 않고 수동 표 유형 지정/자동 복구를 제공한다.
통계는 전체 데이터로 계산하고 후보·출처·등장 기록은 50개씩 표시한다.
현재 출처 모델은 메모리에 보관하며 SQLite는 사용하지 않는다.

## UI와 상태

Window가 입력·선택·완성 결과·임시 작업 폴더를 소유한다.
Worker(QThread)의 queued signals로 상태·완료·실패·중지를 전달한다. 한 번에 한 작업만 실행한다.
진행 중 설정·열 편집·중복 실행을 막고 중지·글자 크기는 유지한다.

재분석 성공 전에는 이전 결과를 유지한다. 성공 후 새 데이터셋으로 교체하고 이전 spool을 정리한다.
같은 입력은 안정된 ID로 열·이름·순서·사용자 값을 복원하며 새 입력은 기본 선택으로 시작한다.
검색·정렬·탭 상태와 열 순서는 독립적이다. 세션별 MIME으로 내부 드래그를 검증한다.

## 저장

export_results는 목적지 아래 자신이 만든 staging에만 쓴다. 선택한 목록·첨부·표·텍스트와 로그를 만들고
선택 시 ZIP을 청크 단위로 작성한 뒤 최종 폴더를 rename한다.
메일·행·파일·복사·ZIP 청크 경계에서 중지를 확인한다. 실패하면 해당 staging만 정리한다.
최종 확정 구간은 중지 불가로 알린다.

실제 단위 기반의 현재 단계 진행률을 사용하고 미확정 단계는 indeterminate로 표시한다.
table_config가 중복 이름·원본 매핑을 검증한다. 미리보기 25행과 전체 Excel은 같은 투영·값 보정을 사용한다.
Excel 수식 모양의 데이터는 문자열로 저장하고 CSV의 기존 수식 방지 처리를 유지한다.

## 호환·배포

기존 compat 계층과 CLI 결과는 유지한다. 2.0 웹 화면은 명시적 호환 경로로 남긴다.
합성 샘플은 서버와 독립된 emailtools.demo로 이동했다.
Qt wheel은 버전·SHA256 고정, 임시 설치·실행 확인 후 게시한다. DLL과 Python 소스는 교체 가능한 형태로 배포한다.
빌드는 별도의 추출 경로에서 BAT/CLI/Qt UI/실제 Excel을 검증한다.
