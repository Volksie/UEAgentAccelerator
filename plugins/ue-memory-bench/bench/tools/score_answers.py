"""Score every recorded answer against its key, for both arms.

Runs a judge session per measurement with `claude --bare`: the judge needs no codebase, no Serena
and no CLAUDE.md, only the question, the key and the answer - so it runs at the ~4.4k floor rather
than the 47k measured harness floor, and on the API key rather than the subscription.

Scores are written incrementally and keyed by (arm, id, recorded_at), so baseline questions that
were measured twice are scored twice and --resume is safe.

Usage:
    python bench/tools/score_answers.py                 # both arms, all measurements
    python bench/tools/score_answers.py --limit 10      # smoke test the judge first
    python bench/tools/score_answers.py --resume
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys
import time

# Environment overridable; see run_bench.py for the same pattern.
# The tree, searched for rather than counted. See _tree_root.py: two-levels-up is right
# until something moves, and then every path built on it is quietly wrong.
from _tree_root import find_tree_root
TREE = find_tree_root(os.path.dirname(os.path.abspath(__file__)))
CLAUDE = os.environ.get("UEAA_CLAUDE") or "claude"
SETTINGS = os.environ.get("UEAA_BENCH_SETTINGS") or os.path.expanduser(
    os.path.join("~", ".claude", "bench-settings.json"))
JUDGE_SYS = os.path.join(TREE, "bench", "tools", "judge-system.txt")
OUT = os.path.join(TREE, "bench", "runs", "scores.jsonl")

def arms_for_tag(tag):
    """Result files for one measured set, by the tag run_bench.py named them with.

    Hardcoded names are how a scorer grades last week's run: it succeeds, and every number comes from
    the wrong measurements. run_bench.py writes results-<arm>-<tag>.jsonl, so read the same names.
    """
    return {
        "baseline": os.path.join(TREE, "bench", "runs", "results-baseline-%s.jsonl" % tag),
        "layers": os.path.join(TREE, "bench", "runs", "results-layers-%s.jsonl" % tag),
    }


def out_for_tag(tag):
    """One scores file per tag. A shared file would hold incomparable runs side by side."""
    name = "scores.jsonl" if tag == "full" else "scores-%s.jsonl" % tag
    return os.path.join(TREE, "bench", "runs", name)

FIELD = re.compile(r"^(CORRECT|RECALL|PRECISION|ROUTE_MATCH|ROUTE_ACTUAL|NOTES):\s*(.*)$")


ROUTE_OVERLAY = os.path.join(TREE, "bench", "expected-routes-g-i.json")
ROUTE_CORRECTIONS = os.path.join(TREE, "bench", "expected-routes-corrections.json")
# Answer keys the frozen set gets WRONG. Same reasoning as the route corrections file, applied to the
# thing that decides correctness rather than route, so it can move a published credit figure - see the
# file's own header and QUESTION-DEFECTS.md. An overlay because editing a runset would make the
# comparison for that run unreproducible from its own input, and because the key is copied into each
# results record at run time, so an edited runset would not reach a rescore anyway.
KEY_CORRECTIONS = os.path.join(TREE, "bench", "answer-key-corrections.json")


def _load_route_file(path):
    if not os.path.exists(path):
        return {}
    d = json.load(io.open(path, encoding="utf-8"))
    return {k: v for k, v in d.items() if not k.startswith("_")}


def load_route_overlay():
    """Expected routes the question set does not define at all.

    An overlay rather than an edit, so the frozen set and the recorded cost figures stay valid.
    Only fills a route in where the record has none; never overrides one the set already defines.
    """
    return _load_route_file(ROUTE_OVERLAY)


def load_route_corrections():
    """Routes the set *does* define but defines wrongly. Overrides, where the overlay only fills.

    Two files and two steps, because a reader has to know which applied. A filled route was missing
    metadata. An overridden one is a defect in a frozen set, and it can move a figure that has already
    been published - so it is reported separately and loudly, and the file's header says a correction
    that moves a published number must be called out wherever that number appears.

    Keyed by question id, so it is only meaningful against the set those ids came from. Ids are reused
    across sets: Q008 here is not Q008 in somebody else's.
    """
    return _load_route_file(ROUTE_CORRECTIONS)


def load_key_corrections(tag=None):
    """Answer keys the frozen set defines wrongly. Overrides the key recorded with the measurement.

    The measurement itself is never touched: the recorded answer stands, and only what it is judged
    against changes. Every entry needs a section in QUESTION-DEFECTS.md saying how the key was wrong,
    how that was established, and what rescoring moves.

    VERSION-SCOPED, and it has to be. A key can be right for one run and wrong for the next, because
    the artefacts it describes are regenerated: a count that was true of one artefact set stops being
    true when the generator starts covering something it did not cover before. So an entry is either a
    plain string - correct for every run - or an object keyed by run tag. A tag absent from such an
    object gets NO correction rather than inheriting another run's number, and the omission is
    reported rather than silent. Judging a new run against an old run's count is the exact failure
    this file exists to stop.
    """
    raw = _load_route_file(KEY_CORRECTIONS)
    out, skipped = {}, []
    for qid, value in raw.items():
        if isinstance(value, dict):
            # Keys beginning with _ are prose for the reader, not run tags; a dict of nothing but
            # those is an entry documenting a defect that corrects no run, which is legitimate.
            if tag in value:
                out[qid] = value[tag]
            else:
                skipped.append(qid)
        else:
            out[qid] = value
    if skipped:
        print("answer-key corrections: %d entry(ies) are version-scoped with nothing for tag '%s', so "
              "they are NOT applied: %s. If that run needs a corrected key, add its tag."
              % (len(skipped), tag, ", ".join(sorted(skipped))))
    return out


def build_prompt(r):
    parts = [
        "GROUP: %s" % r.get("group"),
        "",
        "QUESTION:",
        r.get("question", ""),
        "",
        "ANSWER KEY:",
        str(r.get("key") or "(none recorded)"),
        "",
        "EXPECTED ROUTE:",
        str(r.get("expected_route") or "(none defined for this group)"),
        "",
        "TOOLS THE SESSION USED:",
        json.dumps(r.get("calls_by_tool") or {}),
        "",
        "ANSWER UNDER TEST:",
        str(r.get("answer") or "(no answer produced)"),
    ]
    return "\n".join(parts)


def parse_verdict(text):
    out = {}
    for line in (text or "").splitlines():
        m = FIELD.match(line.strip())
        if m:
            out[m.group(1).lower()] = m.group(2).strip()
    return out


def judge(r, model, timeout_s):
    cmd = [
        CLAUDE, "--bare", "-p", build_prompt(r),
        "--settings", SETTINGS,
        "--system-prompt-file", JUDGE_SYS,
        "--model", model,
        "--tools", "",
        "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
        "--output-format", "json",
        "--no-session-persistence",
    ]
    try:
        p = subprocess.run(cmd, cwd=TREE, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout_s)
        try:
            d = json.loads(p.stdout or "{}")
        except ValueError:
            return {"judge_error": "unparseable output", "stdout_tail": (p.stdout or "")[-300:]}
        if d.get("is_error"):
            return {"judge_error": str(d.get("result"))[:200]}
        v = parse_verdict(d.get("result"))
        if not v.get("correct"):
            return {"judge_error": "no CORRECT field", "raw": str(d.get("result"))[:300]}
        v["judge_tokens"] = (d.get("usage", {}).get("input_tokens", 0)
                             + d.get("usage", {}).get("cache_read_input_tokens", 0)
                             + d.get("usage", {}).get("cache_creation_input_tokens", 0))
        return v
    except subprocess.TimeoutExpired:
        return {"judge_error": "timeout"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="opus")
    ap.add_argument("--limit", type=int, default=0, help="score only the first N (judge smoke test)")
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--only-groups", help="comma separated, e.g. G,I - rescore just these")
    ap.add_argument("--tag", default="full",
                    help="which measured set to score, as run_bench.py tagged it. Names both the input "
                         "files and the scores file")
    ap.add_argument("--pass", dest="judge_pass", type=int, default=1,
                    help="independent judging pass number. A judge disagrees with itself, so run passes "
                         "1..N and take the majority with judge_reliability.py. Recorded on every row and "
                         "part of the --resume key, so passes never overwrite each other")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    todo = []
    arms = arms_for_tag(args.tag)
    if not args.out:
        args.out = out_for_tag(args.tag)
    print("scoring set '%s', pass %d" % (args.tag, args.judge_pass))
    for a, p in sorted(arms.items()):
        print("  %-9s %s" % (a, "OK  " + p if os.path.exists(p) else "MISSING  " + p))
    print("  scores -> %s" % args.out)

    for arm, path in arms.items():
        if not os.path.exists(path):
            print("skip %s, no results at %s" % (arm, path))
            continue
        for r in (json.loads(l) for l in io.open(path, encoding="utf-8") if l.strip()):
            r["_arm"] = arm
            todo.append(r)

    done = set()
    if args.resume and os.path.exists(args.out):
        for line in io.open(args.out, encoding="utf-8"):
            try:
                s = json.loads(line)
                # judge_pass is part of the key, so a second pass re-judges everything instead of
                # skipping it as done. Rows written before passes existed count as pass 1.
                done.add((s["arm"], s["id"], s.get("recorded_at"), s.get("judge_pass", 1)))
            except Exception:
                pass
        print("resume: %d already scored" % len(done))

    overlay = load_route_overlay()
    filled = 0
    for r in todo:
        if not r.get("expected_route") and r["id"] in overlay:
            r["expected_route"] = overlay[r["id"]]
            filled += 1
    if overlay:
        print("route overlay: %d entries, filled %d records that had none" % (len(overlay), filled))

    # Corrections run after the fill and do override, so a question can be filled by the overlay and
    # then corrected. Printed separately and loudly: an overridden route means this score may not match
    # the one published for the run, and that is a thing a reader must be told rather than left to
    # discover by diffing two scores files.
    corrections = load_route_corrections()
    corrected = []
    for r in todo:
        if r["id"] in corrections:
            r["expected_route"] = corrections[r["id"]]
            corrected.append(r["id"])
    if corrections:
        print("route CORRECTIONS: %d entries, overrode %d records (%s)"
              % (len(corrections), len(corrected), ", ".join(sorted(set(corrected))) or "none"))
        if corrected:
            print("  NOTE: a corrected route can change route_match against the published figure "
                  "for this run. See bench/expected-routes-corrections.json.")

    # Key corrections, loudest of the three because this one moves CORRECTNESS rather than route.
    key_fixes = load_key_corrections(args.tag)
    key_fixed = []
    for r in todo:
        if r["id"] in key_fixes:
            r["key"] = key_fixes[r["id"]]
            key_fixed.append(r["id"])
    if key_fixes:
        print("ANSWER KEY CORRECTIONS: %d entries, overrode %d records (%s)"
              % (len(key_fixes), len(key_fixed), ", ".join(sorted(set(key_fixed))) or "none"))
        if key_fixed:
            print("  NOTE: a corrected key changes CREDIT, not just route. Any figure rescored with "
                  "this file present is not the figure published for the run. See "
                  "bench/answer-key-corrections.json and bench/QUESTION-DEFECTS.md.")

    todo = [r for r in todo
            if (r["_arm"], r["id"], r.get("recorded_at"), args.judge_pass) not in done]
    if args.only_groups:
        want = set(args.only_groups.upper().split(","))
        todo = [r for r in todo if r["group"] in want]
    if args.limit:
        todo = todo[:args.limit]
    print("scoring %d measurements with %s\n" % (len(todo), args.model))

    started = time.time()
    for n, r in enumerate(todo, 1):
        v = judge(r, args.model, args.timeout)
        rec = {
            "arm": r["_arm"], "id": r["id"], "group": r["group"],
            "recorded_at": r.get("recorded_at"), "judge_pass": args.judge_pass,
            "correct": v.get("correct"), "recall": v.get("recall"),
            "precision": v.get("precision"), "route_match": v.get("route_match"),
            "route_actual": v.get("route_actual"), "notes": v.get("notes"),
            "judge_error": v.get("judge_error"), "judge_tokens": v.get("judge_tokens"),
        }
        with io.open(args.out, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        flag = rec.get("judge_error") or rec.get("correct")
        print("[%d/%d] %-8s %-6s -> %s" % (n, len(todo), r["_arm"], r["id"], flag), flush=True)

    print("\ndone in %.0fs -> %s" % (time.time() - started, args.out))


if __name__ == "__main__":
    main()
