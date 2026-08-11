#!/usr/bin/env python3
"""Generate the public EvoLDO v0.6.1 task set in Analog Arena demo-task layout.

The generated packages intentionally keep the agent-visible starter, verifier, and
reference solution in separate directories.  Do not hand-edit generated packages;
change this file and regenerate them.
"""
from __future__ import annotations

import hashlib
import json
import random
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "benchmarks" / "ldo_v06"
TASKS = OUT / "tasks"
ORACLES = OUT / "dev_reference" / "oracles"
BASE_IMAGE = "python:3.12-slim"
SKY130_IMAGE = "ghcr.io/arcadia-1/circuit-bench-sky130-ngspice@sha256:bd5c425675eb99fc1a2c3bca10b63a871c457613767e2c6984d6c207b3160500"
BENCHMARK_VERSION = "0.6.1"

TRACK_README = """# EvoLDO v0.6.1 task store

This generated directory contains 69 public-development task packages: 48 pure-model core cases, eight
metamorphic companions, six paired SKY130/ngspice sizing treatments, six IC618/SKILL primary tasks, and
one EDA companion. Every task uses the `task_examples` layout (`task.toml`, `instruction.md`, separate
`environment/starter`, `tests`, and `solution`). Regenerate with `python3 tools/generate_v06_tasks.py`.

`registry.jsonl` hashes the complete package and `dev_reference/oracles` is never copied into an agent
runtime bundle. Tool-task answer grading is only semantic; an official tool score additionally requires
`evoldo-bench verify-live`, whose infrastructure-invalid result must be retried rather than scored zero.
Pure reasoning tasks use six dimensions with ordered-choice partial credit and evidence-set F1 scoring.
See `docs/BENCHMARK_V06.md` for the protocol and score definitions.
"""


SUITES = {
    "structure": [
        ("feedback-polarity", "Feedback polarity from a DC perturbation", "The error-amplifier output drives a PMOS pass gate. Raising VOUT through an ideal test source makes VFB rise and makes the amplifier output rise.", ["VREF=0.8 V", "VOUT perturbation: +10 mV", "VCTRL response: +31 mV", "PMOS current falls when VCTRL rises"], "The closed loop is negative feedback", "The two sign inversions are the error comparison and PMOS common-source action", "Keep the polarity and verify loop gain with the loop opened at a high-impedance point", "This establishes small-signal polarity, not stability margin"),
        ("dropout-path", "Identify the dropout-limiting path", "At maximum load the PMOS gate is already 42 mV above ground and the error amplifier cannot pull it lower. VOUT misses regulation only when VIN approaches VOUT.", ["VIN=1.10 V", "target VOUT=1.00 V", "ILOAD=8 mA", "VCTRL=42 mV", "EA low output limit=35 mV"], "Pass-device headroom is the active limit", "The saturated error amplifier has exhausted gate overdrive before the divider or reference limits", "Increase effective pass width or improve low-side gate drive, then recheck stability", "A wider pass device can change gate pole and transient behavior"),
        ("loop-break", "Choose a valid loop-break location", "The LDO uses a resistive divider into a MOS differential pair. Candidate breakpoints are the divider midpoint, the pass gate, and the reference source.", ["divider Thevenin resistance=330 kohm", "pass-gate DC bias must be preserved", "reference has finite AC impedance", "Middlebrook injection fixture is available"], "Break at the pass-gate drive with a bias-preserving injection fixture", "That location preserves the operating point while exposing the full forward and return paths", "Insert the calibrated injection source and verify return-ratio sign at low frequency", "A raw AC voltage source without bias restoration changes the circuit being measured"),
        ("capless-poles", "Map dominant poles in a capless LDO", "A capless LDO has a high-impedance error-amplifier node, a buffered pass gate, and a load-dependent output pole.", ["EA node Rout=4 Mohm, C=0.7 pF", "pass gate C=18 pF behind 2 kohm buffer", "Cload=80 pF", "Rload spans 200 ohm to 20 kohm"], "The output pole moves most strongly with load while the EA node is the nominal dominant pole", "Rload directly changes the output time constant and can cause pole crossing", "Check loop gain at both load extremes before resizing compensation", "Nominal-load pole ordering is not sufficient for a capless stability claim"),
        ("startup-loop", "Separate startup path from regulation loop", "The bias reference is self-biased and admits a zero-current equilibrium. A weak startup transistor senses the bias node and turns off after current builds.", ["zero-current OP converges", "forced 5 nA pulse starts the circuit", "startup FET current falls below 20 nA after 8 us", "regulation loop remains closed"], "The added device is an escape path, not part of the steady-state regulation loop", "It destabilizes the unwanted equilibrium and becomes negligible at the desired equilibrium", "Size it from worst-corner startup time and verify its residual leakage", "Successful nominal transient does not prove escape from every initial condition"),
        ("architecture-capstone", "Optimize an existing two-stage LDO architecture", "An existing PMOS LDO meets DC accuracy but has 29 degrees phase margin. The pass gate pole is close to the non-dominant amplifier pole; quiescent current has 15 percent margin.", ["UGF=2.6 MHz", "PM=29 deg", "pass-gate pole=1.9 MHz", "EA second pole=3.4 MHz", "IQ=85 uA, limit=100 uA"], "The first optimization target is separation of the pass-gate pole from UGF", "Two nearby non-dominant poles consume phase before crossover", "Use part of the IQ margin to lower gate-drive resistance, then retune compensation", "Do not replace the architecture before checking a local pole-separation fix"),
    ],
    "trend": [
        ("pass-width", "Predict pass-width trends", "Only PMOS pass width is doubled while length, load current, bias, and external capacitance are fixed.", ["initial dropout=145 mV", "initial gate capacitance=12 pF", "driver Rout=8 kohm", "same DC load"], "Dropout tends to improve while the gate pole tends to move lower", "More width lowers on-resistance but raises gate capacitance", "Sweep width and remeasure both dropout and phase margin", "The two metrics need not improve together"),
        ("esr-zero", "Track the output-capacitor ESR zero", "COUT is fixed and ESR changes from 20 milliohm to 400 milliohm.", ["COUT=1 uF", "ESR old=20 mohm", "ESR new=400 mohm", "UGF about 900 kHz"], "The ESR zero moves to a lower frequency", "The zero frequency is inversely proportional to ESR times capacitance", "Overlay loop gain and output impedance for both ESR values", "A lower zero helps only if its placement is useful relative to crossover"),
        ("load-gm", "Infer load-dependent loop movement", "Load current rises by 20 times in a PMOS LDO whose pass device remains saturated and whose bias currents are fixed.", ["COUT fixed", "Rload falls by 20x", "pass gm rises approximately 4.1x", "EA gain nearly fixed"], "The output pole rises substantially and loop gain can also rise", "Lower load resistance and higher pass gm both alter the output-node pole/loop gain", "Check light-load and heavy-load crossover instead of extrapolating one corner", "The direction of phase margin still depends on other pole locations"),
        ("bias-current", "Trade error-amplifier bias current", "The differential-pair bias is doubled with device geometry and compensation capacitor fixed.", ["gm rises 1.42x", "output resistance falls 0.73x", "Ccomp fixed", "IQ budget tightens"], "Unity-gain frequency tends to rise but DC gain need not rise", "gm increases while intrinsic gain is limited by the simultaneous resistance reduction", "Measure gain, UGF, PM, slew, and IQ after the change", "Bias-current scaling is not a free gain improvement"),
        ("temperature-dropout", "Explain a non-monotonic temperature trend", "Dropout improves from -40 C to 27 C but worsens at 125 C under a fixed 5 mA load.", ["mobility decreases with temperature", "threshold magnitude also decreases", "gate drive is not rail-limited at -40 C", "it becomes rail-limited at 125 C"], "Competing threshold and mobility trends change which mechanism dominates", "Threshold reduction initially helps overdrive, then mobility loss and gate-drive saturation dominate", "Plot pass overdrive and gm at all three temperatures", "A single linear temperature coefficient is not justified"),
        ("trend-capstone", "Select a monotonic-safe optimization", "An existing LDO narrowly fails heavy-load dropout and light-load PM. Three proposed single-knob changes are wider pass FET, more Ccomp, or lower driver resistance.", ["heavy dropout miss=18 mV", "light-load PM miss=9 deg", "pass gate pole below UGF at light load", "IQ margin=12 uA"], "Lowering driver resistance is the best first coupled intervention", "It moves the gate pole upward and improves gate charging without directly increasing pass capacitance", "Spend bounded bias current in the driver and remeasure both failing corners", "No single-knob monotonic argument replaces the paired-corner verification"),
    ],
    "diagnosis": [
        ("ringing", "Diagnose load-step ringing", "A load release produces decaying 1.8 MHz ringing. Loop-gain analysis shows 24 degrees PM and crossover at 1.7 MHz.", ["ringing absent with loop opened", "COUT/ESR verified", "supply clean", "ring frequency near crossover"], "Insufficient closed-loop phase margin is the primary cause", "The oscillatory mode aligns with crossover and disappears when feedback is opened", "Localize the phase loss by probing pass-gate and output poles", "The transient alone does not identify which internal pole caused the phase loss"),
        ("cold-start", "Diagnose cold-start failure", "The nominal transient starts, but SS/-40 C with all nodes initialized to zero remains at zero bias indefinitely.", ["reference ramp is present", "supply reaches 1.8 V", "5 nA bias-node pulse recovers", "no overcurrent"], "The bias network is trapped in an unwanted zero-current equilibrium", "An external seed escapes the state while supply and reference are healthy", "Add or strengthen a corner-robust startup path and test initial-condition variants", "Increasing the regulation-loop bandwidth is not the direct remedy"),
        ("dropout-fail", "Diagnose a heavy-load DC miss", "At 10 mA VOUT is 65 mV low, the divider ratio is correct, VREF is correct, and the PMOS gate is at its minimum reachable voltage.", ["EA output saturated low", "pass VSD=92 mV", "pass device in linear region", "light-load regulation correct"], "The pass path lacks available conductance/headroom", "The loop commands maximum drive but the pass device cannot supply the demanded current", "Quantify required pass conductance at the worst VIN and resize pass/driver", "Changing divider ratio would mask rather than solve the dropout limit"),
        ("iq-excess", "Find excess ground current", "Measured no-load supply current is 170 uA versus an 80 uA target. Branch current accounting is available.", ["reference=12 uA", "EA=38 uA", "driver=25 uA", "feedback divider=90 uA", "startup leakage=5 uA"], "The feedback divider dominates the excess", "Its 90 uA branch is larger than all other avoidable contributions", "Increase divider resistance while checking noise, leakage error, and settling", "Blindly reducing EA bias cannot recover the full current excess"),
        ("undershoot", "Disambiguate load-step undershoot", "A 0.1-to-8 mA step causes 140 mV undershoot without sustained ringing. Gate voltage slews slowly for 900 ns before loop recovery.", ["PM=61 deg", "output capacitor nominal", "pass gate slew=0.35 V/us", "driver current clips"], "Pass-gate slew/current limit dominates the first excursion", "Adequate PM and clipped driver current distinguish slew limitation from linear instability", "Increase transient gate-drive capability and verify IQ/overshoot", "Small-signal loop gain alone cannot predict the large-signal first excursion"),
        ("diagnosis-capstone", "Prioritize fixes from a mixed failure signature", "An existing LDO fails startup at SS/cold and rings at FF/light load; dropout and IQ pass.", ["startup pulse rescues SS/cold", "FF/light PM=22 deg", "startup device off in regulation", "pass size has 30 percent dropout margin"], "There are two independent root causes requiring separate local fixes", "The rescue experiment identifies a startup equilibrium issue while loop gain independently identifies a fast-corner stability issue", "Fix startup injection and compensation separately, then run a full regression", "A larger pass device is unsupported and could worsen the stability failure"),
    ],
    "sizing": [
        ("pass-first", "First-pass PMOS width sizing", "Use the supplied SKY130 tt operating points to choose the smallest characterized pass width meeting 6 mA at 120 mV headroom with 20 percent current margin.", ["W=80 um: 5.5 mA", "W=100 um: 6.9 mA", "W=120 um: 8.2 mA", "required with margin=7.2 mA"], "Choose 120 um", "The 100 um point misses the explicit current margin while 120 um is the smallest passing sample", "Use 120 um as a seed and verify SS/hot plus gate-pole movement", "Interpolation outside the characterized corner cannot replace PVT verification"),
        ("divider", "Size a feedback divider", "Choose equal-order E96 values for VOUT=1.2 V from VREF=0.8 V while keeping divider current at or below 3 uA.", ["VOUT/VREF=1+Rtop/Rbot", "ratio Rtop/Rbot=0.5", "minimum total resistance=400 kohm", "candidate pairs: 200k/402k, 249k/499k, 100k/200k"], "Choose 249 kohm over 499 kohm", "It closely realizes the 0.5 ratio and its 748 kohm total keeps current below 3 uA", "Verify bias/leakage error using the actual feedback input current", "Ratio accuracy alone is insufficient when divider current is constrained"),
        ("comp-cap", "Select compensation capacitance", "SKY130/ngspice loop sweeps for an unchanged LDO report the following worst-load results.", ["Ccomp=2 pF: PM=31 deg, UGF=3.7 MHz", "Ccomp=5 pF: PM=54 deg, UGF=1.9 MHz", "Ccomp=8 pF: PM=67 deg, UGF=1.1 MHz", "target PM>=60 deg, UGF>=1.0 MHz"], "Choose 8 pF", "It is the smallest characterized capacitance satisfying both PM and bandwidth constraints", "Verify load transient and all PVT corners at 8 pF", "A larger capacitor is not automatically better because bandwidth and slew remain constrained"),
        ("bias-budget", "Allocate a quiescent-current budget", "An LDO has 30 uA available beyond fixed reference and divider current. Choose the characterized EA/driver allocation meeting gain and slew.", ["EA/driver 20/10 uA: gain 58 dB, slew 0.18 V/us", "15/15: gain 55 dB, slew 0.31 V/us", "10/20: gain 49 dB, slew 0.43 V/us", "targets gain>=52 dB, slew>=0.30 V/us"], "Choose 15 uA EA and 15 uA driver", "It is the only characterized allocation meeting both gain and slew", "Carry that split into PVT and no-load IQ verification", "The allocation is conditional on the fixed-current assumptions"),
        ("driver-ratio", "Co-size driver and pass device", "Three SKY130/ngspice candidates are compared at identical load and COUT.", ["A Wpass=100 um, Rdrv=8k: dropout=128 mV, PM=46 deg", "B Wpass=140 um, Rdrv=8k: dropout=94 mV, PM=35 deg", "C Wpass=140 um, Rdrv=3k: dropout=95 mV, PM=63 deg", "targets dropout<=100 mV, PM>=55 deg"], "Choose candidate C", "The wider pass FET fixes dropout only when the stronger driver also restores the gate-pole margin", "Use C as the next candidate and verify IQ plus load-step peaks", "Sizing the pass device in isolation would select an unstable candidate"),
        ("sizing-capstone", "Select the robust local sizing move", "A frozen PMOS-LDO architecture has a four-knob SKY130 sweep over pass width, input-pair width, driver resistance, and Ccomp.", ["P1 120/40/5k/5p: dropout 108 mV, PM 52 deg, IQ 72 uA", "P2 160/40/3k/8p: dropout 82 mV, PM 64 deg, IQ 86 uA", "P3 200/80/3k/8p: dropout 70 mV, PM 61 deg, IQ 112 uA", "limits dropout<=90 mV, PM>=60 deg, IQ<=100 uA"], "Choose P2", "P2 satisfies every hard constraint and avoids P3's unnecessary IQ violation", "Center a finer PVT sweep around P2 rather than changing architecture", "This is a characterized local optimum, not proof of a global optimum"),
    ],
    "migration": [
        ("gm-id", "Migrate a bias point by gm over ID", "A 180 nm input pair is moved to SKY130 at the same current. The old design uses gm/ID=14 V^-1; copied W/L produces gm/ID=9 V^-1 in the target PDK.", ["target noise requires gm unchanged", "current fixed", "target inversion curve available", "minimum L need not be used"], "Resize from the target-PDK gm/ID curve rather than geometric scaling", "Equal geometric ratios do not preserve inversion level or intrinsic gain across PDKs", "Choose target L for gain, then W for gm/ID=14 at the fixed current", "The migrated dimensions remain model- and corner-dependent"),
        ("headroom", "Audit headroom after a supply migration", "An LDO moves from 3.3 V thick-oxide devices to 1.8 V core devices while retaining a two-stack bias branch and PMOS pass architecture.", ["target VOUT=1.5 V", "worst VIN=1.65 V", "two-stack branch needs 0.42 V", "EA output high swing needs 0.25 V from VDD"], "The copied bias/output stack violates the new voltage budget", "The available rail-to-rail headroom is smaller than the retained stacked-device requirements", "Redesign the bias/output stage for low-voltage swing before transistor scaling", "Reliability limits and device flavor must also be re-qualified"),
        ("model-semantics", "Map device-model semantics", "A source netlist uses four-terminal MOS symbols and explicit body ties; the target PDK offers wrapper subcircuits plus primitive model names.", ["wrapper pins are D G S B", "primitive statistical parameters differ", "body must not float", "target LVS uses wrapper names"], "Use the foundry wrapper with verified pin order and explicit body connection", "Model-name substitution without interface mapping can silently swap pins or bypass required parasitics", "Build and simulate a one-device pin/model smoke test before full migration", "A converged operating point is not evidence of correct model semantics"),
        ("cap-density", "Migrate an on-chip compensation capacitor", "The source uses a 4 pF MIM capacitor. The target MIM option has different density and a 2.5 V maximum terminal rating.", ["source density=1.5 fF/um2", "target density=2.0 fF/um2", "target bias across cap=1.2 V", "fringe parasitic changes by 18 percent"], "Resize physical area from target density and re-extract parasitics", "Capacitance value and parasitic network are process-specific even when voltage reliability passes", "Start near 2000 um2, then use extracted C and reclose the loop", "Schematic nominal capacitance alone does not preserve compensation"),
        ("leakage-startup", "Requalify startup under leakage scaling", "A weak startup FET copied into a lower-leakage process no longer starts at cold, while simply widening it raises hot standby current above spec.", ["cold injection current=0.3 nA", "needed escape current=2 nA", "hot leakage after 10x width=160 nA", "standby limit=50 nA"], "The startup topology needs a better on/off discriminator, not uniform width scaling", "One geometry knob cannot satisfy opposite cold-start and hot-leakage requirements", "Use state-dependent startup sensing and verify both equilibria across corners", "Nominal startup time cannot stand in for leakage-corner qualification"),
        ("migration-capstone", "Plan a low-risk LDO port", "An existing architecture is ported to SKY130. DC regulation passes after geometric scaling, but gain falls 12 dB, startup fails SS/cold, and the pass gate violates no reliability rule.", ["divider ratio correct", "pass headroom passes", "EA ro is lower", "startup injection is 6x weaker at SS/cold"], "Retain the architecture but separately retarget intrinsic gain and startup strength", "The evidence isolates target-PDK gain and equilibrium changes rather than a pass-device or ratio failure", "Retune EA length/cascoding within headroom and redesign startup, then regress", "Passing nominal DC after scaling does not validate the migration"),
    ],
    "system_impact": [
        ("psrr-ripple", "Translate supply ripple through PSRR", "A downstream block tolerates 1 mV rms at 10 kHz. The upstream converter produces 25 mV rms and the LDO PSRR is measured at the same frequency.", ["PSRR=32 dB at 10 kHz", "linear attenuation=39.8", "reference noise excluded", "load fixed"], "The residual supply-ripple contribution is about 0.63 mV rms", "Divide the input ripple by the linear PSRR ratio", "Reserve the remaining noise budget for reference and device noise", "PSRR at 10 kHz does not bound ripple at other harmonics"),
        ("load-spectrum", "Match load spectrum to loop response", "A digital load draws 20 ns current edges at a 5 MHz repetition rate. The LDO UGF is 600 kHz and COUT is 1 uF.", ["edge spectral content far above UGF", "package inductance=1.2 nH", "local C effective at high frequency", "average load within DC limit"], "The local capacitor/package network controls the initial droop", "The feedback loop is too slow to respond during the edge", "Analyze PDN impedance and high-frequency capacitor placement before raising loop bandwidth", "DC load regulation does not predict the edge droop"),
        ("reference-noise", "Budget reference-noise gain", "The LDO is configured for VOUT/VREF=1.5. Integrated reference noise is 18 uV rms and error-amplifier input noise is 11 uV rms over the same band.", ["noise gain=1.5", "sources uncorrelated", "pass/output noise neglected", "same integration band"], "The combined output contribution is about 31.8 uV rms", "Scale reference noise by 1.5 and combine it root-sum-square with amplified input noise", "Add remaining device and resistor noise before comparing to system limit", "Linear addition would overestimate uncorrelated noise"),
        ("package-l", "Recognize package-induced ringing", "Post-layout board simulation adds bond-wire inductance and produces 12 MHz ringing absent in the on-chip extracted simulation.", ["loop UGF=0.9 MHz", "bond wire=2 nH", "COUT effective=88 nF", "ring frequency near LC estimate"], "The package-output LC resonance is the leading cause", "The new mode appears only with package inductance and lies far above loop crossover", "Damp the PDN resonance using capacitor ESR or a damping network", "Retuning low-frequency compensation is not the first supported action"),
        ("sequencing", "Assess enable and rail sequencing", "VREF is present before VIN. EN is asserted while VIN ramps slowly; VOUT briefly overshoots above its final value.", ["EA saturates during low VIN", "pass gate held at maximum drive", "reference already final", "overshoot disappears when EN follows VIN-good"], "Prebias-induced integrator windup during supply ramp causes the overshoot", "The active reference commands regulation before adequate pass/headroom exists", "Gate enable with VIN-good or add anti-windup/soft-start", "Nominal fixed-supply startup does not cover this sequencing case"),
        ("system-capstone", "Choose a system-facing LDO optimization", "The LDO passes standalone specs, but the SoC fails due to 5 MHz load-edge droop and 100 kHz converter ripple. IQ margin is small.", ["UGF=700 kHz", "PSRR@100k=18 dB", "edge droop dominated by package impedance", "converter ripple contribution=4 mV"], "Use separate PDN and feed-forward/ripple remedies rather than only raising bias", "The two failures occupy different frequency ranges and have different measured paths", "Improve local decoupling/damping and target 100 kHz PSRR, then co-simulate", "A single higher-bandwidth loop is neither sufficient nor IQ-neutral"),
    ],
    "design_closure": [
        ("measurement", "Reject an invalid stability measurement", "A reported 78 degree phase margin was obtained by inserting a zero-volt AC source in series with the pass gate, which changed the DC gate voltage by 210 mV.", ["original VOUT=1.20 V", "modified VOUT=0.93 V", "pass region changed", "AC plot otherwise smooth"], "The phase-margin result is invalid because the fixture changed the operating point", "Return-ratio measurements require bias preservation", "Repeat with a bias-preserving loop injection and compare operating points", "A plausible Bode plot does not rescue a changed circuit"),
        ("corner-set", "Select closure corners", "An LDO must regulate from -40 C to 125 C, across process and VIN, at no load and 10 mA.", ["dropout worsens at SS/hot/low VIN/heavy load", "stability worsens at FF/cold/light load", "startup worsens at SS/cold", "leakage worsens at FF/hot"], "Use metric-specific worst corners plus a justified cross-product regression", "Different failure mechanisms peak at different process/load/temperature combinations", "Freeze named corner groups for dropout, stability, startup, and leakage", "Only TT and one global worst corner cannot establish closure"),
        ("regression", "Detect a sizing regression", "Revision B improves dropout by 28 mV but reduces light-load PM from 58 to 39 degrees after pass width is increased.", ["same simulator/model", "same test fixtures", "gate capacitance +44 percent", "driver unchanged"], "Revision B is not closed because it traded one pass for a stability failure", "The larger pass gate moved an internal pole while the driver remained fixed", "Co-size the driver/compensation and rerun the frozen regression", "Reporting only the improved metric is invalid cherry-picking"),
        ("spec-interaction", "Close coupled transient specifications", "Increasing Ccomp fixes PM but causes startup and load-step settling to exceed limits.", ["PM 44 to 66 deg", "startup 14 to 31 us, limit 25 us", "settling 5 to 11 us, limit 8 us", "IQ unchanged"], "The compensation-only change is infeasible under the full spec set", "The same lower bandwidth that improves phase margin slows both required transients", "Search a driver-plus-compensation tradeoff and score all hard constraints", "Stability closure cannot be declared while transient gates fail"),
        ("yield", "Interpret Monte Carlo yield", "A 200-run mismatch simulation gives 99.0 percent DC pass but only 93.5 percent startup pass, with failures clustered at low startup-device beta.", ["DC failures=2", "startup failures=13", "target each metric>=99 percent", "failure clustering reproducible"], "Startup yield is the blocking metric", "Aggregate DC yield cannot hide a separate hard-gate failure mode", "Retarget startup margin and rerun enough samples with the same seed policy", "The observed 93.5 percent is an estimate, not a guaranteed population yield"),
        ("closure-capstone", "Stop or continue architecture optimization", "A frozen existing architecture passes 46 of 48 gates. The remaining failures are SS/hot dropout by 9 mV and FF/light PM by 4 degrees; both respond to a driver/pass co-size without violating IQ in a local sweep.", ["candidate C fixes both misses", "IQ margin after C=6 uA", "startup unchanged", "no reliability violations"], "Continue local sizing; an architecture change is not yet justified", "The misses are small, mechanistically understood, and jointly corrected by a verified local move", "Promote candidate C to full fresh-evidence regression before declaring closure", "Local sweep success is not a substitute for the frozen 48-gate rerun"),
    ],
    "architecture_choice": [
        ("pmos-nmos", "Choose PMOS or NMOS pass device", "A 1.8 V input LDO must produce 1.5 V without a charge pump and with low dropout.", ["available headroom=300 mV", "NMOS source follower needs gate above VOUT", "PMOS gate can be driven toward ground", "load=5 mA"], "Choose a PMOS pass device", "An NMOS follower lacks gate overdrive without a boosted rail", "Use PMOS and budget its larger gate capacitance in compensation", "An NMOS could become viable if a charge pump were allowed"),
        ("ea-topology", "Choose an error-amplifier topology", "The design needs 60 dB DC gain at 1.2 V supply, 25 uA EA current, and near-rail output swing to drive a PMOS gate.", ["telescopic stack lacks swing", "folded cascode meets gain but costs branch current", "two-stage OTA meets swing/current in characterization", "compensation area available"], "Choose the characterized two-stage OTA", "It satisfies low-voltage swing and current constraints while providing a path to required gain", "Use Miller compensation and verify the pass-gate interaction", "The choice is conditional on the supplied characterization, not a universal ranking"),
        ("capless", "Decide whether to use a capless architecture", "The product forbids an external capacitor, permits 100 pF on-chip load, and spans 1 uA to 20 mA load.", ["output pole moves four decades", "IQ target=50 uA", "fast load edges", "area permits 30 pF internal compensation"], "Use a capless architecture only with explicit multi-loop/load-range compensation", "The moving output pole and wide load range make a conventional fixed dominant-output-pole assumption invalid", "Prototype buffered gate/internal compensation and test both load extremes", "Removing COUT is an architectural constraint, not merely a capacitor value change"),
        ("feedforward", "Select a PSRR feed-forward path", "A PMOS LDO meets low-frequency PSRR but has a 2 MHz supply-ripple peak caused by pass-gate feedthrough.", ["loop UGF=250 kHz", "peak persists with higher EA gain", "gate feedthrough phase measured", "extra 4 uA allowed"], "Add a frequency-shaped feed-forward cancellation path", "The ripple lies above loop authority and follows the direct pass-gate path", "Tune cancellation phase/amplitude around 2 MHz and verify noise/stability", "Broadband cancellation is sensitive to PVT and must not be assumed"),
        ("replica", "Evaluate replica bias", "Load regulation is limited by pass-device gm variation over 1000x load. A replica branch could track pass current but adds 12 uA.", ["IQ limit leaves 15 uA", "gm variation causes 18 mV error", "replica predicts gm within 8 percent", "startup interaction manageable"], "A scaled replica bias is justified by the measured load-dependent error", "It directly senses the varying pass operating point within the available IQ budget", "Add a scaled replica and verify matching, startup, and light-load IQ", "The benefit depends on replica correlation across mismatch"),
        ("architecture-capstone", "Choose between local sizing and architecture change", "An existing PMOS LDO misses dropout by 12 mV and PM by 6 degrees. Local co-sizing closes both with 8 uA IQ cost; a proposed NMOS architecture needs a charge pump and new verification.", ["IQ margin=14 uA", "local candidate passes sampled PVT", "charge-pump ripple unknown", "schedule permits one regression cycle"], "Retain the PMOS architecture and apply the local co-size", "The bounded local change fits IQ and schedule while the replacement introduces unverified blocks", "Run the complete regression on the local candidate and keep architecture change as contingency", "Sampled PVT evidence is promising but not final closure"),
    ],
}


# Each pure-model case receives one scenario-local discriminator. Unlike q1-q4,
# these alternatives all use the same circuit quantities and differ by a missed
# constraint, an incomplete calculation, or an unsafe overclaim. Credits encode
# an expert-authored ordered response model: full, plausible-but-incomplete,
# weak, and contradicted. The map is also reused by metamorphic companions.
CHALLENGES = {
    ("structure", "feedback-polarity"): ("Which follow-up most strongly separates correct DC polarity from adequate closed-loop stability?", [
        ("Preserve the operating point and measure signed return ratio across frequency", 1.0),
        ("Run a closed-loop load step and inspect ringing", 0.55),
        ("Repeat only the +10 mV DC perturbation", 0.2),
        ("Accept stability because the DC feedback sign is negative", 0.0)]),
    ("structure", "dropout-path"): ("How much additional low-going EA output swing remains between VCTRL and its characterized limit?", [
        ("7 mV", 1.0), ("35 mV", 0.55), ("42 mV", 0.2), ("100 mV", 0.0)]),
    ("structure", "loop-break"): ("Which acceptance check is required before trusting the injected return ratio?", [
        ("The DC operating point is unchanged and the low-frequency return-ratio sign is consistent", 1.0),
        ("VOUT alone is unchanged after insertion", 0.55),
        ("The Bode plot is smooth", 0.2),
        ("The reported phase margin is positive", 0.0)]),
    ("structure", "capless-poles"): ("Using the supplied RC values, which approximate light-load pole ordering is supported?", [
        ("EA 57 kHz, output 100 kHz, buffered gate 4.4 MHz", 1.0),
        ("Output 100 kHz, EA 57 kHz, buffered gate 4.4 MHz", 0.55),
        ("EA 57 kHz, buffered gate 100 kHz, output 4.4 MHz", 0.2),
        ("All three poles are load invariant", 0.0)]),
    ("structure", "startup-loop"): ("Which evidence pair best supports negligible steady-state startup-path influence?", [
        ("Startup current falls below 20 nA and the regulation loop remains closed", 1.0),
        ("A forced pulse starts the circuit and VOUT regulates", 0.55),
        ("The zero-current operating point converges", 0.2),
        ("The nominal supply reaches its final value", 0.0)]),
    ("structure", "architecture-capstone"): ("What is the largest stated current headroom available for a bounded driver-strength experiment?", [
        ("15 uA", 1.0), ("12.75 uA", 0.55), ("85 uA", 0.2), ("100 uA", 0.0)]),

    ("trend", "pass-width"): ("If pass-gate capacitance doubled and driver resistance stayed fixed, what first-order gate-pole change follows?", [
        ("It moves to about one half its former frequency", 1.0),
        ("It moves lower, but no exact factor can be claimed if other capacitances matter", 0.55),
        ("It is unchanged because load current is fixed", 0.2),
        ("It doubles in frequency", 0.0)]),
    ("trend", "esr-zero"): ("What ESR-zero movement follows from the supplied endpoints?", [
        ("About 7.96 MHz to 0.398 MHz, crossing below the 0.9 MHz UGF", 1.0),
        ("About 8 MHz to 0.4 MHz, without checking its relation to UGF", 0.55),
        ("About 0.4 MHz to 8 MHz", 0.2),
        ("The zero is fixed because COUT is fixed", 0.0)]),
    ("trend", "load-gm"): ("Under an Rload-dominated output pole model, what can and cannot be inferred?", [
        ("The output pole rises about 20x; full loop-gain and PM trends still need the other impedances and poles", 1.0),
        ("The output pole rises about 20x and PM must improve", 0.55),
        ("Loop gain rises exactly 4.1x", 0.2),
        ("Every loop metric is unchanged", 0.0)]),
    ("trend", "bias-current"): ("What first-order DC-gain factor follows from the supplied gm and Rout changes?", [
        ("About 1.04x, so nearly unchanged despite higher UGF tendency", 1.0),
        ("About 1.42x because only gm matters", 0.55),
        ("About 0.73x because only Rout matters", 0.2),
        ("About 2.0x", 0.0)]),
    ("trend", "temperature-dropout"): ("Which new observation would most weaken the claimed hot rail-limiting mechanism?", [
        ("At 125 C the EA output retains ample swing and pass overdrive while dropout still worsens", 1.0),
        ("Mobility falls at 125 C", 0.55),
        ("Threshold magnitude falls from -40 C to 27 C", 0.2),
        ("Dropout is measured at the same load", 0.0)]),
    ("trend", "trend-capstone"): ("When is the lower-driver-resistance proposal actually admissible?", [
        ("Its added current fits the 12 uA budget and the same candidate closes both dropout and light-load PM", 1.0),
        ("It improves gate charging at the nominal corner", 0.55),
        ("It uses exactly all 12 uA without a fresh IQ measurement", 0.2),
        ("It may be accepted from the monotonic gate-pole argument alone", 0.0)]),

    ("diagnosis", "ringing"): ("Which counter-observation would most directly weaken the low-phase-margin diagnosis?", [
        ("The same 1.8 MHz ringing persists with the feedback loop opened", 1.0),
        ("The ringing frequency shifts slightly with load", 0.55),
        ("COUT tolerance is nonzero", 0.2),
        ("The closed-loop crossover remains near 1.7 MHz", 0.0)]),
    ("diagnosis", "cold-start"): ("Which result would most directly weaken the zero-current-equilibrium diagnosis?", [
        ("A bias-node seed fails to recover operation despite a healthy supply and reference", 1.0),
        ("The required seed grows at cold", 0.55),
        ("Nominal startup remains successful", 0.2),
        ("The zero-state operating point still converges", 0.0)]),
    ("diagnosis", "dropout-fail"): ("What pass-path conductance is required to support 10 mA at the observed 92 mV VSD, ignoring margin?", [
        ("About 109 mS", 1.0), ("About 83 mS", 0.55), ("About 10.9 mS", 0.2), ("About 920 mS", 0.0)]),
    ("diagnosis", "iq-excess"): ("What does the branch-current sum imply about a divider-only repair?", [
        ("The non-divider branches already total 80 uA, so reducing the divider alone leaves no target margin", 1.0),
        ("Reducing the divider from 90 to 10 uA exactly closes the target", 0.55),
        ("Reducing EA current alone can recover the full 90 uA excess", 0.2),
        ("The listed branches do not sum to the measured 170 uA", 0.0)]),
    ("diagnosis", "undershoot"): ("What approximate pass-gate excursion is implied by 0.35 V/us for 900 ns?", [
        ("0.315 V", 1.0), ("0.39 V", 0.55), ("0.035 V", 0.2), ("315 V", 0.0)]),
    ("diagnosis", "diagnosis-capstone"): ("What is the minimum regression structure needed after the two local fixes?", [
        ("Separate startup/initial-condition coverage at SS-cold and loop/transient coverage at FF-light, followed by the full frozen regression", 1.0),
        ("One combined nominal startup transient after both changes", 0.55),
        ("Only a dropout sweep because pass width has margin", 0.2),
        ("No regression because each mechanism was already identified", 0.0)]),

    ("sizing", "pass-first"): ("What characterized current margins do the 100 um and 120 um samples have relative to 7.2 mA?", [
        ("-0.3 mA and +1.0 mA", 1.0), ("-0.3 mA and +0.8 mA", 0.55), ("+0.9 mA and +2.2 mA", 0.2), ("Both have positive margin", 0.0)]),
    ("sizing", "divider"): ("Approximately what VOUT and divider current result from 249 kohm over 499 kohm at VREF=0.8 V?", [
        ("1.1992 V and 1.60 uA", 1.0), ("1.2000 V and 1.60 uA", 0.55), ("1.1992 V and 2.40 uA", 0.2), ("0.800 V and 1.60 uA", 0.0)]),
    ("sizing", "comp-cap"): ("What margins does the 8 pF point have to the two stated limits?", [
        ("+7 deg PM and +0.1 MHz UGF", 1.0), ("+7 deg PM with no bandwidth margin", 0.55), ("+13 deg PM and +1.1 MHz UGF", 0.2), ("It misses the bandwidth limit", 0.0)]),
    ("sizing", "bias-budget"): ("What margins does the 15/15 uA allocation have to gain and slew targets?", [
        ("+3 dB and +0.01 V/us", 1.0), ("+3 dB and +0.31 V/us", 0.55), ("+1 dB and +0.01 V/us", 0.2), ("It has no positive margin on either metric", 0.0)]),
    ("sizing", "driver-ratio"): ("Which constraint margins distinguish candidates B and C?", [
        ("B passes dropout but misses PM by 20 deg; C has 5 mV dropout and 8 deg PM margin", 1.0),
        ("B and C both pass dropout, but only C passes PM", 0.55),
        ("B misses dropout and C only passes dropout", 0.2),
        ("Both candidates satisfy both hard constraints", 0.0)]),
    ("sizing", "sizing-capstone"): ("What hard-constraint margins characterize P2, and what blocks P3?", [
        ("P2 has 8 mV, 4 deg, and 14 uA margin; P3 exceeds IQ by 12 uA", 1.0),
        ("P2 passes all gates and P3 fails IQ", 0.55),
        ("P2 has 18 mV dropout margin and P3 fails PM", 0.2),
        ("P3 is preferred because it has the lowest dropout", 0.0)]),

    ("migration", "gm-id"): ("How far below the target inversion-efficiency point is copied W/L?", [
        ("5 V^-1, or about 35.7 percent below target", 1.0), ("5 V^-1 without a normalized comparison", 0.55), ("9 V^-1 below target", 0.2), ("The points are equivalent at fixed current", 0.0)]),
    ("migration", "headroom"): ("Compare worst-case VIN-VOUT headroom with the retained two-stack requirement.", [
        ("150 mV is available versus 420 mV required, a 270 mV deficit", 1.0),
        ("150 mV is available, so the stack is marginal", 0.55),
        ("300 mV is available versus 420 mV required", 0.2),
        ("The stack has 270 mV positive margin", 0.0)]),
    ("migration", "model-semantics"): ("Which smoke-test result is sufficient to proceed to full-netlist migration?", [
        ("Verified D/G/S/B mapping, explicit body behavior, wrapper use, and expected one-device OP", 1.0),
        ("A converged one-device OP with the wrapper name", 0.55),
        ("Matching primitive model names only", 0.2),
        ("A converged full LDO operating point without pin audit", 0.0)]),
    ("migration", "cap-density"): ("What first-pass target area and voltage margin follow from the supplied target MIM data?", [
        ("About 2000 um2 and 1.3 V, before extracted-parasitic closure", 1.0),
        ("About 2000 um2 and adequate voltage margin", 0.55),
        ("About 2667 um2 and 1.3 V", 0.2),
        ("About 2000 um2 proves compensation is preserved", 0.0)]),
    ("migration", "leakage-startup"): ("Under linear width scaling, what conflict appears when cold injection is raised from 0.3 nA to 2 nA?", [
        ("About 6.7x width is needed and projected hot leakage is about 107 nA, above 50 nA", 1.0),
        ("About 6.7x width is needed, without evaluating hot leakage", 0.55),
        ("About 2x width is sufficient and remains below 50 nA", 0.2),
        ("A 10x width satisfies both corners", 0.0)]),
    ("migration", "migration-capstone"): ("Which evidence-to-fix mapping is supported?", [
        ("Lower EA ro maps to gain retargeting; 6x weaker startup injection maps to startup redesign", 1.0),
        ("Both failures map to increasing pass width", 0.55),
        ("Correct divider ratio maps to changing the feedback ratio", 0.2),
        ("Nominal DC pass proves no migration work remains", 0.0)]),

    ("system_impact", "psrr-ripple"): ("After the 0.63 mV ripple contribution, what independent RMS budget remains under a 1 mV total limit?", [
        ("About 0.78 mV rms", 1.0), ("About 0.37 mV rms by linear subtraction", 0.55), ("About 0.63 mV rms", 0.2), ("No budget remains", 0.0)]),
    ("system_impact", "load-spectrum"): ("How does a 20 ns edge compare with the reciprocal of 600 kHz UGF?", [
        ("It is about 83x shorter, so the initial response is outside loop authority", 1.0),
        ("It is much shorter than the loop timescale", 0.55),
        ("It is about 8.3x shorter", 0.2),
        ("It is slower than the loop", 0.0)]),
    ("system_impact", "reference-noise"): ("Which intermediate calculation supports the stated combined output noise?", [
        ("27 uV and 16.5 uV contributions combined by RSS give about 31.6 uV", 1.0),
        ("Scale the 18 uV reference term and combine sources by RSS", 0.55),
        ("Add 18 uV and 11 uV linearly to get 29 uV", 0.2),
        ("Only the 18 uV reference term reaches the output", 0.0)]),
    ("system_impact", "package-l"): ("What resonance estimate follows from 2 nH and 88 nF?", [
        ("About 12 MHz, consistent with the observed new mode", 1.0), ("About 12 MHz without relating it to the observed mode", 0.55), ("About 0.9 MHz", 0.2), ("About 120 kHz", 0.0)]),
    ("system_impact", "sequencing"): ("Which controlled intervention most strongly isolates the sequencing mechanism?", [
        ("Hold EN low until VIN-good while preserving the final reference and load conditions", 1.0),
        ("Reduce the reference amplitude during the same early-EN ramp", 0.55),
        ("Increase COUT and change the ramp simultaneously", 0.2),
        ("Repeat only fixed-supply nominal startup", 0.0)]),
    ("system_impact", "system-capstone"): ("What input ripple corresponds to a 4 mV contribution through 18 dB PSRR at 100 kHz?", [
        ("About 31.8 mV", 1.0), ("About 22 mV", 0.55), ("About 7.9 mV", 0.2), ("About 72 mV", 0.0)]),

    ("design_closure", "measurement"): ("How large is the fixture-induced VOUT operating-point error?", [
        ("270 mV, invalidating comparison with the original loop", 1.0), ("270 mV, but the smooth Bode plot remains usable", 0.55), ("210 mV", 0.2), ("No DC error because the inserted source is zero volts", 0.0)]),
    ("design_closure", "corner-set"): ("Which policy best avoids both missed mechanisms and an unjustified single global-worst corner?", [
        ("Named metric-specific stress corners plus a frozen justified cross-product regression", 1.0),
        ("One worst corner per metric with no cross-checks", 0.55),
        ("TT plus SS-hot-heavy only", 0.2),
        ("Average every metric across all corners", 0.0)]),
    ("design_closure", "regression"): ("What quantified trade did revision B make?", [
        ("It gained 28 mV dropout but lost 19 deg light-load PM while gate capacitance rose 44 percent", 1.0),
        ("It improved dropout and reduced PM", 0.55),
        ("It lost 28 deg PM and gained 19 mV dropout", 0.2),
        ("It improved both hard metrics", 0.0)]),
    ("design_closure", "spec-interaction"): ("By how much do the modified startup and settling times exceed their limits?", [
        ("6 us and 3 us", 1.0), ("6 us and 11 us", 0.55), ("17 us and 6 us", 0.2), ("Neither exceeds its limit", 0.0)]),
    ("design_closure", "yield"): ("For 200 samples and a 99 percent startup target, how far is the observed failure count from the largest passing count?", [
        ("At most 2 failures pass; 13 failures are 11 too many", 1.0),
        ("13 failures correspond to 93.5 percent pass", 0.55),
        ("At most 1 failure passes; 13 are 12 too many", 0.2),
        ("13 failures meet the 99 percent target", 0.0)]),
    ("design_closure", "closure-capstone"): ("What evidence is still missing before candidate C can be called closed?", [
        ("A fresh rerun of all 48 frozen gates with candidate C", 1.0),
        ("Only the two formerly failing gates", 0.55),
        ("A nominal operating point because the local sweep already passed", 0.2),
        ("No evidence; 46 of 48 is sufficient", 0.0)]),

    ("architecture_choice", "pmos-nmos"): ("Which single requirement change most directly reopens the NMOS-pass option?", [
        ("Allow a verified boosted gate rail or charge pump", 1.0),
        ("Increase the output target while keeping VIN fixed", 0.55),
        ("Reduce PMOS gate capacitance", 0.2),
        ("Require still lower dropout without a boosted rail", 0.0)]),
    ("architecture_choice", "ea-topology"): ("Which verification most directly addresses the selected two-stage OTA's new architecture-specific risk?", [
        ("Close Miller and pass-gate pole interactions across load and PVT", 1.0),
        ("Confirm nominal DC gain only", 0.55),
        ("Recheck telescopic output swing", 0.2),
        ("Assume compensation area guarantees stability", 0.0)]),
    ("architecture_choice", "capless"): ("What load-range ratio drives the need for explicit moving-pole coverage?", [
        ("20,000 to 1", 1.0), ("Four decades, without quantifying the endpoint ratio", 0.55), ("1,000 to 1", 0.2), ("20 to 1", 0.0)]),
    ("architecture_choice", "feedforward"): ("How far above loop UGF is the 2 MHz ripple peak?", [
        ("8x, supporting a path outside ordinary loop authority", 1.0), ("8x, without identifying the direct path", 0.55), ("4x", 0.2), ("The peak is below UGF", 0.0)]),
    ("architecture_choice", "replica"): ("How much stated IQ margin remains after adding the 12 uA replica branch?", [
        ("3 uA, so mismatch and light-load overhead remain tight gates", 1.0), ("3 uA", 0.55), ("12 uA", 0.2), ("27 uA", 0.0)]),
    ("architecture_choice", "architecture-capstone"): ("What IQ margin remains after the characterized local co-size?", [
        ("6 uA, pending the complete regression", 1.0), ("6 uA, proving final closure", 0.55), ("8 uA", 0.2), ("14 uA", 0.0)]),
}


# Two observations that form the shortest expert-accepted evidence chain for
# the primary conclusion. Values are one-based positions in each canonical
# row's evidence list; metamorphic companions remap them after reversal.
EVIDENCE_PAIRS = {
    ("structure", "feedback-polarity"): (3, 4),
    ("structure", "dropout-path"): (4, 5),
    ("structure", "loop-break"): (2, 4),
    ("structure", "capless-poles"): (1, 4),
    ("structure", "startup-loop"): (1, 2),
    ("structure", "architecture-capstone"): (1, 3),
    ("trend", "pass-width"): (2, 3),
    ("trend", "esr-zero"): (2, 3),
    ("trend", "load-gm"): (2, 3),
    ("trend", "bias-current"): (1, 2),
    ("trend", "temperature-dropout"): (2, 4),
    ("trend", "trend-capstone"): (2, 3),
    ("diagnosis", "ringing"): (1, 4),
    ("diagnosis", "cold-start"): (1, 3),
    ("diagnosis", "dropout-fail"): (1, 3),
    ("diagnosis", "iq-excess"): (2, 4),
    ("diagnosis", "undershoot"): (1, 4),
    ("diagnosis", "diagnosis-capstone"): (1, 2),
    ("sizing", "pass-first"): (3, 4),
    ("sizing", "divider"): (1, 4),
    ("sizing", "comp-cap"): (3, 4),
    ("sizing", "bias-budget"): (2, 4),
    ("sizing", "driver-ratio"): (3, 4),
    ("sizing", "sizing-capstone"): (2, 4),
    ("migration", "gm-id"): (1, 3),
    ("migration", "headroom"): (2, 3),
    ("migration", "model-semantics"): (1, 3),
    ("migration", "cap-density"): (2, 4),
    ("migration", "leakage-startup"): (1, 3),
    ("migration", "migration-capstone"): (3, 4),
    ("system_impact", "psrr-ripple"): (1, 2),
    ("system_impact", "load-spectrum"): (1, 3),
    ("system_impact", "reference-noise"): (1, 2),
    ("system_impact", "package-l"): (2, 4),
    ("system_impact", "sequencing"): (1, 4),
    ("system_impact", "system-capstone"): (3, 4),
    ("design_closure", "measurement"): (2, 3),
    ("design_closure", "corner-set"): (1, 2),
    ("design_closure", "regression"): (3, 4),
    ("design_closure", "spec-interaction"): (2, 3),
    ("design_closure", "yield"): (2, 3),
    ("design_closure", "closure-capstone"): (1, 2),
    ("architecture_choice", "pmos-nmos"): (2, 3),
    ("architecture_choice", "ea-topology"): (1, 3),
    ("architecture_choice", "capless"): (1, 3),
    ("architecture_choice", "feedforward"): (1, 3),
    ("architecture_choice", "replica"): (1, 3),
    ("architecture_choice", "architecture-capstone"): (1, 2),
}


def dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    if path.suffix in {".py", ".sh"}:
        path.chmod(0o755)


def choice_question(task_id: str, qid: str, prompt: str, correct: str, pool: list[str]) -> tuple[dict, str]:
    distractors = [item for item in pool if item != correct][:]
    rng = random.Random(int(hashlib.sha256((task_id + qid).encode()).hexdigest()[:16], 16))
    rng.shuffle(distractors)
    values = [correct] + distractors[:3]
    rng.shuffle(values)
    labels = ["A", "B", "C", "D"]
    options = [{"id": label, "text": value} for label, value in zip(labels, values)]
    answer = next(item["id"] for item in options if item["text"] == correct)
    return {"id": qid, "kind": "single_choice", "prompt": prompt, "options": options}, answer


def credited_choice_question(task_id: str, qid: str, prompt: str,
                             alternatives: list[tuple[str, float]]) -> tuple[dict, str, dict[str, float]]:
    if len(alternatives) != 4 or sum(float(credit) == 1.0 for _, credit in alternatives) != 1:
        raise ValueError("credited choices require four alternatives and exactly one full-credit answer")
    values = list(alternatives)
    rng = random.Random(int(hashlib.sha256((task_id + qid + "credits").encode()).hexdigest()[:16], 16))
    rng.shuffle(values)
    options = [{"id": chr(65 + index), "text": text} for index, (text, _) in enumerate(values)]
    credits = {option["id"]: float(values[index][1]) for index, option in enumerate(options)}
    answer = next(option_id for option_id, credit in credits.items() if credit == 1.0)
    return {"id": qid, "kind": "ordered_choice", "prompt": prompt, "options": options}, answer, credits


def calibrated_reasoning_question(task_id: str, qid: str, prompt: str, correct: str) -> tuple[dict, str, dict[str, float]]:
    near_misses = {
        "q1": [
            ("The evidence points in this direction, but a different mechanism should be prioritized before acting", 0.4),
            ("The opposite design decision is required after ignoring the stated limiting observation", 0.0),
            ("This result alone establishes complete PVT and transient closure", 0.0),
        ],
        "q2": [
            ("The proposed mechanism is consistent with the observations but the supplied intervention does not fully isolate it", 0.55),
            ("Only the numerical correlation is relevant; held conditions and operating region can be ignored", 0.2),
            ("A nominally converged operating point proves the mechanism across all corners", 0.0),
        ],
        "q3": [
            ("Run only the nearest nominal check, then accept the change without the remaining named gates", 0.55),
            ("Change several knobs and the architecture simultaneously before isolating the mechanism", 0.2),
            ("Skip fresh verification because the evidence already proves closure", 0.0),
        ],
        "q4": [
            ("Restrict the claim to the exact sample but omit the stated mechanism-specific limitation", 0.55),
            ("Generalize the conclusion to every PVT, load, and transient condition", 0.2),
            ("No claim boundary is needed after the preferred option is selected", 0.0),
        ],
    }
    return credited_choice_question(task_id, qid, prompt, [(correct, 1.0), *near_misses[qid]])


def task_toml(task_id: str, title: str, artifacts: list[str], mode: str) -> str:
    artifact_text = ", ".join(json.dumps(item) for item in artifacts)
    network = "host-bridge-only" if mode == "eda_assisted" else "no-network"
    return f'''schema_version = "1.3"
artifacts = [{artifact_text}]

[task]
name = "evoldo/{task_id}"
description = {json.dumps(title)}
authors = [{{ name = "EvoLDO-Bench contributors" }}]

[metadata]
checker_allow_ideal = []
task_id = "{task_id}"
revision = 2
maturity = "L4"
maturity_note = "Public development task; reference answer and deterministic verifier are checked in."
maturity_updated_at = "2026-08-11T00:00:00+08:00"
benchmark_version = "{BENCHMARK_VERSION}"
execution_mode = "{mode}"

[verifier]
environment_mode = "separate"

[environment]
network_mode = "{network}"
build_timeout_sec = 1800.0
cpus = 8
memory_mb = 4096
storage_mb = 10240
'''


VERIFY_PY = r'''#!/usr/bin/env python3
import json, math, os
from pathlib import Path

app = Path(os.environ.get("EVOLDO_APP", "/app"))
here = Path(__file__).resolve().parent
answer_path = app / "answer.json"
expected_path = here / "expected.json"
reward_path = Path(os.environ.get("EVOLDO_REWARD", "/logs/verifier/reward.json"))
reward_path.parent.mkdir(parents=True, exist_ok=True)
passed = 0
total = 0
details = []
try:
    answer = json.loads(answer_path.read_text())
    expected = json.loads(expected_path.read_text())
    raw_reward = 0.0
    critical_failed = []
    for check in expected["checks"]:
        total += 1
        value = answer
        try:
            for part in check["path"].split("."):
                value = value[part]
            if check["kind"] == "choice_credit":
                credit = float(check["credits"].get(value, 0.0))
                ok = credit == 1.0
            elif check["kind"] == "set_f1":
                actual = set(value) if isinstance(value, list) else set()
                target = set(check["expected"])
                overlap = len(actual & target)
                credit = 2.0 * overlap / (len(actual) + len(target)) if actual else 0.0
                ok = actual == target
            else:
                ok = value == check["expected"]
                credit = float(ok)
        except Exception:
            ok, credit = False, 0.0
        passed += int(ok)
        earned = float(check["weight"]) * credit
        raw_reward += earned
        if check.get("critical", False) and credit < float(check.get("critical_credit_threshold", 1.0)):
            critical_failed.append(check["id"])
        details.append({"id": check["id"], "passed": ok, "credit_fraction": credit, "earned": earned})
    score = min(raw_reward, float(expected.get("critical_failure_cap", 49.0))) if critical_failed else raw_reward
    reward = score / 100.0
except Exception as exc:
    reward, details = 0.0, [{"error": str(exc)}]
reward_path.write_text(json.dumps({"reward": reward, "tests_total": total, "tests_passed": passed, "details": details}) + "\n")
'''


def make_package(task_id: str, title: str, suite: str, level: str, variant: str, role: str,
                 case: dict, answers: dict, mode: str = "direct_reasoning", paired_with: str | None = None,
                 extra_starter: dict[str, str] | None = None, extra_solution: dict[str, str] | None = None,
                 choice_credits: dict[str, dict[str, float]] | None = None,
                 set_f1_questions: set[str] | None = None) -> dict:
    root = TASKS / task_id
    starter = root / "environment" / "starter"
    tests = root / "tests"
    solution = root / "solution"
    artifacts = ["/app/answer.json"]
    if mode == "eda_assisted":
        artifacts.append("/app/solution.il")
    write(root / "task.toml", task_toml(task_id, title, artifacts, mode))
    instruction = f"""# {title}

Work only from the evidence and files supplied in this task. Read `case.json`, answer every question, and write `/app/answer.json` following `answer_template.json`. Do not include hidden chain-of-thought; concise engineering justification may be placed in `claim_boundary`.

This is a **{mode}** treatment. {('Use the task-local tool and preserve its ledger; unsupported fabricated tool observations receive no credit.' if mode != 'direct_reasoning' else 'External tools, retrieval, and cross-task context are prohibited for this treatment.')}

Hard requirements:

- Preserve `task_id` exactly as `{task_id}`.
- Select option IDs, not option prose; return a JSON list for `multi_select` questions.
- Finish when the required artifact exists or explicitly report inability through the runner; do not invent evidence.
"""
    write(root / "instruction.md", instruction)
    ssh_layer = "RUN apt-get update && apt-get install -y --no-install-recommends openssh-client && rm -rf /var/lib/apt/lists/*\n" if mode == "eda_assisted" else ""
    docker = f"FROM {SKY130_IMAGE if mode == 'sizing_assisted' else BASE_IMAGE}\n{ssh_layer}WORKDIR /app\nCOPY starter/ /app/\nRUN git init -q && git add . && git -c user.email=evoldo-bench@users.noreply.github.com -c user.name=benchmark commit -qm starter\n"
    write(root / "environment" / "Dockerfile", docker)
    contract = {
        "schema_version": "2.0", "task_id": task_id, "family_id": paired_with or task_id,
        "lineage_id": paired_with or task_id, "split": "dev", "variant": variant, "suite": suite,
        "level": level, "capabilities": [suite, role], "title": title, "language": "en",
        "prompt_file": "instruction.md", "input_files": ["case.json", "answer_template.json"],
        "answer_template_file": "answer_template.json", "eligible_modes": [mode],
        "budget": {"timeout_seconds": 900 if mode != "direct_reasoning" else 300,
                   "max_tool_calls": 30 if mode != "direct_reasoning" else 0},
        "benchmark_version": BENCHMARK_VERSION, "evaluation_role": role,
        "scoring_dimensions": [question.get("dimension", question["id"]) for question in case["questions"]],
    }
    if paired_with:
        contract["paired_with"] = paired_with
    dump(starter / "task_contract.json", contract)
    dump(starter / "case.json", case)
    template = {"schema_version": "2.0", "task_id": task_id,
                "answers": {q["id"]: ([] if q["kind"] == "multi_select" else "OPTION_ID")
                            for q in case["questions"]},
                "claim_boundary": "One concise statement of what the evidence does and does not establish.",
                "confidence": 0.0}
    dump(starter / "answer_template.json", template)
    for name, content in (extra_starter or {}).items():
        write(starter / name, content)
        contract["input_files"].append(name)
    dump(starter / "task_contract.json", contract)
    checks = []
    question_dimensions = {question["id"]: question.get("dimension", question["id"])
                           for question in case["questions"]}
    if len(answers) == 6 and "q6" in answers:
        weights = [16, 16, 12, 12, 24, 20]
    elif len(answers) == 5 and "q5" in answers:
        weights = [20, 20, 15, 15, 30]
    elif len(answers) == 4:
        weights = [30, 30, 25, 15]
    else:
        weights = [100 / len(answers)] * len(answers)
    for index, (qid, answer) in enumerate(answers.items()):
        check = {"id": qid, "path": f"answers.{qid}", "kind": "exact", "expected": answer,
                 "weight": weights[index], "critical": index < 2,
                 "dimension": question_dimensions[qid]}
        if choice_credits and qid in choice_credits:
            check.update({"kind": "choice_credit", "credits": choice_credits[qid]})
            if index < 2:
                # Preserve a hard safety gate only for a fully contradicted
                # physical conclusion.  Partially correct reasoning keeps its
                # continuous score instead of collapsing into the 49-point bin.
                check["critical_credit_threshold"] = 0.01
        if set_f1_questions and qid in set_f1_questions:
            check.update({"kind": "set_f1"})
        checks.append(check)
    oracle = {"schema_version": "1.0", "task_id": task_id, "family_id": contract["family_id"],
              "checks": checks, "critical_failure_cap": 49, "pass_threshold": 70}
    dump(ORACLES / f"{task_id}.oracle.json", oracle)
    dump(tests / "expected.json", oracle)
    write(tests / "verify.py", VERIFY_PY)
    write(tests / "test.sh", "#!/usr/bin/env sh\nset -eu\npython3 /app/analog_arena_tests/verify.py\n")
    write(tests / "Dockerfile", f"FROM {SKY130_IMAGE if mode == 'sizing_assisted' else BASE_IMAGE}\nWORKDIR /app/analog_arena_tests\nCOPY . .\n")
    solution_answer = {"schema_version": "2.0", "task_id": task_id, "answers": answers,
                       "claim_boundary": "Conclusion is limited to the supplied evidence and named operating conditions.",
                       "confidence": 0.95}
    dump(solution / "answer.json", solution_answer)
    write(solution / "solve.sh", "#!/usr/bin/env sh\nset -eu\ncp /solution/answer.json /app/answer.json\n" +
          ("cp /solution/solution.il /app/solution.il\n" if mode == "eda_assisted" else ""))
    for name, content in (extra_solution or {}).items():
        write(solution / name, content)
    return contract


def build_reasoning() -> list[dict]:
    contracts = []
    for suite, rows in SUITES.items():
        for index, row in enumerate(rows):
            slug, title, scenario, evidence, primary, mechanism, action, boundary = row
            task_id = f"v06-{suite.replace('_', '-')}-{index + 1:02d}-{slug}"
            questions, answers = [], {}
            prompts = ["Which conclusion is best supported?", "Which mechanism best explains the evidence?",
                       "What is the best next engineering action?", "Which claim boundary is correct?"]
            all_credits = {}
            for qidx, (prompt, correct) in enumerate(zip(prompts, row[4:8]), 1):
                question, answer, dimension_credits = calibrated_reasoning_question(
                    task_id, f"q{qidx}", prompt, correct)
                question["dimension"] = ("conclusion", "mechanism", "next_action", "claim_boundary")[qidx - 1]
                questions.append(question); answers[f"q{qidx}"] = answer
                all_credits[f"q{qidx}"] = dimension_credits
            challenge_prompt, alternatives = CHALLENGES[(suite, slug)]
            question, answer, credits = credited_choice_question(task_id, "q5", challenge_prompt, alternatives)
            question["dimension"] = "quantitative_or_counterfactual"
            questions.append(question); answers["q5"] = answer
            all_credits["q5"] = credits
            pair = EVIDENCE_PAIRS[(suite, slug)]
            question = {"id": "q6", "kind": "multi_select", "dimension": "evidence_attribution",
                        "select_count": 2,
                        "prompt": "Select exactly two evidence records that form the shortest decisive support chain for the primary conclusion.",
                        "options": [{"id": f"E{i+1}", "text": item} for i, item in enumerate(evidence)]}
            questions.append(question); answers["q6"] = [f"E{index}" for index in pair]
            role = "atomic" if index < 3 else ("coupled" if index < 5 else "existing_architecture_optimization")
            level = "L2" if index < 2 else ("L3" if index == 2 else ("L4" if index < 5 else "L5"))
            case = {"schema_version": "2.0", "task_id": task_id, "scenario": scenario,
                    "evidence": [{"id": f"E{i+1}", "observation": item} for i, item in enumerate(evidence)],
                    "questions": questions, "provenance": {"kind": "expert-authored",
                    "pdk": "SKY130/ngspice" if suite == "sizing" else "not-required"}}
            contracts.append(make_package(task_id, title, suite, level, "canonical", role, case, answers,
                                          choice_credits=all_credits, set_f1_questions={"q6"}))

        # One metamorphic companion per suite: rename internal nodes, reverse evidence order,
        # and permute answer choices while keeping the physical conclusion invariant.
        base_index = 2
        row = rows[base_index]
        slug, title, scenario, evidence = row[:4]
        base_id = f"v06-{suite.replace('_', '-')}-{base_index + 1:02d}-{slug}"
        task_id = f"v06-{suite.replace('_', '-')}-m01-alias-invariance"
        scenario = "Node aliases have been changed (VCTRL->N7, VFB->N3) and evidence rows reordered. " + scenario
        questions, answers = [], {}
        prompts = ["Which conclusion is best supported after the representation change?", "Which mechanism is invariant?",
                   "What is the best next engineering action?", "Which claim boundary remains valid?"]
        all_credits = {}
        for qidx, (prompt, correct) in enumerate(zip(prompts, row[4:8]), 1):
            question, answer, dimension_credits = calibrated_reasoning_question(
                task_id, f"q{qidx}", prompt, correct)
            question["dimension"] = ("conclusion", "mechanism", "next_action", "claim_boundary")[qidx - 1]
            questions.append(question); answers[f"q{qidx}"] = answer
            all_credits[f"q{qidx}"] = dimension_credits
        challenge_prompt, alternatives = CHALLENGES[(suite, slug)]
        question, answer, credits = credited_choice_question(task_id, "q5", challenge_prompt, alternatives)
        question["dimension"] = "quantitative_or_counterfactual"
        questions.append(question); answers["q5"] = answer
        all_credits["q5"] = credits
        canonical_pair = EVIDENCE_PAIRS[(suite, slug)]
        reversed_evidence = list(reversed(evidence))
        remapped_pair = [len(evidence) - index + 1 for index in canonical_pair]
        question = {"id": "q6", "kind": "multi_select", "dimension": "evidence_attribution",
                    "select_count": 2,
                    "prompt": "Select exactly two evidence records that form the shortest decisive support chain after representation changes.",
                    "options": [{"id": f"E{i+1}", "text": item} for i, item in enumerate(reversed_evidence)]}
        questions.append(question); answers["q6"] = [f"E{index}" for index in remapped_pair]
        case = {"schema_version": "2.0", "task_id": task_id, "metamorphic_parent": base_id,
                "transformation": ["bijective internal-node aliasing", "evidence-row reversal", "choice permutation"],
                "scenario": scenario,
                "evidence": [{"id": f"E{i+1}", "observation": item} for i, item in enumerate(reversed_evidence)],
                "questions": questions, "provenance": {"kind": "metamorphic-companion"}}
        contracts.append(make_package(task_id, title + " — alias-invariance companion", suite, "L3",
                                      "metamorphic", "companion", case, answers, paired_with=base_id,
                                      choice_credits=all_credits, set_f1_questions={"q6"}))
    return contracts


SIZER_TOOL = r'''#!/usr/bin/env python3
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
'''


SIZING_TB = r'''* EvoLDO SKY130 sizing probe
.lib '{{model}}' tt
.param WP={{pass_width_um}} WI={{input_width_um}} RD={{driver_res_kohm}}k CC={{ccomp_pf}}p RB={{bias_res_kohm}}k RT={{rtop_kohm}}k RBT={{rbot_kohm}}k
VVIN vdd 0 1.8
VREF ref 0 1.0
RBIAS vdd vbn {RB}
XMBIAS vbn vbn 0 0 sky130_fd_pr__nfet_01v8 L=.5 W=8
XMTAIL ntail vbn 0 0 sky130_fd_pr__nfet_01v8 L=.5 W=16
XM1 nleft vfb ntail 0 sky130_fd_pr__nfet_01v8 L=.5 W=20 M={WI/20}
XM2 vctrl ref ntail 0 sky130_fd_pr__nfet_01v8 L=.5 W=20 M={WI/20}
XM3 nleft nleft vdd vdd sky130_fd_pr__pfet_01v8 L=.5 W=80
XM4 vctrl nleft vdd vdd sky130_fd_pr__pfet_01v8 L=.5 W=80
RDRV vctrl gate {RD}
XMPASS vout gate vdd vdd sky130_fd_pr__pfet_01v8 L=.15 W=20 M={WP/20}
RFBT vout vfb {RT}
RFBB vfb 0 {RBT}
CCOMP vctrl vout {CC}
RLOAD vout 0 1.5k
CLOAD vout 0 10p
.tran .1u 20u
.meas tran EVOLDO_VOUT FIND v(vout) AT=19u
.meas tran EVOLDO_IQ AVG par('-i(VVIN)-0.001') FROM=18u TO=19u
.end
'''


def build_sizing_tools() -> list[dict]:
    contracts = []
    source_rows = SUITES["sizing"]
    defaults = {"pass_width_um": 120, "input_width_um": 40, "driver_res_kohm": 5, "ccomp_pf": 5,
                "bias_res_kohm": 120, "rtop_kohm": 500, "rbot_kohm": 1000}
    configurations = [
        ({"pass_width_um": 120}, "Minimize characterized pass width while retaining the explicit load-current margin."),
        ({"rtop_kohm": 249, "rbot_kohm": 499}, "Meet the 1.5 feedback ratio while minimizing divider current and ratio error."),
        ({"ccomp_pf": 8}, "Find the smallest characterized Ccomp that satisfies both phase-margin and bandwidth constraints."),
        ({"input_width_um": 40, "bias_res_kohm": 120}, "Allocate bias and input-pair size without violating gain, slew, or IQ gates."),
        ({"pass_width_um": 140, "driver_res_kohm": 3, "ccomp_pf": 8}, "Co-size pass, driver, and compensation to close dropout and stability together."),
        ({"pass_width_um": 160, "input_width_um": 40, "driver_res_kohm": 3, "ccomp_pf": 8}, "Minimize normalized area plus IQ subject to every frozen hard constraint."),
    ]
    bounds = {"pass_width_um": [80, 220], "input_width_um": [20, 80], "driver_res_kohm": [2, 10],
              "ccomp_pf": [2, 12], "bias_res_kohm": [60, 240], "rtop_kohm": [100, 600], "rbot_kohm": [200, 1200]}
    for index, (row, configuration) in enumerate(zip(source_rows, configurations), 1):
        target, objective = configuration
        base_id = f"v06-sizing-{index:02d}-{row[0]}"
        task_id = f"v06-tool-sizing-{index:02d}-{row[0]}"
        params = list(target)
        questions = [{"id": f"q{i+1}", "kind": "numeric", "prompt": f"Final {key}"}
                     for i, key in enumerate(params)]
        answers = {f"q{i+1}": value for i, value in enumerate(target.values())}
        spec = {"schema_version": "1.0", "task_id": task_id, "tunable_fields": params,
                "defaults": defaults, "bounds": {field: bounds[field] for field in params},
                "objective": objective, "hard_gates": ["VOUT 1.44 to 1.53 V", "absolute IQ <= 50 uA"],
                "evaluation_budget": 30}
        case = {"schema_version": "2.0", "task_id": task_id,
                "scenario": row[2] + " Use the task-local SKY130/ngspice probe to produce a final sizing candidate.",
                "paired_pure_task": base_id, "evaluation_budget": 30, "candidate_fields": params,
                "evidence": row[3], "objective": objective, "hard_bounds": spec["bounds"],
                "questions": questions,
                "provenance": {"pdk": "SKY130", "simulator": "ngspice", "model_section": "tt"}}
        contracts.append(make_package(task_id, "Tool-assisted sizing: " + row[1], "sizing", "L5", "canonical",
                                      "tool_sizing_treatment", case, answers, "sizing_assisted", base_id,
                                      {"sizer_tool.py": SIZER_TOOL, "sizing_tb.sp": SIZING_TB,
                                       "sizing_spec.json": json.dumps(spec, indent=2) + "\n"},
                                      {"candidate.json": json.dumps(target, indent=2) + "\n"}))
    return contracts


EDA_TOPICS = [
    ("triage", "Triage a controlled Virtuoso failure", "Open a known-good cell read-only, execute the supplied failing check, and identify whether the failure is OA data, netlisting, simulator, or infrastructure.", "failure_class", "netlisting"),
    ("oa-audit", "Read-only OA/SKILL connectivity audit", "Inspect instances, terminals, nets, and connectivity without saving any design data; report dangling instance terminals.", "audit_result", "dangling_terminals_reported"),
    ("oa-edit", "Surgical OA property edit", "Change exactly one instance parameter in a scratch copy, save, close, reopen, and read the value back.", "edit_result", "reopen_readback_matches"),
    ("materialize", "Materialize a visible schematic connection", "Create a named net and visible wire figures between supplied terminals in a scratch cell; save/reopen and verify both connectivity and figures.", "materialization_result", "net_and_wire_figures_persist"),
    ("spectre", "Run and measure a fresh Spectre analysis", "Netlist a scratch LDO cell, run the requested operating-point analysis, and report VOUT with run-directory provenance.", "simulation_result", "fresh_run_measurement_with_provenance"),
    ("mini-closure", "Perform a bounded Virtuoso mini-closure", "Audit, apply one allowed sizing change, netlist, simulate, and accept or revert based on the supplied gate.", "closure_result", "change_accepted_after_fresh_gate"),
]


IC618_TOOL = r'''#!/usr/bin/env python3
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
'''


SKILL_PRELUDE = r'''; EvoLDO IC618 reference: every object is created under the invocation scratch.
procedure(evoldoWriteResult(key value extra)
  let((p)
    p=outfile("evoldo_result.json" "w")
    unless(p error("cannot create terminal result"))
    fprintf(p "{\"status\":\"OK\",\"%s\":\"%s\"%s}\n" key value extra)
    close(p)))

procedure(evoldoScratchCv(mode)
  let((lib path cv)
    lib="EVOLDO_V06_SCRATCH"
    path=simplifyFilename(strcat(getWorkingDir() "/oa_lib"))
    unless(ddGetObj(lib) ddCreateLib(lib path))
    cv=dbOpenCellViewByType(lib "fixture" "schematic" "schematic" mode)
    unless(cv error("cannot open isolated scratch cellview"))
    cv))

procedure(evoldoTermPoint(inst termName)
  let((term pin fig bb)
    term=car(setof(x inst~>master~>terminals x~>name==termName))
    unless(term error("missing terminal %s" termName))
    pin=car(term~>pins) fig=car(pin~>figs)
    bb=dbTransformBBox(fig~>bBox inst~>transform)
    list((xCoord(car(bb))+xCoord(cadr(bb)))/2.0
         (yCoord(car(bb))+yCoord(cadr(bb)))/2.0)))

procedure(evoldoCreateFixture()
  let((cv master r0 p q)
    cv=evoldoScratchCv("w")
    master=dbOpenCellViewByType("analogLib" "res" "symbol" nil "r")
    unless(master error("analogLib/res unavailable"))
    r0=dbCreateInst(cv master "R0" 0:0 "R0")
    unless(r0 error("cannot create R0"))
    dbReplaceProp(r0 "evoldoSizing" "string" "40u")
    p=evoldoTermPoint(r0 "PLUS") q=list(xCoord(p)-1.0 yCoord(p))
    schCreateWire(cv "route" "full" list(p q) 0 0 0 nil nil)
    dbCreateLabel(cv list("wire" "label") q "VIN" "lowerLeft" "R0" "stick" 0.0625)
    evoldoFixtureCheck=schCheck(cv) dbSave(cv) dbClose(cv)
    t))
'''


def skill_program(slug: str) -> str:
    bodies = {
        "triage": r'''procedure(evoldoMain()
  let((p rc)
    p=outfile("bad.scs" "w")
    fprintf(p "simulator lang=spectre\ninclude \"definitely_missing_model.scs\"\n") close(p)
    rc=system("/opt/eda/cadence/SPECTRE181/bin/spectre bad.scs > bad.log 2>&1")
    unless(rc!=0 error("controlled netlisting fixture unexpectedly passed"))
    evoldoWriteResult("failure_class" "netlisting" ",\"controlled_failure_observed\":true")))''',
        "oa-audit": r'''procedure(evoldoMain()
  let((cv dangling before)
    evoldoCreateFixture()
    cv=evoldoScratchCv("r") before=length(cv~>instances) dangling=0
    dangling=if(evoldoFixtureCheck && cadr(evoldoFixtureCheck) then cadr(evoldoFixtureCheck) else 0)
    dbClose(cv)
    unless(before==1 && dangling>0 error("audit fixture contract not observed"))
    evoldoWriteResult("audit_result" "dangling_terminals_reported" ",\"write_count\":0")))''',
        "oa-edit": r'''procedure(evoldoMain()
  let((cv inst prop value)
    evoldoCreateFixture()
    cv=evoldoScratchCv("a") inst=car(cv~>instances)
    dbReplaceProp(inst "evoldoSizing" "string" "80u") dbSave(cv) dbClose(cv)
    cv=evoldoScratchCv("r") inst=car(cv~>instances)
    prop=inst~>evoldoSizing value=prop dbClose(cv)
    unless(value=="80u" error("reopen readback mismatch"))
    evoldoWriteResult("edit_result" "reopen_readback_matches" ",\"changed_properties\":1")))''',
        "materialize": r'''procedure(evoldoMain()
  let((cv master r1 p q chk named shapeCount)
    evoldoCreateFixture()
    cv=evoldoScratchCv("a") master=dbOpenCellViewByType("analogLib" "res" "symbol" nil "r")
    r1=dbCreateInst(cv master "R1" 4:0 "R0")
    p=evoldoTermPoint(r1 "PLUS") q=list(xCoord(p)-1.0 yCoord(p))
    schCreateWire(cv "route" "full" list(p q) 0 0 0 nil nil)
    dbCreateLabel(cv list("wire" "label") q "VOUT" "lowerLeft" "R0" "stick" 0.0625)
    chk=schCheck(cv) dbSave(cv) dbClose(cv)
    cv=evoldoScratchCv("r") named=dbFindNetByName(cv "VOUT") shapeCount=length(cv~>shapes) dbClose(cv)
    unless(chk && car(chk)==0 && named && shapeCount>0 error("materialization did not persist"))
    evoldoWriteResult("materialization_result" "net_and_wire_figures_persist" ",\"reopen_verified\":true")))''',
        "spectre": r'''procedure(evoldoMain()
  let((p rc)
    p=outfile("divider.scs" "w")
    fprintf(p "simulator lang=spectre\nV0 (vdd 0) vsource dc=1.8\nR1 (vdd out) resistor r=600\nR2 (out 0) resistor r=1.2k\ndcOp dc\n") close(p)
    rc=system("/opt/eda/cadence/SPECTRE181/bin/spectre divider.scs +log spectre.log > spectre.stdout 2>&1")
    unless(rc==0 error("fresh Spectre run failed"))
    evoldoWriteResult("simulation_result" "fresh_run_measurement_with_provenance" ",\"expected_vout_v\":1.2,\"run_log\":\"spectre.log\"")))''',
        "mini-closure": r'''procedure(evoldoMain()
  let((cv inst value p rc)
    evoldoCreateFixture()
    cv=evoldoScratchCv("a") inst=car(cv~>instances)
    dbReplaceProp(inst "evoldoSizing" "string" "80u") dbSave(cv) dbClose(cv)
    cv=evoldoScratchCv("r") value=car(cv~>instances)~>evoldoSizing dbClose(cv)
    unless(value=="80u" error("candidate readback failed"))
    p=outfile("gate.scs" "w") fprintf(p "simulator lang=spectre\nV0 (vdd 0) vsource dc=1.8\nR1 (vdd out) resistor r=600\nR2 (out 0) resistor r=1.2k\ndcOp dc\n") close(p)
    rc=system("/opt/eda/cadence/SPECTRE181/bin/spectre gate.scs +log gate.log > gate.stdout 2>&1")
    unless(rc==0 error("fresh closure gate failed"))
    evoldoWriteResult("closure_result" "change_accepted_after_fresh_gate" ",\"reopen_verified\":true")))''',
    }
    return SKILL_PRELUDE + "\n" + bodies[slug] + "\nevoldoMain()\nexit()\n"


def build_eda() -> list[dict]:
    contracts = []
    for index, (slug, title, scenario, field, expected) in enumerate(EDA_TOPICS, 1):
        task_id = f"v06-eda-{index:02d}-{slug}"
        options = [expected, "unsupported_claim", "infrastructure_failure", "no_persistent_evidence"]
        rng = random.Random(index); rng.shuffle(options)
        q = {"id": "q1", "kind": "single_choice", "prompt": "Which terminal result is supported by the required tool workflow?",
             "options": [{"id": chr(65+i), "text": v} for i, v in enumerate(options)]}
        answer = next(item["id"] for item in q["options"] if item["text"] == expected)
        case = {"schema_version": "2.0", "task_id": task_id, "scenario": scenario,
                "required_sequence": ["fresh isolated scratch", "operation", "save/close/reopen where applicable", "readback", "terminal JSON"],
                "hard_gates": ["no modification of pre-existing libraries", "no fabricated observations", "fresh provenance"],
                "questions": [q], "result_field": field,
                "provenance": {"tool": "Cadence Virtuoso IC618/SKILL", "backend": "operator-provided VM"}}
        contracts.append(make_package(task_id, title, "eda_tool", "L5", "canonical", "eda_live", case,
                                      {"q1": answer}, "eda_assisted", None,
                                      {"ic618_tool.py": IC618_TOOL, "SKILL_CONTRACT.md": "Run `python3 ic618_tool.py preflight`, author `solution.il`, then run `python3 ic618_tool.py run --skill solution.il`. Existing VM libraries are out of scope.\n"},
                                      {"solution.il": skill_program(slug)}))
    # One representation companion for E2.
    base = "v06-eda-02-oa-audit"; task_id = "v06-eda-m01-oa-audit-renamed"
    q = {"id": "q1", "kind": "single_choice", "prompt": "Which result remains valid after cell/instance aliases are changed?",
         "options": [{"id": "A", "text": "unsupported_claim"}, {"id": "B", "text": "dangling_terminals_reported"},
                     {"id": "C", "text": "write_required"}, {"id": "D", "text": "no_audit"}]}
    case = {"schema_version": "2.0", "task_id": task_id, "metamorphic_parent": base,
            "transformation": ["cell and instance aliases changed", "instance enumeration order reversed"],
            "scenario": "Repeat the read-only OA audit after bijective cell and instance renaming.",
            "required_sequence": ["fresh isolated scratch", "read-only audit", "terminal JSON"],
            "hard_gates": ["write_count must remain zero", "report dangling terminals by connectivity, not names"],
            "questions": [q], "provenance": {"tool": "Cadence Virtuoso IC618/SKILL"}}
    contracts.append(make_package(task_id, "Read-only OA audit — alias companion", "eda_tool", "L5", "metamorphic",
                                  "companion", case, {"q1": "B"}, "eda_assisted", base,
                                  {"ic618_tool.py": IC618_TOOL}, {"solution.il": skill_program("oa-audit")}))
    return contracts


def package_hash(root: Path) -> str:
    rows = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rows.append(f"{path.relative_to(root).as_posix()}:{hashlib.sha256(path.read_bytes()).hexdigest()}")
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    ORACLES.mkdir(parents=True)
    contracts = build_reasoning() + build_sizing_tools() + build_eda()
    rows = []
    for contract in contracts:
        root = TASKS / contract["task_id"]
        rows.append({key: contract[key] for key in ("task_id", "family_id", "suite", "level", "variant", "split")} | {
            "manifest_sha256": hashlib.sha256((root / "task.toml").read_bytes()).hexdigest(),
            "package_sha256": package_hash(root), "evaluation_role": contract["evaluation_role"],
        })
    write(OUT / "registry.jsonl", "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
    summary = {"benchmark_version": BENCHMARK_VERSION, "task_count": len(rows),
               "pure_core": 48, "pure_companions": 8, "tool_sizing": 6, "eda_primary": 6, "eda_companions": 1,
               "rollouts_per_model": 3, "task_ids_sha256": hashlib.sha256("\n".join(r["task_id"] for r in rows).encode()).hexdigest()}
    dump(OUT / "manifest.json", summary)
    write(OUT / "README.md", TRACK_README)
    dump(OUT / "public_pdk_manifest.json", {
        "provider": "sky130", "repository": "https://github.com/opensource-analog-circuits/sky130_pdk",
        "revision": "e8308aa273c1a6737a5dee89178c4d48270ff87e",
        "model_entry": "libs.tech/ngspice/sky130.lib.spice",
        "model_entry_sha256": "5efa041a988893c1a3580d0ecd57870ea3146b27741c7d42b56baaa336b9549e",
        "simulator": "ngspice", "validated_version": "46"
    })
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
