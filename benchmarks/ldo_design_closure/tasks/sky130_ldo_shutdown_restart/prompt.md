# Close physical shutdown and restart

Make ENB turn the DUT off and allow it to restart, using only physical transistor/resistor paths inside the DUT.

The starter contains one controlled fault: **The active-high bias shunt is intentionally disconnected.** Edit only `starter/ldo.sp` (or a copied candidate), run the declared qualification task, and stop only when every numeric and policy gate passes. Do not use `.ic`, `.nodeset`, an internal ideal source, or a testbench workaround as a DUT fix.
