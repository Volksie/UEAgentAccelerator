"""PostToolUse hook: record when a file the engine-api store indexes was edited.

Ported from the hook wiring in code-review-graph (MIT, tirth8205/code-review-graph). Two things are
taken from it. First the matcher: theirs is `Write|Edit|Bash`, **including Bash**, because a `sed`
or a redirect edits a file just as thoroughly as the Edit tool and a `Write|Edit` matcher never
sees it. Second draining stdin, which their issue #493 is about - a hook that exits without reading
the payload gives the client a BrokenPipeError on a large one.

What is *not* taken from it is the action. Theirs re-parses the changed files and updates the graph
in place. Nothing here can do that: these layers come out of UHT and the commandlets, so they need
a build, and pretending otherwise would write a stale graph that claims to be fresh. The honest
cheap thing is a timestamp, which lets `uncertainty.freshness` say "the store predates your last
edit" instead of silently answering from it.

Filtering on extension is a departure too. CRG stamps on any edit; this stamps only for the file
kinds the store indexes, so editing a design document does not make every class lookup announce
itself as stale. A false staleness warning on every call is worse than none: it gets tuned out, and
then the true one is tuned out with it.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import sys
from pathlib import Path

# What the store is built from. A .uasset matters because bp_edges comes from the Blueprint walk;
# an .ini matters because module and plugin enablement is read from one. Markdown deliberately
# absent - the artefact layers are not this store.
INDEXED = {".h", ".hpp", ".inl", ".cpp", ".cs", ".uasset", ".ini", ".uproject", ".uplugin", ".build"}

STAMP = Path(os.environ.get("ENGINE_API_EDIT_STAMP",
                            Path(__file__).resolve().parent / ".edit-stamp"))


def _paths(payload: dict) -> list[str]:
    """Every file path this tool call plausibly touched.

    Write and Edit name their target. Bash does not, so its whole command line is scanned for
    anything with an indexed extension - crude, and deliberately biased towards a false positive:
    an unnecessary staleness note costs about 30 tokens, a missed one costs a wrong answer stated
    with confidence.
    """
    tool_input = payload.get("tool_input") or {}
    direct = [tool_input.get(k) for k in ("file_path", "path", "notebook_path")]
    found = [p for p in direct if isinstance(p, str) and p]
    command = tool_input.get("command")
    if isinstance(command, str):
        found.extend(tok.strip("'\"`,;()") for tok in command.split())
    return found


def main() -> int:
    # Drain stdin first and unconditionally: everything below is best-effort, and a hook that
    # raises before reading the payload breaks the pipe for the client.
    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return 0
    if not isinstance(payload, dict):
        return 0

    for path in _paths(payload):
        if Path(path).suffix.lower() in INDEXED:
            stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            try:
                STAMP.write_text(stamp, encoding="utf-8")
            except OSError:
                pass  # A hook must never fail the tool call that triggered it.
            return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
