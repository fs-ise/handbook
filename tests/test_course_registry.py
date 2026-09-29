import tempfile
import unittest
from pathlib import Path

from src.course_registry import (
    CourseRegistryError,
    load_course_registry,
    resolve_course_metadata,
    validate_course_references,
)
from src.repository_conformance import read_front_matter


class CourseRegistryTest(unittest.TestCase):
    def test_loads_all_canonical_courses(self) -> None:
        registry = load_course_registry()

        self.assertEqual(8, len(registry.courses))
        self.assertEqual("Introduction to Programming", registry.courses["ITP"]["title"])
        self.assertEqual("Literature Review Seminar", registry.courses["LRS"]["title"])

    def test_resolves_canonical_identifiers_and_legacy_aliases(self) -> None:
        registry = load_course_registry()

        self.assertEqual("ITP", registry.resolve("ITP"))
        self.assertEqual("ITP", registry.resolve("Prog"))
        self.assertEqual("ITSEC", registry.resolve("ITSecM"))
        self.assertEqual("LRS", registry.resolve("LRSem"))
        self.assertEqual("LRS", registry.resolve("LRSemHWR"))
        self.assertEqual("LRS", registry.resolve("LRSemIDIS"))
        self.assertEqual("EWI", registry.resolve("EidWI"))

    def test_rejects_duplicate_keys_and_conflicting_aliases(self) -> None:
        invalid_registries = (
            "courses:\n  ABC:\n    title: One\n  ABC:\n    title: Two\n",
            "courses:\n  ABC:\n    title: One\n    aliases: [Old]\n  DEF:\n    title: Two\n    aliases: [Old]\n",
        )
        for contents in invalid_registries:
            with self.subTest(contents=contents), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "courses.yml"
                path.write_text(contents, encoding="utf-8")
                with self.assertRaises(CourseRegistryError):
                    load_course_registry(path)

    def test_rejects_unknown_course_reference(self) -> None:
        registry = load_course_registry()
        with self.assertRaisesRegex(CourseRegistryError, "sample.qmd: Unknown course identifier"):
            resolve_course_metadata({"course_id": "NOPE"}, registry, "sample.qmd")

    def test_rejects_deprecated_title_field_and_finds_none_in_records(self) -> None:
        registry = load_course_registry()
        with self.assertRaisesRegex(CourseRegistryError, "sample.qmd: missing required course_id"):
            resolve_course_metadata({"title_short": "Prog"}, registry, "sample.qmd")

        course_dir = Path(__file__).resolve().parents[1] / "teaching" / "courses"
        for path in sorted(course_dir.iterdir()):
            if path.suffix in {".md", ".qmd"}:
                with self.subTest(path=path):
                    self.assertNotIn("title_short", read_front_matter(path))

    def test_rejects_legacy_alias_as_course_id(self) -> None:
        registry = load_course_registry()
        with self.assertRaisesRegex(
            CourseRegistryError,
            "sample.qmd: course_id 'Prog' is a legacy alias; use canonical identifier 'ITP'",
        ):
            resolve_course_metadata({"course_id": "Prog"}, registry, "sample.qmd")

    def test_all_historical_offerings_have_valid_canonical_references(self) -> None:
        registry = load_course_registry()
        course_dir = Path(__file__).resolve().parents[1] / "teaching" / "courses"
        offerings = [
            (str(path), read_front_matter(path))
            for path in sorted(course_dir.iterdir())
            if path.suffix in {".md", ".qmd"}
        ]

        validate_course_references(offerings, registry)
        for source, metadata in offerings:
            with self.subTest(source=source):
                self.assertIn("course_id", metadata)
                self.assertIn(metadata["course_id"], registry.courses)


if __name__ == "__main__":
    unittest.main()
