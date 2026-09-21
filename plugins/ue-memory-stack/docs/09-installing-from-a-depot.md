# Installing from a depot

For teams where the repository isn't on everybody's machine, and shouldn't have to be. One person puts the plugin in Perforce; everybody else gets it with a sync and one command, having cloned nothing.

Nothing here is Perforce specific. A network share or any other way of putting the same folder on everybody's disk works the same way.

## What you can and can't get

Read this before you promise your team anything, because the obvious expectation is wrong.

A marketplace can be a **directory**, so a depot can hold one, and a project's *.claude/settings.json* can name it. What that file does **not** do is install the plugin. Claude Code's own documentation, under *Configure team marketplaces*, says so as of version 2.1.195: adding a marketplace doesn't install plugins that come from an external source, and a plugin that only the project's settings enables

> doesn't load until the team member installs it.

Trusting the folder adds the marketplace. The install is a separate step, per person, per project. And an uninstalled plugin fails in the quietest way there is: the commands simply aren't there, with no error and nothing in the settings file to suggest anything is missing.

So the honest shape of this is: **the depot carries everything, and each person runs one command once.** A script in the depot copy is that command.

## The layout

```
//depot/Tools/ClaudePlugins/UEAgentAccelerator/     the marketplace
    .claude-plugin/marketplace.json
    plugins/ue-memory-stack/...
    plugins/ue-memory-bench/...
    Install-FromDepot.ps1                          what everybody else runs
    LICENSE, NOTICE.md

//depot/MyGame/.claude/settings.json                submitted with the project
```

Both plugins go in, because the manifest lists both and a manifest naming a directory that isn't there is a broken marketplace. Which ones get *installed* is a separate decision, and the benchmark is normally left out: it's the machinery for reproducing published numbers, not for making a game.

## The first developer, once

Clone the repository, or download it once. Then, from it:

```powershell
tools\Export-ToDepot.ps1 -DepotPath D:\p4\Tools\ClaudePlugins\UEAgentAccelerator -ProjectRoot D:\p4\MyGame
```

That copies the marketplace payload and *Install-FromDepot.ps1* into the depot workspace, and writes *D:\p4\MyGame\\.claude\settings.json*:

```json
{
  "extraKnownMarketplaces": {
    "ue-agent-accelerator": {
      "source": { "source": "directory", "path": "../Tools/ClaudePlugins/UEAgentAccelerator" }
    }
  },
  "enabledPlugins": { "ue-memory-stack@ue-agent-accelerator": true }
}
```

It merges into that file rather than replacing it, so permissions and hooks already there survive, and it backs the original up once. Then reconcile and submit both paths; the script prints the commands and runs none of them, because a depot layout is yours.

Two details in that file that are easy to get wrong:

**The key is the marketplace's own name.** `ue-agent-accelerator` is what *marketplace.json* declares, and the CLI registers a marketplace under that name. An alias of your own choosing gives you a plugin id — `ue-memory-stack@my-alias` — that nothing else agrees exists, and it fails as silently as everything else here. The export defaults to the declared name and warns if you override it.

**The path is relative, and that is deliberate.** `claude plugin marketplace add` resolves whatever you give it, relative or not, to an **absolute** path and stores it in the person's own settings — which is right per machine and wrong in a file everybody syncs. So the committed file carries a relative path, and nothing but this script puts one there.

Several projects sharing one depot copy: run the export once per project, or once with no `-ProjectRoot` to print the block and paste it into each, with the path made relative to each.

## Everybody else, once each

```
p4 sync
cd D:\p4\MyGame
..\Tools\ClaudePlugins\UEAgentAccelerator\Install-FromDepot.ps1
```

That registers the marketplace from the depot copy and installs the plugin at project scope. It's safe to run again, and running it again is how a synced change reaches you: an already-known marketplace is refreshed, and an already-installed plugin is uninstalled and reinstalled, because that is the only thing that replaces the cached copy a session actually loads. `-Bench` also installs the benchmark plugin; `-WhatIfOnly` prints the two CLI commands and runs neither, if you'd rather do it by hand or put it in your own onboarding script.

Then open the project in Claude and **accept the workspace trust prompt**. A project-scope plugin loads only after the workspace is trusted, and MCP servers, LSP servers and hooks stay unloaded until then. Somebody who dismisses that prompt gets a session with no plugin and no error.

Then, once per project:

```
/ue-memory-stack:setup      writes this project's own files
/ue-memory-stack:update     builds and generates the artefacts
```

## How to tell it worked, and two things that will mislead you

Type `/ue-memory-stack:` in a session. If the commands complete, it's loaded.

**`claude plugin list` reports personal and managed scope, not a project's settings.** Run in a workspace whose project file enables a depot plugin but which has never had the install run, it says "No plugins installed" and `claude plugin marketplace list` doesn't mention the marketplace — which is accurate, and is also what it says when everything is fine except that you're reading the wrong scope. Once the install has run, `claude plugin list` does show it, with `Scope: project`. So that command is worth running after the bootstrap and worth ignoring before it.

**A settings file that looks complete is not evidence of anything.** The file is what it should be whether or not anybody has installed the plugin. That is the whole trap of this route in one sentence.

## Updating

One person pulls a new version of the repository and re-runs the export:

```powershell
tools\Export-ToDepot.ps1 -DepotPath D:\p4\Tools\ClaudePlugins\UEAgentAccelerator -Check
tools\Export-ToDepot.ps1 -DepotPath D:\p4\Tools\ClaudePlugins\UEAgentAccelerator
```

`-Check` writes nothing and exits 1 when the depot copy is behind, which is the form for a release step or a build. Then submit.

Everybody else: `p4 sync`, run *Install-FromDepot.ps1* again, and **restart Claude**. All three steps are load bearing, and the second one is the one people will skip.

**A session does not read the depot directory. It reads a cached copy**, under *~/.claude/plugins/cache/\<marketplace\>/\<plugin\>/\<version\>*, and **the version string is the cache key**. Measured, on CLI 2.1.263: change a file in the marketplace directory without changing the version and `claude plugin marketplace update` reports success, `claude plugin update` reports *already at the latest version*, and every session keeps loading the old copy. Nothing anywhere says so. Only a reinstall — or a version bump — replaces the cache, and that is why the bootstrap now uninstalls before it installs.

So for whoever owns the depot copy: **bump the version in `plugin.json` and `marketplace.json` for any change you expect people to receive.** It is not a formality, it is the mechanism. `claude plugin details` reads the directory live, which makes this trap worse rather than better: the inventory you check will show your change while every session ignores it.

Two things the export will stop you doing, both learned the boring way:

- **A version disagreement.** *marketplace.json* declares a version per plugin and each *plugin.json* declares its own, by hand, in two places. The export refuses rather than copying the disagreement into a depot where everybody inherits it.
- **Files you removed upstream.** A file that's in the depot copy and not in the repository any more is reported and left alone rather than deleted, because deleting things in somebody's workspace isn't a script's business. Until you delete it deliberately, a command you retired keeps working for everybody who syncs, which is the confusing way round.

## Updating has two halves, and conflating them is how this goes wrong

```
p4 sync + Install-FromDepot.ps1 + restart    the tools and instructions
/ue-memory-stack:update                      the artefacts in your project
```

Updating the plugin doesn't refresh your artefacts, and refreshing artefacts doesn't update the plugin. A plugin update can also change what the dump writes, which makes existing artefacts wrong in a way nothing reports — so when release notes say a format changed, regenerate.

And the C++ plugin in each project is a *copy*, made by `/ue-memory-stack:setup`. After a plugin update, run setup again in each project: it notices the copy came from an older version, replaces it, and tells you to rebuild before the next dump. Skip that and the editor builds the old source happily and writes the old format.

## What the depot copy doesn't contain

The seed project, the worked examples and the design notes stay in the repository: none of them is read by a plugin, and copying them puts hundreds of files in a depot for no reason.

The benchmark **does** travel, because it is a plugin's contents rather than a repository folder - about 600 KB of tools, method notes and recorded results. It is copied because a manifest naming a plugin directory that is not there is a broken marketplace, but it is not *installed* unless somebody asks: the bootstrap installs the stack alone, and `-Bench` adds the other one.
