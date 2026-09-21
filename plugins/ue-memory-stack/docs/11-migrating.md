# Migrating from the clone-era install

Before this was a plugin, you installed it by cloning the repository, running scripts out of the clone, and wiring your tree to them by hand. If that is how your tree is set up, this page moves it onto the plugin without losing anything.

**The old route is gone rather than deprecated.** The scripts no longer search for a checkout, and nothing in the repository looks for one. That is deliberate: two install routes means two sets of instructions, and the one nobody tests is the one people follow. So there is a migration, and afterwards there is one way in.

## What survives, untouched

Everything that was actually yours:

| | |
|---|---|
| *Docs/AgentMemory/\*\** | Your artefacts. Nothing about the plugin invalidates them. |
| *CLAUDE.md* | Your routing table. **Setup never overwrites it** — it writes the template only when there is no file at all. Verified: an existing one comes through a migration byte for byte. |
| *.claude/rules/\*.md* | Same rule, and yours are left. Missing ones arrive as *\*.md.template* rather than *\*.md*, because that directory is auto-loaded and an unfilled placeholder there reads as fact. A filled-in *Module.md* counts as present, so the template is not written back over a deliberate deletion. |
| Your design docs | Layer 5 was always yours. |

## What to do

**1. Get the plugin.** From GitHub, or from your depot if somebody has put it there:

```bash
claude plugin marketplace add Volksie/UEAgentAccelerator
claude plugin install ue-memory-stack@ue-agent-accelerator --scope project
```

*09-installing-from-a-depot.md* is the route for a team with no GitHub access, and it is one script per person.

**2. Ask what is missing before writing anything.**

```powershell
${CLAUDE_PLUGIN_ROOT}/scripts/Initialize-AgentMemoryProject.ps1 -ProjectPath D:\MyGame\MyGame.uproject -Check
```

On a clone-era tree that typically reports four things: no *.claude/agent-memory-stack.json*, no per-module rules, and no install record — while confirming your *CLAUDE.md* and your C++ plugin are already there and will be left alone.

**3. Run it for real**, then fill in the `<ANGLE BRACKET>` placeholders in the config it writes. Those are the facts it cannot know, like your engine path.

**4. Delete what the old route left behind.** Nothing does this for you, because they are your files:

- **The clone**, once nothing points at it.
- **Wrapper scripts with the clone's path baked in** — the *Refresh-Memory.ps1* kind of thing every tree grew. They will keep working until the clone moves, and then fail in a way that reads as the stack being broken. `/ue-memory-stack:update` replaces them.
- **Any scheduled task or CI step** that invokes a script from the clone.

**5. Check it.**

```
/ue-memory-stack:doctor
```

On a freshly migrated tree, expect warnings rather than failures: no compile database yet if you never had Layer 0, and no plugin DLL until the next build.

## The one thing that does change under you

Your C++ plugin copy is now compared against the plugin's. When the plugin updates and yours came from an earlier version, setup replaces it and tells you to rebuild — because the old source builds happily and writes the old artefact format, which is the quietest failure in this stack. If you have edited that copy, setup reports it and leaves it alone until you pass `-Force`.

## Rolling back

There is no `--version` flag on `claude plugin install` or `update`, so rollback is the thing your source control already does: put the previous revision of the marketplace back — `p4 sync` to it — and re-run the bootstrap, which uninstalls and reinstalls. Exercised end to end: 0.2.0 → 0.2.1 → 0.2.0, with the installed version following the depot each time.

If you installed from GitHub rather than a depot, rollback means pointing at a marketplace that holds the older version, which in practice means a depot or a fork. That is a real limitation of the GitHub route and worth knowing before you need it rather than during.
