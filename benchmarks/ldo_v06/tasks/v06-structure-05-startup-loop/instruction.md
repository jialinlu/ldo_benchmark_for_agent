# Separate startup path from regulation loop

Work only from the evidence and files supplied in this task. Read `case.json`, answer every question, and write `/app/answer.json` following `answer_template.json`. Do not include hidden chain-of-thought; concise engineering justification may be placed in `claim_boundary`.

This is a **direct_reasoning** treatment. External tools, retrieval, and cross-task context are prohibited for this treatment.

Hard requirements:

- Preserve `task_id` exactly as `v06-structure-05-startup-loop`.
- Select option IDs, not option prose.
- Finish when the required artifact exists or explicitly report inability through the runner; do not invent evidence.
