#!/bin/zsh
set -eu
cd "${0:A:h}"
exec ./run.sh --capture "$@"
