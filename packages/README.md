# 배포본

- `EmailTools_v2.0.0_portable.zip`: 통합 프로그램. 내장 Python/라이브러리를 포함하므로 압축을
  풀고 최상위 `run.bat`을 실행하면 됩니다. HTML·PowerPoint 설명서와 실제 화면 예시도 포함합니다.
  2026-09-08 갱신본에는 간결한 새 UI, 열 설정 접기·너비 조절, 창 크기에 맞는 배치와 최신 설명서가 포함됩니다.
- `EML_Attachment_Tool_v1.0_portable.zip`: 이전 첨부 전용 도구의 보관 자료입니다.
  새 통합 기능은 포함하지 않습니다.

**쉬운 사용 설명서:** 압축을 푼 프로그램 폴더의 `docs` 안에서 아래 파일을 여세요.

- [user-manual.html](../docs/user-manual.html): 화면을 보며 따라 하는 설명서. 인터넷 없이 읽거나 인쇄할 수 있습니다.
- [EmailTools_User_Manual.pptx](../docs/EmailTools_User_Manual.pptx): 같은 작업 순서로 구성한 PowerPoint 설명서

통합 배포본 재생성: `runtime\python\python.exe tools\build_portable.py`
