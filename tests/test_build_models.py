"""Tests for Build model validation."""

from __future__ import annotations
try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import unittest
import uuid

from pc_parts_organizer.models import (
    BUILD_KINDS,
    MAX_BUILD_NAME_LENGTH,
    MAX_BUILD_NOTES_LENGTH,
    Build,
    BuildValidationError,
)


class TestBuildModel(unittest.TestCase):
    def _id(self) -> str:
        return str(uuid.uuid4())

    def test_auto_uuid_and_explicit_uuid(self) -> None:
        b = Build(name="Mi PC")
        uuid.UUID(b.id, version=4)
        explicit = self._id()
        b2 = Build(name="Otra", id=explicit)
        self.assertEqual(b2.id, explicit)

    def test_invalid_uuid_rejected(self) -> None:
        with self.assertRaises(BuildValidationError):
            Build(name="X", id="not-a-uuid")
        with self.assertRaises(BuildValidationError):
            Build(name="X", id=str(uuid.uuid1()))

    def test_name_required_and_normalized(self) -> None:
        with self.assertRaises(BuildValidationError):
            Build(name="")
        with self.assertRaises(BuildValidationError):
            Build(name="   ")
        with self.assertRaises(BuildValidationError):
            Build(name=None)  # type: ignore[arg-type]
        b = Build(name="  Mi PC Ñ  ")
        self.assertEqual(b.name, "Mi PC Ñ")

    def test_name_length_limit(self) -> None:
        Build(name="x" * MAX_BUILD_NAME_LENGTH)
        with self.assertRaises(BuildValidationError):
            Build(name="x" * (MAX_BUILD_NAME_LENGTH + 1))

    def test_notes_optional_normalized_and_limited(self) -> None:
        self.assertEqual(Build(name="A").notes, "")
        self.assertEqual(Build(name="A", notes=None).notes, "")
        self.assertEqual(Build(name="A", notes="  nota  ").notes, "nota")
        Build(name="A", notes="x" * MAX_BUILD_NOTES_LENGTH)
        with self.assertRaises(BuildValidationError):
            Build(name="A", notes="x" * (MAX_BUILD_NOTES_LENGTH + 1))

    def test_kinds_current_planned_and_unknown(self) -> None:
        self.assertEqual(Build(name="A", kind="current").kind, "current")
        self.assertEqual(Build(name="A", kind="planned").kind, "planned")
        self.assertEqual(Build(name="A", kind=" CURRENT ").kind, "current")
        with self.assertRaises(BuildValidationError):
            Build(name="A", kind="archived")
        with self.assertRaises(BuildValidationError):
            Build(name="A", kind=123)  # type: ignore[arg-type]
        self.assertEqual(BUILD_KINDS, ("current", "planned"))

    def test_component_ids_empty_valid(self) -> None:
        self.assertEqual(Build(name="A").component_ids, [])
        self.assertEqual(Build(name="A", component_ids=[]).component_ids, [])
        self.assertEqual(Build(name="A", component_ids=None).component_ids, [])

    def test_component_ids_valid_and_duplicate_rejected(self) -> None:
        a, b = self._id(), self._id()
        build = Build(name="A", component_ids=[a, b])
        self.assertEqual(build.component_ids, [a, b])
        with self.assertRaises(BuildValidationError):
            Build(name="A", component_ids=[a, a])
        with self.assertRaises(BuildValidationError):
            Build(name="A", component_ids=[a, "bad"])
        with self.assertRaises(BuildValidationError):
            Build(name="A", component_ids="not-a-list")  # type: ignore[arg-type]

    def test_defensive_copies_input(self) -> None:
        a = self._id()
        src = [a]
        build = Build(name="A", component_ids=src)
        src.append(self._id())
        self.assertEqual(build.component_ids, [a])

    def test_wrong_types_rejected(self) -> None:
        with self.assertRaises(BuildValidationError):
            Build(name=123)  # type: ignore[arg-type]
        with self.assertRaises(BuildValidationError):
            Build(name="A", notes=123)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
