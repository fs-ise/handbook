"""Load and validate the canonical handbook course registry."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "data" / "courses.yml"


class CourseRegistryError(ValueError):
    """Raised when the registry or a course reference is invalid."""


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise CourseRegistryError(f"Duplicate YAML key: {key}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)


class CourseRegistry:
    """Canonical definitions and legacy-identifier resolution for courses."""

    def __init__(self, courses: dict[str, dict[str, Any]]) -> None:
        self.courses = courses
        self._identifiers: dict[str, str] = {}
        for course_id, definition in courses.items():
            if not isinstance(course_id, str) or not course_id.isalpha() or course_id != course_id.upper():
                raise CourseRegistryError(f"Canonical identifier must be uppercase letters: {course_id!r}")
            if not isinstance(definition, dict) or not isinstance(definition.get("title"), str) or not definition["title"].strip():
                raise CourseRegistryError(f"Course {course_id} must have a non-empty title")
            aliases = definition.get("aliases", [])
            if not isinstance(aliases, list) or not all(isinstance(alias, str) and alias.strip() for alias in aliases):
                raise CourseRegistryError(f"Aliases for {course_id} must be a list of identifiers")
            for identifier in (course_id, *aliases):
                if identifier in self._identifiers:
                    owner = self._identifiers[identifier]
                    raise CourseRegistryError(f"Identifier {identifier!r} is used by both {owner} and {course_id}")
                self._identifiers[identifier] = course_id

    def resolve(self, identifier: str) -> str:
        """Return the canonical identifier for a canonical ID or legacy alias."""
        try:
            return self._identifiers[identifier.strip()]
        except (KeyError, AttributeError) as exc:
            raise CourseRegistryError(f"Unknown course identifier: {identifier!r}") from exc

    def definition(self, identifier: str) -> dict[str, Any]:
        """Return the permanent definition for an identifier or alias."""
        return self.courses[self.resolve(identifier)]


def load_course_registry(path: Path = DEFAULT_REGISTRY) -> CourseRegistry:
    """Load a registry, rejecting duplicate keys and malformed definitions."""
    try:
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise CourseRegistryError(f"Invalid course registry YAML: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("courses"), dict):
        raise CourseRegistryError("Course registry must contain a 'courses' mapping")
    return CourseRegistry(data["courses"])


def resolve_course_metadata(metadata: dict[str, Any], registry: CourseRegistry) -> tuple[str, dict[str, Any]]:
    """Resolve an offering's new course_id or backwards-compatible title_short."""
    reference = metadata.get("course_id") or metadata.get("title_short")
    if not reference:
        raise CourseRegistryError("Course offering has no course_id or title_short")
    canonical = registry.resolve(str(reference))
    return canonical, registry.courses[canonical]


def validate_course_references(offerings: Iterable[tuple[str, dict[str, Any]]], registry: CourseRegistry) -> None:
    """Reject unknown or non-canonical explicit course_id references."""
    errors: list[str] = []
    for source, metadata in offerings:
        try:
            canonical, _ = resolve_course_metadata(metadata, registry)
            explicit = metadata.get("course_id")
            if explicit and explicit != canonical:
                errors.append(f"{source}: course_id {explicit!r} must use canonical identifier {canonical!r}")
        except CourseRegistryError as exc:
            errors.append(f"{source}: {exc}")
    if errors:
        raise CourseRegistryError("Invalid course references:\n" + "\n".join(errors))
