# 이전 첨부 도구 실행 경로

실제 구현, Python과 라이브러리는 상위 **EmailTools 통합 프로그램**으로 이동했습니다.

- 새 화면: 최상위 `../run.bat` 실행 후 **첨부 보관** 또는 **전체 처리** 선택
- 이 폴더의 `run.bat`: 기존 첨부 콘솔 동작과 `_EML_OUTPUT` 결과 형식 유지
- `app.py`: `emailtools.compat.attachments`로 연결하는 호환 진입점
- `setup_embedded_python.bat`: 최상위 `setup_runtime.bat`으로 연결
- 사용 런타임: `../runtime/python/python.exe`

이 폴더만 따로 배포하지 마세요. 자세한 내용은 [통합 사용법](../README.md)을 참고하세요.
