"""Phase 2, step 3: spreadsheets -> read-only DuckDB tables + a readable dump.

Why not Docling here: the eval set cites cell addresses ("Income Statement!C13"),
so citations for sheets need sheet + cell. A markdown table dump throws that away.

Two tables are built, because an accounting worksheet is not a clean rectangle:

  cells    one row per populated cell: sheet, cell_ref, value, formula.
           Exact-value lookups and citations ("Income Statement!C13 = 14000").

  labeled  one row per populated cell, plus the row's label and the column's
           header, found by walking left and up. Lets text-to-SQL ask
           "net profit" instead of "C13". HEURISTIC - merged cells and
           stacked headers can mislabel; `cells` is the ground truth.

           The label is the NEAREST text cell to the left, not the leftmost
           in the row. "Adj Journal Entries" puts two journal blocks side by
           side (A-D original, F-I adjusting), so scanning from column A
           labels the adjusting figure in H10 with the original entry's
           "Dr Equipment" from B10 instead of its own "Dr Depreciation
           Expense - Equipment" in G10.
"""
import json
import pathlib
import re
import sys

import duckdb
import openpyxl

ROOT = pathlib.Path(__file__).resolve().parent.parent
XLSX = ROOT / "eval set" / "3A-Adjust-Class-Worksheet (Answer Key) (1).xlsx"
OUT = ROOT / "parsed"
DB = OUT / "sheets.duckdb"


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def main():
    OUT.mkdir(exist_ok=True)
    (OUT / "sheets").mkdir(exist_ok=True)
    if DB.exists():
        DB.unlink()

    # data_only=True gives the values Excel cached on its last save;
    # data_only=False gives the formulas. We want both: the handoff warns the
    # values live in formulas.
    wb_val = openpyxl.load_workbook(XLSX, data_only=True)
    wb_fml = openpyxl.load_workbook(XLSX, data_only=False)

    cells, labeled = [], []
    report = {"file": XLSX.name, "sheets": {}, "cached_values_missing": []}

    for name in wb_val.sheetnames:
        sv, sf = wb_val[name], wb_fml[name]
        n_cells = n_num = n_formula = n_cached_none = 0

        # Row labels: nearest text cell to the LEFT in the same row.
        # Column headers: nearest text cell above, within 12 rows.
        def row_label(r, c):
            for cc in range(c - 1, 0, -1):
                v = sv.cell(row=r, column=cc).value
                if isinstance(v, str) and v.strip():
                    return v.strip()
            return None

        def col_header(r, c):
            for rr in range(r - 1, max(0, r - 12), -1):
                v = sv.cell(row=rr, column=c).value
                if isinstance(v, str) and v.strip():
                    return v.strip()
            return None

        for row in sv.iter_rows():
            for cell in row:
                if cell.value is None:
                    continue
                ref = f"{cell.coordinate}"
                fml = sf[ref].value
                formula = fml if isinstance(fml, str) and fml.startswith("=") else None
                n_cells += 1
                if is_num(cell.value):
                    n_num += 1
                if formula:
                    n_formula += 1
                    if cell.value is None:
                        n_cached_none += 1
                cells.append({
                    "sheet": name,
                    "cell_ref": f"{name}!{ref}",
                    "row": cell.row,
                    "col": cell.column,
                    "value_text": str(cell.value),
                    "value_num": float(cell.value) if is_num(cell.value) else None,
                    "formula": formula,
                })
                labeled.append({
                    "sheet": name,
                    "cell_ref": f"{name}!{ref}",
                    "row_label": row_label(cell.row, cell.column),
                    "col_header": col_header(cell.row, cell.column),
                    "value_text": str(cell.value),
                    "value_num": float(cell.value) if is_num(cell.value) else None,
                })

        report["sheets"][name] = {
            "populated_cells": n_cells, "numeric": n_num, "formulas": n_formula,
            "dims": f"{sv.max_row}x{sv.max_column}",
        }
        if n_formula and n_cached_none:
            report["cached_values_missing"].append(name)

        # Readable dump, so the owner can eyeball it against Excel.
        lines = [f"# {name}", "", f"{n_cells} populated cells, {n_formula} formulas", ""]
        for row in sv.iter_rows():
            vals = [(c.coordinate, c.value) for c in row if c.value is not None]
            if vals:
                lines.append(" | ".join(f"{ref}={v!r}" for ref, v in vals))
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", name)
        (OUT / "sheets" / f"{safe}.txt").write_text("\n".join(lines), encoding="utf-8")

    con = duckdb.connect(str(DB))
    con.execute("CREATE TABLE cells (sheet VARCHAR, cell_ref VARCHAR, row INTEGER, col INTEGER, value_text VARCHAR, value_num DOUBLE, formula VARCHAR)")
    con.execute("CREATE TABLE labeled (sheet VARCHAR, cell_ref VARCHAR, row_label VARCHAR, col_header VARCHAR, value_text VARCHAR, value_num DOUBLE)")
    con.executemany("INSERT INTO cells VALUES (?,?,?,?,?,?,?)",
                    [[c[k] for k in ("sheet", "cell_ref", "row", "col", "value_text", "value_num", "formula")] for c in cells])
    con.executemany("INSERT INTO labeled VALUES (?,?,?,?,?,?)",
                    [[c[k] for k in ("sheet", "cell_ref", "row_label", "col_header", "value_text", "value_num")] for c in labeled])
    con.close()

    (OUT / "sheets_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"\n{len(cells)} cells -> {DB}")
    if report["cached_values_missing"]:
        print("WARNING: formulas with no cached value in:", report["cached_values_missing"],
              "\n  Excel never saved results for these; they would need recalculating.", file=sys.stderr)


if __name__ == "__main__":
    main()
