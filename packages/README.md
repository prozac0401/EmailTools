# 배포본

- **EmailTools_v2.1.1_portable.zip**: 현재 Windows 네이티브 앱. 파일 입력·분석 결과 표시 오류 수정.
  Python Embedded와 Qt UI 런타임 포함.
  모두 압축 해제하고 최상위 run.bat을 실행한다. 시스템 Python·브라우저·인터넷 없이 사용할 수 있다.
  SHA256 파일을 함께 제공한다.
- EmailTools_v2.1.0_portable.zip: 첫 Windows 네이티브 앱 보관본.
- EmailTools_v2.0.0_portable.zip: 이전 웹 UI 보관본.
- EML_Attachment_Tool_v1.0_portable.zip: 이전 첨부 전용 도구 보관본.

현재 안내는 docs/desktop-guide.md. HTML·PowerPoint 설명서는 2.0 웹 UI 보관 자료다.
재생성: runtime\python\python.exe -X utf8 tools\build_portable.py
빌드는 독립된 추출 경로에서 CLI·네이티브 UI·실제 저장과 콘솔 없는 pythonw 회귀 검사를 실행한다.
