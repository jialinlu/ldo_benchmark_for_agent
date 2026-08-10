# Close capless load-transient behavior

Jointly tune loop drive and compensation for a 0.1 mA to 1 mA load step with only 10 pF external load capacitance.

The starter contains one controlled fault: **The compensation capacitor is intentionally reduced into a poor dynamic regime.** Edit only `starter/ldo.sp` (or a copied candidate), run the declared qualification task, and stop only when every numeric and policy gate passes. Do not use `.ic`, `.nodeset`, an internal ideal source, or a testbench workaround as a DUT fix.

## Deliverable

- Work in `/app` and edit only `/app/circuit.spi`.
- Preserve `.subckt evoldo_sky130_ldo VDD VSS VREF ENB VOUT`.
- Use only physical DUT devices permitted by the task policy.
- The SKY130 model tree is an external, hash-pinned runtime dependency and is not a submitted artifact.
- If time expires, the evaluator grades the current `circuit.spi`; a missing or empty file receives zero reward.
