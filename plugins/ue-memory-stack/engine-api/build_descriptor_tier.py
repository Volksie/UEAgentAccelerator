"""The descriptor tier: what is on disk, before anything is compiled.

Every plugin on disk, which projects enable which, and declared platform availability for every
module against every platform and target type - including consoles this machine has never built
and has no SDK for.

**Availability is resolved by the engine, not here.** `UEAgentAcceleratorTools.ModuleAvailability`
calls `FModuleDescriptor::IsCompiledInConfiguration` and writes the matrix to
`<Project>/Docs/AgentMemory/module-availability.json`; this script reads it. Regenerate with:

    UnrealEditor-Cmd.exe <project>.uproject -run=UEAgentAcceleratorTools.ModuleAvailability
      -unattended -nopause -nosplash -NullRHI -Multiprocess

once per project, because a commandlet only sees its own project's plugin directories.

Why it is done that way, since an earlier version of this file evaluated the rules in Python:

  1. **Licensing.** The Python version was a clause by clause transcription of engine source and said
     so in its own docstring. That makes it a derivative work, which cannot be published. Caught in
     review before it shipped.
  2. **It was also wrong.** Compared against the engine's own answer over 79,965 rows, the
     transcription disagreed on 9 - `LiveLinkCameraRecording` on every Program target. The descriptor
     spells the key `ProgramAllowlist`, lowercase L; the transcription looked for `ProgramAllowList`,
     missed the clause, and fell through to the host-type switch. Unreal's JSON reader is
     case-insensitive and a Python dict is not, so the bug was a layer *below* the logic being
     transcribed, where no amount of care with the algorithm would have found it. Section 5.6 said
     to let the engine's function decide "rather than reimplemented by us and got subtly wrong";
     that was right on both counts.

What the tier keeps: declared console availability still needs **no console SDK and no console
build**, because the engine's function evaluates the descriptor and not the toolchain. What it now
costs: an editor to run the commandlet in, where the Python needed nothing.
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

# ---------------------------------------------------------------------------
# Permissive reading, for the project descriptors this script still reads itself
# ---------------------------------------------------------------------------

_TRAILING_COMMA = re.compile(r",(\s*[}\]])")
_LINE_COMMENT = re.compile(r"^\s*//.*$", re.MULTILINE)


def read_descriptor(path: Path) -> tuple[dict | None, str | None]:
    """Tolerates a UTF-8 BOM, trailing commas and // comments, all of which Unreal's reader accepts
    and a strict one does not. Measured: of 895 engine descriptors, 42 carry a BOM and 34 have
    trailing commas - 76 that a strict reader rejects. Failures are counted, never dropped."""
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        try:
            raw = path.read_text(encoding="utf-16")
        except Exception as exc:  # noqa: BLE001
            return None, f"decode: {exc}"
    except Exception as exc:  # noqa: BLE001
        return None, f"read: {exc}"
    try:
        return json.loads(raw), None
    except json.JSONDecodeError:
        pass
    relaxed = _TRAILING_COMMA.sub(r"\1", _LINE_COMMENT.sub("", raw))
    try:
        return json.loads(relaxed), None
    except json.JSONDecodeError as exc:
        return None, f"json: {exc}"


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS plugin (
    plugin_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    descriptor_path TEXT NOT NULL UNIQUE,
    origin TEXT NOT NULL,
    category TEXT, description TEXT, version_name TEXT,
    enabled_by_default INTEGER, explicitly_loaded INTEGER,
    module_count INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS module (
    module_id INTEGER PRIMARY KEY,
    plugin_id INTEGER NOT NULL REFERENCES plugin(plugin_id),
    name TEXT NOT NULL,
    ordinal INTEGER NOT NULL,          -- 13 plugins declare the same module name twice with
                                       -- different Type and different platform lists
    host_type TEXT, loading_phase TEXT,
    UNIQUE(plugin_id, ordinal));

CREATE TABLE IF NOT EXISTS module_platforms (
    module_id INTEGER NOT NULL REFERENCES module(module_id),
    platform TEXT NOT NULL, target_type TEXT NOT NULL,
    available INTEGER NOT NULL,
    PRIMARY KEY (module_id, platform, target_type)) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS project (
    project_id INTEGER PRIMARY KEY, name TEXT NOT NULL, descriptor_path TEXT NOT NULL UNIQUE);

CREATE TABLE IF NOT EXISTS project_plugin (
    project_id INTEGER NOT NULL REFERENCES project(project_id),
    plugin_name TEXT NOT NULL, enabled INTEGER NOT NULL, resolved_plugin_id INTEGER,
    PRIMARY KEY (project_id, plugin_name)) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS parse_failure (descriptor_path TEXT PRIMARY KEY, error TEXT NOT NULL);

CREATE INDEX IF NOT EXISTS idx_module_plugin ON module(plugin_id);
CREATE INDEX IF NOT EXISTS idx_mp_platform ON module_platforms(platform, target_type, available);
"""


def classify_origin(rel: str) -> str:
    r = rel.replace("\\", "/")
    if "/UnrealEngine/Engine/Platforms/" in r:
        return "platform-extension"
    if "/UnrealEngine/Engine/" in r:
        return "engine"
    if "/Shared/" in r:
        return "shared"
    return "project"


def build(root: Path, out: Path) -> tuple[sqlite3.Connection, dict]:
    if out.exists():
        out.unlink()
    for side in ("-wal", "-shm"):
        p = out.with_name(out.name + side)
        if p.exists():
            p.unlink()
    out.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(out)
    con.executescript(SCHEMA)

    stats = {"matrices": 0, "engine_failures": 0, "platforms": [], "target_types": []}

    # --- availability, resolved by the engine, unioned across the project views -------------
    # Where the commandlet actually writes: ModuleAvailabilityCommandlet.cpp emits
    # ProjectDir/Docs/AgentMemory/module-availability.json, one per project. A staging directory is
    # also accepted, because collecting several projects' matrices into one place by hand is a
    # reasonable thing to have done - but it must not be the only place looked in, which it was.
    matrices = sorted(root.glob("*/Docs/AgentMemory/module-availability.json"))
    staged = sorted((root / "engine-api" / "availability").glob("*.json"))
    matrices = matrices + [p for p in staged if p not in matrices]
    if not matrices:
        raise SystemExit(
            "No module-availability.json found under any <Project>/Docs/AgentMemory/ in %s, and none "
            "staged in engine-api/availability/. Run the commandlet once per project:\n"
            "  UnrealEditor-Cmd.exe <project>.uproject "
            "-run=UEAgentAcceleratorTools.ModuleAvailability "
            "-unattended -nopause -nosplash -NullRHI -Multiprocess" % root)

    plugin_ids: dict[str, int] = {}          # normalised descriptor path -> plugin_id
    plugin_by_name: dict[str, int] = {}
    for mpath in matrices:
        data = json.loads(mpath.read_text(encoding="utf-8"))
        stats["matrices"] += 1
        stats["engine_failures"] += int(data.get("descriptors_failed", 0))
        for fail in data.get("failures", []):
            con.execute("INSERT OR REPLACE INTO parse_failure (descriptor_path, error) VALUES (?,?)",
                        (fail.get("path", ""), fail.get("error", "")))

        for pl in data["plugin_list"]:
            abs_path = pl["descriptor_path"].replace("\\", "/")
            # Relative to the tree root, so the same plugin seen from two projects is one row. This
            # used to split on a literal "/CodeMem/" - the author's tree name - which left the key
            # absolute in every other tree and silently stopped that union happening.
            root_prefix = str(root).replace("\\", "/").rstrip("/") + "/"
            rel = abs_path[len(root_prefix):] if abs_path.lower().startswith(root_prefix.lower()) else abs_path
            key = rel.lower()
            if key not in plugin_ids:
                cur = con.execute(
                    "INSERT INTO plugin (name, descriptor_path, origin, category, description,"
                    " version_name, enabled_by_default, explicitly_loaded, module_count)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (pl["name"], rel, classify_origin(abs_path), pl.get("category"),
                     pl.get("description"), pl.get("version_name"),
                     1 if pl.get("enabled_by_default") else 0,
                     1 if pl.get("explicitly_loaded") else 0, int(pl.get("module_count", 0))))
                plugin_ids[key] = cur.lastrowid
                plugin_by_name.setdefault(pl["name"], cur.lastrowid)
            pid = plugin_ids[key]

            for m in pl["modules"]:
                row = con.execute("SELECT module_id FROM module WHERE plugin_id=? AND ordinal=?",
                                  (pid, m["ordinal"])).fetchone()
                if row is None:
                    cur = con.execute(
                        "INSERT INTO module (plugin_id, name, ordinal, host_type, loading_phase)"
                        " VALUES (?,?,?,?,?)",
                        (pid, m["name"], m["ordinal"], m.get("host_type"), m.get("loading_phase")))
                    mid = cur.lastrowid
                else:
                    mid = row[0]
                for a in m["availability"]:
                    # Union across project views. They should never disagree - the engine evaluates
                    # the same descriptor - so OR is a safety net rather than a merge rule.
                    con.execute(
                        "INSERT INTO module_platforms (module_id, platform, target_type, available)"
                        " VALUES (?,?,?,?)"
                        " ON CONFLICT(module_id, platform, target_type) DO UPDATE SET"
                        " available = MAX(available, excluded.available)",
                        (mid, a["platform"], a["target_type"], 1 if a["available"] else 0))

    stats["platforms"] = [r[0] for r in con.execute(
        "SELECT DISTINCT platform FROM module_platforms ORDER BY platform")]
    stats["target_types"] = [r[0] for r in con.execute(
        "SELECT DISTINCT target_type FROM module_platforms ORDER BY target_type")]

    # --- which projects enable which plugins ------------------------------------------------
    failures: list[tuple[str, str]] = []
    for cand in sorted(list(root.glob("*/*.uproject")) + list(root.glob("*.uproject"))):
        data, err = read_descriptor(cand)
        rel = str(cand.relative_to(root))
        if data is None:
            failures.append((rel, err or "unknown"))
            continue
        cur = con.execute("INSERT OR IGNORE INTO project (name, descriptor_path) VALUES (?,?)",
                          (cand.stem, rel))
        prid = cur.lastrowid or con.execute(
            "SELECT project_id FROM project WHERE descriptor_path=?", (rel,)).fetchone()[0]
        for p in data.get("Plugins") or []:
            if not isinstance(p, dict) or not p.get("Name"):
                continue
            con.execute(
                "INSERT OR REPLACE INTO project_plugin (project_id, plugin_name, enabled,"
                " resolved_plugin_id) VALUES (?,?,?,?)",
                (prid, p["Name"], 1 if p.get("Enabled") else 0, plugin_by_name.get(p["Name"])))

    for path, err in failures:
        con.execute("INSERT OR REPLACE INTO parse_failure (descriptor_path, error) VALUES (?,?)",
                    (path, err))
    stats["project_failures"] = len(failures)

    for k, v in {
        "schema_version": "2",
        "tier": "descriptor",
        "phase": "1",
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tree_root": str(root),
        "availability_resolver": "FModuleDescriptor::IsCompiledInConfiguration, via "
                                 "UEAgentAcceleratorTools.ModuleAvailability",
        "availability_is": "declared, from descriptors on disk. Not observed from any build.",
        "matrices_read": str(stats["matrices"]),
        "platforms": json.dumps(stats["platforms"]),
        "target_types": json.dumps(stats["target_types"]),
    }.items():
        con.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)", (k, v))

    con.commit()
    return con, stats


def report(con: sqlite3.Connection, stats: dict) -> str:
    q = lambda s, *a: con.execute(s, a).fetchone()[0]  # noqa: E731
    out: list[str] = []
    w = out.append
    w("# Engine API database - descriptor tier")
    w("")
    w(f"Generated {q('SELECT value FROM meta WHERE key=?', 'generated_utc')}. **Declared** "
      f"availability, resolved by **`FModuleDescriptor::IsCompiledInConfiguration`** — the engine's "
      f"own function, not a reimplementation. Nothing here was observed from a build.")
    w("")
    w("## Coverage")
    w("")
    w("| | |")
    w("|---|---|")
    w(f"| Plugin descriptors | **{q('SELECT COUNT(*) FROM plugin')}** |")
    w(f"| Modules | **{q('SELECT COUNT(*) FROM module')}** |")
    w(f"| Availability rows | {q('SELECT COUNT(*) FROM module_platforms'):,} |")
    w(f"| Projects | {q('SELECT COUNT(*) FROM project')} |")
    w(f"| Project views merged | {stats['matrices']} |")
    w(f"| Descriptors the engine failed to load | **{stats['engine_failures']}** |")
    w("")
    for origin, in con.execute("SELECT DISTINCT origin FROM plugin ORDER BY origin"):
        n = q("SELECT COUNT(*) FROM plugin WHERE origin=?", origin)
        m = q("SELECT COUNT(*) FROM module m JOIN plugin p USING(plugin_id) WHERE p.origin=?", origin)
        w(f"- `{origin}`: {n} plugins, {m} modules")
    w("")
    w("## What is on disk but nobody enables")
    w("")
    total = q("SELECT COUNT(*) FROM plugin WHERE origin IN ('engine','platform-extension')")
    enabled = q("SELECT COUNT(DISTINCT plugin_name) FROM project_plugin WHERE enabled=1")
    w(f"- Engine-side plugins on disk: **{total}**")
    w(f"- Distinct plugins enabled by any project here: **{enabled}**")
    w("")
    w("| Project | Enables | Resolving to a descriptor we found |")
    w("|---|---|---|")
    for name, in con.execute("SELECT name FROM project ORDER BY name"):
        en = q("SELECT COUNT(*) FROM project_plugin pp JOIN project p USING(project_id)"
               " WHERE p.name=? AND pp.enabled=1", name)
        res = q("SELECT COUNT(*) FROM project_plugin pp JOIN project p USING(project_id)"
                " WHERE p.name=? AND pp.enabled=1 AND pp.resolved_plugin_id IS NOT NULL", name)
        w(f"| {name} | {en} | {res} |")
    w("")
    w("## Declared platform availability")
    w("")
    w("Modules declared compilable for a **Game** target. Console rows are readable with no console "
      "SDK present, because the engine's function evaluates the descriptor and not the toolchain.")
    w("")
    w("| Platform | Modules available (Game) |")
    w("|---|---|")
    for plat in stats["platforms"]:
        n = q("SELECT COUNT(*) FROM module_platforms WHERE platform=? AND target_type='Game'"
              " AND available=1", plat)
        w(f"| {plat} | {n} |")
    w("")
    w("---")
    w("")
    w("**Declared is not observed.** `.Build.cs` can gate on `Target.Platform` in C# that no "
      "descriptor expresses, so a module declared available may still not compile. Confirming that "
      "needs a build for the platform in question.")
    return "\n".join(out) + "\n"


def resolve_root(given):
    """The tree root: the directory holding your project folders, and usually the engine beside them.

    Defaults to the working directory rather than to a path derived from this script's own location.
    The script used to sit two levels below the tree root, so `HERE.parent.parent` was the root; in a
    plugin install it is `plugins/`, which holds no projects, and the build then wrote an empty store
    and reported success. Refusing is the point: an empty store answers every question with silence.
    """
    root = (given or Path.cwd()).resolve()
    if not root.is_dir():
        raise SystemExit(f"--root {root} is not a directory.")
    if list(root.glob("*/*.uproject")):
        return root
    own = list(root.glob("*.uproject"))
    if own:
        raise SystemExit(
            f"--root {root} IS a project ({own[0].name}), not a tree of projects. Pass its parent "
            f"directory: the store is built per tree, and the artefact and export paths this reads "
            f"are <root>/<Project>/...")
    raise SystemExit(
        f"--root {root} holds no <Project>/<Project>.uproject, so there is nothing to build a store "
        f"from. Pass the directory that holds your project folders with --root.")

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=None, type=Path,
                    help="the directory holding your project folders; defaults to the working directory")
    ap.add_argument("--out", default=None, type=Path)
    ap.add_argument("--report", default=None, type=Path)
    args = ap.parse_args()

    root = resolve_root(args.root)
    out = args.out or (HERE / "engine-api-descriptors.db")
    rep = args.report or (HERE / "descriptor-tier-report.md")

    t0 = time.time()
    con, stats = build(root, out)
    rep.write_text(report(con, stats), encoding="utf-8", newline="\n")
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.commit()
    con.close()

    print(f"read {stats['matrices']} engine-resolved matrices in {time.time() - t0:.1f}s")
    print(f"  descriptors the engine failed to load: {stats['engine_failures']}")
    print(f"  project descriptors this script failed to read: {stats.get('project_failures', 0)}")
    print(f"db     -> {out}  ({out.stat().st_size / 1e6:.1f} MB)")
    print(f"report -> {rep}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
