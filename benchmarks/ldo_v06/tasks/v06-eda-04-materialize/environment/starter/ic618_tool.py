#!/usr/bin/env python3
"""IC618 bridge with fresh per-invocation remote scratch directories.

The bridge never touches the user's existing libraries. The SSH target and IC618
installation are supplied by the benchmark operator, not embedded in the task.
"""
import argparse, hashlib, json, os, shlex, subprocess, time
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument("command", choices=["preflight","run"]); p.add_argument("--skill", default="solution.il"); a=p.parse_args()
target=os.environ.get("EVOLDO_EDA_SSH_TARGET"); virtuoso=os.environ.get("EVOLDO_IC618_VIRTUOSO", "/opt/eda/cadence/IC618/tools/dfII/bin/virtuoso")
if not target: raise SystemExit("INFRA: EVOLDO_EDA_SSH_TARGET is required")
if a.command=="preflight":
    cp=subprocess.run(["ssh",target,"test","-x",virtuoso],capture_output=True,text=True); print(json.dumps({"status":"OK" if cp.returncode==0 else "INFRA_FAIL","returncode":cp.returncode})); raise SystemExit(cp.returncode)
skill=Path(a.skill); data=skill.read_bytes(); tag=hashlib.sha256(data+str(time.time_ns()).encode()).hexdigest()[:16]; remote=f"/tmp/evoldo-{tag}"
subprocess.run(["ssh",target,"mkdir","-m","700",remote],check=True)
try:
    subprocess.run(["scp","-q",str(skill),f"{target}:{remote}/run.il"],check=True)
    cmd=f"cd {shlex.quote(remote)} || exit 97; timeout 240 {shlex.quote(virtuoso)} -nograph -nocdsinit -replay run.il -log virtuoso.log; rc=$?; printf '%s\\n' $rc > rc.txt"
    subprocess.run(["ssh",target,cmd],check=False)
    cp=subprocess.run(["ssh",target,"cat",f"{remote}/rc.txt",f"{remote}/evoldo_result.json"],capture_output=True,text=True)
    lines=cp.stdout.splitlines(); ok=cp.returncode==0 and lines[:1]==["0"] and len(lines)>1
    if ok:
        Path("eda_result.json").write_text(lines[1]+"\n")
    else:
        logs=subprocess.run(["ssh",target,"cat",f"{remote}/virtuoso.log"],capture_output=True,text=True)
        Path("eda_remote.log").write_text(logs.stdout+logs.stderr)
    Path("eda_ledger.json").write_text(json.dumps({"scratch_id":tag,"skill_sha256":hashlib.sha256(data).hexdigest(),"remote_returncode":lines[0] if lines else None,"status":"OK" if ok else "EXEC_FAIL"},indent=2)+"\n")
    print(cp.stdout); raise SystemExit(0 if ok else 2)
finally:
    subprocess.run(["ssh",target,"rm","-rf",remote],check=False)
