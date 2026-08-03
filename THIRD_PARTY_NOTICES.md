# Third-party notices and clean-room statement

EvoLDO-Bench was informed by general benchmark engineering ideas such as isolated task bundles,
separation of answer generation from evaluation, paired tool treatments, repeated rollouts, and
provenance tracking.

Razavi-Bench is an external reference:
https://github.com/Arcadia-1/razavi-bench

Analog Design Bench is an external method-level reference:
https://analog-design-bench.tokenzhang.com/
https://github.com/Arcadia-1/analog-design-bench

This repository does **not** copy, adapt, redistribute, or derive tasks, figures, goldens, rubrics,
judge prompts, netlists, score tables, model outputs, or datasets from Razavi-Bench. All included LDO
materials were authored independently for this project. The public Analog Design Bench presentation
informed general reporting ideas such as separating Pass@1 from spec score and showing score versus effort;
no task or hidden implementation detail was used. Users who run external benchmarks must obey their
respective licenses and keep their materials outside this repository.
