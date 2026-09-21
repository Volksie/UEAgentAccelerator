# Layer 3: the engine API store and its server

**Opt-in.** Nothing else in the stack depends on it, so you can add it later, and it's the one layer that needs a build of its own before it answers anything.

It exists for the questions Layer 2 cannot reach. The reflection dump walks the *live* engine, so it only sees what the editor you are running has actually loaded — the right trade for your own code, and no help at all for "is this module available on that console", where the answer has to be true for a platform you have never built for. This layer reads descriptors and the UnrealHeaderTool pass instead, so it covers what is declared rather than what happened to load.

## What it gives a session

Six tools, over one SQLite file, stdio transport, **no dependencies beyond the Python standard library**.

| Tool | Answers |
|---|---|
| `engine_api_class` | What a class is, what it inherits, which module and plugin it comes from |
| `engine_api_members` | What it declares: functions with signatures, properties with declared types |
| `engine_api_blast_radius` | Who references a symbol, including the Blueprint edges from Layer 2 |
| `engine_api_platform` | Whether a module is available on a platform and target type — **declared availability, resolved by the engine's own function**, so it needs no console SDK |
| `engine_api_search` | Names *and comment bodies*, prefix and word-split, across every indexed declaration |
| `engine_api_sql` | Read-only `SELECT`/`WITH` for anything the five fixed tools miss. **Start with `query='schema'`**: one response lists every table and view with its columns, plus the enumerations a query has to guess otherwise — edge kinds, loading phases, platforms, target types |

Five named views cover the shapes that cost the most discovery turns in the measured run: `v_bp_symbol_use` (per symbol and kind: how many Blueprints, graphs and nodes reach it), `v_bp_writes` (Blueprint writes to C++ properties, with the owning module and whether it is engine or project), `v_plugin_platform_gaps`, `v_module_loading_phases` and `v_index_stats`. A view is a query, not a copy, so none of them makes the file bigger.

## Building the store

Three tiers merge into one file, and each answers something the others cannot:

```bash
# 1. what is on disk, before anything is compiled: plugins, modules, declared platform availability.
#    Run the ModuleAvailability commandlet on each project first; this reads what it writes.
#    docs/08-layer3-engine-api.md, "Choosing platforms", says how to pick the platforms.
python build_descriptor_tier.py --root <your tree>

# 2. build your project with -AgentMemoryApi so UnrealHeaderTool emits *.agentapi.json
#    (the exporter is the C++ half of this layer, in ue-plugin/UEAgentAccelerator)

# 3. merge the tiers, plus the Layer 2 artefacts for replication conditions and Blueprint edges
python build_api_db.py --root <your tree>
```

Optionally, index comment *bodies* — the layer nothing else carries:

```bash
python extract_comments.py --root <your tree>
```

That one is worth its own sentence. Layer 2 carries the doc comment attached to a reflected declaration and nothing else, so a `// HACK:` three lines into a `.cpp` is in no artefact at all. A benchmark question was lost to exactly that: the answer was in a comment, and the arm with every layer available invented an explanation instead of finding it.

## Running the server

```bash
python mcp_server.py            # stdio; expects engine-api.db beside it
ENGINE_API_DB=/path/to/engine-api.db python mcp_server.py
```

Register it with your client as an stdio MCP server. It opens the database read-only.

**The `.db` files are not in this repository, deliberately.** They are generated, they are large — 69 MB for a tree with an engine and three projects — and they describe *your* engine and *your* projects rather than ours. Build your own; that is the only version that is true about your tree.

## What it cannot do, and must not pretend to

**Replication conditions.** UnrealHeaderTool sees `Replicated` and `ReplicatedUsing` and stops. The `COND_` is set in `GetLifetimeReplicatedProps` at runtime, so it exists in no header and no UHT pass will ever find it. The store carries those only where the Layer 2 tier supplied them, and the column is `NULL` — meaning *unknown* — everywhere else.

**Anything about a target you have not built.** Declared availability is honest about platforms you have no SDK for, because it reads descriptors. Anything requiring compilation is not.

**Being a superset of the reflection dump.** A plain virtual is not a `UFUNCTION`, so UHT never reports it.

## Honest results, which is most of the point

Two of the newer pieces exist because a confident empty answer is worse than a slow one.

**`uncertainty.py`** marks results whose emptiness is ambiguous. "No rows" can mean the engine really has no such thing, or that this store cannot see it — the class lives in a target nobody exported, or the Blueprint walk for that project did not reach everything. Where the store cannot tell those apart, it says so.

For the Blueprint half it says it precisely, because the generator states its own coverage and the merge job parses that line into `bp_walk`. An empty blast-radius result therefore reports *all N Blueprints with graphs walked, M data-only excluded* rather than a ratio — the ratio was the wrong question, since a data-only Blueprint has no graphs by construction and can never produce an edge, and counting those as misses made coverage read around 54% on a large project and every true negative look weak. **Artefacts generated before that line existed are recognised and named as such**, and the empty result then says what the older walk did and did not cover instead of implying the new coverage.

**`budget.py`** spends a measured response budget by rank instead of truncating whatever the query emitted first. Row costs were measured against this store rather than chosen as round numbers.

**`stamp-edit.py`** is a `PostToolUse` hook that records when a file the store indexes is edited, so a session can tell that the store is behind the tree. It matches `Write|Edit|Bash` — **including Bash**, because a `sed` or a redirect edits a file just as thoroughly as the Edit tool, and a `Write|Edit` matcher never sees it.

## Attribution

`uncertainty.py`, `budget.py` and `stamp-edit.py` take their *ideas* from [code-review-graph](https://github.com/tirth8205/code-review-graph) (MIT): confidence markers on empty results, costing rows by measurement rather than by guess, and a hook matcher that includes Bash. The code here is ours — the data model shares nothing with a tree-sitter graph — and every constant was measured against this store. See *NOTICE.md* at the repository root.
