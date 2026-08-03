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

## Runtime-only public PDK models

The public design-closure track can fetch model files from:
https://github.com/jialinlu/opensource-analog-circuits

The checkout is pinned and hash-checked, remains in an ignored runtime directory, and is not redistributed
by EvoLDO-Bench. The SKY130 model entry carries Apache-2.0 notices and points to the authoritative SkyWater
PDK source: https://github.com/google/skywater-pdk

The optional ASAP7 mirror is tied to the BSD-3-Clause OpenROAD upstream:
https://github.com/The-OpenROAD-Project/asap7
Its OSDI binary is platform-specific and its mirror-subtree notice placement still requires review, so it
is fetch-only and is not counted as a qualified benchmark task.

All LDO DUTs, fault injections, specifications, benches, and development reference netlists in this
repository were independently authored for EvoLDO-Bench. No circuit from the model-source repository was
copied or adapted.
