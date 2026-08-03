# Close line and load regulation

Maintain the output window across 1.65–1.8 V input and 0.1–1 mA load after each physical transition settles.

The starter contains one controlled fault: **The pass array is intentionally too weak at the low-line heavy-load point.** Edit only `starter/ldo.sp` (or a copied candidate), run the declared qualification task, and stop only when every numeric and policy gate passes. Do not use `.ic`, `.nodeset`, an internal ideal source, or a testbench workaround as a DUT fix.
