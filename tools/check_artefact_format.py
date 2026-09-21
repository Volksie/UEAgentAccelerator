# -*- coding: utf-8 -*-
r"""Keeps the artefact format number in one piece across the three places it has to agree.

The commandlet owns it, as a C++ constant. The PowerShell health check cannot read a C++ constant, so
`plugins/ue-memory-stack/artefact-format.json` mirrors it. Two copies of a number drift, and this one
drifting is worse than most: the health check would compare artefacts against the wrong expectation and
report a clean bill or a false alarm, which is precisely the failure the stamp exists to end.

So this fails the repository when:

  * the C++ constant and the JSON disagree
  * the commandlet does not actually write the row the health check parses
  * the health check does not actually read the file that declares the expectation

Usage:  python tools/check_artefact_format.py
"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CPP = os.path.join(ROOT, 'plugins', 'ue-memory-stack', 'ue-plugin', 'UEAgentAccelerator', 'Source',
                   'UEAgentAcceleratorTools', 'Private', 'AgentMemoryDumpCommandlet.cpp')
JSON_PATH = os.path.join(ROOT, 'plugins', 'ue-memory-stack', 'artefact-format.json')
DOCTOR = os.path.join(ROOT, 'plugins', 'ue-memory-stack', 'scripts', 'Test-MemoryStackHealth.ps1')

problems = []


def read(path):
    return io.open(path, encoding='utf-8', errors='replace', newline='').read()


def main():
    cpp = read(CPP)

    m = re.search(r'constexpr\s+int32\s+kArtefactFormatVersion\s*=\s*(\d+)\s*;', cpp)
    if not m:
        problems.append('no kArtefactFormatVersion constant in AgentMemoryDumpCommandlet.cpp')
        cpp_version = None
    else:
        cpp_version = int(m.group(1))

    # The row the health check parses. If the commandlet stops writing it, every artefact set silently
    # becomes "written before the stamp existed" and nothing reports the change.
    if 'TEXT("| Artefact format | %d |")' not in cpp:
        problems.append('the commandlet does not write the "| Artefact format |" row that the health check reads')
    if 'TEXT("| Written by plugin | %s |")' not in cpp:
        problems.append('the commandlet does not write the "| Written by plugin |" row')

    try:
        declared = json.loads(read(JSON_PATH))
    except Exception as e:                                    # noqa: BLE001 - report, do not raise
        problems.append('artefact-format.json does not parse: %s' % e)
        declared = None

    if declared is not None and cpp_version is not None:
        if declared.get('artefactFormat') != cpp_version:
            problems.append('the commandlet writes format %d and artefact-format.json declares %r - '
                            'the health check would compare artefacts against the wrong expectation'
                            % (cpp_version, declared.get('artefactFormat')))
        hist = declared.get('history') or []
        if not any(h.get('format') == cpp_version for h in hist):
            problems.append('format %d has no entry in artefact-format.json history, so nothing records '
                            'what changed or which plugin version introduced it' % cpp_version)

    doctor = read(DOCTOR)
    if 'artefact-format.json' not in doctor:
        problems.append('the health check does not read artefact-format.json, so the stamp is not compared '
                        'to anything')
    if 'Artefact format' not in doctor:
        problems.append('the health check does not look for the "Artefact format" row in MANIFEST.md')

    for p in problems:
        print('  PROBLEM %s' % p)
    if not problems:
        print('artefact format %d: the commandlet, artefact-format.json and the health check agree.' % cpp_version)
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
