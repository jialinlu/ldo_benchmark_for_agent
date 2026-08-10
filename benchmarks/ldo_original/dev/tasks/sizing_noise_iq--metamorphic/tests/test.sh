#!/usr/bin/env sh
set -eu
mkdir -p /logs/verifier
if [ ! -s /app/answer.json ]; then
  printf '%s
' '{"reward":0,"tests_total":8,"tests_passed":0,"partial":0.0,"outcome":"missing_answer"}' > /logs/verifier/reward.json
  exit 0
fi
python3 /app/evoldo_tests/verify.py
