---
description: Write the project side of the memory stack into this tree, or report what is missing
argument-hint: "[--check] [--reference] [--force]"
allowed-tools: Bash, Read, Glob, Grep
---

Set this project up to use the memory stack, or tell the user what it is still missing.

Arguments passed: `$ARGUMENTS`

- `--check` writes nothing and reports. Exit 1 means something is missing or has drifted.
- `--reference` shares one copy of the C++ plugin between several projects instead of copying it. It
  needs a path: ask where that shared copy lives and pass it as `-PluginSource`. Left to itself it
  writes this plugin's own folder into the descriptor, which is the plugin manager's to move and is
  on nobody else's machine.
- `--force` overwrites a copy of the C++ plugin that somebody has edited in the project.

## What to do

**1. Find the `.uproject`, and the tree root that owns it.** Glob for `*.uproject`. If there are
several, the root is the folder **above** them all, not each project's own folder — one config for the
tree, or the refresh and the symbol index end up with different lists of projects. Ask which project
to set up rather than picking.

**2. Check first, always.** On a tree somebody else already set up, this tells you what is actually
absent instead of you finding out by writing over their work:

```powershell
${CLAUDE_PLUGIN_ROOT}/scripts/Initialize-AgentMemoryProject.ps1 -ProjectPath <the .uproject> -Check
```

**3. Then run it for real.** Add `-Root <tree root>` when the root is not the project's own folder,
and `-Mode Reference` for `--reference`.

```powershell
${CLAUDE_PLUGIN_ROOT}/scripts/Initialize-AgentMemoryProject.ps1 -ProjectPath <the .uproject>
```

It writes each thing only when it is absent, so a second run reports "nothing to do" and changes
nothing. Say what it wrote, then tell the user the next two steps, because neither is yours:

- **Build and dump.** `/ue-memory-stack:update` builds the editor target and generates the artefacts.
  Nothing in Layer 2 exists until that has run.
- **Write the routing table.** It put the template at `CLAUDE.md` with placeholders in it. That file is
  an hour of their writing about their own codebase and it is what decides whether any of the other
  layers get read. Offer to work through it with them; do not fill the placeholders in with guesses.

**4. Fill in what the script could not know.** `.claude/agent-memory-stack.json` is written with
`<ANGLE BRACKET>` placeholders wherever the answer is not on disk — the engine path, the Serena
project name. Grep the file for `<` and ask, rather than inventing values that will fail forty minutes
into a build.

## Drift, and what each kind means

`-Check` exits 1 for two different reasons and they have different remedies.

- **"came from plugin X; this plugin is Y"** — the plugin updated and this project is still on the old
  C++ source. A plain re-run fixes it, and then **the editor target must be rebuilt** before the next
  dump: the old DLL runs happily and writes the old format.
- **"differs from this plugin's, at the same version"** — somebody edited the project's copy. That is
  theirs to decide about, so a re-run leaves it alone and reports. `--force` overwrites it. Ask before
  you pass that.

Neither is fixed by deleting the project's copy and re-running. The install record at
`.claude/.uea-install.json` is what makes the first of the two detectable at all, and it is generated
rather than written by hand: without it `-Check` reports "no install record", and a version difference
from then on looks like no difference, because all the script has left to compare is content that
matches. So a tree that answers "no install record" has not lost a preference, it has lost the only
warning it would get on the next plugin update.
