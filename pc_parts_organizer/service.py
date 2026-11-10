"""Inventory/build service layer for PC Parts Organizer.

Public error contract for the UI:
- ComponentValidationError / BuildValidationError (models): invalid data.
- ComponentNotFoundError / BuildNotFoundError (service): entity unavailable.
- BuildNameConflictError: duplicate build name (casefold).
- ComponentInUseError: component is associated with a build and cannot be deleted.
- ComponentAlreadyAssignedError: component is already assigned to a build.
- BatchValidationError (service): a batch was aborted before any write; carries
  per-row rejections. Duplicates and assigned components are reported in the
  BatchAddResult/BatchDeleteResult instead of raising.
- StorageError (storage): read/validation/persistence problem. During CRUD/restore the
  UI must report failure without pretending success.

The service is the single authority for in-memory project state (components + builds).
All mutations are transactional: validate candidate complete state -> persist complete
state -> commit memory only after successful persistence.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from decimal import Decimal, localcontext
from pathlib import Path

from pc_parts_organizer.catalog_models import catalog_duplicate_key as _catalog_duplicate_key
from pc_parts_organizer.models import (
    CATEGORIES,
    Build,
    BuildValidationError,
    Component,
    ComponentValidationError,
)
from pc_parts_organizer.storage import (
    InventoryFileInfo,
    ProjectState,
    StorageError,
    create_pre_restore_backup,
    load_components as _storage_load_components,
    load_project_state as _storage_load_project_state,
    save_components as _storage_save_components,
    save_project_state as _storage_save_project_state,
)
from pc_parts_organizer.technical_profiles import (
    ATTRIBUTE_REGISTRY,
    TechnicalProfile,
    TechnicalProfileValidationError,
    validate_profile_for_category,
)

# Compatibility names exposed for test patching / legacy callers.
load_components = _storage_load_components
load_project_state = _storage_load_project_state
save_components = _storage_save_components
save_project_state = _storage_save_project_state


class ComponentNotFoundError(LookupError):
    """Raised when a requested component does not exist."""

    def __init__(self, component_id: str) -> None:
        super().__init__(f"Component not found: {component_id}")
        self.component_id = component_id


class BuildNotFoundError(LookupError):
    """Raised when a requested build does not exist."""

    def __init__(self, build_id: str) -> None:
        super().__init__(f"Build not found: {build_id}")
        self.build_id = build_id


class BuildNameConflictError(ValueError):
    """Raised when a build name conflicts with an existing build."""

    def __init__(self, name: str) -> None:
        super().__init__(f"Build name already exists: {name}")
        self.name = name


class ComponentInUseError(ValueError):
    """Raised when deleting a component that is associated with a build."""

    def __init__(self, component_id: str, build_id: str) -> None:
        super().__init__(f"Component {component_id} is associated with build {build_id}.")
        self.component_id = component_id
        self.build_id = build_id


class ComponentAlreadyAssignedError(ValueError):
    """Raised when a component is already assigned to a build."""

    def __init__(self, component_id: str, build_id: str) -> None:
        super().__init__(f"Component {component_id} is already assigned to build {build_id}.")
        self.component_id = component_id
        self.build_id = build_id


class TechnicalProfileCategoryConflictError(ValueError):
    """Raised when a component category change is incompatible with its technical profile."""

    def __init__(self, component_id: str, current_category: str, new_category: str) -> None:
        super().__init__(
            f"Component {component_id} category change {current_category!r} -> {new_category!r} is incompatible with its technical profile."
        )
        self.component_id = component_id
        self.current_category = current_category
        self.new_category = new_category


def _canonical_decimal_text(value: Decimal) -> str:
    """Return a canonical decimal string (no sci notation, no trailing zeros, '.' separator)."""
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


@dataclass
class InventoryRestoreResult:
    """Result of a completed inventory/project restore."""

    restored_count: int
    pre_restore_backup: InventoryFileInfo
    restored_build_count: int = 0
    restored_technical_profile_count: int = 0


@dataclass(frozen=True)
class BatchDuplicate:
    """A batch item skipped because it duplicates an existing component."""

    index: int
    name: str
    matched_name: str


@dataclass(frozen=True)
class BatchRejection:
    """A batch item rejected before any persistence happened."""

    index: int
    name: str
    reason: str


@dataclass
class BatchAddResult:
    """Outcome of add_components: created items plus per-row skip reports."""

    created: list[Component] = field(default_factory=list)
    duplicates: list[BatchDuplicate] = field(default_factory=list)


@dataclass(frozen=True)
class BatchSkipped:
    """A batch deletion skipped because the component is assigned."""

    component_id: str
    name: str
    build_name: str


@dataclass
class BatchDeleteResult:
    """Outcome of delete_components: deleted items plus explicit skips."""

    deleted: list[Component] = field(default_factory=list)
    skipped_in_use: list[BatchSkipped] = field(default_factory=list)
    not_found: list[str] = field(default_factory=list)


class BatchValidationError(ValueError):
    """A batch was aborted before any write: carries per-row rejections."""

    def __init__(self, rejected: list[BatchRejection]) -> None:
        details = "; ".join(f"[{r.index}] {r.name or '?'}: {r.reason}" for r in rejected)
        super().__init__(f"Batch rejected with no changes applied: {details}")
        self.rejected = list(rejected)


@dataclass
class InventorySummary:
    """Global inventory summary for the dashboard."""

    total_count: int
    category_counts: dict[str, int] = field(default_factory=dict)
    priced_component_count: int = 0
    unpriced_component_count: int = 0
    price_subtotals_by_currency: dict[str, str] = field(default_factory=dict)


_PRESERVE = object()


def _normalize_components(components: list[Component]) -> list[Component]:
    if not isinstance(components, list):
        raise StorageError("components must be a list of Component objects.")
    normalized: list[Component] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(components):
        if not isinstance(item, Component):
            raise StorageError(f"Component at index {index} must be a Component instance.")
        try:
            c = Component(
                id=item.id, category=item.category, manufacturer=item.manufacturer, model=item.model,
                specifications=item.specifications, notes=item.notes, status=item.status, location=item.location,
                purchase_date=getattr(item, "purchase_date", ""),
                warranty_end_date=getattr(item, "warranty_end_date", ""),
                purchase_price=getattr(item, "purchase_price", ""),
                purchase_currency=getattr(item, "purchase_currency", ""),
            )
        except ComponentValidationError as exc:
            raise StorageError(f"Component at index {index} is invalid: {exc}") from exc
        if c.id in seen_ids:
            raise StorageError(f"Component at index {index} has a duplicate id.")
        seen_ids.add(c.id)
        normalized.append(c)
    return normalized


def _normalize_builds(builds: list[Build] | None) -> list[Build]:
    if builds is None:
        return []
    if not isinstance(builds, list):
        raise StorageError("builds must be a list of Build objects.")
    normalized: list[Build] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(builds):
        if not isinstance(item, Build):
            raise StorageError(f"Build at index {index} must be a Build instance.")
        try:
            b = Build(id=item.id, name=item.name, notes=item.notes, kind=item.kind, component_ids=list(item.component_ids))
        except BuildValidationError as exc:
            raise StorageError(f"Build at index {index} is invalid: {exc}") from exc
        if b.id in seen_ids:
            raise StorageError(f"Build at index {index} has a duplicate id.")
        seen_ids.add(b.id)
        normalized.append(b)
    return normalized


def _normalize_technical_profiles(profiles: list[TechnicalProfile] | None) -> list[TechnicalProfile]:
    if profiles is None:
        return []
    if not isinstance(profiles, list):
        raise StorageError("technical_profiles must be a list of TechnicalProfile objects.")
    normalized: list[TechnicalProfile] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(profiles):
        if not isinstance(item, TechnicalProfile):
            raise StorageError(f"Technical profile at index {index} must be a TechnicalProfile instance.")
        try:
            p = item.copy()
        except TechnicalProfileValidationError as exc:
            raise StorageError(f"Technical profile at index {index} is invalid: {exc}") from exc
        if p.component_id in seen_ids:
            raise StorageError(f"Technical profile at index {index} has a duplicate component_id.")
        seen_ids.add(p.component_id)
        normalized.append(p)
    normalized.sort(key=lambda p: p.component_id)
    return normalized


def _validate_build_references(components: list[Component], builds: list[Build], *, exclude_build_id: str | None = None) -> None:
    component_ids = {c.id for c in components}
    names: set[str] = set()
    global_refs: dict[str, str] = {}
    for build in builds:
        key = build.name.strip().casefold()
        if key in names:
            raise BuildNameConflictError(build.name)
        names.add(key)
        for cid in build.component_ids:
            if cid not in component_ids:
                raise ComponentNotFoundError(cid)
            if cid in global_refs and global_refs[cid] != build.id:
                raise ComponentAlreadyAssignedError(cid, global_refs[cid])
            if exclude_build_id is None or build.id != exclude_build_id:
                global_refs[cid] = build.id
            elif cid in global_refs and global_refs[cid] != build.id:
                raise ComponentAlreadyAssignedError(cid, global_refs[cid])
            else:
                global_refs[cid] = build.id


def _validate_technical_profile_references(components: list[Component], profiles: list[TechnicalProfile]) -> list[TechnicalProfile]:
    categories = {c.id: c.category for c in components}
    seen: set[str] = set()
    checked: list[TechnicalProfile] = []
    for index, profile in enumerate(profiles):
        if profile.component_id in seen:
            raise StorageError(f"Technical profile at index {index} has a duplicate component_id.")
        seen.add(profile.component_id)
        category = categories.get(profile.component_id)
        if category is None:
            raise ComponentNotFoundError(profile.component_id)
        try:
            checked.append(validate_profile_for_category(profile, category))
        except TechnicalProfileValidationError as exc:
            raise StorageError(f"Technical profile at index {index} is invalid: {exc}") from exc
    checked.sort(key=lambda p: p.component_id)
    return checked


class InventoryService:
    """Manage complete project state (inventory + builds + technical profiles) transactionally."""

    def __init__(self) -> None:
        state = self._load_state()
        self._components = [deepcopy(c) for c in state.components]
        self._builds = [deepcopy(b) for b in getattr(state, "builds", []) or []]
        self._technical_profiles = [p.copy() for p in getattr(state, "technical_profiles", []) or []]

    def _load_state(self) -> ProjectState:
        # Support legacy tests/callers patching load_components on this module.
        if load_project_state is not _storage_load_project_state:
            state = load_project_state()
            if isinstance(state, list):
                return ProjectState(components=state, builds=[], technical_profiles=[])
            return state
        if load_components is not _storage_load_components:
            comps = load_components()
            return ProjectState(components=comps, builds=[], technical_profiles=[])
        return load_project_state()

    # --- internal state/persistence ---
    _PRESERVE_PROFILES = object()

    def _commit(
        self,
        components: list[Component],
        builds: list[Build],
        technical_profiles: list[TechnicalProfile] | None | object = _PRESERVE_PROFILES,
    ) -> None:
        if technical_profiles is self._PRESERVE_PROFILES:
            candidate_profiles = [p.copy() for p in self._technical_profiles]
        else:
            candidate_profiles = _normalize_technical_profiles(technical_profiles)
        profiles = _validate_technical_profile_references(components, candidate_profiles)
        comps_arg = [deepcopy(c) for c in components]
        builds_arg = [deepcopy(b) for b in builds]
        profiles_arg = [p.copy() for p in profiles]
        # Prefer save_project_state; honor legacy save_components patches.
        if save_project_state is not _storage_save_project_state:
            try:
                save_project_state(comps_arg, builds_arg, profiles_arg)
            except TypeError:
                save_project_state(comps_arg, builds_arg)
        elif save_components is not _storage_save_components:
            # Legacy patch point expects (components[, builds[, profiles]]) or fewer.
            try:
                save_components(comps_arg, builds_arg, profiles_arg)
            except TypeError:
                try:
                    save_components(comps_arg, builds_arg)
                except TypeError:
                    save_components(comps_arg)
        else:
            save_project_state(comps_arg, builds_arg, profiles_arg)
        self._components = [deepcopy(c) for c in components]
        self._builds = [deepcopy(b) for b in builds]
        self._technical_profiles = [p.copy() for p in profiles]

    def _find_component_index(self, component_id: str) -> int | None:
        for index, component in enumerate(self._components):
            if component.id == component_id:
                return index
        return None

    def _find_build_index(self, build_id: str) -> int | None:
        for index, build in enumerate(self._builds):
            if build.id == build_id:
                return index
        return None

    def _find_build_for_component(self, component_id: str) -> Build | None:
        for build in self._builds:
            if component_id in build.component_ids:
                return build
        return None

    def _check_build_name_unique(self, name: str, *, exclude_build_id: str | None = None) -> None:
        key = name.strip().casefold()
        for build in self._builds:
            if exclude_build_id is not None and build.id == exclude_build_id:
                continue
            if build.name.strip().casefold() == key:
                raise BuildNameConflictError(name)

    # --- components (existing contracts preserved) ---
    def get_components(self) -> list[Component]:
        return [deepcopy(component) for component in self._components]

    def get_component(self, component_id: str) -> Component | None:
        for component in self._components:
            if component.id == component_id:
                return deepcopy(component)
        return None

    def get_summary(self) -> InventorySummary:
        """Return a global summary of the current in-memory inventory."""
        counts: dict[str, int] = {}
        priced_count = 0
        subtotals: dict[str, Decimal] = {}
        with localcontext() as ctx:
            ctx.prec = 50
            for component in self._components:
                counts[component.category] = counts.get(component.category, 0) + 1
                if component.purchase_price and component.purchase_currency:
                    priced_count += 1
                    currency = component.purchase_currency
                    subtotals[currency] = subtotals.get(currency, Decimal("0")) + Decimal(component.purchase_price)
        ordered_counts = {category: counts[category] for category in CATEGORIES if category in counts}
        total_count = len(self._components)
        ordered_subtotals = {currency: _canonical_decimal_text(subtotals[currency]) for currency in sorted(subtotals)}
        return InventorySummary(
            total_count=total_count,
            category_counts=ordered_counts,
            priced_component_count=priced_count,
            unpriced_component_count=total_count - priced_count,
            price_subtotals_by_currency=ordered_subtotals,
        )

    def add_component(
        self, category: str, manufacturer: str, model: str, specifications: str | None = "",
        notes: str | None = "", status: str = "unspecified", location: str | None = "",
        purchase_date: str | None = "", warranty_end_date: str | None = "",
        purchase_price: str | None = "", purchase_currency: str | None = "",
    ) -> Component:
        new_component = Component(
            category=category, manufacturer=manufacturer, model=model, specifications=specifications, notes=notes,
            status=status, location=location, purchase_date=purchase_date, warranty_end_date=warranty_end_date,
            purchase_price=purchase_price, purchase_currency=purchase_currency,
        )
        candidate_components = [deepcopy(c) for c in self._components] + [deepcopy(new_component)]
        candidate_builds = [deepcopy(b) for b in self._builds]
        self._commit(candidate_components, candidate_builds)
        return deepcopy(new_component)

    def update_component(
        self, component_id: str, category: str, manufacturer: str, model: str,
        specifications: str | None = "", notes: str | None = "",
        status: object = _PRESERVE, location: object = _PRESERVE,
        purchase_date: object = _PRESERVE, warranty_end_date: object = _PRESERVE,
        purchase_price: object = _PRESERVE, purchase_currency: object = _PRESERVE,
    ) -> Component:
        index = self._find_component_index(component_id)
        if index is None:
            raise ComponentNotFoundError(component_id)
        existing = self._components[index]
        updated = Component(
            id=component_id, category=category, manufacturer=manufacturer, model=model,
            specifications=specifications, notes=notes,
            status=existing.status if status is _PRESERVE else status,
            location=existing.location if location is _PRESERVE else location,
            purchase_date=existing.purchase_date if purchase_date is _PRESERVE else purchase_date,
            warranty_end_date=existing.warranty_end_date if warranty_end_date is _PRESERVE else warranty_end_date,
            purchase_price=existing.purchase_price if purchase_price is _PRESERVE else purchase_price,
            purchase_currency=existing.purchase_currency if purchase_currency is _PRESERVE else purchase_currency,
        )
        profile = self._find_technical_profile(component_id)
        if profile is not None and existing.category != updated.category:
            try:
                validate_profile_for_category(profile, updated.category)
            except TechnicalProfileValidationError as exc:
                raise TechnicalProfileCategoryConflictError(component_id, existing.category, updated.category) from exc
        candidate_components = [deepcopy(c) for c in self._components]
        candidate_components[index] = deepcopy(updated)
        candidate_builds = [deepcopy(b) for b in self._builds]
        self._commit(candidate_components, candidate_builds)
        return deepcopy(updated)

    def delete_component(self, component_id: str) -> None:
        index = self._find_component_index(component_id)
        if index is None:
            raise ComponentNotFoundError(component_id)
        owner = self._find_build_for_component(component_id)
        if owner is not None:
            raise ComponentInUseError(component_id, owner.id)
        candidate_components = [deepcopy(c) for c in self._components]
        del candidate_components[index]
        candidate_builds = [deepcopy(b) for b in self._builds]
        candidate_profiles = [p.copy() for p in self._technical_profiles if p.component_id != component_id]
        self._commit(candidate_components, candidate_builds, candidate_profiles)

    @staticmethod
    def _display_name(component: Component) -> str:
        manufacturer = (getattr(component, "manufacturer", "") or "").strip()
        model = (getattr(component, "model", "") or "").strip()
        return " ".join(p for p in (manufacturer, model) if p) or getattr(component, "id", "?")

    def _classify_add_items(self, items: list[dict]) -> tuple[list[Component], list[BatchDuplicate], list[BatchRejection]]:
        """Validate/classify a batch: shared by preview and commit. No I/O, no mutation."""
        new_components: list[Component] = []
        duplicates: list[BatchDuplicate] = []
        rejected: list[BatchRejection] = []
        seen_keys: dict[tuple, int] = {}
        for index, raw in enumerate(items):
            if not isinstance(raw, dict):
                rejected.append(BatchRejection(index, "", "item must be a mapping of component fields"))
                continue
            try:
                candidate = Component(
                    category=raw.get("category", ""),
                    manufacturer=raw.get("manufacturer", ""),
                    model=raw.get("model", ""),
                    specifications=raw.get("specifications", ""),
                    notes=raw.get("notes", ""),
                    status=raw.get("status", "unspecified") or "unspecified",
                    location=raw.get("location", "") or "",
                    purchase_date=raw.get("purchase_date", "") or "",
                    warranty_end_date=raw.get("warranty_end_date", "") or "",
                    purchase_price=raw.get("purchase_price", "") or "",
                    purchase_currency=raw.get("purchase_currency", "") or "",
                )
            except (ComponentValidationError, ValueError, TypeError, AttributeError) as exc:
                name = " ".join(str(raw.get(k, "") or "").strip() for k in ("manufacturer", "model")).strip()
                rejected.append(BatchRejection(index, name, str(exc)))
                continue
            key = _catalog_duplicate_key(candidate)
            if key in seen_keys:
                first = seen_keys[key]
                duplicates.append(BatchDuplicate(index, self._display_name(candidate),
                                                 self._display_name(new_components[first])))
                continue
            match_name = None
            for existing in self._components:
                if _catalog_duplicate_key(existing) == key:
                    match_name = self._display_name(existing)
                    break
            if match_name is not None:
                duplicates.append(BatchDuplicate(index, self._display_name(candidate), match_name))
                continue
            seen_keys[key] = len(new_components)
            new_components.append(candidate)
        return new_components, duplicates, rejected

    def preview_add_components(self, items: list[dict]) -> BatchAddResult:
        """Read-only classification: exactly the same validation/duplicate rules
        as add_components, without writing or mutating state."""
        items = list(items or [])
        if not items:
            return BatchAddResult(created=[], duplicates=[])
        new_components, duplicates, rejected = self._classify_add_items(items)
        if rejected:
            raise BatchValidationError(rejected)
        return BatchAddResult(created=[deepcopy(c) for c in new_components], duplicates=duplicates)

    def add_components(self, items: list[dict]) -> BatchAddResult:
        """Add many components atomically with a single commit.

        Every item is validated first; duplicates (vs inventory or within the
        batch, by the same normalized (category, manufacturer, model) identity
        used for catalog entries) are skipped and reported; any invalid item
        aborts the whole batch via BatchValidationError before any write.
        """
        items = list(items or [])
        if not items:
            return BatchAddResult(created=[], duplicates=[])
        new_components, duplicates, rejected = self._classify_add_items(items)
        if rejected:
            raise BatchValidationError(rejected)
        if not new_components:
            return BatchAddResult(created=[], duplicates=duplicates)
        candidate_components = [deepcopy(c) for c in self._components] + [deepcopy(c) for c in new_components]
        candidate_builds = [deepcopy(b) for b in self._builds]
        self._commit(candidate_components, candidate_builds)
        return BatchAddResult(created=[deepcopy(c) for c in new_components], duplicates=duplicates)

    def delete_components(self, component_ids: list[str]) -> BatchDeleteResult:
        """Delete many components atomically with a single commit.

        Assigned components are kept and reported with their build; unknown
        ids (including repeats) are reported as not found. No commit happens
        when nothing is deletable.
        """
        seen: set[str] = set()
        targets: list[str] = []
        not_found: list[str] = []
        for cid in list(component_ids or []):
            cid = str(cid)
            if cid in seen:
                not_found.append(cid)
                continue
            seen.add(cid)
            if self._find_component_index(cid) is None:
                not_found.append(cid)
            else:
                targets.append(cid)
        skipped: list[BatchSkipped] = []
        deletable: list[str] = []
        for cid in targets:
            owner = self._find_build_for_component(cid)
            if owner is not None:
                comp = self._components[self._find_component_index(cid)]  # type: ignore[index]
                skipped.append(BatchSkipped(cid, self._display_name(comp), getattr(owner, "name", owner.id)))
            else:
                deletable.append(cid)
        if not deletable:
            return BatchDeleteResult(deleted=[], skipped_in_use=skipped, not_found=not_found)
        deletable_set = set(deletable)
        candidate_components = [deepcopy(c) for c in self._components if c.id not in deletable_set]
        deleted = [deepcopy(c) for c in self._components if c.id in deletable_set]
        candidate_builds = [deepcopy(b) for b in self._builds]
        candidate_profiles = [p.copy() for p in self._technical_profiles if p.component_id not in deletable_set]
        self._commit(candidate_components, candidate_builds, candidate_profiles)
        return BatchDeleteResult(deleted=deleted, skipped_in_use=skipped, not_found=not_found)

    # --- builds ---
    def get_builds(self) -> list[Build]:
        return [deepcopy(b) for b in self._builds]

    def get_build(self, build_id: str) -> Build | None:
        for build in self._builds:
            if build.id == build_id:
                return deepcopy(build)
        return None

    def add_build(self, name: str, notes: str | None = "", kind: str = "current", component_ids: list[str] | None = None) -> Build:
        new_build = Build(name=name, notes=notes, kind=kind, component_ids=component_ids or [])
        self._check_build_name_unique(new_build.name)
        for cid in new_build.component_ids:
            if self._find_component_index(cid) is None:
                raise ComponentNotFoundError(cid)
            owner = self._find_build_for_component(cid)
            if owner is not None:
                raise ComponentAlreadyAssignedError(cid, owner.id)
        candidate_components = [deepcopy(c) for c in self._components]
        candidate_builds = [deepcopy(b) for b in self._builds] + [deepcopy(new_build)]
        self._commit(candidate_components, candidate_builds)
        return deepcopy(new_build)

    def update_build(
        self, build_id: str, *, name: object = _PRESERVE, notes: object = _PRESERVE,
        kind: object = _PRESERVE, component_ids: object = _PRESERVE,
    ) -> Build:
        index = self._find_build_index(build_id)
        if index is None:
            raise BuildNotFoundError(build_id)
        existing = self._builds[index]
        updated = Build(
            id=build_id,
            name=existing.name if name is _PRESERVE else name,  # type: ignore[arg-type]
            notes=existing.notes if notes is _PRESERVE else notes,  # type: ignore[arg-type]
            kind=existing.kind if kind is _PRESERVE else kind,  # type: ignore[arg-type]
            component_ids=list(existing.component_ids) if component_ids is _PRESERVE else component_ids,  # type: ignore[arg-type]
        )
        self._check_build_name_unique(updated.name, exclude_build_id=build_id)
        for cid in updated.component_ids:
            if self._find_component_index(cid) is None:
                raise ComponentNotFoundError(cid)
            owner = self._find_build_for_component(cid)
            if owner is not None and owner.id != build_id:
                raise ComponentAlreadyAssignedError(cid, owner.id)
        candidate_components = [deepcopy(c) for c in self._components]
        candidate_builds = [deepcopy(b) for b in self._builds]
        candidate_builds[index] = deepcopy(updated)
        self._commit(candidate_components, candidate_builds)
        return deepcopy(updated)

    def delete_build(self, build_id: str) -> None:
        index = self._find_build_index(build_id)
        if index is None:
            raise BuildNotFoundError(build_id)
        candidate_components = [deepcopy(c) for c in self._components]
        candidate_builds = [deepcopy(b) for b in self._builds]
        del candidate_builds[index]
        self._commit(candidate_components, candidate_builds)

    def add_component_to_build(self, build_id: str, component_id: str) -> Build:
        build = self.get_build(build_id)
        if build is None:
            raise BuildNotFoundError(build_id)
        if self._find_component_index(component_id) is None:
            raise ComponentNotFoundError(component_id)
        owner = self._find_build_for_component(component_id)
        if owner is not None:
            raise ComponentAlreadyAssignedError(component_id, owner.id)
        ids = list(build.component_ids)
        if component_id in ids:
            raise ComponentAlreadyAssignedError(component_id, build_id)
        ids.append(component_id)
        return self.update_build(build_id, component_ids=ids)

    def remove_component_from_build(self, build_id: str, component_id: str) -> Build:
        build = self.get_build(build_id)
        if build is None:
            raise BuildNotFoundError(build_id)
        ids = list(build.component_ids)
        if component_id not in ids:
            raise ComponentNotFoundError(component_id)
        ids.remove(component_id)
        return self.update_build(build_id, component_ids=ids)

    def get_available_components(self) -> list[Component]:
        assigned = {cid for b in self._builds for cid in b.component_ids}
        return [deepcopy(c) for c in self._components if c.id not in assigned]

    # --- technical profiles ---
    def _find_technical_profile(self, component_id: str) -> TechnicalProfile | None:
        for profile in self._technical_profiles:
            if profile.component_id == component_id:
                return profile
        return None

    def get_technical_profiles(self) -> list[TechnicalProfile]:
        return [p.copy() for p in self._technical_profiles]

    def get_technical_profile(self, component_id: str) -> TechnicalProfile | None:
        profile = self._find_technical_profile(component_id)
        return profile.copy() if profile is not None else None

    def set_technical_profile(self, profile: TechnicalProfile) -> TechnicalProfile:
        if not isinstance(profile, TechnicalProfile):
            raise StorageError("profile must be a TechnicalProfile instance.")
        candidate = profile.copy()
        component = self.get_component(candidate.component_id)
        if component is None:
            raise ComponentNotFoundError(candidate.component_id)
        checked = _validate_technical_profile_references([component], [candidate])[0]
        # keep other profiles; ensure owner exists overall
        candidate_profiles = [p.copy() for p in self._technical_profiles if p.component_id != checked.component_id] + [checked.copy()]
        # full validation against current complete component set happens in _commit
        self._commit([deepcopy(c) for c in self._components], [deepcopy(b) for b in self._builds], candidate_profiles)
        saved = self.get_technical_profile(checked.component_id)
        assert saved is not None
        return saved

    def delete_technical_profile(self, component_id: str) -> None:
        if self._find_technical_profile(component_id) is None:
            raise ComponentNotFoundError(component_id)
        candidate_profiles = [p.copy() for p in self._technical_profiles if p.component_id != component_id]
        self._commit([deepcopy(c) for c in self._components], [deepcopy(b) for b in self._builds], candidate_profiles)

    def get_project_state(self) -> ProjectState:
        from pc_parts_organizer.storage import WRITE_INVENTORY_SCHEMA_VERSION

        return ProjectState(
            components=[deepcopy(c) for c in self._components],
            builds=[deepcopy(b) for b in self._builds],
            technical_profiles=[p.copy() for p in self._technical_profiles],
            schema_version=WRITE_INVENTORY_SCHEMA_VERSION,
        )

    # --- compatibility (T17.3, read-only query) ---
    def analyze_build_compatibility(self, build_id: str):
        """Analyze a build's compatibility deterministically. No persistence/mutation."""
        build = self.get_build(build_id)
        if build is None:
            raise BuildNotFoundError(build_id)
        # coherent snapshot from same in-memory state
        components = [deepcopy(c) for c in self._components]
        profiles = [p.copy() for p in self._technical_profiles]
        from pc_parts_organizer.compatibility import analyze_build_compatibility as _analyze

        return _analyze(build, components, profiles)

    # --- restore (complete state) ---
    def restore_inventory(
        self,
        components: list[Component] | InventoryFileInfo,
        builds: list[Build] | None = None,
        technical_profiles: list[TechnicalProfile] | None = None,
        *,
        pre_restore_backup_dir: str | Path | None = None,
    ) -> InventoryRestoreResult:
        """Replace the entire project state after creating and verifying a complete pre-restore backup.

        Accepts v1-v4-equivalent state (v1-v3 => missing collections empty in memory).
        v1-v3 restores set technical_profiles=[] (must not keep prior profiles).
        """
        if isinstance(components, InventoryFileInfo):
            cand_components = _normalize_components(list(components.components))
            cand_builds = _normalize_builds(list(components.builds or []))
            cand_profiles = _normalize_technical_profiles(list(getattr(components, "technical_profiles", []) or []))
        else:
            cand_components = _normalize_components(components)
            cand_builds = _normalize_builds(builds)
            cand_profiles = _normalize_technical_profiles(technical_profiles)
        _validate_build_references(cand_components, cand_builds)
        cand_profiles = _validate_technical_profile_references(cand_components, cand_profiles)

        current_components = [deepcopy(c) for c in self._components]
        current_builds = [deepcopy(b) for b in self._builds]
        current_profiles = [p.copy() for p in self._technical_profiles]
        pre_restore = create_pre_restore_backup(
            current_components,
            builds=current_builds,
            technical_profiles=current_profiles,
            directory=pre_restore_backup_dir,
        )
        try:
            save_project_state([deepcopy(c) for c in cand_components], [deepcopy(b) for b in cand_builds], [p.copy() for p in cand_profiles])
        except StorageError as exc:
            raise StorageError(f"{exc} (pre-restore backup preserved at {pre_restore.path})") from exc
        self._components = [deepcopy(c) for c in cand_components]
        self._builds = [deepcopy(b) for b in cand_builds]
        self._technical_profiles = [p.copy() for p in cand_profiles]
        return InventoryRestoreResult(
            restored_count=len(self._components),
            restored_build_count=len(self._builds),
            restored_technical_profile_count=len(self._technical_profiles),
            pre_restore_backup=pre_restore,
        )


__all__ = [
    "InventoryService",
    "InventorySummary",
    "InventoryRestoreResult",
    "BatchAddResult",
    "BatchDeleteResult",
    "BatchDuplicate",
    "BatchRejection",
    "BatchSkipped",
    "BatchValidationError",
    "ComponentNotFoundError",
    "BuildNotFoundError",
    "BuildNameConflictError",
    "ComponentInUseError",
    "ComponentAlreadyAssignedError",
    "TechnicalProfileCategoryConflictError",
    "ComponentValidationError",
    "BuildValidationError",
    "TechnicalProfileValidationError",
    "StorageError",
]
