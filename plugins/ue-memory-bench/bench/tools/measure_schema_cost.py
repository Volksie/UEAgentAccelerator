"""What would the engine-api tool schemas cost if they were resident instead of deferred?

THE QUESTION. The harness defers MCP tool schemas: only the tool NAMES load into each turn, and the
full schema arrives when a session calls ToolSearch. Deferral was measured at **102 tokens a turn**
for the engine-api server (bench/tools/measure_floor.py, 2026-09-10, replacing an inferred 4,781 that
was wrong by 47x). What was never measured is the other side: what the same schemas cost if they were
resident, against the discovery turns deferral spends.

WHAT THIS MEASURES. The server's own `tools/list` response, which is exactly the payload that would
be resident, so the size is a fact rather than an estimate. The token figure is derived from bytes and
IS labelled as derived - this tree's rule is to say so or go and measure it, and a tokenizer is not
available here. The bytes are the measurement; the tokens are arithmetic on it.

WHAT IT DOES NOT SETTLE. Whether resident is cheaper depends on how many discovery turns a run
actually spends, which is a property of the question set. That number is in the run data
(`calls_by_tool` counts ToolSearch per question), not here, and the report prints it alongside.

It works on any MCP server that speaks stdio, not just ours, so point it at whatever you are thinking
of adding to an agent's surface:

    python bench/tools/measure_schema_cost.py
        --server path/to/server.py
        --results baseline=bench/runs/results-baseline.jsonl
        --results layers=bench/runs/results-layers.jsonl
"""
import argparse, io, json, os, subprocess, sys, collections

# Bytes per token for JSON schema text. Prose measures about 2.4 bytes a token on our documents, but
# schema JSON is punctuation-dense and tokenizes worse, so the range is given rather than a point.
BYTES_PER_TOKEN = (2.4, 3.2)


def rpc(proc, method, params=None, mid=1):
    msg = {"jsonrpc": "2.0", "id": mid, "method": method}
    if params is not None:
        msg["params"] = params
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()
    while True:
        line = proc.stdout.readline()
        if not line:
            return None
        try:
            doc = json.loads(line)
        except ValueError:
            continue
        if doc.get("id") == mid:
            return doc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", required=True,
                    help="stdio MCP server to measure, run as `python <server>`")
    # The measured deferred cost per turn, from measure_floor.py. Pass your own: it is a property of
    # your harness, and the point of this script is not to inherit somebody else's number.
    ap.add_argument("--deferred-tokens", type=int, default=102,
                    help="MEASURED per-turn cost of the deferred names, from measure_floor.py")
    ap.add_argument("--results", action="append", default=[], metavar="ARM=PATH",
                    help="a run's results file, once per arm; repeatable")
    args = ap.parse_args()
    SERVER = args.server

    proc = subprocess.Popen([sys.executable, SERVER], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1)
    try:
        rpc(proc, "initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                 "clientInfo": {"name": "measure_schema_cost", "version": "1"}}, 1)
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        proc.stdin.flush()
        resp = rpc(proc, "tools/list", {}, 2)
    finally:
        try:
            proc.terminate()
        except Exception:
            pass

    if not resp or "result" not in resp:
        sys.exit("no tools/list response from %s" % SERVER)

    tools = resp["result"]["tools"]
    print("engine-api exposes %d tools\n" % len(tools))

    total_full = 0
    total_names = 0
    print("%-32s %9s %9s" % ("tool", "schema B", "name B"))
    print("%-32s %9s %9s" % ("-" * 32, "-" * 9, "-" * 9))
    for t in sorted(tools, key=lambda x: x["name"]):
        full = len(json.dumps(t, separators=(",", ":")))
        name = len(t["name"])
        total_full += full
        total_names += name
        print("%-32s %9s %9s" % (t["name"], format(full, ","), format(name, ",")))

    print("%-32s %9s %9s" % ("TOTAL", format(total_full, ","), format(total_names, ",")))

    lo, hi = BYTES_PER_TOKEN
    print("\nResident cost of the full schemas, DERIVED from %s bytes at %.1f-%.1f bytes/token:"
          % (format(total_full, ","), lo, hi))
    print("   roughly %s to %s tokens a turn"
          % (format(int(total_full / hi), ","), format(int(total_full / lo), ",")))
    print("Deferred cost, MEASURED by measure_floor.py: %d tokens a turn." % args.deferred_tokens)

    # THE COMPARISON THAT MATTERS, and the one the first version of this script got wrong.
    #
    # Comparing "739-986 resident tokens a turn" against "102 deferred tokens a turn" makes deferral
    # look 7-10x better and is the wrong comparison, because it prices only one side. A ToolSearch
    # call is a TOOL CALL, and every tool call costs an extra TURN - and a turn on this harness costs
    # the whole standing context again, about 44,000 tokens, not 102. Thirty discovery turns is
    # therefore over a million tokens that deferral spends and residence does not.
    #
    # So model both arms end to end: deferred is what the run actually cost; resident is the same run
    # with the discovery turns removed and the schema added to every remaining turn.
    print("\n" + "=" * 78)
    print("End-to-end, per arm. A discovery turn costs a whole turn, not %d tokens."
          % args.deferred_tokens)
    print("=" * 78)
    for spec in args.results:
        arm, _, p = spec.partition("=")
        if not p or not os.path.exists(p):
            print("\n%s: no results file at %s, skipped" % (arm, p))
            continue
        turns = tokens = searches = qs = 0
        for line in io.open(p, encoding="utf-8"):
            r = json.loads(line)
            qs += 1
            turns += (r.get("turns") or (r.get("calls") or 0) + 1)
            tokens += r.get("tokens_total_in") or 0
            searches += (r.get("calls_by_tool") or {}).get("ToolSearch", 0)

        # Strip the measured deferred cost to get a per-turn base with no MCP schema in it at all.
        base_per_turn = (tokens - args.deferred_tokens * turns) / float(turns)
        resident_turns = turns - searches
        res_lo = int(resident_turns * (base_per_turn + total_full / hi))
        res_hi = int(resident_turns * (base_per_turn + total_full / lo))

        print("\n%s  -  %d questions, %d turns, %d ToolSearch calls" % (arm.upper(), qs, turns, searches))
        print("   deferred, MEASURED       %s tokens over %d turns" % (format(tokens, ","), turns))
        print("   resident, MODELLED       %s to %s tokens over %d turns"
              % (format(res_lo, ","), format(res_hi, ","), resident_turns))
        delta_lo, delta_hi = tokens - res_hi, tokens - res_lo
        if delta_lo > 0 and delta_hi > 0:
            print("   -> RESIDENT is cheaper by %s to %s tokens (%.1f-%.1f%%)"
                  % (format(delta_lo, ","), format(delta_hi, ","),
                     100.0 * delta_lo / tokens, 100.0 * delta_hi / tokens))
        elif delta_lo < 0 and delta_hi < 0:
            print("   -> DEFERRAL is cheaper by %s to %s tokens (%.1f-%.1f%%)"
                  % (format(-delta_hi, ","), format(-delta_lo, ","),
                     100.0 * -delta_hi / tokens, 100.0 * -delta_lo / tokens))
        else:
            print("   -> a wash: the range spans zero")

    print("""
The answer is not a constant - it is set by how much the arm USES the server, because that is what
sets the discovery-turn count. An arm that never reaches for the tools pays residence on every turn
for nothing; an arm that reaches often pays a whole turn each time it does. Both sides scale, in
opposite directions, so this has to be recomputed against the question set in hand rather than
settled once. Recompute it whenever the set changes: a group of questions that reaches for the server
often moves the answer on its own.""")


if __name__ == "__main__":
    main()
