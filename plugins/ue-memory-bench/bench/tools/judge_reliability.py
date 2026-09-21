"""How much of our score is the judge, and what is the arm score once that is taken out.

WHY THIS EXISTS. The layers arm scores 96.9% with partial credit, the headroom to a perfect score is
5.6 points, and the judge agrees with itself about 92% of the time. So the error bar is comparable to
the thing we are trying to measure, and v1 -> v2 proved it: the layers arm "regressed" by 0.3 points,
which was half a question, 150 unchanged / 5 better / 5 worse.

This reads every judging pass in a scores file and reports three things:

  1. Agreement, measured rather than quoted. Per-measurement across passes.
  2. The credit each pass produced on its own, so the spread IS the error bar.
  3. The majority verdict per measurement, and the arm score computed from it, which is the number
     to quote once more than one pass exists.

Run passes first:
    python bench/tools/score_answers.py --pass 2 --resume
    python bench/tools/score_answers.py --pass 3 --resume
    python bench/tools/judge_reliability.py
"""
from __future__ import annotations

import argparse
import collections
import io
import json
import os
import pathlib

# Machine specific, so they are environment overridable rather than baked in. TREE defaults to the
# repository root two levels above this file, which is where it sits in both the working tree and the
# published repo. Same pattern as run_bench.py and score_answers.py.
# The tree, searched for rather than counted. See _tree_root.py: two-levels-up is right
# until something moves, and then every path built on it is quietly wrong.
from _tree_root import find_tree_root
TREE = pathlib.Path(find_tree_root(os.path.dirname(os.path.abspath(__file__))))
CREDIT = {"Y": 1.0, "P": 0.5, "N": 0.0}
RANK = {"N": 0, "P": 1, "Y": 2}


def load(path):
    rows = []
    for line in io.open(path, encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            r.setdefault("judge_pass", 1)
            rows.append(r)
    return rows


def majority(verdicts):
    """Majority verdict, breaking a tie toward the MIDDLE rather than the kinder option.

    Every disagreement v1 recorded was adjacent (Y<->P, P<->N) and none was Y<->N, so a 1-1 tie is
    always between neighbours and the midpoint is the honest read. Breaking ties upward would make
    the score a function of how many times we judged it.
    """
    c = collections.Counter(verdicts)
    top = max(c.values())
    winners = sorted((v for v, n in c.items() if n == top), key=lambda v: RANK[v])
    if len(winners) == 1:
        return winners[0], False
    mid = winners[len(winners) // 2] if len(winners) % 2 else winners[len(winners) // 2 - 1]
    return mid, True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    # Defaults to bench/runs/scores.jsonl, which is what score_answers.py writes with no --tag.
    ap.add_argument("--tag", default="full",
                    help="run tag; reads bench/runs/scores-<tag>.jsonl, or scores.jsonl for 'full'")
    ap.add_argument("--scores", default=None)
    args = ap.parse_args()

    path = args.scores or str(TREE / "bench" / "runs" / (
        "scores.jsonl" if args.tag == "full" else "scores-%s.jsonl" % args.tag))
    if not os.path.exists(path):
        return print("no scores at %s" % path) or 1

    rows = [r for r in load(path) if not r.get("judge_error")]
    passes = sorted({r["judge_pass"] for r in rows})
    print("scores : %s" % path)
    print("passes : %s" % ", ".join(str(p) for p in passes))

    # (arm,id) -> {pass: verdict}
    by_m = collections.defaultdict(dict)
    for r in rows:
        by_m[(r["arm"], r["id"])][r["judge_pass"]] = r["correct"]

    if len(passes) < 2:
        print()
        print("Only one judging pass, so there is nothing to measure yet and no error bar.")
        print("The 3-point figure quoted in bench/arm-comparison.md came from v1's accidental")
        print("repeats, not from this set. Run:")
        print("    python bench/tools/score_answers.py --tag %s --pass 2 --resume" % args.tag)
        return 0

    # ---- 1. agreement ------------------------------------------------------------------------
    multi = {k: v for k, v in by_m.items() if len(v) >= 2}
    unanimous = sum(1 for v in multi.values() if len(set(v.values())) == 1)
    print()
    print("=== agreement, measured on %d measurements judged %d+ times ===" % (len(multi), 2))
    print("  unanimous across passes : %d / %d  (%.1f%%)"
          % (unanimous, len(multi), 100.0 * unanimous / max(len(multi), 1)))

    flips = collections.Counter()
    for v in multi.values():
        seen = sorted(set(v.values()), key=lambda x: RANK[x])
        if len(seen) > 1:
            flips["".join(seen)] += 1
    if flips:
        print("  disagreements by kind   : "
              + ", ".join("%s %d" % (k, n) for k, n in sorted(flips.items())))
        nonadj = {k: n for k, n in flips.items() if k == "NY"}
        print("  reversals (N vs Y)      : %d%s"
              % (sum(nonadj.values()),
                 "" if nonadj else "   (all disagreements adjacent, as in v1)"))

    # ---- 2. per-pass credit: the spread IS the error bar ------------------------------------
    print()
    print("=== credit per pass, per arm. The spread is the error bar ===")
    print("  %-9s %s" % ("arm", "  ".join("pass %d" % p for p in passes) + "     spread"))
    arms = sorted({a for a, _ in by_m})
    for arm in arms:
        vals = []
        for p in passes:
            got = [v[p] for (a, _), v in by_m.items() if a == arm and p in v]
            vals.append(sum(CREDIT[x] for x in got) / max(len(got), 1) if got else None)
        shown = "  ".join("%6.1f%%" % (v * 100) if v is not None else "     - " for v in vals)
        have = [v for v in vals if v is not None]
        spread = (max(have) - min(have)) * 100 if len(have) > 1 else 0.0
        print("  %-9s %s     %+.1f pts" % (arm, shown, spread))

    # ---- 3. majority verdict, the number to quote -------------------------------------------
    print()
    print("=== majority verdict across passes (quote this once >1 pass exists) ===")
    ties = 0
    maj = {}
    for k, v in by_m.items():
        m, tied = majority(list(v.values()))
        maj[k] = m
        ties += 1 if tied else 0
    for arm in arms:
        got = [m for (a, _), m in maj.items() if a == arm]
        c = collections.Counter(got)
        credit = sum(CREDIT[x] for x in got) / max(len(got), 1)
        print("  %-9s n=%3d  Y=%3d P=%3d N=%3d   credit %.1f%%"
              % (arm, len(got), c["Y"], c["P"], c["N"], credit * 100))
    print("  ties broken to the middle: %d" % ties)

    # ---- 4. which measurements are unstable, i.e. not worth reading individually ------------
    unstable = sorted(k for k, v in multi.items() if len(set(v.values())) > 1)
    if unstable:
        print()
        print("=== unstable measurements: do NOT quote these individually ===")
        for arm, qid in unstable:
            print("  %-9s %-6s %s" % (arm, qid, " ".join(
                "p%d=%s" % (p, s) for p, s in sorted(by_m[(arm, qid)].items()))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
