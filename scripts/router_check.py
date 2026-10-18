"""Phase 8: does the router pick the right tag? (Done when right on >= 19 of 21 Build.)

Expected tag: the eval tag for lookup and numeric questions. For not_in_docs
(and partial) questions the eval tag says the Library lacks the answer, not
what KIND of answer is wanted, so their expected tag is in router_labels.csv -
proposed, and counted separately until the owner marks it verified. Build set
only; the Test set is never routed here.

    .venv/bin/python scripts/router_check.py
"""
import csv
import pathlib
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import router  # noqa: E402
from openai_client import client  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main():
    labels = {r["id"]: r for r in csv.DictReader((ROOT / "router_labels.csv").open())}
    groups = {
        "original 21": [r for r in csv.DictReader((ROOT / "eval_set.csv").open()) if r["set"] == "Build"],
        "added 13": [r for r in csv.DictReader((ROOT / "eval_set_added.csv").open()) if r["set"] == "Build"],
    }
    c = client()
    for name, rows in groups.items():
        with ThreadPoolExecutor(4) as pool:
            tags = list(pool.map(lambda r: router.route(c, r["question"])[0], rows))
        right = proposed_right = proposed = 0
        print(f"\n{name}")
        for r, tag in zip(rows, tags):
            if r["tag"] in ("lookup", "numeric"):
                want, kind = r["tag"], "eval tag"
            else:
                lab = labels[r["id"]]
                want = lab["expected_tag"]
                kind = "verified" if lab["verified"].strip().lower() == "yes" else "proposed"
            ok = tag == want
            right += ok
            if kind == "proposed":
                proposed += 1
                proposed_right += ok
            flag = "" if ok else "   <-- WRONG"
            print(f"  {r['id']}  {r['tag']:<12} expected {want:<8} ({kind:<8}) got {tag}{flag}")
        print(f"  right {right} of {len(rows)} (of which {proposed_right} of {proposed} against proposed labels)")


if __name__ == "__main__":
    main()
