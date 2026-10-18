"""The public pages, put together the same way for the Mac server (app.py) and
the static build for Vercel (scripts/build_site.py).

Each page in static/ carries <!--#head-->, <!--#nav--> and <!--#footer-->
markers that the shared pieces in static/partials/ replace; the page's own tab
in the header is marked as the current page.
"""
import pathlib

STATIC = pathlib.Path(__file__).resolve().parent / "static"
PUBLIC = {"landing": None, "uploads": "/uploads", "connectors": "/connectors", "pricing": "/pricing", "faq": "/faq"}


def render(name, app_url=""):
    """One public page as HTML. app_url: where the app lives when the pages are
    served from elsewhere (Vercel); empty when the app serves them itself."""
    html = (STATIC / f"{name}.html").read_text(encoding="utf-8")
    for part in ("head", "nav", "footer"):
        html = html.replace(f"<!--#{part}-->", (STATIC / "partials" / f"{part}.html").read_text(encoding="utf-8"))
    path = PUBLIC.get(name)
    if path:
        html = html.replace(f'class="plain" href="{path}"', f'class="plain" href="{path}" aria-current="page"', 1)
    if app_url:
        html = html.replace('href="/app"', f'href="{app_url}/app"').replace("`/app?q=", f"`{app_url}/app?q=")
    return html
