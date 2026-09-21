# -*- coding: utf-8 -*-
r"""Checks an eval suite without running it.

`claude plugin eval` costs model budget and, on some builds, refuses to run at all ("currently in early
access"). Neither is a reason to leave a suite unchecked until the first paid run: a grader with a
misspelled type, a case with no graders, a scaffold script that does not parse, or an `input_match`
naming a path the scaffold never creates are all mistakes that a run would find slowly and expensively.

What it checks:

  * every case has a prompt (prompt.md or case.yaml) and at least one grader
  * frontmatter parses, and its keys are ones the documented contract defines
  * every grader's type is one of the six documented types, with that type's required fields
  * regex patterns compile, and a `tool_used` pattern's literal parts appear in the case's scaffold,
    which is what catches a path that drifted after the fixture changed
  * scaffold scripts exist and pass `bash -n`

It does not check semantics: whether a grader actually passes on a good answer is what a run is for.

Usage:  python tools/check_evals.py [eval-dir ...]
        defaults to plugins/*/evals
"""
import io
import os
import re
import subprocess
import sys
import glob

GRADER_TYPES = {
    'regex':       {'required': ['pattern'], 'optional': ['flags', 'match', 'target', 'weight', 'arm', 'scored']},
    'tool_used':   {'required': ['tool'], 'optional': ['input_match', 'min', 'max', 'weight', 'arm', 'scored']},
    'tool_order':  {'required': ['before', 'after'], 'optional': ['weight', 'arm', 'scored']},
    'file_exists': {'required': ['path'], 'optional': ['exists', 'weight', 'arm', 'scored']},
    'llm':         {'required': [], 'optional': ['criteria', 'focus', 'weight', 'arm', 'scored']},
    'baseline':    {'required': ['baseline_file'], 'optional': ['criteria', 'focus', 'weight', 'arm', 'scored']},
}

# The runner's own list, quoted back by it when a key is wrong. Note what is NOT here:
# scaffold_script, which belongs under execution: in a case.yaml. The documentation described a flatter
# shape, and four cases were written to it before the loader said otherwise.
PROMPT_KEYS = {'schema_version', 'name', 'description', 'tags', 'plugins', 'runs', 'expected_outcome',
               'model', 'max_turns', 'timeout_seconds', 'allowed_tools', 'artifact_publish',
               'growthbook_overrides', 'append_system_prompt', 'env'}

# case.yaml is nested, and schema_version has to be a string ("1.0"), not a number.
CASE_TOP_KEYS = PROMPT_KEYS | {'execution', 'context', 'graders'}
CASE_EXECUTION_KEYS = {'prompt', 'max_turns', 'timeout_seconds', 'allowed_tools',
                       'model', 'append_system_prompt', 'env', 'artifact_publish'}
# Fixtures live here, and only here. scaffold_script under execution: or at the top level is accepted by
# the loader and never runs - two paid runs went to an empty workspace before that was clear, and the
# score was not zero, because negative graders pass on an answer that says "I could not find anything".
CASE_CONTEXT_KEYS = {'scaffold_script', 'add_dirs', 'history_file'}

MATCH_VALUES = {'contains', 'not_contains'}
TARGETS = {'last_message', 'trace', 'files', 'mock_calls'}

problems = []
notes = []


def fail(where, what):
    problems.append('%s: %s' % (where, what))


def read_frontmatter(path):
    """The documented shape is YAML frontmatter between --- lines. Only the subset used here is parsed:
    scalars, and [a, b] inline lists. A nested structure would need a real YAML parser, and a suite that
    needs one has outgrown this check."""
    text = io.open(path, encoding='utf-8', newline='').read().replace('\r\n', '\n')
    if not text.startswith('---'):
        return None, text
    end = text.find('\n---', 3)
    if end < 0:
        return None, text
    block = text[3:end].strip('\n')
    body = text[end + 4:]
    data = {}
    for line in block.split('\n'):
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        if ':' not in line:
            data['__malformed__'] = line.strip()
            continue
        k, v = line.split(':', 1)
        k, v = k.strip(), v.strip()
        if v.startswith('[') and v.endswith(']'):
            data[k] = [x.strip().strip('\'"') for x in v[1:-1].split(',') if x.strip()]
        else:
            data[k] = v.strip('\'"')
    return data, body


def literals(pattern):
    """Alphanumeric runs a path typo would break, so a changed fixture is caught by the check rather
    than by a paid run scoring zero for a reason nobody reads."""
    return [w for w in re.findall(r'[A-Za-z][A-Za-z0-9_]{3,}', pattern)
            if w not in ('Docs', 'AgentMemory', 'skill', 'md')]


def check_case(case_dir, eval_dir):
    rel = os.path.relpath(case_dir, eval_dir).replace('\\', '/')
    prompt = os.path.join(case_dir, 'prompt.md')
    caseyaml = os.path.join(case_dir, 'case.yaml')
    if not os.path.exists(prompt) and not os.path.exists(caseyaml):
        fail(rel, 'no prompt.md and no case.yaml, so the runner will not see a case here')
        return

    scaffold_text = ''

    if os.path.exists(caseyaml):
        # Not a YAML parser: the shape here is two levels deep and this only has to catch the mistakes
        # that stop a case loading, which the runner reports one at a time and slowly.
        text = io.open(caseyaml, encoding='utf-8', newline='').read().replace('\r\n', '\n')
        top = {}
        section = None
        for line in text.split('\n'):
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            indent = len(line) - len(line.lstrip())
            if indent == 0 and ':' in line:
                k = line.split(':', 1)[0].strip()
                top[k] = line.split(':', 1)[1].strip()
                section = k
            elif indent > 0 and section in ('execution', 'context') and ':' in line and indent <= 2:
                k = line.split(':', 1)[0].strip()
                allowed = CASE_EXECUTION_KEYS if section == 'execution' else CASE_CONTEXT_KEYS
                if k not in allowed:
                    notes.append('%s/case.yaml: %s key %r is not one this checker knows' % (rel, section, k))
                if k == 'scaffold_script' and section != 'context':
                    fail(rel + '/case.yaml', 'scaffold_script is under %s:, where the loader accepts it and '
                                             'never runs it. It belongs under context:' % section)
                if k == 'scaffold_script':
                    sc = line.split(':', 1)[1].strip().strip('\'"')
                    sp = os.path.join(case_dir, sc)
                    if not os.path.exists(sp):
                        fail(rel, 'scaffold_script names %s, which is not there' % sc)
                    else:
                        scaffold_text = io.open(sp, encoding='utf-8', newline='').read()
                        try:
                            r = subprocess.run(['bash', '-n', sp], capture_output=True, text=True)
                            if r.returncode != 0:
                                fail(rel + '/' + sc, 'bash -n says: %s' % (r.stderr.strip().splitlines() or [''])[0])
                        except OSError:
                            notes.append('%s: bash not available, so %s was not syntax checked' % (rel, sc))
        if 'schema_version' not in top:
            fail(rel + '/case.yaml', 'missing required field schema_version')
        elif not (top['schema_version'].startswith('"') or top['schema_version'].startswith("'")):
            fail(rel + '/case.yaml', 'schema_version must be a string, as in schema_version: "1.0"')
        if 'execution' not in top:
            fail(rel + '/case.yaml', 'no execution block, so there is no prompt')
        if 'scaffold_script' in top:
            fail(rel + '/case.yaml', 'scaffold_script is at the top level, where the loader accepts it and '
                                     'never runs it. It belongs under context:')
        for k in top:
            if k not in CASE_TOP_KEYS:
                notes.append('%s/case.yaml: top-level key %r is not one this checker knows' % (rel, k))

    if os.path.exists(prompt):
        fm, body = read_frontmatter(prompt)
        if fm is None:
            fail(rel + '/prompt.md', 'no YAML frontmatter')
            fm = {}
        if '__malformed__' in fm:
            fail(rel + '/prompt.md', 'frontmatter line without a colon: %r' % fm['__malformed__'])
        if not body.strip():
            fail(rel + '/prompt.md', 'frontmatter but no prompt text after it')
        for k in fm:
            if k != '__malformed__' and k not in PROMPT_KEYS:
                notes.append('%s/prompt.md: frontmatter key %r is not one this checker knows; verify it against the docs' % (rel, k))
        sc = fm.get('scaffold_script')
        if sc:
            sp = os.path.join(case_dir, sc)
            if not os.path.exists(sp):
                fail(rel, 'scaffold_script names %s, which is not there' % sc)
            else:
                scaffold_text = io.open(sp, encoding='utf-8', newline='').read()
                try:
                    r = subprocess.run(['bash', '-n', sp], capture_output=True, text=True)
                    if r.returncode != 0:
                        fail(rel + '/' + sc, 'bash -n says: %s' % (r.stderr.strip().splitlines() or [''])[0])
                except OSError:
                    notes.append('%s: bash not available, so %s was not syntax checked' % (rel, sc))

    graders = sorted(glob.glob(os.path.join(case_dir, 'graders', '*.md')))
    if not graders:
        fail(rel, 'no graders, so a run here scores nothing and passes by default')
        return

    # Observed: a run where the fixture never appeared, and the agent said so and stopped, still scored
    # 0.33 - because a not_contains grader is satisfied by an answer that contains nothing. A case needs
    # at least one grader that can only pass on a real answer, or being completely broken scores points.
    positive = 0

    for g in graders:
        gname = rel + '/graders/' + os.path.basename(g)
        fm, body = read_frontmatter(g)
        if fm is None:
            fail(gname, 'no YAML frontmatter')
            continue
        t = fm.get('type')
        if not t:
            fail(gname, 'no type')
            continue
        if t not in GRADER_TYPES:
            fail(gname, 'type %r is not one of the documented types (%s)' % (t, ', '.join(sorted(GRADER_TYPES))))
            continue
        spec = GRADER_TYPES[t]
        for r in spec['required']:
            if r not in fm:
                fail(gname, 'type %s needs %s' % (t, r))
        for k in fm:
            if k in ('type', '__malformed__'):
                continue
            if k not in spec['required'] and k not in spec['optional']:
                notes.append('%s: field %r is not one this checker knows for type %s' % (gname, k, t))
        if t == 'llm' and not body.strip() and 'criteria' not in fm:
            fail(gname, 'an llm grader with neither criteria nor a rubric body has nothing to judge')
        negative = (fm.get('match') == 'not_contains') or (t == 'file_exists' and fm.get('exists') in ('false', False))
        if not negative and t in ('regex', 'tool_used', 'tool_order', 'file_exists', 'llm', 'baseline'):
            positive += 1

        if 'match' in fm and not (fm['match'] in MATCH_VALUES or fm['match'].startswith('count:')):
            fail(gname, 'match %r is not contains, not_contains or count:N' % fm['match'])
        if 'target' in fm and fm['target'] not in TARGETS and not fm['target'].startswith('{'):
            notes.append('%s: target %r is not one of %s' % (gname, fm['target'], ', '.join(sorted(TARGETS))))
        for key in ('pattern', 'input_match'):
            if key in fm:
                try:
                    re.compile(fm[key])
                except re.error as e:
                    fail(gname, '%s does not compile as a regex: %s' % (key, e))
        # A tool_used pattern naming a path the fixture never creates scores zero for ever.
        if t == 'tool_used' and 'input_match' in fm and scaffold_text:
            words = literals(fm['input_match'])
            if words and not any(w in scaffold_text for w in words):
                fail(gname, 'input_match names %s, none of which appears in the scaffold, so it cannot match' %
                     ', '.join(words))

    if positive == 0:
        fail(rel, 'every grader here is a negative one (not_contains, or exists: false). Those pass when '
                  'the agent answers nothing, so this case scores points for being completely broken. Add '
                  'a grader that can only pass on a real answer')


def main(argv):
    dirs = argv[1:] or sorted(glob.glob(os.path.join('plugins', '*', 'evals')))
    if not dirs:
        print('No eval directories found. Pass one, or run from the repository root.')
        return 1
    cases = 0
    for d in dirs:
        for name in sorted(os.listdir(d)):
            case_dir = os.path.join(d, name)
            if not os.path.isdir(case_dir) or name in ('results', 'mocks'):
                continue
            cases += 1
            check_case(case_dir, d)
        print('checked %s' % d.replace('\\', '/'))

    for n in notes:
        print('  note    %s' % n)
    for p in problems:
        print('  PROBLEM %s' % p)
    print('%d case(s), %d problem(s), %d note(s)' % (cases, len(problems), len(notes)))
    if not problems:
        print('Nothing here is proof the graders score correctly - only a run is. This checks the suite is'
              ' well formed.')
    return 1 if problems else 0


if __name__ == '__main__':
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.exit(main(sys.argv))
