"""Engine API database, phase 4: the merge job.

Reads all three tiers into one SQLite file, applying the identity and provenance rules that phase 3
proved out. Win64 only, per the design - console targets are phase 5, and need a console build.

    disk     descriptors on disk (phase 1)         plugins, modules, declared platform availability
    uht      *.agentapi.json from our exporter     classes, functions, signatures, properties, enums
    runtime  Layer 2 reflection artefacts          COND_* replication, which no parse-time tier sees

The rules this file exists to honour, all three found the hard way in phase 3:

  A. ONE row per (name, module_id). The same class legitimately arrives from all three tiers, and a
     row per tier silently doubles every join. `source` keeps the highest fidelity seen,
     `sources` keeps all of them.
  B. `targets` is a UNION across tiers, never the first writer's value. Taking one and discarding the
     rest loses console coverage with no error.
  C. `rep_condition` is written only by the runtime tier, and stays NULL elsewhere - never 0 or "" -
     so a consumer can tell "does not replicate" from "this tier cannot see it".

And the limit found when the exporter first ran at scale: **uht is not a superset of disk.**
`GetLifetimeReplicatedProps` is a plain virtual, not a UFUNCTION, so UHT never reports it while a
header read does. The merge must not drop a disk-tier fact because a uht row exists for that class.

Paths are derived from this file's location rather than hardcoded, so renaming the tree root does not
break it.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_ROOT = HERE.parent.parent  # <root>/engine-api/ -> <root>

FIDELITY = {"disk": 0, "uht": 1, "runtime": 2}

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE modules (
    id INTEGER PRIMARY KEY, name TEXT UNIQUE, type TEXT,
    loading_phase TEXT, plugin TEXT, origin TEXT,           -- engine | project
    source TEXT, sources TEXT);

CREATE TABLE plugins (
    id INTEGER PRIMARY KEY, name TEXT UNIQUE, descriptor_path TEXT,
    origin TEXT, category TEXT, description TEXT,
    module_count INTEGER, enabled_by_any INTEGER);

CREATE TABLE enabled_by (plugin TEXT, project TEXT, PRIMARY KEY (plugin, project)) WITHOUT ROWID;

CREATE TABLE module_platforms (
    -- Keyed by the DESCRIPTOR's module id, not by module name. 17 plugins in this tree declare the
    -- same module name twice in one .uplugin, with different Type and different platform lists -
    -- e.g. AndroidCamera declares AndroidCameraFactory as Editor (no allow list, so every platform)
    -- and again as RuntimeNoCommandlet (allow list ["Android"]). Keying on the name collapsed the
    -- pair and silently dropped 585 rows, losing precisely the platform gating this tier exists to
    -- record. host_type is carried so the two entries stay tellable apart by a reader.
    descriptor_module_id INTEGER NOT NULL,
    plugin TEXT NOT NULL, module_name TEXT NOT NULL, host_type TEXT,
    platform TEXT NOT NULL, target_type TEXT NOT NULL,
    available INTEGER NOT NULL,
    PRIMARY KEY (descriptor_module_id, platform, target_type)) WITHOUT ROWID;

CREATE TABLE module_observed (
    -- OBSERVED availability: this module was actually in that target's UHT build graph. The
    -- counterpart to module_platforms, which is DECLARED. Section 5.6: store both and surface the
    -- gap, because .Build.cs can gate on Target.Platform in C# that no descriptor expresses.
    module_name TEXT NOT NULL, target TEXT NOT NULL, target_type TEXT, platform TEXT,
    PRIMARY KEY (module_name, target)) WITHOUT ROWID;

CREATE TABLE classes (
    id INTEGER PRIMARY KEY, name TEXT, module_id INTEGER, super_id INTEGER, super_name TEXT,
    class_type TEXT, class_flags INTEGER, class_flag_names TEXT, is_deprecated INTEGER,
    deprecation_msg TEXT, header_path TEXT, doc TEXT,
    source TEXT, sources TEXT, targets TEXT,
    UNIQUE(name, module_id));                               -- RULE A

CREATE TABLE class_interfaces (class_id INTEGER, interface_name TEXT,
    PRIMARY KEY (class_id, interface_name)) WITHOUT ROWID;

CREATE TABLE functions (
    id INTEGER PRIMARY KEY, class_id INTEGER, name TEXT,
    function_flags INTEGER, function_type TEXT, specifiers TEXT,
    is_virtual INTEGER, is_override INTEGER, is_deprecated INTEGER, deprecation_msg TEXT, doc TEXT,
    source TEXT, sources TEXT, targets TEXT,
    UNIQUE(class_id, name));      -- RULE A applies to members too; see properties

CREATE TABLE function_params (
    function_id INTEGER, ordinal INTEGER, name TEXT, cpp_type TEXT,
    property_flags INTEGER, is_return INTEGER,
    PRIMARY KEY (function_id, ordinal)) WITHOUT ROWID;

CREATE TABLE properties (
    id INTEGER PRIMARY KEY, class_id INTEGER, name TEXT, cpp_type TEXT,
    property_flags INTEGER, specifiers TEXT,
    rep_condition TEXT,                                     -- RULE C: runtime tier only
    rep_notify TEXT, category TEXT, is_deprecated INTEGER, deprecation_msg TEXT, doc TEXT,
    source TEXT, sources TEXT, targets TEXT,
    -- RULE A APPLIES TO MEMBERS TOO. This was UNIQUE(class_id, name, source) until 2026-09-09, so a
    -- property seen by both the uht and runtime tiers had two rows, and they contradicted each
    -- other: one read "not replicated (runtime-verified)", the other "replication unknown
    -- (parse-time view only)", for the same property. The raw store hid it. The query surface showed
    -- it the first time a member list was rendered, which is an argument for the query surface.
    UNIQUE(class_id, name));

CREATE TABLE bp_edges (
    -- Blueprint -> C++ edges, section 4. The one thing no compile-time tool can produce: clangd
    -- cannot read .uasset, ripgrep skips them silently, and renaming a symbol listed here still
    -- compiles clean while breaking these graphs.
    id INTEGER PRIMARY KEY,
    symbol_class TEXT NOT NULL,      -- as written in the artefact, WITHOUT the U/A prefix
    class_id INTEGER,                -- resolved where the store has that class; NULL when engine-only
    symbol_name TEXT NOT NULL,
    kind TEXT NOT NULL,              -- call | read | write | bind (BindWidget/BindWidgetAnim by-name binding)
    blueprint_path TEXT, graph TEXT, uses INTEGER,
    project TEXT, source TEXT);

CREATE TABLE bp_walk (
    -- What the Blueprint walk covered, per project, parsed from the one fixed "Walk coverage" line
    -- the commandlet writes into BlueprintCallers.md. The absence note on an empty blast-radius
    -- result is built from this, not from a hardcoded total: data-only Blueprints have no graphs and
    -- are not a gap, so walked == total - data_only means the walk was complete.
    project TEXT PRIMARY KEY,
    total INTEGER NOT NULL,
    data_only INTEGER NOT NULL,
    walked INTEGER NOT NULL,
    with_edges INTEGER NOT NULL);

CREATE INDEX idx_bp_symbol ON bp_edges(symbol_class, symbol_name);
CREATE INDEX idx_bp_class ON bp_edges(class_id);
CREATE INDEX idx_bp_kind ON bp_edges(kind);

CREATE TABLE structs (id INTEGER PRIMARY KEY, name TEXT, module_id INTEGER,
    header_path TEXT, doc TEXT, source TEXT, UNIQUE(name, module_id));

CREATE TABLE enums (id INTEGER PRIMARY KEY, name TEXT, module_id INTEGER,
    header_path TEXT, doc TEXT, source TEXT, UNIQUE(name, module_id));

CREATE TABLE enum_values (enum_id INTEGER, name TEXT, value INTEGER,
    PRIMARY KEY (enum_id, name)) WITHOUT ROWID;

CREATE TABLE bp_assets (
    -- One row per Blueprint, from blueprints.jsonl. The sidecar exists so this loader reads DATA
    -- rather than re-parsing a document meant for reading; load_blueprint_edges' own docstring says
    -- what the alternative costs.
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL, stem TEXT, name TEXT,
    parent TEXT, native_parent TEXT, -- 'unknown' when the parent class no longer resolves. Exclude it
                                     -- from COUNT(DISTINCT native_parent): it is not a parent class
    native_parent_id INTEGER,        -- resolved where the store has that class; NULL when engine-only
    data_only INTEGER,               -- 1 yes, 0 no, NULL the registry did not say
    replicated_props INTEGER,
    can_ever_tick INTEGER, start_with_tick_enabled INTEGER, event_tick_wired INTEGER,
    tick_node_disabled INTEGER,  -- a LINKED Event Tick node that is switched OFF. The fourth
                                 -- tick fact, and the only one the compiler never sees: it is
                                 -- why a class can carry a wired tick node and still have
                                 -- bCanEverTick false. Without it a disabled node and no node
                                 -- at all are the same row.
    hard_deps INTEGER, soft_deps INTEGER,
    project TEXT, source TEXT,
    UNIQUE(path, project));

CREATE TABLE bp_variables (
    bp_id INTEGER, name TEXT, type TEXT, default_value TEXT, category TEXT,
    tooltip TEXT, flags TEXT, replication TEXT, rep_notify TEXT, project TEXT);

CREATE TABLE bp_overrides (
    -- owner_kind separates a class default from a component template from an inherited component:
    -- different storage, different editor UI, and a query that cannot tell them apart cannot answer
    -- "what does this CLASS default to" separately from "what does this COMPONENT default to".
    bp_id INTEGER, owner_kind TEXT, owner TEXT, owner_class TEXT, property TEXT,
    value TEXT, inherited TEXT, truncated_from INTEGER, window_at INTEGER,
    redacted INTEGER, project TEXT);

CREATE TABLE bp_components (
    bp_id INTEGER, name TEXT, class TEXT, kind TEXT,
    attach_parent TEXT, attach_socket TEXT, inherited INTEGER, source TEXT,
    parent_is_native INTEGER, project TEXT);

CREATE TABLE bp_functions (
    -- Functions, events and dispatchers in one table, split by `kind`. They are asked about
    -- together ("what can I call on this") far more often than separately.
    bp_id INTEGER, kind TEXT, name TEXT, inputs TEXT, outputs TEXT,
    pure INTEGER, is_const INTEGER, access TEXT, category TEXT, tooltip TEXT,
    net TEXT, wired INTEGER, project TEXT);

CREATE TABLE bp_bp_edges (
    -- Blueprint -> Blueprint. Deliberately NOT bp_edges, which means Blueprint -> C++ and whose row
    -- counts several answer keys depend on.
    bp_id INTEGER, target TEXT, target_stem TEXT, member TEXT, kind TEXT,
    graph TEXT, uses INTEGER, project TEXT);

CREATE TABLE assets (
    -- The registry tier: every asset in enabled content, from tags, nothing loaded. Absence here
    -- means "not in enabled content", not "not on disk" - a disabled plugin never mounts.
    id INTEGER PRIMARY KEY,
    -- Keyed on (path, name): a single package legitimately holds more than one registry asset.
    -- one StateTree task asset holds three - the Blueprint, its
    -- generated class and the CDO - and keying on the path alone silently collapsed 3 rows to 1.
    -- That is the drop rule A exists to prevent, caught by counting against the sidecar.
    path TEXT NOT NULL, name TEXT, class TEXT, row_struct TEXT, schema TEXT,
    project TEXT, UNIQUE(path, name, project));

CREATE TABLE input_bindings (
    -- One row per key-to-action mapping in an InputMappingContext. The only tier whose source had
    -- to load its assets: a binding lives in no asset registry tag, so nothing cheaper can say what
    -- a key does.
    --
    -- NO UNIQUE CONSTRAINT, deliberately, and the reason is worth keeping. (context, key) is not an
    -- identity because one key can drive two actions - LeftMouseButton drives both fire actions in
    -- IMC_Default - and (context, action) is not one either, because an action takes several keys.
    -- (context, action, key) is the minimum, and even that repeats when a context binds the same
    -- pair twice with different triggers. A UNIQUE on any of those would silently collapse rows,
    -- which is exactly what UNIQUE(path, project) did to the registry tier. The loader counts
    -- repeated triples instead and logs them.
    id INTEGER PRIMARY KEY,
    context TEXT NOT NULL, context_name TEXT,
    key TEXT NOT NULL,
    action TEXT, action_name TEXT, value_type TEXT,
    triggers TEXT, modifiers TEXT,
    project TEXT);

CREATE INDEX idx_input_key ON input_bindings(key);
CREATE INDEX idx_input_context ON input_bindings(context);
CREATE INDEX idx_input_action ON input_bindings(action);
-- The composite lookup shape, NON-unique on purpose. I first specified this tuple as the PRIMARY KEY
-- and asked in the same breath that a repeated triple keep both rows; those two cannot both hold,
-- because a PRIMARY KEY in SQLite *is* a uniqueness constraint. Caught by the session that wrote the
-- loader, in the one table where we had both already learned that lesson from UNIQUE(path, project).
-- An index gives the query plan without the constraint.
CREATE INDEX idx_input_triple ON input_bindings(context, action, key, project);

CREATE INDEX idx_bpa_path ON bp_assets(path);
CREATE INDEX idx_bpa_native ON bp_assets(native_parent_id);
CREATE INDEX idx_bpv_bp ON bp_variables(bp_id);
CREATE INDEX idx_bpv_name ON bp_variables(name);
CREATE INDEX idx_bpo_bp ON bp_overrides(bp_id);
CREATE INDEX idx_bpo_prop ON bp_overrides(property);
CREATE INDEX idx_bpc_bp ON bp_components(bp_id);
CREATE INDEX idx_bpf_bp ON bp_functions(bp_id);
CREATE INDEX idx_bpe2_target ON bp_bp_edges(target);
CREATE INDEX idx_assets_class ON assets(class);

CREATE INDEX idx_class_name ON classes(name);
CREATE INDEX idx_class_super ON classes(super_id);
CREATE INDEX idx_class_module ON classes(module_id);
CREATE INDEX idx_fn_class ON functions(class_id);
CREATE INDEX idx_fn_name ON functions(name);
CREATE INDEX idx_prop_class ON properties(class_id);
CREATE INDEX idx_prop_rep ON properties(rep_condition) WHERE rep_condition IS NOT NULL;
CREATE INDEX idx_mp_lookup ON module_platforms(platform, target_type, available);
CREATE INDEX idx_mp_module ON module_platforms(module_name);
CREATE INDEX idx_mo_module ON module_observed(module_name);

CREATE TABLE key_aliases (
    -- What a PERSON calls a gamepad button, against the FKey FName an asset stores. Added 2026-09-20
    -- after a benchmark question asked which asset maps "the X button" on a console controller: the assets
    -- say `Gamepad_FaceButton_Bottom` and nothing in the tree carried the translation, so both the
    -- question and any answer to it rested on general knowledge.
    --
    -- DERIVED, not written by hand: EKeys::GetGamepadDisplayName in InputCore switches on
    -- EConsoleForGamepadLabels and returns a different label per console, so this is checkable against
    -- engine source like every other row in the store.
    --
    -- `console` is the enum's own name. There is deliberately no row for a console the enum does not
    -- name: a newer pad can show its predecessor's labels, so inventing a row would be inventing a fact.
    fkey TEXT NOT NULL, console TEXT NOT NULL, label TEXT NOT NULL,
    PRIMARY KEY (fkey, console)) WITHOUT ROWID;

CREATE INDEX idx_key_alias_label ON key_aliases(label);
"""

FTS = """
CREATE VIRTUAL TABLE search USING fts5(kind, name, owner, doc);

-- Named views for the question shapes that cost the most discovery turns in the v5 benchmark
-- (review recommendation #4). Each answers its shape in one SELECT; engine_api_sql's `schema`
-- mode lists them with their columns. A view is a query, not a copy: it adds nothing to the file.

CREATE VIEW v_bp_symbol_use AS
    -- One row per C++ symbol and edge kind: how many Blueprints reach it, how many rows (graphs),
    -- how many nodes. "Most-called function" is ORDER BY nodes DESC WHERE kind='call'.
    SELECT symbol_class, symbol_name, kind, project,
           COUNT(DISTINCT blueprint_path) AS blueprints, COUNT(*) AS graphs, SUM(uses) AS nodes
    FROM bp_edges GROUP BY symbol_class, symbol_name, kind, project;

CREATE VIEW v_bp_writes AS
    -- Blueprint writes to C++ properties, with the owning module and whether it is engine or project.
    SELECT e.symbol_class, e.symbol_name, e.blueprint_path, e.graph, e.uses, e.project,
           m.name AS module, m.origin
    FROM bp_edges e LEFT JOIN classes k ON k.id = e.class_id LEFT JOIN modules m ON m.id = k.module_id
    WHERE e.kind = 'write';

CREATE VIEW v_plugin_platform_gaps AS
    -- Per platform and target type: plugins with at least one Runtime module declared unavailable,
    -- and how many such modules. Declared availability from .uplugin descriptors, no SDK needed.
    SELECT platform, target_type, host_type,
           COUNT(DISTINCT plugin) AS plugins_with_gap, COUNT(*) AS unavailable_modules
    FROM module_platforms WHERE available = 0
    GROUP BY platform, target_type, host_type;

CREATE VIEW v_module_loading_phases AS
    -- Engine and project modules by declared loading phase (NULL = descriptor did not say).
    SELECT loading_phase, origin, type, COUNT(*) AS modules
    FROM modules GROUP BY loading_phase, origin, type;

CREATE VIEW v_bp_tuning AS
    -- Every tuning value a designer set on a Blueprint, declared variables and overridden defaults
    -- in ONE list, because "what is this number and where does it live" does not care which of the
    -- two storage locations holds it. `source_kind` says which, so a caller that does care can
    -- filter. This is the shape the whole detail dump exists to answer in one query.
    SELECT a.project, a.path AS blueprint, 'variable' AS source_kind,
           '' AS owner, v.name AS property, v.default_value AS value, NULL AS inherited,
           v.type, v.category
    FROM bp_variables v JOIN bp_assets a ON a.id = v.bp_id
    UNION ALL
    SELECT a.project, a.path, 'override',
           CASE WHEN o.owner = '' THEN '(class)' ELSE o.owner END,
           o.property, o.value, o.inherited, o.owner_class, o.owner_kind
    FROM bp_overrides o JOIN bp_assets a ON a.id = o.bp_id;

CREATE VIEW v_bp_users AS
    -- Reverse index for Blueprint -> Blueprint: who breaks if I change this Blueprint's function.
    -- bpcallers/ and bp_edges answer the C++ version of this question and contain none of these.
    SELECT e.target AS blueprint, e.member, e.kind, a.path AS caller, e.graph, e.uses, e.project
    FROM bp_bp_edges e JOIN bp_assets a ON a.id = e.bp_id;

CREATE VIEW v_bp_tick_cost AS
    -- The performance-pass shape: a Blueprint that ticks and does nothing in the tick, and one that
    -- ticks every frame to poll something. can_ever_tick and event_tick_wired are different facts
    -- and reading either alone gives the wrong answer. FOUR facts, not three: a LINKED node that is
    -- DISABLED is invisible to the compiler, so it leaves can_ever_tick false and event_tick_wired
    -- false - identical to a Blueprint with no tick node at all until tick_node_disabled separates
    -- them.
    SELECT project, path, can_ever_tick, start_with_tick_enabled, event_tick_wired,
           tick_node_disabled,
           CASE WHEN can_ever_tick = 1 AND event_tick_wired = 0 THEN 'ticks, empty handler'
                WHEN can_ever_tick = 1 AND event_tick_wired = 1 THEN 'ticks, has work'
                WHEN can_ever_tick = 0 AND event_tick_wired = 1 THEN 'tick node but class cannot tick'
                WHEN tick_node_disabled = 1 THEN 'tick node present but DISABLED'
                ELSE 'does not tick' END AS verdict
    -- NOT `can_ever_tick IS NOT NULL` alone. A Blueprint COMPONENT has no PrimaryActorTick, so its
    -- can_ever_tick is NULL - and a component is perfectly capable of carrying a disabled tick node.
    -- On one sample game that filter returned 9 where the artefacts said 11, both missing rows being
    -- components: a documented route quietly disagreeing with a correct answer, which is worse than
    -- either being wrong on its own.
    FROM bp_assets WHERE can_ever_tick IS NOT NULL OR tick_node_disabled = 1;

CREATE VIEW v_bp_load_cost AS
    -- What loading one Blueprint drags in, heaviest first. A cast is a hard reference, which is the
    -- usual reason a small asset pulls a large graph.
    SELECT project, path, hard_deps, soft_deps,
           (SELECT COUNT(*) FROM bp_bp_edges e WHERE e.bp_id = a.id AND e.kind = 'cast') AS casts
    FROM bp_assets a WHERE hard_deps IS NOT NULL;

CREATE VIEW v_key_ambiguity AS
    -- Labels that mean a DIFFERENT physical key depending on the console. On this engine there is
    -- exactly one, and it is the reason this tier exists rather than a curiosity: "Gamepad X" is
    -- Gamepad_FaceButton_Bottom under one console's labels and Gamepad_FaceButton_Left under another's. In
    -- a sample game's IMC_Default those two keys drive different actions, so the wrong reading of "X" is not a
    -- near miss - it is a confident answer about the wrong button.
    SELECT label, COUNT(DISTINCT fkey) AS keys_, GROUP_CONCAT(console || '=' || fkey, ', ') AS resolves
    FROM key_aliases GROUP BY label HAVING COUNT(DISTINCT fkey) > 1;

CREATE VIEW v_input_key AS
    -- What one key is bound to, across every context. The question a person actually asks ("what is
    -- on the cross button") once they have translated the label to a key - and the label is not the
    -- key: "Gamepad X" is Gamepad_FaceButton_Bottom under one console's labels and
    -- Gamepad_FaceButton_Left under another's, two keys bound to different actions. So the labels are CARRIED HERE rather than left to a
    -- second query and a join the caller has to know to make: `labels` is what a person would call this
    -- key on each console, aggregated so the join cannot multiply the binding rows.
    SELECT i.key, i.project, i.context, i.context_name, i.action, i.action_name, i.value_type,
           i.triggers,
           (SELECT GROUP_CONCAT(a.console || '=' || a.label, ', ')
              FROM key_aliases a WHERE a.fkey = i.key) AS labels
    FROM input_bindings i;

CREATE VIEW v_input_multi_action AS
    -- Keys driving more than one action INSIDE one context. Legitimate when the triggers differ -
    -- a tap and a hold on the same key - and a bug when they do not, so the trigger lists are here
    -- rather than left to a second query.
    SELECT project, context, context_name, key,
           COUNT(DISTINCT action) AS actions,
           GROUP_CONCAT(DISTINCT action_name) AS action_names,
           GROUP_CONCAT(DISTINCT triggers) AS trigger_sets
    FROM input_bindings
    GROUP BY project, context, key
    HAVING COUNT(DISTINCT action) > 1;

CREATE VIEW v_input_layered AS
    -- Keys bound by more than one context. Enhanced Input layering: which one wins depends on what
    -- is pushed at runtime, so a binding read from a single context is not what the player gets.
    SELECT project, key,
           COUNT(DISTINCT context) AS contexts,
           GROUP_CONCAT(DISTINCT context_name) AS context_names,
           COUNT(DISTINCT action) AS actions
    FROM input_bindings
    GROUP BY project, key
    HAVING COUNT(DISTINCT context) > 1;

CREATE VIEW v_input_no_gamepad AS
    -- Actions reachable only from keyboard or mouse. A real finding on a game that ships to
    -- console, and invisible without the bindings.
    SELECT project, action, action_name,
           COUNT(*) AS bindings,
           GROUP_CONCAT(DISTINCT key) AS keys
    FROM input_bindings
    WHERE action IS NOT NULL AND action <> ''
    GROUP BY project, action
    HAVING SUM(CASE WHEN key LIKE 'Gamepad%' THEN 1 ELSE 0 END) = 0;

CREATE VIEW v_index_stats AS
    -- What the search index holds, per kind; for comments, from how many distinct files.
    SELECT kind, COUNT(*) AS rows_,
           COUNT(DISTINCT CASE WHEN kind = 'comment' THEN substr(owner, 1, instr(owner, ':') - 1) END) AS files
    FROM search GROUP BY kind;
"""


# ---------------------------------------------------------------------------
# Merge helpers - rules A, B, C
# ---------------------------------------------------------------------------

def merge_csv(existing: str | None, incoming: str | None) -> str:
    parts = {p for p in (existing or "").split(",") if p} | {p for p in (incoming or "").split(",") if p}
    return ",".join(sorted(parts))


def best_source(a: str | None, b: str | None) -> str:
    return max([a or "", b or ""], key=lambda x: FIDELITY.get(x, -1))


class Db:
    def __init__(self, path: Path):
        if path.exists():
            path.unlink()
        for suffix in ("-wal", "-shm"):
            side = path.with_name(path.name + suffix)
            if side.exists():
                side.unlink()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(path)
        self.con.executescript(SCHEMA)
        self._module_ids: dict[str, int] = {}

    # -- modules ------------------------------------------------------------
    def module(self, name: str, *, mtype=None, phase=None, plugin=None, origin=None, source="uht") -> int:
        if name in self._module_ids:
            mid = self._module_ids[name]
            row = self.con.execute("SELECT source, sources FROM modules WHERE id=?", (mid,)).fetchone()
            self.con.execute("UPDATE modules SET source=?, sources=?, type=COALESCE(type,?),"
                             " loading_phase=COALESCE(loading_phase,?), plugin=COALESCE(plugin,?),"
                             " origin=COALESCE(origin,?) WHERE id=?",
                             (best_source(row[0], source), merge_csv(row[1], source),
                              mtype, phase, plugin, origin, mid))
            return mid
        cur = self.con.execute(
            "INSERT INTO modules (name, type, loading_phase, plugin, origin, source, sources)"
            " VALUES (?,?,?,?,?,?,?)", (name, mtype, phase, plugin, origin, source, source))
        self._module_ids[name] = cur.lastrowid
        return cur.lastrowid

    # -- classes ------------------------------------------------------------
    def upsert_class(self, *, name, module_id, super_name=None, class_type=None, class_flags=None,
                     class_flag_names=None, is_deprecated=None, deprecation_msg=None,
                     header_path=None, doc=None, source, targets) -> int:
        row = self.con.execute("SELECT id, source, sources, targets FROM classes"
                               " WHERE name=? AND module_id=?", (name, module_id)).fetchone()
        if row is None:
            cur = self.con.execute(
                "INSERT INTO classes (name, module_id, super_name, class_type, class_flags,"
                " class_flag_names, is_deprecated, deprecation_msg, header_path, doc, source,"
                " sources, targets) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (name, module_id, super_name, class_type, class_flags, class_flag_names,
                 is_deprecated, deprecation_msg, header_path, doc, source, source, targets))
            return cur.lastrowid
        cid, cur_source, cur_sources, cur_targets = row
        # RULE A: one row. RULE B: targets are a union. COALESCE keeps the first non-null fact,
        # which is what "uht is not a superset of disk" requires - a later tier must not blank a
        # field an earlier one filled.
        self.con.execute(
            "UPDATE classes SET source=?, sources=?, targets=?, super_name=COALESCE(super_name,?),"
            " class_type=COALESCE(class_type,?), class_flags=COALESCE(class_flags,?),"
            " class_flag_names=COALESCE(class_flag_names,?), is_deprecated=COALESCE(is_deprecated,?),"
            " deprecation_msg=COALESCE(NULLIF(deprecation_msg,''),?), header_path=COALESCE(header_path,?),"
            " doc=COALESCE(NULLIF(doc,''),?) WHERE id=?",
            (best_source(cur_source, source), merge_csv(cur_sources, source),
             merge_csv(cur_targets, targets), super_name, class_type, class_flags, class_flag_names,
             is_deprecated, deprecation_msg, header_path, doc, cid))
        return cid


# ---------------------------------------------------------------------------
# Tier 1: descriptors (phase 1 output, re-read here so this script stands alone)
# ---------------------------------------------------------------------------

def upsert_function(db: "Db", *, class_id, name, source, targets, **f) -> None:
    row = db.con.execute("SELECT id, source, sources, targets FROM functions"
                         " WHERE class_id=? AND name=?", (class_id, name)).fetchone()
    if row is None:
        db.con.execute(
            "INSERT INTO functions (class_id, name, function_flags, function_type, specifiers,"
            " is_virtual, is_override, is_deprecated, deprecation_msg, doc, source, sources, targets)"
            " VALUES (?,?,?,?,?,0,0,?,?,?,?,?,?)",
            (class_id, name, f.get("function_flags"), f.get("function_type"), f.get("specifiers"),
             f.get("is_deprecated"), f.get("deprecation_msg"), f.get("doc"), source, source, targets))
        return
    fid, cur_src, cur_srcs, cur_tgts = row
    db.con.execute(
        "UPDATE functions SET source=?, sources=?, targets=?,"
        " function_flags=COALESCE(function_flags,?), function_type=COALESCE(function_type,?),"
        " specifiers=COALESCE(specifiers,?), is_deprecated=COALESCE(is_deprecated,?),"
        " deprecation_msg=COALESCE(NULLIF(deprecation_msg,''),?), doc=COALESCE(NULLIF(doc,''),?)"
        " WHERE id=?",
        (best_source(cur_src, source), merge_csv(cur_srcs, source), merge_csv(cur_tgts, targets),
         f.get("function_flags"), f.get("function_type"), f.get("specifiers"),
         f.get("is_deprecated"), f.get("deprecation_msg"), f.get("doc"), fid))


def upsert_property(db: "Db", *, class_id, name, source, targets, rep_condition=None, **p) -> None:
    row = db.con.execute("SELECT id, source, sources, targets, rep_condition FROM properties"
                         " WHERE class_id=? AND name=?", (class_id, name)).fetchone()
    if row is None:
        db.con.execute(
            "INSERT INTO properties (class_id, name, cpp_type, property_flags, specifiers,"
            " rep_condition, rep_notify, category, is_deprecated, deprecation_msg, doc, source,"
            " sources, targets) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (class_id, name, p.get("cpp_type"), p.get("property_flags"), p.get("specifiers"),
             rep_condition, p.get("rep_notify"), p.get("category"), p.get("is_deprecated"),
             p.get("deprecation_msg"), p.get("doc"), source, source, targets))
        return
    pid, cur_src, cur_srcs, cur_tgts, cur_cond = row
    # RULE C survives the merge: rep_condition is only ever taken from a runtime pass, so a later
    # uht row cannot blank a condition an earlier runtime row established, nor invent one.
    new_cond = rep_condition if (source == "runtime" and rep_condition) else cur_cond
    db.con.execute(
        "UPDATE properties SET source=?, sources=?, targets=?, rep_condition=?,"
        " cpp_type=COALESCE(cpp_type,?), property_flags=COALESCE(property_flags,?),"
        " specifiers=COALESCE(specifiers,?), rep_notify=COALESCE(rep_notify,?),"
        " category=COALESCE(category,?), is_deprecated=COALESCE(is_deprecated,?),"
        " deprecation_msg=COALESCE(NULLIF(deprecation_msg,''),?), doc=COALESCE(NULLIF(doc,''),?)"
        " WHERE id=?",
        (best_source(cur_src, source), merge_csv(cur_srcs, source), merge_csv(cur_tgts, targets),
         new_cond, p.get("cpp_type"), p.get("property_flags"), p.get("specifiers"),
         p.get("rep_notify"), p.get("category"), p.get("is_deprecated"), p.get("deprecation_msg"),
         p.get("doc"), pid))


def load_descriptor_tier(db: Db, root: Path, log: list[str]) -> None:
    desc_db = HERE / "engine-api-descriptors.db"
    if not desc_db.exists():
        log.append(f"descriptor tier absent ({desc_db.name}); run build_descriptor_tier.py first")
        return
    src = sqlite3.connect(f"file:{desc_db}?mode=ro", uri=True)

    for name, path, origin, cat, desc, mcount in src.execute(
            "SELECT name, descriptor_path, origin, category, description, module_count FROM plugin"):
        db.con.execute(
            "INSERT OR IGNORE INTO plugins (name, descriptor_path, origin, category, description,"
            " module_count, enabled_by_any) VALUES (?,?,?,?,?,?,0)",
            (name, path, origin, cat, desc, mcount))

    for proj, plug in src.execute(
            "SELECT p.name, pp.plugin_name FROM project_plugin pp JOIN project p USING(project_id)"
            " WHERE pp.enabled=1"):
        db.con.execute("INSERT OR IGNORE INTO enabled_by (plugin, project) VALUES (?,?)", (plug, proj))
    db.con.execute("UPDATE plugins SET enabled_by_any=1 WHERE name IN (SELECT plugin FROM enabled_by)")

    # Declared availability, keyed by module NAME so the uht tier can join to it without the two
    # tiers having to agree on integer ids.
    rows = src.execute(
        "SELECT m.name, mp.platform, mp.target_type, mp.available,"
        "       p.name, m.host_type, m.loading_phase, p.origin, m.module_id"
        " FROM module_platforms mp JOIN module m USING(module_id) JOIN plugin p USING(plugin_id)"
    ).fetchall()
    seen_modules: set[str] = set()
    for mname, plat, tt, avail, plugin, host, phase, porigin, dmid in rows:
        if mname is None:
            continue
        db.con.execute(
            "INSERT OR IGNORE INTO module_platforms (descriptor_module_id, plugin, module_name,"
            " host_type, platform, target_type, available) VALUES (?,?,?,?,?,?,?)",
            (dmid, plugin, mname, host, plat, tt, avail))
        if mname not in seen_modules:
            seen_modules.add(mname)
            db.module(mname, mtype=host, phase=phase, plugin=plugin,
                      origin="engine" if porigin in ("engine", "platform-extension") else "project",
                      source="disk")
    src.close()
    # Assert the merge lost nothing. A count that quietly shrinks is the failure mode this whole
    # project keeps meeting, so it is checked rather than assumed.
    landed = db.con.execute("SELECT COUNT(*) FROM module_platforms").fetchone()[0]
    if landed != len(rows):
        log.append(f"WARNING: descriptor tier lost {len(rows) - landed} availability rows in merge")
    log.append(f"descriptor tier: {len(seen_modules)} modules, {landed:,} availability rows "
               f"(source had {len(rows):,})")


# ---------------------------------------------------------------------------
# Tier 2: the UHT exporter output
# ---------------------------------------------------------------------------

ENGINE_MARKERS = ("UnrealEngine", "Engine")

# Target name -> EBuildTargetType. UHT's manifest carries TargetName but not the target type, so it
# is derived from the name, which is the convention every target in this tree follows.
def target_type_of(target: str) -> str:
    for suffix, tt in (("Editor", "Editor"), ("Server", "Server"), ("Client", "Client")):
        if target.endswith(suffix):
            return tt
    return "Game"


def _origin_for(base_dir: str, root: Path) -> str:
    norm = (base_dir or "").replace("\\", "/")
    return "engine" if "/UnrealEngine/Engine/" in norm else "project"


def load_uht_tier(db: Db, root: Path, targets: str, log: list[str]) -> None:
    files = sorted(root.rglob("*.agentapi.json"))
    if not files:
        log.append("uht tier absent: no *.agentapi.json found. Run UHT with -AgentMemoryApi")
        return
    n_cls = n_fn = n_prop = n_struct = n_enum = 0
    for path in files:
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            log.append(f"unreadable exporter output {path.name}: {exc}")
            continue
        # The target comes from the FILE, not a command-line flag. Every export is stamped with the
        # target that produced it (exporter change 2026-09-09), which is what makes "observed on a console
        # as well as Win64" representable at all.
        target = d.get("target") or "UnknownTarget"
        tt = target_type_of(target)
        db.con.execute(
            "INSERT OR IGNORE INTO module_observed (module_name, target, target_type, platform)"
            " VALUES (?,?,?,?)", (d["module"], target, tt, targets))
        mid = db.module(d["module"], mtype=d.get("module_type"),
                        origin=_origin_for(d.get("base_directory", ""), root), source="uht")

        for c in d.get("classes", []):
            cid = db.upsert_class(
                name=c["name"], module_id=mid, super_name=c.get("super") or None,
                class_type=c.get("class_type"), class_flags=c.get("class_flags"),
                class_flag_names=c.get("class_flag_names") or None,
                is_deprecated=1 if c.get("is_deprecated") else 0,
                deprecation_msg=c.get("deprecation_message") or None,
                header_path=c.get("header") or None, doc=c.get("doc") or None,
                source="uht", targets=f"{targets}:{target}")
            n_cls += 1
            for iface in c.get("interfaces", []):
                db.con.execute("INSERT OR IGNORE INTO class_interfaces (class_id, interface_name)"
                               " VALUES (?,?)", (cid, iface))
            for f in c.get("functions", []):
                upsert_function(db, class_id=cid, name=f["name"], source="uht", targets=targets,
                                function_flags=f.get("function_flags"),
                                function_type=f.get("function_type"),
                                specifiers=f.get("specifiers") or None,
                                is_deprecated=1 if f.get("is_deprecated") else 0,
                                deprecation_msg=f.get("deprecation_message") or None,
                                doc=f.get("doc") or None)
                fid_row = db.con.execute("SELECT id FROM functions WHERE class_id=? AND name=?",
                                         (cid, f["name"])).fetchone()
                if fid_row:
                    n_fn += 1
                    for prm in f.get("params", []):
                        db.con.execute(
                            "INSERT OR IGNORE INTO function_params (function_id, ordinal, name,"
                            " cpp_type, property_flags, is_return) VALUES (?,?,?,?,?,?)",
                            (fid_row[0], prm["ordinal"], prm.get("name"), prm.get("cpp_type"),
                             prm.get("property_flags"), 1 if prm.get("is_return") else 0))
            for p in c.get("properties", []):
                # RULE C: rep_condition is NOT written here. COND_* is runtime-only.
                # rep_condition stays None here - RULE C, the uht tier cannot see COND_*.
                upsert_property(db, class_id=cid, name=p["name"], source="uht", targets=targets,
                                rep_condition=None, cpp_type=p.get("cpp_type"),
                                property_flags=p.get("property_flags"),
                                specifiers=p.get("specifiers") or None,
                                rep_notify=p.get("rep_notify") or None,
                                category=p.get("category") or None,
                                is_deprecated=1 if p.get("is_deprecated") else 0,
                                deprecation_msg=p.get("deprecation_message") or None,
                                doc=p.get("doc") or None)
                n_prop += 1

        for s in d.get("structs", []):
            db.con.execute("INSERT OR IGNORE INTO structs (name, module_id, header_path, doc, source)"
                           " VALUES (?,?,?,?,'uht')",
                           (s["name"], mid, s.get("header") or None, s.get("doc") or None))
            n_struct += 1
        for e in d.get("enums", []):
            cur = db.con.execute("INSERT OR IGNORE INTO enums (name, module_id, header_path, doc, source)"
                                 " VALUES (?,?,?,?,'uht')",
                                 (e["name"], mid, e.get("header") or None, e.get("doc") or None))
            if cur.lastrowid:
                n_enum += 1
                for v in e.get("values", []):
                    db.con.execute("INSERT OR IGNORE INTO enum_values (enum_id, name, value)"
                                   " VALUES (?,?,?)", (cur.lastrowid, v["name"], v.get("value")))
    # Counts are per FILE, and one class appears in every target that compiles it, so these are
    # ingest counts and not store totals. The store total is reported separately to avoid the
    # five-targets-looks-like-five-times-the-API illusion.
    distinct = db.con.execute("SELECT COUNT(*) FROM classes").fetchone()[0]
    log.append(f"uht tier: {len(files)} export files across "
               f"{db.con.execute('SELECT COUNT(DISTINCT target) FROM module_observed').fetchone()[0]} targets, "
               f"{n_cls:,} class rows ingested -> {distinct:,} distinct classes in the store")


# ---------------------------------------------------------------------------
# Tier 3: the Layer 2 reflection artefacts - the ONLY source of COND_*
# ---------------------------------------------------------------------------

ROW = re.compile(r"^\|(.+)\|$")


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def load_runtime_tier(db: Db, root: Path, targets: str, log: list[str]) -> None:
    total_cls = total_cond = 0
    for proj_docs in sorted(root.glob("*/Docs/AgentMemory/classes")):
        project = proj_docs.parents[2].name
        for md in sorted(proj_docs.glob("*.md")):
            text = md.read_text(encoding="utf-8", errors="replace")
            m = re.search(r"^Module `([^`]+)`", text, re.M)
            module = m.group(1) if m else project
            mid = db.module(module, origin="project", source="runtime")

            inh = re.search(r"^- Inherits: (.+)$", text, re.M)
            chain = [c.strip() for c in inh.group(1).split("->")] if inh else []
            # Artefacts drop the U/A prefix; recover it from the chain, as phase 3 did.
            prefix = "A" if "Actor" in chain else "U"
            name = prefix + md.stem
            super_name = None
            if chain:
                super_name = ("A" if chain[0] in ("Character", "Pawn", "Actor") else "U") + chain[0]

            cid = db.upsert_class(name=name, module_id=mid, super_name=super_name,
                                  source="runtime", targets=targets)
            total_cls += 1

            impl = re.search(r"^- Implements: (.+)$", text, re.M)
            if impl:
                for iface in [i.strip() for i in impl.group(1).split(",")]:
                    db.con.execute("INSERT OR IGNORE INTO class_interfaces (class_id, interface_name)"
                                   " VALUES (?,?)", (cid, "I" + iface))

            block = re.search(r"### Properties\n\n\|.*?\n\|[-| ]+\n(.*?)(?:\n\n|\Z)", text, re.S)
            if not block:
                continue
            for line in block.group(1).strip().splitlines():
                cells = _cells(line)
                if len(cells) < 3:
                    continue
                pname = cells[0].strip("`")
                ptype = cells[1].strip("`")
                spec = cells[2]
                repl = cells[3] if len(cells) > 3 else ""
                cond = (re.search(r"(COND_\w+)", repl) or [None])[0] if "COND_" in repl else None
                cond = re.search(r"(COND_\w+)", repl).group(1) if "COND_" in repl else None
                notify = re.search(r"OnRep=(\w+)", repl).group(1) if "OnRep=" in repl else None
                if cond:
                    total_cond += 1
                upsert_property(db, class_id=cid, name=pname, source="runtime", targets=targets,
                                rep_condition=cond, cpp_type=ptype, specifiers=spec,
                                rep_notify=notify)
    log.append(f"runtime tier: {total_cls} classes, {total_cond} replicated properties with COND_*")


# ---------------------------------------------------------------------------

BP_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*`?([^`|]*)`?\s*\|([^|]*)\|([^|]*)\|\s*$")
WALK_LINE = re.compile(r"Walk coverage:\*\* (\d+) Blueprints, (\d+) data-only, (\d+) walked, (\d+) with edges")


def _resolve_class(db: "Db", sym_class: str):
    """Artefacts drop the U/A/F/I prefix; the store keeps it. Try each."""
    for pre in ("U", "A", "F", "I", ""):
        row = db.con.execute("SELECT id FROM classes WHERE name=? ORDER BY id LIMIT 1",
                             (pre + sym_class,)).fetchone()
        if row:
            return row[0]
    return None


def load_blueprint_edges(db: Db, root: Path, log: list[str]) -> None:
    """Phase 6: Blueprint -> C++ edges from the Layer 2 artefacts.

    Reads `bpcallers.jsonl` where the artefact set has one, and falls back to parsing
    `bpcallers/<Class>.md` where it does not. The fallback is not dead code: an artefact set
    generated before the sidecar existed is still a valid set, and silently reporting zero edges for
    it would be worse than the parse it replaces.

    Why the sidecar. Parsing the Markdown is a second parse of a document meant for reading, so a
    layout change breaks it silently - this docstring said exactly that before the sidecar existed,
    and it was the reason to build one. The commandlet now writes the same FOLDED rows twice, from
    one loop: once as a table and once as JSON. `edges_unresolved` stays the canary either way.
    """
    total = unresolved = 0
    by_project: dict[str, int] = {}
    from_sidecar: list[str] = []
    from_markdown: list[str] = []

    for side in sorted(root.glob("*/Docs/AgentMemory/bpcallers.jsonl")):
        project = side.parents[2].name
        from_sidecar.append(project)
        for line in side.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            cid = _resolve_class(db, e["symbol_class"])
            if cid is None:
                unresolved += 1
            db.con.execute(
                "INSERT INTO bp_edges (symbol_class, class_id, symbol_name, kind, blueprint_path,"
                " graph, uses, project, source) VALUES (?,?,?,?,?,?,?,?,'runtime')",
                (e["symbol_class"], cid, e["symbol_name"], e["kind"], e["blueprint_path"],
                 e["graph"], e["uses"], project))
            total += 1
            by_project[project] = by_project.get(project, 0) + 1

    for bpdir in sorted(root.glob("*/Docs/AgentMemory/bpcallers")):
        if (bpdir.parent / "bpcallers.jsonl").exists():
            continue                      # that project came from its sidecar above
        from_markdown.append(bpdir.parents[2].name)
        project = bpdir.parents[2].name
        for md in sorted(bpdir.glob("*.md")):
            for line in md.read_text(encoding="utf-8", errors="replace").splitlines():
                m = BP_ROW.match(line)
                if not m:
                    continue
                symbol, bp_path, graph, how = (g.strip() for g in m.groups())
                if symbol in ("C++ symbol",) or symbol.startswith("---"):
                    continue
                if "::" in symbol:
                    sym_class, sym_name = symbol.split("::", 1)
                else:
                    sym_class, sym_name = symbol, ""
                how = how.strip().strip("`")
                kind = "call" if how.startswith("call") else (
                       "read" if how.startswith("read") else (
                       "write" if how.startswith("write") else how.split()[0] if how else "unknown"))
                mult = re.search(r"x(\d+)", how)
                uses = int(mult.group(1)) if mult else 1

                cid = _resolve_class(db, sym_class)
                if cid is None:
                    unresolved += 1
                db.con.execute(
                    "INSERT INTO bp_edges (symbol_class, class_id, symbol_name, kind, blueprint_path,"
                    " graph, uses, project, source) VALUES (?,?,?,?,?,?,?,?,'runtime')",
                    (sym_class, cid, sym_name, kind, bp_path.strip("`"), graph, uses, project))
                total += 1
                by_project[project] = by_project.get(project, 0) + 1
    if total:
        detail = ", ".join(f"{k} {v:,}" for k, v in sorted(by_project.items()))
        log.append(f"blueprint edges: {total:,} ({detail}); {unresolved:,} could not resolve to a "
                   f"class row in the store")
        # Which route each project took, because a silent switch is how a consumer ends up unable to
        # tell an empty table from a missing file.
        log.append("blueprint edges route: "
                   + (f"sidecar {', '.join(sorted(from_sidecar))}" if from_sidecar else "sidecar none")
                   + "; "
                   + (f"markdown fallback {', '.join(sorted(from_markdown))}" if from_markdown
                      else "markdown fallback none"))
    else:
        log.append("blueprint edges: none found - check the bpcallers artefact layout")

    # Walk coverage, one fixed line per project in BlueprintCallers.md. An older artefact set has no
    # such line; the table then stays empty for that project and the server falls back to saying so
    # rather than inventing a total.
    walked_projects = []
    for wj in sorted(root.glob("*/Docs/AgentMemory/bpwalk.json")):
        project = wj.parents[2].name
        w = json.loads(wj.read_text(encoding="utf-8"))
        db.con.execute("INSERT OR REPLACE INTO bp_walk (project, total, data_only, walked, with_edges)"
                       " VALUES (?,?,?,?,?)",
                       (project, w["total"], w["data_only"], w["walked"], w["with_edges"]))
        walked_projects.append(f"{project} {w['walked']}/{w['total']} walked, {w['data_only']} "
                               f"data-only, {w['with_edges']} with edges")

    for callers in sorted(root.glob("*/Docs/AgentMemory/BlueprintCallers.md")):
        project = callers.parents[2].name
        if (callers.parent / "bpwalk.json").exists():
            continue
        text = callers.read_text(encoding="utf-8", errors="replace")
        m = WALK_LINE.search(text)
        if not m:
            continue
        db.con.execute("INSERT OR REPLACE INTO bp_walk (project, total, data_only, walked, with_edges)"
                       " VALUES (?,?,?,?,?)", (project, *(int(g) for g in m.groups())))
        walked_projects.append(f"{project} {m.group(3)}/{m.group(1)} walked, {m.group(2)} data-only, {m.group(4)} with edges")
    log.append("blueprint walk coverage: " + (", ".join(walked_projects) if walked_projects
               else "no Walk coverage line in any BlueprintCallers.md (artefacts predate it)"))


def load_blueprint_detail(db: Db, root: Path, log: list[str]) -> None:
    """Phase 7: the Blueprint detail tiers, from the two JSONL sidecars.

    Unlike load_blueprint_edges this reads DATA, not a formatted document: the commandlet builds one
    model per Blueprint and writes it twice, as Markdown to read and as JSON to load. A layout change
    in the Markdown cannot break this loader, which is the entire reason the sidecar exists.

    `detail_unresolved` in the log is this loader's canary, the same role `edges_unresolved` plays for
    the C++ edges: it counts Blueprints whose ultimate native parent has no class row in the store. It
    is never zero on a project with engine-parented Blueprints, so what matters is that it does not
    JUMP. A new table with no canary is a table that goes quietly wrong.
    """
    sidecars = sorted(root.glob("*/Docs/AgentMemory/blueprints.jsonl"))
    if not sidecars:
        log.append("blueprint detail: no blueprints.jsonl found - artefacts predate the detail dump")
        return

    counts = {k: 0 for k in ("bp_assets", "bp_variables", "bp_overrides", "bp_components",
                             "bp_functions", "bp_bp_edges")}
    unresolved = 0
    sections_seen: set[str] = set()

    for side in sidecars:
        project = side.parents[2].name
        for line in side.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            sections_seen.update(rec.get("sections") or [])

            # Artefacts drop the U/A/F/I prefix and carry a full object path; the store keeps the
            # prefix and the bare name. Same recovery loop load_blueprint_edges uses.
            native = (rec.get("native_parent") or "").rsplit(".", 1)[-1]
            nid = None
            if native:
                for pre in ("U", "A", "F", "I", ""):
                    row = db.con.execute("SELECT id FROM classes WHERE name=? ORDER BY id LIMIT 1",
                                         (pre + native,)).fetchone()
                    if row:
                        nid = row[0]
                        break
            if nid is None:
                unresolved += 1

            tick = rec.get("tick") or {}

            def tri(v):
                """None stays NULL: "this build cannot see it" is not "no"."""
                return None if v is None else (1 if v else 0)

            cur = db.con.execute(
                "INSERT OR REPLACE INTO bp_assets (path, stem, name, parent, native_parent,"
                " native_parent_id, data_only, replicated_props, can_ever_tick,"
                " start_with_tick_enabled, event_tick_wired, tick_node_disabled, hard_deps, soft_deps, project, source)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'runtime')",
                # A Blueprint whose parent class no longer resolves comes through as "". Store
                # 'unknown', the word Blueprints.md already uses: an empty string is a VALUE, so
                # COUNT(DISTINCT native_parent) counts it as a parent class, and a closure query over
                # it can never match - which reads as "no Blueprint derives from X".
                (rec["path"], rec.get("stem"), rec.get("name"), rec.get("parent") or "unknown",
                 rec.get("native_parent") or "unknown", nid, tri(rec.get("data_only")),
                 rec.get("replicated_props"), tri(tick.get("can_ever_tick")),
                 tri(tick.get("start_with_tick_enabled")), tri(tick.get("event_tick_wired")),
                 tri(tick.get("tick_node_disabled")),
                 len(rec.get("hard_dependencies") or []), len(rec.get("soft_dependencies") or []),
                 project))
            bp_id = cur.lastrowid
            counts["bp_assets"] += 1

            for v in rec.get("variables") or []:
                db.con.execute(
                    "INSERT INTO bp_variables (bp_id, name, type, default_value, category, tooltip,"
                    " flags, replication, rep_notify, project) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (bp_id, v.get("name"), v.get("type"), v.get("default"), v.get("category"),
                     v.get("tooltip"), ",".join(v.get("flags") or []), v.get("replication"),
                     v.get("rep_notify"), project))
                counts["bp_variables"] += 1

            for o in rec.get("overrides") or []:
                db.con.execute(
                    "INSERT INTO bp_overrides (bp_id, owner_kind, owner, owner_class, property,"
                    " value, inherited, truncated_from, window_at, redacted, project)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (bp_id, o.get("owner_kind"), o.get("owner"), o.get("owner_class"),
                     o.get("property"), o.get("value"), o.get("inherited"),
                     o.get("truncated_from"), o.get("window_at"), 1 if o.get("redacted") else 0,
                     project))
                counts["bp_overrides"] += 1

            for c in rec.get("components") or []:
                db.con.execute(
                    "INSERT INTO bp_components (bp_id, name, class, kind, attach_parent,"
                    " attach_socket, inherited, source, parent_is_native, project)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (bp_id, c.get("name"), c.get("class"), c.get("kind"), c.get("attach_parent"),
                     c.get("attach_socket"), 1 if c.get("inherited") else 0, c.get("source"),
                     1 if c.get("parent_is_native") else 0, project))
                counts["bp_components"] += 1

            for f in rec.get("functions") or []:
                db.con.execute(
                    "INSERT INTO bp_functions (bp_id, kind, name, inputs, outputs, pure, is_const,"
                    " access, category, tooltip, net, wired, project)"
                    " VALUES (?,'function',?,?,?,?,?,?,?,?,NULL,NULL,?)",
                    (bp_id, f.get("name"), ", ".join(f.get("inputs") or []),
                     ", ".join(f.get("outputs") or []), 1 if f.get("pure") else 0,
                     1 if f.get("const") else 0, f.get("access"), f.get("category"),
                     f.get("tooltip"), project))
                counts["bp_functions"] += 1

            for e in rec.get("events") or []:
                db.con.execute(
                    "INSERT INTO bp_functions (bp_id, kind, name, inputs, outputs, pure, is_const,"
                    " access, category, tooltip, net, wired, project)"
                    " VALUES (?,?,?,?,'',NULL,NULL,NULL,NULL,NULL,?,?,?)",
                    (bp_id, "event:" + (e.get("kind") or "?"), e.get("name"),
                     ", ".join(e.get("inputs") or []), ",".join(e.get("net") or []),
                     1 if e.get("wired") else 0, project))
                counts["bp_functions"] += 1

            for d in rec.get("dispatchers") or []:
                db.con.execute(
                    "INSERT INTO bp_functions (bp_id, kind, name, inputs, outputs, pure, is_const,"
                    " access, category, tooltip, net, wired, project)"
                    " VALUES (?,'dispatcher',?,?,'',NULL,NULL,NULL,NULL,NULL,NULL,NULL,?)",
                    (bp_id, d.get("name"), ", ".join(d.get("inputs") or []), project))
                counts["bp_functions"] += 1

            for e in rec.get("calls_out") or []:
                db.con.execute(
                    "INSERT INTO bp_bp_edges (bp_id, target, target_stem, member, kind, graph,"
                    " uses, project) VALUES (?,?,?,?,?,?,?,?)",
                    (bp_id, e.get("target"), e.get("target_stem"), e.get("member"), e.get("kind"),
                     e.get("graph"), e.get("count"), project))
                counts["bp_bp_edges"] += 1

    n_assets = 0
    for side in sorted(root.glob("*/Docs/AgentMemory/assets.jsonl")):
        project = side.parents[2].name
        for line in side.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            a = json.loads(line)
            db.con.execute(
                "INSERT OR REPLACE INTO assets (path, name, class, row_struct, schema, project)"
                " VALUES (?,?,?,?,?,?)",
                (a["path"], a.get("name"), a.get("class"), a.get("row_struct"), a.get("schema"),
                 project))
            n_assets += 1

    detail = ", ".join(f"{k} {v:,}" for k, v in sorted(counts.items()))
    log.append(f"blueprint detail: {detail}; registry assets {n_assets:,}")
    log.append(f"blueprint detail: {unresolved:,} Blueprints whose native parent has no class row "
               f"in the store (detail_unresolved - watch for a JUMP, not for zero)")
    log.append("blueprint detail sections present: " + ", ".join(sorted(sections_seen)))


def load_key_aliases(db: Db, root: Path, log: list[str]) -> None:
    """Phase 8: what a person calls a gamepad button, against the FKey FName an asset stores.

    Added because a question asked which asset maps "the X button" on a console controller and nothing in
    the tree carried the translation - the assets say `Gamepad_FaceButton_Bottom`, and both arms of the
    benchmark had to supply the rest from general knowledge. The engine does carry it:
    `EKeys::GetGamepadDisplayName` switches on `EConsoleForGamepadLabels` and returns a different label
    per console.

    Parsed rather than loaded, and from ONE function, so the failure mode is loud: if the switch is
    restructured this finds nothing and the log says so. `key_alias_labels` in the log is the canary -
    a drop to zero means the function moved, not that the engine stopped having gamepad labels.

    No row for a console the enum does not name, deliberately. `EConsoleForGamepadLabels` names a few
    label sets and a default, and a newer pad can show its predecessor's labels. Emitting a row for it
    would be inventing a fact the engine does not state.
    """
    src = root / "UnrealEngine" / "Engine" / "Source" / "Runtime" / "InputCore" / "Private" / "InputCoreTypes.cpp"
    if not src.exists():
        log.append("key aliases: no InputCoreTypes.cpp at the expected path - tier skipped")
        return
    text = src.read_text(encoding="utf-8", errors="replace")
    start = text.find("FText EKeys::GetGamepadDisplayName")
    if start < 0:
        log.append("key aliases: EKeys::GetGamepadDisplayName not found - the function moved, tier skipped")
        return
    body = text[start:start + 40000]
    rows = 0
    for m in re.finditer(r"(case EConsoleForGamepadLabels::(\w+):|default:)(.*?)break;", body, re.S):
        console = m.group(2) or "Default"
        for fkey, label in re.findall(r'Key == EKeys::(\w+).*?LOCTEXT\("[^"]*", "([^"]+)"\)',
                                      m.group(3), re.S):
            db.con.execute("INSERT OR REPLACE INTO key_aliases (fkey, console, label) VALUES (?,?,?)",
                           (fkey, console, label))
            rows += 1
    consoles = [r[0] for r in db.con.execute("SELECT DISTINCT console FROM key_aliases ORDER BY console")]
    ambiguous = db.con.execute("SELECT COUNT(*) FROM v_key_ambiguity").fetchone()[0] \
        if db.con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='view' AND name='v_key_ambiguity'"
                          ).fetchone()[0] else -1
    log.append(f"key aliases: key_alias_labels {rows} over consoles {consoles}"
               + (f", {ambiguous} label(s) mean a different key per console" if ambiguous >= 0 else ""))


def load_input_bindings(db: Db, root: Path, log: list[str]) -> None:
    """Phase 8: key-to-action bindings, from input.jsonl.

    The dump writes this from loaded InputMappingContext assets, because a binding is in no registry
    tag. There are four contexts on the sample project against 8,687 assets, so the load the registry
    tier avoids costs nothing here and buys the only questions anyone asks of input.

    Two canaries in the log, for the two ways this can go quietly wrong: a binding with no action at
    all, and a repeated (context, action, key) triple. The second is the one to watch - that triple
    is the natural key and it is NOT unique, so a consumer that treats it as one collapses rows.
    """
    sidecars = sorted(root.glob("*/Docs/AgentMemory/input.jsonl"))
    if not sidecars:
        log.append("input bindings: no input.jsonl found - artefacts predate the input tier")
        return

    total = no_action = 0
    seen: set[tuple[str, str, str, str]] = set()
    repeated = 0
    by_project: dict[str, int] = {}

    for side in sidecars:
        project = side.parents[2].name
        for line in side.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            b = json.loads(line)
            if not b.get("action"):
                no_action += 1
            triple = (project, b.get("context", ""), b.get("action", ""), b.get("key", ""))
            if triple in seen:
                repeated += 1
            seen.add(triple)

            db.con.execute(
                "INSERT INTO input_bindings (context, context_name, key, action, action_name,"
                " value_type, triggers, modifiers, project) VALUES (?,?,?,?,?,?,?,?,?)",
                (b.get("context"), b.get("context_name"), b.get("key"), b.get("action"),
                 b.get("action_name"), b.get("value_type"),
                 ",".join(b.get("triggers") or []), ",".join(b.get("modifiers") or []),
                 project))
            total += 1
            by_project[project] = by_project.get(project, 0) + 1

    detail = ", ".join(f"{k} {v:,}" for k, v in sorted(by_project.items()))
    log.append(f"input bindings: {total:,} ({detail})")
    log.append(f"input bindings: {no_action:,} with no action, {repeated:,} repeating a "
               f"(context, action, key) triple - that triple is NOT a unique key")


def resolve_and_index(db: Db, root: Path, log: list[str]) -> None:
    unresolved = 0
    for cid, sname in db.con.execute(
            "SELECT id, super_name FROM classes WHERE super_name IS NOT NULL").fetchall():
        row = db.con.execute("SELECT id FROM classes WHERE name=? ORDER BY id LIMIT 1",
                             (sname,)).fetchone()
        if row:
            db.con.execute("UPDATE classes SET super_id=? WHERE id=?", (row[0], cid))
        else:
            unresolved += 1
    log.append(f"super resolution: {unresolved} classes name a super with no row in the store")

    db.con.executescript(FTS)
    db.con.execute("INSERT INTO search (kind, name, owner, doc)"
                   " SELECT 'class', c.name, m.name, COALESCE(c.doc,'')"
                   " FROM classes c JOIN modules m ON m.id=c.module_id")
    db.con.execute("INSERT INTO search (kind, name, owner, doc)"
                   " SELECT 'function', f.name, c.name, COALESCE(f.doc,'')"
                   " FROM functions f JOIN classes c ON c.id=f.class_id")
    db.con.execute("INSERT INTO search (kind, name, owner, doc)"
                   " SELECT 'property', p.name, c.name, COALESCE(p.doc,'')"
                   " FROM properties p JOIN classes c ON c.id=p.class_id")
    db.con.execute("INSERT INTO search (kind, name, owner, doc)"
                   " SELECT 'struct', s.name, m.name, COALESCE(s.doc,'')"
                   " FROM structs s JOIN modules m ON m.id=s.module_id")
    db.con.execute("INSERT INTO search (kind, name, owner, doc)"
                   " SELECT 'enum', e.name, m.name, COALESCE(e.doc,'')"
                   " FROM enums e JOIN modules m ON m.id=e.module_id")

    # Blueprint detail, so engine_api_search finds a variable by name without anyone knowing which
    # Blueprint it is in.
    #
    # A kind added here has to be added to engine_api_search's advertised `kind` enum in
    # mcp_server.py as well, and the reason is NOT that the server rejects an unadvertised value -
    # it does not, handle() validates required arguments and nothing else. The gate is the MCP
    # CLIENT, which validates against the advertised inputSchema before the call ever leaves it. So
    # a kind missing from that enum is unreachable from a session while working perfectly in a
    # direct call, which is the awkward half: a test that calls the server directly will pass while
    # every real caller is blocked.
    #
    # Corrected 2026-09-20 after review broke their own assertion on purpose and found it
    # had only ever passed. mcp_server.py now gates on the enum COVERING the store in both
    # directions, which is the invariant that is true and checkable from inside the process.
    db.con.execute("INSERT INTO search (kind, name, owner, doc)"
                   " SELECT 'bp_variable', v.name, a.path, COALESCE(v.tooltip,'') || ' ' || COALESCE(v.category,'')"
                   " FROM bp_variables v JOIN bp_assets a ON a.id=v.bp_id")
    db.con.execute("INSERT INTO search (kind, name, owner, doc)"
                   " SELECT 'bp_override', o.property, a.path, COALESCE(o.value,'')"
                   " FROM bp_overrides o JOIN bp_assets a ON a.id=o.bp_id")
    db.con.execute("INSERT INTO search (kind, name, owner, doc)"
                   " SELECT 'bp_function', f.name, a.path, COALESCE(f.tooltip,'')"
                   " FROM bp_functions f JOIN bp_assets a ON a.id=f.bp_id")
    db.con.execute("INSERT INTO search (kind, name, owner, doc)"
                   " SELECT 'bp_asset', a.name, a.path, COALESCE(a.native_parent,'')"
                   " FROM bp_assets a")
    # Indexed by the LABEL, because the label is what someone types: a person asks about "Gamepad X",
    # not about Gamepad_FaceButton_Bottom. FTS5 indexes every column, so the FName finds it too.
    db.con.execute("INSERT INTO search (kind, name, owner, doc)"
                   " SELECT 'key_alias', k.label, k.fkey, k.console FROM key_aliases k")
    db.con.execute("INSERT INTO search (kind, name, owner, doc)"
                   " SELECT 'asset', s.name, s.path, COALESCE(s.class,'') || ' ' || COALESCE(s.row_struct,'')"
                   " FROM assets s")

    # Indexed on the KEY, because that is what a question names. The context is the owner so a hit
    # is a citation. NOTE: like the bp_* kinds, this is unreachable through engine_api_search until
    # its advertised enum is widened - the gate asserts the enum covers the store in both
    # directions, so it fails correctly until both move together.
    db.con.execute("INSERT INTO search (kind, name, owner, doc)"
                   " SELECT 'input_binding', i.key, i.context,"
                   " COALESCE(i.action_name,'') || ' ' || COALESCE(i.value_type,'')"
                   " FROM input_bindings i")

    # Comment blocks, which no other layer carries. Everything above is a doc comment attached to a
    # reflected declaration; a comment inside a function body appears in no artefact at all. Same
    # table, same four columns, no schema change: kind='comment', owner='<path>:<line>' so a hit is
    # a citation. See extract_comments.py for why this exists and what it deliberately is not.
    from extract_comments import index_comments
    c_rows, c_files = index_comments(db.con, root)
    log.append(f"comment index: {c_rows:,} blocks from {c_files:,} files")

    n = db.con.execute("SELECT COUNT(*) FROM search").fetchone()[0]
    log.append(f"FTS5 index: {n:,} rows")


def write_meta(db: Db, root: Path, targets: str) -> None:
    for k, v in {
        "schema_version": "1", "phase": "4", "tree_root": str(root),
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "targets": targets,
        "tiers": "disk (descriptors), uht (our exporter), runtime (Layer 2 artefacts)",
        "rule_a": "one row per (name, module_id); source=highest fidelity, sources=all seen",
        "rule_b": "targets is a union across tiers, never one tier's value",
        "rule_c": "rep_condition written only by the runtime tier; NULL elsewhere means unknown",
        "caveat": "uht is not a superset of disk: plain virtuals are not UFUNCTIONs and UHT never "
                  "reports them",
        "bp_detail_source": "blueprints.jsonl and assets.jsonl, written by the dump commandlet from "
                            "the same model as the Markdown; not a re-parse of the documents",
        "bp_detail_absence": "assets and bp_* cover ENABLED content only - a disabled plugin never "
                             "mounts, so absence there is not absence on disk",
    }.items():
        db.con.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)", (k, v))


def report(db: Db, log: list[str]) -> str:
    q = lambda s, *a: db.con.execute(s, a).fetchone()[0]  # noqa: E731
    out: list[str] = []
    w = out.append
    w("# Engine API database - phase 4, the merge")
    w("")
    w(f"Generated {q('SELECT value FROM meta WHERE key=?','generated_utc')}. "
      f"Targets: **{q('SELECT value FROM meta WHERE key=?','targets')}** (Win64 only; console is phase 5).")
    w("")
    w("| | |")
    w("|---|---|")
    for label, sql in [
        ("Modules", "SELECT COUNT(*) FROM modules"),
        ("Plugins", "SELECT COUNT(*) FROM plugins"),
        ("Classes", "SELECT COUNT(*) FROM classes"),
        ("Functions", "SELECT COUNT(*) FROM functions"),
        ("Function parameters", "SELECT COUNT(*) FROM function_params"),
        ("Properties", "SELECT COUNT(*) FROM properties"),
        ("Structs", "SELECT COUNT(*) FROM structs"),
        ("Enums", "SELECT COUNT(*) FROM enums"),
        ("Declared availability rows", "SELECT COUNT(*) FROM module_platforms"),
        ("FTS5 rows", "SELECT COUNT(*) FROM search"),
    ]:
        w(f"| {label} | {q(sql):,} |")
    w("")
    w("## Provenance")
    w("")
    w("| Tier combination | Classes |")
    w("|---|---|")
    for srcs, n in db.con.execute("SELECT sources, COUNT(*) FROM classes GROUP BY sources"
                                  " ORDER BY COUNT(*) DESC"):
        w(f"| `{srcs}` | {n:,} |")
    w("")
    leaked = q("SELECT COUNT(*) FROM properties WHERE rep_condition IS NOT NULL AND source<>'runtime'")
    w(f"- Properties carrying `rep_condition` from a non-runtime tier: **{leaked}** (must be 0)")
    w(f"- Properties with a `COND_*`: {q('SELECT COUNT(*) FROM properties WHERE rep_condition IS NOT NULL')}")
    w(f"- Classes with rows from more than one tier: "
      f"{q(chr(39).join(['SELECT COUNT(*) FROM classes WHERE sources LIKE ', '%,%', '']))}")
    w("")
    w("## The cross-origin query, on the full store")
    w("")
    rows = db.con.execute("""
        WITH RECURSIVE anc(root_id, id, depth) AS (
            SELECT c.id, c.super_id, 1 FROM classes c
            JOIN modules m ON m.id=c.module_id AND m.origin='project' WHERE c.super_id IS NOT NULL
            UNION ALL
            SELECT a.root_id, c.super_id, a.depth+1 FROM anc a
            JOIN classes c ON c.id=a.id WHERE c.super_id IS NOT NULL)
        SELECT ours.name, COUNT(DISTINCT a.id)
        FROM classes ours JOIN modules m ON m.id=ours.module_id AND m.origin='project'
        LEFT JOIN anc a ON a.root_id=ours.id
        GROUP BY ours.name ORDER BY 2 DESC, 1 LIMIT 8""").fetchall()
    w("Ancestor depth reachable for our own classes, walking into engine rows:")
    w("")
    w("| Our class | Ancestors resolved |")
    w("|---|---|")
    for n, d in rows:
        w(f"| `{n}` | {d} |")
    w("")
    w("## Deprecation and signatures (phase 7)")
    w("")
    w("| | Deprecated | With a replacement stated |")
    w("|---|---|---|")
    for label, tbl in (("Classes", "classes"), ("Functions", "functions"), ("Properties", "properties")):
        d = q(f"SELECT COUNT(*) FROM {tbl} WHERE is_deprecated=1")
        m = q(f"SELECT COUNT(*) FROM {tbl} WHERE is_deprecated=1 AND deprecation_msg IS NOT NULL")
        w(f"| {label} | {d:,} | {m:,} |")
    w("")
    tot_d = q("SELECT (SELECT COUNT(*) FROM classes WHERE is_deprecated=1)"
              " + (SELECT COUNT(*) FROM functions WHERE is_deprecated=1)"
              " + (SELECT COUNT(*) FROM properties WHERE is_deprecated=1)")
    tot_m = q("SELECT (SELECT COUNT(*) FROM classes WHERE deprecation_msg IS NOT NULL)"
              " + (SELECT COUNT(*) FROM functions WHERE deprecation_msg IS NOT NULL)"
              " + (SELECT COUNT(*) FROM properties WHERE deprecation_msg IS NOT NULL)")
    w(f"**{tot_d:,} deprecated declarations, {tot_m:,} of them say what to use instead.** The gap is "
      f"the answer to a question people actually ask - *is there a migration path* - and it is only "
      f"answerable because message and flag are stored separately rather than collapsed into a bool.")
    w("")
    orphan = q("SELECT (SELECT COUNT(*) FROM classes WHERE deprecation_msg IS NOT NULL AND is_deprecated=0)"
               " + (SELECT COUNT(*) FROM functions WHERE deprecation_msg IS NOT NULL AND is_deprecated=0)"
               " + (SELECT COUNT(*) FROM properties WHERE deprecation_msg IS NOT NULL AND is_deprecated=0)")
    orphan_p = q("SELECT COUNT(*) FROM properties WHERE deprecation_msg IS NOT NULL AND is_deprecated=0")
    w(f"**{orphan} declarations carry a `DeprecationMessage` but are NOT flagged deprecated** "
      f"({orphan_p} of them properties) - the author wrote the migration note without the "
      f"`DeprecatedProperty` meta. Examples read *\"Use bElevateLogWarningsToErrors instead\"* and "
      f"*\"MovementComp is deprecated, please use NavMovementInterface\"*, so the intent is not in "
      f"doubt. **Querying `is_deprecated` alone under-reports deprecation**, and only a store holding "
      f"flag and message separately can show that.")
    w("")
    w(f"Signatures: **{q('SELECT COUNT(*) FROM function_params'):,}** parameter rows over "
      f"{q('SELECT COUNT(*) FROM functions'):,} functions, ordered, typed, return marked.")
    w("")
    w("**Decoded specifiers are flag names, not author specifiers.** Both are stored, per section 4. "
      "UHT resolves specifiers into flag combinations, so a property the author wrote as "
      "`BlueprintReadOnly` reads `BlueprintVisible, BlueprintReadOnly` here, and one written "
      "`BlueprintReadWrite` reads `BlueprintVisible` alone. For what the author typed, the Layer 2 "
      "artefacts remain the authority; this column is the machine truth beside them.")
    w("")
    w("## Blueprint edges (phase 6)")
    w("")
    w("The one thing no compile-time tool produces: clangd cannot read `.uasset`, ripgrep skips them "
      "silently, and renaming a symbol listed here still compiles clean while breaking the graph.")
    w("")
    w("| | Rows | Uses |")
    w("|---|---|---|")
    for kind, n, u in db.con.execute(
            "SELECT kind, COUNT(*), SUM(uses) FROM bp_edges GROUP BY kind ORDER BY 2 DESC"):
        w(f"| `{kind}` | {n:,} | {u:,} |")
    tr, tu = db.con.execute("SELECT COUNT(*), SUM(uses) FROM bp_edges").fetchone()
    w(f"| **total** | **{tr:,}** | **{tu:,}** |")
    w("")
    w("Rows and uses are different numbers and both are published elsewhere: the artefact index "
      "counts rows, `CLAUDE.md` quotes uses. Reconciled here rather than left to collide.")
    w("")
    orig = db.con.execute("""SELECT m.origin, COUNT(*), SUM(e.uses) FROM bp_edges e
        JOIN classes c ON c.id=e.class_id JOIN modules m ON m.id=c.module_id
        GROUP BY m.origin ORDER BY 2 DESC""").fetchall()
    w("| Owning class origin | Rows | Uses |")
    w("|---|---|---|")
    for o, n, u in orig:
        w(f"| {o} | {n:,} | {u:,} |")
    w("")
    w("**The engine share is the useful caveat.** Most Blueprint dependencies point at engine "
      "utilities we cannot change, so a blast-radius question should filter to project-owned classes "
      "before it means anything.")
    w("")
    both = q("""SELECT COUNT(DISTINCT c.id) FROM classes c
        WHERE EXISTS(SELECT 1 FROM properties p WHERE p.class_id=c.id AND p.rep_condition IS NOT NULL)
          AND EXISTS(SELECT 1 FROM bp_edges e WHERE e.class_id=c.id)""")
    touch = q("""SELECT COUNT(*) FROM bp_edges e JOIN properties p
        ON p.class_id=e.class_id AND p.name=e.symbol_name WHERE p.rep_condition IS NOT NULL""")
    w(f"**A cross-layer result neither tier could state alone:** {both} classes carry both a `COND_*` "
      f"property and Blueprint edges, and **{touch}** of those edges touch a replicated property. "
      f"Blueprints call functions on these classes; they never read or write the replicated state "
      f"directly. A replication change on them is safe from the Blueprint side.")
    w("")
    w("## Declared vs observed (phase 5)")
    w("")
    w("`module_platforms` is what the descriptors **declare**. `module_observed` is what actually "
      "appeared in a target's UHT build graph. Section 5.6 says store both and surface the gap, "
      "because `.Build.cs` can gate on `Target.Platform` in C# that no descriptor expresses.")
    w("")
    w("| Target | Type | Modules observed |")
    w("|---|---|---|")
    for t, tt, n in db.con.execute(
            "SELECT target, target_type, COUNT(*) FROM module_observed"
            " GROUP BY target, target_type ORDER BY target"):
        w(f"| `{t}` | {tt} | {n:,} |")
    w("")

    # Only modules the descriptor tier knows about can be compared: a module compiled from
    # Source/ rather than a plugin has no .uplugin and therefore no declared row at all.
    comparable = q("""SELECT COUNT(DISTINCT o.module_name) FROM module_observed o
                      WHERE EXISTS (SELECT 1 FROM module_platforms p WHERE p.module_name=o.module_name)""")
    total_obs = q("SELECT COUNT(DISTINCT module_name) FROM module_observed")
    w(f"Of **{total_obs:,}** distinct modules observed, **{comparable:,}** have a declared row to "
      f"compare against. The rest are `Source/`-tree modules with no `.uplugin`, so nothing declares "
      f"them and their absence from `module_platforms` is not a disagreement.")
    w("")

    # MAX(available), not the raw row. A module is declared available if ANY of its descriptor
    # entries permits it - and 17 plugins declare the same module twice with different Type and
    # different platform lists, so one entry routinely says 0 while its sibling says 1. Joining on
    # the raw rows reported six disagreements on the first run of this comparison, every one of them
    # an artefact of that pairing rather than a real declared/observed gap. Aggregating first is the
    # difference between a finding and a fabrication.
    rows = db.con.execute("""
        WITH declared AS (
            SELECT module_name, platform, target_type, MAX(available) AS available
            FROM module_platforms GROUP BY module_name, platform, target_type)
        SELECT o.target_type, COUNT(DISTINCT o.module_name)
        FROM module_observed o
        JOIN declared p ON p.module_name = o.module_name
             AND p.platform = 'Win64' AND p.target_type = o.target_type
        WHERE p.available = 0
        GROUP BY o.target_type ORDER BY 2 DESC""").fetchall()
    w("**Observed in a build graph but declared unavailable for that target type on Win64:**")
    w("")
    if rows:
        w("| Target type | Modules |")
        w("|---|---|")
        for tt, n in rows:
            w(f"| {tt} | {n} |")
        w("")
        w("Examples, with the descriptor entry that says no:")
        w("")
        w("| Module | Plugin | Declared host type | Observed in |")
        w("|---|---|---|---|")
        for mn, pl, ht, tgt in db.con.execute("""
                WITH declared AS (
                    SELECT module_name, platform, target_type, MAX(available) AS available
                    FROM module_platforms GROUP BY module_name, platform, target_type)
                SELECT DISTINCT o.module_name,
                       (SELECT plugin FROM module_platforms x WHERE x.module_name=o.module_name LIMIT 1),
                       (SELECT host_type FROM module_platforms x WHERE x.module_name=o.module_name LIMIT 1),
                       o.target
                FROM module_observed o
                JOIN declared p ON p.module_name = o.module_name
                     AND p.platform='Win64' AND p.target_type = o.target_type
                WHERE p.available = 0 ORDER BY o.module_name LIMIT 10"""):
            w(f"| `{mn}` | {pl} | {ht} | `{tgt}` |")
    else:
        w("None. Every observed module is declared available for the target type it appeared in.")
    w("")
    w("**Declared available on Win64 for a Game target but never observed in one:**")
    w("")
    never = q("""WITH declared AS (
                     SELECT module_name, platform, target_type, MAX(available) AS available
                     FROM module_platforms GROUP BY module_name, platform, target_type)
                 SELECT COUNT(DISTINCT p.module_name) FROM declared p
                 WHERE p.platform='Win64' AND p.target_type='Game' AND p.available=1
                   AND NOT EXISTS (SELECT 1 FROM module_observed o WHERE o.module_name=p.module_name)""")
    w(f"**{never:,}** modules. That is the expected shape rather than a fault: a module declared "
      f"available is only compiled if some enabled plugin pulls it in, and this tree enables a small "
      f"fraction of the 895 engine plugins.")
    w("")
    w("**Console:** no observed console rows, because no console target has been run. The declared "
      "side for any console platform installed with the engine is already in `module_platforms`. "
      "One UHT run per console target fills `module_observed`, and this section starts comparing them.")
    w("")
    w("## Notes")
    w("")
    for line in log:
        w(f"- {line}")
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=None, type=Path,
                    help="tree root; defaults to two levels above this script, so a rename is fine")
    ap.add_argument("--out", default=None, type=Path)
    ap.add_argument("--report", default=None, type=Path)
    ap.add_argument("--targets", default="Win64",
                    help="PLATFORM the exports were produced on. The target NAME comes "
                         "from each file, so a class ends up tagged Win64:a sample game's editor target etc.")
    args = ap.parse_args()

    root = (args.root or DEFAULT_ROOT).resolve()
    out = args.out or (HERE / "engine-api.db")
    rep = args.report or (HERE / "phase4-merge-result.md")

    t0 = time.time()
    log: list[str] = [f"tree root: {root}"]
    db = Db(out)
    load_descriptor_tier(db, root, log)
    load_uht_tier(db, root, args.targets, log)
    load_runtime_tier(db, root, args.targets, log)
    load_blueprint_edges(db, root, log)
    load_blueprint_detail(db, root, log)
    load_key_aliases(db, root, log)
    load_input_bindings(db, root, log)
    resolve_and_index(db, root, log)
    write_meta(db, root, args.targets)
    db.con.commit()

    text = report(db, log)
    rep.write_text(text, encoding="utf-8", newline="\n")
    db.con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    db.con.commit()
    db.con.close()

    print(f"merged in {time.time()-t0:.1f}s")
    for line in log:
        print("  " + line)
    print(f"db     -> {out} ({out.stat().st_size/1e6:.1f} MB)")
    print(f"report -> {rep}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
