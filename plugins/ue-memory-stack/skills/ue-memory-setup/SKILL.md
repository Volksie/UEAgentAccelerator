---
name: ue-memory-setup
description: Install, configure or repair the UE memory stack on a machine or a project - putting the UEAgentAccelerator plugin into an Unreal project, writing the stack config, setting up Serena and clangd for an engine tree, installing the Serena build Layer 1 needs, and diagnosing a layer that is present but answering nothing. Triggers on "set up the memory stack", "install the accelerator", "set up Serena", "clangd index", "compile database", "search_for_pattern is missing", "find_symbol_indexed returns nothing", "after a Serena upgrade".
---

# Setting the stack up, and repairing it

Everything here fails quietly when it fails. A missing layer is not an error; it is an agent that greps instead and answers worse, and nothing says so. So each step below ends in something you can check.

**Diagnosing rather than installing? Run `/ue-memory-stack:doctor` first.** It checks every quiet failure mechanically and distinguishes "checked and wrong" from "could not check", which saves guessing at which of the steps below is the one that matters.

## Getting it into a project

The tools arrive with this plugin. Address them as `${CLAUDE_PLUGIN_ROOT}/scripts/...`; there is nothing to clone.

`/ue-memory-stack:setup` is the whole project side, and `/ue-memory-stack:update` builds and generates. By hand:

```powershell
# 1. the C++ plugin, the descriptor entry, the stack config, the templates. -Check reports instead
${CLAUDE_PLUGIN_ROOT}/scripts/Initialize-AgentMemoryProject.ps1 -ProjectPath D:\MyGame\MyGame.uproject

# 2. build the editor target, then generate the artefacts
${CLAUDE_PLUGIN_ROOT}/scripts/Update-MemoryStack.ps1 -ProjectPath D:\MyGame\MyGame.uproject -EnginePath C:\UE_5.8 -CompileDbDir D:\MyGame
```

Step 1 writes each thing only when it is absent, so a re-run on a set-up tree changes nothing. **Never work around that by deleting a file first**: what it is protecting is somebody's routing table. Two things are not left alone, and the difference matters. A C++ plugin copied from an older version of this plugin is overwritten, because the old source builds and dumps the old format without complaining — and the project needs rebuilding afterwards. A copy that differs at the *same* version is somebody's edit here, so it is reported and kept unless `-Force`.

Then two things that are not optional, and are the reason this stack works at all. Setup places both; finishing them is the user's:

- **Write the routing table.** It lands at the tree root as `CLAUDE.md`, from `${CLAUDE_PLUGIN_ROOT}/templates/CLAUDE.md.template`, with placeholders in it. Rewriting it for that tree is an hour. Nothing makes an agent open the right artefact rather than grepping out of habit except this file, and a row naming a tool you do not have is worse than no row. Work through it with them rather than filling the placeholders in with guesses.
- **Finish the tree's facts.** `.claude/agent-memory-stack.json` is written from what was on disk, with `<ANGLE BRACKET>` placeholders where the answer was not — the engine path, the Serena project name. Grep it for `<` and ask. Complete, it means setup and refresh cannot disagree about which projects exist, which is a disagreement that shows up as artefacts nobody regenerates.

**Several projects sharing one copy of the C++ plugin** is `-Mode Reference -PluginSource <path>`.
Ask for the path rather than omitting it: without one, the descriptor ends up pointing inside this
plugin's own folder, which no colleague has and an update can move.

**A tree with several projects** needs `-Root` on the folder above them all, so they share one
config. Left to itself it uses the folder holding the `.uproject`, which is right for one project
and wrong for four: four configs, and the one the refresh reads lists a single project.

## Layer 1 is the one that is usually broken

Serena and clangd give compiler-grounded answers, and on an engine tree a stock Serena install mostly does not work while reporting nothing. Before trusting it, read `${CLAUDE_PLUGIN_ROOT}/serena/README.md` — it has the six fixes, in order of how much they matter, and how to check from **outside** your agent that they are live. That check is the point: patches written from inside a packaged app can land in a redirected copy that the real server never loads, and every check made from inside the app then says it worked.

```powershell
${CLAUDE_PLUGIN_ROOT}/serena/Install-SerenaForUE.ps1 -DryRun
```

It refuses to run from a shell whose `%APPDATA%` writes are redirected, and tells you so rather than writing into a copy nobody loads.

**After any `uv tool upgrade serena-agent`, every patch is gone.** Silently. Re-run the installer and re-check the live tool list.

## When a layer answers but answers nothing

- `find_symbol_indexed` returning `[]` in a tenth of a second means clangd has not loaded its index yet, not that the symbol is missing. Make one file-based call and ask again.
- `search_for_pattern` missing entirely means the stock Serena context removed it. Use the variant in `${CLAUDE_PLUGIN_ROOT}/serena/contexts/`.
- Scoped symbol calls timing out means the per-call file walk is still in place. Patch 2 in that README.
- A dump that reports its usual summary and writes nothing usually means a stale DLL or an editor still open.

## Going deeper

- `${CLAUDE_PLUGIN_ROOT}/docs/00-getting-started.md` — nothing to a working stack, step by step.
- `${CLAUDE_PLUGIN_ROOT}/docs/02-install-plugin.md` — copy or reference, and the per-project binaries trap.
- `${CLAUDE_PLUGIN_ROOT}/docs/09-installing-from-a-depot.md` — Perforce teams, where nobody has the
  repository. Read it before diagnosing "the commands are not there" on a colleague's machine: a
  project's settings file enables a plugin but does not install it, so the file can be perfect and the
  plugin still absent. The fix is one script in the depot copy, not an edit to the settings.
- `${CLAUDE_PLUGIN_ROOT}/docs/05-serena-clangd.md` — Layers 0 and 1 in full.
- `${CLAUDE_PLUGIN_ROOT}/docs/troubleshooting.md` — the failures that look like success.
