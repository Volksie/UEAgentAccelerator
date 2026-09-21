# Running the dump

```powershell
.\Invoke-AgentMemoryDump.ps1 -ProjectPath D:\MyGame\MyGame.uproject -EnginePath C:\UE_5.8
```

Or the commandlet directly, which is what the script wraps:

```
UnrealEditor-Cmd.exe D:\MyGame\MyGame.uproject ^
  -run=UEAgentAcceleratorTools.AgentMemoryDump ^
  -unattended -nopause -nosplash -NullRHI -Multiprocess
```

Seven seconds or so of editor startup, then it writes. A small project finishes in under a minute. A large one takes a few minutes, and nearly all of that is the Blueprint graph walk.

## Three of those arguments are not optional

Each one cost real time to find, so they're worth knowing rather than copying.

**`-Multiprocess`.** Without it the editor calls Turnkey, which shells out to *Build.bat* `-Mode=ValidatePlatforms`, which takes a global lock and then sits in a `ping` loop forever. See *TargetPlatformManagerModule.cpp:390*. The flag skips the SetupPlatforms UBT call entirely. If your dump hangs doing nothing, this is why.

**The module qualified `-run` name.** The module loads at `PostEngineInit`, which is after commandlet class lookup, so a bare `-run=AgentMemoryDump` gives "looked like a commandlet, but we could not find the class". Qualifying it as `UEAgentAcceleratorTools.AgentMemoryDump` resolves it with no rebuild.

**`-NullRHI`.** There's no graphics device in a commandlet.

`-unattended` and `-nopause` matter less but you want them in a script, because without them a dialog can block forever with nothing on screen to click.

## Options

| Option | What it does |
|---|---|
| `-Out=<dir>` | Where to write. Relative paths are relative to the project folder, absolute paths are used as given. Defaults to *Docs/AgentMemory* |
| `-Modules=A,B` | Walk only these modules instead of discovering them from the project descriptor |
| `-NoBlueprintGraphs` | Skip the graph walk |

`-NoBlueprintGraphs` is the one to think about. The graph walk is the expensive half, and it's also the half that produces the blast radius answers, which is the thing nothing else in the stack can do. Only reach for it if the walk becomes a real problem.

`-Modules` is worth using if your project pulls in plugin modules you don't care about. The dump discovers modules from the project descriptor plus enabled non-engine plugins, which includes this plugin itself, so your index will list its commandlet class alongside your own. That's harmless and expected, but if you'd rather not see it, name your own modules explicitly.

## What lands where

```
Docs/AgentMemory/
  index.md                  one row per class
  classes/<Class>.md        specifiers, replication, doc comments

  Blueprints.md             index of Blueprints by native parent
  blueprints/<Parent>.md    the Blueprints under one parent, linking to each bp/ file
  bp/<stem>.md              ONE BLUEPRINT IN FULL: what it changed from its parent, the
                            variables it declares, its components and widgets, tick,
                            functions, events, dispatchers, timelines, interfaces, the
                            Blueprints it calls into, and what loading it drags in

  BlueprintCallers.md       index of which classes have Blueprint callers, and one line
                            stating what the walk covered
  bpcallers/<Class>.md      which Blueprints use a C++ symbol: call, read, write, bind
  bpusers/<stem>.md         which Blueprints use a BLUEPRINT - calls and casts

  Assets.md                 index of every asset by class, from registry tags
  assets/<Class>.md         the assets of one class, with row struct or schema where
                            the registry carries it

  Input.md                  index of input mapping contexts
  input/<stem>.md           one context: every key it binds, to what, with triggers
  inputkeys/<Key>.md        one key: every context that binds it - the reverse index

  blueprints.jsonl          the Blueprint model as data, one line per Blueprint
  assets.jsonl              the registry tier as data
  bpcallers.jsonl           the C++ edges as data
  bpwalk.json               what the walk covered, as data
  input.jsonl               the bindings as data

  MANIFEST.md               what wrote these, in which format, and WHICH TIERS IT CONTAINS
```

**The `.jsonl` files are the same data as the Markdown beside them, not a second derivation of
it.** The commandlet builds one model per Blueprint and writes it twice - once as a document to
read, once as a line of JSON to query. Layer 3 loads the JSON and does not parse the documents,
because parsing a document meant for reading breaks silently when its layout changes. If you are
writing a tool, read the `.jsonl`; if you are reading, read the Markdown.

**`bpcallers/` and `bpusers/` are one letter apart and answer opposite questions.**
`bpcallers/<Class>.md` is *which Blueprints use this C++ symbol*. `bpusers/<stem>.md` is *which
Blueprints use this Blueprint* - a call into another Blueprint's function, or a `Cast To`, which is
a hard reference and the usual reason loading one asset drags in twenty. No C++ tool sees either:
renaming the target still compiles, and ripgrep skips `.uasset` silently.

**A Blueprint that REPLACES a native component's class is diffed, not just reported as swapped.**
Changing the class is one row; what the new component is *tuned* to is another set of rows entirely,
and without them every layer answers questions about that component from the **parent** — a character
that swaps its movement component and retunes its speeds reports the parent's speeds, confidently.
The diff runs over the properties the two classes share, compared against the **parent's template**
rather than the new class's defaults. That comparison is the part that matters: a replaced
subobject's archetype is its own class's CDO, so everything the parent's constructor already set is
serialised into the asset and *looks* changed.

**Two tiers have deliberate limits, and they say so in their own files.** The asset tier reads
registry tags and never loads, which is what makes it affordable on a project with thousands of
assets - so it covers **enabled content only**, because a disabled plugin never mounts and the
registry holds nothing for it. *Assets.md* names any that were skipped. The input tier is the
opposite: it **does** load, because a key binding lives in no registry tag, and there are few enough
mapping contexts that the load costs nothing.

**A controller label is not a key**, and the input files repeat this rather than assume you know
it. A person says "the cross button"; the asset stores `Gamepad_FaceButton_Bottom`. That
translation is per label set and lives in the engine. A newer console can have no label set of its
own and use its predecessor's, and one label, "Gamepad X", resolves to **two different keys**
depending on which console's labels you read it under. Resolve the label set before resolving the label.

*MANIFEST.md* is the one file here that changes on every run, deliberately. It records the **artefact format** and the **plugin version** that wrote the set, alongside the engine version and the time, and a **coverage table naming which tiers this set contains**.

That table is there for one reason. A tier that writes nothing when it has nothing is
indistinguishable from a tier that does not exist, so every tier is emitted even when empty: a
count of **0** means the walk ran and found none, and a row reading **not in this set** means these
artefacts predate that tier and the question has not been asked yet. Those need different actions,
and without the table a reader cannot tell them apart. Everything else is byte-identical when regenerated from unchanged source, which is what makes the set committable: a diff means the code moved. The format row is what lets `/ue-memory-stack:doctor` tell a current set from one written before the shape changed - reading the files cannot, because an outdated set is still well formed.

The output is deterministic and contains no absolute paths, so commit it. It belongs next to the code it describes, it diffs sensibly, and a reviewer can see a replication condition change in the same pull request that changed it. *06-keeping-it-fresh.md* covers having CI produce it instead, and what you give up by not committing it.

All the index files are indexes on purpose. They started as single flat tables and grew past the point where anything could read them, so they're now one row per class with the detail in a small file beside it. Grep the index, read the one file it points at.

## Checking a run went well

The commandlet logs a summary. Pull it out of the project log:

```powershell
Select-String -Path D:\MyGame\Saved\Logs\MyGame.log -Pattern 'AgentMemoryDump:' | Select-Object -Last 8
```

You want something like:

```
AgentMemoryDump: modules=GameA,GameACore out=Docs/AgentMemory
AgentMemoryDump: wrote index.md and 232 class files
AgentMemoryDump: 506 Blueprints, 4073 C++ edges from graphs
AgentMemoryDump: done, 16 modules, 346 classes, 506 blueprints
```

Two numbers to sanity check against what you know about your own project. If **modules is 0** the plugin didn't load. If **Blueprints is 0** on a project that has some, they're in plugin content: plugin content mounts under `/<PluginName>/` rather than `/Game/`, and Game Feature plugins are the usual case. Both are in *troubleshooting.md*.

## When to re-run it

After any `UCLASS`, `UFUNCTION`, `UPROPERTY` or replication change, and after adding or removing Blueprints that call C++. In practice that means wiring it into whatever already runs after a build. *06-keeping-it-fresh.md* covers the ways a stale artefact hides from you, which is the failure worth designing against: a dump against a stale DLL succeeds, logs its usual summary, exits 0, and writes the old format.
