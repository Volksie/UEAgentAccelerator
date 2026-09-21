---
name: ue-memory-refresh
description: Regenerate or check the freshness of the generated Unreal memory layers - the reflection artefacts under Docs/AgentMemory, the compile database, and the Blueprint index - after a sync, a build, or a change to a UCLASS, UFUNCTION, UPROPERTY or replication. Triggers on "regenerate the dump", "the artefacts look stale", "after getting latest", "I just synced", "rebuild the compile database", "AgentMemoryDump", "the answer looks out of date".
---

# Refreshing the layers

The artefacts describe the code as it was when they were generated. After a sync or a build they can be wrong, and **nothing about a stale artefact looks wrong**: the file is there, it is well formed, and it answers confidently.

## Is it stale? Ask source control, not the filesystem

Comparing timestamps does not work after a sync. Both git and Perforce stamp everything they write with the time they wrote it, so a changed header and an artefact that arrived in the same sync both look new, and their order tells you nothing.

Compare **revisions**, which a sync cannot forge:

```powershell
p4 changes -m1 "MyGame/Source/...#have"           # the code
p4 changes -m1 "MyGame/Docs/AgentMemory/...#have" # what describes it
```

Artefacts at an older change than the code means regenerate. The git form is the same question with `git log -1 --format=%H --` over each path, then asking which commit is an ancestor.

Two things that comparison cannot see: **your own uncommitted edits**, and a tree whose artefacts are **not in source control yet**, where the honest fallback is file times, said out loud as the weaker answer it is.

The compile database is the exception: it is normally ignored by source control, so it is never synced, and its timestamp really is when it was built here.

## Regenerating

One command, in dependency order, with a postcondition on every stage:

```powershell
${CLAUDE_PLUGIN_ROOT}/scripts/Update-MemoryStack.ps1 -StackConfig <tree>\.claude\agent-memory-stack.json
```

`-Preset Artefacts` skips the build, `-Preset Layer1` is the compile database alone, and `-DryRun` prints every command without running any.

**What it is protecting you from, and why it asserts on the artefacts rather than on exit codes:**

- **The editor must be closed.** The dump runs the editor as a commandlet.
- **Every project is built before it is dumped.** The plugin's binaries are per project, so building one and dumping three writes stale output for two of them and reports success.
- **One compile database covers all projects.** It resolves the shared engine files once; a database per project leaves entries that agree only by coincidence.
- **A tool that exits 0 having written nothing is a failure here.** That is what most of the silent failures in this stack look like.

Artefacts are moved aside rather than wiped, because a run that dies half way through otherwise leaves an index saying nothing has any Blueprint callers, which reads exactly like the truth.

## Then

Commit or submit the regenerated artefacts with the code change that caused them. They are describing that change; landing them separately means everyone else's answers are wrong until they do.

## Going deeper

- `${CLAUDE_PLUGIN_ROOT}/docs/06-keeping-it-fresh.md` — the full freshness argument, including the CI check.
- `${CLAUDE_PLUGIN_ROOT}/docs/03-running-the-dump.md` — the invocation, and the three flags that are not optional.
- `${CLAUDE_PLUGIN_ROOT}/docs/troubleshooting.md` — 0 modules, 0 Blueprints, stale DLLs.
