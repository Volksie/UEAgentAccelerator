"""Where the tree being measured is, found rather than counted.

WHY THIS EXISTS. Every tool here used to work the tree out as "two directories above this file". That
is right while nothing moves, and it fails in the worst available way when something does: the path
resolves to a real directory one level off, every path built on it is wrong, and what the tool then
reports is a missing runset, or an empty results file, or a configuration it says the sync did not
bring down. The cause is never mentioned. We hit exactly that in a PowerShell loader that derived a
client root the same way, where moving it one folder made it blame Perforce for a file that was there.

So: search upwards for something that identifies the tree, and say so when there is nothing to find.

`UEAA_TREE` still wins over both. It is how you point these tools at a tree other than the one they
happen to be sitting in.
"""
from __future__ import annotations

import os
import sys

# What marks a tree these tools can run against, best first. bench/projects.json is the one that says
# which projects the questions are drawn from, so a directory holding it is the tree by definition.
# bench/tools is the weaker fallback for a checkout that has not been configured yet.
MARKERS = (os.path.join("bench", "projects.json"), os.path.join("bench", "tools"))


def find_tree_root(start: str | None = None, warn: bool = True) -> str:
    """The nearest directory at or above `start` that looks like the tree. Never raises.

    Falls back to two levels above `start`, which is what the tools assumed before, and says on stderr
    that it did. A wrong answer here makes every later path wrong, so it is worth one line of noise.
    """
    env = os.environ.get("UEAA_TREE")
    if env:
        return os.path.abspath(env)

    start = os.path.abspath(start or os.path.dirname(os.path.abspath(__file__)))
    for marker in MARKERS:
        d = start
        while True:
            if os.path.exists(os.path.join(d, marker)):
                return d
            parent = os.path.dirname(d)
            if parent == d:          # at the volume root
                break
            d = parent

    fallback = os.path.abspath(os.path.join(start, "..", ".."))
    if warn:
        print("warning: no %s in or above %s, so the tree is being taken as %s. Set UEAA_TREE if that "
              "is wrong." % (" or ".join(MARKERS), start, fallback), file=sys.stderr)
    return fallback
