"""Phase 2 done-when check: the parse ceiling.

For every answerable eval question, is its answer actually present in what we
extracted? Parsing sets a hard ceiling on every later phase: an answer that is
not in the parsed text cannot be retrieved, reranked or routed to, no matter
how good phases 4-9 are. So this runs before any retrieval exists.

Three kinds of probe (scripts/probes.json):
  text    a substring that must appear in the file's parsed output
  absent  a substring that must NOT appear (the not_in_docs near-misses)
  cell    a sheet!cell that must hold a given number
  manual  no honest string test exists; the owner judges it

Reported as counts, never percentages.
"""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "parsed"

# Which parsed artefact answers for each source file.
PARSED = {
    "week12hints.txt": "week12hints__txt.lines.txt",
    "IS114 AY26-T1 Course Content, Student Edition.docx": "IS114_AY26-T1_Course_Content_Student_Edition__docx.md",
    "MidtermSampleSolutions.pdf": "MidtermSampleSolutions__pdf.pages.md",
    "IS114 AY26-T1 Course Content, Student Edition.pdf": "IS114_AY26-T1_Course_Content_Student_Edition__pdf.pages.md",
}


def locate(text, idx):
    """Say where a hit landed: PDF page, or line number."""
    before = text[:idx]
    pages = re.findall(r"^## page (\d+)", before, re.M)
    if pages:
        return f"p. {pages[-1]}"
    m = re.findall(r"^\s*(\d+)\s\s", before, re.M)
    return f"line {m[-1]}" if m else f"char {idx}"


def main():
    probes = json.loads((ROOT / "scripts" / "probes.json").read_text())
    text_pass = text_total = 0
    absent_pass = absent_total = 0
    cell_pass = cell_total = 0
    manual = []
    failures = []

    for fname, items in probes.items():
        if fname == "_README":
            continue
        rel = PARSED.get(fname)
        body = None
        if rel:
            p = OUT / rel
            body = p.read_text(encoding="utf-8") if p.exists() else None
        print(f"\n=== {fname}")
        if rel and body is None:
            print(f"  !! not parsed yet: parsed/{rel}")

        for it in items:
            pid, ans = it["id"], it.get("answer", "")
            if "manual" in it:
                manual.append((pid, fname, ans, it["manual"]))
                print(f"  MANUAL {pid:22} {ans}")
                continue

            if "cell" in it:
                cell_total += 1
                try:
                    import duckdb
                    con = duckdb.connect(str(OUT / "sheets.duckdb"), read_only=True)
                    row = con.execute("SELECT value_num, formula FROM cells WHERE cell_ref=?", [it["cell"]]).fetchone()
                    con.close()
                    hit = row and row[0] is not None and abs(row[0] - float(ans)) < 0.005
                except Exception as e:  # noqa: BLE001
                    row, hit = None, False
                    print(f"  ERROR  {pid}: {e}")
                cell_pass += bool(hit)
                got = row[0] if row else None
                print(f"  {'PASS' if hit else 'FAIL'}   {pid:22} {it['cell']} = {got} (want {ans})")
                if not hit:
                    failures.append((pid, fname, f"cell {it['cell']} = {got}, want {ans}"))
                continue

            if "absent" in it:
                absent_total += 1
                if body is None:
                    print(f"  SKIP   {pid:22} (file not parsed)")
                    continue
                found = [s for s in it["absent"] if s.lower() in body.lower()]
                hit = not found
                absent_pass += hit
                print(f"  {'PASS' if hit else 'FAIL'}   {pid:22} absent: {it['absent']}"
                      + ("" if hit else f"  <- FOUND {found}"))
                if not hit:
                    failures.append((pid, fname, f"should be absent but found {found}"))
                continue

            text_total += 1
            if body is None:
                print(f"  SKIP   {pid:22} (file not parsed)")
                continue
            low = body.lower()
            hit_at = next(((s, low.find(s.lower())) for s in it["text"] if s.lower() in low), None)
            text_pass += bool(hit_at)
            if hit_at:
                s, idx = hit_at
                print(f"  PASS   {pid:22} {s!r} at {locate(body, idx)}")
            else:
                print(f"  FAIL   {pid:22} none of {it['text']} found")
                failures.append((pid, fname, f"none of {it['text']} in parsed text"))

    print("\n" + "=" * 60)
    print(f"text probes      {text_pass} of {text_total}")
    print(f"absence probes   {absent_pass} of {absent_total}")
    print(f"cell probes      {cell_pass} of {cell_total}")
    print(f"automatic total  {text_pass + absent_pass + cell_pass} of {text_total + absent_total + cell_total}")
    print(f"manual checks    {len(manual)} awaiting the owner's judgement")
    if failures:
        print("\nFAILURES")
        for pid, fname, why in failures:
            print(f"  {pid:22} {fname}\n    {why}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
