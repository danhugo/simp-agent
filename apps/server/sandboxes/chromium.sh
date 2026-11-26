#!/bin/sh
# /usr/local/bin/chromium, ahead of /usr/bin on PATH: how officecli's screenshots start chromium in the agent's sandbox.
# The container is the isolation (no user namespaces for chromium's own sandbox: --no-sandbox), /dev/shm is small, and
# the root filesystem is read-only, so each run gets a throwaway profile in /tmp (stale ones from killed runs go first).
find /tmp -maxdepth 1 -name '.chromium-*' -mmin +10 -exec rm -rf {} + 2>/dev/null
d=$(mktemp -d /tmp/.chromium-XXXXXX)
/usr/bin/chromium --no-sandbox --disable-dev-shm-usage --disable-gpu --user-data-dir="$d" "$@"
code=$?
rm -rf "$d"
exit $code
