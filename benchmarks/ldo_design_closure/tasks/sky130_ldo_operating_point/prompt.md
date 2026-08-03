# Close nominal operating point and quiescent current

Repair and size the transistor-level LDO so it regulates at 1 mA without excessive supply current.

The starter contains one controlled fault: **The pass device is intentionally under-sized.** Edit only `starter/ldo.sp` (or a copied candidate), run the declared qualification task, and stop only when every numeric and policy gate passes. Do not use `.ic`, `.nodeset`, an internal ideal source, or a testbench workaround as a DUT fix.
