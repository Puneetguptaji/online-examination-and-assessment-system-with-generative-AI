#!/usr/bin/env bash
# Mac/Linux convenience runner. MySQL setup scripts must be run first in Workbench.
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
. .venv/bin/activate
python -m pip install -r requirements.txt
python seed_demo.py
python app.py
