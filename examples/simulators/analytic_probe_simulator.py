#!/usr/bin/env python3
"""Deterministic JSON simulator used to test the tool protocol without a PDK.

This is not a transistor simulator and must not be used to claim circuit qualification. It evaluates
the first-order RC transfer H(jw)=1/(1+j*w*R*C) for protocol and measurement tests.
"""
from __future__ import annotations

import cmath
import json
import math
import sys


def main() -> int:
    request = json.load(sys.stdin)
    parameters = request.get("parameters", {})
    frequencies = parameters.get("frequency_hz", [])
    resistance = float(parameters["resistance_ohm"])
    capacitance = float(parameters["capacitance_f"])
    points = []
    for frequency in frequencies:
        transfer = 1.0 / (1.0 + 1j * 2.0 * math.pi * float(frequency) * resistance * capacitance)
        points.append({
            "frequency_hz": float(frequency),
            "magnitude": abs(transfer),
            "phase_deg": math.degrees(cmath.phase(transfer)),
        })
    json.dump({
        "schema_version": "1.0",
        "status": "OK",
        "evidence_class": "analytic_fixture",
        "claim_boundary": "First-order RC protocol fixture only; not LDO or PDK qualification.",
        "points": points,
    }, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
