#!/bin/zsh
# Build the public pages and deploy them to Vercel (project anchor-study):
#
#   scripts/deploy_site.sh
#
# The app's address (APP_URL) comes from the environment, else from .env's
# WORKOS_REDIRECT_URI minus /callback - the Mac's Funnel address.
#
# Deploys from a copy outside this git repo: Vercel blocks a deploy that carries
# git details whose commit author is not on the Vercel account (seen 18 Oct 2026:
# "the commit author doesn't have permission to create deployments").
set -euo pipefail
cd "${0:A:h}/.."

if [ -z "${APP_URL:-}" ]; then
  APP_URL=$(sed -nE 's/^[[:space:]]*WORKOS_REDIRECT_URI[[:space:]]*=[[:space:]]*(https:[^[:space:]]+)\/callback[[:space:]]*$/\1/p' .env | head -1)
fi
export APP_URL
.venv/bin/python scripts/build_site.py

if [ ! -f site/.vercel/project.json ]; then
  echo "site/ is not linked to the Vercel project yet: cd site && npx --yes vercel@62.2.0 link --yes --project anchor-study"
  exit 1
fi
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cp -R site/. "$TMP"/
find "$TMP" -maxdepth 1 -name ".env*" -delete   # the CLI's token file: never uploaded
(cd "$TMP" && npx --yes vercel@62.2.0 deploy --prod --yes)
