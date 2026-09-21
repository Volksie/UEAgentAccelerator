# Getting started

This takes you from nothing to a working stack on your own Unreal project. It's ordered so you have something useful after step 5, and the optional layers come last, because they're the ones most likely to fight your toolchain.

Every command below addresses the plugin as `${CLAUDE_PLUGIN_ROOT}`, which is the folder Claude Code unpacked it into. There is nothing to clone and no path to remember. Outside a Claude session, `claude plugin details ue-memory-stack` prints the folder if you want to run a script by hand.

## What you need first

| | Why |
|---|---|
| Unreal Engine 5.8 or later, installed or source built | The dump runs as a commandlet inside the editor |
| A C++ Unreal project that builds | The plugin walks your reflected classes, so there have to be some |
| Visual Studio with the C++ toolchain | To build the editor target |
| PowerShell 5.1 or later | The scripts. Nothing here needs PowerShell 7 |

You don't need Python, Serena, clangd or a coding agent to get through steps 1 to 6. Those come in later and each one is optional.

**Note:** everything below assumes Windows, because that's what the scripts are written for. Nothing in the C++ plugin is Windows specific, so if you're on Linux or Mac the commandlet invocation in step 4 is the only part you need, and *03-running-the-dump.md* gives it in full.

## 1. Install the plugin

```bash
claude plugin marketplace add Volksie/UEAgentAccelerator
claude plugin install ue-memory-stack@ue-agent-accelerator --scope project
```

`--scope project` records it in your project's *.claude/settings.json*, so everybody else on the tree gets it from source control instead of installing it themselves. **A project-scope plugin loads only after the workspace trust prompt is accepted** — dismiss that prompt and you get a session with no plugin and no error to explain why. `claude plugin list` is how you tell the difference.

If nobody on your team has GitHub access — the normal case on a Perforce tree — the marketplace can live in the depot instead, and nobody has to clone anything. *09-installing-from-a-depot.md* is that route: one person exports it, and everybody else syncs and runs one script. Read it before writing a settings file by hand, because two things there are counterintuitive — a committed settings file does not install the plugin, and `marketplace add` stores an **absolute** path, which works on the machine that ran it and nowhere else.

## 2. Set the project up

In a Claude session in your project:

```
/ue-memory-stack:setup
```

Or directly, which does the same thing:

```powershell
${CLAUDE_PLUGIN_ROOT}/scripts/Initialize-AgentMemoryProject.ps1 -ProjectPath D:\MyGame\MyGame.uproject
```

That writes the project-side half of the stack: the C++ plugin into *MyGame\Plugins\UEAgentAccelerator* and enabled in the *.uproject*, a *.claude/agent-memory-stack.json* filled in from what it found, a *CLAUDE.md* from the template for you to rewrite, and the per-module rule files. It backs the descriptor up first, to *MyGame.uproject.bak*.

**It writes each of those only when it is absent.** Run it twice and the second run changes nothing and says so. That matters most for *CLAUDE.md*, which is an hour of your writing by the time you're finished with it — a setup script that clobbers that on a re-run is worse than one that never existed.

`-Check` reports and writes nothing, exit 1 if anything is missing. That is the one to run on a tree somebody else set up, and it is also what tells you, after a plugin update, that a project is still carrying the old C++ source. Re-running fixes that, and then **rebuild before your next dump**: the old DLL builds and runs perfectly and writes the old format.

**A tree with several projects** wants `-Root` pointing at the folder above them all, so they share one config. Left to itself it uses the folder holding the *.uproject*, which is right for one project and wrong for four.

**Sharing one copy of the C++ plugin** between projects is `-Mode Reference`, and it wants `-PluginSource` with it: the path you give is written into the descriptor as an `AdditionalPluginDirectories` entry, so it has to be a path your whole team has and one that keeps existing — a depot or a share, not this plugin's own folder inside the plugin manager's cache. Without `-PluginSource` that is exactly what it writes, and it says so. The binaries are built per project either way, so every project you do this on still needs its own build in step 3. Building one project and dumping another writes old format files, reports success and exits 0, which is a bad half hour.

**Note:** the descriptor is edited as text, so the diff is the few lines that changed and the file keeps its indentation and line endings.

**If your project is in Perforce**, the descriptor is checked out first, and so is the dump's output folder in step 4. You don't have to do anything, but it's worth knowing it happens, and worth knowing why it happens on a descriptor that was already writable: a file of type `text+w` stays writable whether or not it's open, so without the checkout the change is made and never joins a changelist. *02-install-plugin.md* has the rest, including what happens when the server is down.

## 3. Build your editor target

```powershell
${CLAUDE_PLUGIN_ROOT}/scripts/Build-UEAgentAccelerator.ps1 -ProjectPath D:\MyGame\MyGame.uproject -EnginePath C:\UE_5.8
```

`-EnginePath` is the engine root, the folder containing *Engine\Binaries*. On a source built engine that's the folder holding *Engine*, not the *Engine* folder itself.

The editor target is read from the *Target.cs* files under *<Project>\Source* rather than assumed to be `<ProjectName>Editor`, because plenty of projects don't follow that convention. A project renamed part way through development is the usual way it happens: the descriptor gets the new name and the target keeps the old one. If a project has more than one editor target the script says which and stops, and you choose with `-Target`.

This calls UnrealBuildTool directly rather than *Build.bat*, because *Build.bat* takes a batch level lock that survives a cancelled build and then blocks the next one. If you've ever had a build sit there doing nothing after you pressed Ctrl-C, that's what it was.

When it finishes it checks that the plugin DLL is actually newer than the plugin source, and stops if it isn't. That check is worth more than it looks, because a dump against a stale DLL succeeds, logs its usual summary, and quietly writes the old format.

## 4. Run the dump

```powershell
${CLAUDE_PLUGIN_ROOT}/scripts/Invoke-AgentMemoryDump.ps1 -ProjectPath D:\MyGame\MyGame.uproject -EnginePath C:\UE_5.8
```

Seven seconds or so of editor startup, then it writes. A large project takes a few minutes, almost all of it the Blueprint graph walk. For scale: 96 modules, 967 classes and 611 Blueprints took three minutes and produced 1,383 files.

Steps 3 and 4 together are what `/ue-memory-stack:update` runs, and once this loop works that is how you'll do it.

If it reports zero modules or zero Blueprints, don't guess: *troubleshooting.md* lists what each of those means and they both have one likely cause each.

**A non-zero exit with files written is not a failure.** *UnrealEditor-Cmd* returns non-zero if anything logged an `Error` during the run, including Blueprint errors in content that has nothing to do with this, so on a project of any age it's the normal result. Judge it on the summary lines and the file count. The script says so when it happens rather than leaving you to wonder.

The dump walks every module in the descriptor, middleware included, and that's the intended behaviour rather than something to trim. Vendor code is often exactly what you need the artefacts for: you have your own code and your own commit history to fall back on, and for Wwise or a marketplace plugin you have neither, so a generated file listing a class's reflected functions and specifiers is the only description of it you own. `-Modules` exists for the case where the walk itself becomes a problem, not as routine tidying.

**Where the output goes.** `-OutDir` defaults to *Docs/AgentMemory* relative to the folder holding the *.uproject*, which is right when that folder is the root of the project. It isn't always: a tree where the descriptor sits in a subfolder and the docs live a level above it wants an explicit path, or you get a second *Docs* folder next to the real one.

```powershell
${CLAUDE_PLUGIN_ROOT}/scripts/Invoke-AgentMemoryDump.ps1 -ProjectPath D:\Work\Tree\MyGame\MyGame.uproject -EnginePath ... -OutDir D:\Work\Tree\Docs\AgentMemory
```

Keep it consistent with the paths in your *CLAUDE.md* routing table and in *.claude/agent-memory-stack.json*, since those are what send the agent to the right file. And give each project its own folder: two projects in one tree dumping to the same *-OutDir* overwrite each other, and the result looks like a dump that half worked rather than like two that collided.

## 5. Look at what you got

Everything lands in *Docs/AgentMemory* under your project:

```
Docs/AgentMemory/
  index.md                  one row per class
  classes/<Class>.md        specifiers, replication, doc comments
  Blueprints.md             index of Blueprints by native parent
  blueprints/<Parent>.md    the Blueprints under one parent
  BlueprintCallers.md       index of which classes have Blueprint callers
  bpcallers/<Class>.md      the actual call sites, per class
```

Open a couple of *classes/* files for classes you know well and check they say what you expect. This is the point at which people find out something surprising about their own code, which is a good sign rather than a bad one.

Commit all of it. The output is deterministic and carries no absolute paths, so it diffs sensibly and belongs in source control next to the code it describes. Deterministic means byte for byte: dumping the same tree twice with no source change between the runs produces identical files, which is what makes a real diff worth reading. If you would rather CI generated it, or would rather not commit generated files at all, *06-keeping-it-fresh.md* weighs those up. The one thing worth knowing now is that an agent that finds no artefacts does not complain, it just goes back to grepping.

**Doing several projects in one tree:** build and dump one, then build and dump the next. Don't build both and then dump both. Editor targets sharing one source engine are matched to it by a `BuildId` that a substantial build regenerates, so building the second project can leave the first one unable to find its own modules. The dump checks for this and stops rather than failing obscurely, but the ordering avoids it.

## 6. Write your CLAUDE.md

Step 2 put the template at the root of your tree. This is the step it's tempting to skip, and it's the one that does most of the work. The artefacts on their own are just files in a folder. What makes an agent read them instead of reaching for ripgrep is a routing table telling it which layer answers which question.

Work through it and replace the placeholders with your own module map, your own conventions and your own paths. *04-writing-your-claude-md.md* goes through it row by row and explains which rows are load bearing and why.

The per-module rules landed in *.claude/rules/* at the same time, as *Module.md.template* and *Building.md.template*, for the detail that only matters once you know which module you are in. **The suffix stays until you fill one in and rename it**, and that is deliberate: *.claude/rules/\*.md* is auto-loaded into every session, so a file of placeholders sitting there is read as fact with the same authority as the one you wrote. Rename it to *Module.md* when it says something true, and it is loaded from then on. There's one more template that step 2 doesn't place, because where it goes is a judgement call: *${CLAUDE_PLUGIN_ROOT}/templates/design-doc.md.template* into your own docs folder, for Layer 5.

Budget an hour on the routing table. It's prose about your codebase, so nobody can write it for you, and it's the part with the highest return.

## 7. Check it actually worked

Ask your agent three questions you already know the answer to, one from each layer:

1. Something about a specifier or a replication condition. It should read *classes/<Class>.md* and not grep a header.
2. A blast radius question, "what breaks if I change this function". It should read the C++ callers **and** *bpcallers/<Class>.md*. If it only does the first, the routing table needs to be firmer.
3. Something about why a system works the way it does. It should reach for your design docs.

What you're checking is the route, not just the answer. A right answer by the wrong route means the next question gets a wrong one.

`/ue-memory-stack:status` is the mechanical half of this: what exists, and whether it still describes the code.

## 8. Fill in the tree's facts

Step 2 wrote *.claude/agent-memory-stack.json* from what it could see on disk, and left `<ANGLE BRACKET>` placeholders wherever it couldn't — your engine path, your Serena project name, your scheduled task. Grep the file for `<` and finish it.

Every path in it is relative to your repository or client root, because the file is committed and read on machines rooted somewhere else.

With it filled in, the refresh reads it instead of repeating four arguments:

```powershell
${CLAUDE_PLUGIN_ROOT}/scripts/Update-MemoryStack.ps1 -StackConfig D:\MyGame\.claude\agent-memory-stack.json
```

Anything you pass explicitly still wins, and a project whose *.uproject* is not where the file says stops the run there rather than forty minutes into a build.

**Why a file rather than arguments.** Two halves of this stack need the same facts: whatever script gets Serena and clangd working on a machine, and whatever refreshes the artefacts afterwards. Written out in both, they drift, and the drift is silent in the usual way — a project in the refresh script but missing from Serena's `ls_workspace_folders` is not an error, it is a project regenerated for ever that no symbol query can see. *${CLAUDE_PLUGIN_ROOT}/templates/scripts/AgentMemoryStack.Config.ps1* is the loader your own setup script reads it with, so both halves get their list from the same place.

## Optional: Layers 0 and 1

Symbol queries, so the agent can ask for definitions and references and get compiler grounded answers rather than text matches.

```powershell
${CLAUDE_PLUGIN_ROOT}/scripts/New-CompileDatabase.ps1 -ProjectPath D:\MyGame\MyGame.uproject -EnginePath C:\UE_5.8
```

Then install Serena and point it at your tree. `/ue-memory-stack:serena-setup` installs the build whose fixes Layer 1 needs on an engine tree, and *05-serena-clangd.md* covers the rest — more usefully, it covers the several ways Layer 1 comes up looking healthy while being bound to the wrong thing.

**Register Serena over HTTP rather than the default `stdio`**, and start it at logon. The default spawns one Serena and one clangd per session, all indexing the same tree, and makes you wait out the language server warm up every time you open a chat — around ten minutes with the engine in the workspace. That cost is the usual reason people conclude Layer 1 is not worth it. One long lived server pays it once. Same doc.

Leave this until the rest is working. It's where the leverage is and it's also where the risk is, so there's no sense taking the risk before you've banked the easy wins.

## Seeing it work on a known good project before your own

The repository this plugin comes from has *seed/AccelDemo*: a deliberately tiny project, three gameplay classes, three Blueprints, both flavours of replication condition, and one function whose comment disagrees with its body on purpose. It's there so you can watch the whole loop work on something known good, which means that when your own project goes wrong you already know what right looks like.

It isn't shipped inside the plugin, so this one does need the repository. If you have it:

```powershell
${CLAUDE_PLUGIN_ROOT}/scripts/Build-UEAgentAccelerator.ps1 -ProjectPath <repo>\seed\AccelDemo\AccelDemo.uproject -EnginePath C:\UE_5.8
${CLAUDE_PLUGIN_ROOT}/scripts/Invoke-AgentMemoryDump.ps1  -ProjectPath <repo>\seed\AccelDemo\AccelDemo.uproject -EnginePath C:\UE_5.8
```

It already has the plugin enabled through a relative path, so there's no setup step. Compare what lands in *seed/AccelDemo/Docs/AgentMemory* against the copy in *examples/*. They should match.

**Important:** `GetReachDistance` in *ADStaminaComponent* has a comment saying the value is in metres over a body that returns centimetres. That's deliberate, it's a benchmark fixture for the class of question where reading the comment alone gives you the wrong answer. Please don't fix it.
