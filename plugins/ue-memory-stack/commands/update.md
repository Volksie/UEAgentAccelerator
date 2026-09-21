---
description: Regenerate the memory layers for this tree - build, compile database, reflection dump, verify
argument-hint: "[--artefacts-only] [--dry-run]"
allowed-tools: Bash, Read, Glob, Grep
---

Regenerate the generated memory layers for this project.

Arguments passed: `$ARGUMENTS`

- `--artefacts-only` skips the build and regenerates the dump alone (`-Preset Artefacts`).
- `--dry-run` prints every command without running any.

## What to do

**1. Find the tree's config.** Look for `.claude/agent-memory-stack.json` from the project root. If it is not there, this tree has not been set up: say so and point at `${CLAUDE_PLUGIN_ROOT}/templates/agent-memory-stack.json.template`, rather than guessing paths.

**2. Say what it will cost, and wait.** A full run builds every project in the config before dumping it. On a large tree that is tens of minutes, and **the Unreal editor has to be closed** for the dump. Ask before starting it. Do not begin an hour of building on your own initiative.

**3. Run it, in the background, and let it finish.**

```powershell
${CLAUDE_PLUGIN_ROOT}/scripts/Update-MemoryStack.ps1 -StackConfig <the config you found>
```

Add `-Preset Artefacts` or `-DryRun` to match the arguments. Without a config, fall back to explicit paths: `-ProjectPath`, `-EnginePath`, `-CompileDbDir`, and say that is what you are doing.

**4. Read what it reports, not the exit code.** Each stage asserts on the artefacts themselves — file counts, sizes, and whether anything was written after the stage started. A tool that exits 0 having written nothing is the failure this stack keeps hitting, so `Assert-Fresh` failing is the script working.

**5. Then say what changed**, and that the artefacts should be committed or submitted with the code change that caused them. Landing them separately leaves everyone else's answers wrong until they do.

## If it fails

- **"in use" or a locked file** usually means the editor is open, or a previous run left isolation applied.
- **A stale DLL** means the plugin binaries are older than the source. The script refuses rather than dumping the old format; rebuild.
- **0 modules or 0 Blueprints** in the output is in `${CLAUDE_PLUGIN_ROOT}/docs/troubleshooting.md`, with the cause for each.
