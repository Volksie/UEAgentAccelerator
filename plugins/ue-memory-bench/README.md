# ue-memory-bench

The benchmark behind the stack's published numbers, as a Claude Code plugin. It generates a question set from your own project's artefacts, builds a clean-room baseline arm to measure against, runs both arms, judges the answers more than once, and says what the resulting figure is allowed to mean.

```bash
claude plugin marketplace add Volksie/UEAgentAccelerator
claude plugin install ue-memory-bench@ue-agent-accelerator --scope project
```

Install it alongside `ue-memory-stack` only if you want to measure. Nobody adding the stack to a game needs the question generator, the clean-room builder or the judging tools, and its skill would compete with the ones that matter day to day.

## What you get

| | |
|---|---|
| `/ue-memory-bench:bench-run` | Run one arm, with the checks that stop a half-isolated tree producing a number |
| `/ue-memory-bench:bench-score` | Judge a finished run three times, check the judge agreed with itself, compare the arms |
| `ue-memory-bench` (skill) | The method: what each step is for, and what a figure may claim |

## What is inside

| Path | What it is |
|---|---|
| `bench/tools/` | The harness: question generation, key checking, clean-room build, runner, judge, comparison |
| `bench/METHOD.md` | How questions are chosen, how isolation is proven, what each figure may mean |
| `bench/BASELINE-ARM-SPEC.md` | What the arm is measured against, and the argument for where that line sits |
| `bench/QUESTION-DEFECTS.md` | The known-broken questions, kept on purpose, with what excluding them would change |
| the `arm-comparison` documents under `bench/` | The recorded results, caveats first |

The harness is Python and uses the standard library only. It runs against **your** tree, so give it `--root`: the tools find a tree by searching upwards for `bench/projects.json`, and inside this plugin that search finds the plugin.

## Before you quote a number from it

**A figure belongs to a version of the stack.** Change the tree and the next run is a new version; the old number does not carry across, and re-running is the only way to move it. Group figures carry weight; single-question figures do not. And the caveats at the top of a comparison document are part of the result rather than decoration — two published figures here have been wrong, both times because an answer key was, and one of those had scored a correct answer as wrong.

## This is not the eval suite

`ue-memory-stack` carries a small `claude plugin eval` suite that asks whether the instructions route a session to the right artefact, on a fixture, for cents. This asks whether a whole tree of real artefacts changes how well real questions get answered, for hours and a real bill. A passing eval suite is not a result, and these numbers are not a regression test.

## Licence

MIT, beside this file. The harness is ours; the projects you point it at are yours.
