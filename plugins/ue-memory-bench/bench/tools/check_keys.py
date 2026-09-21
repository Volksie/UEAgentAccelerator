#!/usr/bin/env python3
"""
Check the generated answer keys against the C++ source, independently of the artefacts
they were derived from.

Section 4 of the benchmark spec says never to use the tool under test as the source of its own
answer key. make_questions.py derives keys from Docs/AgentMemory, which is exactly the thing
Phase 4 measures, so this reads the headers and .cpp files instead and compares.

What it checks, and how:

  C  replication      parse DOREPLIFETIME* out of GetLifetimeReplicatedProps in the .cpp and
                      compare the property set and the COND_ against the key
  F  no replication   assert the class has no DOREPLIFETIME* and no Replicated specifier
  F  no UFUNCTION     assert the class body declares no UFUNCTION
  A  definition site  assert the header declares `class <Class> : public <Parent>`
  B  inheritance      assert the first link of the chain matches the header

Anything it cannot locate is reported as SKIP rather than PASS. A key this script cannot reach
is a key that still needs a person.

Usage:
  python check_keys.py --root . --questions bench/questions-160.json [--all]
"""
import argparse, collections, json, os, random, re, sys

# Filled from bench/projects.json at startup, so this agrees with the generator about where each
# project lives rather than carrying its own copy of the map.
PROJECT_DIRS = {}

def load_project_dirs(path):
    try:
        with open(path, encoding='utf-8') as f:
            cfg = json.load(f)
    except OSError as exc:
        sys.exit('cannot read config %s: %s' % (path, exc))
    return {p['key']: p['dir'] for p in cfg.get('projects', [])}
PREFIXES = ('U', 'A', 'I', 'F', 'S', '')

def read(p):
    try:
        with open(p, encoding='utf-8', errors='replace') as f: return f.read()
    except OSError: return ''

def source_files(root):
    out = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs
                   if d not in ('Binaries', 'Intermediate', 'Saved', 'DerivedDataCache',
                                '.git', 'Content', 'Docs')]
        for f in files:
            if f.endswith(('.h', '.cpp')): out.append(os.path.join(base, f))
    return out

class Source:
    """Every header and .cpp in one project, indexed by the class each declares."""
    def __init__(self, root, proj):
        self.files = source_files(os.path.join(root, PROJECT_DIRS[proj]))
        self.headers = {}   # bare class name -> (path, prefixed name)
        # Require either a base list or an opening brace, so `class UFoo;` forward
        # declarations don't get recorded as real declarations with no parent.
        decl = re.compile(r'^\s*class\s+(?:\w+_API\s+)?([UAIFS]\w+)\s*'
                          r'(?::\s*public\s+([\w:<>, ]+)|\s*\{)', re.M)
        self.parents = {}
        self.reflected = set()
        for p in self.files:
            if not p.endswith('.h'): continue
            txt = read(p)
            for m in decl.finditer(txt):
                full = m.group(1)
                bare = full[1:] if full[0] in 'UAIFS' and len(full) > 1 and full[1].isupper() else full
                if bare not in self.headers:
                    self.headers[bare] = (p, full)
                    # Only reflected classes appear in index.md, so E has to compare like with
                    # like. A UCLASS/UINTERFACE macro sits immediately above the declaration.
                    before = txt[max(0, m.start() - 400):m.start()]
                    if re.search(r'\b(UCLASS|UINTERFACE)\s*\(', before):
                        self.reflected.add(bare)
                    if m.group(2):
                        par = m.group(2).strip().split(',')[0].strip()
                        par = re.sub(r'<.*', '', par).strip()
                        self.parents[bare] = par
        self.cpps = [p for p in self.files if p.endswith('.cpp')]

    def header_text(self, cls):
        e = self.headers.get(cls)
        return read(e[0]) if e else None

    def class_body(self, cls):
        """Text from the class declaration to the next top-level class, roughly."""
        e = self.headers.get(cls)
        if not e: return None
        txt = read(e[0])
        m = re.search(r'^\s*class\s+(?:\w+_API\s+)?%s\b' % re.escape(e[1]), txt, re.M)
        if not m: return None
        rest = txt[m.start():]
        nxt = re.search(r'\n(?:UCLASS|USTRUCT|UINTERFACE)\s*\(', rest[10:])
        return rest[:nxt.start() + 10] if nxt else rest

    @staticmethod
    def _macro_blocks(body, macro):
        """Yield (args, following declaration text) for each MACRO(...) in a class body.

        Scans balanced parens because UFUNCTION args nest, e.g. meta=(DisplayName="x")."""
        out = []
        for m in re.finditer(r'\b%s\s*\(' % macro, body):
            i, depth = m.end() - 1, 0
            while i < len(body):
                if body[i] == '(': depth += 1
                elif body[i] == ')':
                    depth -= 1
                    if depth == 0: break
                i += 1
            args = body[m.end():i]
            decl = body[i + 1:i + 400]
            out.append((args, decl))
        return out

    def ufunctions(self, cls):
        """name -> specifier list, from the UFUNCTION macros in the class body."""
        body = self.class_body(cls)
        if body is None: return None
        found = {}
        for args, decl in self._macro_blocks(body, 'UFUNCTION'):
            d = re.search(r'([A-Za-z_]\w*)\s*\(', re.sub(r'^[^;{]*?\bmeta\s*=.*?\)', '', decl))
            if not d: continue
            name = d.group(1)
            if name in ('if', 'for', 'while', 'return', 'switch'): continue
            flat = re.sub(r'meta\s*=\s*\([^)]*\)', '', args)
            specs = [s.strip() for s in flat.split(',') if s.strip()]
            # UHT makes a const BlueprintCallable function BlueprintPure automatically unless
            # BlueprintPure=false. The header never says so; the live reflection does. This is
            # the clearest case in the whole benchmark of the dump beating a header read.
            # Look only at THIS declaration: from the arg list's closing paren to the first
            # ; or {. Scanning further picks up the const on the next function along.
            j, depth = d.end() - 1, 0
            while j < len(decl):
                if decl[j] == '(': depth += 1
                elif decl[j] == ')':
                    depth -= 1
                    if depth == 0: break
                j += 1
            stop = min([x for x in (decl.find(';', j), decl.find('{', j)) if x != -1] or [j + 40])
            is_const = re.search(r'\bconst\b', decl[j:stop])
            if 'BlueprintCallable' in specs and is_const and \
               not any('BlueprintPure' in s and 'false' in s.lower() for s in specs):
                if 'BlueprintPure' not in specs: specs.append('BlueprintPure')
            found[name] = specs
        return found

    def uproperties(self, cls):
        """name -> (type, specifier list), from the UPROPERTY macros in the class body."""
        body = self.class_body(cls)
        if body is None: return None
        found = {}
        for args, decl in self._macro_blocks(body, 'UPROPERTY'):
            d = re.search(r'^\s*((?:[\w:]+\s*(?:<[^;]*?>)?\s*[*&]?\s+)+?)([A-Za-z_]\w*)\s*(?:=|;|\{)',
                          decl, re.S)
            if not d: continue
            typ = ' '.join(d.group(1).split()).rstrip('*& ')
            flat = re.sub(r'meta\s*=\s*\([^)]*\)', '', args)
            specs = [s.strip() for s in flat.split(',') if s.strip()]
            found[d.group(2)] = (typ, specs)
        return found

    def ancestors(self, cls):
        seen, cur = [], cls
        while cur in self.parents and len(seen) < 20:
            par = self.parents[cur]
            bare = par[1:] if par and par[0] in 'UAIFS' and len(par) > 1 and par[1].isupper() else par
            seen.append(bare); cur = bare
        return seen

    def lifetime_props(self, cls):
        """(props dict name->COND_, found) parsed from GetLifetimeReplicatedProps."""
        e = self.headers.get(cls)
        full = e[1] if e else None
        found, props = False, {}
        pat = re.compile(r'DOREPLIFETIME(?:_CONDITION|_WITH_PARAMS|_CONDITION_NOTIFY|'
                         r'_WITH_PARAMS_FAST|_ACTIVE_OVERRIDE)?(?:_FAST)?\s*\(\s*'
                         r'(\w+)\s*,\s*(\w+)\s*(?:,\s*(COND_\w+))?')
        for p in self.cpps:
            txt = read(p)
            if not full or ('%s::GetLifetimeReplicatedProps' % full) not in txt: continue
            i = txt.index('%s::GetLifetimeReplicatedProps' % full)
            block = txt[i:i + 6000]
            found = True
            for m in pat.finditer(block):
                props[m.group(2)] = m.group(3) or 'COND_None'
        return props, found

def check(q, src):
    """-> (verdict, detail). verdict in PASS / FAIL / SKIP."""
    shape, key = q['shape'], q['key']
    # The first backticked token is often a macro name ("Which `UFUNCTION`s on `X`..."),
    # so skip the vocabulary before taking the first real class name.
    NOISE = {'UFUNCTION', 'UPROPERTY', 'UCLASS', 'USTRUCT', 'UINTERFACE', 'UObject',
             'BlueprintCallable', 'BlueprintPure', 'Replicated', 'Server', 'Client',
             'NetMulticast', 'Reliable'}
    cls = None
    for tok in re.findall(r'`([A-Za-z_]\w*)(?:::\w+)?`', q['question']):
        if tok in NOISE or tok.startswith('COND_'): continue
        cls = tok; break
    if not cls or cls not in src.headers:
        return 'SKIP', 'class %s not found in headers' % cls

    if shape == 'replication condition':
        props, found = src.lifetime_props(cls)
        if not found: return 'SKIP', 'no GetLifetimeReplicatedProps body located'
        want = set(q.get('keyset') or [])
        got = set(props)
        if want != got:
            return 'FAIL', 'key says %s, source says %s' % (sorted(want), sorted(got))
        for name in sorted(want):
            if props[name] not in key:
                return 'FAIL', '%s is %s in source, not in key' % (name, props[name])
        return 'PASS', '%d props, conditions match' % len(want)

    if shape == 'no replication':
        props, _ = src.lifetime_props(cls)
        body = src.class_body(cls) or ''
        spec = re.findall(r'UPROPERTY\s*\(([^)]*)\)', body)
        rep = [s for s in spec if 'Replicated' in s]
        if props: return 'FAIL', 'source replicates %s' % sorted(props)
        if rep:   return 'FAIL', 'header has Replicated specifier: %s' % rep[:2]
        return 'PASS', 'no DOREPLIFETIME and no Replicated specifier'

    if shape == 'no UFUNCTION':
        body = src.class_body(cls)
        if body is None: return 'SKIP', 'class body not located'
        n = len(re.findall(r'\bUFUNCTION\s*\(', body))
        if n: return 'FAIL', 'class body declares %d UFUNCTION' % n
        return 'PASS', 'no UFUNCTION in class body'

    if shape in ('specifier set', 'BlueprintPure set', 'network function'):
        fns = src.ufunctions(cls)
        if fns is None: return 'SKIP', 'class body not located'
        if not fns: return 'SKIP', 'no UFUNCTION parsed from header, likely a macro-heavy body'
        if shape == 'specifier set':   want_spec = lambda s: 'BlueprintCallable' in s
        elif shape == 'BlueprintPure set': want_spec = lambda s: 'BlueprintPure' in s
        else: want_spec = lambda s: any(x in s for x in ('Server', 'Client', 'NetMulticast'))
        got = {n for n, s in fns.items() if want_spec(s)}
        want = set(q.get('keyset') or [])
        if want != got:
            return 'FAIL', 'key says %s, header says %s' % (sorted(want), sorted(got))
        if shape == 'network function':
            for n in sorted(want):
                if 'Reliable' in fns[n] and 'Reliable' not in key:
                    return 'FAIL', '%s is Reliable in the header, key omits it' % n
        return 'PASS', '%d functions, specifiers match' % len(want)

    if shape == 'property type':
        pm = re.search(r'`\w+::(\w+)`', q['question'])
        props = src.uproperties(cls)
        if not pm or props is None: return 'SKIP', 'property or class body not located'
        name = pm.group(1)
        if name not in props: return 'SKIP', 'UPROPERTY %s not parsed from header' % name
        typ = props[name][0]
        kk = key.replace(' ', '').replace('`', '')
        tt = typ.replace(' ', '')
        if tt in kk: return 'PASS', 'type %s matches' % typ
        base = tt.split('<')[0]
        if base == kk:
            return 'TRUNC', ('dump gives %r, header gives %r. The artefact loses the template '
                             'arguments' % (key.strip('`'), typ))
        return 'FAIL', 'header type is %r, key says %r' % (typ, key)

    if shape == 'direct subclasses':
        pm = re.search(r'from `(\w+)`', q['question'])
        if not pm: return 'SKIP', 'parent not parsed from question'
        parent = pm.group(1)
        got = {c for c in src.reflected if src.parents.get(c, '') in (parent, 'U'+parent,
                                                                     'A'+parent, 'I'+parent,
                                                                     'F'+parent, 'S'+parent)}
        want = set(q.get('keyset') or [])
        if not got: return 'SKIP', 'no reflected children of %s parsed from headers' % parent
        missing_from_key = got - want
        if missing_from_key:
            return 'FAIL', 'headers have %s which the key omits' % sorted(missing_from_key)[:5]
        if want - got:
            # A regex over headers will never see every declaration. Only the direction that
            # matters is a hard failure; this direction is my parser, not the key.
            return 'PART', 'key superset by %d; regex missed %s' % (
                len(want - got), sorted(want - got)[:3])
        return 'PASS', '%d subclasses match' % len(want)

    if shape == 'common ancestor':
        names = re.findall(r'`(\w+)`', q['question'])
        if len(names) < 2: return 'SKIP', 'could not read both class names'
        a, b = names[0], names[1]
        ca, cb = src.ancestors(a), set(src.ancestors(b))
        nearest = next((x for x in ca if x in cb), None)
        if not nearest: return 'SKIP', 'no common ancestor reachable from headers alone'
        if nearest in key: return 'PASS', 'nearest common ancestor %s matches' % nearest
        return 'FAIL', 'headers give %s, key says %r' % (nearest, key)

    if shape == 'declared where':
        nm = re.search(r'^Is `(\w+)`', q['question'])
        fns = src.ufunctions(cls)
        if not nm or fns is None: return 'SKIP', 'class body not located'
        if nm.group(1) in fns:
            return 'FAIL', '%s IS declared on %s, key says inherited' % (nm.group(1), cls)
        return 'PASS', '%s absent from %s, consistent with inherited' % (nm.group(1), cls)

    if shape in ('blueprint blast radius', 'blueprint subclasses', 'no Blueprint caller'):
        return 'SKIP', ('no C++ route exists. Layer 2 is the only source, so verifying this key '
                        'needs a second graph walk or a person in the editor')

    if shape in ('definition site', 'inheritance chain'):
        par = src.parents.get(cls)
        if not par: return 'SKIP', 'no parent parsed from header'
        bare = par[1:] if par and par[0] in 'UAIFS' and len(par) > 1 and par[1].isupper() else par
        if bare in key or par in key:
            return 'PASS', 'parent %s matches' % par
        return 'FAIL', 'header parent is %s, key says %r' % (par, key[:70])

    return 'SKIP', 'no independent check for shape %r' % shape

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='.')
    ap.add_argument('--questions', default='bench/questions.json')
    ap.add_argument('--config', default='bench/projects.json')
    ap.add_argument('--seed', type=int, default=7)
    ap.add_argument('--all', action='store_true', help='check every checkable question')
    a = ap.parse_args()

    PROJECT_DIRS.update(load_project_dirs(os.path.join(a.root, a.config)))

    qs = json.load(open(os.path.join(a.root, a.questions), encoding='utf-8'))['questions']
    rng = random.Random(a.seed)

    # Sampling rates from bench/METHOD.md.
    RATE = {'A': 0.10, 'B': 0.10, 'E': 0.10, 'C': 0.25, 'F': 1.00}
    chosen = []
    for grp, rate in RATE.items():
        pool = [q for q in qs if q['group'] == grp]
        n = len(pool) if a.all else max(1, round(len(pool) * rate))
        chosen += rng.sample(pool, min(n, len(pool)))

    srcs, results = {}, []
    for q in sorted(chosen, key=lambda x: x['id']):
        proj = q['project']
        if proj not in PROJECT_DIRS: 
            results.append((q, 'SKIP', 'project %s has no source tree here' % proj)); continue
        if proj not in srcs: srcs[proj] = Source(a.root, proj)
        v, d = check(q, srcs[proj])
        results.append((q, v, d))

    tally = collections.Counter(v for _, v, _ in results)
    print('checked %d questions: %s' % (len(results), dict(tally)))
    print()
    for q, v, d in results:
        if v in ('PASS', 'SKIP'): continue
        print('%-4s %s %-4s %-22s %s' % (v, q['id'], q['group'], q['shape'], d))
    print()
    for q, v, d in results:
        if v == 'PASS':
            print('PASS %s %-2s %-22s %s' % (q['id'], q['group'], q['shape'], d))
    return 1 if tally['FAIL'] else 0   # PART and TRUNC are findings, not failures

if __name__ == '__main__':
    sys.exit(main())
