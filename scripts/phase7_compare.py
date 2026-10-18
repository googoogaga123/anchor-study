"""Phase 7, step 2: compare the owner's labels with the checker.

Runs the CURRENT checker afresh on the 30 sampled answers (the stored verdicts
came from older checker versions), then counts against the owner's labels:

  agreement    owner and checker say the same (supported = not Unsure)
  misses       owner: not supported; checker: passed it      <- must be <= 2 of 30
  false alarms owner: supported;     checker: Unsure
  can't tell   owner could not decide; left out of the three counts above

--reuse takes the checker's verdicts from the last results.json instead of
running the checker again (no API calls) - for when only labels changed.

    .venv/bin/python scripts/phase7_compare.py ~/Downloads/phase7_labels.json [--reuse]
"""
import json
import pathlib
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from checker import check  # noqa: E402
from openai_client import client  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "phase7"
MAX_MISSES = 2


def main():
    labels = json.loads(pathlib.Path(next(a for a in sys.argv[1:] if not a.startswith("--"))).expanduser().read_text())
    sample = json.loads((OUT / "sample.json").read_text())["answers"]
    missing = [a["n"] for a in sample if not (labels.get(str(a["n"])) or {}).get("label")]
    if missing:
        sys.exit(f"{len(missing)} answer(s) not labelled yet: {missing}")
    if "--reuse" in sys.argv:
        old = {r["n"]: r for r in json.loads((OUT / "results.json").read_text())["answers"]}
        verdicts = [{"unsure": old[a["n"]]["checker_unsure"], "unsure_reasons": old[a["n"]]["checker_reasons"]}
                    for a in sample]
    else:
        c = client()
        with ThreadPoolExecutor(4) as pool:
            verdicts = list(pool.map(lambda a: check(c, a["question"], a["result"])[0], sample))

    rows, counts = [], {"agree": 0, "miss": 0, "false_alarm": 0, "cant_tell": 0}
    for a, v in zip(sample, verdicts):
        owner = labels[str(a["n"])]["label"]
        unsure = v["unsure"]
        if owner == "cant_tell":
            kind = "cant_tell"
        elif (owner == "not_supported") == unsure:
            kind = "agree"
        else:
            kind = "miss" if owner == "not_supported" else "false_alarm"
        counts[kind] += 1
        rows.append({"n": a["n"], "id": a["id"], "run": a["run"], "owner": owner,
                     "owner_note": labels[str(a["n"])].get("note", ""), "checker_unsure": unsure,
                     "checker_reasons": v["unsure_reasons"], "result": kind})
    judged = len(sample) - counts["cant_tell"]
    (OUT / "results.json").write_text(json.dumps({"counts": counts, "answers": rows}, indent=1,
                                                 ensure_ascii=False), encoding="utf-8")
    print(f"agreement     {counts['agree']} of {judged}")
    print(f"misses        {counts['miss']} of {judged}   (owner: not supported, checker passed it; "
          f"phase 7 needs <= {MAX_MISSES})")
    print(f"false alarms  {counts['false_alarm']} of {judged}   (owner: supported, checker said Unsure)")
    print(f"can't tell    {counts['cant_tell']} of {len(sample)}")
    for r in rows:
        if r["result"] in ("miss", "false_alarm"):
            print(f"  #{r['n']} {r['id']} {r['result'].upper()} - owner: {r['owner_note'] or '(no note)'}"
                  f" | checker: {'; '.join(r['checker_reasons']) or 'passed'}")
    print("PASS" if counts["miss"] <= MAX_MISSES else "FAIL: fix the checker, then re-validate")


if __name__ == "__main__":
    main()
