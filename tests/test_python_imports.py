import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PythonImportTest(unittest.TestCase):
    def run_with_shadow_package(self, statement: str) -> subprocess.CompletedProcess[str]:
        """Run an import with an unrelated installed-style ``src`` package present."""
        with tempfile.TemporaryDirectory() as directory:
            shadow_src = Path(directory) / "src"
            shadow_src.mkdir()
            (shadow_src / "__init__.py").write_text(
                '"""Unrelated package used to reproduce src shadowing."""\n',
                encoding="utf-8",
            )
            environment = os.environ.copy()
            environment["PYTHONPATH"] = os.pathsep.join(
                filter(None, (directory, environment.get("PYTHONPATH")))
            )
            return subprocess.run(
                [sys.executable, "-c", statement],
                cwd=ROOT,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )

    def assert_local_import(self, statement: str) -> None:
        result = self.run_with_shadow_package(statement)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(str(ROOT / "src" / "course_registry.py"), result.stdout.strip())

    def test_course_overview_import_uses_local_registry(self) -> None:
        self.assert_local_import(
            "import scripts.course_overview as overview; "
            "print(overview.load_course_registry.__code__.co_filename)"
        )

    def test_reports_import_uses_local_registry(self) -> None:
        self.assert_local_import(
            "import src.course_registry as registry; print(registry.__file__)"
        )


if __name__ == "__main__":
    unittest.main()
