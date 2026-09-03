EML Attachment Tool 1.0.0
=========================

목적
----
EML 파일의 본문과 첨부파일을 분리 저장하고, 별도 패키지 없이 읽을 수 있는
첨부파일은 텍스트로도 갈무리하는 Windows 포터블 도구입니다.

실행
----
1) run.bat 더블클릭
2) EML 파일 또는 EML 폴더 경로 입력

또는
- EML 파일을 run.bat 위에 드래그앤드롭
- EML 폴더를 run.bat 위에 드래그앤드롭

중요: Python 실행 정책
----------------------
- 시스템에 설치된 Python을 사용하지 않습니다.
- run.bat은 반드시 .\python\python.exe만 실행합니다.
- python\python.exe가 없으면 setup_embedded_python.bat이 공식 Python.org의
  Windows Embeddable Package (x64)를 python\ 폴더 안에 구성합니다.
- 완전 오프라인 배포가 필요하면 아래 공식 ZIP을 프로그램 루트에 함께 두면 됩니다.

  python-3.13.15-embed-amd64.zip

  setup_embedded_python.bat은 인터넷 다운로드보다 같은 폴더의 ZIP을 우선 사용합니다.

폴더 구조
---------
EML_Attachment_Tool\
  run.bat
  setup_embedded_python.bat
  app.py
  README.txt
  python\
    python.exe
    python313.dll
    python313.zip
    ...

결과
----
입력 EML 폴더 아래에 _EML_OUTPUT 폴더를 생성합니다.

예)
Mail\
  A.eml
  B.eml
  _EML_OUTPUT\
    A\
      _mail.txt
      _attachments_index.txt
      attachments\
        report.docx
        image.png
      _TEXT\
        report.docx.txt
    B\
      ...
    _summary.csv
    _summary.txt

텍스트 읽기 지원
----------------
- TXT, CSV, TSV, JSON, XML, HTML, MD 및 일반 텍스트 파일
- DOCX: 문서 XML에서 텍스트 추출
- XLSX: 시트의 셀 값 추출
- PPTX: 슬라이드 텍스트 추출
- PDF: 텍스트 레이어 읽기 (번들 pypdf 사용)
- 첨부 EML: 메일 헤더/본문 읽기

원본 저장만 지원
----------------
- JPG/PNG 등 이미지
- ZIP 및 기타 바이너리 파일

참고
----
- 암호화/DRM/암호가 설정된 첨부파일은 원본 추출은 가능해도 내용 읽기가 제한될 수 있습니다.
- 같은 이름의 첨부파일이 이미 있으면 (1), (2) 형태로 이름을 회피합니다.
- 첨부파일명은 안전한 basename으로 정규화되며 출력 폴더 밖에는 저장하지 않습니다.
- EXE/BAT/JS/VBS를 포함한 모든 첨부파일은 데이터로만 저장하며 실행하지 않습니다.
- 하위 폴더의 EML도 재귀적으로 처리하며, 출력 폴더 구조를 유지합니다.
- _EML_OUTPUT 내부는 다시 검색하지 않아 재처리를 방지합니다.

내장 보조 라이브러리
--------------------
- pypdf 5.9.0 (BSD-3-Clause): PDF 텍스트 레이어 추출용
- vendor\ 아래에 함께 배포되어 시스템 패키지를 사용하지 않습니다.
