#!/bin/zsh
set -eu
cd "${0:A:h}"
uv sync --python 3.11 --extra whisper
.venv/bin/python download_zipformer.py
exec .venv/bin/python download_vad.py
