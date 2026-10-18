"""Compare two runs of the same setup question by question (no API calls).

    .venv/bin/python scripts/compare_runs.py runs/<old>.jsonl runs/<new>.jsonl [--answers]

Prints, for each run: correct, Hallucinations and checker Unsure (counts),
the answer prompt version, and the final answers' length in words (middle
value); then every question whose verdict changed. --answers also prints
both final answers for every question, to judge the wording by eye.
"""
import json
import statistics
import sys


def load(path):
    rows, summary = {}, {}
    for line in open(path, encoding="utf-8"):
        r = json.loads(line)
        if r.get("summary"):
            summary = r
        else:
            rows[r["id"]] = r
    return rows, summary


def verdict(r):
    return {"correct": bool(r.get("correct")), "Hallucination": bool(r.get("hallucination")),
            "Unsure": bool((r.get("checker") or {}).get("unsure"))}


def words(r):
    return len(((r.get("result") or {}).get("final_answer") or "").split())


def main():
    paths = [a for a in sys.argv[1:] if not a.startswith("--")]
    (old, so), (new, sn) = load(paths[0]), load(paths[1])
    ids = [i for i in old if i in new]
    print(f"{len(ids)} questions in both runs")
    for name, rows, s in (("old", old, so), ("new", new, sn)):
        v = [verdict(rows[i]) for i in ids]
        print(f"  {name}: prompt v{s.get('answer_prompt', '?')}  correct {sum(x['correct'] for x in v)} of {len(ids)}"
              f"  Hallucinations {sum(x['Hallucination'] for x in v)}  Unsure {sum(x['Unsure'] for x in v)}"
              f"  final answer words (middle value) {statistics.median(words(rows[i]) for i in ids)}")
    for i in ids:
        a, b = verdict(old[i]), verdict(new[i])
        changed = [f"{k} {a[k]} -> {b[k]}" for k in a if a[k] != b[k]]
        if changed or "--answers" in sys.argv:
            print(f"\n{i} {'; '.join(changed) or '(no change)'}")
            print(f"  old: {old[i]['result'].get('final_answer')}")
            print(f"  new: {new[i]['result'].get('final_answer')}")


if __name__ == "__main__":
    main()
