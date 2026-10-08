#!/bin/zsh
set -eu
cd "${0:A:h}"
swift build -c release >&2
exec .build/release/realtime-overlay "${PWD:h}" "$@"
