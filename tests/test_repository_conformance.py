import tempfile
import unittest
from pathlib import Path

from src.repository_conformance import render_qmd


class RenderQmdTest(unittest.TestCase):
    def test_summary_repository_links_open_in_new_tab(self) -> None:
        report = {
            "generated_at": "2026-07-24T00:00:00Z",
            "repositories": [
                {
                    "repository": "fs-ise/example",
                    "repository_url": "https://github.com/fs-ise/example",
                    "repository_type": "materials",
                    "overall_status": "pass",
                    "counts": {
                        "pass": 1,
                        "warning": 0,
                        "fail": 0,
                        "not_checked": 0,
                        "error": 0,
                    },
                    "course_id": "example",
                    "course": "Example course",
                    "source_path": "teaching/courses/example.qmd",
                    "commit": None,
                    "errors": [],
                    "checks": [],
                }
            ],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "report.qmd"
            render_qmd(report, output)
            rendered = output.read_text(encoding="utf-8")

        self.assertIn(
            "| [fs-ise/example](https://github.com/fs-ise/example)"
            '{target="_blank"} | materials |',
            rendered,
        )


if __name__ == "__main__":
    unittest.main()
