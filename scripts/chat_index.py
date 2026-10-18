"""Build chat_index.html: every prompt in a Claude Code chat, one click to its reply.

Reads the chat's transcript (~/.claude/projects/<project>/<session>.jsonl) and
writes a local page: the prompts listed down the side, each linking to a copy
of the replies that followed it. Prompts sent while a turn was running
("queued") are included where they were delivered. Anything that looks like an
API key is redacted. The page is a copy for reading - it does not link into the
chat window itself.

    python3 scripts/chat_index.py [session id]      # default: the largest transcript

Kept in sync by Claude Code hooks (.claude/settings.local.json): on every
prompt you send and every time a reply finishes, the hook passes the current
chat's transcript path on stdin and the page is rebuilt. The open page reloads
itself every 20 seconds, keeping your scroll position.
"""
import datetime as dt
import html
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROJ = pathlib.Path.home() / ".claude" / "projects" / ("-" + str(ROOT).strip("/").replace("/", "-").replace("_", "-"))
OUT = ROOT / "chat_index.html"
KEY = re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_*-]{12,}")
SYSTEM_TAG = re.compile(r"<(system-reminder|ide_opened_file|ide_selection|local-command-[a-z]+|command-[a-z]+)>.*?</\1>", re.S)


def text_of(content):
    if isinstance(content, str):
        return content
    return "\n".join(x.get("text", "") for x in content if isinstance(x, dict) and x.get("type") == "text")


def clean_prompt(t):
    t = SYSTEM_TAG.sub("", t)
    t = re.sub(r"<pasted_content[^>]*>", "[pasted]\n", t).replace("</pasted_content>", "")
    return KEY.sub("sk-<redacted>", t).strip()


def when(ts):
    try:
        return dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().strftime("%d %b %H:%M")
    except (AttributeError, ValueError):
        return ""


def load(path):
    turns = []  # [{"prompt", "when", "replies": [str]}]
    for line in path.open():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = e.get("type")
        if kind == "user" and not e.get("isMeta") and not e.get("isCompactSummary"):
            content = e.get("message", {}).get("content")
            if isinstance(content, list) and any(isinstance(x, dict) and x.get("type") == "tool_result" for x in content):
                continue
            p = clean_prompt(text_of(content))
            if p and not p.startswith(("This session is being continued", "<task-notification", "[SYSTEM NOTIFICATION")):
                turns.append({"prompt": p, "when": when(e.get("timestamp")), "replies": []})
        elif kind == "attachment" and e.get("attachment", {}).get("type") == "queued_command":
            a = e["attachment"]
            raw = a.get("prompt")
            p = clean_prompt(text_of(raw) if not isinstance(raw, str) else raw)
            if p and not p.startswith(("<task-notification", "[SYSTEM NOTIFICATION")):
                turns.append({"prompt": p, "when": when(a.get("timestamp") or e.get("timestamp")),
                              "replies": [], "queued": True})
        elif kind == "assistant" and turns:
            for x in e.get("message", {}).get("content", []):
                if isinstance(x, dict) and x.get("type") == "text" and x.get("text", "").strip():
                    turns[-1]["replies"].append(KEY.sub("sk-<redacted>", x["text"]))
    return [t for t in turns if t["prompt"]]


PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Chat index</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/marked/12.0.2/marked.min.js"></script>
<style>
:root{--bg:#fbfaf7;--side:#f2f0ea;--card:#fff;--ink:#1d1d1b;--mute:#6b6a65;--line:#e4e1d8;--acc:#2f5d8a}
@media (prefers-color-scheme:dark){:root{--bg:#1b1b1a;--side:#222220;--card:#242422;--ink:#ecebe6;--mute:#a3a29b;--line:#3a3935;--acc:#8fb6dd}}
*{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 -apple-system,system-ui,sans-serif;display:flex}
nav{position:sticky;top:0;height:100vh;overflow:auto;width:340px;flex:none;background:var(--side);border-right:1px solid var(--line);padding:16px 12px}
nav h1{font-size:16px;margin:0 0 4px} nav input{width:100%;margin:8px 0 10px;padding:6px 8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink)}
nav a{display:block;padding:6px 8px;border-radius:6px;color:var(--ink);text-decoration:none;font-size:13px;line-height:1.35}
nav a:hover,nav a.on{background:var(--card)} nav .n{color:var(--mute);font-variant-numeric:tabular-nums;margin-right:6px}
nav .q{color:var(--acc);font-size:11px;margin-left:4px}
main{flex:1;min-width:0;padding:24px 28px 80px;max-width:980px}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin:0 0 22px;scroll-margin-top:12px}
.meta{color:var(--mute);font-size:12px} .prompt{white-space:pre-wrap;font-weight:600;margin:6px 0 12px;padding:10px 12px;border-left:3px solid var(--acc);background:var(--bg);border-radius:4px}
.reply{border-top:1px dashed var(--line);padding-top:8px;margin-top:8px;overflow-x:auto}
.reply table{border-collapse:collapse;margin:8px 0} .reply td,.reply th{border:1px solid var(--line);padding:4px 8px;font-size:13px}
.reply pre{white-space:pre-wrap;background:var(--bg);padding:8px;border-radius:6px;font-size:12.5px} .reply code{font-size:12.5px}
.top{font-size:12px} a{color:var(--acc)}
@media (max-width:760px){body{display:block} nav{position:static;height:auto;width:auto;max-height:45vh}}
</style></head><body>
<nav><h1>Chat index</h1><div class="meta">__COUNT__ prompts &middot; built __BUILT__</div>
<input id="f" placeholder="Filter prompts..."><div id="toc">__TOC__</div></nav>
<main>__BODY__</main>
<script>
// Auto-refresh: rebuilt by a hook on every prompt and reply; reload to pick it up,
// keeping the scroll position (not while you are filtering).
setInterval(() => {
  if (document.getElementById("f").value) return;
  try { sessionStorage.setItem("chat-index-y", window.scrollY); } catch (e) {}
  location.reload();
}, 20000);
document.querySelectorAll(".md").forEach(el => {
  try { if (window.marked) el.innerHTML = marked.parse(el.textContent); } catch (e) {}
});
document.getElementById("f").addEventListener("input", e => {
  const q = e.target.value.toLowerCase();
  document.querySelectorAll("#toc a").forEach(a => a.hidden = q && !a.dataset.t.includes(q));
});
try { const y = sessionStorage.getItem("chat-index-y"); if (y) window.scrollTo(0, +y); } catch (e) {}
</script></body></html>
"""


def from_hook():
    """The transcript path a Claude Code hook passes on stdin, if any."""
    if sys.stdin is None or sys.stdin.isatty():
        return None
    try:
        p = json.loads(sys.stdin.read() or "{}").get("transcript_path")
    except json.JSONDecodeError:
        return None
    return pathlib.Path(p) if p and pathlib.Path(p).exists() else None


def main():
    sid = sys.argv[1] if len(sys.argv) > 1 else None
    files = sorted(PROJ.glob("*.jsonl"), key=lambda p: p.stat().st_size)
    path = PROJ / f"{sid}.jsonl" if sid else (from_hook() or files[-1])
    turns = load(path)
    toc, body = [], []
    for i, t in enumerate(turns, 1):
        short = " ".join(t["prompt"].split())[:90]
        q = '<span class="q">sent mid-turn</span>' if t.get("queued") else ""
        toc.append(f'<a href="#p{i}" data-t="{html.escape(t["prompt"].lower()[:400])}"><span class="n">{i}</span>'
                   f'{html.escape(short)}{q}</a>')
        replies = "".join(f'<div class="reply md">{html.escape(r)}</div>' for r in t["replies"]) \
            or '<div class="reply meta">(no text reply)</div>'
        body.append(f'<section id="p{i}"><div class="meta">#{i} &middot; {t["when"]}'
                    f'{" &middot; sent while a turn was running" if t.get("queued") else ""}'
                    f' &middot; <a class="top" href="#p1">top</a></div>'
                    f'<div class="prompt">{html.escape(t["prompt"])}</div>{replies}</section>')
    page = (PAGE.replace("__COUNT__", str(len(turns))).replace("__BUILT__", dt.datetime.now().strftime("%d %b %H:%M"))
            .replace("__TOC__", "\n".join(toc)).replace("__BODY__", "\n".join(body)))
    OUT.write_text(page, encoding="utf-8")
    print(f"{len(turns)} prompts from {path.name} -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
