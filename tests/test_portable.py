from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from emailtools.ui.server import create_demo
from openpyxl import load_workbook


@unittest.skipUnless(os.name == "nt", "Windows portable launcher")
class PortableDeploymentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="EmailTools_deployment_")
        cls.test_root = Path(cls.temp.name)
        cls.deploy = cls.test_root / "통합 배포 & 검증 !"
        cls.deploy.mkdir()
        for name in ("main.py", "run.bat", "setup_runtime.bat"):
            shutil.copyfile(ROOT / name, cls.deploy / name)
        for name in ("emailtools", "vendor", "runtime"):
            shutil.copytree(ROOT / name, cls.deploy / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".python-*"))
        cls.source = cls.test_root / "한글 메일 입력 & 폴더 !"
        cls.source.mkdir()
        create_demo(cls.source)
        cls.environment = {**os.environ, "EMAILTOOLS_NO_PAUSE": "1"}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def command(self, arguments, script="run.bat", timeout=30):
        command = f'cmd.exe /d /c call "{self.deploy / script}" {arguments}'
        return subprocess.run(command, cwd=self.test_root, env=self.environment, text=True,
            encoding="utf-8", errors="replace", capture_output=True, timeout=timeout)

    def test_single_runtime_and_independent_deployment_without_old_tool_folders(self):
        self.assertFalse((self.deploy / "eml_table_to_excel").exists())
        self.assertFalse((self.deploy / "eml_attachment_tool").exists())
        result = self.command("--version")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("EmailTools 2.0.0", result.stdout)
        self.assertIn(str(self.deploy / "runtime/python/python.exe"), result.stdout)

    def test_unified_cli_options_and_repeated_runs_from_another_working_directory(self):
        for name, flags, mail_count, original_count, text_count, excel in [
            ("tables", "", 0, 0, 0, True),
            ("attachments", "--attachments", 0, 2, 0, False),
            ("text", "--text", 0, 0, 2, False),
            ("all", "--all", 3, 2, 2, True),
        ]:
            with self.subTest(name=name):
                output = self.test_root / ("출력 " + name)
                result = self.command(f'--cli "{self.source}" {flags} --output "{output}"')
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                folder, = output.iterdir()
                self.assertEqual(len(list(folder.rglob("mail.txt"))), mail_count)
                self.assertEqual(len([p for p in folder.rglob("*") if p.is_file() and p.parent.name == "attachments"]), original_count)
                self.assertEqual(len([p for p in folder.rglob("*") if p.is_file() and p.parent.name == "text"]), text_count)
                self.assertEqual((folder / "tables/EML_Table_Result.xlsx").exists(), excel)
                repeated = self.command(f'--cli "{self.source}" {flags} --output "{output}"')
                self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
                self.assertEqual(len(list(output.iterdir())), 2)

    def test_cli_column_configuration_and_invalid_output_path(self):
        config = self.test_root / "columns.json"
        config.write_text(json.dumps([
            {"source": None, "name": "검토", "value": "대기", "enabled": True},
            {"source": "교육명", "name": "교육명", "enabled": True}], ensure_ascii=False), encoding="utf-8")
        output = self.test_root / "configured"
        result = self.command(f'--cli "{self.source}" --tables --columns-file "{config}" --output "{output}"')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        workbook = load_workbook(next(output.glob("*/tables/*.xlsx")))
        try:
            self.assertEqual([c.value for c in workbook.active[1]], ["검토", "교육명"])
            self.assertEqual(workbook.active["A2"].value, "대기")
        finally:
            workbook.close()
        blocked = self.test_root / "cannot-be-directory"
        blocked.write_text("preserve", encoding="utf-8")
        result = self.command(f'--cli "{self.source}" --all --output "{blocked}"')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(blocked.read_text(encoding="utf-8"), "preserve")

    def test_setup_reuses_legacy_runtime_without_network_or_system_python(self):
        original_deploy = self.deploy
        upgrade = self.test_root / "오프라인 업그레이드 & 검증 !"
        upgrade.mkdir()
        shutil.copyfile(ROOT / "setup_runtime.bat", upgrade / "setup_runtime.bat")
        legacy = upgrade / "eml_attachment_tool/python"
        installed = upgrade / "runtime/python"
        shutil.copytree(ROOT / "runtime/python", legacy)
        self.deploy = upgrade
        try:
            result = self.command("", script="setup_runtime.bat")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((installed / "python.exe").is_file())
            self.assertEqual((installed / "python.exe").read_bytes(), (legacy / "python.exe").read_bytes())
            self.assertNotIn("Downloading", result.stdout)
        finally:
            self.deploy = original_deploy

    def test_offline_zip_installation_and_corrupt_zip_leave_no_partial_runtime(self):
        original_deploy = self.deploy
        upgrade = self.test_root / "ZIP 설치 검증"
        upgrade.mkdir()
        shutil.copyfile(ROOT / "setup_runtime.bat", upgrade / "setup_runtime.bat")
        archive_path = upgrade / "python-3.13.15-embed-amd64.zip"
        archive_path.write_bytes(b"not a zip archive")
        self.deploy = upgrade
        try:
            bad = self.command("", script="setup_runtime.bat")
            self.assertNotEqual(bad.returncode, 0)
            self.assertFalse((upgrade / "runtime/python/python.exe").exists())
            self.assertEqual(list((upgrade / "runtime").iterdir()), [])
            with zipfile.ZipFile(archive_path, "w") as output:
                for file in (ROOT / "runtime/python").iterdir():
                    if file.is_file():
                        output.write(file, file.name)
            installed = self.command("", script="setup_runtime.bat")
            self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
            self.assertTrue((upgrade / "runtime/python/python.exe").is_file())
            self.assertNotIn("Downloading", installed.stdout)
        finally:
            self.deploy = original_deploy


if __name__ == "__main__":
    unittest.main()
