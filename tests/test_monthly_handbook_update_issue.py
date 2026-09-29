import unittest
from unittest.mock import patch

from src.monthly_handbook_update_issue import _comment_body, _issue_body


class MonthlyHandbookUpdateIssueTest(unittest.TestCase):
    def test_comment_and_permanent_description_include_course_reminder(self) -> None:
        expected = (
            "Are there any additional courses or new course offerings that should be included "
            "in the handbook?"
        )
        links = (
            "data/courses.yml",
            "teaching/courses",
            "teaching/new_course.html",
            "teaching/course_overview.html",
        )

        with patch("src.monthly_handbook_update_issue._now_utc_monthstamp", return_value="2026-09"):
            bodies = (_comment_body(), _issue_body())

        for body in bodies:
            self.assertIn(expected, body)
            self.assertIn("genuinely new course", body)
            self.assertIn("new offering of an existing course", body)
            for link in links:
                self.assertIn(link, body)


if __name__ == "__main__":
    unittest.main()
