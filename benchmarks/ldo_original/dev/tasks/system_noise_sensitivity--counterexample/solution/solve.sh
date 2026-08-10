#!/usr/bin/env sh
set -eu
install -m 0644 "${SOLUTION_DIR:-/solution}/answer.json" "${APP_DIR:-/app}/answer.json"
