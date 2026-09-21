"""Build machine-readable run sets from the two question sources.

questions-160.json holds the 105 generated questions. The 55 hand written ones (groups D, G, I)
exist only as markdown tables in questions-handwritten.md, in three different column layouts.
This merges both into one schema the runner can consume, and emits the smoke tier listed in
smoke-20.md.

Output is deterministic and sorted; regenerate rather than hand edit.
"""
import json, io, re, sys, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # bench/
# Defaults. The generated set is the only one you always have; a hand written set and a smoke list
# are optional, because a tree that has only ever run the generator has neither.
GEN = os.path.join(ROOT, "questions.json")
HAND = os.path.join(ROOT, "questions-handwritten.md")
SMOKE_MD = os.path.join(ROOT, "smoke.md")
V2_OVERLAY = os.path.join(ROOT, "questions-v2-overlay.json")

# id prefix -> (group, column names in table order after the id column)
LAYOUTS = {
    "D": ("D", ["project", "question", "key", "findable_in", "route"]),
    "G": ("G", ["project", "question", "key", "checked_by"]),
    "I": ("I", ["question", "key"]),
}

def split_row(line):
    # a markdown table row; strip the leading and trailing pipe, then split.
    # answer keys contain no unescaped pipes in this file - asserted below.
    inner = line.strip()
    if not inner.startswith("|") or not inner.endswith("|"):
        return None
    return [c.strip() for c in inner[1:-1].split("|")]

def parse_handwritten(path):
    out = []
    seen = set()
    for line in io.open(path, encoding="utf-8"):
        cells = split_row(line)
        if not cells:
            continue
        ident = cells[0]
        m = re.fullmatch(r"([DGI])(\d+)", ident)
        if not m:
            continue
        prefix = m.group(1)
        group, cols = LAYOUTS[prefix]
        rest = cells[1:]
        if len(rest) != len(cols):
            print("WARN %s: expected %d columns, got %d - skipped"
                  % (ident, len(cols), len(rest)), file=sys.stderr)
            continue
        if ident in seen:
            print("WARN %s: duplicate id - skipped" % ident, file=sys.stderr)
            continue
        seen.add(ident)
        rec = {"id": ident, "group": group, "source": "handwritten"}
        rec.update(dict(zip(cols, rest)))
        rec.setdefault("project", "-")
        out.append(rec)
    return out

def parse_generated(path):
    d = json.load(io.open(path, encoding="utf-8"))
    out = []
    for q in d["questions"]:
        r = dict(q)
        r["source"] = "generated"
        out.append(r)
    return out

def parse_smoke_ids(path):
    ids = []
    for line in io.open(path, encoding="utf-8"):
        cells = split_row(line)
        if not cells:
            continue
        if re.fullmatch(r"(Q\d+|[DGI]\d+)", cells[0]):
            ids.append(cells[0])
    return ids

def sort_key(rec):
    m = re.fullmatch(r"([A-Z]+)(\d+)", rec["id"])
    return (m.group(1), int(m.group(2)))

def apply_v2(questions):
    """Apply bench/questions-v2-overlay.json on top of the frozen v1 set.

    An overlay rather than an edit, because v1 produced bench/arm-comparison.md and changing it
    would invalidate that table. Entries carry a `_change` field explaining themselves; it is
    dropped from the emitted question but kept in the overlay as the record.
    """
    if not os.path.exists(V2_OVERLAY):
        raise SystemExit("missing %s" % V2_OVERLAY)
    ov = json.load(io.open(V2_OVERLAY, encoding="utf-8"))
    ov = {k: v for k, v in ov.items() if not k.startswith("_")}
    applied = []
    for q in questions:
        patch = ov.get(q["id"])
        if not patch:
            continue
        for field, value in patch.items():
            if field.startswith("_"):
                continue
            q[field] = value
        q["v2_change"] = patch.get("_change", "changed")
        applied.append(q["id"])
    missing = sorted(set(ov) - set(applied))
    if missing:
        raise SystemExit("overlay names ids not in the set: %s" % missing)
    print("v2 overlay applied to %d questions: %s" % (len(applied), ", ".join(sorted(applied))))
    return questions


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", default=GEN,
                    help="generated question set, as written by make_questions.py")
    ap.add_argument("--handwritten", default=None,
                    help="optional markdown tables of hand written questions to merge in")
    ap.add_argument("--smoke", default=None,
                    help="optional markdown listing the ids for the smoke tier")
    ap.add_argument("--out-prefix", default="runset",
                    help="output name stem; writes <stem>-full.json and <stem>-smoke.json")
    ap.add_argument("--v2", action="store_true",
                    help="apply questions-v2-overlay.json and suffix the outputs with -v2")
    args = ap.parse_args()

    if not os.path.exists(args.questions):
        sys.exit("No question set at %s. Run make_questions.py first." % args.questions)

    gen = parse_generated(args.questions)

    # Hand written questions are merged when you have them. Groups that cannot be derived
    # mechanically live there, so a set without them is smaller rather than wrong.
    hand = []
    if args.handwritten:
        if not os.path.exists(args.handwritten):
            sys.exit("No hand written questions at %s." % args.handwritten)
        hand = parse_handwritten(args.handwritten)
    elif os.path.exists(HAND):
        hand = parse_handwritten(HAND)

    allq = sorted(gen + hand, key=sort_key)

    ids = [q["id"] for q in allq]
    assert len(ids) == len(set(ids)), "duplicate question ids"
    print("generated: %d  handwritten: %d  total: %d" % (len(gen), len(hand), len(allq)))
    from collections import Counter
    print("by group :", dict(sorted(Counter(q["group"] for q in allq).items())))

    by_id = {q["id"]: q for q in allq}

    # The smoke tier is optional. Without a list there is simply no smoke runset, which is better
    # than inventing one: which twenty questions represent a set is a judgement, not a sample.
    smoke = None
    smoke_path = args.smoke or (SMOKE_MD if os.path.exists(SMOKE_MD) else None)
    if smoke_path:
        smoke_ids = parse_smoke_ids(smoke_path)
        missing = [i for i in smoke_ids if i not in by_id]
        if missing:
            print("ERROR smoke ids not found in question set: %s" % missing, file=sys.stderr)
            return 1
        smoke = [by_id[i] for i in smoke_ids]
        print("smoke    : %d questions -> %s" % (len(smoke), ", ".join(smoke_ids)))
    else:
        print("smoke    : no smoke list, writing the full runset only")

    suffix = "-v2" if args.v2 else ""
    if args.v2:
        allq = apply_v2(allq)
        by_id = {q["id"]: q for q in allq}
        if smoke is not None:
            smoke = [by_id[i] for i in smoke_ids]

    outputs = [("%s-full%s.json" % (args.out_prefix, suffix), allq)]
    if smoke is not None:
        outputs.append(("%s-smoke%s.json" % (args.out_prefix, suffix), smoke))

    for name, data in outputs:
        p = os.path.join(ROOT, name)
        with io.open(p, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)
            f.write("\n")
        print("wrote %s" % name)
    return 0
if __name__ == "__main__":
    sys.exit(main())
