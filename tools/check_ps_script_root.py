# -*- coding: utf-8 -*-
r"""Fails the repository when a shipped PowerShell script derives a path in a parameter default.

`$PSScriptRoot` is empty on Windows PowerShell 5.1 while parameter defaults are evaluated. A default of
`(Join-Path $PSScriptRoot '..')` therefore kills the script before its first line, with an error that
names Join-Path and says nothing about 5.1:

    Join-Path : Cannot bind argument to parameter 'Path' because it is an empty string.

It works perfectly under PowerShell 7, which is why this keeps shipping. Four scripts here have had it -
the Serena installer, the config loader, the two-tree sync, and the build script, which had never been
run on 5.1 at all until somebody tried. Four occurrences is a missing check rather than bad luck.

The fix is always the same shape: take the parameter with no default, and fill it in the body.

    [string] $PluginSource,          # not  = (Join-Path $PSScriptRoot '..')
    ...
    if (-not $PluginSource) {
        $here = $PSScriptRoot
        if (-not $here) { $here = Split-Path -Parent $MyInvocation.MyCommand.Path }
        $PluginSource = Join-Path $here '..'
    }

Usage:  python tools/check_ps_script_root.py
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEARCH = [os.path.join('plugins', 'ue-memory-stack', 'scripts'),
          os.path.join('plugins', 'ue-memory-stack', 'serena'),
          os.path.join('plugins', 'ue-memory-stack', 'templates'),
          os.path.join('plugins', 'ue-memory-stack', 'hooks'),
          os.path.join('plugins', 'ue-memory-bench', 'bench', 'tools'),
          'tools']


def param_block(text):
    """The span of the first param(...) block, matched by brackets rather than by a regex, because a
    parameter default can contain parentheses of its own."""
    m = re.search(r'^\s*param\s*\(', text, re.M)
    if not m:
        return None
    depth = 0
    for i in range(m.end() - 1, len(text)):
        c = text[i]
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                return text[m.start():i + 1]
    return None


def main():
    problems = []
    checked = 0
    for rel in SEARCH:
        d = os.path.join(ROOT, rel)
        if not os.path.isdir(d):
            continue
        for dirpath, dirnames, filenames in os.walk(d):
            for f in filenames:
                if not f.endswith('.ps1'):
                    continue
                path = os.path.join(dirpath, f)
                text = io.open(path, encoding='utf-8', errors='replace', newline='').read()
                checked += 1
                block = param_block(text)
                if not block:
                    continue
                # Comments inside the block are allowed to mention it - they are usually explaining
                # exactly this - so only code lines count.
                for line in block.split('\n'):
                    code = line.split('#', 1)[0]
                    if '$PSScriptRoot' in code:
                        problems.append('%s: %s' % (os.path.relpath(path, ROOT).replace('\\', '/'),
                                                    line.strip()))
                        break

    for p in problems:
        print('  PROBLEM %s' % p)
    print('%d shipped script(s) checked, %d with $PSScriptRoot in a parameter default' % (checked, len(problems)))
    if problems:
        print('  Take the parameter with no default and fill it in the body; see this file for the shape.')
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
