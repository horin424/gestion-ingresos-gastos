#!/usr/bin/env sh
# Inicia el sistema en macOS o Linux.
set -e
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
    echo "Preparando el sistema por primera vez..."
    python3 -m venv .venv
fi
.venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements.txt
exec .venv/bin/python app.py
