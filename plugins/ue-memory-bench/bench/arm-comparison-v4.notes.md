**This is v4. No figure here compares with v3, and the baseline arm moved as well.** The baseline
arm's mean input tokens per question rose from **97,294 on v3 to 161,479 here** (median 47,046 to
70,148). What changed is measured. Sessions reached for Bash instead of the built-in Grep, Read and
Glob, from the first call on: 53 of v3's 162 non-J questions opened with a shell command, 90 here, and
Bash calls went from 751 to 1,286. They took more, smaller steps: cache writes are unchanged (1.98M
against 1.94M) while cache reads rose 75%. Eight sessions passed 40 turns, against two. **Why is not
proven.** One difference is established: 162 of v3's 170 baseline questions ran with a standing
context of **6,336 tokens**, and every run since 23:26 UTC on 11 September has had 7,307 or more. That
includes v3's group J rerun, all of v3's layers arm, and both v4 arms. The 971 tokens appeared in both
arms at once, on the same CLI build, when the run's model flag changed from `claude-opus-5` to `opus`.
Today both flags give the same floor, so the old context cannot be reproduced or inspected. Ruled
out: effort level, the launching shell, and auto-memory. So v4's two arms share one standing context
and v3's did not. The overall 1.33x is partly the layers getting faster and partly the baseline getting
slower. Quote it as a v4 number only.

**Correct is the MAJORITY of three judging passes, and the error bar is small.** Here 340
measurements were each judged three times: **96.2% unanimous (327 of 340)**, every disagreement
adjacent (8 P/Y, 5 N/P) and **none Y->N**. Per-pass credit varied by **0.6 points on the baseline
arm and 0.3 on the layers arm**. Re-measured on this set rather than carried over:
`tools/judge_reliability.py --tag v4`.

**One baseline question timed out, and it stands.** Q019 reached the 900s ceiling twice; the rule is
one rerun, so it counts as no answer and scored N on all three passes. Its 900s is the ceiling, not a
measurement, so its 28x at the top of the per-question table means nothing. No layers question came
near the ceiling (slowest E102 at 281s), and nothing was re-run at 1800s. v3's I22 note is dropped:
that question had already been reworded before v3 ran, and it scored Y in both arms here.

**The baseline room exposed the run's own metadata, in v3 and in v4 alike.** Its root held
`.baseline-manifest.json` (tree path, per-directory file counts) and the `BENCH-RUN-IN-PROGRESS.md`
lock. Neither contains answer-key content. The cost is a session that knows it is being measured,
plus the turns it spends on these files. Sessions reading the manifest and the lock, out of 170: **v3 49 and 60, v4 25 and 50**.
By group, manifest/lock of n, v3 then v4: A 5/7, 1/3 of 20 · B 5/5, 2/5 of 20 · C 0/0, 0/0 of 20 ·
D 4/5, 1/3 of 15 · E 12/14, 8/16 of 22 · F 1/0, 1/2 of 15 · G 1/3, 0/1 of 10 · H 4/3, 1/2 of 10 ·
I 13/18, 7/14 of 30 · J 4/5, 4/4 of 8. Concentrated in E and I. **Do not compare exposed with
unexposed scores:** a long, floundering session both reads more and scores worse, so the two are
confounded. Recorded by decision rather than fixed mid-run; fixed before any later run.

**What v4 changed, all of it Layer 1 or the harness (see `VERSION.md`):** Serena's per-call file
walk was patched out, so symbolic tools reach clangd within the 45s timeout. `find_symbol_indexed`
and `search_for_pattern` are exposed, and `CLAUDE.md` routes "where is X defined" to them. Group D
design prose was written into the seed project's `Docs/Design/`. The J1 and J5 keys were corrected. The
harness gained a clangd-index gate and an MCP probe. Framing: v3 with Layer 1 working as designed.
