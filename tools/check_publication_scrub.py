#!/usr/bin/env python3
"""Refuse to publish plugin source that still talks about the private tree it was written in.

The plugin source here is developed in a private tree alongside a benchmark, three sample projects
and a pile of design documents, then copied across. Comments written there can name things that mean
nothing to anyone reading this repository, and `tools/Sync-Shared.ps1` already records what the
publication step removes:

    review-task ids, a benchmark question id and a token figure from comments, and the
    walk-coverage note points at engine-api/ rather than tools/engine-api-db/

This file turns that sentence into a gate. Every rule below was derived from an actual difference
between the two copies of a synced file, not invented: each term appears zero times in this
repository today and does appear in the private tree's copy of the same source.

SCOPE IS DELIBERATELY NARROW. Only the surfaces copied from the private tree are scanned. The
benchmark harness is published here as its own plugin and legitimately talks about answer keys,
question ids and `bench/`; the docs legitimately mention the sample projects and the reader's own
CLAUDE.local.md. A first draft of this file banned those repo-wide and produced 432 hits on
unmodified published content, which is a gate measuring the wrong thing.

It is NOT the benchmark's isolation scan and shares no list with it. That one stops a baseline run
reading about the layers it is measured against; this one stops private vocabulary reaching a public
repository. A file can pass either and fail the other.

Like its sibling it is a vocabulary check, not a leak detector: it matches the terms below and
nothing else, so prose describing the private tree in other words goes straight through and a clean
run is not a clearance.

    python tools/check_publication_scrub.py          # exit 1 on a hit, with file:line
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

# Only what is copied from the private tree.
SCAN_DIRS = [
    "plugins/ue-memory-stack/ue-plugin",
    "plugins/ue-memory-stack/engine-api",
    "plugins/ue-memory-stack/scripts",
    # Added when the long-lived launcher shipped. That script was adapted from one that lived in a
    # user's home directory on the development machine and was full of that tree's paths, project
    # names and warm-up targets - exactly the vocabulary this gate exists to catch, in a directory it
    # was not looking at.
    "plugins/ue-memory-stack/serena",
]
SCAN_EXTS = {".py", ".cpp", ".h", ".cs", ".ps1", ".uplugin"}
SKIP_PARTS = {".git", "Binaries", "Intermediate", "Saved", "DerivedDataCache", "__pycache__"}

# (name, pattern, why it must not ship). Each verified absent from this repo before being added.
RULES: list[tuple[str, str, str]] = [
    ("review task id",
     r"\b(?:A\d{1,2}\s*[:/]|v\d item \d)",
     "an internal review task id; it indexes a document that is not published"),
    ("benchmark question id",
     r"\b[QDBFJK]\d{2,3}\b",
     "a benchmark question number; the question set is not shipped with the plugin"),
    ("private tree path",
     r"(?:tools/engine-api-db|tools/Update-MemoryStack|bench/benchmark-spec|bench/tools|"
     r"DESIGN-[a-z-]+\.md|SESSION-HANDOVER|CLAUDE\.local\.md)",
     "a path that exists only in the private tree; point at this repo's layout instead"),
    ("token accounting",
     r"\b\d+(?:\.\d+)?\s*M[- ]token\b",
     "a cost figure from private measurement work"),
    # No "group <letter>" rule here on purpose: it was in the first draft to catch a session's
    # working name for a question group, and it fired on "group F of the benchmark", which is
    # published vocabulary this repo's own bench plugin documents. A rule that hits legitimate
    # content is the repo-wide mistake in miniature, so this matches named sessions only.
    ("session reference",
     r"(?i)\b(?:the harness session|the review session|the store's owner|peer session|"
     r"a concurrent session|the other session)",
     "refers to a concurrent session in the private tree"),
]

COMPILED = [(name, re.compile(pat), why) for name, pat, why in RULES]

# Console platform names, checked across the WHOLE repository rather than the synced source alone,
# because a doc or a generated artefact can name one as easily as a comment can. Nothing here may
# name a console: the code finds them at run time from the engine's confidential-platform list, and
# the prose says "console". Added 2026-09-21 at the maintainer's request, over NDA concerns.
#
# The names are stored as HASHES, so this file doesn't name them either. Every word on a line, and
# every pair of adjacent words, is lowercased and hashed, and a hit is a hash in this set. To add a
# name, append the first 16 hex digits of its SHA-256:
#
#     python -c "import hashlib; print(hashlib.sha256(b'the name').hexdigest()[:16])"
CONSOLE_HASHES = frozenset({
    '2957507e9c300d13', 'd2882518d60c0133', 'b32b516e09a3952a', '75a55e55aa2ded34',
    '06c1f52592fb04ce', '5a44f2737b143ee7', 'ca107bff7ec39d9e', 'f711da60664c04c1',
    '501d5acb4acc06d8', '587d392b6c7680ec', 'c0a4942143e872cd', 'd12db999260ad007',
    'ffe01f7edf8ff32a', '26009102c028e696', 'cb6aa95984762303', 'dea7cd279319a43d',
    '7a69139dbcf7d411', 'b4157e53eb24dbd5',
})
_WORD = re.compile(r"[A-Za-z0-9]+")


def console_hit(line: str) -> str | None:
    """The first word, or pair of words, on this line whose hash is a console name."""
    import hashlib
    words = [w.lower() for w in _WORD.findall(line)]
    for gram in words + [a + " " + c for a, c in zip(words, words[1:])]:
        if hashlib.sha256(gram.encode()).hexdigest()[:16] in CONSOLE_HASHES:
            return gram
    return None


CONSOLE_EXTS = {".md", ".py", ".cpp", ".h", ".cs", ".ps1", ".json", ".uplugin", ".ini", ".txt", ".html", ".svg"}
CONSOLE_SKIP: set[str] = set()


def console_files():
    # What git would publish: tracked files plus new ones not ignored. A build output such as the
    # seed's compile_commands.json names every platform folder in the engine and is gitignored, so
    # walking the disk instead reports a leak that cannot happen.
    import subprocess
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                         cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True).stdout
    for rel in sorted(set(out.splitlines())):
        p = ROOT / rel
        if not p.is_file() or p.suffix.lower() not in CONSOLE_EXTS or (SKIP_PARTS & set(p.parts)):
            continue
        if rel in CONSOLE_SKIP:
            continue
        yield p


def files_to_scan():
    for d in SCAN_DIRS:
        base = ROOT / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file() and p.suffix in SCAN_EXTS and not (SKIP_PARTS & set(p.parts)):
                yield p


def main() -> int:
    hits: list[str] = []
    scanned = 0
    for path in files_to_scan():
        scanned += 1
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for name, rx, why in COMPILED:
                m = rx.search(line)
                if m:
                    rel = path.relative_to(ROOT).as_posix()
                    hits.append(f"  BAD  {rel}:{lineno}  [{name}] {m.group(0)!r}\n"
                                f"       {why}\n"
                                f"       {line.strip()[:110]}")
                    break

    console_scanned = 0
    for path in console_files():
        console_scanned += 1
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            hit = console_hit(line)
            if hit:
                rel = path.relative_to(ROOT).as_posix()
                hits.append(f"  BAD  {rel}:{lineno}  [console name] {hit!r}\n"
                            f"       name no console platform; say \"console\" instead\n"
                            f"       {line.strip()[:110]}")

    print(f"publication scrub: {scanned} synced source file(s) scanned, "
          f"{console_scanned} file(s) repo-wide for console names")
    print()
    print("A vocabulary check, not a leak detector. It matches these and nothing else:")
    for name, _, _ in RULES:
        print(f"  - {name}")
    print("  - a console platform name, anywhere in the repository")
    print()
    print("Prose describing the private tree in other words passes clean. This shares no list with")
    print("the benchmark's isolation scan, so passing one says nothing about the other, and a clean")
    print("run is not a clearance.")
    print()
    if hits:
        print(f"{len(hits)} line(s) still name the private tree. Fix the source IN THIS REPO:")
        for h in hits:
            print(h)
        return 1
    print("OK   nothing in the synced plugin source names the private tree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
