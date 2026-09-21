# -*- coding: utf-8 -*-
r"""Fails the repository when a document points at a file that is not here.

This repository is mostly prose about files, and the prose is load-bearing: the routing table names
artefacts, the guides name scripts, the result documents name the tools that produced them. Every one of
those is a path a reader will try, and paths rot in three ways that have all happened here:

  * a file moves (`bench/` became `plugins/ue-memory-bench/bench/`) and the documents keep the old path
  * a document is copied in from the development tree, where the same file sits somewhere else
  * a document names something that was never published, because it is deliberately not published

The third is the interesting one, and it is why this checks rather than trusts. A sentence citing a file
the reader cannot open is worse than no sentence: it reads as an instruction and fails silently.

What is checked: markdown links, and backticked or italicised tokens, that look like a path INTO this
repository - more than one segment, ending in a source or document extension. Each is resolved against
the document's own directory, every ancestor up to the repository root, and - for
`${CLAUDE_PLUGIN_ROOT}/x` - the plugin the document lives in.

What is deliberately not checked, because these are not promises about this repository:

  * bare filenames. `CLAUDE.md` or `Target.cs` in prose names a KIND of file, and the reader's own tree
    is where it lives. Requiring a directory separator is what keeps this gate honest rather than loud.
  * paths into the reader's tree or another package: `.claude/settings.json`, `Docs/AgentMemory/...`,
    `Engine/...`, CPython's `Lib/...`. They are correct and they are elsewhere.
  * anything with a placeholder in it (`<Class>`, `*.json`, `%s`), which names a shape rather than a file.

A gate that fires on things nobody can fix gets switched off, so the scope is narrow on purpose: a path
with a directory in it, pointing at this repository, that does not resolve.

Usage:  python tools/check_doc_paths.py
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Generated, vendored or recorded output. Documents inside these describe another tree by design.
SKIP_DIRS = {'.git', 'seed', 'examples', 'node_modules', 'results', '__pycache__',
             'Binaries', 'Intermediate', 'Saved', 'DerivedDataCache'}

EXTS = ('.md', '.py', '.ps1', '.json', '.cpp', '.h', '.cs', '.yml', '.yaml', '.txt',
        '.uplugin', '.uproject', '.sh', '.diff', '.ini', '.bat')

LINK = re.compile(r'\[[^\]]*\]\(([^)\s]+)\)')
CODE = re.compile(r'`([^`\n]+)`')
ITALIC = re.compile(r'(?<![\w*])\*([^*\n]+)\*(?![\w*])')

PLACEHOLDER = re.compile(r'[<>*{}%]|\.\.\.|\$\{(?!CLAUDE_PLUGIN_ROOT\})')

# Path roots that belong to the reader's tree, to the engine, or to another package. Correct, and not
# ours to resolve.
ELSEWHERE = ('.claude/', '.serena/', 'lib/', 'engine/', 'docs/agentmemory/', 'docs/design/',
             'source/', 'config/', 'content/', 'binaries/', 'intermediate/', 'saved/',
             'plugins/ueagentacceleratoruht/', 'runs/',
             'system.', 'microsoft.', 'newtonsoft.',
             # Paths inside Serena's own package, named when describing where a fix lives. Listed one
             # by one rather than skipping everything under `serena/`, because THIS repository has a
             # serena/ directory too and its own files must stay checked.
             'serena/tools/', 'serena/agent', 'serena/util/', 'serena/cli.py', 'serena/repl/',
             'serena/ls_manager.py', 'serena/resources/', 'solidlsp/')


def candidates(doc, token):
    """Every place a reader could reasonably resolve this token from."""
    t = token.strip().strip('"\'').replace('\\', '/').split('#')[0].rstrip('.,;:')
    if not t or t.startswith(('http://', 'https://', 'mailto:', '#', '~', '/')):
        return []
    if PLACEHOLDER.search(t):
        return []
    if not t.lower().endswith(EXTS):
        return []
    if re.match(r'^[A-Za-z]:', t):                      # an absolute path in an example
        return []
    # One segment is a filename, not a path into this repository. See the header.
    if '/' not in t.rstrip('/'):
        return []
    if t.lower().startswith(ELSEWHERE):
        return []
    # A generated artefact, named with its project: `LyraStarterGame/Docs/AgentMemory/...`. Those live
    # in the tree that generated them, and this repository publishes a seed set under another name.
    if '/docs/agentmemory/' in t.lower() or '/docs/design/' in t.lower():
        return []
    here = os.path.dirname(doc)
    out = []
    if t.startswith('${CLAUDE_PLUGIN_ROOT}/'):
        rest = t[len('${CLAUDE_PLUGIN_ROOT}/'):]
        # The plugin root is the ancestor directory holding .claude-plugin/plugin.json.
        probe = here
        while probe.startswith(ROOT):
            if os.path.isfile(os.path.join(probe, '.claude-plugin', 'plugin.json')):
                out.append(os.path.join(probe, rest))
                break
            parent = os.path.dirname(probe)
            if parent == probe:
                break
            probe = parent
        return out
    # The document's own directory, then every ancestor up to the repository root: a guide under
    # docs/ naming `hooks/hooks.json` means its plugin's hooks directory, and that is a fair way to
    # write it.
    probe = here
    while True:
        out.append(os.path.join(probe, t))
        if os.path.normcase(probe) == os.path.normcase(ROOT) or not probe.startswith(ROOT):
            break
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    return out


def main():
    problems, docs, checked = [], 0, 0
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if not fn.lower().endswith('.md'):
                continue
            doc = os.path.join(dirpath, fn)
            docs += 1
            text = io.open(doc, encoding='utf-8', errors='replace').read()
            tokens = [(m.group(1), 'link') for m in LINK.finditer(text)]
            tokens += [(m.group(1), 'code') for m in CODE.finditer(text)]
            tokens += [(m.group(1), 'italic') for m in ITALIC.finditer(text)]
            for token, kind in tokens:
                cands = candidates(doc, token)
                if not cands:
                    continue
                checked += 1
                if not any(os.path.exists(c) for c in cands):
                    problems.append((os.path.relpath(doc, ROOT), kind, token.strip()))

    for doc, kind, token in problems:
        print('  UNRESOLVED %-56s %s (%s)' % (doc, token, kind))
    print('%d document(s), %d path reference(s) checked, %d unresolved'
          % (docs, checked, len(problems)))
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
