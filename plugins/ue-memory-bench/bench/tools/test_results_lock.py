#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for run_bench.py's results lock, fresh-run refusal, void-row split and duplicate-id check.

Everything happens in a temp dir with HOLDING redirected into it. No benchmark runs and no isolation
is applied: the isolation and subprocess entry points are replaced with ones that stop the test, so a
refusal that fails to fire can't go on to touch a real tree.

    python bench/tools/test_results_lock.py        # exit 1 on any failure
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS)
import run_bench as rb  # noqa: E402

tmp = tempfile.mkdtemp(prefix="lock-test-")
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("PASS  %s" % name)
    else:
        fail += 1
        print("FAIL  %s  %s" % (name, detail))


def write_rows(path, rows):
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write((r if isinstance(r, str) else json.dumps(r)) + "\n")


# A real answer, and the two shapes a platform refusal takes in a results file.
def real(qid):
    return {"id": qid, "answer": "a real answer", "is_error": False, "turns": 6,
            "calls_by_tool": {"Read": 3}, "tokens_total_in": 90000, "tokens_output": 900}


def refused_fast(qid):
    return {"id": qid, "answer": "You've hit your session limit - resets 12:40pm", "is_error": True,
            "turns": 1, "calls_by_tool": {}, "tokens_total_in": 0, "tokens_output": 0}


def refused_expensive(qid):
    return {"id": qid, "answer": "You've hit your session limit - resets 12:40pm", "is_error": True,
            "turns": 51, "calls_by_tool": {"Bash": 50}, "tokens_total_in": 1280697, "tokens_output": 4000}


def timed_out(qid):
    return {"id": qid, "answer": None, "is_error": True, "timed_out": True, "turns": 97,
            "calls_by_tool": {"Bash": 96}, "tokens_total_in": 2000000, "tokens_output": 9000}


# --- pid_alive: must be able to say yes AND no
dead = subprocess.Popen([sys.executable, "-c", "pass"])
dead.wait()
check("pid_alive(self) is True", rb.pid_alive(os.getpid()))
check("pid_alive(exited child) is False", not rb.pid_alive(dead.pid))
check("pid_alive(None) is False", not rb.pid_alive(None))

res = os.path.join(tmp, "results-layers-t.jsonl")
lock = res + ".lock"


def child_acquire(extra=""):
    code = ("import sys; sys.path.insert(0, %r); import run_bench as rb; "
            "rb.acquire_results_lock(%r%s); print('ACQUIRED')" % (TOOLS, res, extra))
    p = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


# --- a live holder blocks, with and without the flag
rb.acquire_results_lock(res)
check("lock file created with our pid", json.load(open(lock))["pid"] == os.getpid())
rc, out = child_acquire()
check("second writer refused while holder alive",
      rc != 0 and "another run is writing" in out and str(os.getpid()) in out, out[-300:])
rc, out = child_acquire(", break_stale=True")
check("--break-stale-lock never breaks a LIVE holder", rc != 0 and "another run is writing" in out, out[-300:])

# --- a stale holder: refused without the flag, broken with it
os.remove(lock)
json.dump({"pid": dead.pid, "started": "then", "argv": ["run_bench.py", "--arm", "layers"]}, open(lock, "w"))
rc, out = child_acquire()
check("stale lock refused without the flag", rc != 0 and "STALE" in out, out[-300:])
rc, out = child_acquire(", break_stale=True")
check("stale lock broken with the flag", rc == 0 and "ACQUIRED" in out, out[-300:])
check("child released its lock at exit", not os.path.exists(lock))

# --- void rows: both refusal shapes are void, a genuine timeout is not
check("fast refusal is void", rb.is_void_row(refused_fast("Q1")))
check("expensive refusal is void", rb.is_void_row(refused_expensive("Q1")))
check("a timeout is NOT void", not rb.is_void_row(timed_out("Q1")))
check("a real answer is NOT void", not rb.is_void_row(real("Q1")))

# --- split_void_rows moves the void rows out and keeps everything else, junk included
split = os.path.join(tmp, "results-split.jsonl")
write_rows(split, [real("Q1"), refused_fast("Q2"), refused_expensive("Q3"), timed_out("Q4"),
                   real("Q5"), refused_fast("Q5"), "not json at all"])
before = io.open(split, encoding="utf-8").read()
voidf = os.path.join(tmp, "results-split.void.jsonl")
rb.split_void_rows(split, voidf, dry_run=True)
check("dry run writes nothing", io.open(split, encoding="utf-8").read() == before and not os.path.exists(voidf))
done, void, unclassified = rb.split_void_rows(split, voidf)
kept = io.open(split, encoding="utf-8").read().splitlines()
moved = [json.loads(l) for l in io.open(voidf, encoding="utf-8")]
check("void rows moved out, rest kept", len(moved) == 3 and len(kept) == 4, "moved %d kept %d" % (len(moved), len(kept)))
check("done is Q1, Q4, Q5", done == {"Q1", "Q4", "Q5"}, str(done))
check("an id with a real AND a void row keeps only the real one",
      sum(1 for l in kept if '"Q5"' in l) == 1)
check("the non-JSON line survives", "not json at all" in kept)
check("the timeout is kept as recorded and reported as unclassified", unclassified == ["Q4"], str(unclassified))

# --- duplicate_ids: must say yes on a duplicated file, and no on a clean one
dup = os.path.join(tmp, "results-dup.jsonl")
write_rows(dup, [real("Q1"), real("Q2"), real("Q1"), refused_fast("Q3"), refused_fast("Q3")])
check("duplicate_ids finds a real id recorded twice", rb.duplicate_ids(dup) == {"Q1": 2}, str(rb.duplicate_ids(dup)))
clean = os.path.join(tmp, "results-clean.jsonl")
write_rows(clean, [real("Q1"), real("Q2"), refused_fast("Q3")])
check("duplicate_ids is empty on a clean file (void rows don't count)", rb.duplicate_ids(clean) == {})

# --- fresh-run refusal: a non-empty results file and no --resume
rb.HOLDING = tmp


def _stop(*a, **k):
    raise SystemExit("REACHED_ISOLATION - refusal did not fire")


rb.stage_isolation = _stop
rb.ps = _stop
rb.subprocess = None  # any subprocess use before the refusal raises instead of running
runset = os.path.join(tmp, "runset-t.json")
json.dump({"questions": [{"id": "Q001", "question": "?"}]}, open(runset, "w"))
write_rows(os.path.join(tmp, "results-layers-t.jsonl"), [real("Q001")])
argv = sys.argv
sys.argv = ["run_bench.py", "--arm", "layers", "--runset", runset]
try:
    rb.main()
    msg = "main returned"
except SystemExit as e:
    msg = str(e.code)
except Exception as e:  # a crash before the refusal is a failure, and says where
    msg = "%s: %s" % (type(e).__name__, e)
sys.argv = argv
check("fresh run refuses a non-empty results file", "already holds 1 row" in msg, msg[:300])

shutil.rmtree(tmp, ignore_errors=True)
print("\n%d passed, %d failed" % (ok, fail))
sys.exit(1 if fail else 0)
