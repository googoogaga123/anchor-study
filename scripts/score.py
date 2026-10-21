"""Phase 3: run any setup on the Build set and print counts per tag.

    .venv/bin/python scripts/score.py <setup> [--ids Q01,Q02] [--workers 4]

For each question it records:
  correct        matches the answer key (grader.py)
  Hallucination  at least one claim not backed by the whole Library (grader.py)
  Unsure         the live checker's verdict against what was retrieved
                 (checker.py) - what a user would see as an Unsure label
  refusal kind   for not_in_docs: GENUINE if the setup retrieved the near-miss
                 evidence and still refused, HOLLOW if it refused without
                 seeing it (near_miss.json). A hollow pass looks correct but is
                 not evidence that the design refuses when the answer is absent.

Everything is saved to runs/<setup>__<UTC time>.jsonl (one line per question,
plus a summary line), so any count can be traced back to the answer behind it.

The Test set is locked. Running it needs --set Test --final, and the plan says
that happens once, at the very end (phase 10).

Results are counts ("6 of 7"), never percentages.
"""
import argparse
import csv
import datetime as dt
import json
import pathlib
import re
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import library as L  # noqa: E402
from checker import check  # noqa: E402
from grader import grade, says_not_found  # noqa: E402
from answering import EFFORT, PROMPT_VERSION as ANSWER_PROMPT  # noqa: E402
from openai_client import MODEL, client  # noqa: E402
from setups import SETUPS  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"
# partial: the materials answer part of the question (or one reading of it);
# the right answer gives that part and says what the materials do not say.
TAGS = ["lookup", "numeric", "partial", "not_in_docs", "solve"]


def load_questions(which, group=None):
    if group:
        # Questions added to the Build set after the ladder's first results, kept
        # in their own file and reported on their own, so the original 21 - and
        # every result already reported on them - never change. Scored only once
        # the owner has verified every one against the files: a question nobody
        # checked is not evidence.
        name = f"eval_set_{group}.csv"
        rows = [r for r in csv.DictReader((ROOT / name).open()) if r["set"] == which]
        unverified = [r["id"] for r in rows if r["verified"].strip().lower() != "yes"]
        if unverified:
            sys.exit(f"{name}: {len(unverified)} question(s) not verified yet "
                     f"({', '.join(unverified)}). Check each against its file, set verified=Yes, then run.")
        return rows
    return [r for r in csv.DictReader((ROOT / "eval_set.csv").open()) if r["set"] == which]


def refusal_kind(row, result, near_miss):
    if row["tag"] != "not_in_docs" or not says_not_found(result):
        return None
    nm = near_miss.get(row["id"])
    if not nm:
        return "no_near_miss"
    seen = any(re.search(p, e["text"], re.I) for e in result.get("retrieved", []) for p in nm["patterns"])
    return "genuine" if seen else "hollow"


def run_one(c, setup, row, library, near_miss):
    """Score one question. A failure is recorded on that question, never fatal
    to the run - the other answers are already paid for."""
    try:
        return _run_one(c, setup, row, library, near_miss)
    except Exception as e:  # noqa: BLE001
        return {"id": row["id"], "tag": row["tag"], "question": row["question"],
                "error": f"{type(e).__name__}: {str(e)[:300]}"}


def _run_one(c, setup, row, library, near_miss):
    result = setup(c, row)
    verdict, g_usage = grade(c, row, result, library)
    checked, c_usage = check(c, row["question"], result)
    return {
        "id": row["id"], "tag": row["tag"], "question": row["question"],
        "correct_answer": row["correct_answer"],
        "result": {k: v for k, v in result.items() if k not in ("usage", "route_usage")}
                  # The excerpt text is saved too (18 Oct 2026): ids alone point at
                  # different text once the Library is re-chunked. Written after
                  # answering and grading, so it changes no result.
                  | {"retrieved": [{k: e[k] for k in ("id", "file", "loc", "text")}
                                   for e in result.get("retrieved", [])]},
        "correct": verdict["correct"], "hallucination": verdict["hallucination"],
        "grader": verdict, "checker": checked,
        "refusal": refusal_kind(row, result, near_miss),
        "usage": {"answer": result.get("usage"), "route": result.get("route_usage"),
                  "grader": g_usage, "checker": c_usage},
    }


def table(all_records):
    records = [r for r in all_records if "error" not in r]
    failed = [r for r in all_records if "error" in r]

    def counts(rs):
        n = len(rs)
        return (n, sum(r["correct"] for r in rs), sum(r["hallucination"] for r in rs),
                sum(r["checker"]["unsure"] for r in rs))
    lines = [f"{'tag':<13}{'correct':>12}{'Hallucinations':>17}{'checker Unsure':>17}",
             "-" * 59]
    for tag in TAGS + ["all"]:
        rs = records if tag == "all" else [r for r in records if r["tag"] == tag]
        if not rs:
            continue
        n, ok, hal, uns = counts(rs)
        if tag == "all":
            lines.append("-" * 59)
        lines.append(f"{tag:<13}{f'{ok} of {n}':>12}{f'{hal} of {n}':>17}{f'{uns} of {n}':>17}")
    # Added groups mark how each question is worded: naming a code ("Q7", "G7")
    # favours keyword search, everyday words favour vectors. Shown apart so a
    # win on one kind is not read as a win on both.
    for w, label in (("code", "names a code"), ("plain", "everyday words")):
        rs = [r for r in records if r.get("wording") == w]
        if rs:
            n, ok, hal, uns = counts(rs)
            lines.append(f"{label:<13}{f'{ok} of {n}':>12}{f'{hal} of {n}':>17}{f'{uns} of {n}':>17}")
    nid = [r for r in records if r["tag"] == "not_in_docs"]
    if nid:
        kinds = [r["refusal"] for r in nid]
        n_nm = sum(r["id"] in NEAR_MISS for r in nid)
        lines += ["", f"not_in_docs refusals: {sum(k is not None for k in kinds)} of {len(nid)} refused"
                      f" - genuine {kinds.count('genuine')}, hollow {kinds.count('hollow')}"
                      f" (of the {n_nm} with a near-miss in the Library);"
                      f" {kinds.count('no_near_miss')} refused where the Library has no near-miss"]
    if failed:
        lines += ["", f"NOT SCORED ({len(failed)}, left out of every count above): "
                      + ", ".join(f"{r['id']} ({r['error'][:80]})" for r in failed)]
    quotes = sum(r["checker"]["quotes_total"] for r in records)
    if quotes:
        lines.append(f"quoted passages found in the retrieved text: "
                     f"{sum(r['checker']['quotes_ok'] for r in records)} of {quotes}")
    return "\n".join(lines)


NEAR_MISS = {k: v for k, v in json.loads((ROOT / "scripts" / "near_miss.json").read_text()).items()
             if not k.startswith("_")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("setup", choices=sorted(SETUPS))
    ap.add_argument("--set", default="Build", choices=["Build", "Test"])
    ap.add_argument("--group", choices=["added", "solve"], help="score an added group (eval_set_<group>.csv) instead of the original questions; reported on its own. 'solve' (S4) has its own locked Test questions")
    ap.add_argument("--final", action="store_true", help="required to open the Test set (phase 10)")
    ap.add_argument("--ids", help="comma-separated question ids, e.g. Q01,Q22")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--k", type=int, help="chunks handed to the model (default setups.K = 5); "
                    "for side experiments - the run file name records it")
    args = ap.parse_args()
    if args.set == "Test" and not args.final:
        sys.exit("The Test set is locked until phase 10. Re-run with --set Test --final only then.")
    if args.group == "added" and args.set != "Build":
        sys.exit("The added group belongs to the Build set only.")

    import setups as S
    if args.k:
        S.K = args.k
    setup = SETUPS[args.setup]
    rows = load_questions(args.set, args.group)
    if args.ids:
        want = set(args.ids.split(","))
        rows = [r for r in rows if r["id"] in want]
    c, library = client(), L.library_text()
    with ThreadPoolExecutor(args.workers) as pool:
        records = list(pool.map(lambda r: run_one(c, setup, r, library, NEAR_MISS), rows))
    for rec, row in zip(records, rows):
        if row.get("wording"):
            rec["wording"] = row["wording"]

    usage = [u for r in records for u in r.get("usage", {}).values() if u]
    totals = {"model_calls": len(usage),
              "prompt_tokens": sum(u["prompt_tokens"] for u in usage),
              "completion_tokens": sum(u["completion_tokens"] for u in usage)}
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    RUNS.mkdir(exist_ok=True)
    tag = (f"_k{S.K}" if args.k else "") + (f"__{args.group}" if args.group else "")
    out = RUNS / f"{args.setup}{tag}__{stamp}.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        f.write(json.dumps({"summary": True, "setup": args.setup, "set": args.set, "group": args.group,
                            "model": MODEL, "answer_effort": EFFORT, "answer_prompt": ANSWER_PROMPT, "k": S.K,
                            "questions": len(records), "usage": totals,
                            "table": table(records)}, ensure_ascii=False) + "\n")

    label = " (sanity check of the scoring - reads the answer key, not a ladder rung)" \
        if getattr(setup, "CHEATS", False) else ""
    group = f", group {args.group} (not part of the original 21)" if args.group else ""
    print(f"\nsetup: {args.setup}{label}\nset: {args.set}{group}, {len(records)} questions, model {MODEL}, k {S.K}\n")
    print(table(records))
    print(f"\nmodel calls {totals['model_calls']}, tokens in {totals['prompt_tokens']:,}, "
          f"out {totals['completion_tokens']:,}\nsaved {out.relative_to(ROOT)}")
    for r in records:
        if "error" in r:
            print(f"  {r['id']} NOT SCORED - {r['error']}")
            continue
        flags = [x for x, on in (("WRONG", not r["correct"]), ("HALLUCINATION", r["hallucination"]),
                                 ("UNSURE", r["checker"]["unsure"])) if on]
        if flags:
            bad = [cl["claim"] for cl in r["grader"].get("claims", []) if not cl.get("backed")]
            print(f"  {r['id']} {' '.join(flags)}" + (f" - unbacked: {bad}" if bad else ""))


if __name__ == "__main__":
    main()
