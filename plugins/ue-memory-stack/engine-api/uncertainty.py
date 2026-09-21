"""Honest uncertainty markers for empty and capped engine-api results.

Ported from `uncertainty.py` in code-review-graph (MIT, tirth8205/code-review-graph). The idea is
theirs; every gap below was measured against *this* store on 2026-09-18 and none of their code
survives, because the data model shares nothing with a tree-sitter graph.

**The problem.** A bare "no rows" is ambiguous. It can mean "the engine really has no such thing",
or it can mean "this store cannot see that thing": the class lives in a target we never exported,
the member is a plain virtual UHT never reports, or the Blueprint walk never reached that project.
A reading agent takes the first meaning, and then either states a wrong negative or abandons the
layer and greps 187,590 files. `mcp_server.py` already hand-wrote this prose for three tools; this
module makes it a table, covers the tools that had none, and stops the three from drifting apart.

**One sentence is a token saving, not a cost.** Thirty tokens of honesty displaces a multi-thousand
token fallback search, so the marker is hard-capped at `MAX_MARKER_CHARS` and is attached *only*
when a result set is empty or was capped. Every response that carries a full result stays
byte-identical to before this module existed.

The table is data, not scattered conditionals, for the reason the benchmark keeps rediscovering:
a caveat written inline next to one query gets copied to a second query where it is false. Each
`Gap` therefore names the tools it applies to, and nothing else sees it.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Callable, Optional

# Hard budget. Compact context is the whole point of the stack, so an advisory sentence that grows
# past this is a regression, not a feature. Measured: 200 chars is ~50 tokens.
MAX_MARKER_CHARS = 200

_REBUILD = "rebuild with scripts/Update-MemoryStack.ps1"


@dataclass(frozen=True)
class Gap:
    """One verified blind spot in this store, scoped to the tools it actually affects.

    `tools` is what keeps the note honest: a replication caveat belongs on `engine_api_members`
    and never on `engine_api_platform`, whose empty result has nothing to do with the runtime tier.
    `applies` may inspect the query context to suppress a note that is irrelevant to this call.
    """

    tools: frozenset[str]
    note: str
    applies: Optional[Callable[[dict], bool]] = None

    def matches(self, tool: str, ctx: dict) -> bool:
        if tool not in self.tools:
            return False
        return True if self.applies is None else bool(self.applies(ctx))


# ---------------------------------------------------------------------------
# Verified gaps
# ---------------------------------------------------------------------------
# Each entry below was checked against engine-api.db on 2026-09-18. Capabilities the store *does*
# have are deliberately absent: the full inheritance chain, interface lists, deprecation messages
# and declared console availability all work, and a note claiming otherwise would cost tokens to
# tell a reader something false.

GAPS: tuple[Gap, ...] = (
    # Ordered most specific first, because `marker` returns the first match and one precise sentence
    # beats a list the reader skims. The unconditional catch-alls are last.
    Gap(
        tools=frozenset({"engine_api_search", "engine_api_sql"}),
        note="Gameplay tags are declared in Config/DefaultGameplayTags.ini, never in C++, so no "
             "tier of this store has ever seen one.",
        applies=lambda ctx: "tag" in (ctx.get("query") or "").lower(),
    ),
    Gap(
        tools=frozenset({"engine_api_blast_radius"}),
        note="Some Blueprints with graphs were not walked in the projects named, so an empty result "
             "there is under-reporting, not proof of absence.",
        applies=lambda ctx: ctx.get("coverage_is_thin", False),
    ),
    # There is deliberately no "this class has no runtime-tier row" entry here. That is a
    # *field-level* qualifier - the class was found, one column of it is unknowable - and
    # `tool_class` prints it inline on every result, empty or not. Routing it through this table
    # made it fire on an empty member list, where it answered a question nobody had asked: the
    # reader wants to know why the function list is empty, and replication has nothing to say
    # about that.
    Gap(
        tools=frozenset({"engine_api_members"}),
        note="UHT reports UFUNCTIONs only. A plain virtual, a non-reflected member or anything "
             "behind a macro is invisible to this tier - use find_symbol_indexed instead.",
    ),
    Gap(
        tools=frozenset({"engine_api_search"}),
        note="FTS5 needs a trailing * for prefix matching, and kind='comment' searches comment "
             "bodies, which no other index holds.",
    ),
    Gap(
        tools=frozenset({"engine_api_class", "engine_api_members"}),
        note="Only Win64 targets were exported. A class reached solely from a console or Program "
             "target is absent here, not absent from the engine.",
    ),
)


# ---------------------------------------------------------------------------
# Blueprint walk coverage, read from the store rather than hardcoded
# ---------------------------------------------------------------------------
# bp_walk is parsed by build_api_db.py from the one fixed "Walk coverage" line the commandlet writes
# into each project's BlueprintCallers.md: total Blueprints, data-only, walked, with edges. A
# data-only Blueprint has no graphs by construction and cannot produce an edge, so the question an
# empty result raises is not "what share of Blueprints produced edges" (that read as 54% on Lyra and
# made every negative look weak) but "was every Blueprint that has graphs walked". One query,
# cached for the process lifetime.

_coverage_cache: Optional[dict[str, tuple[int, int, int, int]]] = None


def blueprint_coverage(con: sqlite3.Connection) -> dict[str, tuple[int, int, int, int]]:
    """Per project: (total, data_only, walked, with_edges). Empty when the artefacts predate the line."""
    global _coverage_cache
    if _coverage_cache is None:
        try:
            _coverage_cache = {
                r[0]: (r[1], r[2], r[3], r[4])
                for r in con.execute("SELECT project, total, data_only, walked, with_edges FROM bp_walk")
            }
        except sqlite3.Error:
            _coverage_cache = {}
    return _coverage_cache


def incomplete_walk_projects(con: sqlite3.Connection) -> list[str]:
    """Projects where some Blueprint with graphs was NOT walked, so an empty result is weaker there."""
    out = []
    for project, (total, data_only, walked, _with_edges) in blueprint_coverage(con).items():
        graph_bearing = total - data_only
        if walked < graph_bearing:
            out.append(f"{project} {walked}/{graph_bearing}")
    return out


def thin_coverage_projects(con: sqlite3.Connection) -> list[str]:
    """Kept for callers of the old name; the walk is either complete or it is not."""
    return incomplete_walk_projects(con)


def walk_statement(con: sqlite3.Connection) -> str:
    """One sentence per project stating exactly what the walk covered, for an empty result."""
    parts = []
    for project, (total, data_only, walked, with_edges) in sorted(blueprint_coverage(con).items()):
        graph_bearing = total - data_only
        if walked >= graph_bearing:
            parts.append(f"{project}: all {graph_bearing} Blueprints with graphs walked "
                         f"({data_only} data-only excluded, {with_edges} produced edges)")
        else:
            parts.append(f"{project}: {walked} of {graph_bearing} Blueprints with graphs walked")
    # A mixed set - one project regenerated with the coverage line, another not - is shape-identical
    # to a fresh one. Name the projects whose artefacts predate the line so the reader can tell.
    covered = set(blueprint_coverage(con))
    try:
        older = [r[0] for r in con.execute("SELECT DISTINCT project FROM bp_edges ORDER BY project")
                 if r[0] and r[0] not in covered]
    except sqlite3.Error:
        older = []
    if parts and older:
        parts.append(", ".join(older) + ": artefacts predate the coverage line (event and function "
                     "graphs only, no bind edges)")
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# The marker
# ---------------------------------------------------------------------------


def marker(tool: str, ctx: Optional[dict] = None) -> str:
    """The single most relevant caveat for an empty result, or "" when the store has no blind spot.

    First match wins: the table is ordered so the most specific gap for a tool comes first, and a
    reader gets one sentence rather than a list they will skim past.
    """
    ctx = ctx or {}
    for gap in GAPS:
        if gap.matches(tool, ctx):
            note = gap.note
            if "{" in note:
                # A note that cannot be filled must not take the response down with it: a missing
                # key means the caller passed a thinner context than this gap wants, which is a
                # reason to print the note plainly, not to raise out of a read-only query.
                try:
                    note = note.format(**{k: v for k, v in ctx.items() if isinstance(v, str)})
                except (KeyError, IndexError, ValueError):
                    pass
            note = " ".join(note.split())
            if len(note) > MAX_MARKER_CHARS:
                note = note[:MAX_MARKER_CHARS - 1].rstrip() + "…"
            return f"\n\n_Why this may be empty: {note}_"
    return ""


def freshness(con: sqlite3.Connection, edit_stamp: Optional[str] = None) -> str:
    """A note when the tree has been edited since the store was generated, else "".

    `edit_stamp` is the ISO timestamp of the most recent source edit, written by the PostToolUse
    hook in `.claude/settings.json`. Without the hook this is always "", which is the honest
    default: absence of a stamp is not evidence of freshness, but it is not evidence of staleness
    either, and inventing a warning would cost tokens on every call.
    """
    if not edit_stamp:
        return ""
    try:
        generated = con.execute("SELECT value FROM meta WHERE key='generated_utc'").fetchone()
    except sqlite3.Error:
        return ""
    if not generated or edit_stamp <= generated[0]:
        return ""
    return (f"\n\n_Store generated {generated[0]}; source edited since ({edit_stamp}). "
            f"New and renamed symbols are missing until you {_REBUILD}._")
