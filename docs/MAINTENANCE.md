# Maintenance, backup and recovery

Technical guide to PC Parts Organizer data, supported procedures and diagnostics. Complements `USER_GUIDE.md` and `ARCHITECTURE.md`.

> **Restriction.** **Supported** operations run from the UI. Manual interventions on files are last-resort technical procedures and must be done with the application closed and with a prior copy.

---

## 1. Data files and location

Windows: `%LOCALAPPDATA%\PCPartsOrganizer\` (Linux/macOS: `~/.local/share/PCPartsOrganizer/`).

| File | Format | Contents | Writer |
|---|---|---|---|
| `components.json` | JSON, `schema_version` 4 | Inventory + builds + technical profiles | `storage.save_project_state` (atomic) |
| `settings.json` | JSON, `schema_version` 1 | Language (`es`/`en`) | `save_language_preference` (atomic) |
| `catalog.sqlite3` | SQLite | Commercial references | `CatalogStorage` |
| `backups\pre-restore\inventory-pre-restore-<stamp>.json` | JSON | Pre-restore safety copy | `create_pre_restore_backup_from_state` |

## 2. JSON inventory vs. SQLite catalog

- **Inventory (`components.json`)**: your personal collection, with builds and profiles. Open format, validated on read/write, accepts schemas 1–4 and writes 4.
- **Catalog (`catalog.sqlite3`)**: reusable reference library. Internal schema `CATALOG_SCHEMA_VERSION = 1`. Created/updated when using the Catalog tab.

They are not interchangeable: the catalog does not feed inventory profiles or verifications, and the inventory is not automatically imported into the catalog.

## 3. Existing backup procedures

**Export backup** (Inventory → Export backup):
- Exports the complete state to JSON at the chosen destination.
- The file is verifiable with `read_inventory_file` (includes SHA256).

**Pre-restore safety copy** (automatic):
- Before replacing the state, the application creates `backups\pre-restore\inventory-pre-restore-<stamp>.json` and verifies it.
- Never overwrites: if the name exists, a numeric suffix is added.

There is no automatic scheduling of periodic copies nor an external backup tool. Manually copying the data files is the available technical procedure.

## 4. Supported recovery

1. **Restore backup** (Inventory → Restore backup).
2. Select a backup JSON.
3. A **preview** is shown (components, builds, profiles, schema, categories/states).
4. You confirm the replacement. The **safety copy** of the current state is created.
5. The file is revalidated (including SHA256) after the preview to detect changes.

Preview warnings: empty backup, old schemas without builds (v1/v2) or without profiles (v1/v2/v3). In those cases the restore replaces the project and may leave it without builds/profiles.

## 5. Available integrity checks

- **JSON**: structural and cross-reference validation on read; SHA256 on exported copies; `PRAGMA integrity_check` applies only to SQLite.
- **SQLite**: schema/column check on initialization (`CatalogStorage.initialize`). For a one-off external check, open in **read-only mode**:

```bat
python -c "import sqlite3; c=sqlite3.connect('file:%LOCALAPPDATA%/PCPartsOrganizer/catalog.sqlite3?mode=ro', uri=True); print(c.execute('PRAGMA integrity_check').fetchall()); c.close()"
```

- **Language**: `tests/test_localization.py` validates ES/EN parity.

## 6. Schema and profile versions

- Inventory: supported schemas **1–4**; writes **4**.
- Settings: `schema_version` **1**.
- Catalog: `CATALOG_SCHEMA_VERSION` **1**.
- Profiles: `PROFILE_VERSION = 2` (structural shape), `PROFILE_REGISTRY_VERSION = 7` (attribute/validation registry).
- Engine: `ENGINE_RULESET_VERSION = "t17.12-v1"`.

## 7. Old profile compatibility

- A profile is interpretable if its structural version is supported; `validate_profile_for_category` revalidates it against the current registry.
- If the registry changes version, a profile may require review; the application detects it on load/save.
- No attributes were migrated or deleted automatically; existing profiles are preserved.

## 8. What happens on application close

- State persists on every mutation; there is no deferred save on close.
- Closing via the X button or **Close** performs no additional copies.
- Do not leave the application open during manual file edits.

## 9. Common error diagnostics

| Symptom | Likely cause | Action |
|---|---|---|
| “Could not save” | Permissions or disk | Verify writes in `%LOCALAPPDATA%\PCPartsOrganizer` |
| Catalog unavailable | Corrupt database or unexpected schema | Do not edit it; reinstall/recover the catalog from a verified copy |
| Backup does not validate | Modified or truncated file | Export again; do not restore |
| Language reverts | Failure saving `settings.json` | Change again; verify permissions |
| Stale results | Components/profiles changed | Press **Analyze compatibility** again |

## 10. Files that must be protected

- `components.json`, `settings.json`, `catalog.sqlite3`, `backups\`.
- Copy these files (with the application closed) before manual interventions.

## 11. Manual operations to avoid

- Editing `components.json` by hand without validating the schema and cross-references.
- Editing `catalog.sqlite3` with external tools.
- Restoring copies from another machine without verifying schemas.
- Deleting `backups\` or overwriting safety copies.
- Forcing quit during a write.

---

## Interface vs. technical procedure

| Need | Supported path | Technical path (last resort) |
|---|---|---|
| Backup | Export backup | Copy files with the app closed |
| Restore | Restore backup + preview + safety copy | Manually restore verified `components.json` |
| Recover catalog | Reimport verified CSV/JSON | Restore `catalog.sqlite3` from copy |
| Verify integrity | Validation on restore | `PRAGMA integrity_check` in read-only mode |

Technical paths have no UI and no automatic validation guarantees; use them only if the UI path is not viable and always with a prior copy.
