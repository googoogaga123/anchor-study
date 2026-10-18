"""Phase 7, step 1: pick 30 answers for the owner to label, and build the page.

The checker decides the Unsure label on every answer. Phase 7 asks: when the
owner judges an answer by hand, does the checker agree? Done when it misses at
most 2 of 30 (an answer the owner calls not supported, which it passed).

The sample (seed SEED, so it can be rebuilt exactly):
  - from the latest complete Build runs of rungs 1-3 (rungs 2-3 on answering
    prompt v3), original 21 and the added group; never the Test set;
  - only answers with steps - a bare refusal gives the checker nothing to judge;
  - EVERY answer the checker or the grader flagged (Unsure, Hallucination, or
    wrong). Picked at random, 30 would hold one or two bad answers at most,
    and could not show whether the checker misses them;
  - the rest drawn at random, at most 2 answers per question.

The page shows no verdicts and does not say which answers were flagged: the
owner labels blind. Output (phase7/):
  sample.json   the 30, with where each came from (run file, question id)
  label.html    the labelling page; open it in a browser, labels are kept in
                the browser and downloaded as phase7_labels.json

    .venv/bin/python scripts/phase7_sample.py
"""
import collections
import html
import json
import pathlib
import random

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "phase7"
SEED = 7
N = 30
PER_QUESTION = 2

RUNS = [  # latest complete runs, 17 Oct 2026
    "runs/llm_alone__20261017T083136Z.jsonl",
    "runs/vector_3small__20261017T100053Z.jsonl",
    "runs/vector_3small_k3__20261017T101145Z.jsonl",
    "runs/vector_3small_k1__20261017T101219Z.jsonl",
    "runs/vector_3small__added__20261017T101258Z.jsonl",
    "runs/hybrid__20261017T161433Z.jsonl",
    "runs/hybrid_k3__20261017T162448Z.jsonl",
    "runs/hybrid_k1__20261017T163435Z.jsonl",
    "runs/hybrid__added__20261017T173941Z.jsonl",
]


def pool():
    # Run files keep each excerpt's id, file and loc, not its text; every run
    # above used the current 35-chunk Library, so the text comes from it by id.
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import library as L
    text = {c["chunk_id"]: c["text"] for c in L.chunks()}
    out = []
    for run in RUNS:
        for line in (ROOT / run).read_text().splitlines():
            r = json.loads(line)
            if r.get("summary") or "error" in r or not r["result"].get("steps"):
                continue
            flagged = r["checker"]["unsure"] or r["hallucination"] or not r["correct"]
            for e in r["result"]["retrieved"]:
                if "text" not in e:  # runs before 18 Oct saved ids only
                    e["text"] = text[e["id"]]  # KeyError = the Library changed since this run
            out.append({"run": run, "id": r["id"], "question": r["question"], "flagged": flagged,
                        "result": {k: r["result"][k] for k in ("final_answer", "steps", "retrieved")}})
    return out


def pick(answers):
    rng = random.Random(SEED)
    chosen = [a for a in answers if a["flagged"]]
    per_q = collections.Counter(a["id"] for a in chosen)
    rest = [a for a in answers if not a["flagged"]]
    rng.shuffle(rest)
    for a in rest:
        if len(chosen) == N:
            break
        if per_q[a["id"]] < PER_QUESTION:
            chosen.append(a)
            per_q[a["id"]] += 1
    rng.shuffle(chosen)  # flagged ones not first
    for i, a in enumerate(chosen, 1):
        a["n"] = i
    return chosen


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Phase 7 labels</title>
<style>
:root{--bg:#fbfaf7;--card:#fff;--ink:#1d1d1b;--mute:#6b6a65;--line:#e4e1d8;--acc:#2f5d8a;--hl:#fff1a8}
@media (prefers-color-scheme:dark){:root{--bg:#1b1b1a;--card:#242422;--ink:#ecebe6;--mute:#a3a29b;--line:#3a3935;--acc:#8fb6dd;--hl:#5c5220}}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,system-ui,sans-serif}
main{max-width:860px;margin:0 auto;padding:24px 16px 120px}
h1{font-size:22px;margin:0 0 4px} .mute{color:var(--mute)}
.rules{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 16px;margin:16px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin:18px 0}
.card.done{border-color:var(--acc)} .q{font-weight:600} .final{margin:8px 0 10px;padding:8px 10px;border-left:3px solid var(--acc)}
ol.steps li{margin:6px 0} .quote{color:var(--mute);font-style:italic}
details{margin:6px 0;border:1px solid var(--line);border-radius:8px;padding:6px 10px}
summary{cursor:pointer;color:var(--acc)} pre{white-space:pre-wrap;font:13px/1.45 ui-monospace,Menlo,monospace;margin:6px 0}
mark{background:var(--hl);color:inherit}
.label{display:flex;flex-wrap:wrap;gap:14px;align-items:center;margin-top:12px;padding-top:10px;border-top:1px solid var(--line)}
textarea{width:100%;min-height:38px;font:inherit;background:var(--bg);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:6px}
.bar{position:fixed;left:0;right:0;bottom:0;background:var(--card);border-top:1px solid var(--line);padding:10px 16px calc(10px + env(safe-area-inset-bottom,0px))}
.bar div{max-width:860px;margin:0 auto;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
button{font:inherit;padding:6px 14px;border-radius:6px;border:1px solid var(--acc);background:var(--acc);color:#fff;cursor:pointer}
</style></head><body><main>
<h1>Phase 7: is each answer supported?</h1>
<div class="mute">30 answers. Your labels are compared with the checker's afterwards; its verdicts are not shown here.</div>
<div class="rules"><b>Supported</b> = every step, and the final answer, is stated in the retrieved excerpts or follows from them by
simple arithmetic or direct reading. Judge against the excerpts shown, not against what you know or the full course files.
A step saying the materials do not say something counts as supported if the excerpts indeed do not say it.
<br><b>Not supported</b> = at least one step or the final answer is not backed by the excerpts (invented, stretched, or from
outside knowledge), even if it happens to be true. Say which step in the note.
<br>The excerpt a step cites opens by default, its quote highlighted where it appears word for word.</div>
__CARDS__
</main>
<div class="bar"><div><span id="progress"></span><button id="dl">Download labels</button>
<span class="mute">saves phase7_labels.json to your Downloads</span></div></div>
<script>
const KEY = "phase7-labels-v1";
let labels = {};
try { labels = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) {}
function save() { try { localStorage.setItem(KEY, JSON.stringify(labels)); } catch (e) {} progress(); }
function progress() {
  const n = Object.values(labels).filter(l => l.label).length;
  document.getElementById("progress").textContent = n + " of 30 labelled";
  document.querySelectorAll(".card").forEach(c => c.classList.toggle("done", !!(labels[c.dataset.n] || {}).label));
}
document.querySelectorAll(".card").forEach(card => {
  const n = card.dataset.n, l = labels[n] || {};
  card.querySelectorAll("input[type=radio]").forEach(r => {
    if (r.value === l.label) r.checked = true;
    r.addEventListener("change", () => { labels[n] = Object.assign(labels[n] || {}, {label: r.value}); save(); });
  });
  const t = card.querySelector("textarea"); t.value = l.note || "";
  t.addEventListener("input", () => { labels[n] = Object.assign(labels[n] || {}, {note: t.value}); save(); });
});
document.getElementById("dl").addEventListener("click", () => {
  const blob = new Blob([JSON.stringify(labels, null, 1)], {type: "application/json"});
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "phase7_labels.json"; a.click();
});
progress();
</script></body></html>
"""


def esc(s):
    return html.escape(s or "")


def highlight(text, quote):
    """The excerpt, escaped, with the quote marked where it appears word for word."""
    if quote:
        i = text.lower().find(quote.lower())
        if i >= 0:
            return esc(text[:i]) + "<mark>" + esc(text[i:i + len(quote)]) + "</mark>" + esc(text[i + len(quote):])
    return esc(text)


def card(a):
    res = a["result"]
    cited = {s.get("source") for s in res["steps"] if s.get("source")}
    steps = "".join(
        f"<li>{esc(s['text'])}" + (f"<div class='quote'>quote: “{esc(s['quote'])}” — {esc(s.get('source'))}</div>"
                                   if s.get("quote") else "<div class='quote'>no quote</div>") + "</li>"
        for s in res["steps"])
    ev = ""
    for e in res["retrieved"] or []:
        quotes = [s["quote"] for s in res["steps"] if s.get("source") == e["id"] and s.get("quote")]
        body = esc(e["text"])
        for q in quotes[:1]:
            body = highlight(e["text"], q)
        ev += (f"<details{' open' if e['id'] in cited else ''}><summary>{esc(e['id'])} — {esc(e['file'])}, "
               f"{esc(e['loc'])}{' (cited)' if e['id'] in cited else ''}</summary><pre>{body}</pre></details>")
    if not res["retrieved"]:
        ev = "<div class='mute'>No excerpts were retrieved for this answer.</div>"
    n = a["n"]
    return (f"<section class='card' data-n='{n}'><div class='mute'>Answer {n} of 30</div>"
            f"<div class='q'>{esc(a['question'])}</div><div class='final'>{esc(res['final_answer'])}</div>"
            f"<b>Steps</b><ol class='steps'>{steps}</ol><b>Retrieved excerpts</b>{ev}"
            f"<div class='label'><label><input type='radio' name='l{n}' value='supported'> Supported</label>"
            f"<label><input type='radio' name='l{n}' value='not_supported'> Not supported</label>"
            f"<label><input type='radio' name='l{n}' value='cant_tell'> Can't tell</label>"
            f"<textarea placeholder='Note (which step, why)'></textarea></div></section>")


def main():
    answers = pool()
    chosen = pick(answers)
    OUT.mkdir(exist_ok=True)
    (OUT / "sample.json").write_text(json.dumps(
        {"seed": SEED, "pool": len(answers), "flagged_in_pool": sum(a["flagged"] for a in answers),
         "answers": [{k: a[k] for k in ("n", "run", "id", "question", "flagged", "result")} for a in chosen]},
        indent=1, ensure_ascii=False), encoding="utf-8")
    (OUT / "label.html").write_text(PAGE.replace("__CARDS__", "\n".join(card(a) for a in chosen)), encoding="utf-8")
    by_run = collections.Counter(a["run"].split("/")[1].split("__2026")[0] for a in chosen)
    print(f"pool {len(answers)} answers with steps, {sum(a['flagged'] for a in answers)} flagged; "
          f"sample {len(chosen)}: {sum(a['flagged'] for a in chosen)} flagged + "
          f"{sum(not a['flagged'] for a in chosen)} random; {len({a['id'] for a in chosen})} distinct questions")
    print(dict(by_run))
    print(f"-> {(OUT / 'label.html').relative_to(ROOT)}")


if __name__ == "__main__":
    main()
