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
> **CORRECTED AGAIN 2026-09-21: six more answer keys were wrong, found while scoring v6.** The v6 run
> exposed eleven wrong keys. Six of them concern facts that nothing between v5 and v6 changed: native
> parents, the native class hierarchy, engine plugin descriptors and MemBench source. So the same keys were
> wrong for v5 too: Q018, Q034, Q031, Q098, I16 and D2. For example, v5's layers arm answered Q018 with
> **UserWidget, 55**, which is right, and was marked N on all three passes. Both arms were re-judged on those six from the recorded answers, three passes each, and the 2026-09-19 verdicts are kept beside the rescored ones.
> Details are in `QUESTION-DEFECTS.md` under *Decision-5 review of v6*.
>
> **Every figure below is now the twice-corrected one.** Partial credit is **76.8% baseline against 97.1%
> layers**, a gap of **20.3 points**. The 2026-09-19 figures were 75.3%, 95.9% and 20.6. **The layers
> arm's outright-wrong count goes from 2 to 0.** Both arms rise, because the baseline had also reached
> several of the true answers from source (Q018, Q031, Q034), so the gap narrows slightly rather than
> widening. No cost, median or route figure moves. The paragraphs below still quote the 2026-09-19 figures
> where they describe that correction and the drift; read those as history.
>
> **CORRECTED 2026-09-19, after first publication. One answer key was wrong.** Q019's key said "14
> Blueprints, 30 call nodes" for `ULyraInventoryItemInstance::GetStatTagStackCount`. 14 is the artefact's
> ROW count — one row per (Blueprint, graph) — and the Blueprint count is 12; `GA_Weapon_ReloadMagazine`
> alone contributes three graphs. The layers arm answered **12 Blueprints / 30 nodes**, which is right, and
> was marked P for contradicting the key — in v3, v4 and v5 alike, nine judging passes in total. Rescored
> from the recorded answers under a corrected key (`answer-key-corrections.json`): **layers Q019 P →
> Y in all three passes**. The baseline timed out on this question and is unaffected.
>
> **Every figure below is the CORRECTED one.** Layers partial credit is **95.9%**, first published as
> 95.6%; the Y/P/N split is **158/10/2**, first published as 157/11/2; the gap is **20.6 points**, first
> published as 20.3. Baseline 75.3% is unchanged, because its Q019 measurement timed out either way.
> Nothing else moved: no cost figure, no median, no route figure, and no other question's verdict.
>
> **The correction needed two attempts, which is worth knowing if you write one.** The first corrected key
> stated only the right answer, and under it v3's baseline — which reached "14 (likely 15)" by byte-searching
> the assets — scored N rather than its published P. That was the correction's fault, not a finding:
> `ULyraPlayerState` declares a `GetStatTagStackCount` of its own, a byte search cannot tell the two owners
> apart, so ~16 is a defensible number and 14 is a near miss. A corrected key has to say what a defensible
> *alternative* answer looks like or it introduces a second scoring error in place of the first. See
> `QUESTION-DEFECTS.md`.
>
> **This is v5, and no figure here compares with v4.** What changed under the stack between the two is
> substantial: Serena moved from a patched **1.7.0 to the 2.x fork** (`Volksie/serena@codemem`, four
> local ports — the `find_symbol` scope guard, `find_symbol_indexed`, the freshness-poll skip list and
> the C# `.csproj` ignore fix, plus the `is_ignored_path` performance fix now merged upstream as
> `f0693a10`); the engine-api MCP server gained empty-result confidence markers, measured response
> budgets and `INFERRED` tagging; and `engine_api_members` stopped reporting a row count taken from an
> already-truncated list. Five of its six tools changed their output text. Quote these as v5 numbers
> only.
>
> **The baseline arm drifted again, and the cost ratio is partly that.** Mean input tokens per question
> went **97,294 (v3) → 161,479 (v4) → 180,563 (v5)**, on an unchanged question set in an unchanged
> room. The layers arm barely moved over the same interval: **1,442 turns (v4) → 1,417 (v5)**, 8.3 per
> question. So **1.64x turns against v4's 1.56x is mostly the baseline getting more expensive, not the
> layers getting cheaper**, and anyone quoting the widening gap as a gain for the stack is crediting it
> with something it did not do. The room never changes; what moves is the CLI's own behaviour, and that
> is now three recorded values in a row.
>
> **Correct is the MAJORITY of three judging passes, and the error bar is small — smaller than the
> tooling assumes.** 340 measurements were each judged three times: **95.9% unanimous (326 of 340)**,
> every disagreement adjacent (13 P/Y, 1 N/P) and **zero Y↔N reversals**. Per-pass credit varied by
> **1.2 points on the baseline arm and 0.6 on the layers arm**. Re-measured on this set rather than
> carried over: `tools/judge_reliability.py --tag v5`.
>
> **On the layers arm's +2.4 points against v4, the honest reading is "unchanged, possibly slightly
> better".** 93.2% → 95.6% is about four questions, against a per-pass spread of 0.6 points here and a
> comparable spread in v4 — two independent runs each carry that noise, and the difference sits close to
> their combination. The defensible claim is the one the run was designed to test: **the 2.x switch, the
> four ported patches and the engine-api changes did not cost the stack anything.** The baseline's
> 75.3% against v4's 74.4% is **inside its own 1.2-point spread and should be read as noise.**
>
> **Fourteen measurements are unstable and must not be quoted individually.** Baseline: D2, I27, J7,
> Q006, Q009, Q018, Q020, Q067. Layers: D13, I10, I28, Q026, Q034, Q063. They are stable enough in
> aggregate — that is what the majority is for — but a single one of them proves nothing.
>
> **One baseline question timed out, and it stands.** Q019 reached the 900s ceiling after 61 turns with
> no answer, asking how many Blueprints call `ULyraInventoryItemInstance::GetStatTagStackCount`. **v4's
> baseline timed out on the identical question**, also at 900s with no answer, so this is reproducible
> rather than a v5 fault; the layers arm answers it in 25s (v4: 32s). Its wall time is the ceiling, not
> a measurement, so any per-question speedup computed from it is meaningless.
>
> **The floor in this run is not comparable to the historic 47,303.** Measured per arm, in isolation:
> **13,271 layers, 7,615 baseline**. The old constant was measured on 2026-09-07 with the full built-in
> tool set, and B1 has since cut the built-ins to five. Re-measured 2026-09-18, same probe and cwd,
> differing only in `--tools`: **49,161 with the full set against 16,310 with B1's five**. The 32,851
> between them is tool schemas, not standing context. `tools/measure_floor.py` still measures the
> unrestricted surface, so its figures and the run's floor are not interchangeable either.
>
> **The baseline arm was run twice, and the second run is the measured one.** The first two attempts
> stopped at 27/170 and 26/170 on leak-gate trips, both **false positives of the same shape**: the Glob
> tool records a reach as two entries, `path:` then `pattern:`, and the gate evaluated the pattern with
> no root, so the rule that a held name inside the room is only a leak if the room contains it could
> never apply to it. I1 globbed the room for a `Shared` it does not have, I2 for a `CLAUDE.md` it does
> not have — **both the same questions that stopped the v4 baseline run in their `find` form**. The gate
> now rejoins the two entries, and its test passes 51/51 (24 fire, 27 quiet), including all 46 pre-existing cases. **The leak gate is not part of the published harness** - `run_bench.py` here has no gate, no `touched` log and no memory wipe - so this records what the measured run ran under rather than something you can re-run. The measured run was started from scratch afterwards
> rather than resumed, so all 170 questions ran under one gate version.

> **This document is the v5 record, and is left as generated apart from this note. v6 is in *arm-comparison-v6.md* and is the current result.** v6 changed the question set, so no figure here compares with one there, except that v6 reports v5's verdicts on the 139 questions the two runs share, under both generations of keys. The code in this repository has also moved since this run: Layer 2's generator now walks macro graphs and records `BindWidget` bindings, which changes artefact counts, so a question whose answer is a call-node count has a different right answer on artefacts generated now.

Generated by `tools/compare_arms.py`. Regenerate rather than hand edit.

Both arms ran **the same 170 questions**, on the same harness. They did NOT run against the same tree: the baseline arm runs in a clean room built beside it, holding only source, config and content, while the layers arm runs in the tree. Their standing floors differ and are recorded per arm in each run's meta file; nothing below subtracts them. Every figure is a **group median**; representative and coverage sets are never pooled.

- Baseline: 170 measurements over 170 questions (some measured twice)
- With layers: 170 measurements over 170 questions
- Errors or timeouts in either arm: **1**

## Per group

A speedup means nothing without accuracy beside it, so Correct sits in the same table. **Correct** is percent with partial credit (Y=1, P=0.5, N=0); **Y/P/N** is the raw split, because one percentage cannot distinguish a near miss from an invention.

| Group | What | Base s | Layer s | **Speedup** | Base calls | Layer calls | **Base Correct** | **Layer Correct** | Base Y/P/N | Layer Y/P/N |
|---|---|---|---|---|---|---|---|---|---|---|
| A | Structure: definition sites, property types | 31.1 | 24.2 | **1.28x** | 4 | 4 | **80%** | **98%** | 14/4/2 | 19/1/0 |
| B | Inheritance and ancestry | 47.5 | 25.7 | **1.85x** | 8 | 4 | **98%** | **98%** | 19/1/0 | 19/1/0 |
| C | Reflection: specifiers, replication | 31.4 | 25.0 | **1.25x** | 4 | 4 | **82%** | **98%** | 16/1/3 | 19/1/0 |
| D | Comments and documentation | 44.2 | 39.8 | **1.11x** | 8 | 5 | **77%** | **97%** | 10/3/2 | 14/1/0 |
| E | Blueprint blast radius | 142.8 | 48.2 | **2.96x** | 22 | 8 | **86%** | **98%** | 17/4/1 | 21/1/0 |
| F | Negation: absence of replication | 25.5 | 22.1 | **1.15x** | 4 | 3 | **100%** | **97%** | 15/0/0 | 14/1/0 |
| G | Traps: non-existence and ambiguity | 23.5 | 35.0 | **0.67x** | 4 | 6 | **90%** | **100%** | 8/2/0 | 10/0/0 |
| H | Engine API surface | 56.4 | 42.7 | **1.32x** | 10 | 8 | **30%** | **95%** | 2/2/6 | 9/1/0 |
| I | Build, tooling and procedure | 58.9 | 80.7 | **0.73x** | 9 | 12 | **53%** | **97%** | 10/12/8 | 28/2/0 |
| J | Performance: the static determinants of cost | 90.6 | 80.2 | **1.13x** | 10 | 14 | **62%** | **94%** | 3/4/1 | 7/1/0 |
| | **Overall** | **52.7** | **34.3** | **1.54x** | **8** | **5** | **77%** | **97%** | 114/33/23 | 160/10/0 |

Retrieval, median KB: baseline 6.5, with layers 6.0.

**Turns**, the cost metric: baseline 2,326, with layers 1,417 (**1.64x**). A turn is one model call, so it is what the standing context is actually paid on.

**Input tokens**, mean per question, floors included: baseline 180,563, with layers 129,243 (**1.40x**).

## Where the layers earn their keep, and where they do not

Ranked by speedup:

- **E Blueprint blast radius** - 2.96x
- **B Inheritance and ancestry** - 1.85x
- **H Engine API surface** - 1.32x
- **A Structure: definition sites, property types** - 1.28x
- **C Reflection: specifiers, replication** - 1.25x
- **F Negation: absence of replication** - 1.15x
- **J Performance: the static determinants of cost** - 1.13x
- **D Comments and documentation** - 1.11x
- **I Build, tooling and procedure** - 0.73x
- **G Traps: non-existence and ambiguity** - 0.67x

The spread across groups is the finding, not the overall number. A group where the layers barely help is either a question-design problem (the answer was reachable without them) or a routing problem (`CLAUDE.md` does not name the artefact for that question shape). Both are worth chasing; the second is the one the standing lesson in `BASELINE-ARM-SPEC.md` warns about.

## Biggest per-question differences

| id | Group | Baseline s | Layers s | Speedup |
|---|---|---|---|---|
| Q019 | A | 900.1 | 25.3 | 35.58x |
| Q018 | A | 597.6 | 21.3 | 28.06x |
| Q014 | A | 596.2 | 24.0 | 24.84x |
| Q071 | E | 388.1 | 24.2 | 16.04x |
| Q016 | A | 417.7 | 32.9 | 12.70x |
| Q005 | A | 368.5 | 32.4 | 11.37x |
| Q062 | E | 575.3 | 51.2 | 11.24x |
| Q068 | E | 543.9 | 53.3 | 10.20x |
| Q065 | E | 182.2 | 19.3 | 9.44x |
| Q034 | B | 733.9 | 89.6 | 8.19x |
| Q089 | F | 225.2 | 29.1 | 7.74x |
| Q012 | A | 158.3 | 24.5 | 6.46x |
| Q072 | E | 301.6 | 51.1 | 5.90x |
| Q069 | E | 436.5 | 78.3 | 5.57x |
| Q063 | E | 392.7 | 71.9 | 5.46x |

Slowest with the layers than without, if any:

| id | Group | Baseline s | Layers s | Ratio |
|---|---|---|---|---|
| D1 | D | 25.2 | 202.0 | 0.12x |
| Q011 | A | 98.8 | 382.0 | 0.26x |
| D11 | D | 20.5 | 78.7 | 0.26x |
| I24 | I | 64.4 | 214.0 | 0.30x |
| G3 | G | 19.1 | 61.8 | 0.31x |
| I4 | I | 51.4 | 147.5 | 0.35x |
| I11 | I | 95.0 | 269.7 | 0.35x |
| I10 | I | 38.7 | 107.5 | 0.36x |
| I5 | I | 34.9 | 94.0 | 0.37x |
| I25 | I | 59.6 | 150.7 | 0.40x |
| G4 | G | 21.2 | 48.2 | 0.44x |
| D8 | D | 134.9 | 293.7 | 0.46x |
| I12 | I | 56.5 | 116.3 | 0.49x |
| D9 | D | 50.7 | 102.7 | 0.49x |
| I19 | I | 52.4 | 106.0 | 0.49x |
