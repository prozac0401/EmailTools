"""Offline browser UI served by the bundled Python (no pip or Tk required)."""
from __future__ import annotations

import argparse
import base64
import binascii
import json
import logging
import secrets
import sys
import tempfile
import threading
import webbrowser
import zipfile
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO, StringIO
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from xml.sax.saxutils import escape

APP_DIR = Path(__file__).resolve().parent
from emailtools.extractors import tables as core
from emailtools import pipeline
from emailtools.models import ProcessingOptions, AnalysisResult
from emailtools.table_config import validate_columns, project_records
from emailtools.exporters.files import export_results, LOG_FILENAME, ARCHIVE_FILENAME

MAX_REQUEST_BYTES = 96 * 1024 * 1024
MAX_UPLOAD_BYTES = 64 * 1024 * 1024
PAGE_SIZE = 25


from emailtools.demo import create_demo


def save_uploads(folder: Path, files: object) -> None:
    if not isinstance(files, list) or not files or len(files) > 5000:
        raise ValueError("EML 파일을 선택해 주세요. 한 번에 최대 5,000개까지 불러올 수 있습니다.")
    total = 0
    used = set()
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ValueError("파일 정보가 올바르지 않습니다.")
        name = item["name"].replace("\\", "/")
        path = PurePosixPath(name)
        if (not path.parts or path.is_absolute() or ".." in path.parts
                or any(":" in part for part in path.parts) or path.suffix.lower() != ".eml"):
            raise ValueError("EML 파일만 불러올 수 있습니다.")
        target = (folder / Path(*path.parts)).resolve()
        if not target.is_relative_to(folder.resolve()) or str(target).casefold() in used:
            raise ValueError("파일 경로가 중복되었거나 올바르지 않습니다.")
        used.add(str(target).casefold())
        try:
            payload = base64.b64decode(item["data"], validate=True)
        except (KeyError, TypeError, ValueError, binascii.Error) as exc:
            raise ValueError("파일을 읽지 못했습니다. 다시 선택해 주세요.") from exc
        total += len(payload)
        if total > MAX_UPLOAD_BYTES:
            raise ValueError("64 MB를 넘는 데이터는 폴더 경로를 입력해서 불러와 주세요.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)


class Workspace:
    def __init__(self, initial_source: str = "") -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="EmailTools_preview_")
        self.root = Path(self.temp.name)
        self.lock = threading.RLock()
        self.initial_source = initial_source
        self.scan: AnalysisResult | None = None
        self.dataset = ""
        self.phase = "empty"
        self.progress = ""
        self.error = ""
        self.label = ""
        self.demo = False
        self.worker: threading.Thread | None = None
        self.exports: dict[str, Path] = {}
        self.options = ProcessingOptions()
        self.work_temp: tempfile.TemporaryDirectory | None = None
        self.output_suggestion = ""
        self.loaded_request: dict | None = None
        self.cancel_event = threading.Event()
        self.log_text = StringIO()
        self.logger = logging.Logger(f"emailtools.preview.{id(self)}", logging.INFO)
        handler = logging.StreamHandler(self.log_text)
        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        self.logger.addHandler(handler)

    def snapshot(self) -> dict:
        with self.lock:
            data = {"phase": self.phase, "progress": self.progress, "error": self.error,
                    "dataset": self.dataset, "label": self.label, "demo": self.demo,
                    "initial_source": self.initial_source, "options": self.options.as_dict(),
                    "output_suggestion": self.output_suggestion}
            if self.scan:
                data.update(columns=self.scan.columns, total=len(self.scan.records),
                            success=self.scan.success, warnings=self.scan.warnings,
                            failures=self.scan.failures, attachments=self.scan.attachment_count)
            return data

    def load(self, request: dict) -> None:
        with self.lock:
            if self.phase == "loading":
                raise ValueError("파일을 불러오는 중입니다. 잠시 기다려 주세요.")
            options = ProcessingOptions.from_dict(request.get("options"))
            if request.get("reuse") is True:
                if self.loaded_request is None:
                    raise ValueError("다시 분석할 입력이 없습니다. 먼저 파일을 불러와 주세요.")
                request = {**self.loaded_request, "options": options.as_dict()}
            if self.work_temp is not None:
                self.work_temp.cleanup()
            self.work_temp = tempfile.TemporaryDirectory(prefix="dataset_", dir=self.root)
            self.options = options
            self.cancel_event.clear()
            self.phase, self.progress, self.error = "loading", "EML 파일을 찾는 중…", ""
            self.scan = None
            self.dataset = ""
            self.log_text.seek(0)
            self.log_text.truncate()
            self.worker = threading.Thread(target=self._load, args=(request, options), daemon=True)
            self.worker.start()

    def _load(self, request: dict, options: ProcessingOptions) -> None:
        try:
            working = Path(self.work_temp.name)
            demo = request.get("demo") is True
            if demo or "files" in request:
                folder = working / "input"
                folder.mkdir()
                if demo:
                    create_demo(folder)
                    label = "교육 결과 · 샘플 EML 3개"
                else:
                    save_uploads(folder, request["files"])
                    label = "선택한 EML 파일"
                source = folder
            else:
                raw = request.get("source")
                if not isinstance(raw, str) or not raw.strip().strip('"'):
                    raise ValueError("EML 파일 또는 폴더 경로를 입력해 주세요.")
                source = Path(raw.strip().strip('"')).expanduser().resolve()
                label = str(source)
            def progress(message: str) -> None:
                with self.lock:
                    self.progress = message
            scan = pipeline.analyze(source, options, working / "spool", self.logger, progress,
                                    self.cancel_event.is_set)
            with self.lock:
                self.scan, self.dataset = scan, secrets.token_hex(16)
                self.label, self.demo = label, demo
                self.loaded_request = {key: value for key, value in request.items()
                                       if key in {"demo", "files", "source"}}
                self.output_suggestion = str((Path.home() / "Downloads" / "EmailTools")
                    if demo or "files" in request else scan.source_root / "_EML_OUTPUT")
                self.phase, self.progress = "ready", "불러오기 완료"
        except Exception as exc:
            self.logger.exception("불러오기 실패")
            with self.lock:
                self.phase, self.error = "error", str(exc)

    def selection(self, request: dict) -> list[dict]:
        if self.phase != "ready" or not self.scan or request.get("dataset") != self.dataset:
            raise ValueError("데이터가 변경되었습니다. 다시 불러온 뒤 시도해 주세요.")
        if "options" in request and ProcessingOptions.from_dict(request["options"]) != self.scan.options:
            raise ValueError("처리 옵션이 변경되었습니다. 새 옵션으로 다시 분석해 주세요.")
        return validate_columns(request.get("columns"), self.scan.columns) if self.scan.options.extract_tables else []

    def preview(self, request: dict) -> dict:
        with self.lock:
            specs = self.selection(request)
            if not self.scan.options.extract_tables:
                raise ValueError("표 추출을 선택한 뒤 다시 분석해 주세요.")
            page = request.get("page", 0)
            if type(page) is not int or page < 0:
                raise ValueError("페이지 번호가 올바르지 않습니다.")
            total = len(self.scan.records)
            page = min(page, max(0, (total - 1) // PAGE_SIZE))
            rows = self.scan.records[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
            # Preview uses identical sanitation but does not duplicate log entries.
            quiet = logging.Logger("preview.values")
            quiet.addHandler(logging.NullHandler())
            return {"columns": [s["name"] for s in specs],
                    "rows": project_records(rows, specs, quiet),
                    "statuses": [r.get("_status", "") for r in rows],
                    "errors": [r.get("_error", "") for r in rows],
                    "total": total, "page": page, "page_size": PAGE_SIZE}

    def export(self, request: dict) -> dict:
        with self.lock:
            specs = self.selection(request)
            export_id = secrets.token_hex(16)
            output = request.get("output", "")
            if not isinstance(output, str):
                raise ValueError("결과 폴더 경로가 올바르지 않습니다.")
            destination = Path(output.strip().strip('"')) if output.strip() else self.root / "exports"
            folder = export_results(self.scan, destination, self.logger,
                columns=request.get("columns") if specs else None,
                get_log=self.log_text.getvalue, archive=True)
            self.exports[export_id] = folder
            options = self.scan.options
            primary = "zip" if options.save_mail or options.save_attachments or options.extract_text else "xlsx"
            return {"download": f"download/{export_id}/{primary}", "log": f"download/{export_id}/log",
                    "archive": f"download/{export_id}/zip",
                    "excel": f"download/{export_id}/xlsx" if options.extract_tables else None,
                    "output_path": str(folder), "total": len(self.scan.records), "columns": len(specs)}

    def details(self, request: dict) -> dict:
        with self.lock:
            if self.phase != "ready" or not self.scan or request.get("dataset") != self.dataset:
                raise ValueError("데이터가 변경되었습니다. 다시 불러와 주세요.")
            page = request.get("page", 0)
            kind = request.get("kind", "mails")
            if type(page) is not int or page < 0 or kind not in {"mails", "attachments"}:
                raise ValueError("조회 요청이 올바르지 않습니다.")
            rows = []
            for mail in self.scan.mails:
                if kind == "mails":
                    rows.append({"메일": mail.record["source_eml"], "제목": mail.record.get("subject", ""),
                        "보낸 사람": mail.record.get("from", ""), "첨부": str(len(mail.attachments)),
                        "상태": mail.record["_status"], "오류": mail.record["_error"], "본문": mail.body})
                else:
                    for item in mail.attachments:
                        rows.append({"메일": mail.record["source_eml"], "첨부파일": item.name,
                            "크기 (bytes)": str(item.size), "형식": item.content_type,
                            "텍스트 분석": item.text_status, "오류": item.error, "추출 내용": item.text or ""})
            page = min(page, max(0, (len(rows) - 1) // PAGE_SIZE))
            return {"rows": rows[page * PAGE_SIZE:(page + 1) * PAGE_SIZE],
                    "total": len(rows), "page": page, "page_size": PAGE_SIZE}

    def close(self) -> None:
        self.cancel_event.set()
        if self.worker:
            self.worker.join()
        if self.work_temp:
            self.work_temp.cleanup()
        for handler in list(self.logger.handlers):
            handler.close()
            self.logger.removeHandler(handler)
        self.temp.cleanup()


class LocalServer(ThreadingHTTPServer):
    daemon_threads = False

    def __init__(self, workspace: Workspace, port: int = 0):
        self.workspace = workspace
        self.token = secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", port), Handler)
        self.origin = f"http://127.0.0.1:{self.server_port}"
        self.prefix = f"/{self.token}/"
        self.url = self.origin + self.prefix


class Handler(BaseHTTPRequestHandler):
    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(30)

    def log_message(self, *args) -> None:
        pass

    def reply(self, status: int, payload: bytes, content_type: str, filename: str = "") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; "
                         "style-src 'self'; img-src 'self' data:; connect-src 'self'; "
                         "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def json_reply(self, data: dict, status: int = 200) -> None:
        self.reply(status, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def route(self) -> str | None:
        server = self.server
        host = urlsplit(server.origin).netloc
        path = urlsplit(self.path).path
        if (self.headers.get("Host") != host or not path.startswith(server.prefix)
                or self.headers.get("Origin", server.origin) != server.origin):
            self.json_reply({"error": "허용되지 않은 요청입니다."}, 403)
            return None
        return path[len(server.prefix):]

    def do_GET(self) -> None:
        route = self.route()
        if route is None:
            return
        if route == "api/state":
            self.json_reply(self.server.workspace.snapshot())
        elif route in {"", "ui.js", "ui.css"}:
            filename, content_type = {
                "": ("index.html", "text/html; charset=utf-8"),
                "ui.js": ("ui.js", "text/javascript; charset=utf-8"),
                "ui.css": ("ui.css", "text/css; charset=utf-8"),
            }[route]
            self.reply(200, (APP_DIR / "static" / filename).read_bytes(), content_type)
        elif route.startswith("download/"):
            parts = route.split("/")
            folder = self.server.workspace.exports.get(parts[1]) if len(parts) == 3 else None
            names = {"xlsx": Path("tables") / core.OUTPUT_FILENAME,
                     "log": Path(LOG_FILENAME), "zip": Path(ARCHIVE_FILENAME)}
            if folder and parts[2] in names and (folder / names[parts[2]]).is_file():
                path = folder / names[parts[2]]
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(path.stat().st_size))
                self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                try:
                    with path.open("rb") as stream:
                        while chunk := stream.read(1024 * 1024):
                            self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError, TimeoutError):
                    pass
            else:
                self.json_reply({"error": "저장 파일을 찾을 수 없습니다."}, 404)
        else:
            self.json_reply({"error": "페이지를 찾을 수 없습니다."}, 404)

    def do_POST(self) -> None:
        route = self.route()
        if route is None:
            return
        if self.headers.get("X-EmailTools-Token") != self.server.token:
            self.json_reply({"error": "허용되지 않은 요청입니다."}, 403)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_REQUEST_BYTES:
                raise ValueError("요청이 너무 큽니다. 큰 폴더는 경로로 불러와 주세요.")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("요청 형식이 올바르지 않습니다.")
            workspace = self.server.workspace
            if route == "api/load":
                workspace.load(data)
                self.json_reply({"ok": True}, 202)
            elif route == "api/preview":
                self.json_reply(workspace.preview(data))
            elif route == "api/export":
                self.json_reply(workspace.export(data))
            elif route == "api/details":
                self.json_reply(workspace.details(data))
            elif route == "api/cancel":
                workspace.cancel_event.set()
                self.json_reply({"ok": True})
            elif route == "api/shutdown":
                self.json_reply({"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                self.json_reply({"error": "요청을 찾을 수 없습니다."}, 404)
        except (ValueError, TypeError) as exc:
            self.json_reply({"error": str(exc)}, 400)
        except Exception:
            self.server.workspace.logger.exception("화면 요청 처리 오류")
            self.json_reply({"error": "처리하지 못했습니다. 다시 시도하거나 다른 파일을 선택해 주세요."}, 500)


def main() -> int:
    parser = argparse.ArgumentParser(description="EmailTools · 메일/첨부/표 통합 작업 화면",
        epilog="콘솔 일괄 처리: run.bat --cli --help")
    parser.add_argument("source", nargs="?", default="", help="EML 파일 또는 폴더")
    parser.add_argument("--no-browser", action="store_true", help="브라우저 자동 열기 생략")
    parser.add_argument("--port", type=int, default=0, help="로컬 포트 (기본: 자동)")
    args = parser.parse_args()
    workspace = Workspace(args.source)
    server = None
    try:
        server = LocalServer(workspace, args.port)
        print("EmailTools | 처리 옵션을 선택하고 결과를 미리 보세요.", flush=True)
        print(f"화면 주소: {server.url}", flush=True)
        print("종료하려면 화면의 '프로그램 종료' 또는 이 창에서 Ctrl+C를 누르세요.", flush=True)
        if not args.no_browser:
            try:
                webbrowser.open(server.url)
            except (OSError, webbrowser.Error):
                print("브라우저를 자동으로 열지 못했습니다. 위 화면 주소를 직접 열어 주세요.", flush=True)
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        workspace.cancel_event.set()
        if server:
            server.server_close()
        workspace.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
