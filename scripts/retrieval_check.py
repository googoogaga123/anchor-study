"""Where does the chunk holding each answer rank? No answering model involved.

For every answerable Build question, the "answer chunks" are the chunks that
contain its parse-ceiling probe text (probes.json), or - for the two images and
Q17's table, whose probes are manual - every chunk of that file. The
spreadsheet is not chunked, so its questions are listed as unreachable by
vector search.

Prints the rank of the best answer chunk under each embedding model, and
counts how many questions have an answer chunk within the top 1, 3, 5, 10, 20.

    .venv/bin/python scripts/retrieval_check.py [3small bgem3 hybrid]

"hybrid" is phase 6: keyword + 3small vectors in Postgres, RRF, reranker.
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
from checker import norm  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
CUTS = [1, 3, 5, 10, 20]


def _key(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def answer_chunks(row, chunks, probes):
    texts = [t for items in probes.values() if isinstance(items, list)
             for it in items if it["id"].rstrip("b") == row["id"] for t in it.get("text", [])]
    same_file = [c for c in chunks if _key(c["file"]) == _key(row["source_file"])]
    hits = {c["chunk_id"] for c in same_file for t in texts if norm(t) in norm(c["text"])}
    if not hits and row["id"] == "Q17":
        hits = {c["chunk_id"] for c in same_file if "1st cup" in c["text"]}
    if not hits and row["file_format"] == "Image":
        hits = {c["chunk_id"] for c in same_file}
        # A PDF page carrying the same picture, its description reused
        # (describe_pdf_figures.py), holds the same answer.
        hits |= {c["chunk_id"] for c in chunks if f"Same picture as {row['source_file']}" in c["text"]}
    return hits


def main():
    models = sys.argv[1:] or list(embed.MODELS)
    probes = json.loads((ROOT / "scripts" / "probes.json").read_text())
    rows = [r for r in csv.DictReader((ROOT / "eval_set.csv").open())
            if r["set"] == "Build" and r["tag"] != "not_in_docs"]
    chunks = L.chunks()
    n_chunks = len(chunks)
    ranks = {m: {} for m in models}
    print(f"{'Q':<5}{'format':<12}" + "".join(f"{m:>9}" for m in models) + "   answer chunk(s)")
    for r in rows:
        gold = answer_chunks(r, chunks, probes)
        line = f"{r['id']:<5}{r['file_format']:<12}"
        for m in models:
            if m == "hybrid":
                order = [c["chunk_id"] for c in hybrid.search(r["question"], n_chunks)]
            else:
                order = [c["chunk_id"] for _, c in embed.search(m, r["question"], n_chunks)]
            rank = min((order.index(g) + 1 for g in gold), default=None)
            ranks[m][r["id"]] = rank
            line += f"{(rank if rank else '-'):>9}"
        print(line + "   " + (", ".join(sorted(gold)) if gold else "(spreadsheet: not chunked)"))
    reachable = [r["id"] for r in rows if any(ranks[m][r["id"]] for m in models)]
    print(f"\n{len(reachable)} of {len(rows)} answerable Build questions have an answer chunk "
          f"({len(rows) - len(reachable)} live in the spreadsheet). Library = {n_chunks} chunks.")
    for m in models:
        got = [ranks[m][q] for q in reachable]
        print(f"{m:>7}: " + ", ".join(f"top {k}: {sum(x is not None and x <= k for x in got)} of {len(got)}"
                                      for k in CUTS))


if __name__ == "__main__":
    main()
