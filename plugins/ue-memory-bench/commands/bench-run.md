---
description: Run one arm of the benchmark over this tree's question set
argument-hint: "[baseline|layers] [--room] [--smoke]"
allowed-tools: Bash, Read, Glob, Grep
---

Run a benchmark arm. **This spends real model budget and takes a long time. Say what it will cost and wait for a yes before starting.**

Arguments passed: `$ARGUMENTS`

## Before anything

**1. Is the tree ready?** The question set and the runset have to exist, and a run against a half-isolated tree is worse than no run:

```powershell
python ${CLAUDE_PLUGIN_ROOT}/bench/tools/check_keys.py --root <tree> --questions <tree>/bench/questions.json
${CLAUDE_PLUGIN_ROOT}/bench/tools/baseline-isolation.ps1 -Mode Check
```

**2. Say the cost out loud.** Both arms, three judge passes, the full set: that is hours and a real bill. The `--smoke` form exists for checking the plumbing, and is what you want the first time.

**3. Check nothing is holding the tree.** A shell whose working directory is inside `bench/` makes isolation fail with "file in use", and a half-applied isolation is the one way to get a number that looks fine and means nothing.

## Running it

```powershell
python ${CLAUDE_PLUGIN_ROOT}/bench/tools/run_bench.py --arm layers
python ${CLAUDE_PLUGIN_ROOT}/bench/tools/run_bench.py --arm baseline --isolation room
```

The baseline arm is not "the same tree with the artefacts deleted". It is a built clean room, and `Build-BaselineRoot.ps1` builds and verifies it. *BASELINE-ARM-SPEC.md* is the argument for where that line is drawn, and reading it is the difference between a number and a claim.

## Afterwards

Report what ran, what the exit code was, and **what is not yet scored** — a finished run is not a result. Scoring is `/ue-memory-bench:bench-score`. Do not compute or quote a headline figure from raw answers.

**And do not compare across versions.** A figure belongs to the version of the stack that produced it. If the tree has changed since the last recorded run, the next run is a new version and the old number does not carry across. *METHOD.md* says why in more detail than anybody wants until the first time it matters.
