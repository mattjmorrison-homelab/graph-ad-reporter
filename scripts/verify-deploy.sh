#!/bin/sh
set -eu

URL="https://graph-ad-reporter.morrisons.site/version"

# Argo CD Image Updater only polls the registry every ~2 minutes, plus sync
# and rollout time on top of that — so this needs a budget comfortably
# longer than one poll cycle, not just a few seconds of slack.
for i in $(seq 1 20); do
  RESPONSE=$(curl -s -w '\n%{http_code}' "$URL")
  STATUS=$(echo "$RESPONSE" | tail -n1)
  BODY=$(echo "$RESPONSE" | sed '$d')
  ACTUAL=$(echo "$BODY" | jq -r '.commit_sha' 2>/dev/null || echo "<unparseable: $BODY>")
  echo "attempt $i: HTTP $STATUS, commit_sha='$ACTUAL', expected='$CI_COMMIT_SHA'"

  if [ "$ACTUAL" = "$CI_COMMIT_SHA" ]; then
    echo "PASS: deployed commit_sha matches $CI_COMMIT_SHA"
    exit 0
  fi
  sleep 15
done

echo "FAIL: deployed commit_sha never matched $CI_COMMIT_SHA after 20 attempts"
exit 1
