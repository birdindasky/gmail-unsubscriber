#!/bin/zsh
set -eu
cd -- "${0:A:h:h}"
mode=${1:-}
shift || true
if [[ "$mode" != live && "$mode" != demo ]]; then
  print -u2 "Invalid mode [mode_invalid]. Use a project .command launcher."
  exit 1
fi
# Never fall back to a legacy environment or system Python.
if [[ -x .venv-v2-p5/bin/python ]]; then
  runtime=.venv-v2-p5/bin/python
elif [[ -x .venv-v2/bin/python ]]; then
  runtime=.venv-v2/bin/python
else
  print -u2 "Environment missing [environment_missing]. See docs/V2_USAGE.md to rebuild."
  exit 1
fi
if ! "$runtime" -c 'import sys; assert sys.version_info >= (3, 10); import google.auth, google_auth_oauthlib, google_auth_httplib2, googleapiclient.discovery, requests, dkim' >/dev/null 2>&1; then
  print -u2 "Environment incomplete [environment_incomplete]. See docs/V2_USAGE.md to rebuild."
  exit 1
fi
print "Lightmail mode: $mode | runtime: $runtime"
exec "$runtime" app.py "--$mode" "$@"
