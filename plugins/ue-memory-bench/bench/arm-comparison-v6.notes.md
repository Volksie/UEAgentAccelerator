**v6 is two question sets, and they are reported separately.** 139 questions carry over from v5 with their
text unchanged. 52 are new: group K (22) and 30 replacements in F and B. The new ones were drafted under
"removing one layer would change the answer", so **on the 52 the baseline arm is designed to fail.** A
figure over all 191 is a real measurement of a set built to produce it. It never appears alone, and only
the 139 figure is placed in a row with v5 (`BASELINE-ARM-SPEC.md`). The group tables below are over
all 191, because a group is either wholly shared or labelled mixed. Read them with that in mind.

**The headline. Partial credit (Y=1, P=0.5) is the metric v3–v5 published, and majority of three judge passes.**

| Set | Keys | Baseline | Layers | Gap |
|---|---|---|---|---|
| **139 shared, v5** | original keys | **69.8%** | **95.0%** | **+25.2** |
| **139 shared, v6** | original keys | **67.6%** | **92.1%** | **+24.5** |
| **139 shared, v5** | corrected | **71.6%** | **96.4%** | **+24.8** |
| **139 shared, v6** | corrected | **68.3%** | **95.0%** | **+26.6** |
| 52 new, v6 | as run | 63.5% | 92.3% | +28.8 |
| 52 new, v6 | corrected | 66.3% | 96.2% | +29.8 |

The four 139 rows are two like-for-like pairs with v5: same question text, both runs judged against
the same generation of keys. The original pair uses the keys each run was scored with. The corrected pair
uses the 2026-09-21 corrections, which apply to both versions wherever the truth did not change between
them (Q018, Q031, Q034, Q098, I16, D2). The v6 corrected row also carries the v6-only keys (Q019, J1,
J6, Q063). **v5's 170-question headline (97.1% vs 76.8% after its 2026-09-21 correction) must not be set
beside a 139 figure.** The 31 questions v6 removed were ones both arms passed, so v5 on the 139 is lower
than v5 on the 170. The split is computed by a script in the development tree that is not published here.

**On the same 139 questions, both arms scored slightly lower than in v5, and the gap did not move.** The layers arm
fell 2.9 points and the baseline 2.2. By question: the layers arm moved down on 12 and up on 4, the baseline down on 12
and up on 7. Two arms falling together by similar amounts points at something they share (the model on
the day, the judge, the run) rather than at the stack. v4 → v5 moved the layers arm +2.4 and that was
read as noise, so this is the same size in the other direction. **The defensible claim is the one v5
made: the stack's advantage on these questions is unchanged, about 25 points.** This run cannot support
"v6 improved the stack" or "v6 broke it".

**Nine of the layers arm's twelve drops are not explained by any key fix, and they are the list to look at
next:** D13, D8, E101, I14, I23, J5, Q003, Q012, Q016. Each went Y → P. Several are judgement calls the
judge split on across passes (D13, I23 and Q003 are on the unstable list below). None is an N.

**Eleven answer keys were wrong, and the corrected rows are secondary.** A decision taken before the run made it a second route to a key defect: every question the layers arm was marked down on was re-derived from the
store and the source before publication. There were 32 such questions and eleven of the keys were wrong:
F10, F14, K14, K20, Q018, Q031, Q034, Q063, Q098, I16, D2. The details are in `QUESTION-DEFECTS.md`
under *Decision-5 review of v6*, and the corrected keys are v6-scoped entries in the measuring tree's `answer-key-corrections.json`. The as-run verdicts were kept unchanged beside the rescored ones. **The corrections lift both
arms.** Working from source alone, the baseline reached the same corrected answers on Q031 (43), K14
(both functions) and D2 (the comment is false). That is independent confirmation of each fix, and it is
why the corrected gap is only about 2 points wider than the as-run one. **The review was one-sided by
design:** it looked only where the layers arm lost credit.

**The group tables below use the CORRECTED keys**, as v5's did after its Q019 fix. Every cost figure is
unaffected by keys.

**Six of these defects are older than v6, and v5 has been corrected for them (2026-09-21).** Q018's key said the largest native parent is LyraGameplayAbility with 21. v5's layers arm
answered **UserWidget, 55**, quoting the same table the v6 store gives, and had been marked N on all three
passes. Q018, Q034, Q031, Q098, I16 and D2 now carry v5 keys, and v5 was re-judged on them from its
recorded answers. v5's headline moves from 95.9% vs 75.3% to **97.1% vs 76.8%**, and its layers arm now
has no outright-wrong answers. Under the corrected keys the same-139 comparison is layers 96.4 -> 95.0 and
baseline 71.6 -> 68.3: **the gap held at about 25 under either generation of keys.**

**Cost is where v6 differs most, and the split matters more here than for accuracy.**

| Set | Arm | Median s | Median turns | Total hours | Tokens in | Tokens out | Timeouts |
|---|---|---|---|---|---|---|---|
| 139 shared | baseline | 44.1 | 8 | 3.59 | 27.8M | 0.88M | 0 |
| 139 shared | layers | 27.6 | 6 | 1.21 | 12.9M | 0.28M | 0 |
| 52 new | baseline | 160.8 | 22.5 | 3.38 | 23.8M | 0.77M | 2 |
| 52 new | layers | 28.6 | 6 | 0.54 | 6.5M | 0.13M | 0 |

**On the 139 shared, the stack answers in 1.6x less median time and 3.0x less total time, and uses 2.2x
fewer input tokens.** On the 52 new questions the baseline's median is 5.6x the layers' and its total 6.3x,
because those questions are where it has to reconstruct from bytes what a layer holds. The two baseline
timeouts (K5 and K17, both 900s with no answer) are in the new set, and their wall time is the ceiling, not
a measurement. The layers arm's cost barely differs between the two sets (27.6s against 28.6s median).
Nearly all of the difference between them is the baseline's.

**Correct is the MAJORITY of three judging passes.** Each of the 382 measurements was judged three times.
**93.7% were unanimous (358 of 382)**, every disagreement was between neighbouring grades (18 P/Y, 6 N/P),
and **there were zero Y↔N reversals**. That is a little less stable than v5's 95.9%. **One possible reason,
which has not been measured**, is that the new REQUIRED/BONUS/FAIL_IF keys give the judge more room to weigh a
partial answer.
`tools/judge_reliability.py --tag v6`.

**Twenty-four measurements are unstable and must not be quoted individually.** Baseline: B11, I1, I18,
I20, I27, J2, K16, K19, K9, Q009, Q020, Q048, Q050, Q055, Q070, Q076. Layers: D13, E102, F12, F5, I23, I27,
I29, Q003.

**What this repository ships is not exactly what was measured.** The layers for this run were generated before either arm started, from the plugin as it stood at 0.4.0. Since then the generator writes its artefacts with Windows line endings through one helper, which changes their **byte sizes** but not a word of their content, and the plugin now declares its `EnhancedInput` dependency in the .uplugin. The Serena launcher gained a warm-up and a `-Stop`, which are Layer 1 operations rather than anything a question reads. None of that changes an answer, but by this repository's own rule the next measured run is v7, and *CHANGELOG.md* lists what has moved.

**The baseline arm was run twice, and the second run is the measured one.** The first attempt hit the
account's session limit mid-run. Every question after that point was recorded with the platform's refusal
("You've hit your session limit") as its answer, and one expensive question (B8: 51 turns, 1.28M tokens)
had its real answer replaced by the refusal. That run is quarantined rather than deleted, because it is the evidence. **`run_bench.py --resume` now refuses to count
such a row as done**, and it reports any error row it keeps as unclassified rather than treating it as
recorded. A genuine timeout, such as K5 or K17 here, is kept as a measurement. The measured baseline run
started from scratch, so all 191 questions ran under one harness version.

**Same model in both arms, and the same model as every earlier run: opus.** Switching the arms to a
cheaper model was considered and rejected, because on the 139 shared questions it would make the model a
confound in the only comparison with v5.
