# Quick start — PC Parts Organizer

Practical walkthrough from first launch to exported sheet, using only actions that really exist in the UI. The application supports English and Spanish (header selector); this guide uses the English labels.

## 0. Launch

```bat
python -m pc_parts_organizer
```

The first launch creates the data directory and (empty) state files.

## 1. Browse the catalog

1. **Catalog** tab.
2. Search by manufacturer or model (e.g. “AMD”).
3. Filter by category and adjust `Show` if there are many references.
4. Read a reference's specifications and notes in the details panel.

## 2. Add several components to the inventory

1. **Inventory** tab → **Add from catalog**.
2. Select several rows (Shift for a range, Ctrl to add).
3. Change pages if needed: the selection is preserved.
4. Check **Selected: N** and press **Add selected**.
5. Review the report with created and skipped items (duplicates with their matching name).

> Components stay in the inventory **unassigned** to any build.

## 3. Create a build

1. **Builds** tab → **Add build**.
2. Set a name (unique), type (Current/Planned) and notes.
3. Select available components and confirm with **Save**.

## 4. Complete a technical profile

1. Inventory → select a component → **View details** → **Add technical data**.
2. Add the applicable attributes (e.g. RAM: `memory_generation`, `module_form_factor`, `total_capacity_gb`, `module_count`).
3. Record provenance, confidence and, if you have backing, `evidence_ref` + date to mark **Verified**.

## 5. Review data quality

1. Inventory → **Review data**.
2. Filter by category/state and use the **review queue** to see pending attributes and the rules consuming them.
3. Fix values or provide evidence; blocked findings update when you re-analyze.

## 6. Analyze compatibility

1. Builds → **View details** of the build → **Analyze compatibility**.
2. Interpret the global result and the findings by severity.
3. Review **Unevaluated relationships** and **Limitations** before concluding.

## 7. Check the technical audit

In the same build details, **Technical audit** section: demonstrated findings, pending verification, insufficient data and relevant pending attributes with their component and relation (direct/shared).

## 8. Compare two builds

1. Create a second build (e.g. changing RAM or board).
2. Builds → **Compare builds** → select A and B.
3. Review common, added, removed, replaced and new/common/resolved findings.

## 9. Export a sheet

1. In the build details, **Export sheet**.
2. Choose **Markdown (`.md`)** or **Text (`.txt`)**.
3. Choose the destination in the save dialog (no overwrite without confirmation).
4. Review the contents: composition, findings, evidence, limitations and audit.

## Walkthrough summary

```
Catalog → Add several → Build → Technical profile → Quality
        → Analyze → Audit → Compare → Export sheet
```

## Reminders

- `compatible` on a relationship does not certify total compatibility.
- Incompatibilities require verified attributes.
- Export a backup before restores or bulk edits.
