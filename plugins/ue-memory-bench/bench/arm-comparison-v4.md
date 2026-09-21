# Baseline vs with-layers: the paired comparison

> ### Read this before quoting any number below
>
> **Group medians carry weight. Single-question figures do not.** Run-to-run variance on
> the same question, under identical conditions, is about **40% on tool calls and 20% on
> seconds**, measured over 140 questions that were run twice. Q078 moved from 274.8s to
> 109.5s between two runs of itself; Q063 moved from 275.0s to 644.5s. Any claim about an
> individual question needs repeats before it means anything.
>
> **Route is not an arm-vs-arm metric and is no longer reported as one.** Most expected
> routes name a layer artefact, and the baseline arm runs in a clean room that has never
> held one, so it cannot match them whatever it answers. Run `tools/route_split.py`
> for the split that means something.
>
> **One route in this run was scored against a wrong expectation, found afterwards.** Q008's
> expected route named two of the three places the fact lives, so the layers arm was marked
> route_match=N on all three passes for reaching it through the third. **Correctness does not
> move**; the layers route-match figure here is one question pessimistic. The figures below are
> what the run *did* score and are left alone deliberately - a rescore with
> `expected-routes-corrections.json` present reports what it *should* have scored, and the two
> must not be quoted as one number. `QUESTION-DEFECTS.md` has what was checked.
>
> **This is v4. No figure here compares with v3, and the baseline arm moved as well.** The baseline
> arm's mean input tokens per question rose from **97,294 on v3 to 161,479 here** (median 47,046 to
> 70,148). What changed is measured. Sessions reached for Bash instead of the built-in Grep, Read and
> Glob, from the first call on: 53 of v3's 162 non-J questions opened with a shell command, 90 here, and
> Bash calls went from 751 to 1,286. They took more, smaller steps: cache writes are unchanged (1.98M
> against 1.94M) while cache reads rose 75%. Eight sessions passed 40 turns, against two. **Why is not
> proven.** One difference is established: 162 of v3's 170 baseline questions ran with a standing
> context of **6,336 tokens**, and every run since 23:26 UTC on 11 September has had 7,307 or more. That
> includes v3's group J rerun, all of v3's layers arm, and both v4 arms. The 971 tokens appeared in both
> arms at once, on the same CLI build, when the run's model flag changed from `claude-opus-5` to `opus`.
> Today both flags give the same floor, so the old context cannot be reproduced or inspected. Ruled
> out: effort level, the launching shell, and auto-memory. So v4's two arms share one standing context
> and v3's did not. The overall 1.33x is partly the layers getting faster and partly the baseline getting
> slower. Quote it as a v4 number only.
>
> **Correct is the MAJORITY of three judging passes, and the error bar is small.** Here 340
> measurements were each judged three times: **96.2% unanimous (327 of 340)**, every disagreement
> adjacent (8 P/Y, 5 N/P) and **none Y->N**. Per-pass credit varied by **0.6 points on the baseline
> arm and 0.3 on the layers arm**. Re-measured on this set rather than carried over:
> `tools/judge_reliability.py --tag v4`.
>
> **One baseline question timed out, and it stands.** Q019 reached the 900s ceiling twice; the rule is
> one rerun, so it counts as no answer and scored N on all three passes. Its 900s is the ceiling, not a
> measurement, so its 28x at the top of the per-question table means nothing. No layers question came
> near the ceiling (slowest E102 at 281s), and nothing was re-run at 1800s. v3's I22 note is dropped:
> that question had already been reworded before v3 ran, and it scored Y in both arms here.
>
> **The baseline room exposed the run's own metadata, in v3 and in v4 alike.** Its root held
> `.baseline-manifest.json` (tree path, per-directory file counts) and the `BENCH-RUN-IN-PROGRESS.md`
> lock. Neither contains answer-key content. The cost is a session that knows it is being measured,
> plus the turns it spends on these files. Sessions reading the manifest and the lock, out of 170: **v3 49 and 60, v4 25 and 50**.
> By group, manifest/lock of n, v3 then v4: A 5/7, 1/3 of 20 · B 5/5, 2/5 of 20 · C 0/0, 0/0 of 20 ·
> D 4/5, 1/3 of 15 · E 12/14, 8/16 of 22 · F 1/0, 1/2 of 15 · G 1/3, 0/1 of 10 · H 4/3, 1/2 of 10 ·
> I 13/18, 7/14 of 30 · J 4/5, 4/4 of 8. Concentrated in E and I. **Do not compare exposed with
> unexposed scores:** a long, floundering session both reads more and scores worse, so the two are
> confounded. Recorded by decision rather than fixed mid-run; fixed before any later run.
>
> **What v4 changed, all of it Layer 1 or the harness (see `VERSION.md`):** Serena's per-call file
> walk was patched out, so symbolic tools reach clangd within the 45s timeout. `find_symbol_indexed`
> and `search_for_pattern` are exposed, and `CLAUDE.md` routes "where is X defined" to them. Group D
> design prose was written into the seed project's `Docs/Design/`. The J1 and J5 keys were corrected. The
> harness gained a clangd-index gate and an MCP probe. Framing: v3 with Layer 1 working as designed.

> **This document is the v4 record, and is left as generated. v5 is in *arm-comparison-v5.md* and is the current result.** No figure here compares with one there. One key
> behind a figure here was later found wrong and rescored: Q019 moves the layers arm from 93.2% to
> **93.5%** and the gap from 18.8 to **19.1** points. This document keeps what the run scored, which
> is the rule; `QUESTION-DEFECTS.md` has the correction and what it moves in each run.

Generated by `tools/compare_arms.py`. Regenerate rather than hand edit.

Both arms ran **the same 170 questions**, on the same harness. They did NOT run against the same tree: the baseline arm runs in a clean room built beside it, holding only source, config and content, while the layers arm runs in the tree. Their standing floors differ and are recorded per arm in each run's meta file; nothing below subtracts them. Every figure is a **group median**; representative and coverage sets are never pooled.

- Baseline: 170 measurements over 170 questions (some measured twice)
- With layers: 170 measurements over 170 questions
- Errors or timeouts in either arm: **1**

## Per group

A speedup means nothing without accuracy beside it, so Correct sits in the same table. **Correct** is percent with partial credit (Y=1, P=0.5, N=0); **Y/P/N** is the raw split, because one percentage cannot distinguish a near miss from an invention.

| Group | What | Base s | Layer s | **Speedup** | Base calls | Layer calls | **Base Correct** | **Layer Correct** | Base Y/P/N | Layer Y/P/N |
|---|---|---|---|---|---|---|---|---|---|---|
| A | Structure: definition sites, property types | 23.8 | 25.4 | **0.94x** | 4 | 4 | **70%** | **88%** | 11/6/3 | 16/3/1 |
| B | Inheritance and ancestry | 41.9 | 25.2 | **1.66x** | 10 | 5 | **90%** | **92%** | 16/4/0 | 17/3/0 |
| C | Reflection: specifiers, replication | 29.9 | 26.6 | **1.12x** | 4 | 4 | **85%** | **98%** | 16/2/2 | 19/1/0 |
| D | Comments and documentation | 43.0 | 39.4 | **1.09x** | 9 | 6 | **73%** | **97%** | 10/2/3 | 14/1/0 |
| E | Blueprint blast radius | 160.8 | 60.0 | **2.68x** | 22 | 7 | **82%** | **91%** | 15/6/1 | 18/4/0 |
| F | Negation: absence of replication | 24.7 | 21.5 | **1.15x** | 4 | 3 | **100%** | **97%** | 15/0/0 | 14/1/0 |
| G | Traps: non-existence and ambiguity | 19.6 | 31.9 | **0.61x** | 4 | 6 | **90%** | **100%** | 8/2/0 | 10/0/0 |
| H | Engine API surface | 48.7 | 41.7 | **1.17x** | 10 | 8 | **30%** | **90%** | 2/2/6 | 9/0/1 |
| I | Build, tooling and procedure | 59.0 | 88.7 | **0.67x** | 10 | 11 | **53%** | **93%** | 10/12/8 | 26/4/0 |
| J | Performance: the static determinants of cost | 131.9 | 109.7 | **1.20x** | 21 | 16 | **69%** | **88%** | 4/3/1 | 6/2/0 |
| | **Overall** | **49.5** | **37.2** | **1.33x** | **8** | **6** | **74%** | **93%** | 107/39/24 | 149/19/2 |

Retrieval, median KB: baseline 8.1, with layers 5.5.

**Turns**, the cost metric: baseline 2,251, with layers 1,442 (**1.56x**). A turn is one model call, so it is what the standing context is actually paid on.

**Input tokens**, mean per question, floors included: baseline 161,479, with layers 121,502 (**1.33x**).

## Where the layers earn their keep, and where they do not

Ranked by speedup:

- **E Blueprint blast radius** - 2.68x
- **B Inheritance and ancestry** - 1.66x
- **J Performance: the static determinants of cost** - 1.20x
- **H Engine API surface** - 1.17x
- **F Negation: absence of replication** - 1.15x
- **C Reflection: specifiers, replication** - 1.12x
- **D Comments and documentation** - 1.09x
- **A Structure: definition sites, property types** - 0.94x
- **I Build, tooling and procedure** - 0.67x
- **G Traps: non-existence and ambiguity** - 0.61x

The spread across groups is the finding, not the overall number. A group where the layers barely help is either a question-design problem (the answer was reachable without them) or a routing problem (`CLAUDE.md` does not name the artefact for that question shape). Both are worth chasing; the second is the one the standing lesson in `BASELINE-ARM-SPEC.md` warns about.

## Biggest per-question differences

| id | Group | Baseline s | Layers s | Speedup |
|---|---|---|---|---|
| Q019 | A | 900.0 | 31.9 | 28.21x |
| Q005 | A | 341.2 | 22.1 | 15.44x |
| Q014 | A | 293.8 | 20.3 | 14.47x |
| Q018 | A | 371.1 | 25.7 | 14.44x |
| Q077 | E | 252.0 | 21.5 | 11.72x |
| Q071 | E | 246.7 | 24.1 | 10.24x |
| Q065 | E | 193.4 | 21.5 | 9.00x |
| Q062 | E | 419.0 | 49.5 | 8.46x |
| Q072 | E | 564.1 | 82.1 | 6.87x |
| Q030 | B | 177.8 | 27.0 | 6.59x |
| Q031 | B | 630.6 | 101.4 | 6.22x |
| Q068 | E | 466.8 | 82.8 | 5.64x |
| I8 | I | 58.1 | 10.5 | 5.53x |
| Q016 | A | 217.2 | 40.3 | 5.39x |
| Q041 | C | 190.9 | 35.8 | 5.33x |

Slowest with the layers than without, if any:

| id | Group | Baseline s | Layers s | Ratio |
|---|---|---|---|---|
| D1 | D | 19.2 | 147.1 | 0.13x |
| I5 | I | 19.1 | 106.0 | 0.18x |
| Q011 | A | 47.7 | 256.6 | 0.19x |
| Q006 | A | 23.0 | 97.5 | 0.24x |
| I12 | I | 30.1 | 117.6 | 0.26x |
| J7 | J | 24.5 | 85.4 | 0.29x |
| G7 | G | 30.0 | 104.4 | 0.29x |
| E102 | E | 89.4 | 280.6 | 0.32x |
| I24 | I | 43.5 | 135.7 | 0.32x |
| I4 | I | 50.0 | 137.4 | 0.36x |
| E101 | E | 58.8 | 151.2 | 0.39x |
| G3 | G | 15.1 | 37.4 | 0.40x |
| Q003 | A | 19.1 | 47.1 | 0.41x |
| Q096 | H | 38.9 | 93.9 | 0.41x |
| I18 | I | 59.9 | 142.2 | 0.42x |
