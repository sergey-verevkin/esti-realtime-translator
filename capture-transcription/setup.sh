#!/bin/zsh
set -eu
cd "${0:A:h}"
revision=56ac954369a09318e46b88a6eec33c2d2b0d32a3
if [[ ! -d vendor/audiotee/.git ]]; then
    mkdir -p vendor
    git clone https://github.com/makeusabrew/audiotee.git vendor/audiotee
fi
git -C vendor/audiotee checkout --detach "$revision"
uv sync --python 3.11
swift build -c release \
    -Xlinker -sectcreate -Xlinker __TEXT -Xlinker __info_plist -Xlinker "$PWD/Info.plist"
codesign --force --sign - --identifier local.realtime-translation.capture .build/release/realtime-capture

.venv/bin/python download_vad.py
