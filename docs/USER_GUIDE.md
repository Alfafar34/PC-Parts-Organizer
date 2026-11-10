# User guide — PC Parts Organizer

Complete manual for using the application. Action and tab names are given in English (the language shown when English is selected); the main Spanish equivalents are noted in the language section below.

> **Epistemological warning.** Compatibility analysis does not certify a build's total compatibility. It presents conclusions scoped to specific relationships and declares what it does **not** evaluate. A `compatible` result on one relationship does not guarantee that other dimensions (electrical, thermal, geometric) have been checked. See the compatibility section of `ARCHITECTURE.md`.

---

## Language: English and Spanish

The application supports **English and Spanish**. Switch languages from the header selector; the preference is saved in `settings.json` and every label, message and dialog updates immediately. Key Spanish equivalents used in this guide:

| English (this guide) | Spanish |
|---|---|
| Home / Inventory / Builds / Catalog | Inicio / Inventario / Equipos / Catálogo |
| Add component | Añadir componente |
| Add from catalog / Add selected | Añadir desde catálogo / Añadir seleccionados |
| Import CSV / Download CSV template | Importar CSV / Descargar plantilla CSV |
| Delete selected | Eliminar seleccionados |
| Review data | Revisar datos |
| Add build | Añadir equipo |
| Analyze compatibility | Analizar compatibilidad |
| Compare builds | Comparar equipos |
| Export sheet | Exportar ficha |
| Export backup / Restore backup | Exportar copia / Restaurar copia |

## A. First use

### Starting the application

```bat
python -m pc_parts_organizer
```

The main window opens with the dark theme and the tab bar: **Home**, **Inventory**, **Builds**, **Catalog**.

### Tabs and navigation

| Tab | Contents |
|---|---|
| Home | Inventory overview: total, distribution by category, registered prices |
| Inventory | Component table with search, filters, actions and details |
| Builds | Build list, creation, details, comparer |
| Catalog | Commercial references, import/export, selector |

The language selector is in the header (EN/ES) and is saved in `settings.json`.

### Where data is stored

Outside the repository, in the system local data directory (Windows):

```
%LOCALAPPDATA%\PCPartsOrganizer\
  components.json     Inventory + builds + technical profiles
  settings.json       Language
  catalog.sqlite3     Catalog of references
  backups\            Pre-restore safety copies
```

Do not edit these files by hand except through the procedures documented in `MAINTENANCE.md`.

### Catalog vs. inventory: the key difference

- **Catalog**: a reusable reference library (manufacturer, model, specs, notes, commercial provenance). It is not part of your collection.
- **Inventory**: your real components, with status, location, prices, technical profiles and verifications.

Adding from the catalog **copies** only the fields with a real correspondence (category, manufacturer, model, specifications, notes). Commercial provenance (`source`, URL, license, attribution, commercial verification date) **never** becomes technical verification.

---

## B. Catalog and inventory

### Searching catalog components

1. Go to **Catalog**.
2. Type a manufacturer or model and press **Search**.
3. Filter by category and adjust the page size (`Show: 100 / All`).
4. Use **Previous/Next** for pagination.

### Adding components from the catalog (multiple selection)

1. In **Inventory**, press **Add from catalog**.
2. Select several rows (click, Shift for a range, Ctrl to add).
3. Change pages if needed: **the selection is preserved** across pages.
4. The **Selected: N** indicator shows the accumulated total.
5. Press **Add selected** to confirm, or **Cancel**.

**Duplicates and omissions.** The system compares by normalized identity (category + manufacturer + model, ignoring case and redundant spaces). Duplicates are skipped and reported by name with the matching component. No duplicate records are created.

**Report.** After confirming, a dialog opens with the totals and the complete scrollable list: created, skipped duplicates (with the matching name) and rejections (with reason).

**Atomic rejection.** If any entry is invalid, **nothing is added** and the reason is shown per entry. There are no partial additions.

> **Note.** Adding creates components in the inventory and leaves them **unassigned** to any build. Assignment to builds is done individually (section D).

### Importing components from a CSV

1. In **Inventory**, press **Import CSV** (or first download the **CSV template** with **Download CSV template**).
2. Choose the `.csv` file. The application detects the encoding (UTF-8 with/without BOM, UTF-16, Windows-1252) and the delimiter (comma, semicolon, tab).
3. Review the **preview**: totals by state and the full table with source line, state, reason and duplicate match.
4. If detection is unreliable, change the encoding or delimiter and press **Re-analyze**.
5. Press **Import valid rows** or **Cancel**.

**Canonical format.** Headers `category,manufacturer,model,specs,notes` (free order; aliases in Spanish and English such as `categoría`, `fabricante`, `modelo`, `especificaciones`, `notas` are accepted). Only category, manufacturer and model are required. Unknown columns (e.g. `verified_at`, `source`) are listed as non-importable and ignored: they never become verifications.

**Duplicates.** Detected against the inventory and within the file by normalized identity. Duplicates are skipped and reported; rejected rows are reported with reason and line number. The import uses a single transactional operation: either all valid rows are created or nothing is written.

### Creating and editing components

- **Add component** (Inventory): opens the form with category, manufacturer, model, specifications, notes, status, location, dates, price and currency. Price and currency must be set together or both left empty.
- **Edit** / **View details**: available with a single selected row. Details show the component and its technical data.
- **Search catalog** inside the form: fills category, manufacturer, model and specifications from the selected reference. It does not modify status or location.

### Deleting several components

1. In **Inventory**, select several rows.
2. Press **Delete selected**.
3. The confirmation dialog shows: selected, deletable and protected-as-assigned, with the **complete list** of protected items (name + build).
4. Confirm with **Delete** or cancel.

**Assigned protection.** A component assigned to a build **cannot be deleted**; it is kept intact and reported with the name of the build protecting it. To delete it, first remove it from the build. The service revalidates all conditions at execution time: the visual pre-check does not replace transactional validation.

**Result.** Scrollable dialog with deleted, skipped-as-assigned (name and build) and not found. No mass deletion via accidental shortcuts: only the explicit action.

---

## C. Technical profiles

Technical profiles are the basis of compatibility. They are created from a component's details (**Add technical data**) and only for categories with an attribute registry (CPU, GPU, Motherboard, RAM, Storage, PSU, Case, Cooling, Other).

### Creating and completing

1. Open the component details.
2. **Add technical data**.
3. Complete the applicable attributes (e.g. `memory_generation`, `module_form_factor`, `total_capacity_gb`, `module_count` for RAM).
4. For each attribute record: **value**, **unit** (if applicable), **provenance**, **confidence**, **verification status**, **evidence reference** and **verification date**.

### Verification states

| State | Meaning |
|---|---|
| Unverified | Declared value without backing |
| Verified with reference | Requires evidence and verification date |
| Needs review | Modified or pending-confirmation data |

**Warning.** Marking as verified requires an evidence reference and date. Do not declare verification without backing: the application does not authenticate documentation for you.

### Confidence and provenance

- **Provenance** (`source`): user input, catalog import, official documentation, inferred/normalized, unknown.
- **Confidence**: high, medium, low.

### Complete and partial collections

Attributes such as M.2 slots, SATA ports or the PSU cable inventory support declaring **completeness** (complete/partial/unknown) and a **scope** describing what it covers. Mark “complete” only after checking the full source; the application does not verify exhaustiveness by itself.

### Revalidating modified values

If a verified attribute changes value, the system requires review and keeps the previous evidence. Explicitly confirm that the evidence still supports the current value (or provide new evidence). Without this step, the data is not verified.

---

## D. Builds

### Creating a configuration

1. Go to **Builds** → **Add build**.
2. Enter a name (required and unique, case-insensitive), type (Current/Planned), notes and components.
3. Assignment is **individual and unique**: one component cannot be in two builds at once.

### Viewing details and analyzing

- **View details** shows composition grouped by category, compatibility analysis and technical audit.
- **Analyze compatibility** runs the engine on the current state. Results are marked stale if the build, its components, profiles or associations change; analyze again.

### Results and severities

| Result | Meaning |
|---|---|
| Compatible | The evaluated relationships passed with sufficient verified data |
| Incompatible | Confirmed technical contradiction (only with verified attributes) |
| Requires verification | Insufficiently verified conditions; not an incompatibility |
| Insufficient data | Missing attributes needed to conclude |

Severities: **Critical** (confirmed incompatibility), **Warning**, **Information**.

### Limitations and pending data

Details show **Unevaluated relationships** (categories without rules), **Analysis limitations**, findings with **Missing information** and **Recommended action**. Involved participants are listed with category and name; from the findings combo you can open the involved component.

---

## E. Data quality

Access from **Inventory** → **Review data**.

### Summary and filters

- **Summary**: counts by state and totals.
- **Filters** by category, attribute state and search text, with pagination.
- **Component table** with its epistemic state per attribute.
- **Review queue**: pending attributes consumed by engine rules (used by), ordered by priority.

### Fixing data

Select a pending component and use **Edit technical data** to fix values or complete evidence. On save, the quality center is recomputed; findings blocked on pending data may resolve or change.

---

## F. Technical audit

Available in a build's details (**Technical audit** section), computed from the fresh analysis and profiles.

### What it shows

- **Summary**: incompatible, pending verification, insufficient data, not evaluated, relevant pending attributes and inconsistent metadata.
- **Demonstrated incompatibilities**: rule, result, severity and components.
- **Pending verification** and **insufficient data**: finding + linked attributes, marked as **Direct relation** (the missing information names the attribute) or **Shared context** (rule consuming the attribute).
- **Unevaluated relationships** and **Limitations**.
- **Relevant pending attributes** and **Other pending attributes** (not currently blocking).

### Interpretation

- The audit **states facts and pending information**; it is not a score and does not certify compatibility.
- A **demonstrated incompatibility** is a contradiction with verified attributes.
- An **uncertainty** (`requires_verification`) indicates missing verification, not an incompatibility.
- Component links use readable labels (category + manufacturer/model), never internal identifiers.

---

## G. Build comparer

Access from **Builds** → **Compare builds** (requires at least two).

1. Select A and B.
2. The summary shows: common, **added**, **removed** and **replaced**, plus **new**, **common** and **resolved** findings.

### Correspondences

Correspondence is established by demonstrated identity (equivalent component between A and B), not by mere category coincidence. Components without demonstrated correspondence are shown as independent.

### Why a disappearance is not an improvement

A finding disappearing in B does not imply overall compatibility improved: the involved component may have been removed (relationship no longer applicable), or the change may not be covered by implemented rules. **Resolved** findings are explained with the specific change (removed component, corrected attribute, etc.).

---

## H. Configuration sheets

From a build's details, press **Export sheet**. **Markdown (`.md`)** and **Text (`.txt`)** are offered.

### Contents

- Build name, type and notes.
- Composition grouped by category with manufacturer/model and available specs/notes.
- Global result and explanation, rules evaluated.
- Findings with rule, result, severity, participants, compared attributes, explanation, missing information and recommended action.
- Evidence and provenance (recorded metadata).
- **Unevaluated relationships** and **Limitations**.
- **Technical audit** with pending items and inconsistencies.

### Guarantees and warnings

- The sheet is generated from a **fresh analysis** of the current state, not from a saved report.
- It contains **no** UUID as primary information, internal structures or invented specifications.
- Evidence is shown as **declared metadata**; the application does not authenticate documentation.
- No silent overwrite: the system save dialog asks for confirmation.
- Cannot be exported over the active inventory file.

---

## I. Import, export and recovery

### Backups (supported)

- **Export backup** (Inventory): exports the complete state (components + builds + profiles) to JSON at the chosen destination.
- **Restore backup**: select a JSON, a **preview** is shown (counts, schema, categories/states) and, after confirming, a **safety copy** of the current state is created before replacing it.

### When to back up

- Before a restore (automatic: the safety copy).
- Before bulk edits or manual migrations.
- Periodically, to keep a recovery point.

### Which files to protect

- `components.json` (inventory + builds + profiles).
- `settings.json` (language preference).
- `catalog.sqlite3` (catalog).
- `backups\` (safety copies).

### Operations that must NOT be done manually

- Editing `components.json` by hand without following `MAINTENANCE.md`.
- Editing `catalog.sqlite3` with external tools.
- Copying/merging data files between machines without verifying schemas.
- Forcing the application closed during a write (use normal close).

### Catalog import

From **Catalog** → **Import catalog**, CSV and JSON with the documented schema are accepted; duplicates are skipped and the new/skipped count is reported.

### CSV import into inventory

From **Inventory** → **Import CSV**. Format `category,manufacturer,model,specs,notes`
(free order, ES/EN aliases); UTF-8 (±BOM), UTF-16 and Windows-1252 encodings; comma, semicolon and tab delimiters. The preview shows totals and the full per-row table (line, state, reason, duplicate). `preview_add_components` reclassifies without writing; the final import uses `add_components` (a single `_commit`). Non-admitted columns are ignored and listed; they never contribute verification. Downloadable template from **Download CSV template** (UTF-8 with BOM).

---

## Quick examples

**Add 20 references and see the report.** Catalog → select 20 across pages → Inventory → Add from catalog → confirm: the dialog shows created and skipped with their names.

**Detect an incompatibility.** Builds → create a build with board and RAM → complete profiles with verified `memory_generation` → Analyze: a contradiction with verified attributes shows as **Incompatible**; if the data is not verified, it will be **Requires verification**.

**Fix and revalidate.** Quality center → review queue → edit pending attribute → provide evidence → revalidate. Analyze again to update findings.

**Compare.** Builds → Compare → A and B: review replacements with demonstrated correspondence and resolved findings with their explanation.
