"""Measured response budgets for the engine-api tools.

Ported from the ceiling block at the top of `tools/review.py` in code-review-graph (MIT,
tirth8205/code-review-graph). Two ideas are theirs: cost each row type in tokens *by measuring it*
rather than picking a round number, and spend a fixed budget by rank rather than in whatever order
the query happened to emit. The constants below are this store's, measured on 2026-09-18.

**What this fixes.** `rows()` caps every query with `fetchmany(MAX_ROWS)` and the tools print their
counts from the truncated list. `engine_api_members("UKismetMathLibrary")` therefore reported
`## Functions (200)` for a class with **741** - 541 functions silently gone, and the wrong number
stated as a fact rather than as a cap. A budget that is not announced is indistinguishable from
data that does not exist, which is the same failure `uncertainty.py` addresses from the other side.

**Measurement method.** Rendered each tool against real rows and divided total line length by line
count, then chars by 4. That last step is an approximation, so every constant here is an *estimate*
and is named one. It is good enough to size a cap and not good enough to quote: counting with
`tiktoken` against real rendered rows is the route if a real number is ever needed.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Callable, Iterable, Optional, Sequence

CHARS_PER_TOKEN = 4

# Estimated tokens per rendered row, measured 2026-09-18 over AActor (275 members),
# MaterialInstanceDynamic::SetScalarParameterValue (48 Blueprint edges) and `Reach*` (200 hits).
MEMBER_LINE_TOKENS = 35
BP_EDGE_LINE_TOKENS = 36
SEARCH_LINE_TOKENS = 46
CLASS_BLOCK_TOKENS = 131

# Per-response ceiling. The uncapped worst case in the store is UKismetMathLibrary at an estimated
# 26,000 tokens for 741 members; the old silent 200-row cap still let 7,459 through. 4,000 keeps
# the largest engine classes usable without letting one call dominate a turn.
RESPONSE_BUDGET_TOKENS = 4_000

# SQL rows are unpredictable in width, so that tool keeps a row cap rather than a token cap.
SQL_MAX_ROWS = 200


def rows_for(budget_tokens: int, per_row_tokens: int) -> int:
    """How many rows of this kind fit in a budget. At least one, so a response is never all note."""
    return max(1, budget_tokens // max(1, per_row_tokens))


def take(
    items: Sequence[Any],
    per_row_tokens: int,
    budget_tokens: int = RESPONSE_BUDGET_TOKENS,
    rank: Optional[Callable[[Any], Any]] = None,
) -> tuple[list[Any], int]:
    """Spend `budget_tokens` on `items`, best first. Returns (kept, dropped).

    `rank` decides *who gets served*, which is the half a bare cap gets wrong. Ranking cannot make
    a truncated list complete, so the caller must still render the count from `dropped`.
    """
    limit = rows_for(budget_tokens, per_row_tokens)
    ordered = sorted(items, key=rank) if rank is not None else list(items)
    if len(ordered) <= limit:
        return ordered, 0
    return ordered[:limit], len(ordered) - limit


def truncation_note(shown: int, total: int, refinement: str) -> str:
    """The sentence that makes a cap visible. Empty when nothing was dropped.

    `refinement` names the narrower query that would return the rest, because a reader told only
    that a list is incomplete will re-run the same call and get the same truncated list.
    """
    if shown >= total:
        return ""
    return (f"\n_Showing {shown} of {total}, capped at an estimated {RESPONSE_BUDGET_TOKENS} "
            f"tokens per response. {refinement}_")


def count(con: sqlite3.Connection, sql: str, *args: Any) -> int:
    """A true COUNT(*), unaffected by any row cap. The denominator in every truncation note."""
    try:
        r = con.execute(sql, args).fetchone()
    except sqlite3.Error:
        return 0
    return int(r[0]) if r else 0


def all_rows(con: sqlite3.Connection, sql: str, *args: Any) -> list[dict]:
    """Like `mcp_server.rows` but *uncapped*, so the budget decides what is dropped, not fetchmany.

    Only safe because every caller passes the result straight to `take()`. A query that could
    return the whole store belongs on `engine_api_sql`, which keeps its own row cap.
    """
    return [dict(r) for r in con.execute(sql, args).fetchall()]


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------
# What "best first" means here. code-review-graph ranks by change risk, which has no analogue in a
# static API store. The useful ordering instead is **information this tier alone holds**: a
# COND_-bearing property is knowable from no other layer in the stack, whereas a plain accessor is
# one find_symbol_indexed away. Alphabetical order, the current behaviour, ranks by nothing.


def member_rank(row: dict) -> tuple:
    """Sort key for a function or property row. Lower sorts first."""
    replicated = 0 if row.get("rep_condition") else 1
    deprecated = 0 if row.get("is_deprecated") else 1
    specified = 0 if row.get("specifiers") else 1
    return (replicated, deprecated, specified, (row.get("name") or "").lower())


def bp_edge_rank(row: dict) -> tuple:
    """Sort key for a Blueprint edge. Most-used first, matching the existing ORDER BY."""
    return (-(row.get("uses") or 0), row.get("blueprint_path") or "")
