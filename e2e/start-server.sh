#!/bin/sh
# Serves a copy of site/ with a deterministic data.json for the browser tests.
set -e
cd "$(dirname "$0")/.."
DIR=.wrangler/e2e-site
rm -rf "$DIR" && mkdir -p .wrangler && cp -R site "$DIR"
node e2e/fixture.mjs "$DIR/data.json"
exec npx wrangler dev --port 8788 --assets "$DIR" --var ALLOW_UNAUTHENTICATED:true
