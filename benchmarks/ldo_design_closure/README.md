# Public-PDK LDO design-closure track

This track adds **six real transistor-level closure tasks** to the reasoning benchmark. Each task starts
from an independently authored SKY130 LDO netlist containing one controlled fault. An agent must edit the
DUT and earn fresh ngspice evidence; prose alone cannot pass.

## The six tasks

| Task | Injected closure problem | Hard evidence |
|---|---|---|
| `sky130_ldo_operating_point` | under-sized pass device | nominal VOUT, VFB and supply current |
| `sky130_ldo_cold_start` | starved self-bias | ramp from zero with no `.ic`/`.nodeset` |
| `sky130_ldo_shutdown_restart` | disconnected EN bias shunt | physical off state and subsequent restart |
| `sky130_ldo_load_transient` | poor compensation regime | 0.1–1 mA step, dip, peak and settled points |
| `sky130_ldo_line_load_regulation` | weak low-line drive | four 1.65/1.8 V and 0.1/1 mA points |
| `sky130_ldo_pvt_policy` | marginal slow-corner sizing | TT/FF/SS temperature points plus DUT source scan |

The included development reference is deliberately modest: 1.8 V input, approximately 1.5 V output,
0.1–1 mA load and 10 pF load capacitance. It is a benchmark fixture, not a silicon claim or a competitive
LDO result. Resistors/capacitors are ideal passive abstractions; independent, behavioral and controlled
sources, ideal switches, `.ic`, and `.nodeset` are forbidden **inside the DUT**. Testbench stimuli remain
ideal by definition.

## Fetch the pinned public models

PDK model files are not vendored. Fetch and hash-check the model tree referenced by
`public_pdk_manifest.json`:

```bash
python tools/fetch_public_pdk.py --provider sky130
```

The default checkout is under `.runtime/`, which Git ignores. The source commit binds the whole tree and
the entry-file SHA-256 catches accidental path/revision mistakes.

## Run a task or the suite

```bash
evoldo-bench closure-list

# Run a task's intentionally faulty starter; a nonzero exit is expected until repaired.
evoldo-bench closure-run \
  --pdk-root .runtime/public_pdks/opensource-analog-circuits \
  --task-id sky130_ldo_operating_point \
  --output runs/closure-starter

# Qualify one candidate against all six gates.
evoldo-bench closure-run \
  --pdk-root .runtime/public_pdks/opensource-analog-circuits \
  --candidate benchmarks/ldo_design_closure/dev_reference/sky130_reference/ldo.sp \
  --output runs/closure-reference
```

Every run writes rendered decks, raw logs and `result.json` under the selected output directory. The result
distinguishes `INFRA_FAIL`, `MEAS_FAIL`, `POLICY_FAIL`, and `CIRCUIT_FAIL`; simulator absence or model-load
failure must not be reported as a circuit conclusion.

## Model assessment

- **SKY130:** directly usable with stock ngspice. This is the executable and CI-qualified track.
- **ASAP7:** the public mirror contains HSPICE BSIM-CMG cards and an ngspice/OSDI conversion. The committed
  OSDI object is Linux x86-64 specific, so execution requires a compatible OSDI-enabled ngspice or the
  provided container build. It is recorded in the manifest and fetch tool, but is not counted among the
  six qualified tasks until portability, license-notice placement and CI execution are closed.

No circuit/netlist from the model-source repository is copied or adapted. Only its pinned public model
tree is consumed at runtime.
