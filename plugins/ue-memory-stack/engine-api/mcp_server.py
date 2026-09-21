"""The query surface over the engine API store.

An MCP server over `engine-api.db`, stdio transport, **zero dependencies**.

Why it exists, and why now. The design said to build this "only if the benchmark shows raw SQL is a
problem". The benchmark cannot show it, and raw SQL is a problem anyway, for a reason measured on
2026-09-09: **there is no `sqlite3` CLI on this machine**. Section 8's "start without a server"
access path therefore reduces to

    python -c "import sqlite3;c=sqlite3.connect('file:...?mode=ro',uri=True);print(c.execute(\\"SELECT ...\\").fetchone())"

- nested quoting, in a one-liner, in a shell. That is the same shape as the L3 naming hole the
benchmark already quantified: the answer is reachable, the route is awkward, so it gets routed
around, and a benchmark scores the layer as worthless when what is actually bad is the access.

Why no dependencies. The `mcp` package is not installed for the Python that runs outside the Claude
desktop app's MSIX container, and anything registered as an MCP server runs out there. A hand-rolled
JSON-RPC loop over stdin/stdout removes an install step that has already bitten this project twice
(the uv trampoline, and the language servers that needed node and pwsh).

Design notes carried from the rest of the stack:

- **Absence and ignorance must not look the same.** Every response that could be misread as "no"
  says which tier could have known. `rep_condition` is only ever populated by the runtime tier, so a
  property with no condition is reported as *not replicated (runtime-verified)* or *unknown
  (parse-time view only)* depending on `source`, never as a bare null.
- **Blast radius filters to project origin by default.** 86% of Blueprint edges point at engine
  classes nobody here can change; an unfiltered answer is technically true and practically noise.
- The SQL escape hatch is read-only and row-capped. It exists because a fixed tool set always misses
  a question, not because raw SQL is the intended route.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

import budget
import uncertainty

HERE = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("ENGINE_API_DB", HERE / "engine-api.db"))
MAX_ROWS = 200
PROTOCOL = "2025-06-18"

# Written by the PostToolUse hook in .claude/settings.json on every Write, Edit or Bash. One ISO
# timestamp, nothing else. Its absence is not evidence of freshness; see uncertainty.freshness.
EDIT_STAMP = Path(os.environ.get("ENGINE_API_EDIT_STAMP", HERE / ".edit-stamp"))

_con: sqlite3.Connection | None = None


def db() -> sqlite3.Connection:
    global _con
    if _con is None:
        if not DB_PATH.exists():
            raise RuntimeError(
                f"engine-api.db not found at {DB_PATH}. Build it with "
                f"'python build_api_db.py --root <your tree>' beside this file, or point "
                f"ENGINE_API_DB at one you have already built.")
        _con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)
        _con.row_factory = sqlite3.Row
    return _con


def rows(sql: str, *args) -> list[dict]:
    return [dict(r) for r in db().execute(sql, args).fetchmany(MAX_ROWS)]


def one(sql: str, *args):
    r = db().execute(sql, args).fetchone()
    return dict(r) if r else None


def _edit_stamp() -> str:
    """The last recorded source edit, or "" when the hook is not installed or the file is junk."""
    try:
        return EDIT_STAMP.read_text(encoding="utf-8").strip()[:32]
    except OSError:
        return ""


def _footer(tool: str, ctx: dict | None = None, empty: bool = False) -> str:
    """The advisory tail of a response: staleness always, a blind-spot note only when empty.

    Split this way because the two say different things. Staleness is about the store as a whole
    and is just as true of a full result; a blind-spot note is only worth its tokens when the
    reader is about to conclude "no".
    """
    out = uncertainty.freshness(db(), _edit_stamp())
    if empty:
        out += uncertainty.marker(tool, ctx or {})
    return out


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def _resolve_class(name: str) -> dict | None:
    """Accept a bare or prefixed name. Artefacts drop the U/A/F/I prefix and headers keep it, so a
    caller should not have to know which convention the store used.

    A prefix-guessed hit is tagged `_inferred`. Borrowed from code-review-graph, which tags a
    heuristically resolved edge `confidence_tier = INFERRED` rather than letting it read like a
    direct extraction: `Character` matching `ACharacter` is a guess that happens to be right almost
    always, and the one time it picks the wrong prefix the answer is confidently about another
    class. Tagging costs nothing and keeps the tree's own "say inferred" rule in the data rather
    than in prose downstream of it.
    """
    r = one("SELECT c.*, m.name AS module, m.origin FROM classes c JOIN modules m ON m.id=c.module_id"
            " WHERE c.name=?", name)
    if r:
        r["_inferred"] = ""
        return r
    for pre in ("U", "A", "F", "I"):
        r = one("SELECT c.*, m.name AS module, m.origin FROM classes c JOIN modules m ON m.id=c.module_id"
                " WHERE c.name=?", pre + name)
        if r:
            others = [x["name"] for x in rows(
                "SELECT name FROM classes WHERE name IN (?,?,?,?) AND name<>?",
                "U" + name, "A" + name, "F" + name, "I" + name, pre + name)]
            r["_inferred"] = (f"resolved `{name}` to `{pre + name}` by prefix"
                              + (f"; also in the store: {', '.join(others)}" if others else ""))
            return r
    return None


def tool_class(name: str) -> str:
    c = _resolve_class(name)
    if not c:
        near = rows("SELECT name FROM search WHERE search MATCH ? AND kind='class' LIMIT 8", name)
        hint = ", ".join(n["name"] for n in near) if near else "nothing similar"
        return (f"No class named '{name}' in the store.\n"
                f"Near matches: {hint}\n"
                f"Note the store holds what the exported targets compiled. A class in a plugin no "
                f"target enables will not be here; the descriptor tier still knows the plugin."
                + _footer("engine_api_class", {}, empty=True))
    chain, cur, seen = [], c, set()
    while cur and cur["id"] not in seen:
        seen.add(cur["id"])
        chain.append(cur["name"])
        cur = one("SELECT c.*, m.name AS module, m.origin FROM classes c JOIN modules m ON m.id=c.module_id"
                  " WHERE c.id=?", cur["super_id"]) if cur["super_id"] else None
    ifaces = [r["interface_name"] for r in rows(
        "SELECT interface_name FROM class_interfaces WHERE class_id=?", c["id"])]
    nfn = one("SELECT COUNT(*) n FROM functions WHERE class_id=?", c["id"])["n"]
    npr = one("SELECT COUNT(*) n FROM properties WHERE class_id=?", c["id"])["n"]
    nrep = one("SELECT COUNT(*) n FROM properties WHERE class_id=? AND rep_condition IS NOT NULL",
               c["id"])["n"]
    nbp = one("SELECT COALESCE(SUM(uses),0) n FROM bp_edges WHERE class_id=?", c["id"])["n"]

    out = [f"# {c['name']}",
           f"module `{c['module']}` ({c['origin']})   |   {nfn} functions, {npr} properties, "
           f"{nrep} replicated   |   {nbp} Blueprint uses",
           f"inherits: {' -> '.join(chain)}" if len(chain) > 1 else "inherits: (no parent in store)"]
    if ifaces:
        out.append(f"implements: {', '.join(ifaces)}")
    if c["is_deprecated"]:
        out.append(f"**DEPRECATED**: {c['deprecation_msg'] or '(no replacement stated)'}")
    if c["header_path"]:
        out.append(f"header: {c['header_path']}")
    if c["class_flag_names"]:
        out.append(f"flags: {c['class_flag_names']}")
    out.append(f"seen by tiers: {c['sources']}   targets: {c['targets']}")
    if c.get("_inferred"):
        out.append(f"_INFERRED: {c['_inferred']}._")
    # A field-level qualifier, not an empty-result marker: the class was found, but one column of it
    # is unknowable from the tiers that saw it. Deliberately not routed through uncertainty.marker,
    # which fires only on empty results - conflating the two put a "why this may be empty" note on
    # every fully populated class.
    if "runtime" not in (c["sources"] or ""):
        out.append("_No runtime tier row: replication conditions for this class are unknown, not "
                   "absent._")
    return "\n".join(x for x in out if x) + _footer("engine_api_class")


def tool_members(name: str, kind: str = "both") -> str:
    c = _resolve_class(name)
    if not c:
        return f"No class named '{name}'."
    out = [f"# {c['name']} members"]
    if c.get("_inferred"):
        out.append(f"_INFERRED: {c['_inferred']}._")
    # Half the budget each when both kinds are asked for, so a class with 700 functions and 3
    # properties cannot spend the whole response before the properties are reached.
    share = budget.RESPONSE_BUDGET_TOKENS // (2 if kind == "both" else 1)
    if kind in ("both", "functions"):
        total = budget.count(db(), "SELECT COUNT(*) FROM functions WHERE class_id=?", c["id"])
        fns = budget.all_rows(db(), "SELECT id, name, specifiers, is_deprecated, deprecation_msg"
                                    " FROM functions WHERE class_id=?", c["id"])
        fns, _ = budget.take(fns, budget.MEMBER_LINE_TOKENS, share, rank=budget.member_rank)
        out.append(f"\n## Functions ({total})\n")
        out.append(budget.truncation_note(
            len(fns), total,
            f"Use engine_api_search for one name, or engine_api_sql against `functions` "
            f"WHERE class_id={c['id']} for all of them.").strip())
        for f in fns:
            ps = rows("SELECT name, cpp_type, is_return FROM function_params WHERE function_id=?"
                      " ORDER BY ordinal", f["id"])
            sig = ", ".join(f"{p['cpp_type']} {p['name']}" for p in ps if not p["is_return"])
            ret = next((p["cpp_type"] for p in ps if p["is_return"]), "void")
            line = f"- `{ret} {f['name']}({sig})`"
            if f["specifiers"]:
                line += f"  — {f['specifiers']}"
            if f["is_deprecated"]:
                line += f"  **DEPRECATED**: {f['deprecation_msg'] or '(no replacement stated)'}"
            out.append(line)
    if kind in ("both", "properties"):
        total = budget.count(db(), "SELECT COUNT(*) FROM properties WHERE class_id=?", c["id"])
        prs = budget.all_rows(db(), "SELECT name, cpp_type, specifiers, rep_condition, rep_notify,"
                                    " source, is_deprecated, deprecation_msg FROM properties"
                                    " WHERE class_id=?", c["id"])
        prs, _ = budget.take(prs, budget.MEMBER_LINE_TOKENS, share, rank=budget.member_rank)
        out.append(f"\n## Properties ({total})\n")
        out.append(budget.truncation_note(
            len(prs), total,
            f"Replicated, deprecated and specifier-bearing properties are listed first, so what is "
            f"cut is the plain ones. engine_api_sql against `properties` gives all of them.").strip())
        for p in prs:
            line = f"- `{p['cpp_type']} {p['name']}`"
            if p["rep_condition"]:
                line += f"  **replicated {p['rep_condition']}**"
                if p["rep_notify"]:
                    line += f" (OnRep={p['rep_notify']})"
            elif p["source"] == "runtime":
                line += "  not replicated (runtime-verified)"
            else:
                line += "  replication unknown (parse-time view only)"
            if p["specifiers"]:
                line += f"  — {p['specifiers']}"
            if p["is_deprecated"]:
                line += f"  **DEPRECATED**: {p['deprecation_msg'] or '(no replacement stated)'}"
            out.append(line)
    empty = not any(l.startswith("- ") for l in out)
    return "\n".join(x for x in out if x) + _footer(
        "engine_api_members", {"sources": c["sources"]}, empty=empty)


def tool_blast_radius(symbol: str, include_engine: bool = False) -> str:
    """Blueprint users of a C++ symbol. `symbol` may be `Class`, `Class::Member` or a bare member."""
    if "::" in symbol:
        cls, mem = symbol.split("::", 1)
        where, args = "e.symbol_class IN (?,?) AND e.symbol_name=?", (cls, cls.lstrip("UAFI"), mem)
    else:
        where, args = ("(e.symbol_class IN (?,?) OR e.symbol_name=?)",
                       (symbol, symbol.lstrip("UAFI"), symbol))
    origin_clause = "" if include_engine else " AND (m.origin='project' OR m.origin IS NULL)"
    q = (f"SELECT e.symbol_class, e.symbol_name, e.kind, e.blueprint_path, e.graph, e.uses,"
         f" e.project, m.origin FROM bp_edges e"
         f" LEFT JOIN classes c ON c.id=e.class_id LEFT JOIN modules m ON m.id=c.module_id"
         f" WHERE {where}{origin_clause} ORDER BY e.uses DESC, e.blueprint_path")
    every = budget.all_rows(db(), q, *args)
    if not every:
        total = one(f"SELECT COUNT(*) n FROM bp_edges e WHERE {where}", *args)["n"]
        if total and not include_engine:
            return (f"No **project-owned** Blueprint users of `{symbol}`, but {total} edges exist on "
                    f"engine-owned classes. Pass include_engine=true to see them."
                    + _footer("engine_api_blast_radius"))
        # The walk is the only thing in the stack that can see .uasset references, so a miss here is
        # strong evidence - exactly as strong as the walk's coverage, which bp_walk states per
        # project: how many Blueprints have graphs at all (data-only ones cannot produce an edge and
        # are not a gap) and how many of those were walked. Saying it lets the reader weigh the
        # negative instead of taking a flat "real negative" on trust, or a flat "54%" as doubt.
        thin = uncertainty.incomplete_walk_projects(db())
        statement = uncertainty.walk_statement(db())
        if statement:
            # Artefacts from the walk that covers macro graphs and BindWidget bindings, and says so.
            body = (f"No Blueprint graph calls, reads or writes `{symbol}`, and no BindWidget binding to it.\n\n"
                    f"The edges come from a resolved walk over every Blueprint's event, function and macro "
                    f"graphs plus widget designer trees, which is the only thing in the stack that can see "
                    f".uasset references. A C++ tool cannot, and ripgrep skips .uasset silently. Not "
                    f"covered: uses of a class rather than a member (component templates, variable types)."
                    f"\n\n_Walk coverage: {statement}._")
        else:
            # An older artefact set: event and function graphs only, no bind edges, no coverage line.
            body = (f"No Blueprint graph calls, reads or writes `{symbol}`.\n\n"
                    f"The edges come from a resolved graph walk over every Blueprint's event and function "
                    f"graphs, which is the only thing in the stack that can see .uasset references. A C++ "
                    f"tool cannot, and ripgrep skips .uasset silently. This artefact set predates the walk "
                    f"of macro graphs and BindWidget bindings, so a widget bound by name to a C++ property "
                    f"would not appear here.")
        if thin:
            body += (f"\n\n_Weigh this against the walk: {', '.join(thin)} Blueprints with graphs were "
                     f"walked. On those projects an empty result is weak evidence; on the rest it is "
                     f"a real negative._")
        return body + _footer("engine_api_blast_radius", {"coverage_is_thin": bool(thin)}, empty=True)
    total_rows = len(every)
    total_uses = sum(r["uses"] or 0 for r in every)
    rs, _ = budget.take(every, budget.BP_EDGE_LINE_TOKENS, rank=budget.bp_edge_rank)
    out = [f"# Blueprint users of `{symbol}`",
           f"{total_rows} rows, {total_uses} uses"
           + ("" if include_engine else "  (project-owned classes only)")]
    # A bare member name matches that name on every class that declares it. One list of call sites
    # spanning several unrelated owners reads exactly like one list for a single method, which is
    # the ambiguity code-review-graph's scoped resolver refuses to collapse. Say so and name them.
    owners = sorted({r["symbol_class"] for r in every if r["symbol_class"]})
    if "::" not in symbol and len(owners) > 1:
        out.append(f"_INFERRED: `{symbol}` is a bare member name and matched {len(owners)} classes "
                   f"({', '.join(owners[:6])}{'…' if len(owners) > 6 else ''}). These call sites are "
                   f"not all the same method - qualify as `Class::{symbol}` to split them._")
    note = budget.truncation_note(len(rs), total_rows, "Most-used call sites are listed first.")
    if note:
        out.append(note.strip())
    out.append("")
    out += [f"- `{r['symbol_class']}::{r['symbol_name']}` — {r['kind']} x{r['uses']} in "
            f"`{r['blueprint_path']}` / {r['graph']}  [{r['project']}]" for r in rs]
    return "\n".join(out) + _footer("engine_api_blast_radius")


def tool_platform(module: str, platform: str | None = None, target_type: str = "Game") -> str:
    if not platform:
        # No platform named: answer for every platform the store has declarations for, rather than
        # guessing one. Which platforms that is depends on the engine install, consoles included.
        per = rows("SELECT platform, MAX(available) AS available FROM module_platforms"
                   " WHERE module_name=? AND target_type=? GROUP BY platform ORDER BY platform",
                   module, target_type)
        out = [f"# `{module}` / {target_type}, every declared platform"]
        if not per:
            out.append("\n**Declared: unknown.** No descriptor row - this module has no `.uplugin`, so it "
                       "is compiled from a Source/ tree and nothing declares its platforms.")
        for r in per:
            out.append(f"- {r['platform']}: {'available' if r['available'] else 'NOT available'}")
        out.append("\n_Name a platform for the per-plugin detail and what was observed in a build._")
        return "\n".join(out)
    dec = rows("SELECT plugin, host_type, MAX(available) AS available FROM module_platforms"
               " WHERE module_name=? AND platform=? AND target_type=? GROUP BY plugin, host_type",
               module, platform, target_type)
    obs = rows("SELECT target, target_type, platform FROM module_observed WHERE module_name=?", module)
    out = [f"# `{module}` on {platform} / {target_type}"]
    if dec:
        best = max(d["available"] for d in dec)
        out.append(f"\n**Declared: {'available' if best else 'NOT available'}** "
                   f"(from the .uplugin descriptor, no build required)")
        for d in dec:
            out.append(f"- plugin `{d['plugin']}`, host type {d['host_type']}: "
                       f"{'yes' if d['available'] else 'no'}")
        if len(dec) > 1:
            out.append("_Two entries is normal: 13 plugins declare the same module twice with "
                       "different Type and different platform lists. Available if ANY entry says so._")
    else:
        out.append("\n**Declared: unknown.** No descriptor row — this module has no `.uplugin`, so it "
                   "is compiled from a Source/ tree and nothing declares its platforms.")
    if obs:
        out.append(f"\n**Observed** in {len(obs)} build graph(s): "
                   + ", ".join(f"`{o['target']}` ({o['target_type']}, {o['platform']})" for o in obs))
    else:
        out.append("\n**Observed: never.** No target exported here contained it. That is not the same "
                   "as unavailable — it means no build we ran pulled it in.")
    # Worked out from the data rather than from a list of platform names: if no exported target was
    # ever built for this platform, every answer for it is declared, never observed.
    if not rows("SELECT 1 FROM module_observed WHERE platform=? LIMIT 1", platform):
        out.append(f"\n_No {platform} target has been built in this tree, so every {platform} answer "
                   f"here is **declared** availability read from a descriptor, never observed._")
    return "\n".join(out)


def _fts_query(q: str) -> str:
    """Make a plain-English query safe for FTS5, without taking away deliberate FTS5 syntax.

    FTS5 treats `-`, `:` and `*` as operators, so an ordinary phrase blows up rather than missing:
    searching the comment index for "stamina top-up frame" raised `no such column: up`, because the
    hyphen reads as a column filter. That was harmless while the index held only identifiers; it
    became a real problem the moment the index carried English prose.

    A query that already contains a double quote is assumed to know what it is doing and is passed
    through. Otherwise each bare token is quoted, which keeps implicit AND and preserves a trailing
    `*` so prefix search still works - the thing you want when you half-remember a name.
    """
    if '"' in q:
        return q
    parts = []
    for tok in q.split():
        star = tok.endswith("*")
        body = tok[:-1] if star else tok
        body = body.replace('"', "")
        if not body:
            continue
        parts.append(f'"{body}"' + ("*" if star else ""))
    return " ".join(parts) or q


def tool_search(query: str, kind: str = "") -> str:
    q = _fts_query(query)
    if kind:
        rs = rows("SELECT kind, name, owner, doc FROM search WHERE search MATCH ? AND kind=? LIMIT ?",
                  q, kind, MAX_ROWS)
    else:
        rs = rows("SELECT kind, name, owner, doc FROM search WHERE search MATCH ? LIMIT ?",
                  q, MAX_ROWS)
    if not rs:
        return (f"No match for '{query}'. Try a prefix like `{query.split()[0] if query.split() else query}*`"
                f", or kind='comment' to search comment text rather than symbol names."
                + _footer("engine_api_search", {"query": query}, empty=True))
    kept, _ = budget.take(rs, budget.SEARCH_LINE_TOKENS)
    out = [f"{len(rs)} match(es) for '{query}'"
           + (f" (capped at {MAX_ROWS} by the index)" if len(rs) == MAX_ROWS else "")]
    note = budget.truncation_note(len(kept), len(rs), "Narrow with kind=, or a longer prefix.")
    if note:
        out.append(note.strip())
    out.append("")
    for r in kept:
        doc = (r["doc"] or "").replace("\n", " ")[:90]
        out.append(f"- **{r['kind']}** `{r['name']}` on `{r['owner']}`" + (f" — {doc}" if doc else ""))
    return "\n".join(out) + _footer("engine_api_search")


FORBIDDEN = ("insert", "update", "delete", "drop", "alter", "create", "attach", "pragma", "replace")



_SCHEMA_ENUMS = [
    ("bp_edges", "kind"), ("modules", "type"), ("modules", "loading_phase"), ("modules", "origin"),
    ("module_platforms", "platform"), ("module_platforms", "target_type"), ("module_platforms", "host_type"),
    ("plugins", "origin"), ("search", "kind"),
]
_schema_cache: str | None = None


def tool_schema() -> str:
    """Every table and view with its columns, plus the enumerations a query needs to know: one call
    instead of the eight-call discovery the v5 benchmark measured on the heavy questions."""
    global _schema_cache
    if _schema_cache is None:
        con = db()
        out = ["# engine-api.db schema", ""]
        for kind in ("table", "view"):
            names = [r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type=? AND name NOT LIKE 'search_%' ORDER BY name", (kind,))]
            out.append(f"## {kind}s")
            for n in names:
                cols = [r[1] for r in con.execute(f"PRAGMA table_info({n})")]
                out.append(f"- **{n}**({', '.join(cols)})")
            out.append("")
        out.append("## enumerations (value: rows)")
        for t, c in _SCHEMA_ENUMS:
            vals = con.execute(f"SELECT {c}, COUNT(*) FROM {t} GROUP BY 1 ORDER BY 2 DESC").fetchall()
            out.append(f"- {t}.{c}: " + ", ".join(f"{'NULL' if v is None else v}: {n}" for v, n in vals))
        out.append("")
        out.append("Views answer the recurring shapes in one query: v_bp_symbol_use (most-called symbol, "
                   "per-symbol Blueprint/graph/node counts), v_bp_writes (Blueprint writes to C++ "
                   "properties with module and origin), v_plugin_platform_gaps (plugins with unavailable "
                   "modules per platform/target/host type), v_module_loading_phases, v_index_stats "
                   "(search index by kind; comment files). `search` is FTS5: use MATCH, and `kind='comment'` "
                   "for comment bodies. `owner` on a comment row is file:line.")
        _schema_cache = "\n".join(out)
    return _schema_cache


def tool_sql(query: str) -> str:
    q = query.strip().rstrip(";")
    low = q.lower()
    if low in ("", "schema", "help", "tables"):
        return tool_schema()
    if not low.startswith(("select", "with")):
        return "Only SELECT and WITH are allowed."
    if any(f" {w} " in f" {low} " for w in FORBIDDEN):
        return f"Rejected: statement contains a write keyword. This connection is read-only anyway."
    try:
        cur = db().execute(q)
        got = cur.fetchmany(MAX_ROWS)
    except sqlite3.Error as exc:
        return f"SQL error: {exc}"
    if not got:
        return ("0 rows. The query ran and matched nothing - this is not a syntax failure."
                + _footer("engine_api_sql", {"query": query}, empty=True))
    cols = [d[0] for d in cur.description]
    lines = [" | ".join(cols), "-|-".join("-" * len(c) for c in cols)]
    lines += [" | ".join("" if v is None else str(v) for v in r) for r in got]
    if len(got) == MAX_ROWS:
        lines.append(f"\n_(capped at {MAX_ROWS} rows)_")
    return "\n".join(lines)


TOOLS = [
    {
        "name": "engine_api_class",
        "description": "Everything the store knows about one C++ class: module, origin, full "
                       "inheritance chain across engine and project, interfaces, deprecation, "
                       "counts, and which tiers saw it. Accepts a bare or U/A-prefixed name.",
        "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}},
                        "required": ["name"]},
        "fn": lambda a: tool_class(a["name"]),
    },
    {
        "name": "engine_api_members",
        "description": "Functions and properties of a class, with full signatures, decoded "
                       "specifiers, deprecation messages, and COND_* replication. Distinguishes "
                       "'not replicated' from 'we only have a parse-time view'.",
        "inputSchema": {"type": "object", "properties": {
            "name": {"type": "string"},
            "kind": {"type": "string", "enum": ["both", "functions", "properties"]}},
            "required": ["name"]},
        "fn": lambda a: tool_members(a["name"], a.get("kind", "both")),
    },
    {
        "name": "engine_api_blast_radius",
        "description": "Which Blueprint graphs call, read or write a C++ symbol. The only source for "
                       "this: clangd cannot read .uasset and ripgrep skips them silently. Defaults "
                       "to project-owned classes, since most edges point at engine utilities.",
        "inputSchema": {"type": "object", "properties": {
            "symbol": {"type": "string", "description": "Class, Class::Member, or a bare member"},
            "include_engine": {"type": "boolean"}},
            "required": ["symbol"]},
        "fn": lambda a: tool_blast_radius(a["symbol"], bool(a.get("include_engine"))),
    },
    {
        "name": "engine_api_platform",
        "description": "Declared and observed platform availability for a module. Declared comes "
                       "from .uplugin descriptors and works for consoles never built here; observed "
                       "comes from targets actually exported.",
        "inputSchema": {"type": "object", "properties": {
            "module": {"type": "string"},
            "platform": {"type": "string"},
            "target_type": {"type": "string", "enum": ["Game", "Editor", "Client", "Server", "Program"]}},
            "required": ["module"]},
        "fn": lambda a: tool_platform(a["module"], a.get("platform"),
                                      a.get("target_type", "Game")),
    },
    {
        "name": "engine_api_search",
        "description": "Full-text search over class, function, property, struct and enum names and "
                       "doc comments. FTS5 syntax, so prefix queries need a trailing *.",
        "inputSchema": {"type": "object", "properties": {
            "query": {"type": "string"},
            "kind": {"type": "string", "enum": ["class", "function", "property", "struct", "enum", "comment"]}},
            "required": ["query"]},
        "fn": lambda a: tool_search(a["query"], a.get("kind", "")),
    },
    {
        "name": "engine_api_sql",
        "description": "Read-only SELECT against the store, for questions the other tools do not "
                       "cover. Start with query='schema': one response lists every table and view "
                       "with columns and the enumerations (edge kinds, loading phases, platforms, "
                       "target types, search kinds). Views answer the common shapes in one query: "
                       "v_bp_symbol_use, v_bp_writes, v_plugin_platform_gaps, v_module_loading_phases, "
                       "v_index_stats.",
        "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}},
                        "required": ["query"]},
        "fn": lambda a: tool_sql(a["query"]),
    },
]


# ---------------------------------------------------------------------------
# JSON-RPC over stdio
# ---------------------------------------------------------------------------

def respond(msg: dict) -> None:
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def handle(req: dict) -> dict | None:
    rid, method, params = req.get("id"), req.get("method"), req.get("params") or {}
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": PROTOCOL,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "engine-api-db", "version": "1"}}}
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "tools": [{k: t[k] for k in ("name", "description", "inputSchema")} for t in TOOLS]}}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        tool = next((t for t in TOOLS if t["name"] == name), None)
        if tool is None:
            return {"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32601, "message": f"No such tool: {name}"}}

        # Check the tool's own schema BEFORE calling it. Every tool reads its arguments as `a["name"]`,
        # so a caller who passed the right value under the wrong key used to get `KeyError: 'name'` out
        # of the except below - and a bare KeyError from a database-backed server reads as a corrupt
        # store rather than as a typo. That cost a session an hour of inspecting the database after a
        # rebuild, looking for damage that was never there. Name what is missing, name what arrived
        # instead, and list what this tool accepts.
        schema = tool.get("inputSchema") or {}
        accepted = list((schema.get("properties") or {}).keys())
        missing = [k for k in (schema.get("required") or []) if k not in args]
        if missing:
            parts = ["%s: missing required argument %s" % (name, ", ".join(repr(m) for m in missing))]
            unexpected = [k for k in args if k not in accepted]
            if unexpected:
                parts.append("got %s instead" % ", ".join(repr(u) for u in unexpected))
            parts.append("this tool accepts %s" % (", ".join(repr(a) for a in accepted) or "no arguments"))
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": ". ".join(parts) + "."}], "isError": True}}

        try:
            text = tool["fn"](args)
            is_error = False
        except KeyError as exc:  # noqa: PERF203 - a key error here is still an argument problem
            # Reached when a tool reads an OPTIONAL argument it was not given, which is a bug in the
            # tool rather than in the call. Say which, so the next reader does not suspect the store.
            text, is_error = (f"{name}: internal error, no argument {exc} (the call was accepted by "
                              f"the schema, so this is a defect in the tool, not in your arguments "
                              f"or the store)"), True
        except Exception as exc:  # noqa: BLE001
            text, is_error = f"{type(exc).__name__}: {exc}", True
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "content": [{"type": "text", "text": text}], "isError": is_error}}
    if rid is None:
        return None
    return {"jsonrpc": "2.0", "id": rid,
            "error": {"code": -32601, "message": f"Unsupported method: {method}"}}


def main() -> int:
    if "--selftest" in sys.argv:
        print(f"db: {DB_PATH} ({'exists' if DB_PATH.exists() else 'MISSING'})")
        for t in TOOLS:
            print(f"  tool {t['name']}")
        print()
        print(tool_class("ALyraCharacter"))
        print()
        print(tool_blast_radius("LyraHealthComponent::FindHealthComponent"))
        print()
        print(tool_platform("VertexDeltaModel", "Android", "Game"))
        return 0
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        out = handle(req)
        if out is not None:
            respond(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
