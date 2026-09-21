"""Measure what a clangd background index costs, per compile-database scope.

The open question this answers: what does engine-tier clangd indexing cost on your
hardware, and should Layer 1 span the engine or stop at the project boundary?

Three scopes, same machine, same clangd:
  project  - the project TUs only
  scoped   - only the engine TUs the project actually depends on, plus the project TUs
  full     - every engine TU

What it measures: wall clock to a quiet index, files and bytes on disk, and peak clangd RSS.
Completion is detected by the index directory going quiet rather than by a log line, because
clangd's "indexed N/M" output is not a reliable end marker.

Usage:
    python bench/tools/measure_clangd_index.py --scope project
    python bench/tools/measure_clangd_index.py --scope scoped --timeout 3600
"""
import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import time

# Machine specific, so they are environment overridable rather than baked in. TREE defaults to the
# repository root two levels above this file; CLANGD to whatever is on PATH; PROJ and SEED to the
# seed project, which is the one thing we know exists in a fresh clone.
# The tree, searched for rather than counted. See _tree_root.py: two-levels-up is right
# until something moves, and then every path built on it is quietly wrong.
from _tree_root import find_tree_root
TREE   = find_tree_root(os.path.dirname(os.path.abspath(__file__)))
CLANGD = os.environ.get("UEAA_CLANGD") or "clangd.exe"
PROJ   = os.environ.get("UEAA_PROJECT") or os.path.join(TREE, "seed", "AccelDemo")
SEED   = os.environ.get("UEAA_SEED_TU") or os.path.join(
    PROJ, "Source", "AccelDemoCore", "Private", "ADStaminaComponent.cpp")
# clangd writes its background index under the directory holding compile_commands.json - which is
# the staging dir here, NOT the project root. Watching <project>/.cache reported 0 files for a run
# that had in fact written 1,198 shards and 18 MB. Measured 2026-09-08.
CACHE = None  # set once the staging directory is known

SCOPES = {
    "project": "compile_commands_project.json",   # written by this script
    "scoped": "compile_commands_scoped.json",     # engine deps + project
    "full": "compile_commands_full.json",         # every engine TU
}


def dir_stats(d):
    n, b = 0, 0
    for root, _, files in os.walk(d):
        for f in files:
            try:
                b += os.path.getsize(os.path.join(root, f))
                n += 1
            except OSError:
                pass
    return n, b


def rss_mb(pid):
    """Peak working set of a process, via PowerShell. Returns 0 if it has exited."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-Process -Id %d -ErrorAction SilentlyContinue).PeakWorkingSet64" % pid],
            capture_output=True, text=True, timeout=20).stdout.strip()
        return int(out) / (1024.0 * 1024.0) if out.isdigit() else 0.0
    except Exception:
        return 0.0


def make_project_only_db():
    """The 4 project TUs, extracted from the scoped db. Written once, then reused."""
    src = os.path.join(PROJ, "compile_commands_scoped.json")
    dst = os.path.join(PROJ, SCOPES["project"])
    d = json.load(io.open(src, encoding="utf-8"))
    keep = [e for e in d if "/UnrealEngine/" not in e.get("file", "").replace("\\", "/")]
    with io.open(dst, "w", encoding="utf-8", newline="\n") as f:
        json.dump(keep, f, indent=1)
    return dst, len(keep)


def lsp(msg):
    body = json.dumps(msg)
    return ("Content-Length: %d\r\n\r\n%s" % (len(body), body)).encode("utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope", help="named scope from SCOPES, relative to the project")
    ap.add_argument("--db", help="explicit path to a compile database, overrides --scope")
    ap.add_argument("--label", help="name for this measurement in the results file")
    # The index lives in the staging dir and survives the process, so a run that hits its ceiling
    # can be continued rather than restarted. Without this the staging dir is wiped and a long
    # build starts from zero.
    ap.add_argument("--no-reset", action="store_true",
                    help="keep an existing index in the staging dir and continue building it")
    ap.add_argument("--timeout", type=int, default=1800, help="seconds before giving up")
    ap.add_argument("--quiet-for", type=int, default=90,
                    help="seconds of no index growth that counts as finished")
    # Background indexing runs one worker per core by default. On a 24-core machine that is 24
    # concurrent UE ASTs, which is what produced 11.3 GB - a parallelism cost, not a floor.
    ap.add_argument("-j", type=int, default=4, help="clangd background index workers")
    ap.add_argument("--pch-storage", default="disk", choices=["disk", "memory"])
    args = ap.parse_args()

    if args.db:
        dbpath = args.db if os.path.isabs(args.db) else os.path.join(TREE, args.db)
        dbname = os.path.basename(dbpath)
        args.scope = args.label or os.path.splitext(dbname)[0]
    else:
        if not args.scope:
            sys.exit("give --scope or --db")
        if args.scope == "project":
            dbfile, n = make_project_only_db()
            print("wrote %s with %d project TUs" % (os.path.basename(dbfile), n))
        dbname = SCOPES[args.scope]
        dbpath = os.path.join(PROJ, dbname)
    if not os.path.exists(dbpath):
        sys.exit("missing %s" % dbpath)
    entries = len(json.load(io.open(dbpath, encoding="utf-8")))

    # clangd reads compile_commands.json from --compile-commands-dir, so stage the chosen scope
    # into a directory of its own rather than overwriting the project's active database.
    stage = os.path.join(TREE, "bench", "runs", "clangd-%s" % args.scope)
    resumed_from = 0
    if os.path.exists(stage) and not args.no_reset:
        shutil.rmtree(stage, ignore_errors=True)
    if not os.path.exists(stage):
        os.makedirs(stage)
    shutil.copy(dbpath, os.path.join(stage, "compile_commands.json"))

    # The staging dir is fresh, so the index under it starts empty and the number is a build
    # cost rather than a top-up.
    global CACHE
    CACHE = os.path.join(stage, ".cache", "clangd", "index")
    if args.no_reset and os.path.exists(CACHE):
        resumed_from, resumed_bytes = dir_stats(CACHE)
        print("resuming: %d shards, %.1f MB already on disk" % (resumed_from, resumed_bytes / 1e6))

    seed = SEED
    if not os.path.exists(seed):
        sys.exit("seed file missing: %s" % seed)

    print("scope=%s  db=%s  entries=%d" % (args.scope, dbname, entries))
    print("starting clangd, quiet-for=%ds, timeout=%ds" % (args.quiet_for, args.timeout))

    proc = subprocess.Popen(
        [CLANGD, "--compile-commands-dir=" + stage, "--background-index",
         "-j", str(args.j), "--pch-storage=" + args.pch_storage,
         "--background-index-priority=low",
         "--header-insertion=never", "--log=error"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=PROJ)

    started = time.time()
    try:
        proc.stdin.write(lsp({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                              "params": {"processId": os.getpid(),
                                         "rootUri": "file:///" + PROJ.replace("\\", "/"),
                                         "capabilities": {}}}))
        proc.stdin.flush()
        time.sleep(3)
        proc.stdin.write(lsp({"jsonrpc": "2.0", "method": "initialized", "params": {}}))
        proc.stdin.write(lsp({"jsonrpc": "2.0", "method": "textDocument/didOpen",
                              "params": {"textDocument": {
                                  "uri": "file:///" + seed.replace("\\", "/"),
                                  "languageId": "cpp", "version": 1,
                                  "text": io.open(seed, encoding="utf-8", errors="replace").read()}}}))
        proc.stdin.flush()

        last_bytes, last_change, peak = -1, time.time(), 0.0
        while True:
            time.sleep(15)
            elapsed = time.time() - started
            n, b = dir_stats(CACHE) if os.path.exists(CACHE) else (0, 0)
            peak = max(peak, rss_mb(proc.pid))
            print("  %6.0fs  %6d files  %8.1f MB index  %7.0f MB peak rss"
                  % (elapsed, n, b / 1e6, peak), flush=True)
            if b != last_bytes:
                last_bytes, last_change = b, time.time()
            elif time.time() - last_change > args.quiet_for and b > 0:
                print("  index quiet for %ds - finished" % args.quiet_for)
                break
            if elapsed > args.timeout:
                print("  TIMEOUT at %ds - index still growing, this is a lower bound" % args.timeout)
                break
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=30)
        except Exception:
            proc.kill()

    n, b = dir_stats(CACHE) if os.path.exists(CACHE) else (0, 0)
    result = {
        "scope": args.scope, "db": dbname, "db_entries": entries,
        "workers": args.j, "pch_storage": args.pch_storage,
        "seconds": round(time.time() - started, 1),
        "index_files": n, "index_bytes": b, "peak_rss_mb": round(peak, 1),
        "resumed_from_shards": resumed_from,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    out = os.path.join(TREE, "bench", "runs", "clangd-index-cost.jsonl")
    with io.open(out, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(result) + "\n")
    print("\n%s" % json.dumps(result, indent=2))
    print("appended -> %s" % out)


if __name__ == "__main__":
    main()
