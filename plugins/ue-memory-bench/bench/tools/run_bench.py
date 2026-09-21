"""Run one benchmark arm: one question per fresh `claude -p` session.

Method follows bench/BASELINE-ARM-SPEC.md:
  - one question per fresh session, in sequence (never batched: batching was measured 4.6x cheaper
    but dropped tool calls from 21 to 9 across five questions, because each question inherited what
    the last one learned, and tool calls are a scored column)
  - the answer keys and (for the baseline arm) the memory layers are moved out of the tree first
  - results are written incrementally, so a rate-limit stall or a crash loses at most one question

Tool calls and retrieval bytes come from parsing the stream-json event log rather than asking the
agent to self-report. Self-reporting would add instructions to every prompt and change what is
being measured.

Usage:
    python bench/tools/run_bench.py --arm baseline --set smoke
    python bench/tools/run_bench.py --arm layers   --set smoke
    python bench/tools/run_bench.py --arm baseline --set full --resume

The tree is modified while this runs. Do not build, regenerate dumps, or run another Claude
session in this tree until it reports RESTORED.
"""
import argparse
import datetime
import io
import json
import os
import subprocess
import sys
import time

# Machine specific, so they are environment overridable rather than baked in. TREE defaults to the
# repository root two levels above this file. HOLDING must sit OUTSIDE the tree, because the
# isolation step moves tree paths into it.
# The tree, searched for rather than counted. See _tree_root.py: two-levels-up is right
# until something moves, and then every path built on it is quietly wrong.
from _tree_root import find_tree_root
TREE = find_tree_root(os.path.dirname(os.path.abspath(__file__)))
HOLDING = os.environ.get("UEAA_HOLDING") or os.path.join(
    os.path.dirname(TREE), ".uea-bench-holding")
CLAUDE = os.environ.get("UEAA_CLAUDE") or "claude"

# WHERE THE BASELINE ARM RUNS, with --isolation room.
#
# Built by bench/tools/Build-BaselineRoot.ps1: a clean root beside the tree containing only what that
# arm may see. See METHOD.md on why an allowlist beats moving files aside.
#
# The room is NOT the control. The tree is still one absolute path away and an agent with a shell can
# read it, so this is defence in depth: it removes what is present by default. What proves a clean run
# is a per-question record of what each question reached for, which this runner does not yet keep.
ROOM = os.environ.get("UEAA_ROOM") or os.path.join(
    os.path.dirname(TREE), "." + os.path.basename(TREE.rstrip("\\/")) + "-baseline-room")
ROOM_BUILDER = os.path.join(TREE, "bench", "tools", "Build-BaselineRoot.ps1")

# WHAT EACH ARM MAY CALL, from bench/arms.json. Passed with --strict-mcp-config, so an arm gets exactly
# these servers and nothing from the user's own ~/.claude.json. Before this the runner inherited the
# user's registrations, which put a language server into the baseline arm - an arm defined as having
# nothing we built - and nothing recorded that it had happened.
ARMS_PATH = os.environ.get("UEAA_ARMS") or os.path.join(TREE, "bench", "arms.json")


def load_arms():
    if not os.path.exists(ARMS_PATH):
        sys.exit("Missing %s. It defines what each arm may call; see the copy in the repository." % ARMS_PATH)
    with io.open(ARMS_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    for arm in ("baseline", "layers"):
        if arm not in cfg:
            sys.exit("%s has no %r entry" % (ARMS_PATH, arm))
    return cfg


ARMS = None             # set by main()
ARM = "baseline"        # set by main(); selects the allowlist in run_one
MCP_CONFIG_PATH = None  # set by main() once staged

# The isolation script lives in bench/tools, and bench/ is the first thing it moves aside - so
# invoking it from the tree deletes it mid-run and leaves Verify and Restore with nothing to call.
# It is copied into the holding directory at startup and always invoked from there.
ISOLATION_SRC = os.path.join(TREE, "bench", "tools", "baseline-isolation.ps1")
ISOLATION_RUN = os.path.join(HOLDING, "baseline-isolation.ps1")

# Measured 2026-09-07 on this machine: a "reply with exactly: OK" probe through the real harness
# (Serena + auto-loaded CLAUDE.md + the user's MCP config). It is recorded in each run's meta file so
# a later session knows what the arm was carrying; nothing subtracts it. Re-measure it for YOUR
# harness with measure_floor.py, and per arm - two arms with different tool surfaces do not share one.
FLOOR_TOKENS = 47303


def stage_isolation():
    """Copy the isolation script out of the tree before anything is moved.

    Returns the staged path. Called before Apply, so the tool survives its own operation.
    """
    if not os.path.exists(HOLDING):
        os.makedirs(HOLDING)
    if not os.path.exists(ISOLATION_SRC):
        sys.exit("Missing %s" % ISOLATION_SRC)
    with io.open(ISOLATION_SRC, encoding="utf-8") as a:
        body = a.read()
    with io.open(ISOLATION_RUN, "w", encoding="utf-8", newline="\n") as b:
        b.write(body)
    return ISOLATION_RUN


def ps(*args):
    """Run the staged isolation script. Returns (exit_code, output)."""
    script = ISOLATION_RUN if os.path.exists(ISOLATION_RUN) else ISOLATION_SRC
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script] + list(args)
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def parse_stream(lines):
    """Pull the scored columns out of a stream-json event log.

    Returns tool call count, retrieval bytes, per-tool breakdown, final text, and usage.
    Retrieval bytes is the summed length of tool RESULT content: what the session actually pulled
    into context, which is the quantity goal 3 is about. Counting the files' full size on disk
    would overstate it for a targeted grep.
    """
    calls = 0
    retrieval = 0
    by_tool = {}
    tool_errors = []
    final_text = None
    usage = {}
    duration_ms = None
    is_error = False
    result_field = None

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue

        etype = ev.get("type")

        if etype == "assistant":
            for block in (ev.get("message", {}) or {}).get("content", []) or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    calls += 1
                    name = block.get("name", "?")
                    by_tool[name] = by_tool.get(name, 0) + 1

        elif etype == "user":
            for block in (ev.get("message", {}) or {}).get("content", []) or []:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    # Capture the error itself. A run where a tool "wasn't granted" on some questions
                    # could not otherwise say whether that was a permission refusal, a dead server, or
                    # the model paraphrasing something else.
                    if block.get("is_error"):
                        etext = block.get("content")
                        if isinstance(etext, list):
                            etext = " ".join(c.get("text", "") for c in etext if isinstance(c, dict))
                        tool_errors.append(str(etext)[:400])
                    content = block.get("content")
                    if isinstance(content, str):
                        retrieval += len(content)
                    elif isinstance(content, list):
                        for c in content:
                            if isinstance(c, dict) and isinstance(c.get("text"), str):
                                retrieval += len(c["text"])

        elif etype == "result":
            usage = ev.get("usage", {}) or {}
            duration_ms = ev.get("duration_ms")
            is_error = bool(ev.get("is_error"))
            result_field = ev.get("result")
            final_text = ev.get("result")

    total_in = (usage.get("input_tokens", 0)
                + usage.get("cache_read_input_tokens", 0)
                + usage.get("cache_creation_input_tokens", 0))

    return {
        "calls": calls,
        "calls_by_tool": by_tool,
        "tool_errors": tool_errors,
        "retrieval_bytes": retrieval,
        "answer": final_text,
        "raw_result": result_field,
        "is_error": is_error,
        "duration_ms": duration_ms,
        "tokens_total_in": total_in,
        # `tokens_above_floor` used to sit here as `total_in - FLOOR_TOKENS`, and it is gone rather
        # than corrected, because there is nothing to correct it to. It subtracts one floor from a
        # session that pays the standing context on EVERY turn, so the obvious fix is
        # `total_in - floor * turns`. Measured on a 160-question run, that goes negative on 131 of 160
        # baseline questions and 146 of 160 with layers, because the implied per-turn input is not a
        # constant: it ran 21,278 to 70,129 with a median of 30,970 against a floor probe of 37,414.
        # Cache reads dominate the total and do not accumulate at one flat rate per turn.
        #
        # So report what was measured - total input, and turns - and let the reader divide.
        "turns": calls + 1,
        "tokens_output": usage.get("output_tokens", 0),
        "usage": usage,
    }


# The built-in tool surface, identical in both arms.
#
# Set this deliberately or the run inherits whatever `claude -p` defaults to, which includes Write and
# Edit. Two things go wrong then. A run that measures a tree can modify the tree it is measuring; and a
# retrieval question becomes answerable by leaving notes for the next question, which is a different
# experiment from the one you think you are running. Measured on one benchmark run before this was
# set: the baseline arm used Write 23 times and Edit 10 times.
#
# `--tools` is the right flag and `--allowedTools` is not. The first controls which built-in tools
# EXIST; the second only controls which ones skip a permission prompt. `--tools` is scoped to the
# built-in set and does not affect MCP servers.
#
# ToolSearch is in the list because MCP tool schemas are deferred. Without it an arm can see that a
# server exists and never be able to call it, which silently measures the wrong thing.
BUILTIN_TOOLS = ["Bash", "Read", "Grep", "Glob", "ToolSearch"]

# Serena ships write tools of its own, so restricting the built-ins alone still leaves a measured run
# able to edit the tree through replace_content or a symbol body rewrite. Its project memories are a
# second problem: they persist across questions, so one question can answer the next in either arm.
# `--disallowedTools` removes these from the surface entirely rather than refusing them at call time,
# so they cost nothing in schema tokens either.
DISALLOWED_TOOLS = [
    "mcp__serena__write_memory",
    "mcp__serena__delete_memory",
    "mcp__serena__edit_memory",
    "mcp__serena__rename_memory",
    "mcp__serena__read_memory",
    "mcp__serena__list_memories",
    "mcp__serena__replace_content",
    "mcp__serena__replace_in_files",
    "mcp__serena__replace_symbol_body",
    "mcp__serena__insert_after_symbol",
    "mcp__serena__insert_before_symbol",
    "mcp__serena__rename_symbol",
    "mcp__serena__safe_delete_symbol",
    "mcp__serena__onboarding",
    "mcp__serena__open_dashboard",
]


def run_one(question_text, model, timeout_s, cwd=None):
    cmd = [
        CLAUDE, "-p", question_text,
        "--model", model,
        "--output-format", "stream-json",
        "--verbose",
        "--no-session-persistence",
        "--tools", ",".join(BUILTIN_TOOLS),
        "--disallowedTools", ",".join(DISALLOWED_TOOLS),
    ]
    # Without this an MCP tool auto-denies under -p, silently and per call.
    allowed = ((ARMS or {}).get(ARM) or {}).get("allowed_mcp_tools") or []
    if allowed:
        cmd += ["--allowedTools", ",".join(allowed)]
    if MCP_CONFIG_PATH:
        cmd += ["--strict-mcp-config", "--mcp-config", MCP_CONFIG_PATH]
    started = time.time()
    try:
        p = subprocess.run(cmd, cwd=cwd or TREE, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout_s)
        out = p.stdout or ""
        rec = parse_stream(out.splitlines())
        rec["exit_code"] = p.returncode
        if p.returncode != 0 and not rec.get("answer"):
            rec["stderr_tail"] = (p.stderr or "")[-800:]
    except subprocess.TimeoutExpired as e:
        # KEEP WHAT IT DID. This used to write a fixed record of 0 calls and 0 turns, so two questions
        # that timed out read as sessions that had hung without starting. They had been working: one
        # re-ran in 341s and 31 turns. The answer stays None; only the evidence is kept.
        partial = e.stdout or b""
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", "replace")
        rec = parse_stream(partial.splitlines())
        rec.update({"answer": None, "is_error": True, "timed_out": True, "exit_code": None})
    rec["wall_seconds"] = round(time.time() - started, 1)
    return rec


SKIP_DIRS = {"UnrealEngine", "Intermediate", "Binaries", "DerivedDataCache", "Saved", ".git",
             "node_modules", ".vs"}

# Phrases that should not be readable anywhere in the tree during a baseline run. The first two are
# artefact formats, the third and fourth are answer-key wording.
# Path fragments that identify a Layer 2 artefact tree inside an archive.
ARTEFACT_MARKERS = [
    "classes/", "bpcallers/", "blueprints/",
    "blueprintcallers.md", "index.md",
]

LEAK_SIGNATURES = [
    "BlueprintCallers",
    "There is no such function",
    "GenerateProjectFiles` is not needed for C++",
]


def leak_scan(arm):
    """Look for copies of what was moved aside: archives, and files quoting keys or artefacts.

    Moving a directory does nothing if a zip of it is sitting beside it - which is exactly what
    agentmemory.zip turned out to be. This runs after Verify and fails the run on any hit.
    """
    if arm != "baseline":
        return []
    hits = []
    # Artefact trees are recognised by SHAPE, not by being called AgentMemory. Two copies were
    # missed by name-based exclusion: a stray backup of one project's artefacts, and a second
    # holding index.md + classes/*.md. Anything with this shape outside the excluded paths is a
    # leak regardless of what the directory is called.
    ARTEFACT_DIRS = {"classes", "bpcallers", "blueprints"}
    ARTEFACT_FILES = {"index.md", "blueprintcallers.md", "blueprints.md"}

    for root, dirs, files in os.walk(TREE):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        rel_root = os.path.relpath(root, TREE)
        for d in dirs:
            if d.lower() not in ARTEFACT_DIRS:
                continue
            # Name alone is not enough: a project can ship Content/Audio/Blueprints and Content/Audio/Classes,
            # which are .uasset directories and legitimate codebase content. An artefact tree is
            # markdown. That is the discriminator.
            full = os.path.join(root, d)
            try:
                if any(f.lower().endswith(".md") for f in os.listdir(full)):
                    hits.append(("artefact-shaped dir", os.path.join(rel_root, d)))
            except OSError:
                pass
        for fn in files:
            if fn.lower() in ARTEFACT_FILES:
                hits.append(("artefact-shaped file", os.path.join(rel_root, fn)))
        for fn in files:
            path = os.path.join(root, fn)
            rel = os.path.relpath(path, TREE)
            low = fn.lower()
            if low.endswith(".zip"):
                # Judge an archive by what is inside it, not by its extension. A project can ship its own
                # user guide as a zip and that is benchmark content - the prose corpus the depth
                # project exists to provide. agentmemory.zip held 104 classes/*.md and was not.
                try:
                    import zipfile
                    with zipfile.ZipFile(path) as z:
                        names = z.namelist()
                except Exception:
                    hits.append(("unreadable-archive", rel))
                    continue
                bad = [n for n in names if any(p in n.replace("\\", "/").lower() for p in ARTEFACT_MARKERS)]
                if bad:
                    hits.append(("archive holds %d artefact entries e.g. %s" % (len(bad), bad[0]), rel))
                continue
            if low.endswith((".7z", ".tar", ".tar.gz", ".tgz", ".rar")):
                # Cannot inspect these without extra dependencies; surface for a human decision.
                hits.append(("uninspectable-archive", rel))
                continue
            if not low.endswith((".md", ".txt", ".json", ".yml", ".yaml", ".ini")):
                continue
            try:
                if os.path.getsize(path) > 4 * 1024 * 1024:
                    continue
                with io.open(path, encoding="utf-8", errors="ignore") as f:
                    body = f.read()
            except (IOError, OSError):
                continue
            for sig in LEAK_SIGNATURES:
                if sig in body:
                    hits.append(("signature:%s" % sig[:28], rel))
                    break
    return hits


def stage_mcp_config(arm):
    """Write the arm's MCP config into HOLDING and return its path.

    HOLDING rather than bench/: bench/ is moved aside by isolation, so a config inside it would vanish
    mid-run and every later question would silently fall back to the user's own MCP surface.
    """
    if not os.path.exists(HOLDING):
        os.makedirs(HOLDING)
    path = os.path.join(HOLDING, "mcp-%s.json" % arm)
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"mcpServers": ARMS[arm].get("mcp_servers") or {}}, f, indent=2)
    return path


def probe_stdio_mcp_servers(arm, cwd, timeout_s=60):
    """Start every stdio MCP server the arm is defined as having, AFTER isolation, and require tools.

    A missing MCP server is not an error to the CLI. It just removes those tools, and the run carries on
    measuring a different stack. We lost the first attempt at a whole arm that way: isolation held the
    directory the server's script lived in, the floor fell by the size of its schemas, and 26 questions
    ran with zero calls to it before anyone noticed. So the check has to be ours, it has to run after
    isolation (that is what broke it), and it has to reach tools/list, because a server that starts and
    then cannot open its data is just as absent.

    Returns {name: {"ok": bool, "tools": n, "error": str}}. Never raises.
    """
    import threading

    results = {}
    for name, cfg in (ARMS[arm].get("mcp_servers") or {}).items():
        if cfg.get("type") != "stdio":
            continue
        res = {"ok": False, "tools": 0, "error": None}
        try:
            p = subprocess.Popen([cfg["command"]] + list(cfg.get("args") or []),
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 cwd=cwd, text=True, encoding="utf-8",
                                 env=dict(os.environ, **(cfg.get("env") or {})))
            lines = []

            def reader():
                for line in p.stdout:
                    lines.append(line)

            threading.Thread(target=reader, daemon=True).start()

            def ask(msg, want_id):
                p.stdin.write(json.dumps(msg) + "\n")
                p.stdin.flush()
                deadline = time.time() + timeout_s
                while time.time() < deadline:
                    for line in list(lines):
                        try:
                            obj = json.loads(line)
                        except ValueError:
                            continue
                        if obj.get("id") == want_id:
                            return obj
                    if p.poll() is not None:
                        return None
                    time.sleep(0.1)
                return None

            init = ask({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-03-26", "capabilities": {},
                "clientInfo": {"name": "run_bench-mcp-probe", "version": "1"}}}, 1)
            if not init or "result" not in init:
                err = (p.stderr.read() if p.poll() is not None else "") or ""
                res["error"] = "no initialize reply; exit=%s; stderr=%s" % (p.poll(), err[-300:])
            else:
                p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
                p.stdin.flush()
                listed = ask({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}, 2)
                n = len(((listed or {}).get("result") or {}).get("tools") or [])
                res.update({"ok": n > 0, "tools": n})
                if n == 0:
                    res["error"] = "tools/list returned no tools: %s" % json.dumps(listed)[:300]
            try:
                p.kill()
            except Exception:
                pass
        except Exception as e:
            res["error"] = repr(e)[:300]
        results[name] = res
        print("     mcp %-12s %s" % (name, ("ok, %d tools" % res["tools"]) if res["ok"]
                                    else "NOT AVAILABLE: %s" % res["error"]))
    return results


def warm_up_serena(model, gate, cwd, attempts=4):
    """Prove Serena answers a scoped lookup, through the real harness, before question 1.

    Through `claude -p` rather than a port check: an open port says a connection was accepted, not that
    the language server behind it will answer, which is the failure this exists to catch. Scoped,
    because an unscoped find_symbol times out on an engine tree and would measure the wrong thing.

    Passing this does NOT prove clangd has an index loaded - a scoped lookup can come from Serena's own
    cache. wait_for_clangd_index is the second gate. Never raises; the caller decides.
    """
    prompt = ("Call find_symbol for the symbol '%s' with relative_path '%s'. "
              "Reply with only the word READY, or the word FAILED and the error."
              % (gate["scoped_symbol"], gate["scoped_path"]))
    log = []
    for i in range(1, attempts + 1):
        started = time.time()
        rec = run_one(prompt, model, 420, cwd=cwd)
        took = round(time.time() - started, 1)
        used = sum(v for k, v in (rec.get("calls_by_tool") or {}).items() if "serena" in k)
        errs = rec.get("tool_errors") or []
        ok = used > 0 and not errs
        log.append({"attempt": i, "seconds": took, "serena_calls": used,
                    "tool_errors": errs[:2], "answer": (rec.get("answer") or "")[:120]})
        print("     serena probe %d: %ss, %d serena call(s)%s" % (i, took, used, "" if ok else "  <- NOT READY"))
        if ok:
            return {"ready": True, "attempts": i, "seconds": took, "log": log}
        if i < attempts:
            time.sleep(20 * i)
    return {"ready": False, "attempts": attempts, "log": log}


def wait_for_clangd_index(url, gate, timeout_s=900, poll_s=20):
    """Block until find_symbol_indexed answers from a LOADED clangd index.

    clangd loads nothing until the first file is opened, so for minutes after a restart
    find_symbol_indexed returns [] in 0.1s - fast, well-formed and empty, which every question would
    read as "no such symbol". So: open one file with get_diagnostics_for_file (which cannot come from
    Serena's cache), then poll until the gate's symbol resolves to its header. Talks to the server over
    MCP directly: this is a property of the server, and polling through model turns costs tokens for
    nothing. Never raises; the caller decides.
    """
    import urllib.request

    hdr = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}

    def post(payload, session=None, timeout=70):
        h = dict(hdr)
        if session:
            h["mcp-session-id"] = session
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=h, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            sid = r.headers.get("mcp-session-id")
            body = r.read().decode("utf-8", "replace")
        if "data:" in body:
            datas = [l[5:].strip() for l in body.splitlines() if l.startswith("data:")]
            body = datas[-1] if datas else "{}"
        return sid, (json.loads(body) if body.strip() else {})

    def tool(sid, name, args):
        _, res = post({"jsonrpc": "2.0", "id": int(time.time() * 1000) % 10**9, "method": "tools/call",
                       "params": {"name": name, "arguments": args}}, session=sid)
        r = res.get("result") or {}
        return "".join(c.get("text", "") for c in r.get("content", []) if c.get("type") == "text")

    want_name = gate["index_symbol"]
    want_suffix = gate["index_path_suffix"].replace("\\", "/")
    started = time.time()
    log = []
    try:
        sid, _ = post({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "run_bench-clangd-gate", "version": "1"}}})
        post({"jsonrpc": "2.0", "method": "notifications/initialized"}, session=sid)
        t = time.time()
        diag = tool(sid, "get_diagnostics_for_file", {"relative_path": gate["open_file"]})
        log.append({"step": "open file", "seconds": round(time.time() - t, 1), "reply": diag[:120]})
        while time.time() - started < timeout_s:
            text = tool(sid, "find_symbol_indexed", {"query": want_name, "max_matches": 50})
            try:
                hits = [m for m in json.loads(text) if m.get("name") == want_name
                        and (m.get("relative_path") or "").replace("\\", "/").endswith(want_suffix)]
            except (ValueError, TypeError, AttributeError):
                hits = []
            waited = round(time.time() - started, 1)
            if hits:
                print("     clangd index ready after %ss" % waited)
                return {"ready": True, "seconds": waited, "log": log}
            log.append({"step": "poll", "at": waited, "reply": text[:80]})
            print("     clangd index not loaded yet (%ss) - find_symbol_indexed would answer empty" % waited)
            time.sleep(poll_s)
    except Exception as e:
        log.append({"step": "error", "error": repr(e)[:200]})
    return {"ready": False, "seconds": round(time.time() - started, 1), "log": log}


def clangd_pids():
    """The set of running clangd PIDs, or None where there is no way to list them.

    tasklist on Windows, pgrep elsewhere, rather than psutil, so the harness stays standard-library only.
    None means "can't tell" and turns the watch off; an empty set means "none running", which is a real
    answer and a change worth recording if one was running before.
    """
    try:
        if os.name == "nt":
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq clangd.exe", "/FO", "CSV", "/NH"],
                                 capture_output=True, text=True, timeout=30).stdout
            pids = set()
            for line in out.splitlines():
                parts = [p.strip('"') for p in line.split('","')]
                if len(parts) > 1 and parts[0].lower() == "clangd.exe" and parts[1].isdigit():
                    pids.add(int(parts[1]))
            return pids
        out = subprocess.run(["pgrep", "-x", "clangd"], capture_output=True, text=True, timeout=30).stdout
        return {int(p) for p in out.split() if p.isdigit()}
    except (OSError, subprocess.SubprocessError):
        return None


def isolation_proof(arm, model, artefact_dir="Docs/AgentMemory", cwd=None):
    """Ask a session to read the things the baseline must not reach, and record what happened.

    The spec asks for this to be proven rather than assumed, and recorded in the results.

    `artefact_dir` is the path the baseline is supposed to be unable to see. Pass the one belonging
    to the project under test, because probing a directory that does not exist on this tree proves
    only that it does not exist.
    """
    probe = ("Try to read the file CLAUDE.md in the current directory, and then try to list the "
             "directory %s. Report exactly what happened for each: whether "
             "it exists and whether you could read it. Do not guess at contents." % artefact_dir)
    rec = run_one(probe, model, 300, cwd=cwd)
    rec["probe"] = probe
    rec["arm"] = arm
    rec["cwd"] = cwd or TREE
    return rec


# Answers no agent produced. Matched case-insensitively against a SHORT `answer` on an is_error row,
# because the platform's refusal replaces the answer rather than appearing inside one.
PLATFORM_REFUSALS = (
    "session limit",
    "usage limit",
    "rate limit",
    "quota",
    "credit balance",
    "authentication_error",
    "invalid api key",
    "please run /login",
)


def is_void_row(rec):
    """True when a row records something no agent said, so it must not count as work done.

    When an account hits its session limit mid-run, every remaining question comes back in seconds
    with a populated `answer` like "You've hit your session limit". Nothing in the row says it is
    void, so a judge reads it as a short, confident, wrong answer - and a baseline arm that loses half
    its questions this way makes the other arm look far better than it is.

    Two shapes, and the second is the one that hides:
      * NOTHING RAN - is_error with no tool calls, no tokens and at most one turn.
      * THE ANSWER WAS REPLACED - the arm ran, sometimes expensively, and the platform overwrote its
        answer with a refusal. Expensive rows look real, which is exactly why they need catching.

    A genuine failure is NOT void. A timeout that burned its whole budget and recorded no answer is a
    measurement of the arm, and a resume that re-asked it would quietly replace a recorded failure
    with a second attempt at the hardest question in the set.
    """
    if not rec.get("is_error"):
        return False

    did_nothing = (
        not sum((rec.get("calls_by_tool") or {}).values())
        and not (rec.get("tokens_total_in") or 0)
        and not (rec.get("tokens_output") or 0)
        and (rec.get("turns") or 0) <= 1
    )
    if did_nothing:
        return True

    answer = str(rec.get("answer") or "")
    if 0 < len(answer) <= 400:
        low = answer.lower()
        if any(p in low for p in PLATFORM_REFUSALS):
            return True
    return False


def pid_alive(pid):
    """True when a process with this PID is running. Never signals it.

    Deliberately not os.kill(pid, 0): on Windows os.kill with any signal but CTRL_C/CTRL_BREAK calls
    TerminateProcess, so the liveness probe would kill the run it was asking about.
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            # Access denied means it exists and belongs to someone else - treat as alive.
            return ctypes.get_last_error() == 5
        try:
            code = wintypes.DWORD()
            if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return True
            return code.value == STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def acquire_results_lock(results_path, break_stale=False):
    """Take the one-writer lock for results_path, or exit naming whoever holds it.

    A lock whose holder is no longer running is STALE. It is broken only with --break-stale-lock,
    never silently: a stale lock means a run died, and its results file needs reading before another
    run writes into it. A live holder is never broken, flag or not.
    """
    import atexit
    lock_path = results_path + ".lock"
    me = {"pid": os.getpid(), "started": datetime.datetime.now().isoformat(timespec="seconds"),
          "argv": sys.argv}
    for attempt in (1, 2):
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                holder = json.load(io.open(lock_path, encoding="utf-8"))
            except Exception:
                holder = {}
            alive = pid_alive(holder.get("pid"))
            who = "PID %s, started %s: %s" % (holder.get("pid", "?"), holder.get("started", "?"),
                                              " ".join(holder.get("argv") or []) or "(unreadable lock)")
            if alive:
                sys.exit("REFUSING: another run is writing %s\n  holder: %s\n  Two runs into one "
                         "results file score every question they share twice. Wait for it, or stop it."
                         % (results_path, who))
            if not break_stale or attempt == 2:
                sys.exit("REFUSING: %s has a STALE lock - its holder is no longer running.\n"
                         "  holder: %s\n  A run died mid-write. Read the results file before adding "
                         "to it, then rerun with --break-stale-lock." % (results_path, who))
            print("!! breaking stale lock on %s (holder %s)" % (results_path, who), file=sys.stderr)
            os.remove(lock_path)
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(me, f)

        def release():
            try:
                cur = json.load(io.open(lock_path, encoding="utf-8"))
                if cur.get("pid") == me["pid"]:
                    os.remove(lock_path)
            except Exception:
                pass
        atexit.register(release)
        return lock_path


def duplicate_ids(results_path):
    """Ids with more than one non-void row. Void rows are the platform's, not a measurement."""
    seen = {}
    if not os.path.exists(results_path):
        return {}
    for line in io.open(results_path, encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if is_void_row(r):
            continue
        seen[r.get("id")] = seen.get(r.get("id"), 0) + 1
    return {i: n for i, n in seen.items() if n > 1}


def split_void_rows(results_path, void_path, dry_run=False):
    """Read a results file for a resume, and move its void rows out of it.

    Returns (done, void_ids, unclassified_ids). done is every id with a row that counts as recorded.

    The void rows have to LEAVE the file, not just be skipped when working out what to re-ask. The
    re-asked answer is appended to this same file, and the scorer and compare_arms.py count every row,
    so a void row left behind scores its question twice - once as the refusal, which a judge reads as
    a short, confident, wrong answer. They're moved to void_path rather than deleted, because they are
    the record of what happened. A line that isn't JSON is kept exactly as it was: it isn't ours to judge.

    With dry_run nothing is written, because a dry run records no answers to replace them with.
    """
    done, void, unclassified = set(), [], []
    kept_lines, void_lines = [], []
    for line in io.open(results_path, encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            kept_lines.append(line)
            continue
        if is_void_row(r):
            void.append(r["id"])
            void_lines.append(line)
            continue
        kept_lines.append(line)
        if r.get("is_error"):
            unclassified.append(r["id"])
        done.add(r["id"])

    if void_lines and not dry_run:
        def write(path, lines):
            with io.open(path, "w", encoding="utf-8", newline="\n") as f:
                for l in lines:
                    f.write(l if l.endswith("\n") else l + "\n")
        write(void_path, void_lines)
        # Written aside and swapped in, so a crash part way through leaves the original file whole.
        tmp = results_path + ".tmp"
        write(tmp, kept_lines)
        os.replace(tmp, results_path)
    return done, void, unclassified


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True, choices=["baseline", "layers"])
    ap.add_argument("--set", dest="qset", default="full", choices=["smoke", "full"])
    ap.add_argument("--runset", help="explicit runset json, overrides --set; results are named "
                                     "after it so probes never mix with the frozen set")
    ap.add_argument("--model", default="opus")
    ap.add_argument("--timeout", type=int, default=900, help="per-question seconds")
    ap.add_argument("--resume", action="store_true", help="skip ids already in the results file")
    ap.add_argument("--dry-run", action="store_true", help="apply, verify, prove, restore. No questions")
    ap.add_argument("--break-stale-lock", action="store_true",
                    help="remove a results lock whose holder is no longer running. Never breaks a live one")
    ap.add_argument("--isolation", default="move-aside", choices=["move-aside", "room"],
                    help="move-aside holds the layers out of the tree for the baseline arm; room "
                         "runs that arm in a clean root built by Build-BaselineRoot.ps1. The answer "
                         "keys move in both arms either way")
    ap.add_argument("--no-serena-gate", action="store_true",
                    help="skip the Serena warm-up and clangd-index gate for an arm that has Serena. "
                         "Only for a tree without the find_symbol_indexed patch; the run's meta records it")
    ap.add_argument("--room", default=ROOM,
                    help="the built room, for --isolation room. Default beside the tree")
    ap.add_argument("--artefact-dir", default="Docs/AgentMemory",
                    help="the artefact directory the baseline must not be able to see. Probing a "
                         "path that does not exist on this tree proves nothing, so point this at "
                         "the project under test")
    args = ap.parse_args()

    global ARMS, ARM, MCP_CONFIG_PATH
    ARMS = load_arms()
    ARM = args.arm
    MCP_CONFIG_PATH = stage_mcp_config(args.arm)

    if args.runset:
        runset_path = args.runset if os.path.isabs(args.runset) else os.path.join(TREE, args.runset)
        tag = os.path.splitext(os.path.basename(runset_path))[0].replace("runset-", "")
    else:
        runset_name = "runset-smoke.json" if args.qset == "smoke" else "runset-full.json"
        runset_path = os.path.join(TREE, "bench", runset_name)
        tag = args.qset
    if not os.path.exists(runset_path):
        sys.exit("Missing %s.\nBuild it first: python bench/tools/make_runset.py" % runset_path)
    questions = json.load(io.open(runset_path, encoding="utf-8"))

    if not os.path.exists(HOLDING):
        os.makedirs(HOLDING)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    results_path = os.path.join(HOLDING, "results-%s-%s.jsonl" % (args.arm, tag))
    meta_path = os.path.join(HOLDING, "meta-%s-%s-%s.json" % (args.arm, tag, stamp))

    # Before anything reads or rewrites the results file: the resume split below replaces it.
    lock_path = acquire_results_lock(results_path, break_stale=args.break_stale_lock)
    print("results lock: %s" % lock_path)

    # The lock stops two runs writing at once. It does not stop a second run appending to a finished
    # one, and the file lives in HOLDING, which outlasts every run, so that is the easier mistake.
    if not args.resume and not args.dry_run and os.path.exists(results_path) \
            and os.path.getsize(results_path) > 0:
        n = sum(1 for l in io.open(results_path, encoding="utf-8") if l.strip())
        sys.exit("REFUSING: %s already holds %d row(s) from an earlier run, and a fresh run appends.\n"
                 "  --resume to continue that run, or move the file aside to start clean. Appending a "
                 "full run to an old file scores every question it shares twice."
                 % (results_path, n))

    done = set()
    if args.resume and os.path.exists(results_path):
        void_path = os.path.join(HOLDING, "results-%s-%s.void-%s.jsonl" % (args.arm, tag, stamp))
        done, void, unclassified = split_void_rows(results_path, void_path, dry_run=args.dry_run)
        print("resume: %d already recorded" % len(done))
        if void:
            uniq = sorted(set(void))
            print("!! resume: %d row(s) covering %d question(s) are VOID - the platform refused or "
                  "replaced the answer - so they are NOT counted as recorded and WILL be re-asked."
                  % (len(void), len(uniq)), file=sys.stderr)
            print("!! that is what a session limit looks like in a results file: a populated "
                  "`answer` no agent produced. Ids: %s"
                  % (", ".join(uniq[:12]) + (" ..." if len(uniq) > 12 else "")), file=sys.stderr)
            if args.dry_run:
                print("!! dry run: the void rows are left in place. A real resume moves them to %s"
                      % void_path, file=sys.stderr)
            else:
                print("!! moved those rows out of the results file into %s, so the re-asked answers "
                      "will be the only rows for those ids" % void_path, file=sys.stderr)
        if unclassified:
            uniq = sorted(set(unclassified))
            print("!! resume: %d error row(s) are being KEPT as recorded because they do not match a "
                  "known refusal: %s. Read one before trusting this resume - a refusal wearing a new "
                  "message would be scored as an answer."
                  % (len(uniq), ", ".join(uniq[:12]) + (" ..." if len(uniq) > 12 else "")),
                  file=sys.stderr)

    # In room mode the baseline arm runs in the room and the tree keeps its layers, so the paths to
    # hold are the ones BOTH arms hold - the answer keys - which is what `-Arm layers` means to the
    # isolation script. The arm recorded in the results is still the real one.
    in_room = args.isolation == "room" and args.arm == "baseline"
    run_cwd = args.room if in_room else TREE
    hold_arm = "layers" if in_room else args.arm

    if in_room:
        if not os.path.isdir(args.room):
            sys.exit("No room at %s.\nBuild it first:\n"
                     "  powershell -File \"%s\" -Mode Build -TreeRoot \"%s\""
                     % (args.room, ROOM_BUILDER, TREE))
        # A stale room measures a codebase that no longer exists, which is this design's own failure
        # mode. Verify writes nothing and takes seconds, so there is no reason to skip it.
        print("=== verifying the room is not stale ===")
        vcode = subprocess.call(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                                 "-File", ROOM_BUILDER, "-Mode", "Verify",
                                 "-TreeRoot", TREE, "-Root", args.room])
        if vcode != 0:
            sys.exit("The room is stale. Rebuild it before measuring.")
        print("  room: %s" % args.room)

    staged = stage_isolation()
    print("staged isolation tool -> %s" % staged)
    print("  recovery, if this process dies: powershell -File \"%s\" -Mode Restore" % staged)

    code, out = ps("-Mode", "Status")
    if "APPLIED" in out:
        print(out.rstrip())
        sys.exit("Isolation is already applied from an earlier run. Restore first (command above).")

    print("=== applying isolation, arm=%s (holding %s paths) ===" % (args.arm, hold_arm))
    code, out = ps("-Mode", "Apply", "-Arm", hold_arm)
    print(out.rstrip())
    if code != 0:
        sys.exit("Apply failed. Nothing was run.")

    proof = None
    try:
        code, out = ps("-Mode", "Verify", "-Arm", hold_arm)
        print(out.rstrip())
        if code != 0:
            raise RuntimeError("Isolation verification failed - refusing to run.")

        print("=== leak scan ===")
        leaks = leak_scan(hold_arm)
        if leaks:
            for kind, rel in leaks[:25]:
                print("  LEAK [%s] %s" % (kind, rel))
            raise RuntimeError("Leak scan found %d reachable copies - refusing to run." % len(leaks))
        print("  clean")

        print("=== isolation proof session ===")
        proof = isolation_proof(args.arm, args.model, args.artefact_dir, cwd=run_cwd)
        # The console encoding on Windows is not UTF-8, and model answers contain en dashes and
        # similar. An unguarded print raises UnicodeEncodeError AFTER the proof has run, which
        # aborts before the meta file is written and loses the proof record.
        safe = str(proof.get("answer"))[:300].encode("ascii", "replace").decode("ascii")
        print("  answer: %s" % safe)

        servers = ARMS[args.arm].get("mcp_servers") or {}
        if any(c.get("type") == "stdio" for c in servers.values()):
            print("=== probing the arm's stdio MCP servers, after isolation ===")
            mcp_probe = probe_stdio_mcp_servers(args.arm, run_cwd)
            dead = [n for n, r in mcp_probe.items() if not r.get("ok")]
            if dead:
                raise RuntimeError("MCP server(s) %s did not answer after isolation. The arm is defined as "
                                   "having them; a run without them measures a different stack." % ", ".join(dead))

        if "serena" in servers and args.no_serena_gate:
            serena_state = {"ready": None, "reason": "--no-serena-gate"}
            print("  serena gate skipped by --no-serena-gate")
        elif "serena" in servers:
            gate = ARMS[args.arm].get("serena_gate")
            if not gate:
                raise RuntimeError("The %s arm has Serena but %s has no serena_gate. Add one, or pass "
                                   "--no-serena-gate knowingly." % (args.arm, ARMS_PATH))
            print("=== warming Serena ===")
            serena_state = warm_up_serena(args.model, gate, run_cwd)
            if not serena_state.get("ready"):
                raise RuntimeError("Serena did not answer. This arm is defined as having it, so the run "
                                   "would measure something else.")
            if servers["serena"].get("type") == "http":
                print("=== waiting for clangd's index ===")
                serena_state["clangd_index"] = wait_for_clangd_index(servers["serena"]["url"], gate)
                if not serena_state["clangd_index"].get("ready"):
                    raise RuntimeError("clangd's index did not load. find_symbol_indexed would answer empty, "
                                       "and the arm would be scored on 'no such symbol'.")
        else:
            serena_state = {"ready": None, "reason": "arm has no serena"}

        if args.dry_run:
            print("dry run: skipping questions")
        else:
            todo = [q for q in questions if q["id"] not in done]
            print("=== %d questions, arm=%s, model=%s ===" % (len(todo), args.arm, args.model))
            # CLANGD MUST BE THE SAME PROCESS AFTER A QUESTION AS BEFORE IT. The index gate only checks
            # at the start. On our tree clangd died twice in one afternoon - a find_symbol walk left
            # running on the server crashed it - and nothing noticed until the next run. A replacement
            # clangd answers find_symbol_indexed with a fast, well-formed [] for minutes, which every
            # question reads as "no such symbol". So a change is recorded on the question it happened
            # during, and the index is re-awaited before the next one.
            serena_cfg = servers.get("serena") or {}
            watch_clangd = bool(serena_cfg) and not args.no_serena_gate
            clangd_seen = clangd_pids() if watch_clangd else None
            if watch_clangd and clangd_seen is None:
                print("  clangd watch off: cannot list processes on this machine", file=sys.stderr)
                watch_clangd = False
            for n, q in enumerate(todo, 1):
                qtext = q["question"]
                print("[%d/%d] %s (%s) ..." % (n, len(todo), q["id"], q["group"]), end="", flush=True)
                rec = run_one(qtext, args.model, args.timeout, cwd=run_cwd)
                rec.update({
                    "id": q["id"],
                    "group": q["group"],
                    "project": q.get("project", "-"),
                    "arm": args.arm,
                    "model": args.model,
                    "question": qtext,
                    "key": q.get("key"),
                    "expected_route": q.get("route"),
                    "recorded_at": datetime.datetime.now().isoformat(timespec="seconds"),
                })
                if watch_clangd:
                    now = clangd_pids()
                    if now is not None and now != clangd_seen:
                        rec["clangd_changed"] = {"before": sorted(clangd_seen), "after": sorted(now)}
                        print("\n!! clangd changed during %s: %s -> %s. Its answer may rest on an empty "
                              "index; waiting for the index before the next question."
                              % (q["id"], sorted(clangd_seen), sorted(now)), file=sys.stderr)
                        if serena_cfg.get("type") == "http":
                            rec["clangd_index_after_change"] = wait_for_clangd_index(
                                serena_cfg["url"], ARMS[args.arm]["serena_gate"])
                        clangd_seen = clangd_pids() or set()
                with io.open(results_path, "a", encoding="utf-8", newline="\n") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                # Written first, so the question that saw the change keeps its record either way.
                if rec.get("clangd_changed") and "clangd_index_after_change" in rec and \
                        not rec["clangd_index_after_change"].get("ready"):
                    raise RuntimeError("clangd's index did not come back after the change during %s. Every "
                                       "later question would get empty find_symbol_indexed results." % q["id"])
                print(" %ss, %d turns, %d bytes, %d tok%s" % (
                    rec.get("wall_seconds"), rec.get("turns", 0), rec.get("retrieval_bytes", 0),
                    rec.get("tokens_total_in", 0),
                    " ERROR" if rec.get("is_error") else ""))
    finally:
        print("=== restoring ===")
        code, out = ps("-Mode", "Restore")
        print(out.rstrip())
        if code != 0:
            print("!! RESTORE FAILED - resolve by hand before any other work in this tree", file=sys.stderr)
        else:
            # THE STAGED SCRIPT MUST NOT OUTLIVE THE RUN. `ps()` prefers the staged copy, because
            # during a run `bench/` is moved aside and the tree copy does not exist. Left behind
            # afterwards it is still preferred and now stale, so the next run is configured by the
            # previous run's copy of the script - measured on our tree at 45 held paths against the
            # tree's 47, with every check still reporting green. Deleting it here means that between
            # runs there is no staged copy and the fallback reads the tree.
            #
            # Only after a SUCCESSFUL restore: if the restore failed, this file is the recovery route
            # printed at startup and has to survive.
            try:
                if os.path.exists(ISOLATION_RUN):
                    os.remove(ISOLATION_RUN)
                    print("  removed the staged isolation copy (stale the moment this exits)")
            except OSError as e:
                print("!! could not remove %s: %s" % (ISOLATION_RUN, e), file=sys.stderr)

    meta = {
        "arm": args.arm, "set": args.qset, "model": args.model,
        # Recorded rather than inferred. An arm's isolation method and working directory are the two
        # things a later session cannot recover from the answers.
        "isolation": args.isolation, "cwd": run_cwd,
        "mcp_config": MCP_CONFIG_PATH,
        "mcp_servers": sorted((ARMS[args.arm].get("mcp_servers") or {}).keys()),
        "allowed_mcp_tools": list(ARMS[args.arm].get("allowed_mcp_tools") or []),
        "floor_tokens": FLOOR_TOKENS,
        # What the arm could actually call, recorded rather than inferred. Without this the only way
        # to tell what an arm had is to look at which tools happen to appear in its results, which is
        # how a baseline arm went 160 questions with Write available before anyone noticed.
        "tools": {"builtin": list(BUILTIN_TOOLS), "disallowed": list(DISALLOWED_TOOLS)},
        "started": stamp,
        "isolation_proof": proof,
        "questions": len(questions),
    }
    with io.open(meta_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    runs_dir = os.path.join(TREE, "bench", "runs")
    if not os.path.exists(runs_dir):
        os.makedirs(runs_dir)
    # NEVER copy a results file this run did not write. HOLDING accumulates results across runs, so on
    # a --dry-run, which writes none, copying results_path would copy the PREVIOUS run's file into
    # bench/runs/ under a clean name, where the scorer would find it.
    dupes = {} if args.dry_run else duplicate_ids(results_path)
    if args.dry_run:
        print("dry run: not copying results (none were written)")
        copy_list = (meta_path,)
    else:
        copy_list = (results_path, meta_path)

    for src in copy_list:
        if os.path.exists(src):
            name = os.path.basename(src)
            # A file with a question recorded twice is still the record, so it is copied - but under
            # a name the scorer does not look for, so nobody scores it by accident.
            if src == results_path and dupes:
                name = name[:-len(".jsonl")] + ".DUPLICATE-IDS.jsonl"
            dst = os.path.join(runs_dir, name)
            with io.open(src, encoding="utf-8") as a, io.open(dst, "w", encoding="utf-8", newline="\n") as b:
                b.write(a.read())
            print("copied -> bench/runs/%s" % name)

    if dupes:
        shown = ", ".join("%s x%d" % (i, n) for i, n in sorted(dupes.items())[:15])
        print("!! %d question(s) have more than one real row in %s: %s%s\n"
              "!! Copied as .DUPLICATE-IDS.jsonl so it cannot be scored as it stands. Keep one row per "
              "id, then rename it." % (len(dupes), results_path, shown,
                                        " ..." if len(dupes) > 15 else ""), file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
