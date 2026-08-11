# Tool-assisted sizing: Select compensation capacitance

Work only from the evidence and files supplied in this task. Read `case.json`, answer every question, and write `/app/answer.json` following `answer_template.json`. Do not include hidden chain-of-thought; concise engineering justification may be placed in `claim_boundary`.

This is a **sizing_assisted** treatment. Use the task-local tool and preserve its ledger; unsupported fabricated tool observations receive no credit.

Hard requirements:

- Preserve `task_id` exactly as `v06-tool-sizing-03-comp-cap`.
- Select option IDs, not option prose; return a JSON list for `multi_select` questions and a strongest-to-weakest JSON list for `ranked_choice` questions.
- Finish when the required artifact exists or explicitly report inability through the runner; do not invent evidence.
