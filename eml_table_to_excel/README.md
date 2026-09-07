# 이전 표 추출 도구 실행 경로

표 추출과 열 미리보기는 상위 **EmailTools 통합 프로그램**으로 이동했습니다.

- `run.bat`: 최상위 실행 파일을 통해 통합 화면을 엽니다.
- `run.bat --cli "D:\Mail"`: 기존 표 콘솔 동작과 입력 폴더의 XLSX/로그 출력 형식을 유지합니다.
- `run.bat --cli`: 콘솔에서 입력 폴더 경로를 입력받습니다.
- `app.py`: `emailtools.compat.tables`로 연결하는 호환 진입점
- `gui.py`: `emailtools.ui.server`로 연결하는 호환 진입점
- 사용 런타임: `../runtime/python/python.exe`

새 화면에서는 **표 취합**을 선택하면 기존 표 미리보기를 사용할 수 있습니다.
첨부 원본 보관이나 텍스트 추출도 함께 선택할 수 있습니다.

이 폴더만 따로 배포하지 마세요. 자세한 내용은 [통합 사용법](../README.md)을 참고하세요.
