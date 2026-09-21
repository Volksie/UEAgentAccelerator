# Design: ship this as a Claude Code plugin

**Status: design agreed, nothing built.** Written 2026-09-17, revised the same day with Louis's six decisions and a proven distribution route.

**The constraint that shapes it:** the repository is not available on every machine. One developer installs this, puts it in Perforce, and everybody else gets it, uses it and updates it from the depot without ever cloning anything. "Distribution without the repository" below is that workflow. It costs each colleague **one command, once** - not zero, which is what this document claimed until 2026-09-17, wrongly and for a whole phase.

## The problem this solves

Installing this stack today means cloning a repo, copying four templates into your project, rewriting a routing table, writing a config file, applying six Serena patches by hand, and remembering all of it again when any of it changes. The install flow has been tested on real projects twice and each round found steps that were written down and skipped anyway.

A plugin changes three things. It installs with one command and updates with another. Its commands and skills arrive at the moment somebody does the thing, rather than in a document they have to already suspect. And versioning becomes the client's problem rather than a paragraph in a README.

What a plugin does **not** do is put files in your game project. It brings tools and instructions; the project-side files still have to be written into your tree, and a command in the plugin does that. That boundary is the core of this design and everything else follows from it.

## What a Claude plugin is, verified

Checked against the installed marketplace on this machine and the plugin reference, not from memory.

A plugin is a directory. These paths are auto-discovered:

| Path | What it provides |
|---|---|
| `commands/*.md` | Slash commands, namespaced `plugin-name:command` |
| `skills/<name>/SKILL.md` | Skills, loaded when the model judges them relevant |
| `agents/*.md` | Subagents |
| `plugins/ue-memory-stack/hooks/hooks.json` | Hooks, including `SessionStart`, `PreToolUse`, `PostToolUse` |
| `.mcp.json` | MCP servers |
| `.lsp.json` | LSP servers |
| `bin/` | Executables added to PATH |

`plugins/ue-memory-stack/.claude-plugin/plugin.json` carries the name, version, description and licence, and optionally `userConfig`, which is how a plugin asks for machine-specific values. Each option has a `type` of `string`, `number`, `boolean`, `directory` or `file`, and values arrive as `${user_config.KEY}` in MCP and hook configuration and as `CLAUDE_PLUGIN_OPTION_<KEY>` in the environment of anything a hook launches.

`${CLAUDE_PLUGIN_ROOT}` is the plugin's install directory, substituted in skill and agent text, hook commands, and MCP and LSP configuration. **Whether it moves depends on how the plugin was installed**, and this matters more than it sounds: a plugin copied from a remote marketplace gets a new directory on every update, while one installed from a **directory** marketplace is read in place and the path is stable. We are using a directory marketplace, so it is stable here — but nothing in a project file should depend on that, because the same project may be opened by somebody who installed it another way.

Distribution is a marketplace: a `.claude-plugin/marketplace.json` listing plugins and where each one lives. Sources include `github-release`, `url`, `npm`, `file`, `command`, `http` and `skills-dir`; the installed official marketplace also uses `git-subdir` and plain relative paths such as `./plugins/name`. Install and update are CLI commands, with `--scope user|project|local` deciding whether the plugin is personal, shared through the repository, or local and gitignored. There is also `claude plugin validate`, `claude plugin tag` for releases, and `claude plugin eval` for scored test cases.

## The shape: one repository, one marketplace, two plugins

```
UEAgentAccelerator/                     <- the repo, and the marketplace
  .claude-plugin/marketplace.json       <- lists both plugins below

  plugins/ue-memory-stack/              <- PLUGIN 1: the working stack
    .claude-plugin/plugin.json
    commands/{setup,update,status,doctor,serena-patches}.md
    skills/{ue-memory-layers,ue-memory-refresh,ue-memory-setup}/SKILL.md
    hooks/hooks.json
    scripts/          <- today's scripts/, unchanged
    ue-plugin/        <- today's plugin/UEAgentAccelerator (the C++ side)
    serena/           <- the patches, licences and README
    templates/        <- what gets written into a project
    docs/             <- today's docs/, referenced by the skills

  plugins/ue-memory-bench/              <- PLUGIN 2: the benchmark
    .claude-plugin/plugin.json
    commands/{bench-run,bench-score}.md
    skills/ue-memory-bench/SKILL.md
    bench/            <- today's bench/, harness and method
    evals/            <- plugin eval cases, later
```

Two plugins rather than one because the benchmark is 381 KB and 33 files of machinery that nobody installing this to work on a game needs, and because its skill surface would compete with the ones that matter. Anyone reproducing our numbers installs both.

The repo stays the repo. `seed/`, `examples/`, `README.md`, `LICENSE`, `NOTICE.md` and `CHANGELOG.md` stay at the root and ship with neither plugin; the seed project is something you clone and build, not something a plugin installs.

## The boundary: what the plugin owns, what the project owns

This is the part to get right, because everything that has gone wrong in this stack has been a copy of a fact in two places.

| Lives in the plugin | Lives in your project | Why |
|---|---|---|
| `scripts/*.ps1` | — | Nothing project-specific in them |
| The C++ plugin source | A **copy**, or a clone path you chose | See the trap below |
| `docs/**` | — | Referenced by `${CLAUDE_PLUGIN_ROOT}` |
| The Serena patches | — | They patch a Serena install, not a project |
| `templates/**` | The **filled-in copies** | `CLAUDE.md`, `.claude/rules/*`, design docs |
| — | `.claude/agent-memory-stack.json` | Which projects, where artefacts go, database directory |
| — | `Docs/AgentMemory/**` | Generated, per project, in source control |
| Machine facts via `userConfig` | — | Engine path, Serena task name |

**The trap, and it is a real one.** A `.uproject` must never point `AdditionalPluginDirectories` at `${CLAUDE_PLUGIN_ROOT}`. On some install routes that path changes with every update, and the failure mode is the usual one: the editor starts, the plugin is simply absent, the dump reports nothing unusual.

So the C++ plugin is copied twice, deliberately: the repository's copy into the Claude plugin, and the Claude plugin's copy into each project. **Decision 5, and the reason is verification rather than tidiness.** One copy is the source of truth, every project copy can be compared against it, and `doctor` does exactly that — same version, same content, or it says which project is behind and by how much.

## The five surfaces

**Commands** are the things people type, and each one is a place to put a trap that currently lives in a document.

- `setup` — write the project-side files: the C++ plugin, `CLAUDE.md` from the template, the stack config, the rules files. Idempotent, with `--check` reporting without writing.
- `update` — refresh the layers: build, compile database, dump, verify. Wraps `Update-MemoryStack.ps1 -StackConfig`.
- `status` — what exists, what is stale, and the revision comparison from *06-keeping-it-fresh.md* rather than a timestamp check.
- `doctor` — the failures that look like success: a stale DLL, an empty index, a Serena patch reverted by an upgrade, artefacts written by a different plugin version, a `.uproject` pointing at a plugin root that has moved.
- `serena-patches` — run the installer, with its own refusal to run from a redirected shell.

**Skills** are the reasoning, loaded when somebody is doing the thing rather than when they ask for a manual. Three of them, kept small, each pointing at `${CLAUDE_PLUGIN_ROOT}/docs/...` for the long material so the docs stay the single source:

- `ue-memory-layers` — which layer answers which question, the routing table, and what each layer cannot answer. Triggers on the questions people actually type: "where is X defined", "what calls this", "is this replicated".
- `ue-memory-refresh` — when artefacts are stale, how to tell, and how to regenerate. Triggers on a build, a sync, or an answer that looks out of date.
- `ue-memory-setup` — installing the stack, and updating it after a plugin update or a Serena upgrade.

**Hooks** are what a document cannot do, and this is the part the current repo has no answer for at all:

- `SessionStart` — compare artefact and source revisions and say one line if the artefacts are behind. Cheap, and it is the check nobody remembers to run.
- `PreToolUse` on `Write|Edit` — refuse edits to `Docs/AgentMemory/**`. Those files are generated, and hand-editing one is destroying the thing you are reading.
- `PostToolUse` on a build command — note that the reflection dump is now behind the binaries.

Every hook must be cheap and quiet. A hook that costs a second on every session start will be turned off, and then so is everything else in the file.

**Scripts and payload** move across unchanged and are addressed as `${CLAUDE_PLUGIN_ROOT}/scripts/...`. The one change needed: the scripts currently find the accelerator clone by searching candidate paths; under a plugin the honest answer is the plugin root, passed in.

**Configuration** splits by lifetime, which is the rule that keeps it from drifting:

- `userConfig` in the manifest holds *machine* facts: the engine path, the Serena scheduled-task name. They differ per machine and belong to the person, so the client's own configure flow is the right home.
- `.claude/agent-memory-stack.json` in the project holds *tree* facts: which projects, where artefacts go, which compile database. It is committed, and the setup command writes it from the template.

Note the limit: `CLAUDE_PLUGIN_OPTION_*` reaches hooks and MCP servers, not a script a user runs by hand in a terminal. So every script keeps its explicit parameters, and the commands pass them.

## Distribution without the repository

**Corrected 2026-09-17 after it failed in a real session.** What follows now distinguishes what was run from what was assumed, because the first version of this section conflated them and the error sat in published docs for a phase.

A marketplace can be a **directory**, so the depot can hold one, and a project's settings file can name it with a relative path. **What that file cannot do is install the plugin.** Claude Code's *Configure team marketplaces* documentation says so as of 2.1.195: trusting the folder adds the marketplace, and a plugin that only the project's settings enables "doesn't load until the team member installs it". So the depot carries everything and each person runs one install command once. `tools/depot-payload/Install-FromDepot.ps1` ships beside the marketplace copy and is that command.

**How the mistake survived so long, which is the part worth keeping.** Every check run against it was a file check - the copy is complete, the JSON shape matches what the CLI writes, the relative path resolves, `validate --strict` passes, the payload installs at user scope and reports seven components. All true, and none of them touched the question of whether a session installs anything from a settings file. The one check that mattered needed an authenticated session, could not be run from this environment, and was written up as "outstanding, a one-minute check" rather than as "the central claim is unverified". It failed the first time a person ran it. **An exit condition that cannot be executed is not an exit condition, and the parts of a design it guards are unbuilt until it is.**

**The marketplace key is its declared name.** The CLI registers a marketplace under the `name` in its own `marketplace.json` - observed: adding this copy produced `ue-agent-accelerator` in `known_marketplaces.json`, not the alias the settings file used - and a plugin id is `<plugin>@<that name>`. The first version of the export invented `uea-depot`, which yields an id that resolves against nothing. The docs are silent on whether the key must match, so the export now defaults to the declared name and warns on an override rather than relying on the answer.

### The depot layout

```
//depot/Tools/ClaudePlugins/UEAgentAccelerator/     <- the marketplace
    .claude-plugin/marketplace.json
    plugins/ue-memory-stack/...
    plugins/ue-memory-bench/...

//depot/MyGame/.claude/settings.json                <- submitted with the project
```

### The first developer, once

Clone the repository (or download it once) and run
`tools/Export-ToDepot.ps1 -DepotPath <workspace path> -ProjectRoot <project>`. It copies the marketplace payload - the manifest, both plugins and the licences, and nothing else - and writes the project's `.claude/settings.json`, merging rather than replacing:

```json
{
  "extraKnownMarketplaces": {
    "uea-depot": {
      "source": { "source": "directory", "path": "../Tools/ClaudePlugins/UEAgentAccelerator" }
    }
  },
  "enabledPlugins": { "ue-memory-stack@uea-depot": true }
}
```

Then submit both; the script prints the `p4 reconcile` lines and runs none of them. **Write that file rather than running `claude plugin marketplace add`**, and this is the trap the whole workflow turns on: `marketplace add` resolves whatever you give it, relative path included, to an **absolute** path and stores that. Submitted, it names a directory that exists on one machine. A relative path in the same field works correctly — tested: it resolves against the project and a plugin installs from it — but nothing puts one there for you.

### Everybody else, once each

```
p4 sync
cd <their project>
..\Tools\ClaudePlugins\UEAgentAccelerator\Install-FromDepot.ps1
```

Then open the project and accept the workspace trust prompt. The script registers the marketplace from the depot copy and installs at project scope; verified from a configuration directory with no marketplaces and no plugins in it, and it is idempotent - a second run refreshes and reports. What is still only verified at the CLI level is the last inch: a session loading the commands. That needs a person, and it is the check this phase now insists on before calling anything done.

**`claude plugin list` reads personal and managed scope, not a project's settings.** In a workspace whose project settings enable a depot plugin but where nobody has run the install, it says "No plugins installed" and `marketplace list` does not mention the marketplace - CLI 2.1.263. That is accurate, and it reads identically to the case where everything is fine and you are looking at the wrong scope, so it is useless as a diagnosis on its own. After the install it does report the plugin with `Scope: project`, which makes it a fair check *after* the bootstrap and a misleading one before.

The deeper trap, and the one that cost a phase: **a settings file that looks complete is not evidence of anything.** It is byte for byte what it should be whether or not anybody has installed the plugin. `doctor` has to compare the settings against `installed_plugins.json`, not read the settings and conclude.

**The trust step is not optional and is worth saying plainly.** A project-scope plugin loads only after the workspace is trusted, and MCP servers, LSP servers and monitors stay unloaded until then. Somebody who dismisses that prompt gets a session with no plugin and no error. The fix is to reopen the project and accept it; `/ue-memory-stack:doctor` should report the untrusted state in as many words.

### Updating

One developer syncs a new version into the depot and submits. Everybody else:

```
p4 sync
```

runs `Install-FromDepot.ps1` again, and restarts Claude. **Content in the depot copy is read from the directory** - a command file added there appeared in `claude plugin details` with nothing reinstalled, and the cached copy under `~/.claude/plugins/cache/<marketplace>/<plugin>/<version>` did not change, so that cache is not what was read. But the *install* is what records a version, so re-running the bootstrap is what makes a version bump theirs rather than something they assume happened. `claude plugin update ue-memory-stack --scope project` reports what moved.

One trap there: `claude plugin update` defaults to **user** scope and fails with "not installed at scope user" for a project-scope plugin. The error is clear, the flag is `--scope project`, and the docs should carry both.

### What this costs the first developer

Keeping the depot copy current: pulling a new version of the repository and re-copying it. That is a deliberate trade — one person does the version control, everybody else does nothing at all.

Updating has **two halves, and conflating them is how this goes wrong**:

```bash
claude plugin update ue-memory-stack     # the tools and instructions. Restart required.
/ue-memory-stack:update                  # the artefacts in your project
```

Updating the plugin does not refresh your artefacts, and refreshing artefacts does not update the plugin. Worse, a plugin update can change the dump format, which makes existing artefacts wrong in a way nothing reports. So the C++ plugin stamps an artefact format version into what it writes, `doctor` compares that against the installed plugin's version, and the release notes say when a bump requires a full regeneration.

## Risks, and what each one costs

| Risk | Cost if ignored | Mitigation |
|---|---|---|
| `${CLAUDE_PLUGIN_ROOT}` moves, on some install routes | A `.uproject` reference breaks silently; the editor just has no plugin | Copy the C++ plugin into the project; `doctor` compares the copy against the plugin's |
| The depot marketplace path is absolute | Works for whoever added it, breaks for everybody who syncs it | `Export-ToDepot.ps1` computes and writes the relative path; never use `marketplace add` for the committed entry |
| A workspace is never trusted | The plugin is simply absent, no error | Trust step documented; `doctor` says so in as many words |
| A project's settings enable a plugin nobody installed | Identical to the above: no commands, no error, and a settings file that reads as correct | `Install-FromDepot.ps1` in the depot copy; `doctor` compares settings against `installed_plugins.json` rather than trusting the file, and the `SessionStart` hook says so in one line |
| The depot copy falls behind the repository | Everybody is on an old stack and nothing says so | `tools/Export-ToDepot.ps1 -Check` exits 1 when the copy differs, so it can gate a release; one named person still owns the copy |
| Artefacts outlive a format change | Wrong answers, no error | **Mitigated 2026-09-18.** The dump stamps `Artefact format` and `Written by plugin` into `MANIFEST.md`; `doctor` compares the first against `artefact-format.json` and fails on a mismatch. A set with no row was written before the stamp existed, which is itself the answer |
| Binaries are per project | Build one, dump three, two get stale output and report success | Unchanged from today: `update` builds each project before dumping it |
| Project scope needs trust | Hooks and MCP quietly absent on a fresh clone | Documented; `doctor` reports it |
| Windows-only scripts | Half the stack is unavailable on macOS and Linux | Unchanged from today, and stated in the plugin description rather than discovered |
| Serena upgrade reverts the patches | Layer 1 silently stops working | `doctor` checks the live tool list, not the files on disk |
| Skills crowd the context | Every session pays for instructions it does not use | Three small skills with references, not one large one; measure the standing cost before and after |

That last one is measurable with the tooling we already have, and it should be measured rather than assumed.

## Effect on the benchmark

Moving the routing table into a plugin skill is a change to Layer 4, and the arm's standing context changes with it. By this repo's own rule that makes the next measured run **v5**, and no v4 figure carries across. The plan below puts the packaging work before the next run deliberately, so one boundary covers both.

## Plan

Every exit condition is something to run, not something to believe.

**Phase 1 — skeleton that validates. DONE 2026-09-17.** Marketplace manifest at the repository root, both plugin manifests, a README and a licence in each, no content moved. Exit conditions met: `claude plugin validate --strict` passes on the marketplace and both plugins; adding the repository as a directory marketplace offers both, and both install. The empty plugins measure **~0 always-on tokens**, which is the baseline every later phase is measured against.

**Phase 2 — move the components. DONE 2026-09-17.** Scripts, the C++ plugin as `ue-plugin/`, the Serena patches, the templates and the guides all moved into the stack plugin; three commands and three skills written; the clone route cut rather than deprecated. Exit conditions met: the plugin installs from a directory marketplace and reports **six components** and **~482 always-on tokens** against the empty baseline of ~0, every payload path resolves under the plugin root, and a path audit over all 69 documents reports **0 unresolvable references**. Not verified here, and the honest gap: a full build and dump on the seed project, which needs an engine.

**Phase 3 — the setup command. DONE 2026-09-17.** `plugins/ue-memory-stack/scripts/Initialize-AgentMemoryProject.ps1` and `/ue-memory-stack:setup`. It writes the C++ plugin, `.claude/agent-memory-stack.json` filled in from what it found, `CLAUDE.md` from the template, the rules files, and a generated install record. Exit conditions met on copies of the seed project: a first run writes 5 things, a second changes **0 files** and says so, `-Check` exits 1 with 6 missing on a bare project and 0 on a finished one, and an edited `CLAUDE.md` survives every re-run. The plugin now reports **seven components** and **~508 always-on tokens**, the setup command costing ~30 of them.

Two things the exit condition as written would have let through, both found by running it:

- **"Never overwrite" is wrong for one file.** A plugin update leaves every project on the old C++ source, and nothing about that looks broken: the editor builds it, the dump runs, and it writes the old format. So the install record carries the plugin version, a version difference is copied over on the next run, and the run says to rebuild. A copy that differs at the *same* version is somebody's edit and is reported and kept unless `-Force`. Drift is counted separately from absence, because the remedies differ.
- **`-Mode Reference` was never idempotent.** It writes a descriptor entry and no `.uplugin` under the project, so a check that looked only in `<project>/Plugins` reported the plugin missing for ever: `-Check` exited 1 on a correctly set-up tree and every real run reinstalled. It now reads the descriptor's `AdditionalPluginDirectories`. Worse, the path it wrote by default was the plugin's own folder inside the plugin manager's cache — not a path any colleague has, and one an update can move, after which the editor has no plugin and says nothing. `-PluginSource` is now threaded through and the script warns when it is about to write the plugin-owned path.

**Phase 4 — the depot route. DONE 2026-09-17, after a first attempt that failed in a session.**

What is there: `tools/Export-ToDepot.ps1` copies the marketplace payload into a depot workspace, ships `Install-FromDepot.ps1` beside it, and writes the project's `.claude/settings.json` with a relative path and the declared marketplace name, merging into whatever is already in that file. `plugins/ue-memory-stack/docs/09-installing-from-a-depot.md` is the page, inside the plugin so it travels in the copy.

**The first version was wrong in the middle, and it shipped.** It claimed a synced settings file plus a trusted folder was the whole installation. It is not: Claude Code documents that a plugin only a project's settings enables does not load until that person installs it, and the failure is silent - the commands are simply absent. A real session proved it within a day of publishing. The design now costs each colleague one command, once, and that command ships in the depot.

Two defects fell out of the same investigation, and the export prevents both: the settings key must be the marketplace's **declared** name (the first version invented `uea-depot`, giving a plugin id that resolves against nothing), and a version disagreement between `marketplace.json` and a `plugin.json` is refused rather than copied into a depot.

Verified: 69 files copied and nothing else; the copy validates as a marketplace from inside the workspace and installs from the directory reporting the same seven components and ~508 always-on tokens as the repository; `-Check` exits 1 when a bump has left the copy behind; an existing `permissions` block survives the merge; and **the bootstrap works from a configuration directory holding no marketplaces and no plugins**, is idempotent, and afterwards `claude plugin list` reports the plugin at `Scope: project`.

**The last exit condition is met: a session in the synced workspace loads the commands.** Louis ran it after the rework - sync, one bootstrap, open the project, and `/ue-memory-stack:` completes. That is the route end to end, on a workspace whose only relationship to this repository is a copied directory.

**The lesson is worth more than the phase.** The first attempt's session check was written up as "a one-minute check outstanding" while the design's central claim rested on it, and the phase was reported as shipped; it failed the first time a person ran it. **An exit condition that cannot be executed is not an exit condition: until it runs, the thing it guards is unbuilt, and it belongs in the summary as a blocker rather than as a footnote.** Phase 5's `doctor` inherits it directly - it must compare the settings file against `installed_plugins.json`, because a settings file that looks perfect is not evidence that anything is installed.

**Phase 5 — doctor and hooks. DONE 2026-09-17, on the third attempt at one check.**

`plugins/ue-memory-stack/scripts/Test-MemoryStackHealth.ps1` and `/ue-memory-stack:doctor` check the layers that fail without saying anything, and `hooks/` carries two hooks that ship on and one that ships off.

**Four verdicts, not two.** OK, WARN, FAIL and **UNKNOWN**, where UNKNOWN means *not checked* and is printed as its own count rather than folded into a pass. That distinction is the whole point of the tool: a report that silently omits what it could not test reads exactly like one where everything is fine, which is the failure this stack is about and the one this design made itself in Phase 4.

**Verified by fixture, which is the part that matters.** A tree broken in thirteen ways at once - a plugin enabled but not installed, an untrusted workspace, a descriptor with the plugin disabled, an unfilled config placeholder, a config naming a project that is not there, a project copy from an older plugin, a DLL older than its source, an index with no class files, an empty Blueprint caller index, artefacts older than source, a compile database behind its `.Build.cs`, a database pointing at response files that are gone, a Serena upgraded out from under its patches - and **all thirteen are detected**, exit code 1. The fixture also found a real defect the healthy-tree run could not: `$x += (if ...)` is PowerShell 7 syntax and killed the whole script on 5.1, on a path a healthy tree never takes.

**Its first run against a real machine produced three false findings, all mine**: the patch state named the wrong file for one Serena fix (it patches Serena's own `ls_manager.py`, and the fix was present all along), the context check demanded the canonical file name when a team may legitimately run a context of its own name, and the response-file sampler anchored on `@` followed by a drive letter when the database writes `@\"C:/...\"`, so it reported UNKNOWN on a file full of them. A health check that cries wolf gets ignored, so this is worth as much as the detections: **the first thing to test a checker against is something that is working.**

**The Serena sentinels now live in `plugins/ue-memory-stack/serena/layer1-state.json`**, read by both the installer and the doctor, because the same table written twice drifts without anything failing. Both now agree about the machine they are looking at. (Written as `patch-state.json` at the time; renamed when the patches became commits on a fork and there was nothing left to patch.)

**Hook cost, measured rather than assumed.** `claude plugin details` reports hooks as *harness-only, no model context cost*, and always-on stayed at ~508 tokens with them (538 once the doctor command was added). So the entire cost is wall clock, and it is PowerShell process startup rather than anything the scripts do:

| | Measured |
|---|---|
| `SessionStart`, real three-project tree | ~250 ms, once per session |
| `PreToolUse` on `Write\|Edit`, per call | ~220 ms |

So: the session hook ships, and prints **nothing** when healthy, because whatever it prints is context in every session for ever. The write guard ships, because ~220 ms is a fair price for not hand-editing a generated file, and it fails open on unreadable input. The build note **ships off**: ~220 ms on every shell command to say something that applies after a build and not otherwise is a tax on the whole session, and the same fact is already in the refresh skill and the doctor. `plugins/ue-memory-stack/docs/10-hooks.md` carries the numbers and the block to paste to turn it on.

**Named gaps, rather than quiet ones.** Two UNKNOWNs are structural: whether the running Serena actually exposes its tools needs a tool call from inside a session, and **the dump stamps no format version into its output**, so an artefact set written by an older plugin cannot be told from a current one by reading it. The risk table has claimed "format version stamped and checked" as a mitigation since the first draft; it does not exist, and the doctor says so rather than implying otherwise. Stamping it is a commandlet change and a build, so it belongs to a later phase.

**Tested in a session, and the write guard failed.** `SessionStart` works: it fired, and its text reached the model verbatim, naming the stale DLL in that workspace. The write guard did not. The session testing it was configured to make file changes with `sed` and heredocs, so a `sed -i` on a generated artefact was never offered to a hook matching `Write|Edit` - the file was edited, nothing was said, and the only reason anybody knew is that the tester reported it.

**That is the plugin's own thesis turned on the plugin.** A guard over the paths nobody takes produces confidence rather than protection, and shell writes are the normal path in plenty of sessions - including the one that found this, and including the session that then reverted the edit with another `sed -i`. Two things follow. The matcher is now `Write|Edit|MultiEdit|NotebookEdit|Bash`, and the guard's shell arm denies a command only when it can see both a protected path and a writing verb tied to that path, so reading, grepping and copying an artefact out all still pass. And `tools/Test-WriteGuard.ps1` is now a standing test: 24 cases, positives and negatives, all correct, run after any change to the guard. The negatives are the half that decides whether the guard survives people - one that blocks reading an artefact gets deleted by Friday.

**The cost moved with it, and honestly.** The guard now pays ~205-220ms on every shell command as well as every edit. The earlier note in `hooks.json` had rejected a per-Bash hook on exactly that cost, for a hook that only prints advice; paying it for a guard that actually holds is a different trade, and the alternative was a guard that did not.

**The second test failed too, and for a different reason - which turned out to be the most important thing found in this phase.** The fixed matcher was in the marketplace directory and the session still went straight through. **A session does not load a plugin from the marketplace directory. It loads a cached copy**, at `~/.claude/plugins/cache/<marketplace>/<plugin>/<version>`, and **the version string is the cache key.**

Measured on CLI 2.1.263, editing a file in a directory marketplace without changing the version:

| Route | Replaces the cached copy? |
|---|---|
| Edit the marketplace directory | No |
| `claude plugin marketplace update` | No - reports success |
| `claude plugin update` | No - reports *already at the latest version*, which is true of the version and false of the content |
| `claude plugin uninstall` then `install` | **Yes** |
| Bump the version, then `marketplace update` + `plugin update` | **Yes**, and it says *restart to apply changes* |

So the update story for the depot route had a hole in exactly the place that matters: a colleague syncs a fix, runs the bootstrap, is told the plugin is already installed, and keeps loading the old copy for ever. Three fixes followed. `Install-FromDepot.ps1` now uninstalls before installing, so a sync lands. The depot page and the hooks page say the version is the mechanism rather than a formality, and that `claude plugin details` reading the directory live makes the trap *worse* - the inventory you check shows your change while every session ignores it. And the doctor gained the check that would have caught this in one run: it fingerprints the loaded copy against the marketplace it came from, per file, and names what differs. Tested both ways - it caught a one-file difference (the health check script itself, which I had edited after installing) and went green after the reinstall it recommends.

That check had its own bug on first run, in the same shape as the fixture one: it called a function that did not exist in that script, on a branch only reached when the two versions match. **The paths a healthy state skips are where the bugs live**, and both of this phase's own defects were there.

**The plugin is now 0.2.0**, and the bump is deliberate rather than tidy: it is what carries the doctor, the hooks and the guard fix onto machines that already have 0.1.0.

**The guard fired.** Third attempt, in a new session against the 0.2.0 cache: `sed -i` on an artefact was refused. So both hooks are now verified in a real session rather than only against payloads, and the phase is done.

Worth keeping: **the check failed twice for reasons that had nothing to do with the thing being tested.** First the matcher covered the wrong tools, then the session was loading a cached copy from before the fix. Both looked identical from the outside - the guard did not fire - and neither was visible from the code being reviewed. A test that fails is only informative if you can tell *which* layer failed, and here that took a check of the loaded copy against its source, which is now the doctor's job.

**Phase 6 — the benchmark plugin. DONE 2026-09-18.**

`bench/` moved into `plugins/ue-memory-bench/bench/` with `git mv`, and the plugin gained two commands (`bench-run`, `bench-score`) and one skill. It reports **three components and ~183 always-on tokens** - the reason it is a separate plugin, since nobody working on a game pays that. Both plugins are now 0.2.0.

**The plan put the eval cases in the wrong plugin, and the reason matters.** It said "eval cases under `evals/` drawn from the question set we already have". But `claude plugin eval` sandboxes a run with **one plugin loaded, no CLAUDE.md, no other plugins and a throwaway working directory**, so an eval case measures the plugin it belongs to. What we want measured is whether the *stack's* instructions route a session to the right artefact, so the suite lives at `plugins/ue-memory-stack/evals/` and each case builds its own fixture with a scaffold script. The benchmark's question set could not be reused directly either: those questions are about a real tree that the sandbox does not have.

So there are now two instruments, and conflating them is the mistake to guard against:

| | `claude plugin eval` | `ue-memory-bench` |
|---|---|---|
| Asks | do the instructions route correctly | do the layers change how well real questions get answered |
| Against | a fixture built per run | a real tree, hundreds of classes |
| Costs | cents, minutes | hours, and a real bill |
| Cadence | per commit | per version, deliberately |

Four cases, each pairing an **answer** grader with a **route** grader, because a right answer by the wrong route is a coincidence that will not repeat: the replication condition that is not in the header, the blast radius whose only caller is a Blueprint, the comment that says metres over a body returning centimetres, and one case asserting the `ue-memory-layers` skill fires at all (a plugin-fired indicator rather than part of the score, which is what `--ablation with-without` does with `tool_used: Skill`).

**`tools/check_evals.py` is the gate that made this worth writing before it could be run.** It checks every case has a prompt and at least one grader, that frontmatter parses, that each grader's type is one of the six documented ones with that type's required fields, that patterns compile, that scaffold scripts pass `bash -n`, and that a `tool_used` pattern's literal parts appear in the scaffold - which is what catches a path that drifted after a fixture changed. It immediately failed on three of my own graders: a heredoc had eaten a backslash, leaving `[/\]` as `[/\]` minus one character, an unterminated character class that would have scored zero for ever and read exactly like a routing failure. A paid run would have found that slowly and misattributed it.

Two more defects fell out of the move. The blanket path rewrite repointed **both** sides of a sync pair, when only the repository side moved - the working tree still keeps `bench/` at its root, and the pair would have compared against a directory that does not exist there. And `Sync-Shared.ps1` derived `-RepoPath` from `$PSScriptRoot` in a parameter default, which is empty on Windows PowerShell 5.1: the script died before its first line. That is the third time this exact bug has appeared in this repository, and the first time this tool had been run on 5.1 rather than pwsh 7.

**The exit condition is met: the suite runs and scores.** After updating the CLI to 2.1.276 and a `/login` for the credentials an eval's `claude -p` children need: four cases, three runs each, both arms, 24 runs, 864 seconds, **$4.25**. All four now score 1.00 with the plugin.

**And the result is more useful than a pass, because three of the four cases score 1.00 *without* the plugin as well.** They are measuring the model's competence at reading a four-file directory, not this plugin's contribution: on a fixture that small there is no wrong route to take, whatever the instructions say. Only `layers-skill-fires` separates the arms, and trivially, because the skill does not exist in the baseline. **A green suite here means "nothing regressed", not "the layers help"**, and the README says so rather than quoting mean Δ +0.28 as if it were evidence. Making the cases discriminate is the follow-up: decoys a text search hits first, a header that contradicts the artefact, a `.uasset` a grep would answer from and be wrong, or a turn budget where the efficient route is the only one that finishes.

**The graders were the weak part, twice, and both failures read as the plugin failing.** A `tool_used: Read` grader reported *Read called 0x* on a run whose trace shows `Read` on exactly that path; and a session that reached the file with `Grep` was marked as not having routed at all. Both route graders are now a regex over `target: trace`, which asks whether the session opened the artefact rather than which verb it used. Worse, a `not_contains` grader failed an answer for *naming* the wrong figure while rejecting it - the model answered "200 cm, the doc comment is stale" and mentioned 20,000 to explain what the comment would imply. That is a bad answer key, the exact failure this project's own benchmark method warns about, and it is now an `llm` grader judging the claim.

**Three things about the runner that cost a paid run each to learn, now in the suite's README:** `scaffold_script` belongs under a `context:` block and is silently ignored anywhere else; the scaffold shells out to `bash`, which must be on `PATH`; and a broken case does not score zero, because negative graders pass on an answer containing nothing. `tools/check_evals.py` now catches all three before a run starts.

**One thing the suite proved that reading could not:** in the units case the session fired `ue-memory-layers`, opened the `.cpp`, and answered correctly. The instruction "comments are not answers about units, read the body too" is being followed - worth knowing precisely because that was the case most likely to fail.

**Phase 7 — migration and the old route. DONE 2026-09-18.**

**This phase's plan was written before the decision to cut the clone route, and half of it was therefore wrong.** It said the clone-and-copy install keeps working and the README documents both. Two install routes means two sets of instructions, and the one nobody tests is the one people follow - so the old route stayed cut, and what shipped is a migration rather than a parallel path: `plugins/ue-memory-stack/docs/11-migrating.md`.

**Exercised end to end on a scratch tree built to look the way the old route left one** - artefacts, a hand-written `CLAUDE.md`, a wrapper script with a clone path baked in, no stack config, no install record:

- **Migration.** `-Check` reported exactly the four missing things and confirmed the routing table and the C++ plugin were already there; the real run wrote the config, the rules and the record, and **`CLAUDE.md` came through byte for byte** (SHA-256 compared before and after). The stale wrapper was left alone, because it is theirs to delete - the page says to.
- **Install, update, rollback.** Through the depot bootstrap: 0.2.0 installed, then 0.2.1 after the depot copy moved, then **0.2.0 again** after the depot was put back. There is no `--version` flag on `claude plugin install` or `update`, so rollback is what source control already does: sync the marketplace back and re-run the bootstrap, which uninstalls and reinstalls. Worth stating plainly because the GitHub route has no equivalent - rolling back there means pointing at a marketplace that holds the older version, which in practice means a depot or a fork.
- **The migrated tree refreshes.** `doctor` on it: 8 ok, 3 warnings, 0 failures, 2 not checked - and every warning true of that tree (no DLL built yet, no `BlueprintCallers.md`, no compile database).

One number worth recording: the depot payload is now **154 files**, up from 69, because the benchmark became a plugin's contents in Phase 6 and a marketplace copies whole plugins.

## After the phases

**The artefact format stamp, 2026-09-18.** The oldest unmet claim in this document: the risk table had said "format version stamped and checked" since the first draft, and nothing was stamped, so the health check reported it as UNKNOWN. Now `kArtefactFormatVersion` in the commandlet writes two rows into `MANIFEST.md` - the format, and the plugin version that wrote the set - and the health check compares the first against `plugins/ue-memory-stack/artefact-format.json`. Three places have to agree, so `tools/check_artefact_format.py` fails the repository when they drift: a stamp nobody compares is decoration.

`MANIFEST.md` was the right home rather than a new file: it already exists, already changes on every run, and is already excluded from the determinism check. Stamping every artefact would make each regeneration a 457-file diff, which is why that file exists at all.

**And a fourth instance of one bug, which earned a gate.** The build script derived `-PluginSource` from `$PSScriptRoot` in a parameter default, which is empty on Windows PowerShell 5.1 - so it died before its first line, and had therefore never been run on 5.1 at all. Same bug as the Serena installer, the config loader and `Sync-Shared.ps1`. Four occurrences is a missing check, not bad luck: `tools/check_ps_script_root.py` now fails the repository for any shipped script that does it.

## Decisions, taken 2026-09-17

1. **Two plugins**: the stack, and the benchmark.
2. **Names**: `ue-memory-stack` and `ue-memory-bench`. Commands read `/ue-memory-stack:update`.
3. **The repository is its own marketplace**, with relative plugin paths. No release step per change, and it is what the depot copy needs anyway.
4. **Project scope by default**, with the trust step written down rather than discovered. See below.
5. **The C++ plugin ships inside the Claude plugin**, and `setup` copies it from there into each project. One copy is the source, every project copy is checkable against it, and `doctor` compares them.
6. **The docs move into the plugin**, except anything generated or project-specific. The guides are part of the tool; `examples/` and the seed project are not.

## What is verified and what is not

Verified on this machine: the auto-discovery paths, the manifest schema including `userConfig`, `${CLAUDE_PLUGIN_ROOT}` semantics and its behaviour on update, the marketplace source types in use, and the full `claude plugin` CLI surface including `validate`, `tag` and `eval`.

Verified since, with a scratch workspace shaped like a depot, then removed: a directory marketplace validates and installs; a **relative** path in `extraKnownMarketplaces` resolves against the project and a plugin installs from it, while `marketplace add` stores an absolute one; a project-scope plugin loads and reports its components; a version bump and a new command in the marketplace directory are picked up **from disk with no update command at all**; and `claude plugin update` defaults to user scope and fails on a project-scope plugin until told `--scope project`.

Also found, and useful: `claude plugin details <name>` prints a projected always-on token cost per plugin. That is how the standing-context question gets answered in Phase 5 rather than argued.

Still not verified, and worth a spike before Phase 5: what a `SessionStart` hook costs in practice, whether `PreToolUse` can refuse a write cleanly enough to read as guidance rather than an error, and whether three skills crowd the context more than one skill with references.
