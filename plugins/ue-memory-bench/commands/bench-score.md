---
description: Judge a completed run, check judge agreement, and compare the arms
argument-hint: "[--passes 3] [--compare]"
allowed-tools: Bash, Read, Glob, Grep
---

Score a run that has already finished, then compare the arms. **Also spends model budget**: each judging pass is a model call per answer.

Arguments passed: `$ARGUMENTS`

## What to do

**1. Judge, more than once.** One pass is an opinion:

```powershell
python ${CLAUDE_PLUGIN_ROOT}/bench/tools/score_answers.py --pass 1
python ${CLAUDE_PLUGIN_ROOT}/bench/tools/score_answers.py --pass 2 --resume
python ${CLAUDE_PLUGIN_ROOT}/bench/tools/score_answers.py --pass 3 --resume
```

**2. Then ask whether the judge agreed with itself**, before believing anything it said:

```powershell
python ${CLAUDE_PLUGIN_ROOT}/bench/tools/judge_reliability.py
```

Report the agreement and the per-pass spread. **A verdict from a judge that disagrees with itself across passes is not evidence**, and the majority verdict is what counts.

**3. Compare the arms**, and read `route_split.py` as well as the headline:

```powershell
python ${CLAUDE_PLUGIN_ROOT}/bench/tools/compare_arms.py --baseline <results-baseline> --layers <results-layers> --scores <scores>
python ${CLAUDE_PLUGIN_ROOT}/bench/tools/route_split.py
```

## Reporting it honestly

- **Group figures carry weight; single-question figures do not.** One question is one sample.
- **Name what was excluded and why.** *QUESTION-DEFECTS.md* exists because broken questions were left in the set on purpose, and a figure that quietly drops them is a different figure.
- **Say "inferred" when a number is inferred.** Once a figure is in prose it reads exactly like a measured one.
- **Write the notes file.** `--notes` puts the caveats at the top of the comparison document, where somebody quoting the number will see them. A result document without them will be quoted without them.

If a question timed out, say so rather than scoring it as wrong: those are different failures, and only one of them is about the stack.
