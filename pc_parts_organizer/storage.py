"""Storage path resolution and inventory persistence for PC Parts Organizer.

Inventory schema evolution:
- schema_version 1 (legacy): keys {schema_version, components}; component keys
  {id, category, manufacturer, model, specifications, notes}.
- schema_version 2 (consolidated, definitive): adds {status, location, purchase_date,
  warranty_end_date, purchase_price, purchase_currency}.
- schema_version 3: adds builds collection {id,name,notes,kind,component_ids}.
- schema_version 4 (current): adds technical_profiles collection
  {component_id,profile_version,attributes:[{key,value,unit,original_value,source,
  confidence,verification_status,evidence_ref,verified_at}]}. Profiles are independent
  UUID-linked entities (max 1 per component) validated against a category registry.
  Component keeps its 12 fields unchanged.
- Loading accepts v1-v4. v1/v2/v3 => technical_profiles=[] in memory, builds=[] for
  v1/v2. Loading never rewrites/migrates files. v1-v3 conversion happens only on normal
  complete-state writes (schema v4).
- Unknown schema versions and unknown keys are rejected. Invalid/corrupt files are
  never treated as empty inventories; no partial repair.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pc_parts_organizer.models import (
    Build,
    BuildValidationError,
    Component,
    ComponentValidationError,
)
from pc_parts_organizer.technical_profiles import (
    PROFILE_KEYS,
    TechnicalProfile,
    TechnicalProfileValidationError,
    parse_profile_dict,
)

APP_DATA_DIR_NAME = "PCPartsOrganizer"
COMPONENTS_FILE_NAME = "components.json"
SETTINGS_FILE_NAME = "settings.json"
BACKUPS_DIR_NAME = "backups"
PRE_RESTORE_BACKUP_DIR_NAME = "pre-restore"
SUPPORTED_INVENTORY_SCHEMA_VERSIONS = (1, 2, 3, 4)
WRITE_INVENTORY_SCHEMA_VERSION = 4
SETTINGS_SCHEMA_VERSION = 1
DEFAULT_LANGUAGE = "es"
ROOT_KEYS_V1V2 = {"schema_version", "components"}
ROOT_KEYS_V3 = {"schema_version", "components", "builds"}
ROOT_KEYS_V4 = {"schema_version", "components", "builds", "technical_profiles"}
COMPONENT_KEYS_V1 = {
    "id",
    "category",
    "manufacturer",
    "model",
    "specifications",
    "notes",
}
COMPONENT_KEYS_V2 = COMPONENT_KEYS_V1 | {
    "status",
    "location",
    "purchase_date",
    "warranty_end_date",
    "purchase_price",
    "purchase_currency",
}
REQUIRED_COMPONENT_KEYS = {"id", "category", "manufacturer", "model"}
BUILD_KEYS = {"id", "name", "notes", "kind", "component_ids"}
REQUIRED_BUILD_KEYS = {"id", "name", "kind"}
_OMIT = object()


class StorageError(Exception):
    """Base error for storage-related operations."""


@dataclass
class ProjectState:
    """Complete persistent project state (inventory + builds + technical profiles)."""

    components: list[Component]
    builds: list[Build]
    technical_profiles: list[TechnicalProfile] | None = None
    schema_version: int = WRITE_INVENTORY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.technical_profiles is None:
            self.technical_profiles = []


@dataclass
class InventoryFileInfo:
    """Validated inventory/project file metadata (no UI)."""

    components: list[Component]
    schema_version: int
    sha256: str
    path: Path | None = None
    builds: list[Build] | None = None
    technical_profiles: list[TechnicalProfile] | None = None

    def __post_init__(self) -> None:
        if self.builds is None:
            self.builds = []
        if self.technical_profiles is None:
            self.technical_profiles = []


def _get_local_app_data_path() -> Path:
    raw_value = os.environ.get("LOCALAPPDATA")
    if raw_value is None or not raw_value.strip():
        raise StorageError("LOCALAPPDATA is not set or is empty.")
    path = Path(raw_value)
    if not path.is_absolute():
        raise StorageError("LOCALAPPDATA must be an absolute path.")
    return path


def get_data_directory() -> Path:
    """Return the application data directory without creating it."""
    return _get_local_app_data_path() / APP_DATA_DIR_NAME


def get_components_file_path() -> Path:
    """Return the components JSON file path without creating it."""
    return get_data_directory() / COMPONENTS_FILE_NAME


def get_settings_file_path() -> Path:
    """Return the settings JSON file path without creating it."""
    return get_data_directory() / SETTINGS_FILE_NAME


def _validate_schema_version(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value not in SUPPORTED_INVENTORY_SCHEMA_VERSIONS:
        raise StorageError(f"schema_version must be one of {SUPPORTED_INVENTORY_SCHEMA_VERSIONS}.")
    return value


def _validate_root(document: object) -> tuple[int, list[object], list[object], list[object]]:
    if not isinstance(document, dict):
        raise StorageError("Inventory JSON root must be an object.")
    if "schema_version" not in document:
        raise StorageError("schema_version is required.")
    schema_version = _validate_schema_version(document["schema_version"])
    if schema_version in (1, 2):
        allowed_root = ROOT_KEYS_V1V2
    elif schema_version == 3:
        allowed_root = ROOT_KEYS_V3
    else:
        allowed_root = ROOT_KEYS_V4
    unknown_keys = set(document) - allowed_root
    if unknown_keys:
        raise StorageError(f"Unknown root keys: {', '.join(sorted(unknown_keys))}.")
    if "components" not in document:
        raise StorageError("components is required.")
    components = document["components"]
    if not isinstance(components, list):
        raise StorageError("components must be a list.")
    if schema_version in (1, 2):
        return schema_version, components, [], []
    if "builds" not in document:
        raise StorageError("builds is required.")
    builds = document["builds"]
    if not isinstance(builds, list):
        raise StorageError("builds must be a list.")
    if schema_version == 3:
        return schema_version, components, builds, []
    if "technical_profiles" not in document:
        raise StorageError("technical_profiles is required.")
    profiles = document["technical_profiles"]
    if not isinstance(profiles, list):
        raise StorageError("technical_profiles must be a list.")
    return schema_version, components, builds, profiles


def _validate_component_item(item: object, index: int, schema_version: int) -> Component:
    if not isinstance(item, dict):
        raise StorageError(f"Component at index {index} must be an object.")
    allowed_keys = COMPONENT_KEYS_V1 if schema_version == 1 else COMPONENT_KEYS_V2
    unknown_keys = set(item) - allowed_keys
    if unknown_keys:
        raise StorageError(f"Component at index {index} has unknown keys: {', '.join(sorted(unknown_keys))}.")
    missing_keys = REQUIRED_COMPONENT_KEYS - set(item)
    if missing_keys:
        raise StorageError(f"Component at index {index} is missing required keys: {', '.join(sorted(missing_keys))}.")
    try:
        return Component(
            id=item["id"], category=item["category"], manufacturer=item["manufacturer"], model=item["model"],
            specifications=item.get("specifications", ""), notes=item.get("notes", ""),
            status=item.get("status", "unspecified"), location=item.get("location", ""),
            purchase_date=item.get("purchase_date", ""), warranty_end_date=item.get("warranty_end_date", ""),
            purchase_price=item.get("purchase_price", ""), purchase_currency=item.get("purchase_currency", ""),
        )
    except ComponentValidationError as exc:
        raise StorageError(f"Component at index {index} is invalid: {exc}") from exc


def _validate_build_item(item: object, index: int) -> Build:
    if not isinstance(item, dict):
        raise StorageError(f"Build at index {index} must be an object.")
    unknown_keys = set(item) - BUILD_KEYS
    if unknown_keys:
        raise StorageError(f"Build at index {index} has unknown keys: {', '.join(sorted(unknown_keys))}.")
    missing_keys = REQUIRED_BUILD_KEYS - set(item)
    if missing_keys:
        raise StorageError(f"Build at index {index} is missing required keys: {', '.join(sorted(missing_keys))}.")
    try:
        return Build(id=item["id"], name=item["name"], notes=item.get("notes", ""), kind=item["kind"], component_ids=item.get("component_ids", []))
    except BuildValidationError as exc:
        raise StorageError(f"Build at index {index} is invalid: {exc}") from exc


def _validate_cross_references(
    components: list[Component],
    builds: list[Build],
    technical_profiles: list[TechnicalProfile] | None = None,
) -> None:
    component_ids = {c.id for c in components}
    build_ids: set[str] = set()
    build_names: set[str] = set()
    global_component_refs: set[str] = set()
    for index, build in enumerate(builds):
        if build.id in build_ids:
            raise StorageError(f"Build at index {index} has a duplicate id.")
        build_ids.add(build.id)
        name_key = build.name.strip().casefold()
        if name_key in build_names:
            raise StorageError(f"Build at index {index} has a duplicate name.")
        build_names.add(name_key)
        for cid in build.component_ids:
            if cid not in component_ids:
                raise StorageError(f"Build at index {index} references unknown component id: {cid}")
            if cid in global_component_refs:
                raise StorageError(f"Component id {cid} is assigned to more than one build.")
            global_component_refs.add(cid)
    profile_owner_ids: set[str] = set()
    for index, profile in enumerate(technical_profiles or []):
        if profile.component_id not in component_ids:
            raise StorageError(f"Technical profile at index {index} references unknown component id: {profile.component_id}")
        if profile.component_id in profile_owner_ids:
            raise StorageError(f"Technical profile at index {index} has a duplicate component_id.")
        profile_owner_ids.add(profile.component_id)


def _parse_validated_project_state(
    document: object,
) -> tuple[int, list[Component], list[Build], list[TechnicalProfile]]:
    schema_version, items, build_items, profile_items = _validate_root(document)
    components: list[Component] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(items):
        component = _validate_component_item(item, index, schema_version)
        if component.id in seen_ids:
            raise StorageError(f"Component at index {index} has a duplicate id.")
        seen_ids.add(component.id)
        components.append(component)
    component_categories = {c.id: c.category for c in components}
    builds: list[Build] = []
    for index, item in enumerate(build_items):
        builds.append(_validate_build_item(item, index))
    profiles: list[TechnicalProfile] = []
    seen_profile_owners: set[str] = set()
    for index, item in enumerate(profile_items):
        if not isinstance(item, dict):
            raise StorageError(f"Technical profile at index {index} must be an object.")
        component_id_raw = item.get("component_id")
        try:
            # normalize id for lookup/key tracking; parse_profile_dict also validates
            from pc_parts_organizer.technical_profiles import _normalize_uuid
            owner_id = _normalize_uuid(component_id_raw, "component_id")
        except TechnicalProfileValidationError as exc:
            raise StorageError(f"Technical profile at index {index} is invalid: {exc}") from exc
        if owner_id in seen_profile_owners:
            raise StorageError(f"Technical profile at index {index} has a duplicate component_id.")
        seen_profile_owners.add(owner_id)
        category = component_categories.get(owner_id)
        if category is None:
            raise StorageError(f"Technical profile at index {index} references unknown component id: {owner_id}")
        try:
            profile = parse_profile_dict(item, index, category)
        except TechnicalProfileValidationError as exc:
            raise StorageError(f"Technical profile at index {index} is invalid: {exc}") from exc
        profiles.append(profile)
    profiles.sort(key=lambda p: p.component_id)
    _validate_cross_references(components, builds, profiles)
    return schema_version, components, builds, profiles


def parse_inventory_text(raw_text: str) -> tuple[int, list[Component], list[Build]]:
    """Parse and strictly validate inventory/project JSON text (v1-v4).

    Historical 3-tuple contract preserved for existing consumers.
    """
    schema_version, components, builds, _profiles = parse_project_state_text(raw_text)
    return schema_version, components, builds


def parse_project_state_text(raw_text: str) -> tuple[int, list[Component], list[Build], list[TechnicalProfile]]:
    """Parse and strictly validate complete project JSON text (v1-v4)."""
    try:
        document = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise StorageError(f"Inventory file contains invalid JSON: {exc.msg}.") from exc
    return _parse_validated_project_state(document)


def load_project_state() -> ProjectState:
    """Load complete project state. Missing file => empty state (no write)."""
    path = get_components_file_path()
    try:
        raw_text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ProjectState(components=[], builds=[], technical_profiles=[], schema_version=WRITE_INVENTORY_SCHEMA_VERSION)
    except UnicodeDecodeError as exc:
        raise StorageError("Inventory file is not valid UTF-8.") from exc
    except OSError as exc:
        raise StorageError(f"Could not read inventory file: {exc}") from exc
    schema_version, components, builds, technical_profiles = parse_project_state_text(raw_text)
    return ProjectState(
        components=components,
        builds=builds,
        technical_profiles=technical_profiles,
        schema_version=schema_version,
    )


def load_components() -> list[Component]:
    """Load components from the inventory JSON file.

    Returns an empty list when the inventory file does not exist.
    Raises StorageError for invalid content or read/decode errors.
    Never rewrites the inventory file.
    """
    return load_project_state().components


def _validated_components_for_save(components: object) -> list[Component]:
    if not isinstance(components, list):
        raise StorageError("components must be a list of Component objects.")
    validated: list[Component] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(components):
        if not isinstance(item, Component):
            raise StorageError(f"Component at index {index} must be a Component instance.")
        try:
            normalized = Component(
                id=item.id, category=item.category, manufacturer=item.manufacturer, model=item.model,
                specifications=item.specifications, notes=item.notes, status=item.status, location=item.location,
                purchase_date=getattr(item, "purchase_date", ""), warranty_end_date=getattr(item, "warranty_end_date", ""),
                purchase_price=getattr(item, "purchase_price", ""), purchase_currency=getattr(item, "purchase_currency", ""),
            )
        except ComponentValidationError as exc:
            raise StorageError(f"Component at index {index} is invalid: {exc}") from exc
        if normalized.id in seen_ids:
            raise StorageError(f"Component at index {index} has a duplicate id.")
        seen_ids.add(normalized.id)
        validated.append(normalized)
    return validated


def _validated_builds_for_save(builds: object) -> list[Build]:
    if builds is None:
        return []
    if not isinstance(builds, list):
        raise StorageError("builds must be a list of Build objects.")
    validated: list[Build] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(builds):
        if not isinstance(item, Build):
            raise StorageError(f"Build at index {index} must be a Build instance.")
        try:
            normalized = Build(id=item.id, name=item.name, notes=item.notes, kind=item.kind, component_ids=list(item.component_ids))
        except BuildValidationError as exc:
            raise StorageError(f"Build at index {index} is invalid: {exc}") from exc
        if normalized.id in seen_ids:
            raise StorageError(f"Build at index {index} has a duplicate id.")
        seen_ids.add(normalized.id)
        validated.append(normalized)
    return validated


def _validated_technical_profiles_for_save(profiles: object) -> list[TechnicalProfile]:
    if profiles is None:
        return []
    if not isinstance(profiles, list):
        raise StorageError("technical_profiles must be a list of TechnicalProfile objects.")
    component_categories: dict[str, str] | None = None
    # category validation requires component context at save time is handled by _validate_cross_references
    # plus explicit category-aware normalization when component categories are known via service/state.
    # Here we defensively normalize copies and basic shape; category/key validity is enforced by callers
    # that have component context and by cross-ref/profile parse paths.
    validated: list[TechnicalProfile] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(profiles):
        if not isinstance(item, TechnicalProfile):
            raise StorageError(f"Technical profile at index {index} must be a TechnicalProfile instance.")
        try:
            normalized = item.copy()
        except TechnicalProfileValidationError as exc:
            raise StorageError(f"Technical profile at index {index} is invalid: {exc}") from exc
        if normalized.component_id in seen_ids:
            raise StorageError(f"Technical profile at index {index} has a duplicate component_id.")
        seen_ids.add(normalized.component_id)
        validated.append(normalized)
    validated.sort(key=lambda p: p.component_id)
    return validated


def _serialize_project_state(
    components: list[Component],
    builds: list[Build],
    technical_profiles: list[TechnicalProfile] | None = None,
) -> str:
    profiles = sorted(technical_profiles or [], key=lambda p: p.component_id)
    document = {
        "schema_version": WRITE_INVENTORY_SCHEMA_VERSION,
        "components": [
            {
                "id": c.id, "category": c.category, "manufacturer": c.manufacturer, "model": c.model,
                "specifications": c.specifications, "notes": c.notes, "status": c.status, "location": c.location,
                "purchase_date": c.purchase_date, "warranty_end_date": c.warranty_end_date,
                "purchase_price": c.purchase_price, "purchase_currency": c.purchase_currency,
            }
            for c in components
        ],
        "builds": [
            {"id": b.id, "name": b.name, "notes": b.notes, "kind": b.kind, "component_ids": list(b.component_ids)}
            for b in builds
        ],
        "technical_profiles": [p.to_dict() for p in profiles],
    }
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


def _is_same_path(a: Path, b: Path) -> bool:
    try:
        return a.resolve(strict=False) == b.resolve(strict=False)
    except OSError:
        return os.path.abspath(os.fspath(a)) == os.path.abspath(os.fspath(b))


def read_inventory_file(path: str | Path, *, expected_sha256: str | None = None) -> InventoryFileInfo:
    """Read and strictly validate an inventory/project JSON file (read-only)."""
    file_path = Path(path)
    try:
        raw_bytes = file_path.read_bytes()
    except FileNotFoundError as exc:
        raise StorageError(f"Inventory file not found: {file_path}") from exc
    except OSError as exc:
        raise StorageError(f"Could not read inventory file: {exc}") from exc
    digest = hashlib.sha256(raw_bytes).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise StorageError("The selected inventory file changed after it was validated.")
    try:
        raw_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StorageError("Inventory file is not valid UTF-8.") from exc
    schema_version, components, builds, technical_profiles = parse_project_state_text(raw_text)
    return InventoryFileInfo(
        components=components,
        builds=builds,
        technical_profiles=technical_profiles,
        schema_version=schema_version,
        sha256=digest,
        path=file_path,
    )


def save_project_state(
    components: list[Component],
    builds: list[Build] | None = None,
    technical_profiles: list[TechnicalProfile] | None | object = _OMIT,
) -> None:
    """Save complete project state to JSON using a safe atomic write (schema v4).

    Omitted `technical_profiles` preserves existing profiles (compat/no accidental loss).
    Explicit `[]` clears profiles.
    """
    validated_components = _validated_components_for_save(components)
    validated_builds = _validated_builds_for_save(builds or [])
    if technical_profiles is _OMIT:
        try:
            existing_profiles = load_project_state().technical_profiles or []
        except Exception:
            existing_profiles = []
        validated_profiles = _validated_technical_profiles_for_save(existing_profiles)
    else:
        validated_profiles = _validated_technical_profiles_for_save(technical_profiles)
    _validate_cross_references(validated_components, validated_builds, validated_profiles)
    # enforce category registry validity for persisted profiles
    categories = {c.id: c.category for c in validated_components}
    from pc_parts_organizer.technical_profiles import validate_profile_for_category

    checked_profiles: list[TechnicalProfile] = []
    for index, profile in enumerate(validated_profiles):
        category = categories.get(profile.component_id)
        if category is None:
            raise StorageError(f"Technical profile at index {index} references unknown component id: {profile.component_id}")
        try:
            checked_profiles.append(validate_profile_for_category(profile, category))
        except TechnicalProfileValidationError as exc:
            raise StorageError(f"Technical profile at index {index} is invalid: {exc}") from exc
    checked_profiles.sort(key=lambda p: p.component_id)
    payload = _serialize_project_state(validated_components, validated_builds, checked_profiles)
    path = get_components_file_path()
    _atomic_write_json(path, payload, "components.")


def save_components(
    components: list[Component],
    builds: list[Build] | None = None,
    technical_profiles: list[TechnicalProfile] | None | object = _OMIT,
) -> None:
    """Save project state. Compatibility: preserves omitted builds/profiles."""
    existing_builds = None
    existing_profiles = _OMIT
    if builds is None or technical_profiles is _OMIT:
        try:
            state = load_project_state()
            existing_builds = state.builds
            existing_profiles = state.technical_profiles or []
        except Exception:
            existing_builds = []
            existing_profiles = []
    if builds is None:
        builds = existing_builds or []
    if technical_profiles is _OMIT:
        technical_profiles = existing_profiles
    save_project_state(components, builds, technical_profiles)


def _export_validated_state(
    components: list[Component],
    builds: list[Build],
    technical_profiles: list[TechnicalProfile],
    destination: str | Path,
    *,
    active_path: str | Path | None = None,
    temp_prefix: str = "inventory-export.",
) -> InventoryFileInfo:
    dest = Path(destination)
    active = Path(active_path) if active_path is not None else get_components_file_path()
    if _is_same_path(dest, active):
        raise StorageError("The export destination cannot be the active inventory file.")
    validated_components = _validated_components_for_save(components)
    validated_builds = _validated_builds_for_save(builds)
    validated_profiles = _validated_technical_profiles_for_save(technical_profiles)
    _validate_cross_references(validated_components, validated_builds, validated_profiles)
    categories = {c.id: c.category for c in validated_components}
    from pc_parts_organizer.technical_profiles import validate_profile_for_category

    checked_profiles = []
    for index, profile in enumerate(validated_profiles):
        category = categories.get(profile.component_id)
        if category is None:
            raise StorageError(f"Technical profile at index {index} references unknown component id: {profile.component_id}")
        try:
            checked_profiles.append(validate_profile_for_category(profile, category))
        except TechnicalProfileValidationError as exc:
            raise StorageError(f"Technical profile at index {index} is invalid: {exc}") from exc
    payload = _serialize_project_state(validated_components, validated_builds, checked_profiles)
    _atomic_write_json(dest, payload, temp_prefix)
    try:
        info = read_inventory_file(dest)
    except StorageError:
        try:
            dest.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return info


def export_project_state(
    state: ProjectState,
    destination: str | Path,
    *,
    active_path: str | Path | None = None,
) -> InventoryFileInfo:
    """Export a complete ProjectState snapshot (unambiguous; preserves all collections)."""
    if not isinstance(state, ProjectState):
        raise StorageError("state must be a ProjectState instance.")
    return _export_validated_state(
        list(state.components),
        list(getattr(state, "builds", []) or []),
        list(getattr(state, "technical_profiles", []) or []),
        destination,
        active_path=active_path,
    )


def export_inventory(
    components: list[Component] | ProjectState,
    destination: str | Path,
    *,
    active_path: str | Path | None = None,
    builds: list[Build] | None = None,
    technical_profiles: list[TechnicalProfile] | None = None,
) -> InventoryFileInfo:
    """Export snapshot/state to JSON and verify.

    - Pass `ProjectState` as first arg for unambiguous complete-state export.
    - Legacy snapshot form accepts components/builds/technical_profiles; omitted
      profiles default to [] (explicit snapshot, not current-state omission).
    """
    if isinstance(components, ProjectState):
        if builds is not None or technical_profiles is not None:
            raise StorageError("Pass either ProjectState or component collections, not both.")
        return export_project_state(components, destination, active_path=active_path)
    return _export_validated_state(
        components,
        builds or [],
        technical_profiles or [],
        destination,
        active_path=active_path,
    )


def get_pre_restore_backup_directory() -> Path:
    return get_data_directory() / BACKUPS_DIR_NAME / PRE_RESTORE_BACKUP_DIR_NAME


def create_pre_restore_backup_from_state(
    state: ProjectState,
    *,
    directory: str | Path | None = None,
) -> InventoryFileInfo:
    """Create and verify a pre-restore backup of a complete ProjectState. Never overwrites."""
    if not isinstance(state, ProjectState):
        raise StorageError("state must be a ProjectState instance.")
    target_dir = Path(directory) if directory is not None else get_pre_restore_backup_directory()
    validated_components = _validated_components_for_save(list(state.components))
    validated_builds = _validated_builds_for_save(list(getattr(state, "builds", []) or []))
    validated_profiles = _validated_technical_profiles_for_save(list(getattr(state, "technical_profiles", []) or []))
    _validate_cross_references(validated_components, validated_builds, validated_profiles)
    categories = {c.id: c.category for c in validated_components}
    from pc_parts_organizer.technical_profiles import validate_profile_for_category

    checked_profiles = []
    for index, profile in enumerate(validated_profiles):
        category = categories.get(profile.component_id)
        if category is None:
            raise StorageError(f"Technical profile at index {index} references unknown component id: {profile.component_id}")
        try:
            checked_profiles.append(validate_profile_for_category(profile, category))
        except TechnicalProfileValidationError as exc:
            raise StorageError(f"Technical profile at index {index} is invalid: {exc}") from exc
    payload = _serialize_project_state(validated_components, validated_builds, checked_profiles)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise StorageError(f"Could not create backup directory: {exc}") from exc
    dest: Path | None = None
    for suffix in [""] + [f"-{i}" for i in range(1, 1000)]:
        candidate = target_dir / f"inventory-pre-restore-{stamp}{suffix}.json"
        if not candidate.exists():
            dest = candidate
            break
    if dest is None:
        raise StorageError("Could not allocate a pre-restore backup file name.")
    _atomic_write_json(dest, payload, "inventory-pre-restore.")
    info = read_inventory_file(dest)
    try:
        verify = hashlib.sha256(dest.read_bytes()).hexdigest()
    except OSError as exc:
        raise StorageError(f"Could not verify pre-restore backup: {exc}") from exc
    if verify != info.sha256:
        raise StorageError("Pre-restore backup integrity verification failed.")
    return info


def create_pre_restore_backup(
    components: list[Component] | ProjectState,
    *,
    builds: list[Build] | None = None,
    technical_profiles: list[TechnicalProfile] | None = None,
    directory: str | Path | None = None,
) -> InventoryFileInfo:
    """Create and verify a pre-restore backup. Never overwrites.

    - Pass `ProjectState` for unambiguous complete-state backup.
    - Legacy snapshot form accepts component collections (omitted profiles => snapshot empty).
    """
    if isinstance(components, ProjectState):
        if builds is not None or technical_profiles is not None:
            raise StorageError("Pass either ProjectState or component collections, not both.")
        return create_pre_restore_backup_from_state(components, directory=directory)
    return create_pre_restore_backup_from_state(
        ProjectState(components=list(components), builds=list(builds or []), technical_profiles=list(technical_profiles or []), schema_version=WRITE_INVENTORY_SCHEMA_VERSION),
        directory=directory,
    )


def _atomic_write_json(path: Path, payload: str, temp_prefix: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise StorageError(f"Could not create data directory: {exc}") from exc
    temp_path: Path | None = None
    try:
        fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=temp_prefix, suffix=".tmp")
        temp_path = Path(temp_name)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as temp_file:
            temp_file.write(payload)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, path)
        temp_path = None
    except OSError as exc:
        raise StorageError(f"Could not save file: {exc}") from exc
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def load_language_preference(supported_languages: tuple[str, ...]) -> str:
    """Load the saved language preference, defaulting safely without modifying files."""
    path = get_settings_file_path()
    try:
        raw_text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return DEFAULT_LANGUAGE
    except (UnicodeDecodeError, OSError):
        return DEFAULT_LANGUAGE

    try:
        document = json.loads(raw_text)
    except json.JSONDecodeError:
        return DEFAULT_LANGUAGE

    if not isinstance(document, dict):
        return DEFAULT_LANGUAGE
    if document.get("schema_version") != SETTINGS_SCHEMA_VERSION:
        return DEFAULT_LANGUAGE
    language = document.get("language")
    if language not in supported_languages:
        return DEFAULT_LANGUAGE
    return language


def save_language_preference(language: str, supported_languages: tuple[str, ...]) -> None:
    """Persist the language preference using a safe atomic write."""
    if language not in supported_languages:
        raise StorageError(f"Unsupported language: {language}")
    document = {"schema_version": SETTINGS_SCHEMA_VERSION, "language": language}
    payload = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    _atomic_write_json(get_settings_file_path(), payload, "settings.")
