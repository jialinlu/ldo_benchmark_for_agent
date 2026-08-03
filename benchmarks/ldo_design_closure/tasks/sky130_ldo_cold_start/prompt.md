# Close true cold start from zero supply

Achieve self-starting regulation after a supply/reference ramp without nodeset, IC, or an internal ideal bias source.

The starter contains one controlled fault: **The self-bias resistor is intentionally near-open, so it cannot establish the intended loop current.** Edit only `starter/ldo.sp` (or a copied candidate), run the declared qualification task, and stop only when every numeric and policy gate passes. Do not use `.ic`, `.nodeset`, an internal ideal source, or a testbench workaround as a DUT fix.
