# Close true cold start from zero supply

Achieve self-starting regulation after a supply/reference ramp without nodeset, IC, or an internal ideal bias source.

The starter contains one controlled fault: **The self-bias resistor is intentionally near-open, so it cannot establish the intended loop current.** Edit only `starter/ldo.sp` (or a copied candidate), run the declared qualification task, and stop only when every numeric and policy gate passes. Do not use `.ic`, `.nodeset`, an internal ideal source, or a testbench workaround as a DUT fix.

## Deliverable

- Work in `/app` and edit only `/app/circuit.spi`.
- Preserve `.subckt evoldo_sky130_ldo VDD VSS VREF ENB VOUT`.
- Use only physical DUT devices permitted by the task policy.
- The SKY130 model tree is an external, hash-pinned runtime dependency and is not a submitted artifact.
- If time expires, the evaluator grades the current `circuit.spi`; a missing or empty file receives zero reward.
