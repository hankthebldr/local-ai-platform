---
name: Sheet Index
summary: Tabular index output — a single markdown table with a stable header row and one record per line.
target: sheet
version: 1
---
Produce a tabular index.

- Emit ONE markdown table. The first row is the header; the second is the `---` separator; every subsequent row is exactly one record.
- Keep column order stable across the whole output — never reorder or drop columns mid-table.
- One record per row; do not wrap a record across multiple lines. Escape pipes inside cells as `\|`.
- Prefer short, machine-parseable cell values (ids, statuses, counts) over prose; put long explanation in a trailing `notes` column.
- Do not emit surrounding prose before or after the table — the table IS the deliverable.
