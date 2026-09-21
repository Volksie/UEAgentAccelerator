# Layer 3: the engine API surface

**Opt-in.** Nothing else in the stack depends on it, so you can add it later, and it needs a build step of its own before it answers anything.

The layer has three parts: an **exporter** that rides the UnrealHeaderTool run every build already does, a **store** that merges what it emits with on-disk descriptors and the Layer 2 artefacts, and a **server** that answers six kinds of question over the result. The exporter is C++ and lives in the plugin's `ue-plugin/UEAgentAccelerator`; the store and the server are Python with no dependencies beyond the standard library, in `${CLAUDE_PLUGIN_ROOT}/engine-api/`, which has its own README with the build and run commands.

## What it's for

Layer 2 walks the live reflection system, which means it only sees what the editor you're running has actually loaded. That's the right trade for your own code, and it's no help at all for a question like "is this module available on that console", where the answer has to be true for a platform you have never built for.

This layer rides the UnrealHeaderTool run that every build already does. You cannot build for a platform without running UHT over that platform's modules, so the coverage comes for free with the builds you already run.

## What it cannot do, and must not pretend to

**Replication conditions.** UHT sees `Replicated` and `ReplicatedUsing` and stops. The `COND_` lives in `GetLifetimeReplicatedProps` and does not exist until runtime, so it appears in no header and no UHT pass will ever find it.

The field stays null here and is written by Layer 2 instead. That distinction matters more than it looks: absence and ignorance have to look different in the output, or a reader treats "we didn't look" as "there isn't one".

## Why it's a separate plugin

This is the part that costs an afternoon if you work it out yourself.

UBT's `EnumerateUbtPlugins` scans the engine's and the project's own *Build*, *Source*, *Plugins* and *Mods* directories for `*.ubtplugin.csproj`, compiles what it finds, and registers it with UHT if the assembly carries `[UnrealHeaderTool]`. It **never consults `AdditionalPluginDirectories`**, and the csproj it finds has to sit under an enabled plugin's directory.

So an exporter parked in a shared plugin folder is never discovered, never compiled and never registered, and nothing tells you why.

The pattern that works keeps one copy of the source and puts a thin shim under each project:

```
Plugins/UEAgentAcceleratorUht/
  UEAgentAcceleratorUht.uplugin              "Modules": [], it hosts no module
  Source/
    UEAgentAcceleratorUhtPlugin.ubtplugin.csproj   compiles the shared .cs from up the tree
    ...csproj.props                                EngineDir, machine specific, not committed
```

The *.uplugin* has an empty `Modules` array because the plugin exists only to be a directory UBT will look inside. The csproj pulls the source in from wherever the real copy lives:

```xml
<ItemGroup>
  <Compile Include="..\..\..\..\..\plugin\UEAgentAccelerator\Source\UEAgentAcceleratorUht\*.cs" />
</ItemGroup>
```

A second project that needs the exporter gets another thin csproj like that one, never another copy of the `.cs`. The seed project here carries a working example.

## `ModuleName` is a trap, and it fails silently

`[UhtExporter]` requires a `ModuleName`, and it must name a module present in **that target's** manifest. If it is missing, UHT skips your exporter, logs one line about it, and still reports `Result: Succeeded`. You get a green build and no output.

The obvious value is wrong. Naming your own plugin's editor module looks right, because it ties the exporter to the plugin being enabled. It also produces **nothing at all for Game targets**, because an `Type: Editor` module is not in a Game target's manifest. Measured on a sample game: its Editor target had 707 modules with that module present, its Client and Server targets 317 and 312 with it absent from both.

A console target is a Game target. So the failure lands exactly where this layer is supposed to earn its keep: console targets would export nothing, report success, and look like consoles with no API surface.

Name a module that exists in every target type instead. `CoreUObject` does. You do not lose the plugin gate by doing so, because UBT only compiles and registers a `*.ubtplugin.csproj` found under an **enabled** plugin, so with the plugin off the exporter is never registered at all. `ModuleName` was a second, redundant gate that happened to be the wrong shape.

Two consequences worth knowing:

- **Put the target in the filename.** `MakePath` writes into the named module's output directory, so every target writes to the same place. With a plain `.agentapi.json` the second target silently overwrites the first for every shared module, and `Engine` is shared by all of them. Stamp the file as `<Module>.<Target>.agentapi.json` and put `target` in the content too, or "seen on a console as well as Win64" is unrepresentable.
- **Await the export tasks.** Creating them and returning lets the session tear down first. That produced one write, no files, and a successful build.

**Note:** the `.props` file holding `EngineDir` is machine specific and is gitignored. Copy the *.props.template* beside it and fill in your engine path, or the csproj can't resolve the engine assemblies it references.

**Note:** those relative `Compile Include` paths are the fragile part. Move the shared folder and the build fails complaining about no source files rather than about a missing path, so if you rename anything, grep the csproj files.

## Declared platform availability, and why it is a commandlet

The exporter above describes what UHT saw. A second question sits next to it: **is this module even
available on that platform**, for a platform you have never built for. That is answered from the
`.uplugin` and `.uproject` descriptors rather than from any build, and `ModuleAvailabilityCommandlet`
in this plugin does it.

It calls `FModuleDescriptor::IsCompiledInConfiguration` across every descriptor, platform and target
type and writes the resolved matrix out. The point is that it **calls the engine's function rather
than reimplementing its rules**. That matters for two reasons, and we learned the second one the
expensive way.

The first is licensing: a reimplementation of engine logic is a derivative of engine source, and that
cannot be published. The second is that it was also simply wrong. Before the reimplementation was
deleted it was run against the engine's own answer over 79,965 rows. They agreed on 79,956 and
disagreed on nine, all because the descriptor key is spelled `ProgramAllowlist` with a lowercase L
while the reimplementation looked for `ProgramAllowList`. **Unreal's JSON reader is case insensitive
and a Python dictionary is not.** The defect was a layer below the algorithm being copied, where no
amount of care with the logic would have found it.

So: if the engine exposes a function that decides something, call it. `IsCompiledInConfiguration` is
`PROJECTS_API`, and this plugin already depends on `Projects`.

```
UnrealEditor-Cmd.exe <project>.uproject "-run=UEAgentAcceleratorTools.ModuleAvailability" ^
  -unattended -nopause -nosplash -NullRHI -Multiprocess
```

### Choosing platforms

By default it resolves the desktop and mobile platforms plus every **confidential** platform this engine
install knows about, from `FDataDrivenPlatformInfoRegistry::GetConfidentialPlatforms()`. A console only
appears there when its platform extension is installed, so on a machine licensed for a console you get it
without naming it anywhere, and on one that isn't you get nothing you aren't entitled to.

To pick the list yourself, set it in the project's *Config/DefaultEditor.ini*. It replaces the default
entirely, so list everything you want, including the desktop platforms:

```ini
[/Script/UEAgentAcceleratorTools.ModuleAvailabilityCommandlet]
+Platforms=Win64
+Platforms=Android
+Platforms=<a console you're licensed for>
```

`-Platforms=Win64,Android,...` on the command line overrides the ini, which is handy for a project whose
config isn't yours to edit.

The name is the engine's platform name, the one its descriptors use in `PlatformAllowList`.
**Important:** a misspelt name isn't rejected. `IsCompiledInConfiguration` reads any module with no
platform list as available, so a typo produces a matrix that looks entirely plausible. Check the counts
for a new platform (step 4 below) against one you know, rather than trusting the run.

The input tier has one console-specific sentence too: the note in *Input.md* about controller labels is
generic unless you point `InputLabelNoteFile` at a text file of your own wording, in the
`[/Script/UEAgentAcceleratorTools.AgentMemoryDumpCommandlet]` section, or pass `-InputLabelNote=<file>`
to the dump. The file replaces the note's bullet points line for line, and a path is relative to the project.

### Adding a platform

1. Add it to the list above, in every project you run the commandlet on.
2. Run the commandlet on each project. It writes *Docs/AgentMemory/module-availability.json*.
3. Run `build_descriptor_tier.py`, then `build_api_db.py`. The descriptor tier reads the file from step 2,
   so running it first fails with a message telling you to run the commandlet.
4. Check it landed: `engine_api_sql` with `SELECT platform, COUNT(*) FROM module_platforms GROUP BY platform`.

That's the **declared** side, and it needs no SDK. To have the platform **observed** as well, build its
Game target with `-AgentMemoryApi` so the exporter writes that target's modules, then run
`build_api_db.py` again. `module_observed` is where those rows go, and `engine_api_platform` says
"declared, never observed" for any platform that has none.

Three things that will bite you:

- **Quote the `-run=` argument in PowerShell.** Unquoted, `-run=Module.Class` loses the class half and
  you get "looked like a commandlet, but we could not find the class". The scripts in this repo pass
  arguments as an array and are unaffected; typing it at a prompt is where this bites.
- **Run it once per project.** A commandlet only sees its own project's plugin directories, so two
  projects on the same engine report different plugin counts. Whatever consumes the output has to
  union them.
- **It writes UTF-8 explicitly, and that is not optional.** `FFileHelper::SaveStringToFile`
  auto-detects an encoding and wrote UTF-16 on the first run, which broke the reader on byte 0.

**Note:** the tooling that consumes this matrix is not in this repository yet. The commandlet ships
because it is part of the plugin and it stands on its own; the database it feeds does not.

## Why not use the exporter Unreal ships

`UhtJsonExporter` hands the live UHT module graph straight to `System.Text.Json`. That graph is cyclic by construction, types carry a back-reference to their owning class and functions are a linked list, so it throws

```
A possible object cycle was detected ... maximum allowed depth of 64
```

on every module and writes nothing. It ships with its options set to none, so it's off by default and nothing exercises it.

This exporter walks the graph and emits a flat projection instead of handing the graph to a serialiser. Cycles can't arise because nothing follows a back-reference: every cross-type link is written as a name, and names are resolved to ids in a later step.

## Running it

**The exporter** is off by default. Pass `-AgentMemoryApi` on the UHT command line, or set it in the `[UnrealHeaderTool]` config, and it runs as part of the build UHT was doing anyway. Because it is off unless asked for, having the plugin enabled costs a small csproj compile and nothing else.

**The store** is three commands, and each tier answers something the others cannot:

```bash
python ${CLAUDE_PLUGIN_ROOT}/engine-api/build_descriptor_tier.py --root <your tree>
# build with -AgentMemoryApi so UHT emits *.agentapi.json
python ${CLAUDE_PLUGIN_ROOT}/engine-api/build_api_db.py --root <your tree>
```

**The server** is stdio, registered with your client like any other MCP server:

```bash
python ${CLAUDE_PLUGIN_ROOT}/engine-api/mcp_server.py
```

It opens the database read-only and expects it beside itself, or wherever `ENGINE_API_DB` points.

## What the store carries that nothing else does

| | |
|---|---|
| Declared platform availability | Whether a module is available on a console or any target you have never built — read from descriptors and resolved by the engine's own function, so no console SDK is involved |
| Comment bodies | `extract_comments.py` indexes every comment block with a file and line, including the ones inside function bodies. Layer 2 carries only the doc comment on a reflected declaration, so a `// HACK:` three lines into a `.cpp` is in no artefact at all |
| One store, both halves | The same query reaches engine declarations and your project's, which is what makes "who references this" answerable across the seam |
| Its own schema | `engine_api_sql` with `query='schema'` returns every table and view with columns and the enumerations a query needs, in one call. Named views answer the recurring shapes — most-called symbol, Blueprint writes to C++ properties, plugins with modules unavailable per platform, modules by loading phase, what the index holds |
| What a Blueprint changed | `v_bp_tuning` puts declared variables and overridden defaults in **one list**, so "every value whose name contains *Height*, with what it would have been" is one query. This is the only route that reaches a **data-only** Blueprint's contents at all — the kind that has no graph, where the asset *is* its defaults |
| Blueprint to Blueprint | `v_bp_users` is the reverse index for calls and casts between Blueprints, which no compile-time tool can see. Kept out of the C++ edge table on purpose: they answer different questions and merging them would silently change what a row count means |
| Tick, as four facts | `v_bp_tick_cost` separates *can ever tick*, *starts with tick enabled*, *does Event Tick have anything connected*, and *is that node disabled* — reading any one alone gives the wrong answer. The fourth is the one the compiler never sees: a linked node that is switched off is not compiled, so it leaves the first three reading **exactly like a Blueprint with no tick node at all**. The view also has to reach Blueprint **components**, which have no `PrimaryActorTick` and so carry a null `can_ever_tick` while being perfectly capable of holding a disabled tick node |
| What loading drags in | `v_bp_load_cost` gives hard and soft package dependencies plus cast count, from the asset registry, **without loading anything** |
| Finding a name without knowing where it lives | `engine_api_search` covers the C++ surface and the new tiers under their own kinds: `kind='bp_variable'`, `'bp_override'`, `'bp_function'`, `'bp_asset'`, `'asset'`, `'input_binding'`, `'key_alias'`, alongside `'class'`, `'function'`, `'property'`, `'struct'`, `'enum'` and `'comment'`. So a variable is findable by name without knowing which Blueprint declares it |
| Key bindings and what people call them | `v_input_key` gives what a key is bound to with the console labels alongside; `v_input_layered` gives the keys more than one context binds, where which wins is a runtime question. `key_aliases` translates between the `FKey` an asset stores and the name a person uses, from the engine's own table — and `v_key_ambiguity` holds the one label that means two different keys |

## The database is not in this repository

It is generated, it is large — 69 MB for an engine plus three projects — and it describes *your* engine and *your* projects. The builders are here; the output is yours to make. `engine-api/.gitignore` keeps it out.

## Honest results, which is most of why this layer is interesting

A store like this is at its most dangerous when it is confidently empty. Three pieces exist for that:

- **`uncertainty.py`** marks a result whose emptiness is ambiguous — the class may live in a target nobody exported, or the Blueprint walk for that project may not have reached everything. For the Blueprint half it is exact rather than hedged: the generator writes one line saying how many Blueprints exist, how many are data-only and how many were walked, the merge job parses it into `bp_walk`, and an empty blast-radius result quotes it. **An artefact set written before that line existed is recognised and named**, so the answer describes the walk that actually produced it rather than the one shipping today.
- **`budget.py`** spends a measured response budget by rank, rather than truncating whatever the query emitted first. The row costs were measured against this store.
- **`stamp-edit.py`**, a `PostToolUse` hook, records when an indexed file is edited, so a session can tell the store is behind the tree. It matches `Write|Edit|Bash`, because a `sed` edits a file just as thoroughly as the Edit tool and a `Write|Edit` matcher never sees it.

Their ideas come from [code-review-graph](https://github.com/tirth8205/code-review-graph) (MIT); the code and every constant here are ours, measured against this store. *NOTICE.md* carries the attribution.

## Status

It works end to end: UBT discovers the csproj and compiles it during an ordinary build, the tiers merge, and the server answers. The database is always rebuilt from scratch rather than migrated, so after an update you rebuild it and that's it. The schema grows between versions (function signatures, decoded flag names and deprecation messages all landed after the first cut), and a rebuild is how you pick those up.

It earns its place on questions the other layers structurally can't answer: platform availability for targets you can't build, comments that live nowhere else, and SQL over the Blueprint, asset and input tiers. For anything the reflection dump already covers, prefer the reflection dump, because it's a file you can read without a server running.
