"""Phase 8: the SQL route - numeric questions answered from the spreadsheets.

Spreadsheets are never chunked (an accounting worksheet cut into 800-token
pieces loses which number sits under which header). They live in read-only
DuckDB (parse_sheets.py): `cells` (ground truth, one row per populated cell)
and `labeled` (each cell with its row label and column header).

  1. Plan     Luna sees the two tables' columns and a catalog of the cells -
              every text cell with its text, every number cell with its row
              label and column header but NOT its value - and either says the
              spreadsheets cannot answer, or writes one SELECT returning the
              cells the answer needs (cell_ref in every row, no arithmetic in
              SQL: sums and differences happen in the answer's steps, where
              the checker can see them).
  2. Run      the SELECT on a read-only connection with external access off
              (no files, no URLs); anything but one SELECT is refused. An
              error or no rows gets one retry with the error.
  3. Answer   the returned cells become evidence ("Income Statement!C13 =
              14000 (row: Net Profit)") for the same Explained-answer prompt
              as every rung, so the checker and the grader treat it alike.

Fallback: when the plan says the spreadsheets cannot answer, the SQL fails
twice, or the answer comes back "not found", the caller uses hybrid search.
"""
import re

import duckdb

import library as L
from answering import ask_with_docs
from openai_client import ask_json

DB = L.OUT / "sheets.duckdb"
MAX_ROWS = 50
MAX_CATALOG = 800  # cells listed for the model; above this, labels only

PLAN_PROMPT = """\
A student's question may be answerable from their spreadsheet, stored in DuckDB:

  cells(sheet, cell_ref, row, col, value_text, value_num, formula)
  labeled(sheet, cell_ref, row_label, col_header, value_text, value_num)

cell_ref looks like 'Income Statement!C13'. labeled gives each cell the text
label to its left (row_label) and above it (col_header); value_num is set for
numbers. The spreadsheet is "{spreadsheet}". Its cells (number cells show
their labels, not their values):

{catalog}

QUESTION
{question}

If this spreadsheet cannot answer the question, reply
{{"answerable": false, "why": "<short>", "sql": null}}.
Otherwise write ONE DuckDB SELECT that returns the cells the answer needs -
every row must include cell_ref, row_label, col_header, value_text - and no
arithmetic (sums, differences) in SQL: return the cells, the answer adds them
up. Prefer selecting by cell_ref when the catalog shows the exact cell.
Reply {{"answerable": true, "why": "<short>", "sql": "<the SELECT>"}}.
{retry}
Reply with JSON only."""


def catalog(con):
    rows = con.execute("""
        SELECT l.cell_ref, l.row_label, l.col_header, l.value_text, l.value_num
        FROM labeled l JOIN cells c USING (sheet, cell_ref)
        ORDER BY l.sheet, c.row, c.col""").fetchall()
    lines = []
    for ref, rl, ch, text, num in rows:
        if num is None:
            lines.append(f"{ref}: {text!r}")
        else:
            lines.append(f"{ref}: <number> row={rl!r} col={ch!r}")
    if len(lines) > MAX_CATALOG:  # a big sheet: number cells' labels only
        lines = [ln for ln in lines if "<number>" in ln][:MAX_CATALOG]
    return "\n".join(lines)


def _valid(v):
    return isinstance(v.get("answerable"), bool) and (not v["answerable"] or isinstance(v.get("sql"), str))


def _is_one_select(sql):
    s = sql.strip().rstrip(";").strip()
    return bool(re.match(r"(?is)^(select|with)\b", s)) and ";" not in s


def plan_and_run(c, question, db=DB, spreadsheet=None):
    """Returns (rows or None, trace, usages). rows = list of dicts with cell_ref.
    `db`: the Library's DuckDB file (the website keeps one per Library)."""
    # Read-only stops writes, not reads: a SELECT can still call read_text('<any file>')
    # or fetch a URL. External access off keeps model-written SQL inside this database
    # (pentest.md: a SELECT passing the guard read a file from disk).
    con = duckdb.connect(str(db), read_only=True, config={"enable_external_access": False})
    trace, usages, retry = {"attempts": []}, [], ""
    try:
        cat = catalog(con)
        for _ in range(2):
            plan, usage = ask_json(c, PLAN_PROMPT.format(spreadsheet=spreadsheet or L.SPREADSHEET, catalog=cat,
                                                         question=question, retry=retry),
                                   effort="low", valid=_valid)
            usages.append(usage)
            attempt = {"answerable": plan["answerable"], "why": plan.get("why"), "sql": plan.get("sql")}
            trace["attempts"].append(attempt)
            if not plan["answerable"]:
                return None, trace, usages
            sql = plan["sql"].strip().rstrip(";")
            if not _is_one_select(sql):
                attempt["error"] = "not a single SELECT"
            else:
                try:
                    cur = con.execute(sql)
                    cols = [d[0] for d in cur.description]
                    rows = [dict(zip(cols, r)) for r in cur.fetchmany(MAX_ROWS)]
                    if "cell_ref" not in cols:
                        attempt["error"] = "result has no cell_ref column"
                    elif not rows:
                        attempt["error"] = "no rows"
                    else:
                        attempt["rows"] = len(rows)
                        return rows, trace, usages
                except duckdb.Error as e:
                    attempt["error"] = str(e).splitlines()[0][:300]
            retry = (f"\nYour previous SQL was:\n{sql}\nIt failed: {attempt['error']}. "
                     f"Fix it, or say the spreadsheet cannot answer.\n")
        return None, trace, usages
    finally:
        con.close()


def answer(c, question, db=DB, spreadsheet=None, cell=None, on_text=None, on_evidence=None):
    """Explained answer from spreadsheet cells, or None to fall back. Returns (result or None, trace).
    `cell(ref)` turns a cell_ref into evidence (default: the eval Library's);
    `on_text` streams the answer as it is written (answering.ask_with_docs);
    `on_evidence(cells)` hears which cells were found, before the answer is written."""
    rows, trace, usages = plan_and_run(c, question, db, spreadsheet)
    trace["plan_usage"] = usages
    if not rows:
        return None, trace
    evidence, seen = [], set()
    for r in rows:
        ref = r["cell_ref"]
        if ref not in seen and (ev := (cell or L.sheet_cell)(ref)):
            seen.add(ref)
            evidence.append(ev)
    if not evidence:
        return None, trace
    if on_evidence:
        on_evidence(evidence)
    result = ask_with_docs(c, question, evidence, on_text=on_text)
    if result.get("not_found"):
        trace["answer"] = "not found in the cells"
        return None, trace
    return result, trace
