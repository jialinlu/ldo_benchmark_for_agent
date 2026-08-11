# Materialize a visible schematic connection

Work only from the evidence and files supplied in this task. Read `case.json`, answer every question, and write `/app/answer.json` following `answer_template.json`. Do not include hidden chain-of-thought; concise engineering justification may be placed in `claim_boundary`.

This is a **eda_assisted** treatment. Use the task-local tool and preserve its ledger; unsupported fabricated tool observations receive no credit.

Hard requirements:

- Preserve `task_id` exactly as `v06-eda-04-materialize`.
- Select option IDs, not option prose; return a JSON list for `multi_select` questions.
- Finish when the required artifact exists or explicitly report inability through the runner; do not invent evidence.
