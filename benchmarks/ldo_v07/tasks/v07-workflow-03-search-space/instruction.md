# Construct a role-aware sizing campaign

Act as the design-review engineer for this isolated LDO case. Read `case.json` and produce
`/app/answer.json` following `answer_template.json`. The deliverable is a structured engineering
artifact, not a multiple-choice explanation: classify every requested record, compute requested
values, and order only the actions that the supplied evidence authorizes.

Rules:

- Use only supplied case material and, in a declared KG-on treatment, the frozen local retrieval.
- Web search, browsing, remote retrieval, and undeclared tools are forbidden in every treatment.
- Return exactly one JSON object; preserve task ID `v07-workflow-03-search-space` and all controlled identifiers.
- Keep `claim_boundary` concise and restrict it to evidence actually supplied.
