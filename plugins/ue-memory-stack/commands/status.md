---
description: Report what memory layers exist for this tree and whether they still describe the code
allowed-tools: Bash, Read, Glob, Grep
---

Report the state of the memory layers for this project. **Read-only: change nothing.**

## What to check, in this order

**1. Is the stack set up here at all?** `.claude/agent-memory-stack.json`, the plugin in the project's descriptor, and at least one `Docs/AgentMemory` directory. If any is missing, say which and stop — the rest of the checks describe something that is not there.

**2. Do the artefacts still describe the code?** Compare **revisions**, not timestamps: a sync stamps everything with the time it wrote it, so file times cannot tell a changed header from a regenerated artefact.

```powershell
p4 changes -m1 "<project>/Source/...#have"
p4 changes -m1 "<project>/Docs/AgentMemory/...#have"
```

Under git, `git log -1 --format=%H --` over each path and ask which commit is an ancestor of the other. Artefacts behind the code means regenerate.

Two blind spots to report rather than hide: **uncommitted local edits**, which no revision comparison sees, and **artefacts not in source control yet**, where the only answer is file times and it should be given as the weaker answer it is.

**3. The compile database.** Timestamps are sound here, because it is ignored by source control and never synced. Older than the newest `.Build.cs` means it needs regenerating.

**4. Layer 1, if this tree uses it.** Whether Serena answers, and whether clangd has an index loaded. `find_symbol_indexed` returning `[]` in a tenth of a second is an unloaded index, not a missing symbol.

## Then

Report what you found as a short list: what exists, what is behind, and what to run. **Do not regenerate anything** — that is `/ue-memory-stack:update`, and it needs the editor closed and the user's say-so.
