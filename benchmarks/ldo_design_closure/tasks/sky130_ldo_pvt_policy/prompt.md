# Close public-PDK PVT corners and DUT policy

Meet regulation/current limits at distinct process/temperature points while passing the no-ideal-device and no-forced-state source scan.

The starter contains one controlled fault: **The pass array is intentionally marginal at the slow/cold point.** Edit only `starter/ldo.sp` (or a copied candidate), run the declared qualification task, and stop only when every numeric and policy gate passes. Do not use `.ic`, `.nodeset`, an internal ideal source, or a testbench workaround as a DUT fix.
