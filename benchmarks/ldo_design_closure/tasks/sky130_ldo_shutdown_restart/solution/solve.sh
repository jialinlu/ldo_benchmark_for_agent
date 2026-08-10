#!/usr/bin/env sh
set -eu
install -m 0644 "${SOLUTION_DIR:-/solution}/circuit.spi" "${APP_DIR:-/app}/circuit.spi"
