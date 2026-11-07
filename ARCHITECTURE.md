# Architecture: three layers and an integrity agent

1. **SOURCE (never modified).** The uploaded Excel/CSV files. They are only read. Each file is hashed (SHA-256) before and after every build; a change fails the build and the integrity check.
2. **WORKING replica.** Built in memory from the source: sheets and columns mapped (fixable in Advanced mode), units converted, suspect rows flagged, exclusions applied. Decisions (mapping fixes, excluded rows, exceptions, utilisation bands) live in a sidecar `decisions.json`, never in the source. Each row keeps its origin as file, sheet and Excel row.
3. **CHAT / OUTPUT.** The master workbook (plus `Copilot_Prompt.md`) and, with `--sqlite`, a read-only SQLite container holding the same tables for a chat model or SQL tool. Every number is computed by code with a status label (calculated, estimated, team assumption, KAM reported, missing).

**Integrity agent** (`integrity.py`): a deterministic verifier that runs over layers 1 to 3. It checks source hashes, row counts source to working to output, sums of kg and repairs, utilisation recomputed from its parts, and that the SQLite container equals the workbook. Results go to the `Integrity_Check` sheet and the build report. Any failure is shown in Simple mode and the numbers must not be quoted until reviewed.

**Review workflow**: upload, validation flags conflicting or implausible entries (with file/sheet/row), the reviewer excludes them or keeps them as reported exceptions, then build the workbook (and, in Advanced mode, the PowerPoint). Reviewers: the uploader and optionally the KAM.

**Utilisation band**: default 30 to 70 %, adjustable per customer; food, hygiene, healthcare and cleanroom customers default to 40 to 80 % (a team assumption, to be confirmed with Lindström).
