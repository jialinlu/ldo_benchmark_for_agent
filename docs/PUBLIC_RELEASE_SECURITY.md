# Public release security gate

Before publishing a release, run:

```bash
python tools/audit_public_release.py
python -m unittest discover -s tests -v
python tools/run_self_check.py
evoldo-bench audit
```

The public-release audit scans the tracked tree, every reachable Git blob, and reachable commit
metadata. It rejects common credentials, private keys, personal email addresses, absolute workstation
or server paths, private IP addresses, vendor build/license details, suspicious credential files,
private EDA artifact types, and unexpectedly large files. Matched values are never printed.

This repository intentionally contains only:

- independently authored benchmark prompts and public development oracles;
- generic JSON evidence and tiny conceptual MOS connectivity snippets;
- public software, schemas, tests, documentation, and provenance tools;
- generic references to private PDK/site adapters as architectural boundaries.

It must never contain real DUT netlists, OA databases, GDS/OASIS, foundry models, private device names,
company testbenches, internal hostnames, user paths, license-feature identifiers, API keys, access
tokens, private keys, or non-public email addresses.

The automated gate is a defense in depth measure, not proof of compliance. A human review is still
required for every public release, especially for new circuit fixtures, screenshots, archives, and
third-party materials.
