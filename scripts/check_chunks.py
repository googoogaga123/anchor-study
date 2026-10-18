"""Phase 2, step 6 check: does chunking keep every answer findable?

check_ceiling.py proved each answer is somewhere in the parsed text. Chunking
can still lose it: an answer cut across a chunk boundary is in neither half,
and a chunk whose page or line range is wrong produces a wrong citation.

Three checks, reported as counts:
  whole     every text probe sits entirely inside at least one chunk
  cited     that chunk's page/line range covers the location the eval set
            cites (PDF pages and text-file lines; the Word file has no pages)
  together  the near-miss tables stay in one chunk each, so a retriever that
            finds the table sees all of it - G1 next to G11, Week 1 next to
            Week 13. A split table would let a not_in_docs question pass for
            the wrong reason: "G12 isn't in the half I retrieved".
"""
import csv
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "parsed"

IS114_PDF = "IS114 AY26-T1 Course Content, Student Edition.pdf"
# (name, file, regexes that must all match inside the same chunk)
TOGETHER = [
    ("sections table G1-G11", IS114_PDF,
     [rf"\|\s*G{n}\s*\|" for n in range(1, 12)]),
    ("schedule Weeks 1-13", IS114_PDF,
     [rf"^\|\s*{n}\s*\|" for n in range(1, 14)] + [r"Trial Exam"]),
    ("midterm Q11 willingness-to-pay table", "MidtermSampleSolutions.pdf",
     [r"1st cup\s*\|\s*12\s*\|\s*10\s*\|\s*6\s*\|"]),
]


def cited_span(location):
    """Pages or lines the eval set cites, or None when it cites neither."""
    if m := re.match(r"p\.\s*(\d+)", location):
        return ("page", {int(m.group(1))})
    if location.lower().startswith("line"):
        return ("line", {int(n) for n in re.findall(r"\d+", location.split("(")[0])})
    return None


def covers(chunk, span):
    kind, wanted = span
    if kind == "page" and "page_start" in chunk:
        return any(chunk["page_start"] <= w <= chunk["page_end"] for w in wanted)
    if kind == "line" and "line_start" in chunk:
        return any(chunk["line_start"] <= w <= chunk["line_end"] for w in wanted)
    return False


def main():
    chunks = [json.loads(ln) for ln in (OUT / "chunks.jsonl").read_text().splitlines()]
    probes = json.loads((ROOT / "scripts" / "probes.json").read_text())
    evals = {r["id"]: r for r in csv.DictReader((ROOT / "eval_set.csv").open())}
    failures = []
    whole = whole_n = cited = cited_n = 0

    for fname, items in probes.items():
        if fname == "_README":
            continue
        mine = [c for c in chunks if c["file"] == fname]
        if not mine:
            continue  # spreadsheet (DuckDB) and PNGs (not described yet)
        print(f"\n=== {fname}")
        for it in items:
            if "text" not in it:
                continue
            pid = it["id"]
            whole_n += 1
            hits = [c for c in mine
                    if any(s.lower() in c["text"].lower() for s in it["text"])]
            if not hits:
                print(f"  FAIL   {pid:6} not whole in any chunk: {it['text']}")
                failures.append(f"{pid}: answer split or lost by chunking")
                continue
            whole += 1
            ev = evals.get(pid.rstrip("b"))
            span = cited_span(ev["location"]) if ev else None
            where = ", ".join(f"{c['chunk_id']} ({c['loc'] or c['heading']})" for c in hits)
            if span is None:
                print(f"  PASS   {pid:6} in {where}  [eval cites {ev['location']!r}: no page/line to compare]"
                      if ev else f"  PASS   {pid:6} in {where}")
                continue
            cited_n += 1
            ok = any(covers(c, span) for c in hits)
            cited += ok
            print(f"  {'PASS' if ok else 'FAIL'}   {pid:6} in {where}  [eval cites {ev['location']!r}]")
            if not ok:
                failures.append(f"{pid}: chunk location does not cover {ev['location']!r}")

    print("\n=== near-miss and answer tables kept whole")
    together = 0
    for name, fname, needles in TOGETHER:
        hit = [c for c in chunks if c["file"] == fname
               and all(re.search(n, c["text"], re.M) for n in needles)]
        together += bool(hit)
        print(f"  {'PASS' if hit else 'FAIL'}   {name}"
              + (f" in {hit[0]['chunk_id']} ({hit[0]['loc']})" if hit else ""))
        if not hit:
            failures.append(f"{name}: split across chunks")

    print("\n" + "=" * 60)
    print(f"answer whole in a chunk      {whole} of {whole_n}")
    print(f"chunk covers cited location  {cited} of {cited_n}")
    print(f"tables kept in one chunk     {together} of {len(TOGETHER)}")
    if failures:
        print("\nFAILURES")
        for f in failures:
            print("  " + f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
