"""Did each setup FIND the right evidence? One count per rung, top 1 / 3 / 5.

No answering model: this measures retrieval only, so it explains (or not) the
answer scores. The 21 Build questions split three ways, each with its own test:

  answer chunk   12  the answer sits in a chunk (retrieval_check.answer_chunks):
                     is that chunk in the top k?
  near-miss       4  not_in_docs with something close in the Library
                     (near_miss.json): is that near-miss text in the top k?
                     Seeing it is what makes a refusal genuine, not hollow.
  spreadsheet     2  the answer is one cell: did the setup return that cell?
                     Search never can (the spreadsheet is not chunked); the
                     SQL route can, whatever k is.

The other 3 not_in_docs questions have nothing close in the Library, so there
is no right evidence to find; they are listed, not counted. Totals are out of
18, not 21: counting those 3 as hits would flatter every rung.

  routed = the app's route (phase 8): the SQL route for the spreadsheet cells,
  hybrid search for everything else (the numeric questions it does not answer
  fall back to hybrid too).

    .venv/bin/python scripts/evidence_check.py
"""
import csv
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import embed  # noqa: E402
import hybrid  # noqa: E402
import library as L  # noqa: E402
import sql_route  # noqa: E402
from openai_client import client  # noqa: E402
from retrieval_check import answer_chunks  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
CUTS = [1, 3, 5]


def main():
    rows = [r for r in csv.DictReader((ROOT / "eval_set.csv").open()) if r["set"] == "Build"]
    probes = json.loads((ROOT / "scripts" / "probes.json").read_text())
    near = {k: v for k, v in json.loads((ROOT / "scripts" / "near_miss.json").read_text()).items()
            if not k.startswith("_")}
    chunks = L.chunks()
    n = len(chunks)
    c = client()

    # Full rankings per question, once per search method.
    rank = {"vector": {}, "hybrid": {}}
    for r in rows:
        rank["vector"][r["id"]] = [ch for _, ch in embed.search("3small", r["question"], n)]
        rank["hybrid"][r["id"]] = hybrid.search(r["question"], n)

    # The SQL route's cells for the spreadsheet questions (independent of k).
    sql_cells = {}
    for r in rows:
        if r["file_format"] == "Spreadsheet":
            got, _, _ = sql_route.plan_and_run(c, r["question"])
            sql_cells[r["id"]] = {g["cell_ref"] for g in (got or [])}

    kinds, nothing = {}, []
    for r in rows:
        if r["file_format"] == "Spreadsheet":
            kinds[r["id"]] = "spreadsheet"
        elif r["tag"] == "not_in_docs":
            if r["id"] in near:
                kinds[r["id"]] = "near-miss"
            else:
                nothing.append(r["id"])
        else:
            kinds[r["id"]] = "answer chunk"

    def found(setup, r, k):
        kind = kinds[r["id"]]
        if kind == "spreadsheet":
            return setup == "routed" and r["location"] in sql_cells.get(r["id"], set())
        top = rank["hybrid" if setup == "routed" else setup][r["id"]][:k]
        if kind == "answer chunk":
            gold = answer_chunks(r, chunks, probes)
            return any(ch["chunk_id"] in gold for ch in top)
        pats = near[r["id"]]["patterns"]
        return any(re.search(p, ch["text"], re.I) for ch in top for p in pats)

    parts = ["answer chunk", "near-miss", "spreadsheet"]
    size = {p: sum(v == p for v in kinds.values()) for p in parts}
    head = f"{'setup':<8}{'top k':>6}" + "".join(f"{p + ' (of ' + str(size[p]) + ')':>24}" for p in parts) \
        + f"{'found (of ' + str(len(kinds)) + ')':>18}"
    print(head)
    print("-" * len(head))
    missed = {}
    for setup in ("vector", "hybrid", "routed"):
        for k in CUTS:
            hits = {p: 0 for p in parts}
            for r in rows:
                if r["id"] in kinds:
                    if found(setup, r, k):
                        hits[kinds[r["id"]]] += 1
                    else:
                        missed.setdefault((setup, k), []).append(r["id"])
            total = sum(hits.values())
            print(f"{setup:<8}{k:>6}" + "".join(f"{hits[p]:>24}" for p in parts) + f"{total:>18}")
    print(f"\nnothing to find (not_in_docs with no near-miss in the Library): {', '.join(nothing)}")
    print("not found:")
    for (setup, k), ids in missed.items():
        print(f"  {setup} top {k}: {', '.join(ids)}")


if __name__ == "__main__":
    main()
