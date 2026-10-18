"""The front page's example answers, copied word for word from real runs.

    .venv/bin/python scripts/web_samples.py

The try-it box on the front page shows a saved answer instead of running the
pipeline (no cost, nothing to abuse). Each one is copied unchanged from a
`routed` run file - never written or edited by hand - with its steps, quotes,
citations and pictures, and the run it came from.

Only questions whose answers show no personal details are used (owner's call,
18 Oct): no TA names, emails or Telegram handles. The script refuses to write
anything that looks like an email address, a handle or a phone number.

Writes web/static/samples.json and copies any picture into web/static/samples/.
"""
import json
import pathlib
import re
import shutil

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "static"

# (run file, question id, the button's label), in the order the front page
# offers them; the first fills the box. All from the prompt v4 routed runs of
# 18 Oct; A04 was left out because its routed answer came back Unsure.
SAMPLES = [
    ("runs/routed__added__20261018T070746Z.jsonl", "A06", "Quiz marks"),       # everyday course rule
    ("runs/routed__added__20261018T070746Z.jsonl", "A13", "Quiz time limit"),  # says what the materials don't cover
    ("runs/routed__20261018T070432Z.jsonl", "Q18", "Midterm maths"),           # maths from the midterm PDF
    ("runs/routed__20261018T070432Z.jsonl", "Q08", "Read a flowchart"),        # answer resting on a picture
    ("runs/routed__20261018T070432Z.jsonl", "Q11", "Spreadsheet figure"),      # a number read from a spreadsheet
]
PERSONAL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|(?<![\w/])@[A-Za-z_]\w{2,}|\+?\d[\d ]{7,}\d")


def sample(run, qid, label):
    row = next(r for r in map(json.loads, (ROOT / run).open(encoding="utf-8")) if r.get("id") == qid)
    res = row["result"]
    by_id = {e["id"]: e for e in res.get("retrieved", [])}
    steps = []
    for s in res.get("steps", []):
        ev = by_id.get(s.get("source"))
        steps.append({"text": s["text"], "quote": s.get("quote"),
                      "source": {"file": ev["file"], "loc": ev["loc"]} if ev else None})
    pictures = []
    for p in res.get("pictures") or []:
        src = ROOT / p["image"]
        dest = OUT / "samples" / src.name
        dest.parent.mkdir(exist_ok=True)
        shutil.copyfile(src, dest)
        pictures.append({**{k: p[k] for k in ("file", "loc", "kind", "note")}, "image": f"/static/samples/{src.name}"})
    out = {"id": qid, "label": label, "question": row["question"], "final_answer": res["final_answer"],
           "not_found": bool(res.get("not_found")), "steps": steps, "pictures": pictures,
           "route": {"path": (res.get("route") or {}).get("path")},
           "unsure": row["checker"]["unsure"], "unsure_reasons": row["checker"]["unsure_reasons"],
           "from_run": run}
    shown = json.dumps({k: out[k] for k in ("question", "final_answer", "steps", "pictures")}, ensure_ascii=False)
    if PERSONAL.search(shown):
        raise SystemExit(f"{qid}: looks like personal details ({PERSONAL.search(shown).group()}) - not written")
    return out


def main():
    samples = [sample(*s) for s in SAMPLES]
    (OUT / "samples.json").write_text(json.dumps(samples, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    for s in samples:
        print(f"{s['id']}  unsure={s['unsure']}  pictures={len(s['pictures'])}  {s['question']}")


if __name__ == "__main__":
    main()
