#!/bin/zsh
# Install a local macOS launcher. Models and Python environments stay in the workspace.
set -eu
cd "${0:A:h}"
swift build -c release
exec /usr/bin/python3 package_app.py "$@"
