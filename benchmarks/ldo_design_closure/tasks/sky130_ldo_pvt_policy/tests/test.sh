#!/usr/bin/env sh
set -eu
mkdir -p /logs/verifier
if [ ! -s /app/circuit.spi ]; then
  printf '%s
' '{"reward":0,"tests_total":1,"tests_passed":0,"partial":0.0,"outcome":"missing_candidate"}' > /logs/verifier/reward.json
  exit 0
fi
PYTHONPATH=/app/evoldo_tests python3 /app/evoldo_tests/verify.py
