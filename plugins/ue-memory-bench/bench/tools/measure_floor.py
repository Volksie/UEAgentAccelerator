"""Measure the standing per-turn cost of a harness configuration, by asking it nothing.

WHY THIS EXISTS. The layers arm pays 16,212 tokens more per turn than the baseline arm, and across a
160-question run that is about 14M tokens, roughly 37% of the arm's total. Before cutting anything we
need to know what the pieces actually cost, and the honest way to find that out is to measure each
configuration rather than to add up file sizes and assume the tokenizer agrees.

The probe is the same one run_bench.py uses: "Reply with exactly: OK". Whatever comes back as input
tokens is what that configuration charges before a single question is asked.

Usage:
    python bench/tools/measure_floor.py                       # every configuration
    python bench/tools/measure_floor.py --only serena-only    # just one
"""
from __future__ import annotations

import argparse
import io
import json
import os
import pathlib
import subprocess
import sys
import time

# Machine specific, so they are environment overridable rather than baked in. TREE defaults to the
# repository root two levels above this file, which is where it sits in both the working tree and the
# published repo. Same pattern as run_bench.py and score_answers.py.
# The tree, searched for rather than counted. See _tree_root.py: two-levels-up is right
# until something moves, and then every path built on it is quietly wrong.
from _tree_root import find_tree_root
TREE = pathlib.Path(find_tree_root(os.path.dirname(os.path.abspath(__file__))))
CLAUDE = os.environ.get("UEAA_CLAUDE") or os.path.expanduser(
    os.path.join("~", ".local", "bin", "claude"))
# Outside the tree on purpose: isolation moves tree paths into it, so a holding directory
# inside the tree would move itself.
HOLDING = pathlib.Path(os.environ.get("UEAA_HOLDING") or
                       TREE.parent / ".uea-bench-holding")
PROBE = "Reply with exactly: OK"

SERENA = {"type": "http", "url": "http://127.0.0.1:24290/mcp", "timeout": 900000}
# Your own MCP surface goes here. Each line of the CONFIGS list below is a configuration you can
# price, so replace these with what your agents actually load rather than measuring ours.
# `sys.executable` rather than a hardcoded interpreter: a path baked in here is the first thing
# that breaks on somebody else's machine.
ENGINE_API = {
    "type": "stdio",
    "command": sys.executable,
    "args": [str(TREE / "tools" / "engine-api-db" / "mcp_server.py")],
    "env": {},
}

# Each configuration is (name, mcp servers, extra claude args, note).
# "no project context" uses --bare, which skips CLAUDE.md auto-discovery and auto-memory, so the
# difference against the same MCP surface is what the project's own instructions cost.
# --bare needs an explicit credential because it never reads OAuth or the keychain. The judge already
# runs that way, so borrow its settings file rather than inventing a second one.
BENCH_SETTINGS = os.environ.get("UEAA_BENCH_SETTINGS") or os.path.expanduser(
    os.path.join("~", ".claude", "bench-settings.json"))
BARE = ["--bare", "--settings", BENCH_SETTINGS]

CONFIGS = [
    ("no-mcp",             {},                                      [], "harness alone"),
    ("serena-only",        {"serena": SERENA},                      [], "the baseline arm's surface"),
    ("serena+engine-api",  {"serena": SERENA, "engine-api": ENGINE_API}, [], "the layers arm's surface"),
    ("bare-no-mcp",        {},                                    BARE, "no CLAUDE.md, no rules, no memory"),
    ("bare+serena",        {"serena": SERENA},                    BARE, "MCP cost without project context"),
]


def probe(name, servers, extra, model, timeout_s):
    cfg = HOLDING / ("floorprobe-%s.json" % name)
    HOLDING.mkdir(parents=True, exist_ok=True)
    with io.open(cfg, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"mcpServers": servers}, f, indent=2)

    cmd = [CLAUDE, "-p", PROBE, "--model", model, "--output-format", "json",
           "--no-session-persistence", "--strict-mcp-config", "--mcp-config", str(cfg)] + extra
    t0 = time.time()
    p = subprocess.run(cmd, cwd=str(TREE), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout_s)
    try:
        d = json.loads(p.stdout or "{}")
    except ValueError:
        return None, "unparseable output: %s" % (p.stdout or "")[-200:]
    if d.get("is_error"):
        return None, str(d.get("result"))[:200]
    u = d.get("usage", {}) or {}
    total = (u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
             + u.get("cache_creation_input_tokens", 0))
    return {"tokens": total, "seconds": round(time.time() - t0, 1)}, None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default="opus")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--only", default=None, help="measure a single named configuration")
    args = ap.parse_args()

    todo = [c for c in CONFIGS if args.only in (None, c[0])]
    if not todo:
        print("no configuration named %r. Known: %s" % (args.only, ", ".join(c[0] for c in CONFIGS)))
        return 1

    print("probe: %r  cwd: %s\n" % (PROBE, TREE))
    got = {}
    for name, servers, extra, note in todo:
        res, err = probe(name, servers, extra, args.model, args.timeout)
        if err:
            print("  %-20s FAILED  %s" % (name, err))
            continue
        got[name] = res["tokens"]
        print("  %-20s %8s tok  (%4.1fs)   %s" % (name, "{:,}".format(res["tokens"]),
                                                  res["seconds"], note))

    # The deltas are the point. Adding up file sizes and assuming is how the last estimate went wrong.
    print("\n=== what each piece actually costs, measured ===")
    def delta(a, b, label):
        if a in got and b in got:
            print("  %-46s %+8s tok/turn" % (label, "{:,}".format(got[b] - got[a])))
    delta("no-mcp", "serena-only", "serena's tool schemas")
    delta("serena-only", "serena+engine-api", "engine-api's 6 tool schemas (deferred)")
    delta("bare-no-mcp", "no-mcp", "CLAUDE.md + .claude/rules/ + CLAUDE.local.md")
    delta("bare-no-mcp", "bare+serena", "serena's schemas again, as a cross-check")
    if "bare-no-mcp" in got and "no-mcp" in got:
        ctx = got["no-mcp"] - got["bare-no-mcp"]
        files = 12012 + 26227 + 636  # CLAUDE.md + .claude/rules/* + CLAUDE.local.md
        print("\n  project instruction files on disk: %s bytes" % "{:,}".format(files))
        print("  measured cost of loading them     : %s tok/turn" % "{:,}".format(ctx))
        if ctx > 0:
            print("  so about %.1f bytes per token, which is why a 4-bytes-per-token estimate" % (files / ctx))
            print("  understated this by a wide margin. Markdown tables tokenize badly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
