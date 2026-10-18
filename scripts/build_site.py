"""Build the public pages as a static site for Vercel (owner's choice, 18 Oct 2026:
the front end on Vercel, the app on the owner's Mac).

    APP_URL=https://<mac>.<tailnet>.ts.net .venv/bin/python scripts/build_site.py
    npx vercel@62.2.0 deploy site --prod

Output: site/ (gitignored) - the five public pages put together exactly as the
Mac server serves them (web/pages.py), the files they load (styles, scripts,
the saved sample answers and their picture, the demo clips) and vercel.json.
Nothing in site/ calls the app's API: the try-it box shows saved answers.

Every "Sign in", "Try Anchor" and "Start free trial" link goes to APP_URL/app.
Without APP_URL (the app not online yet) they go to /soon, a page that says
so instead of a dead link.
"""
import json
import os
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "web"))
import pages  # noqa: E402

OUT = ROOT / "site"
COPY = ["anchor.css", "site.css", "site.js", "answer.js", "samples.json", "samples", "demos"]

SOON = """<!doctype html>
<html lang="en"><head>
<!--#head-->
<title>Anchor opens soon</title>
<meta name="robots" content="noindex">
</head>
<body>
<!--#nav-->
<header class="page-hero" style="min-height:62vh"><div class="inner">
  <span class="badge soon">Opening soon</span>
  <h1>Anchor isn't open yet.</h1>
  <p class="sub">We're getting sign-up ready. Until then, try the saved answers on the front page, or watch the demos.</p>
  <div class="actions"><a class="btn" href="/">Back to the front page</a><a class="btn ghost" href="/faq">Read the FAQ</a></div>
</div></header>
<!--#footer-->
</body></html>
"""

VERCEL = {
    "cleanUrls": True,
    "trailingSlash": False,
    "headers": [
        {"source": "/(.*)", "headers": [
            {"key": "X-Content-Type-Options", "value": "nosniff"},
            {"key": "Referrer-Policy", "value": "strict-origin-when-cross-origin"},
            {"key": "X-Frame-Options", "value": "SAMEORIGIN"}]},
        {"source": "/static/demos/(.*)", "headers": [{"key": "Cache-Control", "value": "public, max-age=86400"}]},
    ],
}


def main():
    app_url = (os.environ.get("APP_URL") or "").strip().rstrip("/")
    if app_url and not app_url.startswith("https://"):
        sys.exit("APP_URL must be the app's https address, e.g. https://my-mac.tailnet-name.ts.net")
    if OUT.exists():  # start clean, but keep .vercel/ (the link to the Vercel project)
        for old in OUT.iterdir():
            if old.name != ".vercel":
                shutil.rmtree(old) if old.is_dir() else old.unlink()
    (OUT / "static").mkdir(parents=True)
    for name in pages.PUBLIC:
        html = pages.render(name, app_url)
        if not app_url:  # no app online yet: its links say so instead of failing
            html = html.replace('href="/app"', 'href="/soon"').replace("`/app?q=${encodeURIComponent(q)}`", "`/soon`")
        (OUT / ("index.html" if name == "landing" else f"{name}.html")).write_text(html, encoding="utf-8")
    if not app_url:
        soon = SOON
        for part in ("head", "nav", "footer"):
            soon = soon.replace(f"<!--#{part}-->", (pages.STATIC / "partials" / f"{part}.html").read_text(encoding="utf-8"))
        (OUT / "soon.html").write_text(soon.replace('href="/app"', 'href="/soon"'), encoding="utf-8")
    for item in COPY:
        src = pages.STATIC / item
        (shutil.copytree if src.is_dir() else shutil.copy2)(src, OUT / "static" / item)
    (OUT / "vercel.json").write_text(json.dumps(VERCEL, indent=2) + "\n", encoding="utf-8")
    # The Vercel CLI keeps a token in .env.local when linking: never upload it.
    (OUT / ".vercelignore").write_text(".env*\n.gitignore\n", encoding="utf-8")
    left = [p.name for p in OUT.glob("*.html") if "/app" in p.read_text(encoding="utf-8").replace(f"{app_url}/app", "")]
    if left:
        sys.exit(f"links to /app left unrewritten in: {left}")
    size = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
    print(f"site/: {len(list(OUT.glob('*.html')))} pages, {size / 2**20:.1f} MB; app links -> "
          f"{app_url + '/app' if app_url else '/soon (no APP_URL yet)'}")


if __name__ == "__main__":
    main()
