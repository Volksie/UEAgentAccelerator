"""Did the ten questions added for v3 actually work?

A new question can fail in ways a green run hides. It can error or time out; it can turn out trivial,
so both arms answer it in two turns and it measures the model; it can be unanswerable, so the arm
flails and gives up; or its key can be unjudgeable, which only shows up when a judge disagrees with
itself. This reports the first three from one arm's data, and prints the answers so the fourth can be
judged by a person.

Usage:
    python bench/tools/assess_new_questions.py bench/runs/results-baseline-v3.jsonl
"""
import io, json, os, re, sys, collections, statistics

# The tree, searched for rather than counted. See _tree_root.py: two-levels-up is right
# until something moves, and then every path built on it is quietly wrong.
from _tree_root import find_tree_root
TREE = find_tree_root(os.path.dirname(os.path.abspath(__file__)))

# Phrases that mean an answer saw the run rather than the codebase. A new question judged on a
# contaminated answer is being judged on the wrong thing, so it is flagged rather than scored.
#
# The last three are the names OUR leaks came through - a run marker, a tree-root document, a
# pipeline log directory. **Replace them with yours.** The generic phrases above them catch an answer
# that says out loud it knows it is being measured, which is the half that transfers.
LEAK = re.compile(r'BENCH-RUN-IN-PROGRESS|benchmark run|being measured|bench-holding|'
                  r'temporarily moved|VERSION\.md|REVIEW-independent|_stackrun', re.I)
REFUSAL = re.compile(r"haven'?t granted|not granted|didn'?t approve|requires? approval|"
                     r"permission (?:to|for|denied)|don'?t have permission", re.I)
# An answer that declines rather than answers.
DECLINED = re.compile(r"can'?t answer|cannot answer|unable to (?:answer|determine)|"
                      r"after the (?:run|benchmark)|once the run|I did not find|no way to tell", re.I)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        TREE, 'bench', 'runs', 'results-baseline-full.jsonl')
    if not os.path.exists(path):
        sys.exit('no results at %s' % path)
    rows = {json.loads(l)['id']: json.loads(l) for l in io.open(path, encoding='utf-8')}

    add_path = os.path.join(TREE, 'bench', 'questions-v3-additions.json')
    added = json.load(io.open(add_path, encoding='utf-8'))['questions']
    new_ids = [q['id'] for q in added]
    keys = {q['id']: q for q in added}

    # Group baselines to compare against, computed from questions that are NOT new.
    by_group = collections.defaultdict(list)
    for qid, r in rows.items():
        if qid not in new_ids:
            by_group[r.get('group')].append(r.get('turns') or (r.get('calls') or 0) + 1)

    print('=' * 78)
    print('THE TEN ADDED QUESTIONS, against %s' % os.path.basename(path))
    print('=' * 78)
    missing = [q for q in new_ids if q not in rows]
    if missing:
        print('NOT RUN: %s\n' % ', '.join(missing))

    hdr = '%-6s %-6s %6s %8s  %-9s %-9s %s'
    print(hdr % ('id', 'group', 'turns', 'vs grp', 'leak?', 'refusal?', 'state'))
    print('-' * 78)
    flags = collections.Counter()
    for qid in new_ids:
        r = rows.get(qid)
        if not r:
            continue
        a = r.get('answer') or ''
        turns = r.get('turns') or (r.get('calls') or 0) + 1
        peers = by_group.get(r.get('group')) or []
        med = statistics.median(peers) if peers else 0
        ratio = ('%.1fx' % (turns / med)) if med else '-'
        leak = 'LEAKED' if LEAK.search(a) else '-'
        refusal = 'REFUSED' if REFUSAL.search(a) else '-'
        state = 'ERROR' if r.get('is_error') else ('TIMEOUT' if r.get('timed_out') else
                ('declined' if DECLINED.search(a) else ('blank' if not a.strip() else 'answered')))
        for k, v in (('leak', leak != '-'), ('refusal', refusal != '-'),
                     ('declined', state == 'declined'), ('error', state in ('ERROR', 'TIMEOUT'))):
            if v:
                flags[k] += 1
        print(hdr % (qid, r.get('group'), turns, ratio, leak, refusal, state))

    print('\nflags: %s' % (dict(flags) or 'none'))
    print('\nHow to read "vs grp": turns against the median of the OTHER questions in the same group.')
    print('Near 1.0 means the new question costs what its group costs. Much below 1.0 on the baseline')
    print('arm is the warning sign - it suggests the question is easier than intended, which is how a')
    print('replacement ends up measuring the model again.')

    print('\n' + '=' * 78)
    print('ANSWERS, for judging the keys by eye. The key follows each answer.')
    print('=' * 78)
    for qid in new_ids:
        r = rows.get(qid)
        if not r:
            continue
        print('\n--- %s (%s) %s' % (qid, r.get('group'), '-' * 50))
        print('Q:   %s' % keys[qid]['question'])
        print('\nGOT: %s' % (r.get('answer') or '(blank)').strip()[:1400])
        print('\nKEY: %s' % keys[qid]['key'][:700])


if __name__ == '__main__':
    main()
