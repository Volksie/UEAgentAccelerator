**CORRECTED AGAIN 2026-09-21: six more answer keys were wrong, found while scoring v6.** The v6 run
exposed eleven wrong keys. Six of them concern facts that nothing between v5 and v6 changed: native
parents, the native class hierarchy, engine plugin descriptors and MemBench source. So the same keys were
wrong for v5 too: Q018, Q034, Q031, Q098, I16 and D2. For example, v5's layers arm answered Q018 with
**UserWidget, 55**, which is right, and was marked N on all three passes. Both arms were re-judged on those six from the recorded answers, three passes each, and the 2026-09-19 verdicts are kept beside the rescored ones.
Details are in `QUESTION-DEFECTS.md` under *Decision-5 review of v6*.

**Every figure below is now the twice-corrected one.** Partial credit is **76.8% baseline against 97.1%
layers**, a gap of **20.3 points**. The 2026-09-19 figures were 75.3%, 95.9% and 20.6. **The layers
arm's outright-wrong count goes from 2 to 0.** Both arms rise, because the baseline had also reached
several of the true answers from source (Q018, Q031, Q034), so the gap narrows slightly rather than
widening. No cost, median or route figure moves. The paragraphs below still quote the 2026-09-19 figures
where they describe that correction and the drift; read those as history.

**CORRECTED 2026-09-19, after first publication. One answer key was wrong.** Q019's key said "14
Blueprints, 30 call nodes" for `ULyraInventoryItemInstance::GetStatTagStackCount`. 14 is the artefact's
ROW count — one row per (Blueprint, graph) — and the Blueprint count is 12; `GA_Weapon_ReloadMagazine`
alone contributes three graphs. The layers arm answered **12 Blueprints / 30 nodes**, which is right, and
was marked P for contradicting the key — in v3, v4 and v5 alike, nine judging passes in total. Rescored
from the recorded answers under a corrected key (`answer-key-corrections.json`): **layers Q019 P →
Y in all three passes**. The baseline timed out on this question and is unaffected.

**Every figure below is the CORRECTED one.** Layers partial credit is **95.9%**, first published as
95.6%; the Y/P/N split is **158/10/2**, first published as 157/11/2; the gap is **20.6 points**, first
published as 20.3. Baseline 75.3% is unchanged, because its Q019 measurement timed out either way.
Nothing else moved: no cost figure, no median, no route figure, and no other question's verdict.

**The correction needed two attempts, which is worth knowing if you write one.** The first corrected key
stated only the right answer, and under it v3's baseline — which reached "14 (likely 15)" by byte-searching
the assets — scored N rather than its published P. That was the correction's fault, not a finding:
`ULyraPlayerState` declares a `GetStatTagStackCount` of its own, a byte search cannot tell the two owners
apart, so ~16 is a defensible number and 14 is a near miss. A corrected key has to say what a defensible
*alternative* answer looks like or it introduces a second scoring error in place of the first. See
`QUESTION-DEFECTS.md`.

**This is v5, and no figure here compares with v4.** What changed under the stack between the two is
substantial: Serena moved from a patched **1.7.0 to the 2.x fork** (`Volksie/serena@codemem`, four
local ports — the `find_symbol` scope guard, `find_symbol_indexed`, the freshness-poll skip list and
the C# `.csproj` ignore fix, plus the `is_ignored_path` performance fix now merged upstream as
`f0693a10`); the engine-api MCP server gained empty-result confidence markers, measured response
budgets and `INFERRED` tagging; and `engine_api_members` stopped reporting a row count taken from an
already-truncated list. Five of its six tools changed their output text. Quote these as v5 numbers
only.

**The baseline arm drifted again, and the cost ratio is partly that.** Mean input tokens per question
went **97,294 (v3) → 161,479 (v4) → 180,563 (v5)**, on an unchanged question set in an unchanged
room. The layers arm barely moved over the same interval: **1,442 turns (v4) → 1,417 (v5)**, 8.3 per
question. So **1.64x turns against v4's 1.56x is mostly the baseline getting more expensive, not the
layers getting cheaper**, and anyone quoting the widening gap as a gain for the stack is crediting it
with something it did not do. The room never changes; what moves is the CLI's own behaviour, and that
is now three recorded values in a row.

**Correct is the MAJORITY of three judging passes, and the error bar is small — smaller than the
tooling assumes.** 340 measurements were each judged three times: **95.9% unanimous (326 of 340)**,
every disagreement adjacent (13 P/Y, 1 N/P) and **zero Y↔N reversals**. Per-pass credit varied by
**1.2 points on the baseline arm and 0.6 on the layers arm**. Re-measured on this set rather than
carried over: `tools/judge_reliability.py --tag v5`.

**On the layers arm's +2.4 points against v4, the honest reading is "unchanged, possibly slightly
better".** 93.2% → 95.6% is about four questions, against a per-pass spread of 0.6 points here and a
comparable spread in v4 — two independent runs each carry that noise, and the difference sits close to
their combination. The defensible claim is the one the run was designed to test: **the 2.x switch, the
four ported patches and the engine-api changes did not cost the stack anything.** The baseline's
75.3% against v4's 74.4% is **inside its own 1.2-point spread and should be read as noise.**

**Fourteen measurements are unstable and must not be quoted individually.** Baseline: D2, I27, J7,
Q006, Q009, Q018, Q020, Q067. Layers: D13, I10, I28, Q026, Q034, Q063. They are stable enough in
aggregate — that is what the majority is for — but a single one of them proves nothing.

**One baseline question timed out, and it stands.** Q019 reached the 900s ceiling after 61 turns with
no answer, asking how many Blueprints call `ULyraInventoryItemInstance::GetStatTagStackCount`. **v4's
baseline timed out on the identical question**, also at 900s with no answer, so this is reproducible
rather than a v5 fault; the layers arm answers it in 25s (v4: 32s). Its wall time is the ceiling, not
a measurement, so any per-question speedup computed from it is meaningless.

**The floor in this run is not comparable to the historic 47,303.** Measured per arm, in isolation:
**13,271 layers, 7,615 baseline**. The old constant was measured on 2026-09-07 with the full built-in
tool set, and B1 has since cut the built-ins to five. Re-measured 2026-09-18, same probe and cwd,
differing only in `--tools`: **49,161 with the full set against 16,310 with B1's five**. The 32,851
between them is tool schemas, not standing context. `tools/measure_floor.py` still measures the
unrestricted surface, so its figures and the run's floor are not interchangeable either.

**The baseline arm was run twice, and the second run is the measured one.** The first two attempts
stopped at 27/170 and 26/170 on leak-gate trips, both **false positives of the same shape**: the Glob
tool records a reach as two entries, `path:` then `pattern:`, and the gate evaluated the pattern with
no root, so the rule that a held name inside the room is only a leak if the room contains it could
never apply to it. I1 globbed the room for a `Shared` it does not have, I2 for a `CLAUDE.md` it does
not have — **both the same questions that stopped the v4 baseline run in their `find` form**. The gate
now rejoins the two entries, and its test passes 51/51 (24 fire, 27 quiet), including all 46 pre-existing cases. **The leak gate is not part of the published harness** - `run_bench.py` here has no gate, no `touched` log and no memory wipe - so this records what the measured run ran under rather than something you can re-run. The measured run was started from scratch afterwards
rather than resumed, so all 170 questions ran under one gate version.
