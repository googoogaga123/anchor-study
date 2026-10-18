#!/bin/zsh
# Serve the Anchor app from this Mac to the internet (owner's choice, 18 Oct 2026: the
# front end on Vercel, the app on this Mac).
#
#   scripts/serve_public.sh          start the app, then share it publicly
#   Ctrl+C                           stop both
#
# Sharing, in order of preference:
#   Tailscale Funnel   a fixed https://<this-mac>.<tailnet>.ts.net address, free. On a Mac,
#                      Funnel needs the open-source command-line Tailscale (brew install
#                      tailscale; sudo brew services start tailscale; tailscale up), with
#                      MagicDNS, HTTPS and Funnel turned on for the tailnet.
#   Cloudflare tunnel  a quick tunnel: a new https://<random>.trycloudflare.com each start,
#                      so WorkOS's redirect and the Vercel build's APP_URL must follow it.
#
# With Funnel the app is told its address (PUBLIC_ORIGIN), and WorkOS's return address
# defaults to <address>/callback - add that under Redirects in the WorkOS dashboard, and
# rebuild the Vercel front end with APP_URL=<address> so its buttons reach the app.
#
# Refuses to start unless the login service is set up (with the development sign-in on,
# anyone could sign in as anyone - the owner included), and refuses to share a port that
# something else - an older server - is already using.
set -euo pipefail
cd "${0:A:h}/.."

.venv/bin/python - <<'EOF'
import sys
sys.path.insert(0, "web")
import auth
problems = []
if not auth.LOGIN_SERVICE:
    problems.append("WORKOS_API_KEY and WORKOS_CLIENT_ID are not set (.env)")
if auth.DEV_LOGIN:
    problems.append("DEV_LOGIN is on - anyone could sign in as anyone")
if not auth._env("SESSION_SECRET"):
    problems.append("SESSION_SECRET is not set (.env) - everyone would be signed out at each restart")
if problems:
    sys.exit("Not starting a public site:\n  - " + "\n  - ".join(problems))
EOF

PORT=${PORT:-8000}
if lsof -ti:"$PORT" >/dev/null 2>&1; then
  echo "Port $PORT is already in use (an older Anchor server?). Stop it first, so only this protected one is shared."
  exit 1
fi

TS=$(command -v tailscale || true)
if [ -n "$TS" ]; then
  DNS=$("$TS" status --json 2>/dev/null | .venv/bin/python -c "import json, sys; print(json.load(sys.stdin)['Self']['DNSName'].rstrip('.'))" 2>/dev/null || true)
  if [ -z "$DNS" ]; then
    echo "Tailscale is installed but not connected: run 'sudo brew services start tailscale' and 'tailscale up' first."
    exit 1
  fi
  export PUBLIC_ORIGIN="https://$DNS"
  export WORKOS_REDIRECT_URI="${WORKOS_REDIRECT_URI:-$PUBLIC_ORIGIN/callback}"
elif ! command -v cloudflared >/dev/null; then
  echo "Install a way to share the app first: brew install tailscale (recommended, fixed address) or brew install cloudflared"
  exit 1
fi

# The real database (PGDATABASE, default ailodge) - not the recording one.
unset WEB_PGDATABASE
caffeinate -i .venv/bin/uvicorn web.app:app --port "$PORT" --proxy-headers --forwarded-allow-ips 127.0.0.1 &
SITE=$!
trap 'kill $SITE 2>/dev/null' EXIT INT TERM

# Share it only once it answers, with the login service on and the dev sign-in off.
for i in {1..60}; do
  CFG=$(curl -s "http://localhost:$PORT/api/auth-config" || true)
  [ -n "$CFG" ] && break
  sleep 1
done
echo "$CFG" | .venv/bin/python -c "
import json, sys
c = json.loads(sys.stdin.read() or '{}')
if not c.get('login_service') or c.get('dev_login'):
    sys.exit('The app did not come up protected (login service on, dev sign-in off): not sharing it.')
"

if [ -n "$TS" ]; then
  "$TS" funnel --bg "localhost:$PORT"
  trap '"$TS" funnel --bg "localhost:$PORT" off 2>/dev/null; kill $SITE 2>/dev/null' EXIT INT TERM
  echo
  echo "The app is public at $PUBLIC_ORIGIN (Tailscale Funnel)."
  echo "  WorkOS dashboard, Redirects:  $WORKOS_REDIRECT_URI"
  echo "  Vercel front end:             APP_URL=$PUBLIC_ORIGIN .venv/bin/python scripts/build_site.py, then redeploy"
  echo "Ctrl+C stops the app and the sharing."
  wait $SITE
else
  echo "App on http://localhost:$PORT. Starting a Cloudflare quick tunnel; its https address appears below."
  cloudflared tunnel --url "http://localhost:$PORT"
fi
