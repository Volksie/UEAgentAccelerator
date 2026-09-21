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
> **v6 is two question sets, and they are reported separately.** 139 questions carry over from v5 with their
> text unchanged. 52 are new: group K (22) and 30 replacements in F and B. The new ones were drafted under
> "removing one layer would change the answer", so **on the 52 the baseline arm is designed to fail.** A
> figure over all 191 is a real measurement of a set built to produce it. It never appears alone, and only
> the 139 figure is placed in a row with v5 (`BASELINE-ARM-SPEC.md`). The group tables below are over
> all 191, because a group is either wholly shared or labelled mixed. Read them with that in mind.
>
> **The headline. Partial credit (Y=1, P=0.5) is the metric v3–v5 published, and majority of three judge passes.**
>
> | Set | Keys | Baseline | Layers | Gap |
> |---|---|---|---|---|
> | **139 shared, v5** | original keys | **69.8%** | **95.0%** | **+25.2** |
> | **139 shared, v6** | original keys | **67.6%** | **92.1%** | **+24.5** |
> | **139 shared, v5** | corrected | **71.6%** | **96.4%** | **+24.8** |
> | **139 shared, v6** | corrected | **68.3%** | **95.0%** | **+26.6** |
> | 52 new, v6 | as run | 63.5% | 92.3% | +28.8 |
> | 52 new, v6 | corrected | 66.3% | 96.2% | +29.8 |
>
> The four 139 rows are two like-for-like pairs with v5: same question text, both runs judged against
> the same generation of keys. The original pair uses the keys each run was scored with. The corrected pair
> uses the 2026-09-21 corrections, which apply to both versions wherever the truth did not change between
> them (Q018, Q031, Q034, Q098, I16, D2). The v6 corrected row also carries the v6-only keys (Q019, J1,
> J6, Q063). **v5's 170-question headline (97.1% vs 76.8% after its 2026-09-21 correction) must not be set
> beside a 139 figure.** The 31 questions v6 removed were ones both arms passed, so v5 on the 139 is lower
> than v5 on the 170. The split is computed by a script in the development tree that is not published here.
>
> **On the same 139 questions, both arms scored slightly lower than in v5, and the gap did not move.** The layers arm
> fell 2.9 points and the baseline 2.2. By question: the layers arm moved down on 12 and up on 4, the baseline down on 12
> and up on 7. Two arms falling together by similar amounts points at something they share (the model on
> the day, the judge, the run) rather than at the stack. v4 → v5 moved the layers arm +2.4 and that was
> read as noise, so this is the same size in the other direction. **The defensible claim is the one v5
> made: the stack's advantage on these questions is unchanged, about 25 points.** This run cannot support
> "v6 improved the stack" or "v6 broke it".
>
> **Nine of the layers arm's twelve drops are not explained by any key fix, and they are the list to look at
> next:** D13, D8, E101, I14, I23, J5, Q003, Q012, Q016. Each went Y → P. Several are judgement calls the
> judge split on across passes (D13, I23 and Q003 are on the unstable list below). None is an N.
>
> **Eleven answer keys were wrong, and the corrected rows are secondary.** A decision taken before the run made it a second route to a key defect: every question the layers arm was marked down on was re-derived from the
> store and the source before publication. There were 32 such questions and eleven of the keys were wrong:
> F10, F14, K14, K20, Q018, Q031, Q034, Q063, Q098, I16, D2. The details are in `QUESTION-DEFECTS.md`
> under *Decision-5 review of v6*, and the corrected keys are v6-scoped entries in the measuring tree's `answer-key-corrections.json`. The as-run verdicts were kept unchanged beside the rescored ones. **The corrections lift both
> arms.** Working from source alone, the baseline reached the same corrected answers on Q031 (43), K14
> (both functions) and D2 (the comment is false). That is independent confirmation of each fix, and it is
> why the corrected gap is only about 2 points wider than the as-run one. **The review was one-sided by
> design:** it looked only where the layers arm lost credit.
>
> **The group tables below use the CORRECTED keys**, as v5's did after its Q019 fix. Every cost figure is
> unaffected by keys.
>
> **Six of these defects are older than v6, and v5 has been corrected for them (2026-09-21).** Q018's key said the largest native parent is LyraGameplayAbility with 21. v5's layers arm
> answered **UserWidget, 55**, quoting the same table the v6 store gives, and had been marked N on all three
> passes. Q018, Q034, Q031, Q098, I16 and D2 now carry v5 keys, and v5 was re-judged on them from its
> recorded answers. v5's headline moves from 95.9% vs 75.3% to **97.1% vs 76.8%**, and its layers arm now
> has no outright-wrong answers. Under the corrected keys the same-139 comparison is layers 96.4 -> 95.0 and
> baseline 71.6 -> 68.3: **the gap held at about 25 under either generation of keys.**
>
> **Cost is where v6 differs most, and the split matters more here than for accuracy.**
>
> | Set | Arm | Median s | Median turns | Total hours | Tokens in | Tokens out | Timeouts |
> |---|---|---|---|---|---|---|---|
> | 139 shared | baseline | 44.1 | 8 | 3.59 | 27.8M | 0.88M | 0 |
> | 139 shared | layers | 27.6 | 6 | 1.21 | 12.9M | 0.28M | 0 |
> | 52 new | baseline | 160.8 | 22.5 | 3.38 | 23.8M | 0.77M | 2 |
> | 52 new | layers | 28.6 | 6 | 0.54 | 6.5M | 0.13M | 0 |
>
> **On the 139 shared, the stack answers in 1.6x less median time and 3.0x less total time, and uses 2.2x
> fewer input tokens.** On the 52 new questions the baseline's median is 5.6x the layers' and its total 6.3x,
> because those questions are where it has to reconstruct from bytes what a layer holds. The two baseline
> timeouts (K5 and K17, both 900s with no answer) are in the new set, and their wall time is the ceiling, not
> a measurement. The layers arm's cost barely differs between the two sets (27.6s against 28.6s median).
> Nearly all of the difference between them is the baseline's.
>
> **Correct is the MAJORITY of three judging passes.** Each of the 382 measurements was judged three times.
> **93.7% were unanimous (358 of 382)**, every disagreement was between neighbouring grades (18 P/Y, 6 N/P),
> and **there were zero Y↔N reversals**. That is a little less stable than v5's 95.9%. **One possible reason,
> which has not been measured**, is that the new REQUIRED/BONUS/FAIL_IF keys give the judge more room to weigh a
> partial answer.
> `tools/judge_reliability.py --tag v6`.
>
> **Twenty-four measurements are unstable and must not be quoted individually.** Baseline: B11, I1, I18,
> I20, I27, J2, K16, K19, K9, Q009, Q020, Q048, Q050, Q055, Q070, Q076. Layers: D13, E102, F12, F5, I23, I27,
> I29, Q003.
>
> **What this repository ships is not exactly what was measured.** The layers for this run were generated before either arm started, from the plugin as it stood at 0.4.0. Since then the generator writes its artefacts with Windows line endings through one helper, which changes their **byte sizes** but not a word of their content, and the plugin now declares its `EnhancedInput` dependency in the .uplugin. The Serena launcher gained a warm-up and a `-Stop`, which are Layer 1 operations rather than anything a question reads. None of that changes an answer, but by this repository's own rule the next measured run is v7, and *CHANGELOG.md* lists what has moved.
>
> **The baseline arm was run twice, and the second run is the measured one.** The first attempt hit the
> account's session limit mid-run. Every question after that point was recorded with the platform's refusal
> ("You've hit your session limit") as its answer, and one expensive question (B8: 51 turns, 1.28M tokens)
> had its real answer replaced by the refusal. That run is quarantined rather than deleted, because it is the evidence. **`run_bench.py --resume` now refuses to count
> such a row as done**, and it reports any error row it keeps as unclassified rather than treating it as
> recorded. A genuine timeout, such as K5 or K17 here, is kept as a measurement. The measured baseline run
> started from scratch, so all 191 questions ran under one harness version.
>
> **Same model in both arms, and the same model as every earlier run: opus.** Switching the arms to a
> cheaper model was considered and rejected, because on the 139 shared questions it would make the model a
> confound in the only comparison with v5.

Generated by `tools/compare_arms.py`. Regenerate rather than hand edit.

Both arms ran **the same 191 questions**, on the same harness. They did NOT run against the same tree: the baseline arm runs in a clean room built beside it, holding only source, config and content, while the layers arm runs in the tree. Their standing floors differ and are recorded per arm in each run's meta file; nothing below subtracts them. Every figure is a **group median**; representative and coverage sets are never pooled.

- Baseline: 191 measurements over 191 questions (some measured twice)
- With layers: 191 measurements over 191 questions
- Errors or timeouts in either arm: **2**

## Per group

A speedup means nothing without accuracy beside it, so Correct sits in the same table. **Correct** is percent with partial credit (Y=1, P=0.5, N=0); **Y/P/N** is the raw split, because one percentage cannot distinguish a near miss from an invention.

| Group | What | Base s | Layer s | **Speedup** | Base calls | Layer calls | **Base Correct** | **Layer Correct** | Base Y/P/N | Layer Y/P/N |
|---|---|---|---|---|---|---|---|---|---|---|
| A | Structure: definition sites, property types | 25.4 | 30.3 | **0.84x** | 5 | 4 | **78%** | **90%** | 13/5/2 | 16/4/0 |
| B | Inheritance and ancestry | 180.7 | 29.0 | **6.23x** | 27 | 6 | **63%** | **92%** | 8/8/3 | 16/3/0 |
| C | Reflection: specifiers, replication | 30.9 | 18.6 | **1.67x** | 4 | 3 | **80%** | **98%** | 15/2/3 | 19/1/0 |
| D | Comments and documentation | 42.4 | 17.9 | **2.37x** | 7 | 4 | **70%** | **93%** | 9/3/3 | 13/2/0 |
| E | Blueprint blast radius | 110.7 | 31.0 | **3.57x** | 22 | 5 | **82%** | **95%** | 15/6/1 | 20/2/0 |
| F | Effective flags, replication, writers (v6 replacements) | 55.6 | 26.4 | **2.11x** | 9 | 4 | **87%** | **93%** | 12/2/1 | 13/2/0 |
| G | Traps: non-existence and ambiguity | 26.1 | 20.8 | **1.26x** | 4 | 6 | **95%** | **100%** | 9/1/0 | 10/0/0 |
| H | Engine API surface | 43.5 | 18.2 | **2.39x** | 8 | 2 | **20%** | **100%** | 1/2/7 | 10/0/0 |
| I | Build, tooling and procedure | 39.2 | 32.1 | **1.22x** | 6 | 6 | **52%** | **95%** | 10/11/9 | 27/3/0 |
| J | Performance: the static determinants of cost | 41.2 | 33.6 | **1.23x** | 6 | 6 | **62%** | **94%** | 3/4/1 | 7/1/0 |
| K | Blueprint tier: one layer changes the answer (v6) | 191.8 | 31.4 | **6.11x** | 26 | 6 | **57%** | **100%** | 10/5/7 | 22/0/0 |
| | **Overall, all 191 - see the preamble for the split** | **55.3** | **27.8** | **1.99x** | **9** | **5** | **68%** | **95%** | 105/49/37 | 173/18/0 |

Retrieval, median KB: baseline 9.5, with layers 6.1.

**Turns**, the cost metric: baseline 3,254, with layers 1,268 (**2.57x**). A turn is one model call, so it is what the standing context is actually paid on.

**Input tokens**, mean per question, floors included: baseline 270,312, with layers 101,552 (**2.66x**).

## Where the layers earn their keep, and where they do not

Ranked by speedup:

- **B Inheritance and ancestry** - 6.23x
- **K Blueprint tier: one layer changes the answer (v6)** - 6.11x
- **E Blueprint blast radius** - 3.57x
- **H Engine API surface** - 2.39x
- **D Comments and documentation** - 2.37x
- **F Effective flags, replication, writers (v6 replacements)** - 2.11x
- **C Reflection: specifiers, replication** - 1.67x
- **G Traps: non-existence and ambiguity** - 1.26x
- **J Performance: the static determinants of cost** - 1.23x
- **I Build, tooling and procedure** - 1.22x
- **A Structure: definition sites, property types** - 0.84x

The spread across groups is the finding, not the overall number. A group where the layers barely help is either a question-design problem (the answer was reachable without them) or a routing problem (`CLAUDE.md` does not name the artefact for that question shape). Both are worth chasing; the second is the one the standing lesson in `BASELINE-ARM-SPEC.md` warns about.

## Biggest per-question differences

| id | Group | Baseline s | Layers s | Speedup |
|---|---|---|---|---|
| Q014 | A | 827.7 | 13.7 | 60.42x |
| K5 | K | 900.1 | 19.6 | 45.92x |
| K20 | K | 865.0 | 19.2 | 45.05x |
| B8 | B | 567.5 | 18.2 | 31.18x |
| Q062 | E | 460.2 | 18.4 | 25.01x |
| F5 | F | 465.4 | 19.1 | 24.37x |
| K17 | K | 900.0 | 37.1 | 24.26x |
| K12 | K | 778.6 | 34.3 | 22.70x |
| K11 | K | 458.5 | 22.1 | 20.75x |
| Q072 | E | 824.8 | 40.1 | 20.57x |
| Q068 | E | 368.2 | 22.1 | 16.66x |
| Q018 | A | 546.4 | 34.1 | 16.02x |
| K8 | K | 393.8 | 26.7 | 14.75x |
| B14 | B | 492.1 | 33.8 | 14.56x |
| B15 | B | 344.9 | 25.3 | 13.63x |

Slowest with the layers than without, if any:

| id | Group | Baseline s | Layers s | Ratio |
|---|---|---|---|---|
| Q009 | A | 24.1 | 146.1 | 0.16x |
| Q011 | A | 108.4 | 296.4 | 0.37x |
| G3 | G | 24.7 | 64.3 | 0.38x |
| Q004 | A | 13.8 | 30.6 | 0.45x |
| G1 | G | 20.4 | 43.4 | 0.47x |
| Q003 | A | 23.2 | 46.8 | 0.50x |
| Q001 | A | 16.7 | 32.4 | 0.52x |
| Q017 | A | 23.2 | 43.4 | 0.53x |
| G4 | G | 21.1 | 38.3 | 0.55x |
| Q006 | A | 26.6 | 45.2 | 0.59x |
| K1 | K | 19.6 | 30.5 | 0.64x |
| I10 | I | 50.6 | 71.5 | 0.71x |
| I19 | I | 23.5 | 32.6 | 0.72x |
| J7 | J | 34.3 | 47.2 | 0.73x |
| I25 | I | 47.2 | 64.8 | 0.73x |
