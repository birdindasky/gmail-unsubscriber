#!/bin/zsh
set -e
cd -- "${0:A:h}"
exec /bin/zsh scripts/launch-v2.sh demo "$@"
