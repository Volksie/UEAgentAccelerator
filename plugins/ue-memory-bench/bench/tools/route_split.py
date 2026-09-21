"""Route match, split by whether the baseline arm could take the route at all.

WHY THIS EXISTS. *arm-comparison-v2.md* reported "baseline used the intended route on 43 of 160,
layers on 129 of 160" as if it were a comparison. It is not one. 128 of the 160 expected routes name
a generated artefact, a Layer 4 instruction file or the engine-api server, and isolation moves every
one of those out of the tree for the baseline run. On those questions the baseline arm scores near
zero **by construction**, however good its answer, so the headline gap measured the isolation script
rather than the agent.

Split the set and the picture is honest, and more interesting:

  * where the route names a layer artefact, baseline 10.9% against layers 82.0% (n=128). The 10.9%
    is not skill, it is the judge crediting a near-enough substitute.
  * where the route is reachable in both arms, baseline 87.5% against layers 84.4% (n=32). Dead
    level, inside the 1.3-point judging error bar.

**That second line is v2's, and it does not survive the set changing.** On the 170-question set the
buckets are n=151 and n=19 rather than 128 and 32 - more questions name a layer artefact, so
"reachable in both arms" is a smaller and different set of questions and the two are not comparable.
Within it the arms are not level: baseline 10/19 against layers 15/19 in v3, and 8/19 against 18/19 in
v4 and again in v5. At n=19 one question is 5.3 points, so read that as a direction and not as a
measurement - but the sentence that the layers arm has no edge at taking a route both arms can take is
a v2 finding only, and was reported as a general one.

It lasted three measured versions because this script hardcoded v2's runset and scores file and named
neither in its output, so it printed v2's split for every run and agreed with this docstring exactly.
Which is the argument for the provenance line it now prints first.
"""
import argparse, json, io, collections, re, os

# Machine specific, so environment overridable. Defaults to the repository root two levels
# above this file. Same pattern as run_bench.py.
# The tree, searched for rather than counted. See _tree_root.py: two-levels-up is right
# until something moves, and then every path built on it is quietly wrong.
from _tree_root import find_tree_root
T = find_tree_root(os.path.dirname(os.path.abspath(__file__)))

_ap = argparse.ArgumentParser(description=__doc__,
                              formatter_class=argparse.RawDescriptionHelpFormatter)
_ap.add_argument('--runset', default=os.path.join(T, 'bench', 'runset-full.json'),
                 help='the runset, for each question expected route')
_ap.add_argument('--scores', default=os.path.join(T, 'bench', 'runs', 'scores.jsonl'),
                 help='the scored answers, which carry the route the run actually took')
# Optional: groups that define no expected route in the frozen set can have them supplied as an
# overlay rather than by editing the set, which would make it a different set.
_ap.add_argument('--overlay', default=os.path.join(T, 'bench', 'expected-routes-overlay.json'),
                 help='extra expected routes, keyed by question id. Skipped if absent')
# Corrections OVERRIDE a route the set defines wrongly, where the overlay only fills one that is
# missing. The classification below turns on the route string, so a corrected route can move a
# question between the two buckets - same precedence the scorer uses.
_ap.add_argument('--corrections', default=os.path.join(T, 'bench', 'expected-routes-corrections.json'),
                 help='expected routes the set defines WRONGLY. Skipped if absent')
_args = _ap.parse_args()

for _label, _p in (('runset', _args.runset), ('scores', _args.scores)):
    if not os.path.exists(_p):
        raise SystemExit('no %s at %s. Pass --%s.' % (_label, _p, _label))

rs = json.load(io.open(_args.runset, encoding='utf-8'))
ov = {}
if os.path.exists(_args.overlay):
    ov = json.load(io.open(_args.overlay, encoding='utf-8'))


def overlay_route(qid):
    v = ov.get(qid)
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        return v.get('route') or v.get('expected_route') or ''
    return ''


def _load_corrections(path):
    if not os.path.exists(path):
        return {}
    d = json.load(io.open(path, encoding='utf-8'))
    return {k: v for k, v in d.items() if not k.startswith('_')}


corr = _load_corrections(_args.corrections)


def correction_route(qid):
    v = corr.get(qid)
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        return v.get('route') or v.get('expected_route') or ''
    return ''


route = {}
for r in rs:
    route[r['id']] = (correction_route(r['id']) or r.get('route')
                      or overlay_route(r['id']) or '').strip()

# Anything naming a generated artefact, a Layer 3 instruction file, a design doc, or the engine-api
# server is a route the baseline arm physically cannot take: isolation moved the file out of the tree.
LAYER_TERMS = [
    'agentmemory', 'index.md', 'blueprints.md', 'blueprintcallers', 'bpcallers',
    'classes/', 'classes\\', 'blueprints/', 'reflection', 'manifest.md',
    'claude.md', '.claude', 'layer 3', 'layer 2', 'docs/design', 'docs\\design',
    'design doc', 'design tier', 'engine-api', 'engine_api', 'routing table',
    # Add your own tree's instruction and design file names here. A route naming one of those is a
    # route the baseline arm could not have taken, and a term missing from this list scores it as
    # though it could.
]


def is_layer_route(er):
    low = er.lower()
    return any(t in low for t in LAYER_TERMS)


rows = [json.loads(l) for l in io.open(_args.scores,
                                       encoding='utf-8')]
passes = collections.defaultdict(list)
for r in rows:
    passes[(r['arm'], r['id'])].append(r.get('route_match'))

maj = {}
for k, v in passes.items():
    c = collections.Counter(x for x in v if x)
    maj[k] = c.most_common(1)[0][0] if c else None

layer_ids, both_ids, none_ids = [], [], []
for qid, er in route.items():
    if not er:
        none_ids.append(qid)
    elif is_layer_route(er):
        layer_ids.append(qid)
    else:
        both_ids.append(qid)


def rate(ids, arm):
    hit = sum(1 for i in ids if maj.get((arm, i)) == 'Y')
    return hit, len(ids), (100.0 * hit / len(ids) if ids else 0.0)


print('runset:  %s  (%d questions)' % (_args.runset, len(rs)))
print('scores:  %s  (%d rows)' % (_args.scores, len(rows)))
if corr:
    print('corrections applied: %s' % ', '.join(sorted(corr)))
print()
print('routes defined: %d   undefined: %d' % (len(layer_ids) + len(both_ids), len(none_ids)))
print()
for name, ids in (('route names a layer artefact', layer_ids),
                  ('route reachable in both arms', both_ids)):
    b = rate(ids, 'baseline')
    l = rate(ids, 'layers')
    print('%-30s n=%3d   baseline %3d/%-3d %5.1f%%   layers %3d/%-3d %5.1f%%'
          % (name, len(ids), b[0], b[1], b[2], l[0], l[1], l[2]))

print()
# Over the set that was actually read. This divided by a literal 160 - the size of one early set - so
# the percentage was wrong for every run of any other size, silently.
n_set = len(rs)
for arm in ('baseline', 'layers'):
    hit = sum(1 for (a, i), v in maj.items() if a == arm and v == 'Y')
    print('overall (the figure now being retired): %-9s %d/%d  %.0f%%'
          % (arm, hit, n_set, 100.0 * hit / n_set if n_set else 0.0))

print()
print('by group, both-reachable only:')
grp = {r['id']: r['group'] for r in rs}
g = collections.defaultdict(lambda: [0, 0, 0])
for i in both_ids:
    g[grp[i]][0] += 1
    g[grp[i]][1] += 1 if maj.get(('baseline', i)) == 'Y' else 0
    g[grp[i]][2] += 1 if maj.get(('layers', i)) == 'Y' else 0
for k in sorted(g):
    n, b, l = g[k]
    print('  %-2s n=%2d  baseline %2d  layers %2d' % (k, n, b, l))

print()
print('both-reachable ids: %s' % ', '.join(sorted(both_ids)))
