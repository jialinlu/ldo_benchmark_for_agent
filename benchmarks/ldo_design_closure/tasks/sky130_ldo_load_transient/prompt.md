# Close capless load-transient behavior

Jointly tune loop drive and compensation for a 0.1 mA to 1 mA load step with only 10 pF external load capacitance.

The starter contains one controlled fault: **The compensation capacitor is intentionally reduced into a poor dynamic regime.** Edit only `starter/ldo.sp` (or a copied candidate), run the declared qualification task, and stop only when every numeric and policy gate passes. Do not use `.ic`, `.nodeset`, an internal ideal source, or a testbench workaround as a DUT fix.
