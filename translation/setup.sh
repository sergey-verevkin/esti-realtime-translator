#!/bin/zsh
set -eu
cd "${0:A:h}"
uv sync --python 3.11
exec .venv/bin/python download_model.py
