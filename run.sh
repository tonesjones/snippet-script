#!/bin/sh
# Create a local Python environment on first use, then run snippet_check.py with all arguments.
set -e
here=$(cd "$(dirname "$0")" && pwd)
if [ ! -x "$here/.venv/bin/python" ]; then
    python3 -m venv "$here/.venv" || { echo 'Could not create .venv; install Python 3.9 or later.' >&2; exit 2; }
    "$here/.venv/bin/python" -m pip install --quiet --disable-pip-version-check -r "$here/requirements.txt" || { rm -rf "$here/.venv"; exit 2; }
fi
exec "$here/.venv/bin/python" "$here/snippet_check.py" "$@"
