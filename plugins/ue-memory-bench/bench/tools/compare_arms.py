"""Paired baseline vs with-layers comparison, per group.

Both arms ran the same 160 questions on the same harness, same tree state, same floor. That is the
comparison the smoke run could not make, because its baseline came from a different question set
and its with-layers figures came from a harness with a different floor.

Group medians, never a single pooled number across the representative and coverage sets.
"""
import argparse
import collections
import os
import io
import json
import statistics as st

# No floor subtraction anywhere in this file any more. `tokens_above_floor` was
# dropped from the record because no arithmetic on a single floor constant describes the data -
# the implied per-turn input spans 21,278 to 70,129 on the baseline arm alone. See run_bench.py.
def turns_of(r):
    t = r.get("turns")
    return t if t is not None else (r.get("calls") or 0) + 1

NAMES = {
    "J": "Performance: the static determinants of cost",
    "A": "Structure: definition sites, property types",
    "B": "Inheritance and ancestry",
    "C": "Reflection: specifiers, replication",
    "D": "Comments and documentation",
    "E": "Blueprint blast radius",
    "F": "Negation: absence of replication",
    "G": "Traps: non-existence and ambiguity",
    "H": "Engine API surface",
    "I": "Build, tooling and procedure",
}


# What prints when --notes is not given. Deliberately not a real run's figures: this block used to be
# hardcoded with ours, so a comparison of YOUR run printed OUR judge agreement and OUR timeouts as if
# they described it. Write a notes file per run instead; bench/arm-comparison-v4.notes.md is an example.
NO_NOTES = """\
**No run notes were supplied, so nothing here describes this run's judging or its timeouts.**
Pass `--notes` with a file holding this run's judge agreement (`judge_reliability.py`), any
questions that timed out or were re-run, and any defect found in the set. See `bench/METHOD.md`.""".split("\n")


def load(p):
    return [json.loads(l) for l in io.open(p, encoding="utf-8") if l.strip()]


def bygroup(rows):
    d = collections.defaultdict(list)
    for r in rows:
        d[r["group"]].append(r)
    return d


def med(rs, f):
    v = [r.get(f) or 0 for r in rs]
    return st.median(v) if v else 0


def ratio(a, b):
    return (a / b) if b else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--layers", required=True)
    ap.add_argument("--scores", help="bench/runs/scores.jsonl - puts Correct beside the speedups")
    ap.add_argument("--out", required=True)
    # The shareable page carries the same numbers, so it is named HERE rather than hand-added to the
    # output: this file says "regenerate rather than hand edit", and a link added by hand is gone the
    # next time anybody does. If the numbers change, the page has to be republished to the same URL
    # or the two disagree in public.
    ap.add_argument("--page", help="URL of the published page for this comparison")
    ap.add_argument("--notes", help="markdown file of this version's caveats, one paragraph per "
                    "blank-line-separated block, quoted into the preamble")
    args = ap.parse_args()

    base, lay = load(args.baseline), load(args.layers)
    B, L = bygroup(base), bygroup(lay)

    # Scores are keyed (arm, id, recorded_at), the same key the scorer writes, so a question
    # measured twice is counted twice rather than collapsing to whichever verdict was kinder.
    #
    # MAJORITY ACROSS JUDGING PASSES. This key deliberately omits judge_pass, so with three passes
    # in the file each row overwrote the one before and the table reported PASS 3 ALONE - while
    # judge_reliability.py, on the same data, prints "majority verdict across passes (quote this
    # once >1 pass exists)". The two disagreed on v3: 109/42/19 here against 110/40/20 there. The
    # passes are collected and voted instead, which is what the three passes were run for.
    passes = {}
    if args.scores and os.path.exists(args.scores):
        for s in load(args.scores):
            if not s.get("correct"):
                continue
            passes.setdefault((s["arm"], s["id"], s.get("recorded_at")), []).append(
                (s.get("judge_pass", 1), s["correct"].upper()[:1]))

    def _majority(votes):
        """Most common verdict; a tie goes to P, the cautious reading between two neighbours."""
        c = collections.Counter(v for _, v in votes).most_common()
        if len(c) > 1 and c[0][1] == c[1][1]:
            return "P"
        return c[0][0]

    scores = {k: {"correct": _majority(v), "passes": len(v)} for k, v in passes.items()}

    def correct(rows, arm):
        """Percentage correct with partial credit, plus the raw Y/P/N counts.

        A single percentage hides whether the misses are near-misses or inventions, so both are
        reported. Y=1, P=0.5, N=0.
        """
        got = [scores.get((arm, r["id"], r.get("recorded_at"))) for r in rows]
        got = [g for g in got if g and g.get("correct")]
        if not got:
            return None, (0, 0, 0), 0
        y = sum(1 for g in got if g["correct"].upper().startswith("Y"))
        pp = sum(1 for g in got if g["correct"].upper().startswith("P"))
        nn = sum(1 for g in got if g["correct"].upper().startswith("N"))
        return 100.0 * (y + 0.5 * pp) / len(got), (y, pp, nn), len(got)

    def fmt_correct(rows, arm):
        pct, (y, p, n), tot = correct(rows, arm)
        if pct is None:
            return "-", "-"
        return "%.0f%%" % pct, "%d/%d/%d" % (y, p, n)

    o = []
    o.append("# Baseline vs with-layers: the paired comparison")
    o.append("")
    if args.page:
        o.append("**Shareable version of this page:** <%s>" % args.page)
        o.append("")
        o.append("Private until shared from the page's own share menu. **If the numbers here change,")
        o.append("the page must be republished to the same URL** or the two disagree in public.")
        o.append("")
    o.append("> ### Read this before quoting any number below")
    o.append(">")
    o.append("> **Group medians carry weight. Single-question figures do not.** Run-to-run variance on")
    o.append("> the same question, under identical conditions, is about **40% on tool calls and 20% on")
    o.append("> seconds**, measured over 140 questions that were run twice. Q078 moved from 274.8s to")
    o.append("> 109.5s between two runs of itself; Q063 moved from 275.0s to 644.5s. Any claim about an")
    o.append("> individual question needs repeats before it means anything.")
    o.append(">")
    o.append("> **Route is not an arm-vs-arm metric and is no longer reported as one.** Most expected")
    o.append("> routes name a layer artefact, and the baseline arm runs in a clean room that has never")
    o.append("> held one, so it cannot match them whatever it answers. Run `bench/tools/route_split.py`")
    o.append("> for the split that means something.")
    # Everything measured per run (judge agreement, timeouts, known defects, run caveats) comes from
    # --notes. It used to be hardcoded here, so every later comparison printed one run's figures.
    notes = NO_NOTES
    if args.notes:
        notes = io.open(args.notes, encoding="utf-8").read().strip("\n").split("\n")
    o.append(">")
    for line in notes:
        o.append("> " + line if line else ">")
    o.append("")
    o.append("Generated by `bench/tools/compare_arms.py`. Regenerate rather than hand edit.")
    o.append("")
    o.append("Both arms ran **the same %d questions**, on the same harness. They did NOT run against "
             "the same tree: the baseline arm runs in a clean room built beside it, holding only "
             "source, config and content, while the layers arm runs in the tree. "
             "Their standing floors differ and are recorded per arm in each run's meta file; "
             "nothing below subtracts them. Every figure is a **group median**; "
             "representative and coverage sets are never pooled."
             % len({r["id"] for r in base}))
    o.append("")
    o.append("- Baseline: %d measurements over %d questions (some measured twice)"
             % (len(base), len({r["id"] for r in base})))
    o.append("- With layers: %d measurements over %d questions"
             % (len(lay), len({r["id"] for r in lay})))
    o.append("- Errors or timeouts in either arm: **%d**"
             % sum(1 for r in base + lay if r.get("is_error") or r.get("timed_out")))
    o.append("")
    o.append("## Per group")
    o.append("")
    o.append("A speedup means nothing without accuracy beside it, so Correct sits in the same table. "
             "**Correct** is percent with partial credit (Y=1, P=0.5, N=0); **Y/P/N** is the raw split, "
             "because one percentage cannot distinguish a near miss from an invention.")
    o.append("")
    o.append("| Group | What | Base s | Layer s | **Speedup** | Base calls | Layer calls "
             "| **Base Correct** | **Layer Correct** | Base Y/P/N | Layer Y/P/N |")
    o.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for g in sorted(B):
        b, l = B[g], L.get(g, [])
        if not l:
            continue
        bs, ls = med(b, "wall_seconds"), med(l, "wall_seconds")
        bc, lc = med(b, "calls"), med(l, "calls")
        bpct, bsplit = fmt_correct(b, "baseline")
        lpct, lsplit = fmt_correct(l, "layers")
        o.append("| %s | %s | %.1f | %.1f | **%.2fx** | %.0f | %.0f | **%s** | **%s** | %s | %s |"
                 % (g, NAMES.get(g, ""), bs, ls, ratio(bs, ls), bc, lc, bpct, lpct, bsplit, lsplit))
    bs, ls = med(base, "wall_seconds"), med(lay, "wall_seconds")
    bc, lc = med(base, "calls"), med(lay, "calls")
    bpct, bsplit = fmt_correct(base, "baseline")
    lpct, lsplit = fmt_correct(lay, "layers")
    o.append("| | **Overall** | **%.1f** | **%.1f** | **%.2fx** | **%.0f** | **%.0f** | **%s** | **%s** | %s | %s |"
             % (bs, ls, ratio(bs, ls), bc, lc, bpct, lpct, bsplit, lsplit))
    o.append("")
    o.append("Retrieval, median KB: baseline %.1f, with layers %.1f."
             % (med(base, "retrieval_bytes") / 1024.0, med(lay, "retrieval_bytes") / 1024.0))
    o.append("")

    tb = sum(turns_of(r) for r in base)
    tl = sum(turns_of(r) for r in lay)
    o.append("**Turns**, the cost metric: baseline %s, with layers %s (**%.2fx**). A turn is one "
             "model call, so it is what the standing context is actually paid on."
             % (format(tb, ","), format(tl, ","), ratio(tb, tl)))
    mb = sum(r.get("tokens_total_in") or 0 for r in base) / len(base)
    ml = sum(r.get("tokens_total_in") or 0 for r in lay) / len(lay)
    o.append("")
    o.append("**Input tokens**, mean per question, floors included: baseline %s, with layers %s "
             "(**%.2fx**)." % (format(int(mb), ","), format(int(ml), ","), ratio(mb, ml)))
    o.append("")

    o.append("## Where the layers earn their keep, and where they do not")
    o.append("")
    rows = []
    for g in sorted(B):
        if g not in L:
            continue
        rows.append((ratio(med(B[g], "wall_seconds"), med(L[g], "wall_seconds")), g))
    rows.sort(reverse=True)
    o.append("Ranked by speedup:")
    o.append("")
    for r, g in rows:
        o.append("- **%s %s** - %.2fx" % (g, NAMES.get(g, ""), r))
    o.append("")
    o.append("The spread across groups is the finding, not the overall number. A group where the "
             "layers barely help is either a question-design problem (the answer was reachable "
             "without them) or a routing problem (`CLAUDE.md` does not name the artefact for that "
             "question shape). Both are worth chasing; the second is the one the standing lesson in "
             "`bench/BASELINE-ARM-SPEC.md` warns about.")
    o.append("")

    o.append("## Biggest per-question differences")
    o.append("")
    bmed = {}
    for r in base:
        bmed.setdefault(r["id"], []).append(r.get("wall_seconds") or 0)
    lmap = {r["id"]: r for r in lay}
    diffs = []
    for qid, secs in bmed.items():
        if qid in lmap:
            b = st.median(secs)
            l = lmap[qid].get("wall_seconds") or 0
            diffs.append((ratio(b, l), qid, b, l))
    diffs.sort(reverse=True)
    o.append("| id | Group | Baseline s | Layers s | Speedup |")
    o.append("|---|---|---|---|---|")
    for r, qid, b, l in diffs[:15]:
        o.append("| %s | %s | %.1f | %.1f | %.2fx |" % (qid, lmap[qid]["group"], b, l, r))
    o.append("")
    o.append("Slowest with the layers than without, if any:")
    o.append("")
    worse = [d for d in diffs if d[0] < 1.0]
    if worse:
        o.append("| id | Group | Baseline s | Layers s | Ratio |")
        o.append("|---|---|---|---|---|")
        for r, qid, b, l in sorted(worse)[:15]:
            o.append("| %s | %s | %.1f | %.1f | %.2fx |" % (qid, lmap[qid]["group"], b, l, r))
    else:
        o.append("None. Every question was at least as fast with the layers.")
    o.append("")
    # Only when there is nothing to score against. This went out unconditionally for two versions,
    # so a document whose every group row carried a Correct column still ended by announcing that
    # accuracy had not been measured.
    if not scores:
        o.append("**Not yet scored:** Correct and Route. Every figure here is cost, not accuracy. "
                 "A faster wrong answer is not an improvement, so this table is only half the result.")
        o.append("")

    with io.open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(o))
    print("wrote %s" % args.out)


if __name__ == "__main__":
    main()
