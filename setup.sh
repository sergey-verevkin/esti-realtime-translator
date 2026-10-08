#!/bin/zsh
set -eu
cd "${0:A:h}"
if (( $# > 1 )) || { (( $# == 1 )) && [[ "$1" != "--english" ]]; }; then
    print -u2 'Usage: ./setup.sh [--english]'
    exit 2
fi
for dependency in uv swift git curl ffmpeg; do
    command -v "$dependency" >/dev/null || { print -u2 "Missing dependency: $dependency"; exit 1; }
done
[[ "$(uname -s)" == Darwin && "$(uname -m)" == arm64 ]] || { print -u2 'This setup currently supports Apple Silicon macOS.'; exit 1; }
./capture-transcription/setup.sh
./capture-transcription/setup-zipformer-large.sh
if (( $# == 1 )); then ./capture-transcription/setup-zipformer-en.sh; fi
./translation/setup.sh
./overlay/build-app.sh
