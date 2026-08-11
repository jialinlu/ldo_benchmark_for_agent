#!/usr/bin/env python3
"""Budgeted SKY130/ngspice sizing probe. One invocation consumes one evaluation."""
import argparse, json, os, subprocess, tempfile
from pathlib import Path

p = argparse.ArgumentParser(); p.add_argument("candidate"); args = p.parse_args()
root = Path(__file__).resolve().parent
spec = json.loads((root / "sizing_spec.json").read_text())
ledger = root / "sizing_ledger.json"
entries = json.loads(ledger.read_text()) if ledger.exists() else []
if len(entries) >= 30: raise SystemExit("evaluation budget exhausted")
c = json.loads(Path(args.candidate).read_text())
if set(c) != set(spec["tunable_fields"]): raise SystemExit("candidate fields do not match sizing_spec")
values = dict(spec["defaults"]); values.update(c)
for key in spec["tunable_fields"]:
    lo, hi = spec["bounds"][key]
    if not lo <= float(c[key]) <= hi: raise SystemExit(f"invalid {key}")
pdk = Path(os.environ.get("SKY130_PDK_ROOT", "/opt/sky130"))
model = pdk / "libs.tech/ngspice/sky130.lib.spice"
if not model.exists(): raise SystemExit("INFRA: set SKY130_PDK_ROOT to the sky130A model root")
deck = (root / "sizing_tb.sp").read_text()
for key, value in values.items(): deck = deck.replace("{{" + key + "}}", str(value))
deck = deck.replace("{{model}}", str(model))
with tempfile.TemporaryDirectory(prefix="evoldo-sizer-") as td:
    path = Path(td) / "run.sp"; path.write_text(deck)
    cp = subprocess.run([os.environ.get("NGSPICE", "ngspice"), "-b", str(path)], cwd=td, text=True, capture_output=True)
    text = cp.stdout + "\n" + cp.stderr
    metrics = {}
    for line in text.splitlines():
        clean = line.strip()
        if clean.upper().startswith("EVOLDO_") and "=" in clean:
            k, v = clean.split("=", 1); metrics[k[7:].strip().lower()] = float(v.strip().split()[0])
    if cp.returncode or "vout" not in metrics: raise SystemExit("SIM_FAIL\n" + text[-2000:])
entry = {"candidate": c, "expanded_candidate": values, "metrics": metrics, "objective": spec["objective"]}; entries.append(entry); ledger.write_text(json.dumps(entries, indent=2)+"\n")
print(json.dumps(entry, indent=2))
