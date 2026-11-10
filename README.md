# PC Parts Organizer

Desktop application (Tkinter) to organize your PC component inventory, browse a catalog of commercial references, record technical data with evidence, and evaluate the compatibility of configured builds.

> **Important.** The compatibility engine does **not** certify a computer's total compatibility. It presents conclusions scoped to specific relationships and requires verified attributes; everything not evaluated is explicitly declared (`not_evaluated`, limitations). Read `docs/ARCHITECTURE.md` before interpreting results.

## Main features

- **Component inventory** with search, category filters, sorting and details.
- **Catalog of commercial references** in SQLite, with search, pagination, CSV/JSON import/export and bulk add to inventory.
- **Bulk add from catalog**: cross-page selection, duplicates detected and skipped with a report, and atomic rejection on invalid entries.
- **CSV import into inventory**: preview with per-row validation, duplicate detection, delimiter/encoding switching and a single transactional commit (with downloadable template).
- **Technical profiles** per component with typed attributes, provenance, confidence, evidence and verification states.
- **Builds** with single assignment of components, details and deletion.
- **Deterministic compatibility engine** (no I/O): findings with rule, severity, participants, evidence and explanation; global result and unevaluated relationships.
- **Per-build technical audit**: findings linked to specific attributes, relevant/future pending items, inconsistencies and counts.
- **Quality center**: global summary, review queue and pending-data fixes.
- **Build comparer**: added/removed/replaced components with demonstrated correspondences and new/common/resolved findings.
- **Configuration sheets** exportable to Markdown (`.md`) and plain text (`.txt`) from a fresh analysis.
- **Backup and restore** with SHA256 verification and a pre-restore safety copy.
- **Persistent ES/EN localization** with exact key parity.

## Technologies

- **Python 3.14+** (verified with CPython 3.14.5) and **Tkinter** (standard widget set, requires a display; on Windows it ships with Python).
- **SQLite 3** (standard `sqlite3` module) for the catalog only.
- **No external dependencies**: no `pip install` is required to run or validate.
  The application and its tests use only standard Python and Tkinter.
  Pillow is optional and is only used by certain visual-validation tools in
  `tools/` (screenshots); you do not need to install it to run the application.

## Language support

The application supports **English and Spanish**. Switch languages from the header selector; the preference is saved in `settings.json` and every label, message and dialog updates immediately (verified with exact ES/EN key parity). This documentation uses the English UI terms (e.g. **Inventory**, **Builds**, **Add from catalog**, **Analyze compatibility**).

## Requirements

1. Python 3.14 or newer with Tkinter available.
2. Write permission in `%LOCALAPPDATA%\PCPartsOrganizer` (Windows) / `~/.local/share/PCPartsOrganizer` (Linux/macOS via `XDG_DATA_HOME`/local system data folder).
3. No network, no external database, no compilation needed.

## Setup and execution

```bat
REM from the repository root
python -m pc_parts_organizer
```

No installation or build step. The first launch creates the data directory and state files if missing.

## Repository structure

```
pc_parts_organizer/        Application package
  app.py                   Entry point (run())
  __main__.py              python -m pc_parts_organizer
  models.py                Component, Build and model validation
  service.py               InventoryService (transactional authority)
  storage.py               JSON persistence, schemas, backups, import/export
  catalog_models.py        CatalogEntry and duplicate key
  catalog_storage.py       Catalog SQLite (read/write mode)
  catalog_service.py       Catalog service
  catalog_io.py            Catalog CSV/JSON import/export
  technical_profiles.py    Profiles, AttributeSpec, attribute registry, validation
  compatibility/           Pure compatibility engine + per-relationship rules
  data_quality.py          Data quality, attribute states, CONSUMERS, queue
  build_audit.py           Per-build technical audit
  build_compare.py         Build comparer
  build_sheet.py           Markdown/TXT sheets
  localization.py          Translator and language preference
  locales/es.json, en.json Complete localization
  ui/                      Tkinter views and forms
tests/                     unittest suite (fail-closed isolation in TEMP)
tools/                     Synthetic visual-validation preparers
docs/                      User guide, architecture, maintenance, quick start
```

## Data location

Data is stored **outside** the repository, in the system local data directory:

- Windows: `%LOCALAPPDATA%\PCPartsOrganizer\`
- Linux/macOS: `~/.local/share/PCPartsOrganizer/`

Files:

| File | Contents |
|---|---|
| `components.json` | Inventory + builds + technical profiles (JSON, `schema_version` 4 when writing; accepts 1–4 when reading) |
| `settings.json` | Language preference (`schema_version` 1) |
| `catalog.sqlite3` | Catalog of commercial references |
| `backups/` | Pre-restore safety copies |

The catalog and the inventory are **separate stores**: the catalog is a reusable reference library; the inventory is your personal collection. Adding from the catalog **copies** only fields with a real correspondence (category, manufacturer, model, specifications, notes) and never transfers commercial provenance as technical verification.

## Documentation

- `docs/USER_GUIDE.md` — complete step-by-step manual.
- `docs/QUICK_START.md` — practical walkthrough from first launch to exported sheet.
- `docs/ARCHITECTURE.md` — layers, contracts, compatibility engine and technical limits.
- `docs/MAINTENANCE.md` — backup, restore and diagnostics.

## Important limitations

- The engine evaluates specific relationships; it does not guarantee physical, electrical or overall functional compatibility.
- Incompatibilities are only declared with **verified attributes**; without verification, the result will be `requires_verification` or `insufficient_data`, never a confirmed incompatibility.
- `compatible` on a relationship does not imply that other unevaluated dimensions (e.g. PCIe lanes, PSU power, thermal capacity) have been checked.
- The application does not authenticate manufacturer documentation; evidence metadata is shown exactly as recorded.
- The catalog database is single-process SQLite; do not edit it manually with external tools.
- Real data must not be edited by hand; use the UI functions or the procedures documented in `docs/MAINTENANCE.md`.

## AI-assisted development

AI tools, including OpenCode and ChatGPT, were used throughout development
to assist with implementation, debugging, test development, and documentation.

The project requirements, scope, and development direction were defined by
the maintainer, who remains responsible for the resulting code and its maintenance.
