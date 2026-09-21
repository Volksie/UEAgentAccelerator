---
name: ue-memory-bench
description: Measuring whether the UE memory stack actually helps on a tree, and what a measured figure is allowed to mean. Covers generating a question set from a project's own artefacts, the clean-room baseline arm, running an arm, multi-pass judging and judge agreement, comparing arms, and the version boundary that stops one run's number being quoted against another. Triggers on "benchmark the stack", "measure my tree", "did the artefacts help", "baseline arm", "score the run", "judge agreement", "is that number comparable".
---

# Measuring the stack

The point of measuring is to find out whether the layers help, which means the measurement has to be able to say no. Most of what follows exists because an earlier version of it said yes for the wrong reason.

## The four steps, and the trap in each

**1. A question set from the tree's own artefacts.** `${CLAUDE_PLUGIN_ROOT}/bench/tools/make_questions.py`, with a projects file in your own tree naming the projects (`projects.example.json` beside the tools shows the shape). Then **`check_keys.py`, always**: two published figures have been wrong because an answer key was, and in one case the arm under test had answered correctly and been scored wrong.

**2. A baseline arm that is built, not deleted.** The comparison is against a clean room — a tree containing what somebody would have without any of this — and `Build-BaselineRoot.ps1` builds it from an allowlist and verifies it. Isolation by moving files aside is a denylist, and a denylist missed something. **`baseline-isolation.ps1 -Mode Check` before any run**: a half-isolated tree produces a number that looks ordinary and means nothing.

**3. Running an arm.** `run_bench.py`, with each arm's tool surface defined by `${CLAUDE_PLUGIN_ROOT}/bench/arms.json` and passed with `--strict-mcp-config`, so an arm gets the tools the spec says rather than whatever the operator's machine happens to have.

**4. Judging, three times, then asking whether the judge agreed.** `score_answers.py` per pass, then `judge_reliability.py`. The majority verdict is the verdict. A judge that disagrees with itself across passes has not produced evidence, and the spread belongs in the write-up.

## What a figure is allowed to mean

- **A number belongs to a version of the stack.** Change the tree and the next run is a new version; the old figure does not carry across, and re-running is the only way to move it. `VERSION.md` in a tree exists for this.
- **Group figures carry weight. Single-question figures do not.**
- **Turns, not tokens, are the cost metric here**, and the reason is in *METHOD.md*: a token count reversed direction between two versions for reasons that had nothing to do with the stack.
- **Say "inferred" when a number is inferred.** A figure attributed to one cause and measured at another is the failure this whole document is guarding: 4,781 tokens a turn were once attributed to MCP schemas and measured at 102.

## Where the detail is

- `${CLAUDE_PLUGIN_ROOT}/bench/METHOD.md` — how questions are chosen, how isolation is proven, what each figure may claim.
- `${CLAUDE_PLUGIN_ROOT}/bench/BASELINE-ARM-SPEC.md` — what the baseline is and the argument for where the line sits.
- `${CLAUDE_PLUGIN_ROOT}/bench/QUESTION-DEFECTS.md` — the known-broken questions, kept on purpose, with what excluding them would change.
- `${CLAUDE_PLUGIN_ROOT}/bench/arm-comparison-v6.md` — the current recorded result, caveats first. v6 changed the question set, so it reports 139 shared questions and 52 new ones separately; only the 139 figure sits beside v5's verdicts on the same questions. The v5 and earlier documents are beside it and are superseded; no other figure in one compares with a figure in another.

## Not the same instrument as `claude plugin eval`

The stack plugin carries a small eval suite, and it answers a different question. `claude plugin eval` runs a sandboxed session with one plugin loaded and a fixture on disk, and asks whether the instructions route correctly — cheap, repeatable, per-commit. This benchmark asks whether a whole tree of real artefacts changes how well a real question gets answered — expensive, occasional, and versioned. Neither substitutes for the other, and a passing eval suite is not a result.
