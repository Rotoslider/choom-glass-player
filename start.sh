#!/bin/sh
# Start the travel glass (Linux or a Mac): the server, the mic and Chrome on the Portrait. Ctrl+C stops it.
cd "$(dirname "$0")"
if [ -x .venv/bin/python ]; then exec .venv/bin/python player/launch.py; else exec python3 player/launch.py; fi
