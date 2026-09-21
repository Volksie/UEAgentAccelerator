#!/usr/bin/env python3
"""
Turn sampled candidates into fully formed benchmark questions with mechanically derived
answer keys. The rules it follows are in bench/METHOD.md.

sample_candidates.py stops at "here is a symbol worth asking about". This goes the rest of
the way and writes the question text and the key, which is what takes groups A, B, C, E and F
from a week of hand authoring down to a review pass.

The rule from section 4 stands: never use the tool under test as the source of its own answer
key. Every key here comes from the reflection artefacts, which are independent of clangd.
Group C carries a 25 percent hand check rather than 10, because in Phase 4 the reflection walk
is itself the tool under test. Every group F key is hand checked without exception, because an
incorrect "no" is the worst error this file can contain.

Reads only Docs/AgentMemory. A candidate the artefacts cannot describe is not a fair question
to ask of the artefact tier.

Usage:
  python make_questions.py --root . --seed 1 --config bench/projects.json --out bench/questions.md
"""
import argparse, collections, json, os, random, re, sys

def load_config(path):
    """Which projects to draw questions from, and how many from each.

    Externalised so this runs on any tree. The shape is multi-project because a stratum needs a
    population to be sampled from and no one project has all of them, but a single project is the
    default and is enough to get a set out of your own code. See bench/projects.json.
    """
    try:
        with open(path, encoding='utf-8') as f:
            cfg = json.load(f)
    except OSError as exc:
        sys.exit('cannot read config %s: %s' % (path, exc))
    if not cfg.get('projects'):
        sys.exit('%s lists no projects' % path)
    seen = set()
    for p in cfg['projects']:
        for field in ('key', 'dir'):
            if not p.get(field):
                sys.exit('every project needs a %s: %r' % (field, p))
        if p['key'] in seen:
            sys.exit('duplicate project key %r' % p['key'])
        seen.add(p['key'])
    return cfg

# ---------------------------------------------------------------- artefact loading

def read(p):
    try:
        with open(p, encoding='utf-8') as f: return f.read()
    except OSError: return ''

def cells(line):
    """Split a markdown table row into stripped, backtick free cells. None if not a row."""
    s = line.strip()
    if not s.startswith('|') or set(s) <= set('|- '): return None
    return [c.strip().strip('`').strip() for c in s.strip('|').split('|')]

class Bank:
    """Everything the artefacts know about one project."""
    def __init__(self, spec, root):
        self.name = spec['key']
        self.spec = spec
        self.dir  = os.path.join(root, spec['dir'], 'Docs', 'AgentMemory')
        # Hand written C++ callers for this project, from its cpp_callers config block. Empty is
        # fine, and is the right answer for a project too large to keep them true by hand.
        self.cpp_callers = spec.get('cpp_callers', {})
        self.classes, self.detail = {}, {}
        self.blueprints, self.edges = [], []
        self._load()

    def _load(self):
        for line in read(os.path.join(self.dir, 'index.md')).split('\n'):
            c = cells(line)
            if not c or len(c) < 7 or c[0] == 'Class': continue
            try: fns, props, rep = int(c[3]), int(c[4]), int(c[5])
            except ValueError: continue
            self.classes[c[0]] = dict(cls=c[0], module=c[1], parent=c[2],
                                      fns=fns, props=props, rep=rep)
        for cls in self.classes:
            self.detail[cls] = self._class_detail(cls)
        for line in read(os.path.join(self.dir, 'Blueprints.md')).split('\n'):
            c = cells(line)
            if not c or len(c) < 7 or c[0] == 'Blueprint': continue
            self.blueprints.append(dict(path=c[0], native=c[1], parent=c[2], interfaces=c[3],
                                        rep=c[4], dataonly=c[5], comps=c[6]))
        for line in read(os.path.join(self.dir, 'BlueprintCallers.md')).split('\n'):
            c = cells(line)
            if not c or len(c) < 4 or c[0] == 'Symbol': continue
            self.edges.append(dict(symbol=c[0], bp=c[1], graph=c[2], kind=c[3]))

    def _class_detail(self, cls):
        txt = read(os.path.join(self.dir, 'classes', cls + '.md'))
        d = dict(chain='', doc='', fns=[], props=[])
        section = None
        for line in txt.split('\n'):
            if line.startswith('- Inherits:'): d['chain'] = line.split(':', 1)[1].strip(); continue
            if line.startswith('- Doc:'):      d['doc']   = line.split(':', 1)[1].strip(); continue
            if line.startswith('### Functions'):  section = 'f'; continue
            if line.startswith('### Properties'): section = 'p'; continue
            if line.startswith('#'): section = None; continue
            c = cells(line)
            if not c: continue
            if section == 'f' and len(c) >= 2 and c[0] != 'Function':
                d['fns'].append(dict(name=c[0], spec=c[1], doc=c[2] if len(c) > 2 else ''))
            elif section == 'p' and len(c) >= 4 and c[0] != 'Property':
                d['props'].append(dict(name=c[0], type=c[1], spec=c[2], rep=c[3],
                                       doc=c[4] if len(c) > 4 else ''))
        return d

    def children_of(self, parent):
        return sorted(c for c, r in self.classes.items() if r['parent'] == parent)

    def replicated(self, cls):
        return [p for p in self.detail[cls]['props'] if p['rep']]

    def with_spec(self, cls, spec):
        return sorted(f['name'] for f in self.detail[cls]['fns']
                      if spec in [s.strip() for s in f['spec'].split(',')])

    def edges_for(self, symbol):
        return [e for e in self.edges if e['symbol'] == symbol]

    def called_symbols(self):
        return {e['symbol'] for e in self.edges}

def area_for(bank, module):
    """Area label for one module, taken from the project's own rules in the config.

    The spec's area table assumes a real game plus the engine tree. Any one project stands in for
    part of that, so the mapping is by module and has to be declared per project rather than
    guessed here. First matching rule wins."""
    m = module or ''
    areas = bank.spec.get('areas') or {}
    for rule in areas.get('rules') or []:
        if 'module_contains' in rule and rule['module_contains'] in m:
            return rule['area']
        if 'module_in' in rule and m in rule['module_in']:
            return rule['area']
    return areas.get('default', 'Project code')

# ---------------------------------------------------------------- assembly

class Out:
    def __init__(self): self.qs = []
    def extend(self, items):
        for kw in items:
            kw['id'] = 'Q%03d' % (len(self.qs) + 1)
            self.qs.append(kw)

def fill(rng, pools, target):
    """Round robin across the shape pools until we hit the target, or run out.

    Round robin rather than a fixed split per shape, because populations differ wildly between
    projects and a fixed split silently under-delivers. A shortfall is reported rather than
    quietly absorbed: it is the signal that the stratum needs the engine tier."""
    pools = [list(p) for p in pools]
    for p in pools: rng.shuffle(p)
    out, i = [], 0
    while len(out) < target and any(pools):
        p = pools[i % len(pools)]
        if p: out.append(p.pop())
        i += 1
    return out

# ---------------------------------------------------------------- group A

def A_definition_site(b, proj):
    return [dict(group='A', shape='definition site', project=proj,
                 area=area_for(b, r['module']), scoring='exact',
                 question='Which module declares `%s`, and what is its immediate parent class?' % r['cls'],
                 key='Module `%s`, parent `%s`.' % (r['module'], r['parent']),
                 route='index.md row, or find_symbol')
            for r in b.classes.values() if r['parent'] not in ('', '-')]

def A_property_type(b, proj):
    return [dict(group='A', shape='property type', project=proj,
                 area=area_for(b, r['module']), scoring='exact',
                 question='What is the declared type of `%s::%s`?' % (r['cls'], p['name']),
                 key='`%s`' % p['type'],
                 route='classes/%s.md, or the header' % r['cls'])
            for r in b.classes.values()
            for p in b.detail[r['cls']]['props'] if p['type']]

def A_function_doc(b, proj):
    return [dict(group='A', shape='function purpose', project=proj,
                 area=area_for(b, r['module']), scoring='prose',
                 question='What does `%s::%s` do, and what are its `UFUNCTION` specifiers?'
                          % (r['cls'], f['name']),
                 key='%s  Specifiers: %s' % (f['doc'].rstrip(' .') + '.', f['spec']),
                 route='classes/%s.md Functions table' % r['cls'])
            for r in b.classes.values()
            for f in b.detail[r['cls']]['fns'] if f['doc']]

# ---------------------------------------------------------------- group B

def _chain(b, cls):
    d = b.detail.get(cls)
    if not d or not d['chain']: return []
    return [cls] + [x.strip() for x in d['chain'].split('->')]

def _nearest_common(b, a, c):
    ca, cc = _chain(b, a), _chain(b, c)
    if not ca or not cc or a == c: return None
    s = set(cc)
    for x in ca[1:]:
        if x in s: return x
    return None

def B_chain(b, proj):
    return [dict(group='B', shape='inheritance chain', project=proj,
                 area=area_for(b, r['module']), scoring='exact',
                 question='What is the full native inheritance chain of `%s`, from its immediate '
                          'parent up to `UObject`?' % r['cls'],
                 key=b.detail[r['cls']]['chain'],
                 route='classes/%s.md Inherits line, or repeated find_symbol' % r['cls'])
            for r in b.classes.values() if b.detail[r['cls']]['chain'].count('->') >= 2]

def B_common_ancestor(b, proj, rng):
    by_mod = collections.defaultdict(list)
    for r in b.classes.values(): by_mod[r['module']].append(r)
    mods = [m for m, v in by_mod.items() if len(v) >= 2]
    seen, out = set(), []
    for _ in range(800):
        if len(mods) < 2: break
        m1, m2 = rng.sample(mods, 2)
        a, c = rng.choice(by_mod[m1]), rng.choice(by_mod[m2])
        k = tuple(sorted((a['cls'], c['cls'])))
        if k in seen: continue
        ca = _nearest_common(b, a['cls'], c['cls'])
        if not ca: continue
        seen.add(k)
        out.append(dict(group='B', shape='common ancestor', project=proj,
                        area=area_for(b, a['module']), scoring='exact',
                        question='`%s` and `%s` are declared in different modules. Do they share a '
                                 'common ancestor, and what is the nearest one?' % (a['cls'], c['cls']),
                        key='Yes: `%s`.' % ca,
                        route='two Inherits lines, or two find_symbol chains'))
    return out

def B_declared_where(b, proj):
    out = []
    for r in b.classes.values():
        parent = r['parent']
        if parent not in b.detail: continue
        own = {f['name'] for f in b.detail[r['cls']]['fns']}
        inherited = sorted({f['name'] for f in b.detail[parent]['fns']} - own)
        for name in inherited[:2]:
            out.append(dict(group='B', shape='declared where', project=proj,
                            area=area_for(b, r['module']), scoring='exact',
                            question='Is `%s` declared on `%s` itself, or inherited? If inherited, '
                                     'from where?' % (name, r['cls']),
                            key='Inherited from `%s`. `%s` does not redeclare it.' % (parent, r['cls']),
                            route='compare classes/%s.md with classes/%s.md' % (r['cls'], parent)))
    return out

# ---------------------------------------------------------------- group C

def C_replication(b, proj):
    out = []
    for r in b.classes.values():
        if r['rep'] <= 0: continue
        reps = b.replicated(r['cls'])
        out.append(dict(group='C', shape='replication condition', project=proj,
                        area=area_for(b, r['module']), scoring='set', handcheck=True,
                        question='Which `UPROPERTY`s on `%s` replicate, and under what condition?' % r['cls'],
                        key='; '.join('`%s` %s' % (p['name'], p['rep']) for p in reps) or 'none',
                        keyset=[p['name'] for p in reps],
                        route='classes/%s.md Replication column. The conditions live in '
                              'GetLifetimeReplicatedProps, not in the header, so clangd cannot '
                              'answer this even in principle' % r['cls']))
    return out

def C_specifier(b, proj):
    out = []
    for r in b.classes.values():
        s = b.with_spec(r['cls'], 'BlueprintCallable')
        if not s: continue
        out.append(dict(group='C', shape='specifier set', project=proj,
                        area=area_for(b, r['module']), scoring='set', handcheck=True,
                        question='Which `UFUNCTION`s on `%s` are `BlueprintCallable`?' % r['cls'],
                        key=', '.join('`%s`' % x for x in s), keyset=s,
                        route='classes/%s.md Specifiers column' % r['cls']))
    return out

def C_pure(b, proj):
    out = []
    for r in b.classes.values():
        s = b.with_spec(r['cls'], 'BlueprintPure')
        if not s: continue
        out.append(dict(group='C', shape='BlueprintPure set', project=proj,
                        area=area_for(b, r['module']), scoring='set', handcheck=True,
                        question='Which `UFUNCTION`s on `%s` are `BlueprintPure`, and what does that '
                                 'change about how a graph calls them?' % r['cls'],
                        key=', '.join('`%s`' % x for x in s), keyset=s,
                        route='classes/%s.md Specifiers column' % r['cls']))
    return out

def C_network(b, proj):
    out = []
    for r in b.classes.values():
        net = [f for f in b.detail[r['cls']]['fns']
               if re.search(r'\b(Server|Client|NetMulticast)\b', f['spec'])]
        if not net: continue
        out.append(dict(group='C', shape='network function', project=proj,
                        area=area_for(b, r['module']), scoring='set', handcheck=True,
                        question='Which `UFUNCTION`s on `%s` are RPCs, of what kind, and which of '
                                 'them are reliable?' % r['cls'],
                        key='; '.join('`%s` (%s)' % (f['name'], f['spec']) for f in net),
                        keyset=[f['name'] for f in net],
                        route='classes/%s.md Specifiers column' % r['cls']))
    return out

# ---------------------------------------------------------------- group E

def E_subclasses(b, proj):
    out = []
    for parent in {r['parent'] for r in b.classes.values()}:
        kids = b.children_of(parent)
        if len(kids) < 2: continue
        out.append(dict(group='E', shape='direct subclasses', project=proj,
                        area=area_for(b, b.classes[kids[0]]['module']), scoring='set',
                        question='List every reflected class in this project that derives directly '
                                 'from `%s`. I need the complete set.' % parent,
                        key=', '.join('`%s`' % k for k in kids), keyset=kids,
                        route='grep the Inherits column of index.md'))
    return out

def E_bp_subclasses(b, proj):
    byn = collections.defaultdict(list)
    for bp in b.blueprints: byn[bp['native']].append(bp['path'])
    out = []
    for nat, v in byn.items():
        if not (2 <= len(v) <= 25): continue
        kids = sorted(v)
        out.append(dict(group='E', shape='blueprint subclasses', project=proj,
                        area='Blueprints', scoring='set',
                        question='List every Blueprint in this project whose ultimate native parent '
                                 'is `%s`. I need the complete set.' % nat,
                        key='%d Blueprints: %s' % (len(kids), ', '.join('`%s`' % k for k in kids)),
                        keyset=kids,
                        route='Blueprints.md Native parent column. No C++ tool can see this'))
    return out


def E_blast(b, proj, lo=2, hi=15, hand=False):
    """Only symbols this project actually owns.

    Most of the 4,073 Lyra edges land on engine functions, and "if I change the signature of
    AIController::RunBehaviorTree" is not a change anyone here is going to make. The question is
    only worth asking about code we can break, so the owning class has to be in our own index."""
    counts = collections.Counter(e['symbol'] for e in b.edges)
    out = []
    for sym, c in counts.items():
        if not (lo <= c <= hi): continue
        if sym.split('::')[0] not in b.classes: continue
        es = b.edges_for(sym)
        bps = sorted({e['bp'] for e in es})
        kinds = {e['kind'] for e in es}
        # A property read is broken by a rename, not by a signature change. Getting this wrong
        # in the question makes the question itself unanswerable.
        if kinds <= {'read', 'write'}:
            verb = 'rename the `UPROPERTY` `%s`' % sym
        elif kinds <= {'call'}:
            verb = 'change the signature of `%s`' % sym
        else:
            verb = 'rename or change the signature of `%s`' % sym
        key = '%d Blueprint graph(s): %s' % (len(bps), ', '.join('`%s`' % x for x in bps))
        key += ' (used as: %s)' % ', '.join(sorted(kinds))
        if hand:
            cpp = b.cpp_callers.get(sym)
            key += '. ' + (cpp if cpp else
                           '**The C++ callers still need adding to this key by hand: the '
                           'artefacts carry only the Blueprint half.**')
        q = dict(group='E', shape='blueprint blast radius', project=proj,
                 area='Blueprints', scoring='set',
                 question='If I %s, which Blueprint graphs break? I need the complete list, C++ '
                          'and Blueprint.' % verb,
                 key=key, keyset=bps,
                 route='BlueprintCallers.md. clangd cannot see .uasset files, ripgrep skips them '
                       'silently, and renaming this symbol still compiles clean')
        if hand: q['handcheck'] = True
        out.append(q)
    return out

# ---------------------------------------------------------------- group F

def F_no_rep(b, proj):
    return [dict(group='F', shape='no replication', project=proj,
                 area=area_for(b, r['module']), scoring='empty_set', handcheck=True,
                 question='Which properties on `%s` replicate?' % r['cls'],
                 key='None. It declares %d properties and not one of them replicates.' % r['props'],
                 keyset=[],
                 route='classes/%s.md, Replication column empty throughout' % r['cls'])
            for r in b.classes.values() if r['rep'] == 0 and r['props'] > 0]

def F_no_ufunction(b, proj):
    return [dict(group='F', shape='no UFUNCTION', project=proj,
                 area=area_for(b, r['module']), scoring='empty_set', handcheck=True,
                 question='Does `%s` declare any `UFUNCTION`? If so, which?' % r['cls'],
                 key='No. It is a reflected class but declares no UFUNCTION at all.',
                 keyset=[],
                 route='index.md, Fns column reads 0')
            for r in b.classes.values() if r['fns'] == 0]

def F_no_bp_caller(b, proj):
    called = b.called_symbols()
    out = []
    for r in b.classes.values():
        for f in b.with_spec(r['cls'], 'BlueprintCallable'):
            sym = '%s::%s' % (r['cls'], f)
            if sym in called: continue
            out.append(dict(group='F', shape='no Blueprint caller', project=proj,
                            area='Blueprints', scoring='empty_set', handcheck=True,
                            question='`%s` is `BlueprintCallable`. Is it actually called from any '
                                     'Blueprint graph in this project?' % sym,
                            key='No. It is exposed to Blueprint but no graph calls it. A full marks '
                                'answer says it checked, rather than merely reporting nothing found.',
                            keyset=[],
                            route='BlueprintCallers.md, absent. Answering from the header is the '
                                  'trap: BlueprintCallable says it could be called, not that it is'))
    return out


# ---------------------------------------------------------------- group H

DECL = re.compile(r'^\s*(?:UPROPERTY|UFUNCTION)?[^;{]*?\b(\w+)\s*(?:\(|;|=)')

def H_deprecated(engine_root, rng, want):
    """Deprecation questions, from the engine tree.

    None of the three benchmark projects contains a single UE_DEPRECATED, so this stratum
    cannot come from them at all. The engine headers carry 1,742 of them, and the macro is
    self documenting: it holds the version it was deprecated in and the message naming the
    replacement, so the key derives mechanically rather than by hand.
    """
    if not engine_root or not os.path.isdir(engine_root): return []
    dirs = [os.path.join(engine_root, d) for d in (
        'Runtime/Engine/Classes', 'Runtime/Engine/Public', 'Runtime/CoreUObject/Public')]
    pat = re.compile(r'UE_DEPRECATED\(\s*([0-9.]+)\s*,\s*"((?:[^"\\]|\\.)*)"\s*\)')
    out = []
    for d in dirs:
        for base, sub, files in os.walk(d):
            for fn in files:
                if not fn.endswith('.h'): continue
                path = os.path.join(base, fn)
                lines = read(path).split('\n')
                for i, line in enumerate(lines):
                    m = pat.search(line)
                    if not m: continue
                    sym = ''
                    for nxt in lines[i + 1:i + 4]:
                        s = nxt.strip()
                        if not s or s.startswith(('//', '/*', '#', 'UPROPERTY', 'UFUNCTION',
                                                          'USTRUCT', 'UCLASS', 'UENUM', 'UINTERFACE',
                                                          'UDELEGATE', 'GENERATED_')): continue
                        dm = DECL.match(s)
                        cand = dm.group(1) if dm else ''
                        # A name ending in _DEPRECATED answers the question in the question,
                        # which measures nothing.
                        if cand and not cand.endswith('_DEPRECATED') \
                           and cand not in ('return', 'if', 'else', 'const', 'struct', 'class',
                                            'enum', 'typedef', 'using', 'template', 'friend'):
                            sym = cand
                        break
                    if not sym or len(sym) < 4: continue
                    out.append(dict(group='H', shape='deprecation', project='engine',
                                    area='Runtime/Engine, CoreUObject', scoring='prose',
                                    question='Is `%s` (in `%s`) deprecated? If so, since which '
                                             'engine version, and what replaces it?' % (sym, fn),
                                    key='Yes, deprecated in %s. The macro message reads: "%s"'
                                        % (m.group(1), m.group(2)),
                                    route='UE_DEPRECATED macro on the declaration, and the '
                                          'DeprecationMessage metadata UHT derives from it. '
                                          'Source: %s' % os.path.relpath(path, engine_root)))
    # One per file at most, so ten questions are not ten members of the same deprecated struct.
    seen, uniq = set(), []
    rng.shuffle(out)
    for q in out:
        f = q['route'].rsplit('/', 1)[-1]
        if f in seen: continue
        seen.add(f); uniq.append(q)
    return uniq[:want]

# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='.')
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--out', default='bench/questions.md')
    ap.add_argument('--config', default='bench/projects.json',
                    help='which projects to draw from, and how many questions from each')
    a = ap.parse_args()

    cfg = load_config(a.config)
    rng = random.Random(a.seed)
    banks = {}
    for spec in cfg['projects']:
        b = Bank(spec, a.root)
        if not b.classes:
            sys.exit('no artefacts for %s at %s. Run the dump on that project first.' % (b.name, b.dir))
        banks[b.name] = b

    out, short = Out(), []
    def take(label, target, pools):
        got = fill(rng, pools, target)
        out.extend(got)
        if len(got) < target: short.append((label, target, len(got)))

    def pools_for(group, b, blast):
        """Generators available for one group. A stratum may name a subset in "generators";
        by default it gets all of them, which is what you want unless a group is thin here."""
        p = b.name
        if group == 'A':
            return {'definition_site': lambda: A_definition_site(b, p),
                    'property_type':   lambda: A_property_type(b, p),
                    'function_doc':    lambda: A_function_doc(b, p)}
        if group == 'B':
            return {'chain':           lambda: B_chain(b, p),
                    'common_ancestor': lambda: B_common_ancestor(b, p, rng),
                    'declared_where':  lambda: B_declared_where(b, p)}
        if group == 'C':
            return {'replication': lambda: C_replication(b, p),
                    'specifier':   lambda: C_specifier(b, p),
                    'pure':        lambda: C_pure(b, p),
                    'network':     lambda: C_network(b, p)}
        if group == 'E':
            return {'subclasses':    lambda: E_subclasses(b, p),
                    'bp_subclasses': lambda: E_bp_subclasses(b, p),
                    'blast':         lambda: E_blast(b, p, **blast)}
        if group == 'F':
            return {'no_rep':       lambda: F_no_rep(b, p),
                    'no_ufunction': lambda: F_no_ufunction(b, p),
                    'no_bp_caller': lambda: F_no_bp_caller(b, p)}
        sys.exit('unknown group %r in config' % group)

    for spec in cfg['projects']:
        b = banks[spec['key']]
        for group, s in sorted((spec.get('strata') or {}).items()):
            n = s.get('n', 0)
            if n <= 0: continue
            avail = pools_for(group, b, s.get('blast') or {})
            names = s.get('generators') or sorted(avail)
            unknown = [g for g in names if g not in avail]
            if unknown:
                sys.exit('group %s has no generator(s) %s. Available: %s'
                         % (group, unknown, sorted(avail)))
            take('%s / %s' % (group, b.name), n, [avail[g]() for g in names])

    # Group H comes from the engine tree rather than from any project, because a project with no
    # UE_DEPRECATED in it gives an empty stratum however you sample it.
    eng_n = (cfg.get('engine_strata') or {}).get('H', 0)
    if eng_n:
        if not cfg.get('engine_source'):
            sys.exit('engine_strata asks for group H but engine_source is not set in the config')
        take('H / engine', eng_n,
             [H_deprecated(os.path.join(a.root, cfg['engine_source']), rng, 60)])

    render(out, a, short)

def render(out, a, short):
    by_group = collections.Counter(q['group'] for q in out.qs)
    by_area  = collections.Counter(q['area'] for q in out.qs)
    by_proj  = collections.Counter(q['project'] for q in out.qs)
    L = []
    A = L.append
    A('# Benchmark questions: the mechanically derived strata')
    A('')
    A('Generated by `bench/tools/make_questions.py`, seed **%d**. Do not hand edit. Change the '
      'generator and re-run, or the set stops being reproducible.' % a.seed)
    A('')
    covered = ', '.join('**%s**' % g for g in sorted(by_group))
    A('Covers groups %s, from the projects named in the config. These are the strata whose keys '
      'bench/METHOD.md says we can derive rather than hand author. Groups D, G and I stay '
      'hand written.' % covered)
    A('')
    if 'H' in by_group:
        A('**Group H comes from the engine tree, not from the benchmark projects.** There is not one '
      '`UE_DEPRECATED` across three projects combined, so a deprecation stratum drawn from '
      'them would have been empty. `Runtime/Engine` and `CoreUObject` public headers hold 1,742. '
      'Same finding as group C on a project where only two classes replicated anything, and the '
      'same fix: take each stratum from wherever it is actually populated.')
    A('')
    A('Every key here comes from the reflection artefacts, never from clangd, because clangd is one '
      'of the things being measured. Group C carries a **25 percent** hand check rather than 10, '
      'because in Phase 4 the reflection walk is itself the tool under test. Every group F key is '
      'hand checked **without exception**: an incorrect "no" is the worst error this file can hold.')
    A('')
    A('## Counts')
    A('')
    A('| Group | n | Project | n | Area | n |')
    A('|---|---|---|---|---|---|')
    g, p, ar = sorted(by_group.items()), sorted(by_proj.items()), sorted(by_area.items())
    for i in range(max(len(g), len(p), len(ar))):
        row  = [g[i][0], str(g[i][1])] if i < len(g) else ['', '']
        row += [p[i][0], str(p[i][1])] if i < len(p) else ['', '']
        row += [ar[i][0], str(ar[i][1])] if i < len(ar) else ['', '']
        A('| ' + ' | '.join(row) + ' |')
    A('')
    A('Total **%d**.' % len(out.qs))
    A('')
    if short:
        A('### Shortfalls')
        A('')
        A('A stratum that came up short is a finding, not a bug. It means the population is not '
          'there in these three projects and the questions have to come from the engine tier.')
        A('')
        A('| Stratum | Wanted | Got |')
        A('|---|---|---|')
        for lbl, want, got in short: A('| %s | %d | %d |' % (lbl, want, got))
        A('')
    A('## How to run')
    A('')
    A('One question per fresh session, see bench/METHOD.md. Run them in sequence and '
      'the later ones inherit context, at which point the token numbers stop meaning anything.')
    A('')
    A('| Scoring mode | Scored how |')
    A('|---|---|')
    A('| `exact` | String or value match against the key |')
    A('| `set` | Recall and precision reported **separately**, never collapsed into one number |')
    A('| `empty_set` | Pass needs the empty set **and** evidence the agent checked, not a guess |')
    A('| `prose` | Judgement |')
    A('')
    for grp in sorted(by_group):
        A('## Group %s' % grp)
        A('')
        A('| # | Project | Area | Shape | Question | Answer key | Route | Score |')
        A('|---|---|---|---|---|---|---|---|')
        for q in out.qs:
            if q['group'] != grp: continue
            A('| %s | %s | %s | %s | %s | %s | %s | `%s`%s |' % (
                q['id'], q['project'], q['area'], q['shape'],
                q['question'].replace('|', '\\|'),
                q['key'].replace('|', '\\|'),
                q['route'].replace('|', '\\|'),
                q['scoring'], ' + hand' if q.get('handcheck') else ''))
        A('')
    md = os.path.join(a.root, a.out)
    body = '\n'.join(L) + '\n'
    d = os.path.dirname(md)
    if d: os.makedirs(d, exist_ok=True)
    with open(md, 'w', encoding='utf-8') as f: f.write(body)
    js = md.rsplit('.', 1)[0] + '.json'
    with open(js, 'w', encoding='utf-8') as f:
        json.dump(dict(seed=a.seed, generated_by='make_questions.py', questions=out.qs), f, indent=1)
    print('wrote %s and %s' % (md, js))
    print('  total %d' % len(out.qs))
    for k, v in sorted(by_group.items()): print('  group %-2s %3d' % (k, v))
    for k, v in sorted(by_proj.items()):  print('  proj  %-10s %3d' % (k, v))
    for lbl, want, got in short:          print('  SHORT %-14s wanted %d got %d' % (lbl, want, got))

if __name__ == '__main__':
    main()
