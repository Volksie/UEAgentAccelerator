---
description: Check the memory stack in this tree and on this machine, and say what is broken and what fixes it
argument-hint: "[--json] [--skip-serena]"
allowed-tools: Bash, Read, Glob, Grep
---

Diagnose the memory stack. **Read-only: build nothing, regenerate nothing, change nothing.**

Arguments passed: `$ARGUMENTS`

## What to do

**1. Run it.** From the tree root, or pass `-Root`:

```powershell
${CLAUDE_PLUGIN_ROOT}/scripts/Test-MemoryStackHealth.ps1
```

Add `-Json` for `--json`, `-SkipSerena` for `--skip-serena`, and `-ProjectPath <uproject>` to check one project instead of every project in the config. Exit 1 means at least one FAIL.

**2. Read the verdicts as four different things, not two.**

| | |
|---|---|
| `OK` | Checked, and correct. |
| `WARN` | Checked, and probably wrong — or right and worth knowing. |
| `FAIL` | Checked, and wrong. Each one carries the remedy; quote it. |
| `UNKNOWN` | **Not checked.** The thing that would answer it is not available from a script. |

**`UNKNOWN` is not a pass, and reporting it as one is the failure this stack exists to prevent.** Two of them are structural rather than accidental: whether the running Serena actually exposes its tools needs a tool call from inside this session, and the dump stamps no format version into its output, so an old artefact set cannot be told from a current one by reading it. Say so in as many words.

**3. Then do the one thing the script cannot.** If it reports `UNKNOWN` on "server answers", try it here: ask for a symbol with `find_symbol_indexed` and use `search_for_pattern` once. A patched Serena that has not been restarted looks exactly like a working one from the file system, and this is the check that tells them apart. Report what happened.

**4. Report, in this order:** failures with their remedies, then what was not checked and why, then warnings, then a one-line summary. Do not bury a FAIL under a list of OKs, and do not offer to fix anything that needs a build without saying what it will cost — `/ue-memory-stack:update` closes the editor and takes minutes to tens of minutes.

## What it will not tell you

It compares file times for artefact staleness, which is the weak answer: a sync stamps every file with the time it wrote it. `/ue-memory-stack:status` does the revision comparison, which is the real one. If the doctor warns that artefacts look behind, that is a prompt to compare revisions rather than a verdict.

It also does not know whether your session actually loaded this plugin. If you are reading this, it did.
